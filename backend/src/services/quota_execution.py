"""补招名额方案的异步领取、执行与幂等创建。"""

import logging
from datetime import timedelta
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from src.config.database import Session
from src.constants.enums import QuotaStatus
from src.domain.quota import make_signature, plan_quota
from src.models.quota import QuotaPlan
from src.models.source import Dataset
from src.services.audit import record
from src.services.quota_validation import normalize_quota_params
from src.utils.time import now

log = logging.getLogger(__name__)
LEASE_MINUTES = 3
MAX_ATTEMPTS = 3


def create_plan(db, dataset_id, name, raw_caps, raw_needs, actor):
    """同批次同上限并发提交时复用既有方案，不新增记录。"""
    dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise LookupError("找不到指定的数据批次")
    caps, needs = normalize_quota_params(raw_caps, raw_needs)
    signature = make_signature(dataset_id, caps, needs)
    existing = db.scalar(select(QuotaPlan).where(QuotaPlan.signature == signature).with_for_update())
    if existing:
        return existing, False
    plan = QuotaPlan(dataset_id=dataset_id, signature=signature, name=name,
                     channel_caps=caps, program_needs=needs, author=actor)
    db.add(plan)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(QuotaPlan).where(QuotaPlan.signature == signature))
        return existing, False
    record(db, actor, 'quota.queued', plan.id, dataset_id=dataset_id)
    return plan, True


def claim():
    stamp = now()
    with Session.begin() as db:
        query = select(QuotaPlan).where(or_(
            QuotaPlan.status == QuotaStatus.QUEUED,
            and_(QuotaPlan.status == QuotaStatus.RUNNING, QuotaPlan.lease_until < stamp)))
        job = db.scalar(query.order_by(QuotaPlan.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None
        if job.attempt >= MAX_ATTEMPTS:
            job.status = QuotaStatus.FAILED
            job.error = '后台进程多次中断，请重新发起补招分析'
            job.finished_at = stamp
            record(db, 'worker', 'quota.failed', job.id, reason=job.error)
            return None
        job.status = QuotaStatus.RUNNING
        job.attempt += 1
        job.lease_until = stamp + timedelta(minutes=LEASE_MINUTES)
        # 只读取发起时快照的批次与上限，中断续跑不随新提交改变口径。
        rows = db.get(Dataset, job.dataset_id).rows
        return job.id, job.attempt, rows, dict(job.channel_caps), dict(job.program_needs)


def execute(lease):
    job_id, attempt, rows, caps, needs = lease
    result = failure = None
    try:
        result = plan_quota(rows, caps, needs)
    except ValueError as error:
        failure = str(error)[:500]
    except Exception:
        log.exception('Quota plan %s failed', job_id)
        failure = '补招分配计算失败，请核对批次与上限后重试'
    with Session.begin() as db:
        job = db.get(QuotaPlan, job_id, with_for_update=True)
        if job.attempt != attempt or job.status != QuotaStatus.RUNNING:
            return
        job.lease_until = None
        job.finished_at = now()
        job.status = QuotaStatus.FAILED if failure else QuotaStatus.COMPLETE
        job.result = None if failure else result
        job.error = failure
        record(db, 'worker', f'quota.{job.status}', job.id, attempt=attempt, reason=failure)
