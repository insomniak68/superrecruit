"""Tests for the fit assessment module."""

import json
import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.fit_assessor import assess_fit, FitResult, _score_to_level


# ── Threshold mapping ──

def test_score_to_level_strong():
    assert _score_to_level(0.75) == "strong"
    assert _score_to_level(0.9) == "strong"
    assert _score_to_level(1.0) == "strong"


def test_score_to_level_good():
    assert _score_to_level(0.5) == "good"
    assert _score_to_level(0.74) == "good"


def test_score_to_level_weak():
    assert _score_to_level(0.25) == "weak"
    assert _score_to_level(0.49) == "weak"


def test_score_to_level_poor():
    assert _score_to_level(0.0) == "poor"
    assert _score_to_level(0.24) == "poor"


# ── General assessment ──

@patch("src.fit_assessor._generate_rationale", return_value="Test rationale.")
def test_general_assessment_no_skills(mock_rat):
    result = assess_fit([])
    assert result.fit_score == 0.0
    assert result.fit_level == "poor"


@patch("src.fit_assessor._generate_rationale", return_value="Good breadth of skills.")
def test_general_assessment_with_skills(mock_rat):
    skills = [
        {"skill_name": "Python", "category": "language", "llm_confidence": 0.9, "final_confidence": 0.9},
        {"skill_name": "React", "category": "framework", "llm_confidence": 0.8, "final_confidence": 0.8},
        {"skill_name": "Docker", "category": "devops", "llm_confidence": 0.7, "final_confidence": 0.7},
        {"skill_name": "Leadership", "category": "soft_skill", "llm_confidence": 0.6, "final_confidence": 0.6},
    ]
    result = assess_fit(skills)
    assert 0.0 < result.fit_score <= 1.0
    assert result.fit_level in ("strong", "good", "weak", "poor")
    assert result.rationale


# ── Role-based assessment ──

@patch("src.fit_assessor._generate_rationale", return_value="Matches core skills well.")
@patch("src.fit_assessor.get_role_archetype")
def test_role_assessment_full_match(mock_role, mock_rat):
    from src.knowledge_base import RoleArchetype, RoleArchetypeSkill
    mock_role.return_value = RoleArchetype(
        id=1, name="Backend Dev",
        core_skills=[
            RoleArchetypeSkill(skill_concept_id=1, skill_name="Python", weight=1.0, min_confidence=0.5),
            RoleArchetypeSkill(skill_concept_id=2, skill_name="SQL", weight=1.0, min_confidence=0.5),
        ],
        adjacent_skills=[
            RoleArchetypeSkill(skill_concept_id=3, skill_name="Docker", weight=0.5, is_core=False),
        ],
    )
    skills = [
        {"skill_name": "Python", "category": "language", "final_confidence": 0.9},
        {"skill_name": "SQL", "category": "language", "final_confidence": 0.85},
        {"skill_name": "Docker", "category": "devops", "final_confidence": 0.7},
    ]
    result = assess_fit(skills, role_archetype_id=1)
    assert result.fit_score >= 0.7
    assert result.fit_level in ("strong", "good")
    assert "core_skills" in result.breakdown


@patch("src.fit_assessor._generate_rationale", return_value="Missing critical core skills.")
@patch("src.fit_assessor.get_role_archetype")
def test_role_assessment_missing_core(mock_role, mock_rat):
    from src.knowledge_base import RoleArchetype, RoleArchetypeSkill
    mock_role.return_value = RoleArchetype(
        id=1, name="Backend Dev",
        core_skills=[
            RoleArchetypeSkill(skill_concept_id=1, skill_name="Python", weight=1.0, min_confidence=0.5),
            RoleArchetypeSkill(skill_concept_id=2, skill_name="SQL", weight=1.0, min_confidence=0.5),
        ],
        adjacent_skills=[],
    )
    # Candidate has neither core skill
    skills = [
        {"skill_name": "JavaScript", "category": "language", "final_confidence": 0.9},
    ]
    result = assess_fit(skills, role_archetype_id=1)
    assert result.fit_score < 0.25
    assert result.fit_level == "poor"


# ── Position profile assessment ──

@patch("src.fit_assessor._generate_rationale", return_value="Partial match.")
def test_position_profile_assessment(mock_rat):
    profile = {
        "name": "Data Engineer",
        "core_skills": ["Python", "SQL"],
        "adjacent_skills": ["Spark"],
    }
    skills = [
        {"skill_name": "Python", "category": "language", "final_confidence": 0.85},
    ]
    result = assess_fit(skills, position_profile=profile)
    assert 0.0 < result.fit_score < 1.0
    assert result.breakdown["role"] == "Data Engineer"


# ── Position-level equivalency overrides flow through scoring ──

@patch("src.fit_assessor._generate_rationale", return_value="Equivalent match.")
def test_position_overrides_affect_scoring(mock_rat):
    """Position-level equivalency overrides should change scores vs. global defaults."""
    import tempfile, importlib
    tmp = tempfile.mktemp(suffix=".db")
    os.environ["SR_DB_PATH"] = tmp
    import src.database
    importlib.reload(src.database)
    from src.database import init_db, get_db
    init_db()

    from src.models import EquivalencyGroupCreate, EquivalencySkill
    from src.skill_equivalencies import create_equivalency_group

    # Global: AWS ↔ Azure @ 0.8
    create_equivalency_group(EquivalencyGroupCreate(
        name="Cloud",
        skills=[
            EquivalencySkill(skill_name="AWS", weight=1.0),
            EquivalencySkill(skill_name="Azure", weight=0.8),
        ],
    ))

    # Create position with override: AWS ↔ Azure @ 0.3
    conn = get_db()
    overrides = json.dumps([{
        "name": "Cloud Override",
        "skills": [
            {"skill_name": "aws", "weight": 1.0},
            {"skill_name": "azure", "weight": 0.3},
        ],
    }])
    cur = conn.execute(
        "INSERT INTO position_profiles (title, equivalency_overrides) VALUES (?, ?)",
        ("Strict AWS Role", overrides),
    )
    pos_id = cur.lastrowid
    conn.commit()
    conn.close()

    candidate_skills = [
        {"skill_name": "Azure", "category": "cloud", "final_confidence": 0.9},
    ]

    # Without position override (global: 0.8 weight)
    profile_global = {
        "name": "Cloud Role",
        "core_skills": [{"name": "AWS", "weight": 1.0}],
        "adjacent_skills": [],
    }
    result_global = assess_fit(candidate_skills, position_profile=profile_global)

    # With position override (0.3 weight)
    profile_override = {
        "name": "Strict AWS Role",
        "position_id": pos_id,
        "core_skills": [{"name": "AWS", "weight": 1.0}],
        "adjacent_skills": [],
    }
    result_override = assess_fit(candidate_skills, position_profile=profile_override)

    # Override should produce a lower score
    assert result_override.fit_score < result_global.fit_score


# ── FitResult serialization ──

def test_fit_result_to_dict():
    result = FitResult(fit_score=0.756, fit_level="strong", rationale="Great fit.", breakdown={"key": "val"})
    d = result.to_dict()
    assert d["fit_score"] == 0.756
    assert d["fit_level"] == "strong"
    assert d["rationale"] == "Great fit."
    assert d["breakdown"] == {"key": "val"}


# ── LLM rationale generation (mocked) ──

@patch("src.fit_assessor.get_client")
def test_rationale_llm_called(mock_get_client):
    mock_client = MagicMock()
    mock_client.complete.return_value = "Strong technical background with excellent Python skills."
    mock_get_client.return_value = mock_client

    from src.fit_assessor import _generate_rationale
    rationale = _generate_rationale(
        [{"skill_name": "Python", "final_confidence": 0.9}],
        0.85, "strong", {}
    )
    assert "Python" in rationale or "Strong" in rationale
    mock_client.complete.assert_called_once()


@patch("src.fit_assessor.get_client", side_effect=Exception("LLM down"))
def test_rationale_fallback_on_error(mock_get_client):
    from src.fit_assessor import _generate_rationale
    rationale = _generate_rationale([], 0.85, "strong", {})
    assert "Strong fit" in rationale


# ── Override persistence (via DB) ──

def test_fit_override_db(tmp_path):
    """Test that fit overrides are stored in the database."""
    os.environ["SR_DB_PATH"] = str(tmp_path / "test.db")
    from src.database import init_db, get_db
    init_db()

    conn = get_db()
    conn.execute("INSERT INTO candidates (name, email) VALUES (?, ?)", ("Test", "test@test.com"))
    conn.execute(
        "INSERT INTO fit_assessments (candidate_id, fit_score, fit_level, rationale, breakdown_json, assessed_by) VALUES (?,?,?,?,?,?)",
        (1, 0.85, "strong", "Override rationale", "{}", "human")
    )
    conn.commit()

    row = conn.execute("SELECT * FROM fit_assessments WHERE candidate_id=1 ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    assert row["fit_level"] == "strong"
    assert row["assessed_by"] == "human"
    assert row["rationale"] == "Override rationale"

    # Cleanup
    del os.environ["SR_DB_PATH"]


# ── Bulk output inclusion ──

def test_bulk_result_includes_fit():
    from src.bulk_processor import CandidateResult
    result = CandidateResult(filename="test.pdf", fit_score=0.72, fit_level="good")
    d = result.to_dict()
    assert d["fit_score"] == 0.72
    assert d["fit_level"] == "good"
    csv_row = result.to_csv_row()
    assert csv_row["fit_score"] == 0.72
    assert csv_row["fit_level"] == "good"
