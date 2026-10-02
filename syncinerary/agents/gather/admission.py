"""One deterministic identity gate for resolved discovery results."""

from __future__ import annotations

import math
import re
import unicodedata
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from syncinerary.agents.gather.traits import is_visitable_place
from syncinerary.domain.models import CandidateType
from syncinerary.obs.tracing import get_tracer
from syncinerary.tools.places import PlaceMatch, ResolvedCity
from syncinerary.tools.places.google_places import haversine_km

FOOD_TYPES = frozenset(
    {
        "bakery",
        "bar",
        "cafe",
        "coffee_shop",
        "food_court",
        "ice_cream_shop",
        "market",
        "restaurant",
        "steak_house",
        "tea_house",
        "pub",
        "wine_bar",
        "bistro",
        "diner",
        "noodle_shop",
        "deli",
        "bar_and_grill",
        "beer_garden",
        "brewpub",
        "gastropub",
        "cat_cafe",
        "dog_cafe",
        "pastry_shop",
        "bagel_shop",
    }
)
LODGING_TYPES = frozenset(
    {
        "bed_and_breakfast",
        "campground",
        "extended_stay_hotel",
        "guest_house",
        "hostel",
        "hotel",
        "lodging",
        "motel",
        "resort_hotel",
    }
)
ATTRACTION_TYPES = frozenset(
    {
        "tourist_attraction",
        "museum",
        "art_gallery",
        "park",
        "national_park",
        "botanical_garden",
        "garden",
        "beach",
        "hiking_area",
        "zoo",
        "aquarium",
        "amusement_park",
        "historical_landmark",
        "historical_place",
        "monument",
        "cultural_landmark",
        "cultural_center",
        "shopping_mall",
        "plaza",
        "observation_deck",
        "scenic_spot",
        "natural_feature",
        "buddhist_temple",
        "hindu_temple",
        "shinto_shrine",
        "church",
        "mosque",
        "synagogue",
        "place_of_worship",
        "performing_arts_theater",
        "opera_house",
        "library",
        "public_bath",
        "spa",
        "hot_spring",
        "ski_resort",
        "visitor_center",
        "art_museum",
        "history_museum",
        "city_park",
        "state_park",
        "sculpture",
        "castle",
        "fountain",
        "landmark",
        "bridge",
        "amusement_center",
        "tourist_information_center",
        "planetarium",
        "wildlife_park",
        "wildlife_refuge",
        "water_park",
        "ferris_wheel",
        "night_club",
    }
)


class AdmissionReason(StrEnum):
    ACCEPTED = "accepted"
    ADMINISTRATIVE = "administrative_area"
    GENERIC = "generic_category_name"
    GUIDE = "guide_or_collection"
    EVENT = "event_or_campaign"
    UNSUPPORTED = "unsupported_place_type"
    IDENTITY = "insufficient_identity"
    OUTSIDE = "outside_city"


class CandidateAdmission(BaseModel):
    accepted: bool
    reason_code: AdmissionReason
    evidence_level: Literal["social_and_places", "places_strong", "places_weak"]
    evidence: dict[str, str | bool | int | None]


def supported_candidate_type(place: PlaceMatch) -> CandidateType | None:
    # A primary type is authoritative. Secondary restaurant tags on museums
    # describe amenities and must not turn a museum into a meal.
    kinds = {place.primary_type} if place.primary_type else set(place.types)
    if kinds & LODGING_TYPES:
        return CandidateType.LODGING
    if kinds & FOOD_TYPES or any(t.endswith("_restaurant") for t in kinds):
        return CandidateType.FOOD
    if kinds & ATTRACTION_TYPES:
        return CandidateType.ATTRACTION
    return None


def _normalized(value: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


_GENERIC = {
    "food",
    "restaurants",
    "nightlife",
    "lights",
    "attractions",
    "sightseeing",
    "travel",
    "guide",
    "itinerary",
    "shopping",
    "美食",
    "餐厅",
    "餐廳",
    "夜生活",
    "灯光",
    "燈光",
    "景点",
    "景點",
    "观光",
    "觀光",
    "旅游",
    "旅遊",
    "购物",
    "購物",
}
# Whole-name matching only. An institution containing 'Tokyo' is not generic.
_GENERIC_NAME = re.compile(
    r"^(?:[a-z]+(?:\s+[a-z]+){0,3})\s+(?:food|restaurants|nightlife|lights|"
    r"attractions|sightseeing|travel|shopping)$",
    re.IGNORECASE,
)
_GUIDE = re.compile(
    r"攻略|行程推荐|行程推薦|\b(?:itinerary|travel guide|tour package|top \d+)\b|"
    r"\btours?\s*[-–]|\b(?:walking|bus|private|guided) tours?\b",
    re.IGNORECASE,
)
_EVENT = re.compile(
    r"\b(?:festival|campaign)$|\bfestival of\b|"
    r"\b(?:projection mapping|night\s*(?:&|and)\s*light)\b|"
    r"投影秀|燈光秀|灯光秀|夜晚與燈光|夜晚与灯光",
    re.IGNORECASE,
)


def name_rejection(name: str, destination: str) -> AdmissionReason | None:
    if _GUIDE.search(name):
        return AdmissionReason.GUIDE
    if _EVENT.search(name):
        return AdmissionReason.EVENT
    normalized = _normalized(name)
    city = _normalized(destination)
    suffix = normalized.removeprefix(city) if city else normalized
    if suffix in _GENERIC or _GENERIC_NAME.fullmatch(name.strip()):
        return AdmissionReason.GENERIC
    # Localized provider names can differ from the canonical English city.
    if re.fullmatch(r"[\u3400-\u9fff]{1,8}(?:美食|夜生活|购物|購物|景点|景點)", normalized):
        return AdmissionReason.GENERIC
    return None


def admit_place(
    place: PlaceMatch,
    *,
    destination: str,
    city: ResolvedCity | None = None,
    social_evidence: bool = False,
) -> CandidateAdmission:
    evidence = {
        "place_id": place.place_id,
        "primary_type": place.primary_type,
        "has_hours": bool(place.hours_by_weekday),
        "has_summary": bool(place.editorial_summary),
        "has_website": bool(place.website_uri),
        "has_phone": bool(place.phone_number),
        "rating_count": place.user_rating_count,
        "business_status": place.business_status,
        "social_evidence": social_evidence,
    }
    strong = any(
        (
            evidence["has_hours"],
            evidence["has_summary"],
            evidence["has_website"],
            evidence["has_phone"],
            (place.user_rating_count or 0) > 0,
        )
    )
    reason = AdmissionReason.ACCEPTED
    if not is_visitable_place(place.primary_type, place.types):
        reason = AdmissionReason.ADMINISTRATIVE
    elif rejected := name_rejection(place.display_name, destination):
        reason = rejected
    elif supported_candidate_type(place) is None:
        reason = AdmissionReason.UNSUPPORTED
    elif (
        not place.place_id.strip()
        or not place.display_name.strip()
        or not math.isfinite(place.lat)
        or not math.isfinite(place.lng)
        or not -90 <= place.lat <= 90
        or not -180 <= place.lng <= 180
        or place.business_status == "CLOSED_PERMANENTLY"
    ):
        reason = AdmissionReason.IDENTITY
    elif city and haversine_km((city.lat, city.lng), (place.lat, place.lng)) > city.radius_km:
        reason = AdmissionReason.OUTSIDE
    elif not social_evidence and not strong:
        reason = AdmissionReason.IDENTITY
    accepted = reason == AdmissionReason.ACCEPTED
    decision = CandidateAdmission(
        accepted=accepted,
        reason_code=reason,
        evidence=evidence,
        evidence_level=(
            "social_and_places"
            if accepted and social_evidence
            else "places_strong"
            if accepted
            else "places_weak"
        ),
    )
    with get_tracer().start_as_current_span("gather.admission") as span:
        span.set_attribute("city", destination)
        span.set_attribute("admission.reason", reason.value)
        span.set_attribute("admission.accepted", accepted)
    return decision
