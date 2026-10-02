"""Deterministic source coverage of deduplicated, visible swipe cards."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable

from opentelemetry import trace
from pydantic import BaseModel

from syncinerary.agents.gather.dedup import dedup_candidates, merge_candidate_evidence
from syncinerary.config.gather import REEL_TARGET_RATIO
from syncinerary.domain.models import CandidatePlace, CandidateType, SocialPlatform
from syncinerary.tools.fetch.social import normalize_social_url

logger = logging.getLogger(__name__)


def is_reel_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        ref = normalize_social_url(value)
    except ValueError:
        return False
    return ref.platform is SocialPlatform.INSTAGRAM and "/reel/" in ref.canonical_url


def has_reel(candidate: CandidatePlace, *, automatic: bool = False) -> bool:
    # Structured post evidence is produced by extraction, not by a generic
    # source badge or a Google photo. Personal links count only in visible mix.
    if any(s.type == "buzz" for s in candidate.sources):
        if any(
            is_reel_url(p.get("url"))
            for p in candidate.enrichment.get("social_posts", [])
            if isinstance(p, dict)
        ):
            return True
        if any(s.type == "buzz" and is_reel_url(s.url) for s in candidate.sources):
            return True
    return not automatic and any(
        s.type == "personal"
        and s.subtype == "user_paste"
        and is_reel_url(s.url or candidate.enrichment.get("source_url"))
        for s in candidate.sources
    )


class SourceMix(BaseModel):
    total: int
    reels: int
    other_social: int
    google_only: int
    other: int
    reel_share: float
    google_only_share: float
    majority_met: bool
    target_met: bool
    target_shortfall: int


class SourceMixReport(BaseModel):
    visible: SourceMix
    automatic: SourceMix
    by_city: dict[str, SourceMix]
    by_category: dict[str, SourceMix]


def _mix(cards: list[CandidatePlace], *, automatic: bool) -> SourceMix:
    reels = other_social = google = 0
    for card in cards:
        sources = [
            s
            for s in card.sources
            if not (automatic and s.type == "personal" and s.subtype == "user_paste")
        ]
        if has_reel(card, automatic=automatic):
            reels += 1
        elif any(s.type == "buzz" for s in card.sources):
            other_social += 1
        elif (
            all(s.type == "discovery" and s.subtype == "google_places" for s in sources) and sources
        ):
            google += 1
    total = len(cards)
    return SourceMix(
        total=total,
        reels=reels,
        other_social=other_social,
        google_only=google,
        other=total - reels - other_social - google,
        reel_share=reels / total if total else 0,
        google_only_share=google / total if total else 0,
        majority_met=bool(total and reels * 2 > total),
        target_met=bool(total and reels >= math.ceil(total * REEL_TARGET_RATIO)),
        target_shortfall=max(0, math.ceil(total * REEL_TARGET_RATIO) - reels),
    )


def source_mix_report(candidates: Iterable[CandidatePlace]) -> SourceMixReport:
    by_id: dict[str, CandidatePlace] = {}
    for card in candidates:
        if card.type is CandidateType.LODGING:
            continue
        key = card.enrichment.get("google_place_id") or str(card.id)
        existing = by_id.get(key)
        by_id[key] = merge_candidate_evidence(existing, card) if existing else card
    cards = dedup_candidates(list(by_id.values()))
    automatic = [
        c
        for c in cards
        if any(s.type in {"buzz", "discovery"} or s.subtype == "profile_driven" for s in c.sources)
    ]
    return SourceMixReport(
        visible=_mix(cards, automatic=False),
        automatic=_mix(automatic, automatic=True),
        by_city={
            city: _mix(
                [c for c in automatic if (c.enrichment.get("city") or "unknown") == city],
                automatic=True,
            )
            for city in sorted({c.enrichment.get("city") or "unknown" for c in automatic})
        },
        by_category={
            kind: _mix([c for c in automatic if c.type.value == kind], automatic=True)
            for kind in sorted({c.type.value for c in automatic})
        },
    )


def record_source_mix(candidates: list[CandidatePlace]) -> SourceMixReport:
    report = source_mix_report(candidates)
    span = trace.get_current_span()
    for group, mix in (("visible", report.visible), ("automatic", report.automatic)):
        for key, value in mix.model_dump().items():
            span.set_attribute(f"gather.source_mix.{group}.{key}", value)
    for city, mix in report.by_city.items():
        span.set_attribute(f"gather.source_mix.city.{city}.reel_share", mix.reel_share)
    logger.info("gather.source_mix %s", report.model_dump_json())
    return report
