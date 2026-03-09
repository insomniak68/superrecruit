"""Tests for position profiles CRUD and integration."""

import json
import os
import sys
import pytest

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SR_DB_PATH", ":memory:")

from src.database import init_db, get_db
from src.models import PositionProfileCreate, PositionProfileUpdate, SkillRequirement
from src.position_profiles import (
    create_position, get_position, list_positions, update_position,
    delete_position, activate_position, get_active_position,
)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    old_db_path = os.environ.get("SR_DB_PATH")
    db_path = str(tmp_path / "test.db")
    os.environ["SR_DB_PATH"] = db_path
    # Force reimport to pick up new path
    import importlib
    from src import database
    importlib.reload(database)
    from src import position_profiles
    importlib.reload(position_profiles)
    init_db()
    yield
    if old_db_path is not None:
        os.environ["SR_DB_PATH"] = old_db_path
    else:
        os.environ.pop("SR_DB_PATH", None)
    importlib.reload(database)


def _make_profile(**kwargs) -> PositionProfileCreate:
    defaults = {
        "title": "Senior Python Developer",
        "department": "Engineering",
        "description": "Build stuff",
        "required_skills": [
            SkillRequirement(skill_name="Python", min_confidence=0.7, weight=1.5),
            SkillRequirement(skill_name="SQL", min_confidence=0.5, weight=1.0),
        ],
        "preferred_skills": [
            SkillRequirement(skill_name="Docker", min_confidence=0.3, weight=0.5),
        ],
        "min_experience_years": 5,
    }
    defaults.update(kwargs)
    return PositionProfileCreate(**defaults)


class TestPositionCRUD:
    def test_create_and_get(self):
        p = create_position(_make_profile())
        assert p.id is not None
        assert p.title == "Senior Python Developer"
        assert p.department == "Engineering"
        assert len(p.required_skills) == 2
        assert p.required_skills[0].skill_name == "Python"
        assert p.is_active is False

        fetched = get_position(p.id)
        assert fetched is not None
        assert fetched.title == p.title

    def test_list(self):
        create_position(_make_profile(title="Role A"))
        create_position(_make_profile(title="Role B"))
        all_pos = list_positions()
        assert len(all_pos) == 2
        titles = {p.title for p in all_pos}
        assert "Role A" in titles
        assert "Role B" in titles

    def test_update(self):
        p = create_position(_make_profile())
        updated = update_position(p.id, PositionProfileUpdate(title="Updated Title", min_experience_years=10))
        assert updated.title == "Updated Title"
        assert updated.min_experience_years == 10
        assert updated.department == "Engineering"  # unchanged

    def test_update_nonexistent(self):
        result = update_position(9999, PositionProfileUpdate(title="X"))
        assert result is None

    def test_delete(self):
        p = create_position(_make_profile())
        assert delete_position(p.id) is True
        assert get_position(p.id) is None
        assert delete_position(p.id) is False

    def test_activate(self):
        p1 = create_position(_make_profile(title="A"))
        p2 = create_position(_make_profile(title="B"))

        activated = activate_position(p1.id)
        assert activated.is_active is True
        assert get_active_position().id == p1.id

        # Activate another — first should deactivate
        activate_position(p2.id)
        assert get_position(p1.id).is_active is False
        assert get_active_position().id == p2.id

    def test_activate_nonexistent(self):
        assert activate_position(9999) is None

    def test_get_nonexistent(self):
        assert get_position(9999) is None

    def test_created_by(self):
        p = create_position(_make_profile(), created_by="job_parser")
        assert p.created_by == "job_parser"

    def test_empty_skills(self):
        p = create_position(_make_profile(required_skills=[], preferred_skills=[]))
        assert p.required_skills == []
        assert p.preferred_skills == []

    def test_update_skills(self):
        p = create_position(_make_profile())
        new_skills = [SkillRequirement(skill_name="Rust", min_confidence=0.8, weight=2.0)]
        updated = update_position(p.id, PositionProfileUpdate(required_skills=new_skills))
        assert len(updated.required_skills) == 1
        assert updated.required_skills[0].skill_name == "Rust"
