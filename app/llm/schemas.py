"""Structured LLM output contract (spec section 17). The LLM must return
JSON matching this shape; anything else fails validation and is never
persisted. This is the raw, untrusted shape — app/llm/decision_generator.py
additionally enforces number-grounding and taxonomy rules on top of it.
"""

from typing import Literal

from pydantic import BaseModel, field_validator, ConfigDict, Field

from app.decisions.taxonomy import DECISION_TYPES


class ExpectedImpactItem(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    metric: str
    direction: Literal["increase", "decrease", "stabilize"]
    type: Literal["qualitative", "quantitative"]
    value: float | None = None
    unit: str | None = None


class LLMDecisionOutput(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid', str_max_length=2000)
    title: str = Field(min_length=1,max_length=200)
    summary: str = Field(min_length=1,max_length=2000)
    decision_type: str
    action_id: str | None = None
    problem_signal: str
    recommended_decision: str
    reasoning: list[str]
    expected_impact: list[ExpectedImpactItem]
    department: str = "finance"
    support_departments: list[str] = []

    @field_validator("decision_type")
    @classmethod
    def _decision_type_known(cls, v: str) -> str:
        if v not in DECISION_TYPES:
            raise ValueError(f"decision_type '{v}' is not in the fixed taxonomy")
        return v

    @field_validator("reasoning")
    @classmethod
    def _reasoning_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("reasoning must contain at least one item")
        return v
