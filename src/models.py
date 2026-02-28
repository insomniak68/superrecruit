from pydantic import BaseModel
from typing import Optional
from enum import Enum


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SkillAssessment(BaseModel):
    skill_name: str
    category: str
    evidence: str
    llm_confidence: Confidence
    final_confidence: Optional[Confidence] = None
    reasoning: str


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
