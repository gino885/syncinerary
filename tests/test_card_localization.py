from types import SimpleNamespace
from uuid import uuid4

from syncinerary.domain.models import CandidatePlace, CandidateType


async def test_chinese_card_text_is_translated_without_changing_source_evidence(monkeypatch):
    from syncinerary.agents.gather import localization
    candidate = CandidatePlace(trip_id=uuid4(), type=CandidateType.ATTRACTION,
        name_canonical="Art Center", lat=35, lng=139,
        enrichment={"source_description": "Modern art exhibitions", "source_url": "https://example.com"})
    original = candidate.model_dump()
    async def translate(request, **kwargs):
        assert "Traditional Chinese" in request.system
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
            type="text", text='{"items":[{"key":0,"text":"藝術中心"},{"key":1,"text":"現代藝術展覽"}]}')])
    monkeypatch.setattr(localization, "call_llm", translate)
    result = await localization.localize_candidates([candidate], "zh-Hant")
    assert result[0].name_canonical == "藝術中心"
    assert result[0].name_original_lang == "Art Center"
    assert result[0].enrichment["source_description"] == "現代藝術展覽"
    assert result[0].enrichment["source_url"] == candidate.enrichment["source_url"]
    assert candidate.model_dump() == original


async def test_category_label_is_chinese_but_solver_category_stays_stable(monkeypatch):
    from syncinerary.agents.gather import localization
    from syncinerary.api.schemas import CandidateCardOut
    candidate = CandidatePlace(trip_id=uuid4(), type=CandidateType.ATTRACTION,
                               name_canonical="Art Center", category="art_museum", lat=35, lng=139)
    async def translate(request, **kwargs):
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(
            type="text", text='{"items":[{"key":0,"text":"藝術中心"},{"key":1,"text":"美術館"}]}')])
    monkeypatch.setattr(localization, "call_llm", translate)
    translated = (await localization.localize_candidates([candidate], "zh-Hant"))[0]
    assert translated.category == "art_museum"
    card = CandidateCardOut.of(translated)
    assert card.category_label == "美術館"
    assert card.description is None  # no invented English filler without source text


async def test_already_localized_cards_do_not_spend_another_model_call(monkeypatch):
    from syncinerary.agents.gather import localization
    candidate = CandidatePlace(trip_id=uuid4(), type=CandidateType.ATTRACTION,
                               name_canonical="藝術中心", lat=35, lng=139,
                               enrichment={"content_locale": "zh-Hant"})
    async def unexpected(*args, **kwargs):
        raise AssertionError("translation already exists")
    monkeypatch.setattr(localization, "call_llm", unexpected)
    assert await localization.localize_candidates([candidate], "zh-Hant") == [candidate]
