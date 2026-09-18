"""Applies category/language rules on top of raw Xtream catalog data.

Categories and streams are kept as plain dicts straight out of the
upstream JSON: Xtream panels are inconsistent about whether ids
(category_id, stream_id, ...) are JSON numbers or strings, so every
comparison here goes through str() instead of relying on a fixed type.
"""

import re
from typing import Dict, List, Pattern, Sequence, Set, Tuple

from .config import CategoryFilter, LanguageFilter, SectionFilter


class LanguageMatcher:
    """Compiles the `languages:` section of the config once."""

    def __init__(self, patterns: Dict[str, List[Pattern]]):
        self._patterns = patterns

    @classmethod
    def compile(cls, defs: Dict[str, List[str]]) -> "LanguageMatcher":
        compiled = {code: [re.compile(p) for p in patterns] for code, patterns in defs.items()}
        return cls(compiled)

    def matches(self, code: str, text: str) -> bool:
        return any(pattern.search(text) for pattern in self._patterns.get(code, ()))

    def matches_any(self, codes: Sequence[str], text: str) -> bool:
        return any(self.matches(code, text) for code in codes)


def _name_allowed_by_category_filter(cf: CategoryFilter, name: str) -> bool:
    if cf.mode == "all":
        return True
    lname = name.lower()
    hit = any(candidate.lower() in lname for candidate in cf.names)
    if cf.mode == "include":
        return hit
    return not hit  # exclude


def _name_allowed_by_language_filter(lm: LanguageMatcher, lf: LanguageFilter, name: str) -> bool:
    if lf.mode == "all":
        return True
    hit = lm.matches_any(lf.codes, name)
    if lf.mode == "include":
        return hit
    return not hit  # exclude


def category_allowed(lm: LanguageMatcher, sf: SectionFilter, category_name: str) -> bool:
    return _name_allowed_by_category_filter(sf.categories, category_name) and _name_allowed_by_language_filter(
        lm, sf.languages, category_name
    )


def allowed_category_ids(
    lm: LanguageMatcher, sf: SectionFilter, categories: List[dict]
) -> Tuple[List[dict], Set[str]]:
    kept = []
    ids: Set[str] = set()
    for category in categories:
        if category_allowed(lm, sf, category.get("category_name", "")):
            kept.append(category)
            ids.add(str(category.get("category_id")))
    return kept, ids


def filter_by_category(items: List[dict], allowed_ids: Set[str]) -> List[dict]:
    return [item for item in items if str(item.get("category_id")) in allowed_ids]
