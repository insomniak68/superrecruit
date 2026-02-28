import os
import yaml
from .models import SkillAssessment, TestBank

TEST_BANK_DIR = os.path.join(os.path.dirname(__file__), "test_bank")


def load_test_bank() -> list[TestBank]:
    tests = []
    for f in os.listdir(TEST_BANK_DIR):
        if f.endswith(".yaml") or f.endswith(".yml"):
            with open(os.path.join(TEST_BANK_DIR, f)) as fh:
                data = yaml.safe_load(fh)
                tests.append(TestBank(**data))
    return tests


def _get_related_skill_names(skill_name: str) -> list[str]:
    """Get names of related/equivalent skills from KB."""
    try:
        from .knowledge_base import get_skill_by_canonical, get_skill_relations, get_skill_concept
        concept = get_skill_by_canonical(skill_name.lower().strip())
        if not concept:
            return []
        relations = get_skill_relations(concept.id)
        names = []
        for r in relations:
            if r.relation_type in ("equivalent", "subset", "adjacent"):
                other_id = r.target_skill_id if r.source_skill_id == concept.id else r.source_skill_id
                other = get_skill_concept(other_id)
                if other:
                    names.append(other.name.lower())
        return names
    except Exception:
        return []


def select_tests(skills: list[SkillAssessment]) -> list[TestBank]:
    bank = load_test_bank()
    selected = {}
    unmatched = []

    for skill in skills:
        conf = skill.final_confidence or skill.llm_confidence
        if conf >= 0.8:
            continue
        skill_lower = skill.skill_name.lower()
        search_names = [skill_lower] + _get_related_skill_names(skill.skill_name)
        found = False
        for test in bank:
            tags = [t.lower() for t in test.skill_tags]
            for sn in search_names:
                if sn in tags or any(sn in t or t in sn for t in tags):
                    if test.id not in selected:
                        selected[test.id] = test
                    found = True
                    break
        if not found:
            unmatched.append(skill.skill_name)

    if unmatched:
        print(f"[TestSelector] No tests for: {', '.join(unmatched)}")

    return list(selected.values())
