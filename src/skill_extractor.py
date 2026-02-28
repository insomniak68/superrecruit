import json
import os
from .models import SkillAssessment
from .llm_config import get_client

PROMPT = """Analyze this resume and extract all technical and professional skills claimed.

For each skill, provide:
1. skill_name: The specific skill
2. category: One of [programming, framework, database, cloud, devops, methodology, soft_skill, design, data, security, other]
3. evidence: Direct quotes or references from the resume supporting this skill
4. confidence: A numeric score from 0.0 to 1.0
   - 0.8–1.0: Years of relevant experience, matching job titles, certifications
   - 0.4–0.7: Mentioned in context but ambiguous (short tenure, tangential role)
   - 0.0–0.3: Listed in skills section but never referenced in experience
5. reasoning: Why you assigned this confidence level

Return ONLY a JSON array of objects with these fields. No markdown, no explanation.

Resume:
{resume_text}"""


def extract_skills(resume_text: str) -> list[SkillAssessment]:
    client = get_client("skill_extraction")
    raw = client.complete(
        messages=[{"role": "user", "content": PROMPT.format(resume_text=resume_text)}],
        max_tokens=4096,
    ).strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3]

    skills_data = json.loads(raw)
    skills = []
    for s in skills_data:
        skills.append(SkillAssessment(
            skill_name=s["skill_name"],
            category=s.get("category", "other"),
            evidence=s.get("evidence", ""),
            llm_confidence=float(s["confidence"]),
            reasoning=s.get("reasoning", ""),
        ))
    # Enrich with knowledge base
    try:
        from .knowledge_base import enrich_with_knowledge_base
        skills = enrich_with_knowledge_base(skills)
    except Exception:
        pass  # KB enrichment is optional — don't break extraction
    return skills
