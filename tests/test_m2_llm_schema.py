"""The structured output schema the provider will actually accept.

These exist because every stubbed test passed while all three structured calls
were failing with a 400 in production. Screenshot OCR, TikTok caption
extraction, and social buzz mining were all dead for that reason.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from syncinerary.harness.wrapper import UNSUPPORTED_SCHEMA_KEYWORDS, strict_json_schema


class Inner(BaseModel):
    name: str = Field(min_length=1)
    post_index: int = Field(ge=1, le=99)


class Outer(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    items: list[Inner] = Field(default_factory=list, max_length=8)


def test_every_object_is_closed_including_nested_definitions():
    schema = strict_json_schema(Outer)

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Inner"]["additionalProperties"] is False


def test_constraint_keywords_the_provider_rejects_are_stripped():
    schema = strict_json_schema(Outer)

    def walk(node):
        if isinstance(node, dict):
            assert not (UNSUPPORTED_SCHEMA_KEYWORDS & node.keys()), node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)


def test_the_shape_the_model_has_to_produce_is_left_alone():
    schema = strict_json_schema(Outer)

    assert set(schema["properties"]) == {"label", "items"}
    assert schema["$defs"]["Inner"]["properties"]["post_index"]["type"] == "integer"


def test_stripping_does_not_weaken_what_we_enforce_on_the_way_back():
    """The constraints still run: the response is parsed through the model."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Outer.model_validate({"items": [{"name": "", "post_index": 0}]})
