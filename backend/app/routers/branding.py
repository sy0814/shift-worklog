"""系统名称（三种语言，可只填一种；不填的语言用默认名称）。读取不需要登录（登录页要显示），修改仅管理员。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import AppSetting, User
from ..security import require_admin

router = APIRouter(prefix="/api/branding", tags=["settings"])
KEY = "app_name"


class Branding(BaseModel):
    zh: str = Field(default="", max_length=40)
    sr: str = Field(default="", max_length=40)
    en: str = Field(default="", max_length=40)


def _get(db: Session) -> Branding:
    row = db.get(AppSetting, KEY)
    return Branding(**(row.value if row and isinstance(row.value, dict) else {}))


@router.get("", response_model=Branding)
def get_branding(db: Session = Depends(get_db)):
    return _get(db)


@router.put("", response_model=Branding)
def put_branding(body: Branding, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    old = _get(db)
    new = Branding(**{k: v.strip() for k, v in body.model_dump().items()})
    if new != old:
        row = db.get(AppSetting, KEY)
        if row is None:
            db.add(AppSetting(key=KEY, value=new.model_dump()))
        else:
            row.value = new.model_dump()
        audit.log(db, user_id=admin.id, action="update", entity="setting", entity_id=KEY,
                  field=KEY, old=old.model_dump(), new=new.model_dump())
        db.commit()
    return new
