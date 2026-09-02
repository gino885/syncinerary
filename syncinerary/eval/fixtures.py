"""Typed fixture loading for the eval harness (CLAUDE.md section 12.3).

A fixture is a hand-written JSON file: a trip, its travelers, their
constraints, a candidate pool, the votes those travelers cast, and what the
run is expected to hold true. Fixtures are written rather than captured from
live runs, because a captured fixture drifts with the providers and stops
being a fixed yardstick.

Parsing is strict. Every model here forbids unknown keys, so a mistyped
field in a fixture is an error rather than a silently skipped assertion. That
matters more here than anywhere else in the codebase: a scorer that never
runs looks exactly like a scorer that passed.
"""
from __future__ import annotations

import json
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from syncinerary.domain.models import (
    CandidatePlace,
    CandidateType,
    Constraint,
    ConstraintKind,
    Traveler,
    Trip,
    TripState,
    Vote,
    VoteSignal,
)
from syncinerary.tools.weather import WeatherDay, WeatherForecast

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Fixtures name their entities with short slugs ("odori-park"). Every id is
# derived from the fixture name and that slug, so the same fixture produces
# the same uuids on every machine and a stored eval_result stays comparable
# across runs and commits.
_ID_NAMESPACE = UUID("6f9f7d38-5c2f-4a2a-9a0f-9f6b1a4d2c11")

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def fixture_uuid(fixture_name: str, kind: str, slug: str) -> UUID:
    """A stable uuid for one named thing inside one fixture."""
    return uuid5(_ID_NAMESPACE, f"{fixture_name}/{kind}/{slug}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TravelerSpec(_Strict):
    slug: str
    name: str
    home_city: str | None = None
    interests: list[str] = Field(default_factory=list)
    #: Hard dietary exclusions become a `dietary` constraint of kind `hard`.
    dietary_excludes: list[str] = Field(default_factory=list)


class ConstraintSpec(_Strict):
    type: str
    #: A traveler slug, or None for a group-level constraint.
    traveler: str | None = None
    kind: Literal["hard", "soft"] = "hard"
    priority: int = 1
    value: dict[str, Any] = Field(default_factory=dict)


class CandidateSpec(_Strict):
    slug: str
    name: str
    type: Literal["attraction", "food", "lodging"] = "attraction"
    lat: float
    lng: float
    area: str | None = None
    category: str | None = None
    price_tier: int = 2
    duration_min: int = 60
    fatigue_cost: int = 2
    weather_dependent: bool = False
    dietary_tags: list[str] = Field(default_factory=list)
    #: Open hours as [start_hour, end_hour] on every weekday, unless
    #: `hours_by_weekday` spells out something narrower.
    open_hours: list[int] = Field(default=[8, 21])
    hours_by_weekday: dict[str, list[list[int]]] | None = None
    #: Kept out of the shortlist and used only as a replan alternative.
    spare: bool = False

    @model_validator(mode="after")
    def _check_hours(self) -> CandidateSpec:
        if len(self.open_hours) != 2 or self.open_hours[0] >= self.open_hours[1]:
            raise ValueError(f"{self.slug}: open_hours must be [start, end] with start < end")
        return self

    def hours(self) -> dict[str, list[list[int]]]:
        if self.hours_by_weekday is not None:
            return self.hours_by_weekday
        return {weekday: [list(self.open_hours)] for weekday in WEEKDAYS}


class VoteSpec(_Strict):
    traveler: str
    candidate: str
    signal: Literal["like", "dislike", "like_with_note", "must_have"] = "like"
    note_text: str | None = None


class WeatherSpec(_Strict):
    #: Zero-based trip day.
    day: int
    precipitation_probability: int = Field(ge=0, le=100)


class DisruptionSpec(_Strict):
    trigger: Literal[
        "reservation_cancelled",
        "transit_delay",
        "overslept",
        "place_closed",
        "weather",
        "other",
    ]
    #: Which stop of the seeded itinerary is hit, by zero-based position
    #: within its day. Injectors resolve it to a real node id.
    day: int = 0
    stop_index: int = 0
    delay_minutes: int | None = None
    #: Local clock time the group actually got going, for `overslept`.
    at: str | None = None


class ExpectationSpec(_Strict):
    """What the run has to hold true. Absent keys are simply not asserted."""

    #: Candidate slugs that must appear in the itinerary.
    must_include: list[str] = Field(default_factory=list)
    #: Candidate slugs that must never appear.
    must_exclude: list[str] = Field(default_factory=list)
    #: Slugs the group marked must-go. These are pinned for the solver and
    #: are also checked by the feasibility family.
    must_go: list[str] = Field(default_factory=list)
    #: Slugs pinned to a specific zero-based day.
    pinned_days: dict[str, int] = Field(default_factory=dict)
    #: Floors on quality metrics, by metric name.
    min_scores: dict[str, float] = Field(default_factory=dict)
    #: For disruption fixtures: the day the proposal is allowed to change.
    replan_day: int | None = None


class EvalFixture(_Strict):
    name: str
    description: str
    destination: str
    cities: list[str] = Field(default_factory=list)
    country: str | None = None
    start_date: date
    days: int = Field(gt=0)
    day_start_hour: int = 8
    day_end_hour: int = 21
    travelers: list[TravelerSpec]
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    candidates: list[CandidateSpec]
    votes: list[VoteSpec] = Field(default_factory=list)
    weather: list[WeatherSpec] = Field(default_factory=list)
    disruption: DisruptionSpec | None = None
    expected: ExpectationSpec = Field(default_factory=ExpectationSpec)

    @model_validator(mode="after")
    def _check_references(self) -> EvalFixture:
        traveler_slugs = {traveler.slug for traveler in self.travelers}
        candidate_slugs = {candidate.slug for candidate in self.candidates}
        if len(traveler_slugs) != len(self.travelers):
            raise ValueError(f"{self.name}: duplicate traveler slug")
        if len(candidate_slugs) != len(self.candidates):
            raise ValueError(f"{self.name}: duplicate candidate slug")

        def require(kind: str, slug: str, known: set[str]) -> None:
            if slug not in known:
                raise ValueError(f"{self.name}: unknown {kind} {slug!r}")

        for vote in self.votes:
            require("traveler", vote.traveler, traveler_slugs)
            require("candidate", vote.candidate, candidate_slugs)
        for constraint in self.constraints:
            if constraint.traveler is not None:
                require("traveler", constraint.traveler, traveler_slugs)
        for group in (
            self.expected.must_include,
            self.expected.must_exclude,
            self.expected.must_go,
            list(self.expected.pinned_days),
        ):
            for slug in group:
                require("candidate", slug, candidate_slugs)
        for spec in self.weather:
            if not 0 <= spec.day < self.days:
                raise ValueError(f"{self.name}: weather day {spec.day} is outside the trip")
        return self

    @property
    def is_disruption(self) -> bool:
        return self.disruption is not None

    @property
    def end_date(self) -> date:
        return self.start_date + timedelta(days=self.days - 1)


class LoadedFixture(BaseModel):
    """A fixture resolved into the domain objects the pipeline consumes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: EvalFixture
    trip: Trip
    travelers: list[Traveler]
    constraints: list[Constraint]
    #: Everything the fixture declares, spares included.
    candidates: list[CandidatePlace]
    votes: list[Vote]
    weather: WeatherForecast
    #: slug -> id and id -> slug, so scorers can report in the fixture's own
    #: vocabulary rather than in uuids.
    ids_by_slug: dict[str, UUID]
    slugs_by_id: dict[UUID, str]

    @property
    def pool(self) -> list[CandidatePlace]:
        """The candidates that go to the deck. Spares are replan stock only."""
        spare = {
            self.ids_by_slug[candidate.slug]
            for candidate in self.spec.candidates
            if candidate.spare
        }
        return [candidate for candidate in self.candidates if candidate.id not in spare]

    @property
    def spares(self) -> list[CandidatePlace]:
        spare = {
            self.ids_by_slug[candidate.slug]
            for candidate in self.spec.candidates
            if candidate.spare
        }
        return [candidate for candidate in self.candidates if candidate.id in spare]

    def slugs(self, ids: list[UUID]) -> list[str]:
        return [self.slugs_by_id.get(value, str(value)) for value in ids]

    def state(self) -> TripState:
        return TripState(
            trip=self.trip,
            travelers=self.travelers,
            constraints=self.constraints,
            candidates=self.pool,
            votes=self.votes,
            day_start=time(self.spec.day_start_hour),
            day_end=time(self.spec.day_end_hour),
        )


def _constraints_for(spec: EvalFixture, traveler_ids: dict[str, UUID], trip_id: UUID) -> list[Constraint]:
    constraints: list[Constraint] = []
    # A traveler's dietary exclusions are written as a plain list on the
    # traveler for legibility, then expanded into the constraint shape the
    # pipeline reads. Keeps a fixture readable without inventing a second
    # dietary mechanism.
    for traveler in spec.travelers:
        if traveler.dietary_excludes:
            constraints.append(
                Constraint(
                    id=fixture_uuid(spec.name, "constraint", f"{traveler.slug}-dietary"),
                    trip_id=trip_id,
                    traveler_id=traveler_ids[traveler.slug],
                    type="dietary",
                    value={"excludes": list(traveler.dietary_excludes)},
                    kind=ConstraintKind.HARD,
                )
            )
    for index, constraint in enumerate(spec.constraints):
        constraints.append(
            Constraint(
                id=fixture_uuid(spec.name, "constraint", f"{constraint.type}-{index}"),
                trip_id=trip_id,
                traveler_id=(
                    traveler_ids[constraint.traveler] if constraint.traveler else None
                ),
                type=constraint.type,
                value=constraint.value,
                priority=constraint.priority,
                kind=ConstraintKind(constraint.kind),
            )
        )
    return constraints


def load_fixture(spec: EvalFixture) -> LoadedFixture:
    """Resolve a parsed fixture into domain objects with stable ids."""
    trip_id = fixture_uuid(spec.name, "trip", spec.name)
    trip = Trip(
        id=trip_id,
        destination=spec.destination,
        cities=spec.cities or [spec.destination],
        country=spec.country,
        start_date=spec.start_date,
        end_date=spec.end_date,
        days=spec.days,
    )

    traveler_ids = {
        traveler.slug: fixture_uuid(spec.name, "traveler", traveler.slug)
        for traveler in spec.travelers
    }
    travelers = [
        Traveler(
            id=traveler_ids[traveler.slug],
            trip_id=trip_id,
            name=traveler.name,
            home_city=traveler.home_city,
            profile={"interests": list(traveler.interests)},
        )
        for traveler in spec.travelers
    ]

    candidate_ids = {
        candidate.slug: fixture_uuid(spec.name, "candidate", candidate.slug)
        for candidate in spec.candidates
    }
    candidates = [
        CandidatePlace(
            id=candidate_ids[candidate.slug],
            trip_id=trip_id,
            type=CandidateType(candidate.type),
            name_canonical=candidate.name,
            lat=candidate.lat,
            lng=candidate.lng,
            area=candidate.area,
            hours_by_weekday=candidate.hours(),
            price_tier=candidate.price_tier,
            duration_estimate_min=candidate.duration_min,
            dietary_tags=list(candidate.dietary_tags),
            weather_dependent=candidate.weather_dependent,
            fatigue_cost=candidate.fatigue_cost,
            category=candidate.category,
        )
        for candidate in spec.candidates
    ]

    votes = [
        Vote(
            id=fixture_uuid(spec.name, "vote", f"{vote.traveler}-{vote.candidate}"),
            candidate_id=candidate_ids[vote.candidate],
            traveler_id=traveler_ids[vote.traveler],
            signal=VoteSignal(vote.signal),
            note_text=vote.note_text,
        )
        for vote in spec.votes
    ]

    rain_by_day = {entry.day: entry.precipitation_probability for entry in spec.weather}
    weather = WeatherForecast(
        days=[
            WeatherDay(
                date=spec.start_date + timedelta(days=day),
                precipitation_probability_max=rain_by_day.get(day, 0),
                # WMO codes: 61 is rain, 1 is mainly clear. `is_rainy` reads
                # both this and the probability, so a fixture that says
                # "it rains" has to say it in both places or the solver and
                # the scorer would disagree about the same day.
                weather_code=61 if rain_by_day.get(day, 0) >= 50 else 1,
                precipitation_sum_mm=round(rain_by_day.get(day, 0) / 10, 1),
            )
            for day in range(spec.days)
        ]
    )

    return LoadedFixture(
        spec=spec,
        trip=trip,
        travelers=travelers,
        constraints=_constraints_for(spec, traveler_ids, trip_id),
        candidates=candidates,
        votes=votes,
        weather=weather,
        ids_by_slug=candidate_ids | traveler_ids,
        slugs_by_id={value: key for key, value in (candidate_ids | traveler_ids).items()},
    )


def parse_fixture(path: Path) -> EvalFixture:
    spec = EvalFixture.model_validate_json(path.read_text())
    if spec.name != path.stem:
        raise ValueError(f"{path.name}: fixture name {spec.name!r} does not match the file name")
    return spec


def fixture_paths(directory: Path | None = None) -> list[Path]:
    return sorted((directory or FIXTURE_DIR).glob("*.json"))


def load_all(directory: Path | None = None) -> list[LoadedFixture]:
    """Every fixture on disk, in file-name order so runs are comparable."""
    return [load_fixture(parse_fixture(path)) for path in fixture_paths(directory)]


def load_by_name(name: str, directory: Path | None = None) -> LoadedFixture:
    path = (directory or FIXTURE_DIR) / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"No fixture named {name!r} in {directory or FIXTURE_DIR}")
    return load_fixture(parse_fixture(path))


def dump_fixture(spec: EvalFixture, path: Path) -> None:
    """Write a fixture back out, used by the fixture round-trip test."""
    path.write_text(json.dumps(spec.model_dump(mode="json"), indent=2) + "\n")


__all__ = [
    "FIXTURE_DIR",
    "WEEKDAYS",
    "CandidateSpec",
    "ConstraintSpec",
    "DisruptionSpec",
    "EvalFixture",
    "ExpectationSpec",
    "LoadedFixture",
    "TravelerSpec",
    "VoteSpec",
    "WeatherSpec",
    "dump_fixture",
    "fixture_paths",
    "fixture_uuid",
    "load_all",
    "load_by_name",
    "load_fixture",
    "parse_fixture",
]
