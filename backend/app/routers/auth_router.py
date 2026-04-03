from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import Agency, User
from app.schemas import LoginRequest, LoginResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account disabled")

    agency = db.query(Agency).filter(Agency.id == user.agency_id).first()
    token = create_access_token(user.id, user.role, user.agency_id)

    return LoginResponse(
        success=True,
        token=token,
        must_change_password=bool(user.must_change_password),
        user={
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "agent_name": user.agent_name,
            "agency_id": user.agency_id,
        },
        agency={
            "id": agency.id if agency else "",
            "code": agency.code if agency else "",
            "name": agency.name if agency else "",
            "slug": agency.slug if agency else "",
        },
    )


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    db.commit()
    return {"success": True, "message": "Password changed successfully"}


@router.get("/me")
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    agency = db.query(Agency).filter(Agency.id == user.agency_id).first()
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "agent_name": user.agent_name,
        "agency_id": user.agency_id,
        "is_active": user.is_active,
        "agency": {
            "id": agency.id if agency else "",
            "code": agency.code if agency else "",
            "name": agency.name if agency else "",
            "slug": agency.slug if agency else "",
        },
    }
