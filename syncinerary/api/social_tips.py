"""Select one intact practical sentence from already attributed place evidence.

No new model call and no invented recommendation. Longer sentences are omitted,
not cut mid-qualification. This intentionally favors precision over coverage.
"""

import re
from typing import Literal, Protocol

from pydantic import BaseModel


class AttributedHighlight(Protocol):
    highlight: str | None
    url: str
    label: str


class SocialTipOut(BaseModel):
    text: str
    url: str
    source: str
    kind: Literal["food", "visit"]


FOOD = re.compile(
    r"\b(order|try|recommend(?:ed)?|signature|must.try)\b|推薦|推荐|必點|必点|招牌|必吃|おすすめ|注文",
    re.IGNORECASE,
)
PRACTICAL = re.compile(
    r"\b(book|reserve|reservation|tickets?|cash|queue|arrive|entrance|last entry|"
    r"closed|bring|avoid|before|after|sunset|sunrise)\b|"
    r"預約|预约|門票|门票|現金|现金|排隊|排队|入口|日落|日出|公休|避開|避开|予約|入場|現金",
    re.IGNORECASE,
)
UNSAFE = re.compile(r"https?://|ignore.*instructions|system prompt|忽略.*指令", re.IGNORECASE)


def social_tip(posts: list[AttributedHighlight], *, food: bool) -> SocialTipOut | None:
    for post in posts:
        if (
            not post.highlight
            or UNSAFE.search(post.highlight)
            or "..." in post.highlight
            or "…" in post.highlight
        ):
            continue
        # Keep sentence boundaries for languages which do not separate words by spaces.
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])|(?<=[。！？])\s*|\n+", post.highlight)
        for raw in sentences:
            sentence = " ".join(raw.split())
            if not 8 <= len(sentence) <= 160 or sentence.endswith(("…", "...")):
                continue
            kind = "food" if food and FOOD.search(sentence) else "visit"
            if kind == "food" or PRACTICAL.search(sentence):
                return SocialTipOut(text=sentence, url=post.url, source=post.label, kind=kind)
    return None
