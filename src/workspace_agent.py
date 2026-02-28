"""Chat agent for the interactive analysis workspace."""

import json
import os
import re
from anthropic import Anthropic

client = Anthropic()

SYSTEM_PROMPT_TEMPLATE = """You are an AI recruiting analyst helping review a candidate's skills and qualifications.

## Candidate Information
**Name:** {name}
**Email:** {email}

## Resume
{resume_text}

## Current Skill Analysis
{skills_summary}

## Instructions
- Help the recruiter analyze this candidate's qualifications
- Answer questions about the resume, skills, and fit for roles
- When the recruiter asks you to modify the analysis (adjust scores, add/remove skills, etc.), include an actions block in your response

To modify the analysis, include a fenced JSON block like this in your response:

```actions
[
  {{"action": "adjust_confidence", "skill_name": "Python", "confidence": 0.85}},
  {{"action": "add_skill", "skill_name": "Docker", "category": "devops", "confidence": 0.6, "evidence": "Mentioned in project descriptions"}},
  {{"action": "remove_skill", "skill_name": "COBOL"}},
  {{"action": "set_note", "skill_name": "Python", "note": "Strong evidence from multiple projects"}},
  {{"action": "add_equivalency", "skill_name": "React", "equivalent_to": "Frontend Development"}},
  {{"action": "learn_skill_concept", "name": "React Native", "category": "framework", "description": "Cross-platform mobile framework"}},
  {{"action": "learn_equivalency", "skill_name": "React.js", "equivalent_to": "React", "strength": 1.0}}
]
```

Only include actions when the recruiter explicitly asks for changes. Always explain your reasoning in your message text.
"""


def _build_skills_summary(skills: list[dict]) -> str:
    if not skills:
        return "No skills extracted yet."
    lines = []
    for s in skills:
        conf = s.get("final_confidence") or s.get("llm_confidence") or 0
        try:
            conf = float(conf)
        except (ValueError, TypeError):
            conf = 0.0
        lines.append(f"- {s['skill_name']} ({s.get('category', 'other')}): {conf*100:.0f}% confidence — {s.get('reasoning', '')}")
    return "\n".join(lines)


def _parse_actions(text: str) -> tuple[str, list[dict]]:
    """Extract action blocks from response text. Returns (clean_text, actions)."""
    actions = []
    pattern = r"```actions\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    for match in matches:
        try:
            parsed = json.loads(match)
            if isinstance(parsed, list):
                actions.extend(parsed)
            elif isinstance(parsed, dict):
                actions.append(parsed)
        except json.JSONDecodeError:
            pass
    clean_text = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    return clean_text, actions


def chat(candidate: dict, skills: list[dict], history: list[dict], user_message: str) -> tuple[str, list[dict]]:
    """Process a chat message. Returns (display_message, actions)."""
    # Add knowledge base context
    kb_context = ""
    try:
        from .knowledge_base import get_skills_context
        kb_context = get_skills_context()
    except Exception:
        pass

    system = SYSTEM_PROMPT_TEMPLATE.format(
        name=candidate.get("name", "Unknown"),
        email=candidate.get("email", ""),
        resume_text=candidate.get("resume_text", "(no resume text)"),
        skills_summary=_build_skills_summary(skills),
    ) + kb_context

    messages = []
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        system=system,
        messages=messages,
    )

    raw_text = response.content[0].text
    display_text, actions = _parse_actions(raw_text)

    return display_text, actions
