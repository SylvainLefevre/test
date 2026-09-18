import unittest

from xtream_filter.config import CategoryFilter, LanguageFilter, SectionFilter
from xtream_filter.filters import (
    LanguageMatcher,
    allowed_category_ids,
    category_allowed,
    filter_by_category,
)


class CategoryFilterModesTest(unittest.TestCase):
    def setUp(self):
        self.lm = LanguageMatcher.compile({})

    def _sf(self, cf):
        return SectionFilter(categories=cf, languages=LanguageFilter(mode="all"))

    def test_all_passes_everything(self):
        self.assertTrue(category_allowed(self.lm, self._sf(CategoryFilter(mode="all")), "Adult Content"))

    def test_include_matches(self):
        sf = self._sf(CategoryFilter(mode="include", names=["france"]))
        self.assertTrue(category_allowed(self.lm, sf, "FRANCE | General"))

    def test_include_rejects_non_match(self):
        sf = self._sf(CategoryFilter(mode="include", names=["france"]))
        self.assertFalse(category_allowed(self.lm, sf, "Germany"))

    def test_exclude_matches_is_rejected(self):
        sf = self._sf(CategoryFilter(mode="exclude", names=["adult"]))
        self.assertFalse(category_allowed(self.lm, sf, "Adult Content"))

    def test_exclude_non_match_is_kept(self):
        sf = self._sf(CategoryFilter(mode="exclude", names=["adult"]))
        self.assertTrue(category_allowed(self.lm, sf, "Kids"))


class LanguageFilterModesTest(unittest.TestCase):
    def setUp(self):
        self.lm = LanguageMatcher.compile(
            {
                "FR": [r"(?i)\bFR\b", r"(?i)france"],
                "EN": [r"(?i)\bEN\b", r"(?i)\bUK\b"],
            }
        )

    def _sf(self, lf):
        return SectionFilter(categories=CategoryFilter(mode="all"), languages=lf)

    def test_all_passes_everything(self):
        self.assertTrue(category_allowed(self.lm, self._sf(LanguageFilter(mode="all")), "DE | Sport"))

    def test_include_fr_matches(self):
        sf = self._sf(LanguageFilter(mode="include", codes=["FR"]))
        self.assertTrue(category_allowed(self.lm, sf, "FR | Sport"))

    def test_include_fr_rejects_en(self):
        sf = self._sf(LanguageFilter(mode="include", codes=["FR"]))
        self.assertFalse(category_allowed(self.lm, sf, "UK | Sport"))

    def test_exclude_fr_drops_match(self):
        sf = self._sf(LanguageFilter(mode="exclude", codes=["FR"]))
        self.assertFalse(category_allowed(self.lm, sf, "FR | Sport"))

    def test_exclude_fr_keeps_other(self):
        sf = self._sf(LanguageFilter(mode="exclude", codes=["FR"]))
        self.assertTrue(category_allowed(self.lm, sf, "UK | Sport"))

    def test_include_multiple_codes_matches_second(self):
        sf = self._sf(LanguageFilter(mode="include", codes=["FR", "EN"]))
        self.assertTrue(category_allowed(self.lm, sf, "UK | News"))


class AllowedCategoryIdsAndStreamFilteringTest(unittest.TestCase):
    def test_end_to_end(self):
        lm = LanguageMatcher.compile({"FR": [r"(?i)^FR"]})
        sf = SectionFilter(
            categories=CategoryFilter(mode="exclude", names=["adult"]),
            languages=LanguageFilter(mode="include", codes=["FR"]),
        )
        categories = [
            {"category_id": "1", "category_name": "FR | General"},
            {"category_id": "2", "category_name": "FR | Adult"},
            {"category_id": "3", "category_name": "UK | General"},
        ]

        kept, ids = allowed_category_ids(lm, sf, categories)
        self.assertEqual([c["category_id"] for c in kept], ["1"])
        self.assertEqual(ids, {"1"})

        streams = [
            {"stream_id": "10", "category_id": "1", "name": "Chan A"},
            {"stream_id": "11", "category_id": "2", "name": "Chan B"},
            {"stream_id": "12", "category_id": "3", "name": "Chan C"},
        ]
        filtered = filter_by_category(streams, ids)
        self.assertEqual([s["stream_id"] for s in filtered], ["10"])

    def test_ids_compare_as_strings_regardless_of_json_type(self):
        # Xtream panels are inconsistent about numeric vs string ids.
        lm = LanguageMatcher.compile({})
        sf = SectionFilter(categories=CategoryFilter(mode="all"), languages=LanguageFilter(mode="all"))
        categories = [{"category_id": 1, "category_name": "General"}]
        _, ids = allowed_category_ids(lm, sf, categories)
        self.assertEqual(ids, {"1"})

        streams = [{"stream_id": 10, "category_id": "1"}]
        filtered = filter_by_category(streams, ids)
        self.assertEqual(len(filtered), 1)


if __name__ == "__main__":
    unittest.main()
