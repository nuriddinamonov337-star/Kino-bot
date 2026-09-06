"""Typed job contracts shared by handlers and background workers."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReelGenerationJob:
    movie_id: UUID
    job_id: UUID | None = None
