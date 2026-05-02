"""
Authentication service for CASSIE backend.

This module provides:
- Password hashing and verification
- JWT token generation and validation
- User authentication utilities
"""

import os
import secrets
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

# JWT settings
_WEAK_JWT_SECRETS = {
    "",
    "admin",
    "secret",
    "password",
    "your-secret-key-change-in-production",
    "change-me-in-production",
}


def _load_secret_key() -> str:
    configured_secret = os.getenv("JWT_SECRET_KEY", "")
    environment = os.getenv("CASSIE_ENV", os.getenv("ENVIRONMENT", "development")).lower()
    allow_insecure = os.getenv("CASSIE_ALLOW_INSECURE_DEFAULTS", "false").lower() in {"1", "true", "yes"}

    if configured_secret and configured_secret not in _WEAK_JWT_SECRETS and len(configured_secret) >= 32:
        return configured_secret

    if environment in {"prod", "production"} and not allow_insecure:
        raise RuntimeError("JWT_SECRET_KEY must be set to a strong unique value in production.")

    logger.warning(
        "JWT_SECRET_KEY is missing or weak; using an ephemeral development secret. "
        "Set JWT_SECRET_KEY to a stable 32+ character random value before deployment."
    )
    return secrets.token_urlsafe(48)


SECRET_KEY = _load_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours default
JOB_UPLOAD_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_JOB_UPLOAD_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days default


def hash_password(password: str) -> str:
    """
    Hash a plain text password using bcrypt.
    
    Args:
        password: Plain text password (will be truncated to 72 bytes if needed)
        
    Returns:
        str: Hashed password (bcrypt format)
    """
    # Bcrypt has a 72-byte limit, so truncate if necessary
    # This is safe because we're hashing, not storing the full password
    if isinstance(password, str):
        password_bytes = password.encode('utf-8')
        if len(password_bytes) > 72:
            password_bytes = password_bytes[:72]
    else:
        password_bytes = password
    
    # Generate salt and hash password
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain text password against a bcrypt hash.
    
    Args:
        plain_password: Plain text password to verify (will be truncated to 72 bytes if needed)
        hashed_password: Hashed password from database (bcrypt format)
        
    Returns:
        bool: True if password matches, False otherwise
    """
    try:
        # Bcrypt has a 72-byte limit, so truncate if necessary for verification
        if isinstance(plain_password, str):
            password_bytes = plain_password.encode('utf-8')
            if len(password_bytes) > 72:
                password_bytes = password_bytes[:72]
        else:
            password_bytes = plain_password
        
        # Verify password
        hashed_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception as e:
        logger.warning(f"Password verification error: {e}")
        return False


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Data to encode in the token (typically user_id and username)
        expires_delta: Optional expiration time delta
        
    Returns:
        str: Encoded JWT token
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Decode and validate a JWT access token.
    
    Args:
        token: JWT token string
        
    Returns:
        dict: Decoded token payload if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        return None


def get_token_expiration() -> datetime:
    """
    Get the default token expiration time.
    
    Returns:
        datetime: Expiration datetime
    """
    return datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)


def create_job_upload_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a scoped JWT token for queued job uploads and post-upload execution.

    Args:
        data: Token payload including user_id, username, and job_id
        expires_delta: Optional expiration time delta

    Returns:
        str: Encoded JWT token
    """
    to_encode = data.copy()
    to_encode["token_type"] = "job_upload_session"

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=JOB_UPLOAD_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_demo_token(session_id: str, demo_code_id: int) -> str:
    """
    Create a JWT demo session token for a public demo user.

    Demo tokens are stateless — no real user account is associated.
    They carry role="demo" and is_demo=True so backend dependencies
    can distinguish them from normal access tokens without a DB lookup.
    """
    from backend.api.utils.config_loader import get_config
    config = get_config()
    data = {
        "session_id": session_id,
        "role": "demo",
        "is_demo": True,
        "demo_code_id": demo_code_id,
        "token_type": "demo_session",
    }
    return create_access_token(
        data=data,
        expires_delta=timedelta(minutes=config.demo.session_ttl_minutes),
    )


def create_scoped_token(
    data: Dict[str, Any],
    *,
    token_type: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT token with an explicit token_type claim."""
    to_encode = data.copy()
    to_encode["token_type"] = token_type

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
