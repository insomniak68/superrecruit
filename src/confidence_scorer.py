import re
from .models import SkillAssessment, Confidence


def score_confidence(skills: list[SkillAssessment], parsed_resume: dict) -> list[SkillAssessment]:
    sections = parsed_resume.get("sections", {})
    experience_text = " ".join([
        sections.get(k, "") for k in ["experience", "work experience", "professional experience", "employment"]
    ]).lower()
    skills_section = sections.get("skills", sections.get("technical skills", sections.get("core competencies", ""))).lower()
    certs_text = sections.get("certifications", sections.get("certificates", "")).lower()

    for skill in skills:
        name_lower = skill.skill_name.lower()
        boost = 0

        # Mentioned in experience
        if name_lower in experience_text:
            boost += 1
        # Only in skills section
        if name_lower in skills_section and name_lower not in experience_text:
            boost -= 1
        # Has certification
        if name_lower in certs_text:
            boost += 1
        # Count mentions across resume
        mentions = parsed_resume.get("raw_text", "").lower().count(name_lower)
        if mentions >= 3:
            boost += 1

        # Apply boost to LLM confidence
        conf_map = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
        rev_map = {0: Confidence.LOW, 1: Confidence.MEDIUM, 2: Confidence.HIGH}
        base = conf_map[skill.llm_confidence]
        final = max(0, min(2, base + boost))
        skill.final_confidence = rev_map[final]

    return skills
