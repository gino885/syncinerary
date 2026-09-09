"""Languages the server can write shared trip content in.

Three related language choices run through this product:

- display language, which the iOS app resolves from its selected localization
- output language, which is what the server writes narratives and reasons in,
  persisted per trip because a group reads one artifact
- search language, which follows Chinese versus English from the creator's
  stored output locale so returned social content matches the UI. RedNote is
  always searched in its measured Simplified Chinese vocabulary.
"""

#: Locale tag to the name the model is asked to write in. Traditional and
#: Simplified are listed separately on purpose: they are not interchangeable,
#: and a traveler who reads one does not want the other.
SUPPORTED_OUTPUT_LOCALES = {
    "en": "English",
    "zh-Hant": "Traditional Chinese (繁體中文), as written in Taiwan",
    "zh-Hans": "Simplified Chinese (简体中文)",
    "ja": "Japanese",
}

DEFAULT_OUTPUT_LOCALE = "en"


def normalize_output_locale(value: str | None) -> str:
    """The supported tag closest to what was asked for.

    Matching is exact, then by primary subtag, so `zh-Hant-TW` resolves to
    `zh-Hant` while a bare `zh` does not silently become Traditional: script
    matters more than region here, so an ambiguous tag falls back rather than
    guessing which Chinese somebody meant.
    """
    if not value:
        return DEFAULT_OUTPUT_LOCALE
    cleaned = value.strip()
    for tag in SUPPORTED_OUTPUT_LOCALES:
        if cleaned.casefold() == tag.casefold():
            return tag
    for tag in SUPPORTED_OUTPUT_LOCALES:
        if cleaned.casefold().startswith(f"{tag.casefold()}-"):
            return tag
    return DEFAULT_OUTPUT_LOCALE


def language_name(locale: str | None) -> str:
    """How the prompt names the language it must write in."""
    return SUPPORTED_OUTPUT_LOCALES[normalize_output_locale(locale)]


__all__ = [
    "DEFAULT_OUTPUT_LOCALE",
    "SUPPORTED_OUTPUT_LOCALES",
    "language_name",
    "normalize_output_locale",
]
