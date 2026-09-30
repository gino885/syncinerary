"""Conservative Chinese-language evidence from permitted public post text.

This checks the text we can actually read, not the spoken language of a video.
A translated card, a Chinese query, an author name, or a few hashtags is not
proof that the original post offers Chinese content.
"""

import re
import unicodedata

from syncinerary.tools.fetch.social import DiscoveredSocialURL

_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]")
_OTHER_EAST_ASIAN = re.compile(r"[\u3040-\u30ff\uac00-\ud7af]")
_TAG_OR_URL = re.compile(r"https?://\S+|[#@][\w\u3400-\u9fff]+", re.IGNORECASE)


def chinese_source_evidence(post: DiscoveredSocialURL) -> str | None:
    """Require a meaningful Chinese passage, allowing bilingual venue names.

    Eight Han characters and a Chinese majority among letters reject sparse
    place labels inside English/Japanese captions. These are conservative
    admission thresholds, not a claim to detect every language or dialect.
    Check fields separately so an English platform footer cannot overwhelm a
    Chinese caption. Never inspect query text or model-written highlights.
    """
    body_fields = (post.caption, post.cover_text, post.description)
    ambiguous_title = any(_OTHER_EAST_ASIAN.search(raw or "") for raw in body_fields)
    for raw in (*body_fields, None if ambiguous_title else post.title):
        if not raw:
            continue
        text = _TAG_OR_URL.sub("", unicodedata.normalize("NFKC", raw))
        # Snippets may include several passages. An actual Chinese sentence
        # can coexist with a faithful English translation of the same caption.
        for passage in re.split(r"[\n。！？!?]", text):
            han = len(_HAN.findall(passage))
            letters = sum(character.isalpha() for character in passage)
            if han >= 8 and han * 2 >= letters and not _OTHER_EAST_ASIAN.search(passage):
                return passage.strip()[:240]
    return None
