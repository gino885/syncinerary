"""M3: cross-source entity resolution. CLAUDE.md section 8.4."""
from __future__ import annotations

from uuid import uuid4

from syncinerary.agents.gather.dedup import dedup_candidates, normalize_name
from syncinerary.domain.models import CandidatePlace, CandidateType, Source


def _place(name: str, lat: float, lng: float, **kwargs) -> CandidatePlace:
    return CandidatePlace(
        trip_id=uuid4(),
        type=CandidateType.ATTRACTION,
        name_canonical=name,
        lat=lat,
        lng=lng,
        **kwargs,
    )


def test_name_normalization_ignores_case_accents_and_punctuation():
    assert normalize_name("Ōno Pond") == normalize_name("ono pond")
    assert normalize_name("Sapporo TV Tower!") == "sapporo tv tower"


def test_the_same_museum_indexed_twice_collapses_to_one_card():
    """Two Google listings metres apart were becoming two stops on two days."""
    candidates = [
        _place("The Hokkaido University Museum", 43.0755, 141.3405),
        _place("Hokkaido University Museum", 43.07551, 141.34052),
    ]

    resolved = dedup_candidates(candidates)

    assert len(resolved) == 1
    assert resolved[0].name_canonical == "The Hokkaido University Museum"


def test_two_different_places_at_the_same_address_stay_separate():
    candidates = [
        _place("Sapporo Art Museum", 43.0100, 141.3600),
        _place("Sapporo Beer Garden", 43.01001, 141.36001),
    ]

    assert len(dedup_candidates(candidates)) == 2


def test_the_same_name_far_apart_stays_separate():
    candidates = [
        _place("Seicomart", 43.0600, 141.3500),
        _place("Seicomart", 43.1900, 140.9900),
    ]

    assert len(dedup_candidates(candidates)) == 2


def test_merging_keeps_every_source_row_and_fills_missing_enrichment():
    discovered = _place(
        "Ramen Yokocho",
        43.0550,
        141.3530,
        sources=[Source(type="discovery", subtype="google_places")],
        enrichment={"google_place_id": "ChIJ-a"},
    )
    from_a_post = _place(
        "Ramen Yokocho",
        43.05501,
        141.35301,
        sources=[Source(type="buzz", sources_count=4)],
        enrichment={"google_place_id": "ChIJ-b", "source_description": "Alley of ramen."},
    )

    merged = dedup_candidates([discovered, from_a_post])

    assert len(merged) == 1
    assert [source.type for source in merged[0].sources] == ["discovery", "buzz"]
    # The surviving card keeps its own identity but gains what it was missing.
    assert merged[0].enrichment["google_place_id"] == "ChIJ-a"
    assert merged[0].enrichment["source_description"] == "Alley of ramen."


def test_dedup_never_reorders_the_pool():
    candidates = [
        _place("First", 43.0600, 141.3500),
        _place("Duplicate target", 43.0700, 141.3600),
        _place("Third", 43.0800, 141.3700),
        _place("Duplicate Target", 43.07001, 141.36001),
    ]

    resolved = dedup_candidates(candidates)

    assert [c.name_canonical for c in resolved] == ["First", "Duplicate target", "Third"]
