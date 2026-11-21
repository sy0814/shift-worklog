from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

ALGORITHM = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.access_token_hours)
    return jwt.encode({"sub": str(user.id), "exp": exp}, s.secret_key, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    err = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token",
                        headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
        uid = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise err
    user = db.get(User, uid)
    if user is None or not user.is_active:
        raise err
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


# ---- 图片地址签名：<img src> 带不了 Authorization 头，所以给每个文件一个限时签名 ----
FILE_TOKEN_HOURS = 12


def file_token(att_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=FILE_TOKEN_HOURS)
    return jwt.encode({"att": att_id, "exp": exp}, get_settings().secret_key + ":file",
                      algorithm=ALGORITHM)


def verify_file_token(token: str, att_id: int) -> bool:
    try:
        payload = jwt.decode(token, get_settings().secret_key + ":file", algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return False
    return payload.get("att") == att_id
