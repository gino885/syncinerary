"""Chinese discovery must use Chinese source evidence, not translated captions."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from syncinerary.agents.gather import localization, social
from syncinerary.domain.models import SocialPlatform, Trip
from syncinerary.tools.fetch.social import (
    BraveSocialSearchOutput,
    DiscoveredSocialURL,
    normalize_social_url,
)
from syncinerary.tools.places import PlaceMatch


def _reel(code: str, *, title: str, description: str | None = None,
          like_count: int | None = None) -> DiscoveredSocialURL:
    return DiscoveredSocialURL(
        reference=normalize_social_url(f"https://www.instagram.com/reel/{code}/"),
        query="波士頓 美食 必去景點",
        rank=1,
        title=title,
        description=description,
        like_count=like_count,
    )


async def _search(monkeypatch, posts, *, locale="zh-Hant",
                  platform=SocialPlatform.INSTAGRAM):
    async def provider(_tool, _value, **_kwargs):
        return BraveSocialSearchOutput(results=posts)

    monkeypatch.setattr(social, "run_tool", provider)
    return await social._search_platform(
        platform,
        query="波士頓 美食 必去景點",
        destination="Boston",
        output_locale=locale,
    )


@pytest.mark.parametrize("locale", ["zh-Hant", "zh-Hans"])
async def test_chinese_discovery_keeps_chinese_posts_instead_of_viral_english_reels(
    monkeypatch, locale,
):
    english = _reel(
        "english", title="Can you guess which Massachusetts city I am in?",
        description="Try the clam chowder at Quincy Market in Boston.",
        like_count=100_000,
    )
    chinese = _reel(
        "chinese", title="波士頓美食散步：昆西市場必吃龍蝦堡",
        description="第一次到波士頓，推薦這間市場裡的龍蝦堡和濃湯。",
        like_count=30,
    )

    posts = await _search(monkeypatch, [english, chinese], locale=locale)

    assert [post.reference.platform_id for post in posts] == ["chinese"]


@pytest.mark.parametrize(
    "post",
    [
        _reel("unknown", title="Quincy Market | Instagram"),
        _reel(
            "hashtags", title="Best Boston food spots #波士頓 #美食",
            description="You have to try this lobster roll at Quincy Market.",
        ),
        _reel(
            "placename", title="波士頓 Boston food guide",
            description="Can you guess which Massachusetts city I am in? "
            "Come to Quincy Market for the best clam chowder and lobster rolls.",
        ),
        _reel(
            "japanese", title="波士頓 昆西市場",
            description="ボストンで絶対に食べたいロブスターロールを紹介します。",
        ),
    ],
    ids=["unknown-language", "chinese-hashtags", "chinese-city-name", "japanese-caption"],
)
async def test_chinese_discovery_does_not_claim_sparse_cjk_as_chinese_content(
    monkeypatch, post,
):
    assert await _search(monkeypatch, [post]) == []


async def test_chinese_discovery_accepts_chinese_caption_with_original_english_venue_name(
    monkeypatch,
):
    post = _reel(
        "bilingual", title="Quincy Market 波士頓自由行",
        description="來波士頓一定要逛昆西市場，龍蝦堡與海鮮濃湯都值得試試。",
    )

    assert await _search(monkeypatch, [post]) == [post]


async def test_english_discovery_still_accepts_english_source_content(monkeypatch):
    post = _reel(
        "english", title="Boston food guide",
        description="Try a lobster roll at Quincy Market.",
    )

    assert await _search(monkeypatch, [post], locale="en") == [post]


async def test_chinese_discovery_accepts_meaningful_chinese_title_without_caption(monkeypatch):
    post = _reel("titleonly", title="波士頓昆西市場必吃龍蝦堡與海鮮濃湯")

    assert await _search(monkeypatch, [post]) == [post]


async def test_chinese_discovery_checks_tiktok_caption_after_permitted_metadata_read(monkeypatch):
    post = DiscoveredSocialURL(
        reference=normalize_social_url("https://www.tiktok.com/@traveler/video/7000000001"),
        query="波士頓 美食",
        rank=1,
        title="Quincy Market | TikTok",
    )
    read_post = post.model_copy(update={
        "caption": "波士頓自由行推薦昆西市場，來這裡吃龍蝦堡和海鮮濃湯。",
    })

    async def permitted_read(_posts, **_kwargs):
        return [read_post]

    monkeypatch.setattr(social, "read_tiktok_posts", permitted_read)

    assert await _search(monkeypatch, [post], platform=SocialPlatform.TIKTOK) == [read_post]


@pytest.mark.parametrize(
    "post",
    [
        _reel(
            "kanjititle", title="波士頓昆西市場海鮮料理",
            description="ボストンで絶対に食べたいロブスターロールを紹介します。",
        ),
        _reel(
            "fullwidthhashtag", title="My Boston food tour",
            description="＃波士頓龍蝦堡美食推薦",
        ),
    ],
    ids=["kanji-title-japanese-caption", "fullwidth-hashtag-only"],
)
async def test_chinese_discovery_does_not_accept_non_chinese_caption_via_title_or_tag(
    monkeypatch, post,
):
    assert await _search(monkeypatch, [post]) == []


async def test_source_language_evidence_survives_mining_card_creation_and_localization(monkeypatch):
    evidence = "波士頓自由行推薦昆西市場,來這裡吃龍蝦堡和海鮮濃湯"
    post = _reel("evidence", title="Quincy Market", description=evidence)
    mined = {}
    social.merge_mentions(
        mined,
        social.SocialPlaceMentions(mentions=[social.SocialPlaceMention(
            name="昆西市場", canonical_name="Quincy Market", post_index=1,
            highlight="龍蝦堡和海鮮濃湯",
        )]),
        [post], SocialPlatform.INSTAGRAM,
    )
    trip = Trip(destination="Boston", start_date="2026-10-11", end_date="2026-10-13", days=3)
    place = PlaceMatch(
        place_id="quincy-market", display_name="Quincy Market",
        lat=42.36, lng=-71.05, primary_type="tourist_attraction",
        types=["tourist_attraction"],
    )
    candidate = social.to_candidate(place, mined["quincy market"], trip)
    original = candidate.model_dump()

    async def translate(request, **_kwargs):
        payload = json.loads(request.messages[0].content)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
            type="text", text=json.dumps({"items": [
                {"key": item["key"], "text": "翻譯後的顯示文字"} for item in payload
            ]}),
        )])

    monkeypatch.setattr(localization, "call_llm", translate)
    translated = (await localization.localize_candidates([candidate], "zh-Hant"))[0]

    for card in (candidate, translated):
        source = card.enrichment["social_posts"][0]
        assert source["content_language"] == "zh"
        assert source["language_evidence"] == evidence
        assert source["url"] == post.reference.canonical_url
    assert translated.enrichment["social_posts"][0]["highlight"] != "龍蝦堡和海鮮濃湯"
    assert candidate.model_dump() == original
