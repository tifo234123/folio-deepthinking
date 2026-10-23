from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    source_id: str
    quote: str = Field(min_length=3, max_length=2400)


class Finding(StrictModel):
    category: Literal["main", "definition", "formula", "method", "data"]
    title: str = Field(min_length=1, max_length=250)
    content: str = Field(min_length=1, max_length=8000)
    details: dict[str, str] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(min_length=1, max_length=12)


class Extraction(StrictModel):
    findings: list[Finding] = Field(max_length=40)


class SectionSpec(StrictModel):
    title: str = Field(min_length=1, max_length=250)
    parent_index: int | None = None
    source_ids: list[str] = Field(min_length=1)


class StructureSpec(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    sections: list[SectionSpec] = Field(min_length=1, max_length=200)


class AnswerPart(StrictModel):
    text: str = Field(min_length=1, max_length=12000)
    kind: Literal["source", "explanation", "status"]
    source_ids: list[str] = Field(default_factory=list)


class Action(StrictModel):
    tool: Literal["search", "sections", "read_source", "coverage", "extract", "propose_structure", "save_note", "navigate", "list_books"]
    arguments: dict = Field(default_factory=dict)


class AssistantResponse(StrictModel):
    parts: list[AnswerPart] = Field(default_factory=list, max_length=20)
    action: Action | None = None

