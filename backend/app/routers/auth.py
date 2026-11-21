from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import User
from ..schemas import MeUpdate, PasswordChange, TokenOut, UserOut
from ..security import create_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == form.username))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    audit.log(db, user_id=user.id, action="login", entity="user", entity_id=user.id)
    db.commit()
    return TokenOut(access_token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: MeUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit.log_changes(db, user, body.model_dump(exclude_none=True),
                      user_id=user.id, entity="user", entity_id=user.id)
    db.commit()
    return user


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChange, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "wrong old password")
    user.password_hash = hash_password(body.new_password)
    audit.log(db, user_id=user.id, action="change_password", entity="user", entity_id=user.id)
    db.commit()
