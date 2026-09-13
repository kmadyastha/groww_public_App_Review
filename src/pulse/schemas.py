"""Domain contracts for the Groww weekly review pulse.

RawReview must not carry reviewer identity. PulseNote is locked to 3 themes,
3 quotes, and 3 actions (problem-statement invariants).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Store = Literal["play", "app_store"]
OwnerHint = Literal["Product", "Support", "Growth"]
PulseStatus = Literal["loading", "ready", "published", "failed"]
Severity = Literal["low", "medium", "high"]

GROW_PLAY_ID = "com.nextbillion.groww"
GROW_APP_STORE_ID = "1404871703"


class RawReview(BaseModel):
    """Public-store review after parse. No author, email, or device fields."""

    model_config = ConfigDict(extra="forbid")

    store: Store
    review_id_source: str
    rating: int = Field(ge=1, le=5)
    title: str | None = None
    text: str
    date: date
    locale: str = "en_IN"


class SanitizedReview(BaseModel):
    """Review after PII redaction. review_id is an opaque hash, not the store id."""

    model_config = ConfigDict(extra="forbid")

    review_id: str
    store: Store
    rating: int = Field(ge=1, le=5)
    title: str | None = None
    text: str
    date: date
    locale: str = "en_IN"


class ThemeCluster(BaseModel):
    name: str
    review_ids: list[str]
    count: int = Field(ge=0)
    avg_rating: float = Field(ge=1.0, le=5.0)
    severity: Severity
    play_count: int = Field(default=0, ge=0)
    app_store_count: int = Field(default=0, ge=0)


class Quote(BaseModel):
    """Verbatim snippet copied from a sanitized review (never model-invented)."""

    review_id: str
    text: str
    rating: int = Field(ge=1, le=5)
    store: Store
    date: date


class ActionIdea(BaseModel):
    title: str
    rationale: str
    theme: str
    owner_hint: OwnerHint


class ThemeHighlight(BaseModel):
    """One of the top-3 themes shown in the written pulse."""

    name: str
    summary: str


class PulseNote(BaseModel):
    """Structured weekly pulse: exactly 3 themes, 3 quotes, 3 actions."""

    title: str
    themes: Annotated[list[ThemeHighlight], Field(min_length=3, max_length=3)]
    quotes: Annotated[list[Quote], Field(min_length=3, max_length=3)]
    actions: Annotated[list[ActionIdea], Field(min_length=3, max_length=3)]
    body: str = ""

    @field_validator("quotes")
    @classmethod
    def _distinct_quote_ids(cls, quotes: list[Quote]) -> list[Quote]:
        ids = [q.review_id for q in quotes]
        if len(set(ids)) != len(ids):
            raise ValueError("quotes must come from three distinct review_ids")
        return quotes


class DateWindow(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _end_on_or_after_start(self) -> DateWindow:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ProductInfo(BaseModel):
    name: str
    android_id: str
    ios_id: str
    locale: str


class DocRef(BaseModel):
    document_id: str
    url: str


class EmailRef(BaseModel):
    draft_id: str = ""
    message_id: str | None = None
    sent: bool = False


class PublishResult(BaseModel):
    """MCP publish/notify outcome. Draft and optional send id."""

    document_id: str | None = None
    url: str | None = None
    draft_id: str | None = None
