"""M3 user-submitted social link persistence and provenance."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID

import pytest

from syncinerary.agents.gather import personal as personal_module
from syncinerary.agents.gather.attachments import (
    ExtractedPlaceMention,
    ScreenshotExtraction,
    ScreenshotExtractionUnavailable,
    extract_screenshot,
)
from syncinerary.agents.gather.personal import (
    TextPlaceExtraction,
    extract_place_mentions,
)
from syncinerary.api.routers import trips as trips_module
from syncinerary.domain.models import (
    AttachmentInputType,
    AttachmentStatus,
    SocialPlatform,
    SourceAttachment,
    Traveler,
    Trip,
)
from syncinerary.store.repositories import (
    CandidatePlaceRepository,
    SourceAttachmentRepository,
    TravelerRepository,
    TripRepository,
)
from syncinerary.tools.fetch.social import SocialLinkMetadata, SocialPostPreview
from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput


async def _trip_and_traveler(session):
    trip = await TripRepository(session).add(
        Trip(
            destination="Hokkaido",
            start_date=date(2026, 5, 21),
            end_date=date(2026, 5, 25),
            days=5,
        )
    )
    traveler = await TravelerRepository(session).add(
        Traveler(trip_id=trip.id, name="Gino")
    )
    return trip, traveler


async def test_attachment_repository_round_trips_contributor_and_input_type(session):
    trip, traveler = await _trip_and_traveler(session)
    attachment = SourceAttachment(
        trip_id=trip.id,
        traveler_id=traveler.id,
        platform=SocialPlatform.REDNOTE,
        input_type=AttachmentInputType.LINK,
        status=AttachmentStatus.PENDING,
        original_url="http://xhslink.com/o/8YJmF0qK4t",
        canonical_url="https://xhslink.com/o/8YJmF0qK4t",
        platform_id="8YJmF0qK4t",
    )

    saved = await SourceAttachmentRepository(session).add(attachment)
    fetched = await SourceAttachmentRepository(session).get(saved.id)

    assert fetched == saved
    assert fetched.traveler_id == traveler.id
    assert fetched.input_type is AttachmentInputType.LINK
    assert fetched.status is AttachmentStatus.PENDING


async def test_post_reel_link_strips_tracking_and_identifies_contributor(client, unreadable_links):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]

    response = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": (
                "https://www.instagram.com/reel/DcbEs5IpTCt/"
                "?igsi=MWFrdjFtbDB4eGg4cw=="
            ),
        },
    )

    assert response.status_code == 201
    assert response.json()["platform"] == "instagram"
    assert response.json()["input_type"] == "link"
    # Instagram permalinks are essentially never in a search index and section
    # 15 rules out reading the post, so this link is terminal on arrival and
    # says what the traveler can do about it.
    assert response.json()["status"] == "failed"
    assert response.json()["canonical_url"] == (
        "https://www.instagram.com/reel/DcbEs5IpTCt/"
    )
    assert response.json()["contributor"] == {"id": traveler_id, "name": "Gino"}


async def test_post_link_stays_pending_when_brave_metadata_is_not_configured(
    client,
    monkeypatch,
):
    monkeypatch.setattr(personal_module.settings, "brave_search_api_key", "")
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )

    response = await client.post(
        f"/trips/{created.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.instagram.com/reel/DcbEs5IpTCt/",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending"


async def test_post_rednote_short_link_is_preserved_for_enrichment(client, unreadable_links):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]

    response = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "http://xhslink.com/o/8YJmF0qK4t",
        },
    )

    assert response.status_code == 201
    assert response.json()["platform"] == "rednote"
    assert response.json()["canonical_url"] == "https://xhslink.com/o/8YJmF0qK4t"
    assert response.json()["status"] == "failed"


async def test_pending_link_can_be_resubmitted_with_a_place_name(
    client,
    monkeypatch,
):
    async def fake_run_tool(tool, arguments, **_kwargs):
        if tool.name == "social_link_metadata":
            return SocialLinkMetadata(
                platform=SocialPlatform.REDNOTE,
                canonical_url="https://xhslink.com/o/8YJmF0qK4t",
                platform_id="8YJmF0qK4t",
            )
        assert tool.name == "google_places_text_search"
        assert arguments.query == "Otaru Canal"
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id="ChIJ-otaru",
                    display_name="Otaru Canal",
                    lat=43.1987,
                    lng=140.9947,
                    primary_type="tourist_attraction",
                )
            ]
        )

    monkeypatch.setattr(personal_module, "run_tool", fake_run_tool)
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]
    first = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "http://xhslink.com/o/8YJmF0qK4t",
        },
    )

    second = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "http://xhslink.com/o/8YJmF0qK4t",
            "place_name": "Otaru Canal",
        },
    )

    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "ready"
    assert second.json()["candidate_id"] is not None


async def test_link_place_name_becomes_a_personal_candidate_without_a_picture(
    client,
    session,
    monkeypatch,
):
    async def fake_run_tool(tool, arguments, **_kwargs):
        assert tool.name == "google_places_text_search"
        assert arguments.query == "Otaru Canal"
        assert arguments.destination == "Hokkaido"
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id="ChIJ-otaru",
                    display_name="Otaru Canal",
                    formatted_address="Otaru, Hokkaido, Japan",
                    lat=43.1987,
                    lng=140.9947,
                    primary_type="tourist_attraction",
                    types=["tourist_attraction", "point_of_interest"],
                )
            ]
        )

    monkeypatch.setattr(personal_module, "run_tool", fake_run_tool)
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]

    response = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "https://www.instagram.com/reel/Da2UDmNtLvp/",
            "place_name": "Otaru Canal",
        },
    )

    assert response.status_code == 201
    assert response.json()["submitted_place_name"] == "Otaru Canal"
    assert response.json()["status"] == "ready"
    assert response.json()["candidate_id"] is not None

    candidates = await CandidatePlaceRepository(session).list_for_trip(trip_id)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.name_canonical == "Otaru Canal"
    assert candidate.enrichment["google_place_id"] == "ChIJ-otaru"
    assert candidate.enrichment["attachment_id"] == response.json()["id"]
    assert candidate.sources[0].model_dump(mode="json") == {
        "type": "personal",
        "score": None,
        "articles_count": None,
        "sources_count": None,
        "subtype": "user_paste",
        "by": traveler_id,
        "via": "instagram_link",
    }


async def test_link_place_name_is_checked_in_each_selected_city(
    client,
    session,
    monkeypatch,
):
    searched: list[str] = []

    async def fake_run_tool(_tool, arguments, **_kwargs):
        searched.append(arguments.destination)
        if arguments.destination == "Otaru":
            return PlaceSearchOutput(
                matches=[
                    PlaceMatch(
                        place_id="ChIJ-otaru",
                        display_name="Otaru Canal",
                        lat=43.1987,
                        lng=140.9947,
                        primary_type="tourist_attraction",
                    )
                ]
            )
        return PlaceSearchOutput(matches=[])

    monkeypatch.setattr(personal_module, "run_tool", fake_run_tool)
    created = await client.post(
        "/trips",
        json={
            "cities": ["Sapporo", "Otaru"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )

    response = await client.post(
        f"/trips/{created.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.instagram.com/reel/Da2UDmNtLvp/",
            "place_name": "Otaru Canal",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "ready"
    assert searched == ["Sapporo", "Otaru"]
    candidates = await CandidatePlaceRepository(session).list_for_trip(
        created.json()["trip"]["id"]
    )
    assert candidates[0].enrichment["city"] == "Otaru"


async def test_link_rejects_a_whitespace_only_place_name(client):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )

    response = await client.post(
        f"/trips/{created.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.instagram.com/reel/Da2UDmNtLvp/",
            "place_name": "   ",
        },
    )

    assert response.status_code == 422


async def test_tiktok_discovery_page_is_rejected_as_an_attachment(client):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]

    response = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": (
                "https://www.tiktok.com/discover/"
                "the-next-station-is-shibuya-capcut-template"
            ),
        },
    )

    assert response.status_code == 422
    assert "specific post" in response.json()["detail"]


async def test_attachment_cannot_claim_a_traveler_from_another_trip(client):
    first = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    second = await client.post(
        "/trips",
        json={
            "cities": ["Tokyo"],
            "country": "Japan",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "creator_name": "Ana",
        },
    )

    response = await client.post(
        f"/trips/{first.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": second.json()["traveler_id"],
            "url": "https://www.instagram.com/reel/Da2UDmNtLvp/",
        },
    )

    assert response.status_code == 404
    assert "not on trip" in response.json()["detail"]


class ScreenshotMessages:
    def __init__(self, text: str, *, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = (
            []
            if self.stop_reason == "refusal"
            else [SimpleNamespace(type="text", text=self.text)]
        )
        return SimpleNamespace(stop_reason=self.stop_reason, content=content)


async def test_caption_place_extraction_uses_typed_structured_output():
    stub = ScreenshotMessages(
        '{"language":"en","short_description":"Blue-hour reflections along the canal.",'
        '"place_mentions":['
        '{"name":"Otaru Canal","evidence":"Night walk at Otaru Canal"}]}'
    )

    result = await extract_place_mentions(
        "Night walk at Otaru Canal",
        platform=SocialPlatform.TIKTOK,
        client=stub,
    )

    assert result.place_mentions[0].name == "Otaru Canal"
    assert result.short_description == "Blue-hour reflections along the canal."
    sent = stub.calls[0]
    assert sent["messages"] == [
        {
            "role": "user",
            "content": "TikTok caption:\nNight walk at Otaru Canal",
        }
    ]
    assert sent["output_config"]["format"]["type"] == "json_schema"


async def test_tiktok_link_uses_official_preview_then_google_place(
    client,
    session,
    monkeypatch,
):
    async def fake_run_tool(tool, arguments, **_kwargs):
        if tool.name == "tiktok_oembed":
            return SocialPostPreview(
                platform=SocialPlatform.TIKTOK,
                canonical_url=arguments.url,
                platform_id="1234567890",
                caption="Night walk at Otaru Canal",
                author_name="Traveler",
                author_url="https://www.tiktok.com/@traveler",
                thumbnail_url="https://p16-sign.tiktokcdn-us.com/preview.jpeg",
            )
        assert tool.name == "google_places_text_search"
        assert arguments.query == "Otaru Canal"
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id="ChIJ-otaru",
                    display_name="Otaru Canal",
                    lat=43.1987,
                    lng=140.9947,
                    primary_type="tourist_attraction",
                )
            ]
        )

    async def fake_extract(*_args, **_kwargs):
        return TextPlaceExtraction(
            language="en",
            short_description="Blue-hour reflections make this canal especially cinematic.",
            place_mentions=[
                ExtractedPlaceMention(
                    name="Otaru Canal",
                    evidence="Night walk at Otaru Canal",
                )
            ],
        )

    monkeypatch.setattr(personal_module, "run_tool", fake_run_tool)
    monkeypatch.setattr(personal_module, "extract_place_mentions", fake_extract)
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]

    response = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "https://www.tiktok.com/@traveler/video/1234567890",
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "ready"
    candidates = await CandidatePlaceRepository(session).list_for_trip(trip_id)
    assert candidates[0].enrichment["platform_preview_url"] == (
        "https://p16-sign.tiktokcdn-us.com/preview.jpeg"
    )
    assert candidates[0].enrichment["source_description"] == (
        "Blue-hour reflections make this canal especially cinematic."
    )


async def test_screenshot_extraction_uses_a_typed_image_and_json_schema():
    stub = ScreenshotMessages(
        '{"raw_text":"小樽运河","language":"zh-CN","place_mentions":'
        '[{"name":"小樽运河","evidence":"夜景很漂亮"}]}'
    )

    result = await extract_screenshot(
        b"not-a-real-png-but-the-boundary-is-stubbed",
        media_type="image/png",
        platform=SocialPlatform.REDNOTE,
        client=stub,
    )

    assert result.raw_text == "小樽运河"
    assert result.language == "zh-CN"
    assert result.place_mentions[0].name == "小樽运河"
    sent = stub.calls[0]
    assert sent["messages"][0]["content"][0]["type"] == "image"
    assert sent["messages"][0]["content"][0]["source"]["type"] == "base64"
    assert sent["messages"][0]["content"][0]["source"]["media_type"] == "image/png"
    assert sent["messages"][0]["content"][1]["type"] == "text"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "schema" in sent["output_config"]["format"]


async def test_screenshot_extraction_rejects_unsupported_media_before_calling_model():
    stub = ScreenshotMessages("{}")

    with pytest.raises(ValueError, match="image/png"):
        await extract_screenshot(
            b"image",
            media_type="image/svg+xml",
            platform=SocialPlatform.REDNOTE,
            client=stub,
        )

    assert stub.calls == []


async def test_screenshot_refusal_is_a_typed_failure():
    stub = ScreenshotMessages("", stop_reason="refusal")

    with pytest.raises(ScreenshotExtractionUnavailable, match="refused"):
        await extract_screenshot(
            b"image",
            media_type="image/jpeg",
            platform=SocialPlatform.INSTAGRAM,
            client=stub,
        )


async def test_upload_screenshot_extracts_evidence_and_preserves_contributor(
    client,
    session,
    monkeypatch,
    tmp_path,
):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]
    attached = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "http://xhslink.com/o/8YJmF0qK4t",
        },
    )
    attachment_id = attached.json()["id"]
    attachment_repo = SourceAttachmentRepository(session)
    await attachment_repo.record_metadata(
        UUID(attachment_id),
        metadata={"submitted_place_name": "Otaru Canal"},
    )

    async def fake_extract(image, *, media_type, platform):
        assert image == b"screenshot-bytes"
        assert media_type == "image/png"
        assert platform is SocialPlatform.REDNOTE
        return ScreenshotExtraction(
            raw_text="小樽运河 夜景很漂亮",
            language="zh-CN",
            place_mentions=[
                ExtractedPlaceMention(name="小樽运河", evidence="夜景很漂亮")
            ],
        )

    monkeypatch.setattr(trips_module, "extract_screenshot", fake_extract)
    monkeypatch.setattr(
        trips_module.settings,
        "attachment_upload_dir",
        str(tmp_path),
    )

    response = await client.post(
        f"/trips/{trip_id}/attachments/{attachment_id}/screenshot",
        data={"traveler_id": traveler_id},
        files={"screenshot": ("note.png", b"screenshot-bytes", "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["has_screenshot"] is True
    assert response.json()["submitted_place_name"] == "Otaru Canal"
    assert response.json()["contributor"] == {"id": traveler_id, "name": "Gino"}
    stored = list(tmp_path.rglob("*.png"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"screenshot-bytes"


async def test_upload_screenshot_rejects_unsupported_content_type(
    client,
    monkeypatch,
    tmp_path,
):
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]
    traveler_id = created.json()["traveler_id"]
    attached = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": traveler_id,
            "url": "https://www.instagram.com/reel/Da2UDmNtLvp/",
        },
    )

    monkeypatch.setattr(
        trips_module.settings,
        "attachment_upload_dir",
        str(tmp_path),
    )
    response = await client.post(
        f"/trips/{trip_id}/attachments/{attached.json()['id']}/screenshot",
        data={"traveler_id": traveler_id},
        files={"screenshot": ("note.svg", b"<svg/>", "image/svg+xml")},
    )

    assert response.status_code == 415
    assert list(tmp_path.rglob("*")) == []


async def test_an_unreadable_link_says_what_the_traveler_can_do_next(client, unreadable_links):
    """The bug this replaced: five real Instagram links sat at 'pending'
    forever with no error and no prompt, so the traveler waited for a card
    that was never coming."""
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )

    response = await client.post(
        f"/trips/{created.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.instagram.com/reel/DcbEs5IpTCt/",
        },
    )

    assert response.json()["status"] == "failed"
    assert response.json()["failure_reason"] == "needs_place_name"
    assert response.json()["candidate_id"] is None


async def test_a_missing_search_key_leaves_the_link_retryable(client, monkeypatch):
    """A deployment gap must not burn the attachment: configuring the key and
    re-running should still pick it up, so this one stays pending."""
    monkeypatch.setattr(personal_module.settings, "brave_search_api_key", "")
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )

    response = await client.post(
        f"/trips/{created.json()['trip']['id']}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.instagram.com/reel/DcbEs5IpTCt/",
        },
    )

    assert response.json()["status"] == "pending"
    assert response.json()["failure_reason"] is None


async def test_naming_the_place_rescues_a_failed_link(client, unreadable_links):
    """needs_place_name has to be actionable, or it is just a nicer dead end."""
    created = await client.post(
        "/trips",
        json={
            "cities": ["Hokkaido"],
            "country": "Japan",
            "start_date": "2026-05-21",
            "end_date": "2026-05-25",
            "creator_name": "Gino",
        },
    )
    trip_id = created.json()["trip"]["id"]

    failed = await client.post(
        f"/trips/{trip_id}/attachments/links",
        json={
            "traveler_id": created.json()["traveler_id"],
            "url": "https://www.instagram.com/reel/DcbEs5IpTCt/",
            "place_name": "Otaru Canal",
        },
    )

    assert failed.json()["submitted_place_name"] == "Otaru Canal"
