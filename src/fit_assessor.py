"""Overall candidate-role fit assessment module.

Scores how well a candidate's skills match a role archetype or position profile,
producing a fit score (0.0-1.0), fit level, rationale, and category breakdown.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from .knowledge_base import (
    get_role_archetype,
    get_skill_relations,
    get_skill_by_canonical,
)
from .llm_config import get_client
from .skill_equivalencies import find_equivalents, adjusted_skill_score

logger = logging.getLogger(__name__)


@dataclass
class FitResult:
    fit_score: float  # 0.0 - 1.0
    fit_level: str  # strong, good, weak, poor
    rationale: str
    breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fit_score": round(self.fit_score, 3),
            "fit_level": self.fit_level,
            "rationale": self.rationale,
            "breakdown": self.breakdown,
        }


def _score_to_level(score: float) -> str:
    if score >= 0.75:
        return "strong"
    elif score >= 0.5:
        return "good"
    elif score >= 0.25:
        return "weak"
    return "poor"


def _get_equivalent_names(canonical_name: str) -> set[str]:
    """Get all equivalent skill names for a canonical name."""
    equivalents = {canonical_name}
    concept = get_skill_by_canonical(canonical_name)
    if not concept or not concept.id:
        return equivalents
    relations = get_skill_relations(concept.id)
    for rel in relations:
        if rel.relation_type == "equivalent":
            other_id = rel.target_skill_id if rel.source_skill_id == concept.id else rel.source_skill_id
            from .knowledge_base import get_skill_concept
            other = get_skill_concept(other_id)
            if other:
                equivalents.add(other.canonical_name)
    return equivalents


def _find_skill_match(
    skill_canonical: str,
    candidate_skills_map: dict[str, float],
    position_id: int = None,
) -> tuple[Optional[float], Optional[str]]:
    """Find a candidate skill matching the required skill, considering equivalencies.

    Returns (score, explanation) or (None, None) if no match.
    """
    # Direct match
    if skill_canonical in candidate_skills_map:
        return candidate_skills_map[skill_canonical], None

    # Check configurable skill equivalencies first (explicit weights, takes precedence)
    eq_skills = find_equivalents(skill_canonical, position_id=position_id)
    best_score = None
    best_explanation = None
    for eq in eq_skills:
        eq_name = eq["skill_name"]
        if eq_name in candidate_skills_map:
            base = candidate_skills_map[eq_name]
            adj, explanation = adjusted_skill_score(eq_name, skill_canonical, base, position_id)
            if best_score is None or adj > best_score:
                best_score = adj
                best_explanation = explanation
    if best_score is not None:
        return best_score, best_explanation

    # Fall back to KB equivalencies (default weight 0.85, with explanation)
    KB_EQUIV_WEIGHT = 0.85
    equivalents = _get_equivalent_names(skill_canonical)
    for eq in equivalents:
        if eq in candidate_skills_map:
            base = candidate_skills_map[eq]
            adj = round(base * KB_EQUIV_WEIGHT, 3)
            pct = int(KB_EQUIV_WEIGHT * 100)
            explanation = f"{skill_canonical} required → has {eq} (KB equivalent, {pct}% weight) → adjusted score: {adj}"
            if best_score is None or adj > best_score:
                best_score = adj
                best_explanation = explanation
    if best_score is not None:
        return best_score, best_explanation

    return None, None


def _assess_with_role(skills: list[dict], role_archetype_id: int, position_id: int = None) -> FitResult:
    """Assess fit against a specific role archetype."""
    role = get_role_archetype(role_archetype_id)
    if not role:
        return _assess_general(skills)

    # Build candidate skill map: canonical_name -> confidence
    candidate_map: dict[str, float] = {}
    for s in skills:
        name = s.get("skill_name", "").lower().strip()
        conf = float(s.get("final_confidence") or s.get("llm_confidence") or 0)
        candidate_map[name] = max(candidate_map.get(name, 0), conf)

    breakdown = {}
    total_weight = 0.0
    weighted_score = 0.0

    # Score core skills (heavy weight)
    core_scores = []
    for rs in role.core_skills:
        skill_name = rs.skill_name.lower().strip() if rs.skill_name else ""
        weight = rs.weight or 1.0
        total_weight += weight

        match_conf, eq_explanation = _find_skill_match(skill_name, candidate_map, position_id=position_id)
        if match_conf is not None:
            # Penalize if below min_confidence
            if rs.min_confidence and match_conf < rs.min_confidence:
                skill_score = match_conf * 0.7  # partial credit
            else:
                skill_score = match_conf
        else:
            skill_score = 0.0  # Missing core skill

        weighted_score += skill_score * weight
        entry = {"skill": rs.skill_name, "score": round(skill_score, 3), "matched": match_conf is not None}
        if eq_explanation:
            entry["equivalency"] = eq_explanation
        core_scores.append(entry)

    # Score adjacent skills (lower weight)
    adjacent_scores = []
    for rs in role.adjacent_skills:
        skill_name = rs.skill_name.lower().strip() if rs.skill_name else ""
        weight = rs.weight or 0.5
        total_weight += weight

        match_conf, eq_explanation = _find_skill_match(skill_name, candidate_map, position_id=position_id)
        if match_conf is not None:
            skill_score = match_conf
        else:
            skill_score = 0.0  # Not penalized as heavily — just no bonus

        weighted_score += skill_score * weight
        entry = {"skill": rs.skill_name, "score": round(skill_score, 3), "matched": match_conf is not None}
        if eq_explanation:
            entry["equivalency"] = eq_explanation
        adjacent_scores.append(entry)

    fit_score = weighted_score / total_weight if total_weight > 0 else 0.0
    fit_score = max(0.0, min(1.0, fit_score))

    breakdown = {
        "role": role.name,
        "core_skills": core_scores,
        "adjacent_skills": adjacent_scores,
    }

    fit_level = _score_to_level(fit_score)
    rationale = _generate_rationale(skills, fit_score, fit_level, breakdown)

    return FitResult(
        fit_score=fit_score,
        fit_level=fit_level,
        rationale=rationale,
        breakdown=breakdown,
    )


def _assess_with_profile(skills: list[dict], position_profile: dict) -> FitResult:
    """Assess fit against an ad-hoc position profile (dict with core_skills, adjacent_skills)."""
    candidate_map: dict[str, float] = {}
    for s in skills:
        name = s.get("skill_name", "").lower().strip()
        conf = float(s.get("final_confidence") or s.get("llm_confidence") or 0)
        candidate_map[name] = max(candidate_map.get(name, 0), conf)

    position_id = position_profile.get("position_id")
    total_weight = 0.0
    weighted_score = 0.0
    core_scores = []
    adjacent_scores = []

    for req in position_profile.get("core_skills", []):
        skill_name = req if isinstance(req, str) else req.get("name", "")
        weight = 1.0 if isinstance(req, str) else req.get("weight", 1.0)
        total_weight += weight

        match_conf, eq_explanation = _find_skill_match(skill_name.lower().strip(), candidate_map, position_id=position_id)
        skill_score = match_conf if match_conf is not None else 0.0
        weighted_score += skill_score * weight
        entry = {"skill": skill_name, "score": round(skill_score, 3), "matched": match_conf is not None}
        if eq_explanation:
            entry["equivalency"] = eq_explanation
        core_scores.append(entry)

    for req in position_profile.get("adjacent_skills", []):
        skill_name = req if isinstance(req, str) else req.get("name", "")
        weight = 0.5 if isinstance(req, str) else req.get("weight", 0.5)
        total_weight += weight

        match_conf, eq_explanation = _find_skill_match(skill_name.lower().strip(), candidate_map, position_id=position_id)
        skill_score = match_conf if match_conf is not None else 0.0
        weighted_score += skill_score * weight
        entry = {"skill": skill_name, "score": round(skill_score, 3), "matched": match_conf is not None}
        if eq_explanation:
            entry["equivalency"] = eq_explanation
        adjacent_scores.append(entry)

    fit_score = weighted_score / total_weight if total_weight > 0 else 0.0
    fit_score = max(0.0, min(1.0, fit_score))
    fit_level = _score_to_level(fit_score)

    breakdown = {
        "role": position_profile.get("name", "Custom Position"),
        "core_skills": core_scores,
        "adjacent_skills": adjacent_scores,
    }

    rationale = _generate_rationale(skills, fit_score, fit_level, breakdown)

    return FitResult(fit_score=fit_score, fit_level=fit_level, rationale=rationale, breakdown=breakdown)


def _assess_general(skills: list[dict]) -> FitResult:
    """General assessment when no role or profile is specified."""
    if not skills:
        return FitResult(fit_score=0.0, fit_level="poor", rationale="No skills data available for assessment.", breakdown={})

    confidences = []
    categories = set()
    for s in skills:
        conf = float(s.get("final_confidence") or s.get("llm_confidence") or 0)
        confidences.append(conf)
        cat = s.get("category", "other")
        if cat and cat != "irrelevant":
            categories.add(cat)

    avg_conf = sum(confidences) / len(confidences)
    skill_count = len(skills)
    breadth = len(categories)

    # Heuristic: combine count, confidence, breadth
    count_factor = min(1.0, skill_count / 10)  # max out at 10 skills
    breadth_factor = min(1.0, breadth / 4)  # max out at 4 categories
    fit_score = (avg_conf * 0.5) + (count_factor * 0.3) + (breadth_factor * 0.2)
    fit_score = max(0.0, min(1.0, fit_score))
    fit_level = _score_to_level(fit_score)

    breakdown = {
        "role": "General Assessment",
        "avg_confidence": round(avg_conf, 3),
        "skill_count": skill_count,
        "category_breadth": breadth,
        "categories": sorted(categories),
    }

    rationale = _generate_rationale(skills, fit_score, fit_level, breakdown)

    return FitResult(fit_score=fit_score, fit_level=fit_level, rationale=rationale, breakdown=breakdown)


def _generate_rationale(skills: list[dict], fit_score: float, fit_level: str, breakdown: dict) -> str:
    """Use LLM to generate a 1-2 sentence rationale."""
    try:
        client = get_client("confidence_reasoning")

        skill_summary = ", ".join(
            f"{s.get('skill_name', '?')} ({float(s.get('final_confidence') or s.get('llm_confidence') or 0)*100:.0f}%)"
            for s in skills[:15]
        )

        prompt = (
            f"A candidate has these skills: {skill_summary}.\n"
            f"Their overall fit score is {fit_score:.0%} ({fit_level}).\n"
            f"Breakdown: {json.dumps(breakdown, default=str)}\n\n"
            f"Write a concise 1-2 sentence rationale explaining this fit assessment. "
            f"Focus on key strengths and gaps. Be specific, not generic."
        )

        rationale = client.complete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            system="You are a recruiting analyst. Write concise, specific fit rationales."
        )
        return rationale.strip()
    except Exception as e:
        logger.warning(f"LLM rationale generation failed: {e}")
        # Fallback to template rationale
        if fit_level == "strong":
            return f"Strong fit ({fit_score:.0%}) — candidate demonstrates solid coverage across required skills."
        elif fit_level == "good":
            return f"Good fit ({fit_score:.0%}) — candidate meets most requirements with some gaps."
        elif fit_level == "weak":
            return f"Weak fit ({fit_score:.0%}) — candidate has notable skill gaps for this role."
        else:
            return f"Poor fit ({fit_score:.0%}) — candidate lacks most required skills."


def assess_fit(
    skills: list[dict],
    role_archetype_id: int = None,
    position_profile: dict = None,
    position_id: int = None,
) -> FitResult:
    """Main entry point for fit assessment.

    Args:
        skills: List of skill dicts with skill_name, category, llm_confidence, final_confidence
        role_archetype_id: Optional KB role archetype to assess against
        position_profile: Optional ad-hoc position profile dict with core_skills/adjacent_skills

    Returns:
        FitResult with score, level, rationale, and breakdown
    """
    if role_archetype_id:
        return _assess_with_role(skills, role_archetype_id, position_id=position_id)
    elif position_profile:
        return _assess_with_profile(skills, position_profile)
    else:
        return _assess_general(skills)
