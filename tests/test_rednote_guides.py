from syncinerary.agents.gather.guides import grounded_mentions, guide_query
from syncinerary.agents.gather.social import SocialPlaceMention, SocialPlaceMentions
from syncinerary.tools.fetch.social import DiscoveredSocialURL, normalize_social_url


def test_guide_query_preserves_order_and_actual_duration():
    assert guide_query(["东京", "镰仓", "热海"], 3) == (
        "东京 镰仓 热海 3天2夜攻略"
    )
    assert guide_query(["镰仓"], 2).endswith("镰仓 2天1夜攻略")


def test_guide_headings_and_untraceable_mentions_are_dropped():
    post = DiscoveredSocialURL(
        reference=normalize_social_url("https://www.xiaohongshu.com/discovery/item/abc123"),
        query="test",
        rank=1,
        title="东京五天四夜攻略",
        description="东京美食：筑地场外市场。下午参观东京国立博物馆。",
    )
    mentions = SocialPlaceMentions(
        mentions=[
            SocialPlaceMention(name=n, post_index=i)
            for n, i in [
                ("东京五天四夜攻略", 1),
                ("东京美食", 1),
                ("筑地场外市场", 1),
                ("东京国立博物馆", 1),
                ("Invented Cafe", 1),
                ("Other", 8),
            ]
        ]
    )
    accepted = grounded_mentions(mentions, [post], "东京")
    assert [m.name for m in accepted.mentions] == ["筑地场外市场", "东京国立博物馆"]
    assert all(m.highlight for m in accepted.mentions)


def _guide_trip(days=5, names=None):
    from datetime import date, timedelta

    from syncinerary.domain.models import Trip

    start = date(2026, 10, 1)
    return Trip(
        destination=" / ".join(names or ["Tokyo"]),
        cities=names or ["Tokyo"],
        days=days,
        start_date=start,
        end_date=start + timedelta(days=days - 1),
        output_locale="zh-Hant",
    )


async def test_verified_five_day_baseline_has_breadth_and_multiple_traceable_sources(monkeypatch):
    from syncinerary.agents.gather import guides
    from syncinerary.agents.gather.dedup import dedup_candidates
    from syncinerary.tools.places import PlaceMatch, PlaceSearchOutput, ResolvedCity

    trip = _guide_trip()
    city = ResolvedCity(
        query="Tokyo", place_id="tokyo", name="Tokyo", lat=35.68, lng=139.76, radius_km=35
    )
    named = {
        "东京国立博物馆": "museum",
        "筑地场外市场": "market",
        "上野公园": "park",
        "隐巷咖啡": "cafe",
    }
    queries = []

    async def search(platform, *, query, destination, output_locale="en"):
        queries.append(query)
        return [
            DiscoveredSocialURL(
                reference=normalize_social_url(
                    f"https://www.xiaohongshu.com/discovery/item/guide{i}"
                ),
                query=query,
                rank=i,
                title="东京五天四夜攻略",
                description="、".join(named),
            )
            for i in (1, 2)
        ]

    async def extract(posts, **kwargs):
        return SocialPlaceMentions(
            mentions=[
                SocialPlaceMention(name=name, post_index=index)
                for index in (1, 2)
                for name in named
            ]
        )

    async def resolve(tool, request):
        return PlaceSearchOutput(
            matches=[
                PlaceMatch(
                    place_id=request.query,
                    display_name=request.query,
                    lat=city.lat,
                    lng=city.lng,
                    primary_type=named[request.query],
                    types=[named[request.query]],
                )
            ]
        )

    monkeypatch.setattr(guides, "_search_platform", search)
    monkeypatch.setattr(guides, "extract_post_places", extract)
    monkeypatch.setattr(guides, "run_tool", resolve)
    candidates, attempts = await guides.discover_guide_baseline(trip, [city], ["东京"], 20)
    assert queries == [guide_query(["东京"], 5)]
    assert attempts == len(candidates) == 4
    assert {"core", "food", "nature", "cafe"} <= guides.coverage(candidates, "Tokyo")
    assert all(
        len(c.sources) == 2 and all(s.url and s.mention_text and s.query for s in c.sources)
        for c in candidates
    )
    assert len(dedup_candidates([candidates[0], candidates[0]])) == 1
    assert len(dedup_candidates([candidates[0], candidates[0]])[0].sources) == 2


async def test_thin_city_fallback_uses_allocated_days_with_shared_attempt_budget(monkeypatch):
    from syncinerary.agents.gather import guides
    from syncinerary.tools.places import ResolvedCity

    trip = _guide_trip(names=["Tokyo", "Kamakura", "Atami"])
    cities = [
        ResolvedCity(query=name, place_id=name, name=name, lat=35 + i, lng=139, radius_km=20)
        for i, name in enumerate(trip.cities)
    ]
    queries = []

    async def search(platform, *, query, destination, output_locale="en"):
        queries.append(query)
        return []

    async def extract(posts, **kwargs):
        return SocialPlaceMentions()

    monkeypatch.setattr(guides, "_search_platform", search)
    monkeypatch.setattr(guides, "extract_post_places", extract)
    _, attempts = await guides.discover_guide_baseline(trip, cities, ["东京", "镰仓", "热海"], 8)
    assert queries == [
        guide_query(["东京", "镰仓", "热海"], 5),
        guide_query(["东京"], 2),
        guide_query(["镰仓"], 2),
        guide_query(["热海"], 1),
    ]
    assert attempts == 0
