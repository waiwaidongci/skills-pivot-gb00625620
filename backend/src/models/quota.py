from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.constants.enums import QuotaStatus
from src.utils.time import now


class QuotaPlan(Base):
    """下月补招名额的内部分析方案。

    signature 由数据批次、渠道接待上限与项目待补人数规范化后哈希得到，
    配合唯一约束保证同批次同上限的并发重跑只落一个方案。
    """

    __tablename__ = 'quota_plans'
    __table_args__ = (UniqueConstraint('signature', name='uq_quota_plan_signature'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    signature: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default=QuotaStatus.QUEUED, index=True)
    # 发起时快照：中断续跑始终使用这批上限与这个批次，不随后续提交变化。
    channel_caps: Mapped[dict] = mapped_column(JSON)
    program_needs: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(String(500))
    attempt: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None]
    author: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None]
