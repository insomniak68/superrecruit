from pydantic import BaseModel, field_validator
from typing import Optional


class SkillAssessment(BaseModel):
    skill_name: str
    category: str
    evidence: str
    llm_confidence: float
    final_confidence: Optional[float] = None
    reasoning: str

    @field_validator("llm_confidence", "final_confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v):
        if v is None:
            return v
        return max(0.0, min(1.0, float(v)))


class CandidateCreate(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None


class CandidateResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str]
    resume_path: Optional[str]
    skills: list[SkillAssessment] = []
    created_at: str


class TestQuestion(BaseModel):
    id: str
    type: str  # coding, multiple_choice, short_answer, code_review
    difficulty: str
    prompt: str
    test_cases: list[dict] = []
    rubric: Optional[str] = None
    options: list[str] = []
    correct_answer: Optional[str] = None
    points: int = 10


class TestBank(BaseModel):
    id: str
    name: str
    category: str
    skill_tags: list[str]
    time_limit_minutes: int
    passing_score: int
    questions: list[TestQuestion]


class AssessmentPackage(BaseModel):
    candidate_id: int
    tests: list[str]  # test IDs
    token: str
