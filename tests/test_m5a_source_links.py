"""M5a: source links on badges, and the source's own words on the card.

CLAUDE.md section 8.5: a badge whose provenance has a public URL opens that
URL, a badge without one stays plain text, a buzz card lists every post behind
it, and only URLs the social parser accepts are ever linkable.
"""
from __future__ import annotations

from datetime import time
from uuid import uuid4

from syncinerary.api.schemas import (
    CandidateCardOut,
    ItineraryStopOut,
    google_maps_place_url,
    source_badges,
    source_posts,
)
from syncinerary.domain.models import CandidatePlace, ItineraryNode, Source

TIKTOK = "https://www.tiktok.com/@traveler/video/7481234567890123456"
REEL = "https://www.instagram.com/reel/DcbEs5IpTCt/"


def _node(candidate_id):
    return ItineraryNode(
        version_id=uuid4(),
        candidate_id=candidate_id,
        day=0,
        start_time=time(12),
        end_time=time(13),
    )


def _buzz_candidate(**enrichment) -> CandidatePlace:
    posts = [
        {
            "platform": "tiktok",
            "url": TIKTOK,
            "rank": 1,
            "author_name": "Travel Notes",
            "highlight": None,
        },
        {
            "platform": "instagram",
            "url": REEL,
            "rank": 2,
            "author_name": None,
            "highlight": "Miso broth worth the queue.",
        },
    ]
    return CandidatePlace(
        trip_id=uuid4(),
        type="food",
        name_canonical="Ramen Shingen",
        lat=43.05,
        lng=141.35,
        sources=[
            Source(type="buzz", sources_count=2),
            Source(type="discovery", subtype="google_places"),
        ],
        enrichment={
            "google_place_id": "ChIJ-shingen",
            "social_platforms": ["tiktok", "instagram"],
            "social_post_urls": [TIKTOK, REEL],
            "social_posts": posts,
            "social_highlight": "Miso broth worth the queue.",
            "source_description": "A ramen counter near the station.",
            **enrichment,
        },
    )


def test_public_social_badge_opens_the_best_ranked_post_and_names_its_platform():
    social, _discovered = source_badges(_buzz_candidate())

    assert social.kind.value == "social"
    assert social.label == "Found on TikTok, Instagram"
    assert social.url == TIKTOK
    assert social.platform == "TikTok"


def test_explicit_engagement_supports_a_popular_badge():
    candidate = _buzz_candidate(
        social_posts=[
            {
                "platform": "tiktok",
                "url": TIKTOK,
                "rank": 1,
                "like_count": 12_400,
                "comment_count": 380,
            }
        ]
    )

    popular, _discovered = source_badges(candidate)

    assert popular.kind.value == "trending"
    assert popular.label == "Popular on TikTok, Instagram"


def test_discovered_badge_opens_the_google_maps_place_page():
    _, discovered = source_badges(_buzz_candidate())

    assert discovered.url == (
        "https://www.google.com/maps/search/?api=1"
        "&query=Ramen%20Shingen&query_place_id=ChIJ-shingen"
    )
    assert discovered.platform == "Google Maps"
    assert google_maps_place_url(_buzz_candidate(google_place_id=None)) is None


def test_a_badge_without_a_public_url_stays_plain_text():
    candidate = _buzz_candidate(
        google_place_id=None,
        social_posts=[{"platform": "tiktok", "url": "https://example.com/not-a-post"}],
    )

    trending, discovered = source_badges(candidate)

    assert trending.url is None and trending.platform is None
    assert discovered.url is None and discovered.platform is None


def test_card_details_list_every_post_with_who_said_what():
    posts = source_posts(_buzz_candidate())

    assert [(post.label, post.url) for post in posts] == [("TikTok", TIKTOK), ("Instagram", REEL)]
    assert posts[0].author_name == "Travel Notes"
    assert posts[1].highlight == "Miso broth worth the queue."


def test_the_card_speaks_in_the_posts_words_on_the_deck_and_the_itinerary():
    candidate = _buzz_candidate()

    card = CandidateCardOut.of(candidate)
    stop = ItineraryStopOut.of(_node(candidate.id), candidate)

    assert card.description == "Miso broth worth the queue."
    assert card.description_source == "Instagram Reel"
    assert stop.description == card.description
    assert stop.description_source == card.description_source
    assert [post.url for post in stop.source_posts] == [TIKTOK, REEL]
    assert stop.source_badges[0].url == TIKTOK


def test_without_a_quote_the_card_falls_back_to_the_place_listing():
    candidate = _buzz_candidate(social_highlight=None)

    card = CandidateCardOut.of(candidate)

    assert card.description == "A ramen counter near the station."
    assert card.description_source == "Google Places"


def test_a_tracking_link_is_normalized_and_unsupported_or_search_urls_are_dropped():
    candidate = _buzz_candidate(
        social_posts=[
            {"platform": "instagram", "url": f"{REEL}?igsh=tracking"},
            {"platform": "tiktok", "url": "https://www.tiktok.com/discover/sapporo"},
            {"platform": "tiktok", "url": "https://example.com/post"},
            {"platform": "instagram", "url": REEL},
        ]
    )

    posts = source_posts(candidate)

    assert [post.url for post in posts] == [REEL]
    assert source_badges(candidate)[0].url == REEL


def test_rows_written_before_per_post_details_still_list_their_posts():
    candidate = _buzz_candidate(social_posts=None, social_highlight=None)

    posts = source_posts(candidate)

    assert [(post.platform, post.url) for post in posts] == [
        ("tiktok", TIKTOK),
        ("instagram", REEL),
    ]
    assert all(post.highlight is None for post in posts)
    assert source_badges(candidate)[0].url == TIKTOK


def test_attached_badge_opens_the_post_the_traveler_shared():
    traveler_id = uuid4()
    candidate = CandidatePlace(
        trip_id=uuid4(),
        type="attraction",
        name_canonical="Otaru Canal",
        lat=43.1987,
        lng=140.9947,
        sources=[Source(type="personal", subtype="user_paste", by=traveler_id, via="tiktok_link")],
        enrichment={
            "platform": "tiktok",
            "source_url": TIKTOK,
            "source_description": "Blue-hour reflections make this canal cinematic.",
        },
    )

    (badge,) = source_badges(candidate, viewer_id=traveler_id)
    card = CandidateCardOut.of(candidate, viewer_id=traveler_id)

    assert badge.kind.value == "attached_by_you"
    assert badge.url == TIKTOK
    assert badge.platform == "TikTok"
    assert [post.url for post in card.source_posts] == [TIKTOK]
    assert card.description == "Blue-hour reflections make this canal cinematic."
    assert card.description_source == "TikTok"


def test_a_screenshot_attachment_keeps_a_plain_badge():
    candidate = CandidatePlace(
        trip_id=uuid4(),
        type="attraction",
        name_canonical="Otaru Canal",
        lat=43.1987,
        lng=140.9947,
        sources=[Source(type="personal", subtype="user_paste", by=uuid4(), via="tiktok_screenshot")],
        enrichment={"platform": "tiktok", "input_type": "screenshot"},
    )

    (badge,) = source_badges(candidate)

    assert badge.url is None and badge.platform is None
    assert source_posts(candidate) == []


def test_a_card_that_buzzes_and_was_attached_lists_the_shared_post_once():
    candidate = _buzz_candidate(platform="tiktok", source_url=f"{TIKTOK}?is_from_webapp=1")
    candidate = candidate.model_copy(
        update={
            "sources": [
                *candidate.sources,
                Source(type="personal", subtype="user_paste", by=uuid4(), via="tiktok_link"),
            ]
        }
    )

    posts = source_posts(candidate)

    assert [post.url for post in posts] == [TIKTOK, REEL]
    _trending, _discovered, attached = source_badges(candidate)
    assert attached.url == TIKTOK
