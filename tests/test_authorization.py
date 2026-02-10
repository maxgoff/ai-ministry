"""Integration tests for authorization enforcement on protected endpoints.

Tests that verify:
- Unauthenticated requests return 401
- Users cannot access other users' conversations (IDOR protection)
- Users can only list their own conversations
- IDOR attacks are prevented (accessing by ID without ownership)
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
def user1(client):
    """Create first test user and return credentials with token."""
    email = "user1@example.com"
    password = "password123"

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
        "headers": {"Authorization": f"Bearer {token_data['access_token']}"}
    }


@pytest.fixture
def user2(client):
    """Create second test user and return credentials with token."""
    email = "user2@example.com"
    password = "password456"

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
        "headers": {"Authorization": f"Bearer {token_data['access_token']}"}
    }


@pytest.fixture
def user1_conversation(client, user1):
    """Create a conversation for user1."""
    response = client.post(
        "/api/conversations",
        json={},
        headers=user1["headers"]
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def user2_conversation(client, user2):
    """Create a conversation for user2."""
    response = client.post(
        "/api/conversations",
        json={},
        headers=user2["headers"]
    )
    assert response.status_code == 200
    return response.json()


class TestUnauthenticatedAccess:
    """Tests verifying that unauthenticated requests return 401."""

    def test_list_conversations_requires_auth(self, client):
        """GET /api/conversations returns 401 without authentication."""
        response = client.get("/api/conversations")
        assert response.status_code == 401

    def test_create_conversation_requires_auth(self, client):
        """POST /api/conversations returns 401 without authentication."""
        response = client.post("/api/conversations", json={})
        assert response.status_code == 401

    def test_get_conversation_requires_auth(self, client, user1, user1_conversation):
        """GET /api/conversations/{id} returns 401 without authentication."""
        conversation_id = user1_conversation["id"]
        response = client.get(f"/api/conversations/{conversation_id}")
        assert response.status_code == 401

    def test_send_message_requires_auth(self, client, user1, user1_conversation):
        """POST /api/conversations/{id}/message returns 401 without authentication."""
        conversation_id = user1_conversation["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/message",
            json={"content": "Test message"}
        )
        assert response.status_code == 401

    def test_send_message_stream_requires_auth(self, client, user1, user1_conversation):
        """POST /api/conversations/{id}/message/stream returns 401 without authentication."""
        conversation_id = user1_conversation["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/message/stream",
            json={"content": "Test message"}
        )
        assert response.status_code == 401

    def test_export_markdown_requires_auth(self, client, user1, user1_conversation):
        """GET /api/conversations/{id}/export/markdown returns 401 without authentication."""
        conversation_id = user1_conversation["id"]
        response = client.get(f"/api/conversations/{conversation_id}/export/markdown")
        assert response.status_code == 401

    def test_export_pdf_requires_auth(self, client, user1, user1_conversation):
        """GET /api/conversations/{id}/export/pdf returns 401 without authentication."""
        conversation_id = user1_conversation["id"]
        response = client.get(f"/api/conversations/{conversation_id}/export/pdf")
        assert response.status_code == 401

    def test_models_health_requires_auth(self, client):
        """GET /api/models/health returns 401 without authentication."""
        response = client.get("/api/models/health")
        assert response.status_code == 401


class TestInvalidTokenAccess:
    """Tests verifying that invalid tokens are rejected with 401."""

    def test_list_conversations_invalid_token(self, client):
        """GET /api/conversations returns 401 with invalid token."""
        response = client.get(
            "/api/conversations",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    def test_create_conversation_invalid_token(self, client):
        """POST /api/conversations returns 401 with invalid token."""
        response = client.post(
            "/api/conversations",
            json={},
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    def test_get_conversation_invalid_token(self, client, user1, user1_conversation):
        """GET /api/conversations/{id} returns 401 with invalid token."""
        conversation_id = user1_conversation["id"]
        response = client.get(
            f"/api/conversations/{conversation_id}",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    def test_send_message_invalid_token(self, client, user1, user1_conversation):
        """POST /api/conversations/{id}/message returns 401 with invalid token."""
        conversation_id = user1_conversation["id"]
        response = client.post(
            f"/api/conversations/{conversation_id}/message",
            json={"content": "Test message"},
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401

    def test_models_health_invalid_token(self, client):
        """GET /api/models/health returns 401 with invalid token."""
        response = client.get(
            "/api/models/health",
            headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401


class TestExpiredTokenAccess:
    """Tests verifying that expired tokens are rejected with 401."""

    def test_list_conversations_expired_token(self, client):
        """GET /api/conversations returns 401 with expired token."""
        from datetime import timedelta
        from backend.auth import create_access_token

        expired_token = create_access_token(
            {"sub": "some-user-id"},
            expires_delta=timedelta(seconds=-10)  # Already expired
        )

        response = client.get(
            "/api/conversations",
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401

    def test_create_conversation_expired_token(self, client):
        """POST /api/conversations returns 401 with expired token."""
        from datetime import timedelta
        from backend.auth import create_access_token

        expired_token = create_access_token(
            {"sub": "some-user-id"},
            expires_delta=timedelta(seconds=-10)
        )

        response = client.post(
            "/api/conversations",
            json={},
            headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert response.status_code == 401


class TestUserConversationIsolation:
    """Tests verifying users can only see their own conversations."""

    def test_list_conversations_shows_only_own(self, client, user1, user2):
        """Each user only sees their own conversations in list."""
        # Create conversations for user1
        for i in range(3):
            client.post("/api/conversations", json={}, headers=user1["headers"])

        # Create conversations for user2
        for i in range(2):
            client.post("/api/conversations", json={}, headers=user2["headers"])

        # User1 should only see their 3 conversations
        response1 = client.get("/api/conversations", headers=user1["headers"])
        assert response1.status_code == 200
        assert len(response1.json()) == 3

        # User2 should only see their 2 conversations
        response2 = client.get("/api/conversations", headers=user2["headers"])
        assert response2.status_code == 200
        assert len(response2.json()) == 2

    def test_list_conversations_empty_for_new_user(self, client, user1):
        """New user sees empty conversation list."""
        response = client.get("/api/conversations", headers=user1["headers"])
        assert response.status_code == 200
        assert response.json() == []

    def test_created_conversation_appears_in_user_list(self, client, user1):
        """Newly created conversation appears in user's list."""
        # Create conversation
        create_response = client.post(
            "/api/conversations",
            json={},
            headers=user1["headers"]
        )
        assert create_response.status_code == 200
        created_id = create_response.json()["id"]

        # Check it appears in list
        list_response = client.get("/api/conversations", headers=user1["headers"])
        assert list_response.status_code == 200
        conversations = list_response.json()
        assert len(conversations) == 1
        assert conversations[0]["id"] == created_id

    def test_user_does_not_see_other_users_conversations(self, client, user1, user2):
        """User cannot see conversations created by other users."""
        # Create conversation as user1
        create_response = client.post(
            "/api/conversations",
            json={},
            headers=user1["headers"]
        )
        assert create_response.status_code == 200
        user1_conv_id = create_response.json()["id"]

        # User2 should not see user1's conversation
        list_response = client.get("/api/conversations", headers=user2["headers"])
        assert list_response.status_code == 200
        conversations = list_response.json()

        # Verify user1's conversation is not in user2's list
        conv_ids = [c["id"] for c in conversations]
        assert user1_conv_id not in conv_ids


class TestIDORPrevention:
    """Tests verifying IDOR attacks are prevented.

    IDOR (Insecure Direct Object Reference) attacks occur when an attacker
    can access resources by guessing/iterating IDs without proper authorization.
    These tests verify that accessing another user's resources by ID is blocked.
    """

    def test_get_other_users_conversation_returns_404(
        self, client, user1, user2, user1_conversation
    ):
        """Accessing another user's conversation by ID returns 404."""
        conversation_id = user1_conversation["id"]

        # User2 tries to access user1's conversation
        response = client.get(
            f"/api/conversations/{conversation_id}",
            headers=user2["headers"]
        )

        # Should return 404 (not 403) to prevent enumeration
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_send_message_other_users_conversation_returns_404(
        self, client, user1, user2, user1_conversation
    ):
        """Sending message to another user's conversation returns 404."""
        conversation_id = user1_conversation["id"]

        # User2 tries to send message to user1's conversation
        response = client.post(
            f"/api/conversations/{conversation_id}/message",
            json={"content": "Unauthorized message"},
            headers=user2["headers"]
        )

        assert response.status_code == 404

    def test_stream_message_other_users_conversation_returns_404(
        self, client, user1, user2, user1_conversation
    ):
        """Streaming message to another user's conversation returns 404."""
        conversation_id = user1_conversation["id"]

        # User2 tries to stream message to user1's conversation
        response = client.post(
            f"/api/conversations/{conversation_id}/message/stream",
            json={"content": "Unauthorized message"},
            headers=user2["headers"]
        )

        assert response.status_code == 404

    def test_export_markdown_other_users_conversation_returns_404(
        self, client, user1, user2, user1_conversation
    ):
        """Exporting another user's conversation as markdown returns 404."""
        conversation_id = user1_conversation["id"]

        # User2 tries to export user1's conversation
        response = client.get(
            f"/api/conversations/{conversation_id}/export/markdown",
            headers=user2["headers"]
        )

        assert response.status_code == 404

    def test_export_pdf_other_users_conversation_returns_404(
        self, client, user1, user2, user1_conversation
    ):
        """Exporting another user's conversation as PDF returns 404."""
        conversation_id = user1_conversation["id"]

        # User2 tries to export user1's conversation as PDF
        response = client.get(
            f"/api/conversations/{conversation_id}/export/pdf",
            headers=user2["headers"]
        )

        assert response.status_code == 404

    def test_nonexistent_conversation_returns_404(self, client, user1):
        """Accessing non-existent conversation returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        response = client.get(
            f"/api/conversations/{fake_id}",
            headers=user1["headers"]
        )

        assert response.status_code == 404

    def test_same_response_for_nonexistent_and_unauthorized(
        self, client, user1, user2, user1_conversation
    ):
        """Same error response for non-existent and unauthorized access.

        This prevents attackers from distinguishing between:
        1. Conversation exists but belongs to another user
        2. Conversation doesn't exist at all

        Both should return identical 404 responses.
        """
        fake_id = "00000000-0000-0000-0000-000000000000"
        real_id = user1_conversation["id"]

        # Access non-existent conversation
        nonexistent_response = client.get(
            f"/api/conversations/{fake_id}",
            headers=user1["headers"]
        )

        # Access real conversation as wrong user
        unauthorized_response = client.get(
            f"/api/conversations/{real_id}",
            headers=user2["headers"]
        )

        # Both should return 404 with same message
        assert nonexistent_response.status_code == 404
        assert unauthorized_response.status_code == 404
        assert nonexistent_response.json() == unauthorized_response.json()


class TestOwnerCanAccessOwnConversations:
    """Tests verifying owners can access their own conversations."""

    def test_owner_can_get_own_conversation(self, client, user1, user1_conversation):
        """Owner can access their own conversation by ID."""
        conversation_id = user1_conversation["id"]

        response = client.get(
            f"/api/conversations/{conversation_id}",
            headers=user1["headers"]
        )

        assert response.status_code == 200
        assert response.json()["id"] == conversation_id

    def test_owner_can_export_own_conversation_markdown(
        self, client, user1, user1_conversation
    ):
        """Owner can export their own conversation as markdown."""
        conversation_id = user1_conversation["id"]

        response = client.get(
            f"/api/conversations/{conversation_id}/export/markdown",
            headers=user1["headers"]
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"

    def test_owner_can_export_own_conversation_pdf(
        self, client, user1, user1_conversation
    ):
        """Owner can export their own conversation as PDF (if fpdf2 is installed)."""
        conversation_id = user1_conversation["id"]

        response = client.get(
            f"/api/conversations/{conversation_id}/export/pdf",
            headers=user1["headers"]
        )

        # Should be 200 if fpdf2 is installed, 501 if not
        assert response.status_code in [200, 501]
        if response.status_code == 200:
            assert response.headers["content-type"] == "application/pdf"


class TestPublicEndpointsRemainAccessible:
    """Tests verifying public endpoints remain accessible without authentication."""

    def test_health_check_is_public(self, client):
        """GET / (health check) is accessible without authentication."""
        response = client.get("/")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_config_is_public(self, client):
        """GET /api/config is accessible without authentication."""
        response = client.get("/api/config")

        assert response.status_code == 200
        assert "available_models" in response.json()
        assert "available_personas" in response.json()


class TestCrossUserConversationOperations:
    """Tests verifying cross-user conversation operations are blocked."""

    def test_user_cannot_enumerate_other_users_conversations(
        self, client, user1, user2
    ):
        """User cannot determine if a conversation exists for another user."""
        # User1 creates multiple conversations
        user1_conversations = []
        for i in range(5):
            response = client.post(
                "/api/conversations",
                json={},
                headers=user1["headers"]
            )
            user1_conversations.append(response.json()["id"])

        # User2 tries to access each of user1's conversations
        # All should return 404, making enumeration useless
        for conv_id in user1_conversations:
            response = client.get(
                f"/api/conversations/{conv_id}",
                headers=user2["headers"]
            )
            assert response.status_code == 404

    def test_conversation_isolation_after_multiple_creations(
        self, client, user1, user2
    ):
        """Conversation isolation is maintained after multiple creations."""
        # Create interleaved conversations
        user1_ids = []
        user2_ids = []

        for i in range(3):
            # User1 creates
            r1 = client.post("/api/conversations", json={}, headers=user1["headers"])
            user1_ids.append(r1.json()["id"])

            # User2 creates
            r2 = client.post("/api/conversations", json={}, headers=user2["headers"])
            user2_ids.append(r2.json()["id"])

        # Verify user1 can only access their own
        for conv_id in user1_ids:
            response = client.get(
                f"/api/conversations/{conv_id}",
                headers=user1["headers"]
            )
            assert response.status_code == 200

        for conv_id in user2_ids:
            response = client.get(
                f"/api/conversations/{conv_id}",
                headers=user1["headers"]
            )
            assert response.status_code == 404

        # Verify user2 can only access their own
        for conv_id in user2_ids:
            response = client.get(
                f"/api/conversations/{conv_id}",
                headers=user2["headers"]
            )
            assert response.status_code == 200

        for conv_id in user1_ids:
            response = client.get(
                f"/api/conversations/{conv_id}",
                headers=user2["headers"]
            )
            assert response.status_code == 404
