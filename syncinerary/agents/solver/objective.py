"""Bounded soft-objective weights consumed by the deterministic solver."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SolverObjectiveWeights(BaseModel):
    """Relative costs that can never relax a hard constraint."""

    dispersion: int = Field(default=20, ge=0, le=100)
    diversity: int = Field(default=15, ge=0, le=100)
    weather: int = Field(default=30, ge=0, le=100)
    vote: int = Field(default=25, ge=0, le=100)
    conditional: int = Field(default=35, ge=0, le=100)

__all__ = ["SolverObjectiveWeights"]
