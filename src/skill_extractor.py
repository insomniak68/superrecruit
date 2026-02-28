import json
import os
import anthropic
from .models import SkillAssessment, Confidence

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

PROMPT = """Analyze this resume and extract all technical and professional skills claimed.

For each skill, provide:
1. skill_name: The specific skill
2. category: One of [programming, framework, database, cloud, devops, methodology, soft_skill, design, data, security, other]
3. evidence: Direct quotes or references from the resume supporting this skill
4. confidence: HIGH, MEDIUM, or LOW
   - HIGH: Years of relevant experience, matching job titles, certifications
   - MEDIUM: Mentioned in context but ambiguous (short tenure, tangential role)
   - LOW: Listed in skills section but never referenced in experience
5. reasoning: Why you assigned this confidence level

Return ONLY a JSON array of objects with these fields. No markdown, no explanation.

Resume:
{resume_text}"""


def extract_skills(resume_text: str) -> list[SkillAssessment]:
    client = anthropic.Anthropic(api_key=API_KEY)
    message = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": PROMPT.format(resume_text=resume_text)}],
    )
    raw = message.content[0].text.strip()
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
            llm_confidence=Confidence(s["confidence"]),
            reasoning=s.get("reasoning", ""),
        ))
    return skills
