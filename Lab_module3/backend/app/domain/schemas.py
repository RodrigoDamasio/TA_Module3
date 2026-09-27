"""Pydantic models for LLM output: lenient twins (sent to Gemini) + strict models (validated
locally). Same approach as Lab 2 — Gemini accepts only a subset of JSON Schema."""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "info"]
ComplexityLevel = Literal["low", "medium", "high"]


# ---- Analyzer --------------------------------------------------------------------


class AnalysisLLM(BaseModel):
    summary: str
    components: list[str]
    dependencies: list[str]
    patterns: list[str]
    risks: list[str]


class AnalysisOut(BaseModel):
    summary: str = Field(min_length=10, max_length=1200)
    components: list[str] = Field(max_length=20)
    dependencies: list[str] = Field(max_length=20)
    patterns: list[str] = Field(max_length=20)
    risks: list[str] = Field(max_length=15)


# ---- Planner ---------------------------------------------------------------------


class PlanStepLLM(BaseModel):
    id: int
    title: str
    description: str
    depends_on: list[int]
    complexity: ComplexityLevel
    source_files: list[str]
    target_files: list[str]


class PlanLLM(BaseModel):
    steps: list[PlanStepLLM]


class PlanStepOut(BaseModel):
    id: int = Field(ge=1)
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=1500)
    depends_on: list[int]
    complexity: ComplexityLevel
    source_files: list[str]
    target_files: list[str] = Field(min_length=1, max_length=5)


class PlanOut(BaseModel):
    steps: list[PlanStepOut] = Field(min_length=1)


# ---- Executor --------------------------------------------------------------------


class GeneratedFileLLM(BaseModel):
    path: str
    content: str


class StepLLM(BaseModel):
    files: list[GeneratedFileLLM]
    notes: str


class GeneratedFile(BaseModel):
    path: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=60000)


class StepOut(BaseModel):
    files: list[GeneratedFile] = Field(min_length=1, max_length=5)
    notes: str = Field(default="", max_length=2000)


# ---- Verifier --------------------------------------------------------------------


class IssueLLM(BaseModel):
    severity: Severity
    file: str
    line: int | None
    message: str


class VerificationLLM(BaseModel):
    issues: list[IssueLLM]
    confidence: int
    verdict: Literal["pass", "fail"]


class IssueOut(BaseModel):
    severity: Severity
    file: str = Field(max_length=120)
    line: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=3, max_length=800)


class VerificationOut(BaseModel):
    issues: list[IssueOut] = Field(max_length=20)
    confidence: int = Field(ge=1, le=10)
    verdict: Literal["pass", "fail"]
