"""「系统设置 → 访问地址」（仅系统管理员）：看现在的地址、改成新的 IP / 电脑名（见 app/server_address.py）。"""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, server_address as sa
from ..db import get_db
from ..models import User
from ..security import require_admin

router = APIRouter(prefix="/api/server-address", tags=["server-address"])


class AddressOut(BaseModel):
    hosts: str  # 现在的地址，例如 "192.168.1.50, worklog"
    pending: str  # 已提交、还没生效的新地址
    candidates: list[str]  # 这台服务器自己的 IP 和电脑名
    status: dict | None  # 上一次在网页上改的结果
    windows: bool  # 只有 Windows 服务器上能在网页里改


class AddressIn(BaseModel):
    hosts: str = Field(max_length=300)


def _out() -> AddressOut:
    return AddressOut(hosts=sa.current(), pending=sa.pending(), candidates=sa.candidates(), status=sa.status(),
                      windows=os.name == "nt")


@router.get("", response_model=AddressOut)
def get_address(_: User = Depends(require_admin)):
    return _out()


@router.put("", response_model=AddressOut)
def set_address(body: AddressIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        hosts = sa.normalize(body.hosts)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    old = sa.current()
    try:
        sa.request(hosts)
    except (RuntimeError, OSError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"address: {e}") from e
    audit.log(db, user_id=admin.id, action="update", entity="setting", entity_id="server_address",
              field="site_hosts", old=old, new=hosts)
    db.commit()
    return _out()
