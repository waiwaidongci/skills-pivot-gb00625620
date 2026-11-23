from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import connection
from src.constants.enums import Role
from src.controllers.auth import allow
from src.models.quota import QuotaPlan
from src.schemas.requests import QuotaPlanRequest
from src.services.quota_execution import create_plan
from src.utils.time import iso
from src.utils.wakeup import wake

router = APIRouter(prefix='/quota-plans')


def _summary(item):
    return {
        'id': item.id, 'dataset_id': item.dataset_id, 'name': item.name, 'status': item.status,
        'author': item.author, 'signature': item.signature, 'error': item.error,
        'created_at': iso(item.created_at), 'finished_at': iso(item.finished_at),
        'channel_caps': item.channel_caps, 'program_needs': item.program_needs,
    }


@router.get('')
def index(db: Session = Depends(connection), actor=Depends(allow(Role.ADMIN, Role.ANALYST))):
    query = select(QuotaPlan).order_by(QuotaPlan.id.desc()).limit(100)
    return [_summary(item) for item in db.scalars(query)]


@router.post('', status_code=202)
def create(body: QuotaPlanRequest, db: Session = Depends(connection),
           actor=Depends(allow(Role.ADMIN, Role.ANALYST))):
    try:
        item, created = create_plan(db, body.dataset_id, body.name,
                                    body.channel_caps, body.program_needs, actor.username)
        db.commit()
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    if created:
        wake()
    return {**_summary(item), 'reused': not created,
            'result': item.result, 'attempt': item.attempt}


@router.get('/{plan_id}')
def detail(plan_id: int, db: Session = Depends(connection),
           actor=Depends(allow(Role.ADMIN, Role.ANALYST))):
    item = db.get(QuotaPlan, plan_id)
    if not item:
        raise HTTPException(404, '找不到该补招方案')
    return {**_summary(item), 'result': item.result, 'attempt': item.attempt}
