"""Simulator-safe decorative assets in the SwiftUI client."""
from pathlib import Path

IOS_SOURCE = Path(__file__).parents[1] / "ios" / "Syncinerary"
RUNTIME_EFFECT_SOURCES = (
    "Design/LoadingScript.swift",
    "Features/Swipe/SwipeDecision.swift",
    "Features/Swipe/VotingCompleteView.swift",
)


def _looks_like_emoji(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or codepoint == 0xFE0F
    )


def test_runtime_swift_source_does_not_embed_emoji_glyphs():
    """macOS 15 simulators render embedded emoji as question-mark boxes."""
    offenders: list[str] = []
    for relative_path in RUNTIME_EFFECT_SOURCES:
        path = IOS_SOURCE / relative_path
        text = path.read_text()
        if any(_looks_like_emoji(character) for character in text):
            offenders.append(str(path.relative_to(IOS_SOURCE)))

    assert offenders == []
