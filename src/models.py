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


class SkillRequirement(BaseModel):
    skill_name: str
    min_confidence: float = 0.0
    weight: float = 1.0


class PositionProfileCreate(BaseModel):
    title: str
    department: str = ""
    description: str = ""
    required_skills: list[SkillRequirement] = []
    preferred_skills: list[SkillRequirement] = []
    min_experience_years: int = 0


class PositionProfileUpdate(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    description: Optional[str] = None
    required_skills: Optional[list[SkillRequirement]] = None
    preferred_skills: Optional[list[SkillRequirement]] = None
    min_experience_years: Optional[int] = None


class PositionProfileResponse(BaseModel):
    id: int
    title: str
    department: str
    description: str
    required_skills: list[SkillRequirement]
    preferred_skills: list[SkillRequirement]
    min_experience_years: int
    created_at: str
    updated_at: str
    is_active: bool
    created_by: str


class JobPostingInput(BaseModel):
    text: str


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


class EquivalencySkill(BaseModel):
    skill_name: str
    weight: float = 1.0

    @field_validator("weight", mode="before")
    @classmethod
    def clamp_weight(cls, v):
        return max(0.0, min(1.0, float(v)))


class EquivalencyGroupCreate(BaseModel):
    name: str
    description: str = ""
    skills: list[EquivalencySkill] = []


class EquivalencyGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    skills: Optional[list[EquivalencySkill]] = None


class EquivalencyGroupResponse(BaseModel):
    id: int
    name: str
    description: str
    skills: list[EquivalencySkill]
    created_at: str


class AssessmentPackage(BaseModel):
    candidate_id: int
    tests: list[str]  # test IDs
    token: str
