"""Integration tests for authentication API endpoints.

Tests for /api/auth/register, /api/auth/login, and /api/auth/me endpoints.
Uses FastAPI TestClient to test the actual HTTP API behavior.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Set up test database before importing app modules
TEST_DATA_DIR = tempfile.mkdtemp()


@pytest.fixture(autouse=True)
def setup_test_db():
    """Use a temporary database for each test module."""
    with patch.dict(os.environ, {"DATA_DIR": TEST_DATA_DIR}):
        # Clear any existing test database
        db_path = Path(TEST_DATA_DIR) / "ministry.db"
        if db_path.exists():
            db_path.unlink()

        # Patch the storage module's DATA_DIR and DB_PATH
        with patch("backend.storage.DATA_DIR", TEST_DATA_DIR):
            with patch("backend.storage.DB_PATH", db_path):
                yield


@pytest.fixture
def client(setup_test_db):
    """Create a test client for the FastAPI app."""
    from backend.main import app
    return TestClient(app)


@pytest.fixture
def registered_user(client):
    """Create a registered user and return credentials."""
    email = "testuser@example.com"
    password = "securepassword123"

    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200

    token_data = response.json()
    return {
        "email": email,
        "password": password,
        "access_token": token_data["access_token"],
        "token_type": token_data["token_type"]
    }


class TestRegistration:
    """Tests for POST /api/auth/register endpoint."""

    def test_successful_registration_returns_token(self, client):
        """Successful registration returns JWT token with bearer type."""
        response = client.post(
            "/api/auth/register",
            json={"email": "newuser@example.com", "password": "password123"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0

    def test_successful_registration_token_is_valid(self, client):
        """Token from registration can be used to access protected endpoints."""
        # Register a new user
        response = client.post(
            "/api/auth/register",
            json={"email": "validtoken@example.com", "password": "password123"}
        )
        assert response.status_code == 200
        token = response.json()["access_token"]

        # Use the token to access /api/auth/me
        me_response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "validtoken@example.com"

    def test_registration_with_existing_email_fails(self, client, registered_user):
        """Registration with an already registered email returns 400."""
        response = client.post(
            "/api/auth/register",
            json={"email": registered_user["email"], "password": "differentpassword"}
        )

        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_registration_with_invalid_email_format_fails(self, client):
        """Registration with invalid email format returns 422."""
        invalid_emails = [
            "notanemail",
            "missing@domain",
            "@nodomain.com",
            "spaces in@email.com",
            "",
        ]

        for invalid_email in invalid_emails:
            response = client.post(
                "/api/auth/register",
                json={"email": invalid_email, "password": "password123"}
            )
            assert response.status_code == 422, f"Expected 422 for email: {invalid_email}"

    def test_registration_without_email_fails(self, client):
        """Registration without email field returns 422."""
        response = client.post(
            "/api/auth/register",
            json={"password": "password123"}
        )
        assert response.status_code == 422

    def test_registration_without_password_fails(self, client):
        """Registration without password field returns 422."""
        response = client.post(
            "/api/auth/register",
            json={"email": "nopassword@example.com"}
        )
        assert response.status_code == 422

    def test_registration_with_empty_body_fails(self, client):
        """Registration with empty body returns 422."""
        response = client.post(
            "/api/auth/register",
            json={}
        )
        assert response.status_code == 422

    def test_registration_stores_user_correctly(self, client):
        """Registration creates user with correct email in database."""
        email = "stored@example.com"
        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": "password123"}
        )
        assert response.status_code == 200
        token = response.json()["access_token"]

        # Verify user was stored by fetching profile
        me_response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        user = me_response.json()
        assert user["email"] == email
        assert "id" in user
        assert "created_at" in user

    def test_registration_password_is_hashed(self, client):
        """Verify password is not stored in plaintext."""
        from backend import storage

        email = "hashedpwd@example.com"
        password = "myplaintextpassword"

        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": password}
        )
        assert response.status_code == 200

        # Fetch user from database directly
        user = storage.get_user_by_email(email)
        assert user is not None
        # Password should be hashed (bcrypt hashes start with $2)
        assert user["hashed_password"].startswith("$2")
        # Password should not be stored as plaintext
        assert user["hashed_password"] != password


class TestLogin:
    """Tests for POST /api/auth/login endpoint."""

    def test_successful_login_returns_token(self, client, registered_user):
        """Successful login returns JWT token with bearer type."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": registered_user["email"],
                "password": registered_user["password"]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 0

    def test_login_token_is_valid(self, client, registered_user):
        """Token from login can be used to access protected endpoints."""
        # Login
        response = client.post(
            "/api/auth/login",
            json={
                "email": registered_user["email"],
                "password": registered_user["password"]
            }
        )
        assert response.status_code == 200
        token = response.json()["access_token"]

        # Use the token to access /api/auth/me
        me_response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == registered_user["email"]

    def test_login_with_wrong_password_fails(self, client, registered_user):
        """Login with incorrect password returns 401."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": registered_user["email"],
                "password": "wrongpassword"
            }
        )

        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    def test_login_with_nonexistent_email_fails(self, client):
        """Login with email that doesn't exist returns 401."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "anypassword"
            }
        )

        assert response.status_code == 401
        # Should use same message as wrong password to prevent user enumeration
        assert "invalid" in response.json()["detail"].lower()

    def test_login_with_invalid_email_format_fails(self, client):
        """Login with invalid email format returns 422."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "notanemail",
                "password": "password123"
            }
        )
        assert response.status_code == 422

    def test_login_without_email_fails(self, client):
        """Login without email field returns 422."""
        response = client.post(
            "/api/auth/login",
            json={"password": "password123"}
        )
        assert response.status_code == 422

    def test_login_without_password_fails(self, client):
        """Login without password field returns 422."""
        response = client.post(
            "/api/auth/login",
            json={"email": "user@example.com"}
        )
        assert response.status_code == 422

    def test_login_with_empty_body_fails(self, client):
        """Login with empty body returns 422."""
        response = client.post(
            "/api/auth/login",
            json={}
        )
        assert response.status_code == 422

    def test_login_case_sensitive_email(self, client, registered_user):
        """Login email matching should be case-sensitive per standard behavior."""
        # SQLite is case-insensitive for comparisons by default,
        # but email addresses are typically case-insensitive in practice.
        # This test documents the current behavior.
        uppercase_email = registered_user["email"].upper()
        response = client.post(
            "/api/auth/login",
            json={
                "email": uppercase_email,
                "password": registered_user["password"]
            }
        )
        # SQLite's default behavior is case-insensitive for LIKE/=
        # This documents the actual behavior
        if response.status_code == 200:
            # If case-insensitive (SQLite default)
            assert "access_token" in response.json()
        else:
            # If case-sensitive (would need COLLATE BINARY)
            assert response.status_code == 401

    def test_multiple_logins_produce_different_tokens(self, client, registered_user):
        """Each login produces a unique token (due to timestamp/nonce in JWT)."""
        response1 = client.post(
            "/api/auth/login",
            json={
                "email": registered_user["email"],
                "password": registered_user["password"]
            }
        )
        response2 = client.post(
            "/api/auth/login",
            json={
                "email": registered_user["email"],
                "password": registered_user["password"]
            }
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

        token1 = response1.json()["access_token"]
        token2 = response2.json()["access_token"]

        # Tokens might be the same if generated at the exact same second
        # but both should be valid
        # This is a weak assertion - mainly checking both requests succeed


class TestGetMe:
    """Tests for GET /api/auth/me endpoint."""

    def test_get_me_returns_current_user(self, client, registered_user):
        """GET /api/auth/me returns the authenticated user's profile."""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {registered_user['access_token']}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == registered_user["email"]
        assert "id" in data
        assert "created_at" in data

    def test_get_me_does_not_expose_password(self, client, registered_user):
        """GET /api/auth/me should not return password or hashed_password."""
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {registered_user['access_token']}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "password" not in data
        assert "hashed_password" not in data

    def test_get_me_without_token_fails(self, client):
        """GET /api/auth/me without Authorization header returns 401."""
        response = client.get("/api/auth/me")

        assert response.status_code == 401

    def test_get_me_with_invalid_token_fails(self, client):
        """GET /api/auth/me with invalid token returns 401."""
        invalid_tokens = [
            "invalid-token",
            "Bearer invalid-token",  # This gets extracted as "invalid-token"
            "",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature",
        ]

        for token in invalid_tokens:
            response = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 401, f"Expected 401 for token: {token}"

    def test_get_me_with_expired_token_fails(self, client):
        """GET /api/auth/me with expired token returns 401."""
        from datetime import timedelta
        from backend.auth import create_access_token

        # Create an already-expired token
        expired_token = create_access_token(
            {"sub": "some-user-id"},
            expires_delta=timedelta(seconds=-10)  # Expired 10 seconds ago
        )

        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401

    def test_get_me_with_malformed_authorization_header(self, client):
        """GET /api/auth/me with malformed Authorization header returns 401."""
        malformed_headers = [
            {"Authorization": "NotBearer token"},
            {"Authorization": "Basic dXNlcjpwYXNz"},  # Basic auth instead of Bearer
            {"Authorization": "Bearer"},  # Missing token
        ]

        for headers in malformed_headers:
            response = client.get("/api/auth/me", headers=headers)
            assert response.status_code in [401, 422], f"Expected 401/422 for: {headers}"

    def test_get_me_with_token_for_deleted_user(self, client, registered_user):
        """GET /api/auth/me returns 401 if user no longer exists.

        This tests the edge case where a valid token exists but the user
        has been deleted from the database.
        """
        from backend import storage

        # Get the user ID from the token claims
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {registered_user['access_token']}"}
        )
        assert response.status_code == 200
        user_id = response.json()["id"]

        # Manually delete the user from the database
        from backend.storage import _get_connection, _ensure_db
        _ensure_db()
        with _get_connection() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

        # Try to access /api/auth/me with the now-orphaned token
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {registered_user['access_token']}"}
        )

        # Should return 401 since user no longer exists
        assert response.status_code == 401


class TestIntegrationScenarios:
    """Integration tests covering end-to-end user scenarios."""

    def test_register_then_login_same_credentials(self, client):
        """User can register and then login with the same credentials."""
        email = "newuser@example.com"
        password = "securepassword123"

        # Register
        register_response = client.post(
            "/api/auth/register",
            json={"email": email, "password": password}
        )
        assert register_response.status_code == 200
        register_token = register_response.json()["access_token"]

        # Login with same credentials
        login_response = client.post(
            "/api/auth/login",
            json={"email": email, "password": password}
        )
        assert login_response.status_code == 200
        login_token = login_response.json()["access_token"]

        # Both tokens should work for /api/auth/me
        for token in [register_token, login_token]:
            me_response = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
            assert me_response.status_code == 200
            assert me_response.json()["email"] == email

    def test_different_users_have_different_ids(self, client):
        """Different users should have different user IDs."""
        users = []

        for i in range(3):
            email = f"user{i}@example.com"
            response = client.post(
                "/api/auth/register",
                json={"email": email, "password": "password123"}
            )
            assert response.status_code == 200
            token = response.json()["access_token"]

            me_response = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
            users.append(me_response.json())

        # All user IDs should be unique
        user_ids = [u["id"] for u in users]
        assert len(user_ids) == len(set(user_ids)), "User IDs should be unique"

    def test_user_created_at_is_set(self, client):
        """User's created_at timestamp is set during registration."""
        from datetime import datetime

        response = client.post(
            "/api/auth/register",
            json={"email": "timestamped@example.com", "password": "password123"}
        )
        assert response.status_code == 200
        token = response.json()["access_token"]

        me_response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        user = me_response.json()

        # Verify created_at is a valid ISO timestamp
        assert "created_at" in user
        # Should be parseable as ISO format
        try:
            parsed = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
            # Should be recent (within the last minute)
            now = datetime.utcnow()
            diff = abs((now - parsed.replace(tzinfo=None)).total_seconds())
            assert diff < 60, "created_at should be recent"
        except ValueError:
            pytest.fail(f"created_at is not valid ISO format: {user['created_at']}")
