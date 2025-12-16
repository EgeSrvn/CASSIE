from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.api.database.db_init import get_db
from backend.api.models.user_model import (
  User,
  UserCreate,
  UserLogin,
  UserRead,
  TokenResponse,
  create_access_token,
  hash_password,
  verify_password,
  decode_access_token,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
  token: str = Depends(oauth2_scheme),
  db: Session = Depends(get_db),
) -> User:
  email = decode_access_token(token)
  if not email:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
  user = db.query(User).filter(User.email == email).first()
  if not user:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
  return user


@router.post("/register", response_model=TokenResponse)
def register(payload: UserCreate, db: Session = Depends(get_db)):
  existing = db.query(User).filter(User.email == payload.email).first()
  if existing:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

  user = User(
    email=payload.email,
    password_hash=hash_password(payload.password),
  )
  db.add(user)
  db.commit()
  db.refresh(user)

  token = create_access_token(user.email)
  return TokenResponse(
    access_token=token,
    user=UserRead.model_validate(user),
  )


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
  user = db.query(User).filter(User.email == payload.email).first()
  if not user or not verify_password(payload.password, user.password_hash):
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

  token = create_access_token(user.email)
  return TokenResponse(
    access_token=token,
    user=UserRead.model_validate(user),
  )


