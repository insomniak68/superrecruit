"""Tests for the knowledge base module."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import src.database as db_mod

@pytest.fixture(autouse=True)
def setup_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    db_mod.init_db()
    yield

from src.knowledge_base import (
    SkillConcept, SkillRelation, RoleArchetype, RoleArchetypeSkill,
    EmployerInterpretation, EmployerSkillOverride,
    create_skill_concept, get_skill_concept, get_skill_by_canonical,
    list_skill_concepts, update_skill_concept, delete_skill_concept,
    create_skill_relation, get_skill_relations, delete_skill_relation,
    create_role_archetype, get_role_archetype, list_role_archetypes,
    update_role_archetype, delete_role_archetype,
    create_employer_interpretation, get_employer_interpretation,
    list_employer_interpretations, delete_employer_interpretation,
    search_knowledge_base, export_knowledge_base, import_knowledge_base,
    enrich_with_knowledge_base,
)


class TestSkillConcepts:
    def test_create_and_get(self):
        s = create_skill_concept(SkillConcept(name="Python", category="programming", description="A language"))
        assert s.id is not None
        assert s.canonical_name == "python"
        got = get_skill_concept(s.id)
        assert got.name == "Python"

    def test_canonical_lookup(self):
        create_skill_concept(SkillConcept(name="JavaScript"))
        s = get_skill_by_canonical("javascript")
        assert s is not None
        assert s.name == "JavaScript"

    def test_list(self):
        create_skill_concept(SkillConcept(name="A"))
        create_skill_concept(SkillConcept(name="B"))
        assert len(list_skill_concepts()) == 2

    def test_update(self):
        s = create_skill_concept(SkillConcept(name="Old"))
        updated = update_skill_concept(s.id, {"name": "New", "description": "Updated"})
        assert updated.name == "New"
        assert updated.version == 2

    def test_delete(self):
        s = create_skill_concept(SkillConcept(name="ToDelete"))
        assert delete_skill_concept(s.id)
        assert get_skill_concept(s.id) is None

    def test_delete_cascades_relations(self):
        a = create_skill_concept(SkillConcept(name="A"))
        b = create_skill_concept(SkillConcept(name="B"))
        create_skill_relation(SkillRelation(source_skill_id=a.id, target_skill_id=b.id, relation_type="adjacent"))
        delete_skill_concept(a.id)
        assert len(get_skill_relations(b.id)) == 0


class TestSkillRelations:
    def test_create_and_get(self):
        a = create_skill_concept(SkillConcept(name="A"))
        b = create_skill_concept(SkillConcept(name="B"))
        r = create_skill_relation(SkillRelation(source_skill_id=a.id, target_skill_id=b.id, relation_type="equivalent", strength=0.9))
        assert r.id is not None
        rels = get_skill_relations(a.id)
        assert len(rels) == 1
        assert rels[0].relation_type == "equivalent"

    def test_delete(self):
        a = create_skill_concept(SkillConcept(name="A"))
        b = create_skill_concept(SkillConcept(name="B"))
        r = create_skill_relation(SkillRelation(source_skill_id=a.id, target_skill_id=b.id, relation_type="adjacent"))
        assert delete_skill_relation(r.id)
        assert len(get_skill_relations(a.id)) == 0


class TestRoleArchetypes:
    def test_create_with_skills(self):
        py = create_skill_concept(SkillConcept(name="Python"))
        sql = create_skill_concept(SkillConcept(name="SQL"))
        role = create_role_archetype(RoleArchetype(
            name="Python Dev", description="Backend dev",
            core_skills=[RoleArchetypeSkill(skill_concept_id=py.id, min_confidence=0.7)],
            adjacent_skills=[RoleArchetypeSkill(skill_concept_id=sql.id, weight=0.5, is_core=False)],
            green_flags=["open source"], red_flags=["no git"]
        ))
        assert role.id is not None
        got = get_role_archetype(role.id)
        assert len(got.core_skills) == 1
        assert len(got.adjacent_skills) == 1
        assert got.green_flags == ["open source"]

    def test_list_and_delete(self):
        create_role_archetype(RoleArchetype(name="R1"))
        create_role_archetype(RoleArchetype(name="R2"))
        assert len(list_role_archetypes()) == 2
        roles = list_role_archetypes()
        delete_role_archetype(roles[0].id)
        assert len(list_role_archetypes()) == 1


class TestEmployerInterpretations:
    def test_crud(self):
        py = create_skill_concept(SkillConcept(name="Python"))
        role = create_role_archetype(RoleArchetype(name="Dev"))
        ei = create_employer_interpretation(EmployerInterpretation(
            role_archetype_id=role.id, employer_name="Acme",
            overrides=[EmployerSkillOverride(skill_concept_id=py.id, priority="prioritize")],
            notes="They love Python"
        ))
        assert ei.id is not None
        got = get_employer_interpretation(ei.id)
        assert got.employer_name == "Acme"
        assert len(got.overrides) == 1
        eis = list_employer_interpretations(role.id)
        assert len(eis) == 1
        assert delete_employer_interpretation(ei.id)


class TestSearch:
    def test_search_skills(self):
        create_skill_concept(SkillConcept(name="Python", description="A great language"))
        create_skill_concept(SkillConcept(name="JavaScript"))
        results = search_knowledge_base("python")
        assert len(results["skills"]) == 1
        assert results["skills"][0].name == "Python"

    def test_search_roles(self):
        create_role_archetype(RoleArchetype(name="Data Scientist", description="ML expert"))
        results = search_knowledge_base("data")
        assert len(results["roles"]) == 1


class TestExportImport:
    def test_round_trip(self):
        py = create_skill_concept(SkillConcept(name="Python", category="programming"))
        js = create_skill_concept(SkillConcept(name="JavaScript", category="programming"))
        create_skill_relation(SkillRelation(source_skill_id=py.id, target_skill_id=js.id, relation_type="adjacent", strength=0.5))
        role = create_role_archetype(RoleArchetype(
            name="Dev", core_skills=[RoleArchetypeSkill(skill_concept_id=py.id, min_confidence=0.5)]
        ))
        create_employer_interpretation(EmployerInterpretation(role_archetype_id=role.id, employer_name="Test Corp"))

        exported = export_knowledge_base()
        assert exported["version"] == "1.0"
        assert len(exported["skill_concepts"]) == 2
        assert len(exported["skill_relations"]) == 1
        assert len(exported["role_archetypes"]) == 1

        # Import into same DB — should skip existing
        stats = import_knowledge_base(exported)
        assert stats["skills_skipped"] == 2
        assert stats["skills_created"] == 0
        assert stats["roles_skipped"] == 1


class TestEnrichment:
    def test_enrich(self):
        create_skill_concept(SkillConcept(name="Python", category="programming", description="Language",
                                           competency_signals={"strong": ["projects"]}))
        from src.models import SkillAssessment
        skills = [SkillAssessment(skill_name="Python", category="other", evidence="", llm_confidence=0.8, reasoning="")]
        enriched = enrich_with_knowledge_base(skills)
        assert hasattr(enriched[0], 'kb_concept_id')
        assert enriched[0].kb_category == "programming"

    def test_enrich_missing(self):
        from src.models import SkillAssessment
        skills = [SkillAssessment(skill_name="Obscure", category="other", evidence="", llm_confidence=0.5, reasoning="")]
        enriched = enrich_with_knowledge_base(skills)
        assert not hasattr(enriched[0], 'kb_concept_id')


class TestSeedIdempotency:
    def test_seed_twice(self):
        """Seeding twice should not create duplicates."""
        from scripts.seed_knowledge_base import seed
        seed()
        count1 = len(list_skill_concepts())
        seed()
        count2 = len(list_skill_concepts())
        assert count1 == count2
        assert count1 > 0
