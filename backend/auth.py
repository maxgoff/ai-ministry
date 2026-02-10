"""Authentication utilities for AI Ministry.

Provides password hashing, JWT token creation/verification,
and FastAPI dependencies for protecting endpoints.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import AUTH_ALGORITHM, AUTH_ACCESS_TOKEN_EXPIRE_MINUTES, AUTH_SECRET_KEY

# Password hashing context using bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token extraction from Authorization header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    Args:
        plain_password: The plain text password to verify
        hashed_password: The bcrypt hashed password to check against

    Returns:
        True if the password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt.

    Args:
        password: The plain text password to hash

    Returns:
        The bcrypt hashed password
    """
    return pwd_context.hash(password)


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        data: The payload data to encode in the token (typically {"sub": user_id})
        expires_delta: Optional custom expiration time. Defaults to
                       AUTH_ACCESS_TOKEN_EXPIRE_MINUTES from config.

    Returns:
        The encoded JWT token string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=AUTH_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, AUTH_SECRET_KEY, algorithm=AUTH_ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode a JWT token.

    Args:
        token: The JWT token string to verify

    Returns:
        The decoded token payload

    Raises:
        HTTPException: 401 error if token is invalid or expired
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        return payload
    except JWTError:
        raise credentials_exception


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """
    FastAPI dependency that extracts and validates the current user from the JWT token.

    This dependency can be added to any endpoint that requires authentication.
    It extracts the token from the Authorization header (Bearer scheme),
    validates it, and returns the user information.

    Args:
        token: The JWT token extracted from the Authorization header
               (automatically injected by FastAPI via oauth2_scheme)

    Returns:
        A dict containing user information from the token payload:
        - "sub": The user ID
        - Other claims from the token

    Raises:
        HTTPException: 401 error if:
            - No token provided
            - Token is invalid
            - Token is expired
            - Token missing required "sub" claim

    Usage:
        @app.get("/protected")
        async def protected_route(current_user: dict = Depends(get_current_user)):
            return {"user_id": current_user["sub"]}
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = verify_token(token)

    # Ensure the token has a subject (user_id)
    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    return payload
