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


def select_tests(skills: list[SkillAssessment]) -> list[TestBank]:
    bank = load_test_bank()
    selected = {}
    unmatched = []

    for skill in skills:
        conf = skill.final_confidence or skill.llm_confidence
        if conf >= 0.8:
            continue
        skill_lower = skill.skill_name.lower()
        found = False
        for test in bank:
            tags = [t.lower() for t in test.skill_tags]
            if skill_lower in tags or any(skill_lower in t or t in skill_lower for t in tags):
                if test.id not in selected:
                    selected[test.id] = test
                found = True
        if not found:
            unmatched.append(skill.skill_name)

    if unmatched:
        print(f"[TestSelector] No tests for: {', '.join(unmatched)}")

    return list(selected.values())
