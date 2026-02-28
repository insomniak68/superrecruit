"""Tests for skill equivalencies module."""

import json
import os
import sys
import pytest

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Use temp DB
os.environ["SR_DB_PATH"] = ":memory:"

from src.database import init_db, get_db
from src.models import EquivalencyGroupCreate, EquivalencyGroupUpdate, EquivalencySkill
from src.skill_equivalencies import (
    create_equivalency_group,
    get_equivalency_group,
    list_equivalency_groups,
    update_equivalency_group,
    delete_equivalency_group,
    seed_equivalency_groups,
    find_equivalents,
    adjusted_skill_score,
)


@pytest.fixture(autouse=True)
def setup_db():
    """Re-init DB for each test."""
    # Override DB_PATH to use temp file for isolation
    import tempfile
    tmp = tempfile.mktemp(suffix=".db")
    os.environ["SR_DB_PATH"] = tmp
    # Reload module to pick up new path
    import importlib
    import src.database
    importlib.reload(src.database)
    from src.database import init_db
    init_db()
    yield
    try:
        os.unlink(tmp)
    except OSError:
        pass


class TestCRUD:
    def test_create_and_get(self):
        data = EquivalencyGroupCreate(
            name="Cloud Platforms",
            description="Cloud providers",
            skills=[
                EquivalencySkill(skill_name="AWS", weight=1.0),
                EquivalencySkill(skill_name="Azure", weight=0.8),
            ],
        )
        group = create_equivalency_group(data)
        assert group.id is not None
        assert group.name == "Cloud Platforms"
        assert len(group.skills) == 2
        assert group.skills[0].skill_name == "aws"
        assert group.skills[1].weight == 0.8

        fetched = get_equivalency_group(group.id)
        assert fetched is not None
        assert fetched.name == "Cloud Platforms"

    def test_list(self):
        create_equivalency_group(EquivalencyGroupCreate(
            name="Group A", skills=[EquivalencySkill(skill_name="x", weight=1.0)]
        ))
        create_equivalency_group(EquivalencyGroupCreate(
            name="Group B", skills=[EquivalencySkill(skill_name="y", weight=1.0)]
        ))
        groups = list_equivalency_groups()
        assert len(groups) == 2

    def test_update(self):
        group = create_equivalency_group(EquivalencyGroupCreate(
            name="Old Name",
            skills=[EquivalencySkill(skill_name="a", weight=1.0)],
        ))
        updated = update_equivalency_group(group.id, EquivalencyGroupUpdate(
            name="New Name",
            skills=[
                EquivalencySkill(skill_name="b", weight=0.9),
                EquivalencySkill(skill_name="c", weight=0.7),
            ],
        ))
        assert updated.name == "New Name"
        assert len(updated.skills) == 2

    def test_delete(self):
        group = create_equivalency_group(EquivalencyGroupCreate(
            name="To Delete",
            skills=[EquivalencySkill(skill_name="x", weight=1.0)],
        ))
        assert delete_equivalency_group(group.id) is True
        assert get_equivalency_group(group.id) is None

    def test_delete_nonexistent(self):
        assert delete_equivalency_group(9999) is False

    def test_get_nonexistent(self):
        assert get_equivalency_group(9999) is None


class TestSeed:
    def test_seed_creates_groups(self):
        created = seed_equivalency_groups()
        assert len(created) >= 4  # cloud, frontend, backend, databases at minimum
        # Idempotent
        created2 = seed_equivalency_groups()
        assert len(created2) == 0

    def test_seed_idempotent(self):
        seed_equivalency_groups()
        seed_equivalency_groups()
        groups = list_equivalency_groups()
        names = [g.name for g in groups]
        assert len(names) == len(set(names))  # no duplicates


class TestMatchingLogic:
    def test_find_equivalents(self):
        create_equivalency_group(EquivalencyGroupCreate(
            name="Cloud",
            skills=[
                EquivalencySkill(skill_name="AWS", weight=1.0),
                EquivalencySkill(skill_name="Azure", weight=0.8),
                EquivalencySkill(skill_name="GCP", weight=0.85),
            ],
        ))
        equivs = find_equivalents("aws")
        names = {e["skill_name"] for e in equivs}
        assert "azure" in names
        assert "gcp" in names
        assert "aws" not in names

    def test_find_equivalents_no_match(self):
        equivs = find_equivalents("nonexistent_skill")
        assert equivs == []

    def test_adjusted_skill_score_exact(self):
        score, explanation = adjusted_skill_score("python", "python", 0.9)
        assert score == 0.9
        assert explanation == "exact match"

    def test_adjusted_skill_score_equivalent(self):
        create_equivalency_group(EquivalencyGroupCreate(
            name="Cloud",
            skills=[
                EquivalencySkill(skill_name="AWS", weight=1.0),
                EquivalencySkill(skill_name="Azure", weight=0.8),
            ],
        ))
        score, explanation = adjusted_skill_score("azure", "aws", 0.85)
        assert abs(score - 0.85 * 0.8) < 0.01
        assert "80% equivalent" in explanation

    def test_adjusted_skill_score_no_equivalency(self):
        score, explanation = adjusted_skill_score("python", "kubernetes", 0.9)
        assert score == 0.0
        assert "no equivalency" in explanation

    def test_position_overrides(self):
        """Position-level overrides take precedence over global."""
        # Global: AWS ↔ Azure @ 0.8
        create_equivalency_group(EquivalencyGroupCreate(
            name="Cloud",
            skills=[
                EquivalencySkill(skill_name="AWS", weight=1.0),
                EquivalencySkill(skill_name="Azure", weight=0.8),
            ],
        ))

        # Create a position with override: AWS ↔ Azure @ 0.5
        from src.database import get_db
        conn = get_db()
        overrides = json.dumps([{
            "name": "Cloud Override",
            "skills": [
                {"skill_name": "aws", "weight": 1.0},
                {"skill_name": "azure", "weight": 0.5},
            ],
        }])
        cur = conn.execute(
            "INSERT INTO position_profiles (title, equivalency_overrides) VALUES (?, ?)",
            ("Test Position", overrides),
        )
        pos_id = cur.lastrowid
        conn.commit()
        conn.close()

        # With position override
        equivs = find_equivalents("aws", position_id=pos_id)
        azure = next(e for e in equivs if e["skill_name"] == "azure")
        assert azure["weight"] == 0.5

        # Without position (global)
        equivs_global = find_equivalents("aws")
        azure_global = next(e for e in equivs_global if e["skill_name"] == "azure")
        assert azure_global["weight"] == 0.8


class TestWeightClamping:
    def test_weight_clamped_to_0_1(self):
        s = EquivalencySkill(skill_name="test", weight=1.5)
        assert s.weight == 1.0

    def test_weight_clamped_negative(self):
        s = EquivalencySkill(skill_name="test", weight=-0.5)
        assert s.weight == 0.0
