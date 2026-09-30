"""Sparse Reel yield must not consume the remaining Chinese social searches."""
import httpx
import pytest

from syncinerary.agents.gather.social_search import (
    SearchOutcome,
    initialize_social_search_state,
    plan_next_search,
    update_search_state,
)
from syncinerary.domain.models import SocialPlatform
from syncinerary.harness import run_tool
from syncinerary.tools.fetch.social import (
    BraveSocialSearchInput,
    SearchIntent,
    SearchIntentType,
    make_brave_social_search_tool,
    normalize_social_url,
)


def test_chinese_reel_shortfall_probes_more_rednote_intents_before_exhausting_budget():
    state = initialize_social_search_state(
        destination="Boston", destination_local_name="波士頓", output_locale="zh-Hant",
        target_candidates=24,
    )
    sequence = [
        (SocialPlatform.INSTAGRAM, SearchIntentType.PLACES, 1),
        (SocialPlatform.REDNOTE, SearchIntentType.FOOD, 3),
        (SocialPlatform.TIKTOK, SearchIntentType.HIDDEN_GEMS, 0),
        (SocialPlatform.INSTAGRAM, SearchIntentType.FOOD, 0),
    ]
    for platform, kind, places in sequence:
        update_search_state(state, intent=SearchIntent(platform=platform, intent_type=kind),
            query=kind.value, outcome=SearchOutcome(raw_results_count=20,
                extracted_mentions_count=places, resolved_places_count=places,
                new_unique_places_count=places))
    action = plan_next_search(state)
    assert action is not None
    assert action.platform is SocialPlatform.REDNOTE
    assert action.intent_type is not SearchIntentType.FOOD
    # Resource ceilings still win even when neither source target was met.
    state.max_searches = state.searches_used
    assert plan_next_search(state) is None
    assert state.stop_reason.value == "search_budget_reached"


def test_rednote_shared_note_path_normalizes_to_the_same_post():
    note = "5e25cfae000000000100ab06"
    direct = normalize_social_url(f"https://www.xiaohongshu.com/explore/{note}")
    shared = normalize_social_url(f"https://www.xiaohongshu.com/discovery/item/sgh/{note}")
    assert shared == direct
    with pytest.raises(ValueError):
        normalize_social_url("https://www.xiaohongshu.com/mobile/question/83626")


async def test_rednote_search_scopes_both_note_paths_without_admitting_topic_pages():
    def respond(request):
        query = request.url.params["q"]
        assert "site:xiaohongshu.com/explore" in query
        assert "site:xiaohongshu.com/discovery/item" in query
        assert "OR" in query
        return httpx.Response(200, json={"web":{"results":[
            {"url":"https://www.xiaohongshu.com/explore/abc123", "title":"波士頓三天兩夜旅行攻略"},
            {"url":"https://www.xiaohongshu.com/discovery/item/sgh/def456", "title":"波士頓海港散步路線推薦"},
            {"url":"https://www.xiaohongshu.com/mobile/question/83626", "title":"聚合話題頁面"},
        ]}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(make_brave_social_search_tool(client=client, api_key="test"),
            BraveSocialSearchInput(platform=SocialPlatform.REDNOTE, query="波士頓 攻略", search_lang="zh-hant"))
    assert [p.reference.platform_id for p in result.results] == ["abc123", "def456"]
