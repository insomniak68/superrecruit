"""Tests for the interactive analysis workspace."""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.main import app
from src.database import init_db, get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("SR_DB_PATH", db_path)
    import src.database
    monkeypatch.setattr(src.database, "DB_PATH", db_path)
    init_db()
    # Insert a test candidate
    conn = get_db()
    conn.execute(
        "INSERT INTO candidates (id, name, email, resume_text) VALUES (1, 'Test User', 'test@example.com', 'Experienced Python developer with 5 years of experience.')"
    )
    conn.execute(
        "INSERT INTO skill_assessments (id, candidate_id, skill_name, category, evidence, llm_confidence, final_confidence, reasoning) VALUES (1, 1, 'Python', 'language', 'resume mentions Python', 0.8, 0.8, 'Strong evidence')"
    )
    conn.commit()
    conn.close()
    yield


def test_workspace_page_loads():
    resp = client.get("/workspace/1")
    assert resp.status_code == 200
    assert "Test User" in resp.text
    assert "Python" in resp.text


def test_workspace_404():
    resp = client.get("/workspace/999")
    assert resp.status_code == 404


def test_patch_skill_confidence():
    resp = client.patch("/api/workspace/1/skills/1", json={"confidence": 0.95})
    assert resp.status_code == 200
    data = resp.json()
    assert float(data["final_confidence"]) == pytest.approx(0.95, abs=0.01)


def test_patch_skill_irrelevant():
    resp = client.patch("/api/workspace/1/skills/1", json={"irrelevant": True})
    assert resp.status_code == 200
    assert resp.json()["category"] == "irrelevant"


def test_patch_skill_note():
    resp = client.patch("/api/workspace/1/skills/1", json={"note": "Updated note"})
    assert resp.status_code == 200
    assert resp.json()["reasoning"] == "Updated note"


def test_patch_skill_404():
    resp = client.patch("/api/workspace/1/skills/999", json={"confidence": 0.5})
    assert resp.status_code == 404


def test_add_skill():
    resp = client.post("/api/workspace/1/skills", json={"skill_name": "Docker", "category": "tool", "confidence": 0.6})
    assert resp.status_code == 200
    data = resp.json()
    assert data["skill_name"] == "Docker"
    assert float(data["final_confidence"]) == pytest.approx(0.6, abs=0.01)


def test_add_skill_empty_name():
    resp = client.post("/api/workspace/1/skills", json={"skill_name": ""})
    assert resp.status_code == 400


def test_add_skill_candidate_404():
    resp = client.post("/api/workspace/999/skills", json={"skill_name": "Go"})
    assert resp.status_code == 404


@patch("src.workspace_agent.get_client")
def test_chat_endpoint(mock_get_client):
    mock_llm = MagicMock()
    mock_llm.complete.return_value = "This candidate has strong Python skills."
    mock_get_client.return_value = mock_llm

    resp = client.post("/api/workspace/1/chat", json={"message": "Tell me about this candidate"})
    assert resp.status_code == 200
    data = resp.json()
    assert "Python" in data["message"]
    assert isinstance(data["skills"], list)


@patch("src.workspace_agent.get_client")
def test_chat_with_actions(mock_get_client):
    mock_llm = MagicMock()
    mock_llm.complete.return_value = """I'll adjust the Python confidence.

```actions
[{"action": "adjust_confidence", "skill_name": "Python", "confidence": 0.95}]
```"""
    mock_get_client.return_value = mock_llm

    resp = client.post("/api/workspace/1/chat", json={"message": "Increase Python confidence"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["actions"]) == 1
    assert data["actions"][0]["action"] == "adjust_confidence"
    # Verify skill was updated
    skill = next(s for s in data["skills"] if s["skill_name"] == "Python")
    assert float(skill["final_confidence"]) == pytest.approx(0.95, abs=0.01)


@patch("src.workspace_agent.get_client")
def test_chat_persists_conversation(mock_get_client):
    mock_llm = MagicMock()
    mock_llm.complete.return_value = "Hello!"
    mock_get_client.return_value = mock_llm

    client.post("/api/workspace/1/chat", json={"message": "Hi"})

    conn = get_db()
    messages = conn.execute("SELECT * FROM workspace_conversations WHERE candidate_id=1 ORDER BY created_at").fetchall()
    conn.close()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hi"
    assert messages[1]["role"] == "assistant"


def test_chat_empty_message():
    resp = client.post("/api/workspace/1/chat", json={"message": ""})
    assert resp.status_code == 400


def test_skill_overrides_recorded():
    client.patch("/api/workspace/1/skills/1", json={"confidence": 0.3})
    conn = get_db()
    overrides = conn.execute("SELECT * FROM skill_overrides WHERE candidate_id=1").fetchall()
    conn.close()
    assert len(overrides) >= 1
    assert overrides[0]["field"] == "final_confidence"
    assert overrides[0]["source"] == "human"
