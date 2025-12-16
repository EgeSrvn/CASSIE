from datetime import datetime, timedelta
import os
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from backend.api.database.db_init import Base


# use bcrypt_sha256 to avoid bcrypt's 72-byte limit (it hashes the password with sha256 before applying bcrypt)
pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))


class User(Base):
  __tablename__ = "users"
  __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

  id = Column(Integer, primary_key=True, index=True)
  email = Column(String(255), nullable=False, unique=True, index=True)
  password_hash = Column(String(255), nullable=False)
  created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


def hash_password(password: str) -> str:
  return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
  return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str) -> str:
  expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRES_MINUTES)
  to_encode = {"sub": subject, "exp": expire}
  return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
  try:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    return payload.get("sub")
  except JWTError:
    return None


# Pydantic schemas


class UserCreate(BaseModel):
  email: EmailStr
  password: str


class UserLogin(BaseModel):
  email: EmailStr
  password: str


class UserRead(BaseModel):
  id: int
  email: EmailStr
  created_at: datetime

  class Config:
    from_attributes = True


class TokenResponse(BaseModel):
  access_token: str
  token_type: str = "bearer"
  user: UserRead


