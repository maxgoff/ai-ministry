"""Tests for backend/auth.py authentication utility functions.

Unit tests for password hashing, JWT token creation/verification,
and edge cases like expired and invalid tokens.
"""

import time
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from jose import jwt

from backend.auth import (
    create_access_token,
    get_password_hash,
    verify_password,
    verify_token,
)
from backend.config import AUTH_ALGORITHM, AUTH_SECRET_KEY


class TestPasswordHashing:
    """Tests for password hashing and verification functions."""

    def test_get_password_hash_returns_bcrypt_hash(self):
        """get_password_hash should return a bcrypt hash string."""
        password = "testpassword123"
        hashed = get_password_hash(password)

        # bcrypt hashes start with $2b$ (or $2a$, $2y$)
        assert hashed.startswith("$2")
        assert len(hashed) == 60  # bcrypt hashes are 60 chars

    def test_get_password_hash_different_each_time(self):
        """Same password should produce different hashes (due to salt)."""
        password = "testpassword123"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        assert hash1 != hash2

    def test_verify_password_correct_password(self):
        """verify_password returns True for correct password."""
        password = "correctpassword"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_wrong_password(self):
        """verify_password returns False for wrong password."""
        password = "correctpassword"
        hashed = get_password_hash(password)

        assert verify_password("wrongpassword", hashed) is False

    def test_verify_password_case_sensitive(self):
        """verify_password is case sensitive."""
        password = "TestPassword"
        hashed = get_password_hash(password)

        assert verify_password("testpassword", hashed) is False
        assert verify_password("TESTPASSWORD", hashed) is False
        assert verify_password("TestPassword", hashed) is True

    def test_verify_password_empty_string(self):
        """verify_password works with empty string password."""
        password = ""
        hashed = get_password_hash(password)

        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False

    def test_verify_password_special_characters(self):
        """verify_password works with special characters."""
        password = "p@$$w0rd!#$%^&*()"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True
        assert verify_password("p@$$w0rd", hashed) is False

    def test_verify_password_unicode(self):
        """verify_password works with unicode characters."""
        password = "пароль密码🔐"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True
        assert verify_password("password", hashed) is False


class TestJWTTokenCreation:
    """Tests for JWT token creation function."""

    def test_create_access_token_returns_string(self):
        """create_access_token returns a JWT string."""
        token = create_access_token({"sub": "user123"})

        assert isinstance(token, str)
        # JWT has 3 parts separated by dots
        assert token.count(".") == 2

    def test_create_access_token_contains_subject(self):
        """Token payload contains the subject claim."""
        user_id = "user-uuid-123"
        token = create_access_token({"sub": user_id})

        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        assert payload["sub"] == user_id

    def test_create_access_token_contains_expiration(self):
        """Token payload contains the exp claim."""
        token = create_access_token({"sub": "user123"})

        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        assert "exp" in payload
        assert isinstance(payload["exp"], int)

    def test_create_access_token_custom_expiration(self):
        """create_access_token respects custom expiration delta."""
        # Very short expiration
        token = create_access_token(
            {"sub": "user123"},
            expires_delta=timedelta(seconds=10)
        )

        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        # exp should be approximately 10 seconds from now
        now = time.time()
        assert payload["exp"] < now + 15  # within 15 seconds
        assert payload["exp"] > now - 5  # not in the past

    def test_create_access_token_preserves_additional_data(self):
        """Token preserves additional data beyond just 'sub'."""
        data = {
            "sub": "user123",
            "email": "test@example.com",
            "role": "admin"
        }
        token = create_access_token(data)

        payload = jwt.decode(token, AUTH_SECRET_KEY, algorithms=[AUTH_ALGORITHM])
        assert payload["sub"] == "user123"
        assert payload["email"] == "test@example.com"
        assert payload["role"] == "admin"

    def test_create_access_token_does_not_modify_original_data(self):
        """create_access_token should not modify the input dict."""
        data = {"sub": "user123"}
        original_keys = set(data.keys())

        create_access_token(data)

        # exp should not be added to original dict
        assert set(data.keys()) == original_keys


class TestJWTTokenVerification:
    """Tests for JWT token verification function."""

    def test_verify_token_valid_token(self):
        """verify_token returns payload for valid token."""
        user_id = "user-uuid-456"
        token = create_access_token({"sub": user_id})

        payload = verify_token(token)

        assert payload["sub"] == user_id
        assert "exp" in payload

    def test_verify_token_returns_all_claims(self):
        """verify_token returns all claims from the token."""
        data = {
            "sub": "user123",
            "custom_claim": "custom_value"
        }
        token = create_access_token(data)

        payload = verify_token(token)

        assert payload["sub"] == "user123"
        assert payload["custom_claim"] == "custom_value"


class TestExpiredTokenHandling:
    """Tests for handling expired JWT tokens."""

    def test_verify_token_expired_raises_401(self):
        """verify_token raises 401 HTTPException for expired token."""
        # Create a token that expires immediately
        token = create_access_token(
            {"sub": "user123"},
            expires_delta=timedelta(seconds=-1)  # Already expired
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Could not validate credentials"
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    def test_verify_token_very_old_token(self):
        """verify_token rejects tokens with very old expiration."""
        # Create a token that expired a long time ago
        token = create_access_token(
            {"sub": "user123"},
            expires_delta=timedelta(days=-365)  # Expired a year ago
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)

        assert exc_info.value.status_code == 401


class TestInvalidTokenHandling:
    """Tests for handling invalid JWT tokens."""

    def test_verify_token_malformed_token(self):
        """verify_token raises 401 for malformed token string."""
        malformed_tokens = [
            "not-a-jwt-token",
            "abc.def",
            "abc.def.ghi.jkl",
            "",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",  # Only header
        ]

        for token in malformed_tokens:
            with pytest.raises(HTTPException) as exc_info:
                verify_token(token)

            assert exc_info.value.status_code == 401
            assert exc_info.value.detail == "Could not validate credentials"

    def test_verify_token_wrong_secret_key(self):
        """verify_token raises 401 for token signed with wrong key."""
        # Create a token with a different secret key
        wrong_key = "wrong-secret-key-definitely-not-correct"
        token = jwt.encode(
            {"sub": "user123", "exp": time.time() + 3600},
            wrong_key,
            algorithm=AUTH_ALGORITHM
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)

        assert exc_info.value.status_code == 401

    def test_verify_token_wrong_algorithm(self):
        """verify_token raises 401 for token with wrong algorithm."""
        # Create a token with HS384 instead of HS256
        token = jwt.encode(
            {"sub": "user123", "exp": time.time() + 3600},
            AUTH_SECRET_KEY,
            algorithm="HS384"
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)

        assert exc_info.value.status_code == 401

    def test_verify_token_tampered_payload(self):
        """verify_token raises 401 for tampered token."""
        # Create a valid token
        token = create_access_token({"sub": "user123"})

        # Tamper with the payload (middle part)
        parts = token.split(".")
        # Modify the payload to be something different
        parts[1] = "eyJzdWIiOiJoYWNrZXIiLCJleHAiOjk5OTk5OTk5OTl9"  # {"sub": "hacker", "exp": 9999999999}
        tampered_token = ".".join(parts)

        with pytest.raises(HTTPException) as exc_info:
            verify_token(tampered_token)

        assert exc_info.value.status_code == 401

    def test_verify_token_none_algorithm_attack(self):
        """verify_token rejects tokens using 'none' algorithm (security)."""
        # Attempt a "none" algorithm attack
        header = {"alg": "none", "typ": "JWT"}
        payload = {"sub": "attacker", "exp": time.time() + 3600}

        # Manually construct a token with no signature
        import base64
        import json

        def b64url(data):
            return base64.urlsafe_b64encode(
                json.dumps(data).encode()
            ).rstrip(b"=").decode()

        fake_token = f"{b64url(header)}.{b64url(payload)}."

        with pytest.raises(HTTPException) as exc_info:
            verify_token(fake_token)

        assert exc_info.value.status_code == 401

    def test_verify_token_missing_exp_claim(self):
        """verify_token handles token without exp claim."""
        # Create a token without expiration (though our create_access_token always adds it)
        # We need to manually create one without exp
        token = jwt.encode(
            {"sub": "user123"},  # No exp claim
            AUTH_SECRET_KEY,
            algorithm=AUTH_ALGORITHM
        )

        # python-jose should accept tokens without exp by default
        # The function should return the payload without error
        payload = verify_token(token)
        assert payload["sub"] == "user123"


class TestEdgeCases:
    """Edge cases and boundary conditions for auth functions."""

    def test_very_long_password(self):
        """Verify bcrypt handles very long passwords.

        Note: bcrypt truncates passwords at 72 bytes for hashing.
        This is expected behavior and a known limitation of bcrypt.
        Passwords longer than 72 bytes will match if the first 72 bytes are equal.
        """
        long_password = "a" * 1000
        hashed = get_password_hash(long_password)

        # The password should verify (bcrypt truncates at 72 bytes)
        assert verify_password(long_password, hashed) is True
        # Passwords with same first 72 bytes will match (bcrypt limitation)
        assert verify_password("a" * 72, hashed) is True
        # Different password should fail
        assert verify_password("b" * 72, hashed) is False

    def test_token_with_complex_payload(self):
        """Token handles complex payload structures."""
        complex_data = {
            "sub": "user-uuid",
            "permissions": ["read", "write", "admin"],
            "metadata": {"department": "engineering", "level": 5}
        }
        token = create_access_token(complex_data)

        payload = verify_token(token)
        assert payload["sub"] == "user-uuid"
        assert payload["permissions"] == ["read", "write", "admin"]
        assert payload["metadata"]["department"] == "engineering"

    def test_password_with_null_bytes_rejected(self):
        """Verify bcrypt rejects passwords with null bytes (security feature).

        bcrypt explicitly rejects NULL bytes in passwords because many backends
        silently truncate at the first NULL, which would be a security issue.
        """
        from passlib.exc import PasswordValueError

        password_with_null = "pass\x00word"

        # bcrypt should reject passwords containing null bytes
        with pytest.raises(PasswordValueError):
            get_password_hash(password_with_null)

    def test_create_token_with_empty_dict(self):
        """create_access_token works with empty data dict."""
        token = create_access_token({})

        payload = verify_token(token)
        assert "exp" in payload
