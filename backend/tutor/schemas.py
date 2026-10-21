"""Data shapes shared across the tutor package (pydantic, extra='forbid')."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Chunk(BaseModel):
    """One search_docs hit: a cited passage of the official corpus."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: UUID
    url: str
    anchor: str | None
    heading_path: str
    content: str
    tier: int
    fetched_at: datetime | None
    score: float

    @property
    def cite_url(self) -> str:
        """URL with the heading anchor, the form the tutor puts in citations."""
        return f"{self.url}#{self.anchor}" if self.anchor else self.url
