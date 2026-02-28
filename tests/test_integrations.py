"""Tests for integration API: submission, API key auth, webhooks, status polling."""

import os
import sys
import json
import base64
import time
import unittest
from unittest.mock import patch, MagicMock

# Use temp DB
os.environ["SR_DB_PATH"] = "/tmp/test_superrecruit_integ.db"

from fastapi.testclient import TestClient
from src.main import app, ADMIN_SECRET

client = TestClient(app, raise_server_exceptions=False)
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_SECRET}"}

# Trigger startup
with TestClient(app):
    pass


def _create_integration(name="TestPartner", webhook_url=None):
    body = {"name": name}
    if webhook_url:
        body["webhook_url"] = webhook_url
    resp = client.post("/api/admin/integrations", json=body, headers=ADMIN_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    return data["api_key"], data["integration"]


def _make_resume_base64():
    """Create a minimal PDF-like content for testing."""
    # Real tests would use a proper PDF; here we just base64-encode something
    return base64.b64encode(b"%PDF-1.4 fake resume content for testing").decode()


class TestAdminIntegrations(unittest.TestCase):

    def test_create_integration(self):
        api_key, integration = _create_integration("Acme Corp")
        self.assertTrue(api_key.startswith("sr_live_"))
        self.assertEqual(integration["name"], "Acme Corp")
        self.assertEqual(integration["is_active"], 1)

    def test_list_integrations(self):
        _create_integration("ListTest")
        resp = client.get("/api/admin/integrations", headers=ADMIN_HEADERS)
        self.assertEqual(resp.status_code, 200)
        names = [i["name"] for i in resp.json()]
        self.assertIn("ListTest", names)

    def test_revoke_integration(self):
        api_key, integration = _create_integration("RevokeMe")
        resp = client.delete(f"/api/admin/integrations/{integration['id']}", headers=ADMIN_HEADERS)
        self.assertEqual(resp.status_code, 200)
        # Key should no longer work
        resp = client.get("/api/v1/submissions", headers={"X-API-Key": api_key})
        self.assertEqual(resp.status_code, 401)

    def test_admin_auth_required(self):
        resp = client.post("/api/admin/integrations", json={"name": "NoAuth"}, headers={"Authorization": "Bearer wrong"})
        self.assertEqual(resp.status_code, 403)


class TestAPIKeyAuth(unittest.TestCase):

    def test_missing_key(self):
        resp = client.get("/api/v1/submissions")
        self.assertEqual(resp.status_code, 422)  # missing header

    def test_invalid_key(self):
        resp = client.get("/api/v1/submissions", headers={"X-API-Key": "bad_key"})
        self.assertEqual(resp.status_code, 401)

    def test_valid_key(self):
        api_key, _ = _create_integration("AuthTest")
        resp = client.get("/api/v1/submissions", headers={"X-API-Key": api_key})
        self.assertEqual(resp.status_code, 200)


class TestSubmissionAPI(unittest.TestCase):

    @patch("src.main._process_submission")
    def test_create_submission(self, mock_process):
        api_key, _ = _create_integration("SubmitTest")
        headers = {"X-API-Key": api_key}
        resp = client.post("/api/v1/submissions", json={
            "name": "Jane Doe",
            "email": "jane@example.com",
            "resume": _make_resume_base64(),
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "accepted")
        self.assertIn("submission_id", data)
        mock_process.assert_called_once()

    @patch("src.main._process_submission")
    def test_get_submission(self, mock_process):
        api_key, _ = _create_integration("GetTest")
        headers = {"X-API-Key": api_key}
        resp = client.post("/api/v1/submissions", json={
            "name": "John", "email": "john@test.com", "resume": _make_resume_base64()
        }, headers=headers)
        sub_id = resp.json()["submission_id"]

        resp = client.get(f"/api/v1/submissions/{sub_id}", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["submission_id"], sub_id)
        self.assertEqual(resp.json()["status"], "accepted")

    @patch("src.main._process_submission")
    def test_list_submissions_filtered(self, mock_process):
        api_key, _ = _create_integration("ListSubTest")
        headers = {"X-API-Key": api_key}
        client.post("/api/v1/submissions", json={
            "name": "A", "email": "a@test.com", "resume": _make_resume_base64()
        }, headers=headers)
        resp = client.get("/api/v1/submissions?status=accepted", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.json()), 1)

    @patch("src.main._process_submission")
    def test_cross_integration_isolation(self, mock_process):
        api_key_a, _ = _create_integration("OrgA")
        api_key_b, _ = _create_integration("OrgB")
        resp = client.post("/api/v1/submissions", json={
            "name": "Secret", "email": "s@a.com", "resume": _make_resume_base64()
        }, headers={"X-API-Key": api_key_a})
        sub_id = resp.json()["submission_id"]

        # OrgB can't see OrgA's submission
        resp = client.get(f"/api/v1/submissions/{sub_id}", headers={"X-API-Key": api_key_b})
        self.assertEqual(resp.status_code, 404)


class TestWebhookDispatch(unittest.TestCase):

    @patch("src.webhooks.httpx.post")
    def test_webhook_fires(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_post.return_value = mock_resp

        from src.webhooks import fire_webhook
        result = fire_webhook("sub-123", "submission.analyzed", {"test": True}, "https://example.com/hook", 1)
        self.assertTrue(result)
        mock_post.assert_called_once()

    @patch("src.webhooks.httpx.post")
    def test_webhook_retries(self, mock_post):
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.text = "error"
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.text = "ok"
        mock_post.side_effect = [fail_resp, ok_resp]

        from src.webhooks import fire_webhook
        result = fire_webhook("sub-456", "submission.analyzed", {}, "https://example.com/hook", 1)
        self.assertTrue(result)
        self.assertEqual(mock_post.call_count, 2)


class TestExistingEndpoints(unittest.TestCase):
    """Ensure existing endpoints still work."""

    def test_health(self):
        resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)

    def test_list_candidates(self):
        resp = client.get("/api/candidates")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    # Clean up test DB before run
    if os.path.exists("/tmp/test_superrecruit_integ.db"):
        os.unlink("/tmp/test_superrecruit_integ.db")
    unittest.main()
