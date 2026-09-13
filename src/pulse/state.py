"""LangGraph run state. Downstream nodes never re-fetch raw reviews."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from pulse.schemas import (
    ActionIdea,
    DateWindow,
    DocRef,
    EmailRef,
    ProductInfo,
    PulseNote,
    PulseStatus,
    Quote,
    RawReview,
    SanitizedReview,
    ThemeCluster,
)


class PulseState(BaseModel):
    run_id: str
    window: DateWindow
    product: ProductInfo
    reviews: list[SanitizedReview] = Field(default_factory=list)
    raw_reviews: list[RawReview] = Field(default_factory=list)
    clusters: list[ThemeCluster] = Field(default_factory=list)
    quotes: list[Quote] = Field(default_factory=list)
    actions: list[ActionIdea] = Field(default_factory=list)
    pulse: PulseNote | None = None
    snapshot_path: str | None = None
    doc: DocRef | None = None
    email: EmailRef | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: PulseStatus = "loading"
    write_attempts: int = Field(default=0, ge=0)
    validation_passed: bool = False

    @field_validator("clusters")
    @classmethod
    def _at_most_five_themes(cls, clusters: list[ThemeCluster]) -> list[ThemeCluster]:
        if len(clusters) > 5:
            raise ValueError("clusters must contain at most 5 themes")
        return clusters
