"""
tests/test_tools.py

Unit tests for the three FitFindr tools:
  - search_listings  (pure logic, no LLM)
  - suggest_outfit   (LLM call mocked)
  - create_fit_card  (LLM call mocked)

Run with:  python -m pytest tests/test_tools.py -v
"""

import sys
import os
import types
from unittest.mock import MagicMock, patch

import pytest

# Make sure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_groq_response(text: str):
    """Build a minimal mock that mimics groq ChatCompletion response shape."""
    msg = MagicMock()
    msg.content = text
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


SAMPLE_ITEM = {
    "id": "lst_001",
    "title": "Vintage Levi's 501 Jeans — Medium Wash",
    "description": "Classic 501s in a perfect medium wash.",
    "category": "bottoms",
    "style_tags": ["vintage", "classic", "denim", "streetwear"],
    "size": "W30 L30",
    "condition": "good",
    "price": 38.0,
    "colors": ["blue", "indigo"],
    "brand": "Levi's",
    "platform": "depop",
}

SAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans, dark wash",
            "category": "bottoms",
            "colors": ["dark blue", "indigo"],
            "style_tags": ["denim", "streetwear", "baggy"],
        },
        {
            "id": "w_002",
            "name": "White oversized tee",
            "category": "tops",
            "colors": ["white"],
            "style_tags": ["casual", "streetwear", "oversized"],
        },
    ]
}

EMPTY_WARDROBE = {"items": []}


# ══════════════════════════════════════════════════════════════════════════════
# Tool 1: search_listings
# ══════════════════════════════════════════════════════════════════════════════

class TestSearchListings:

    def test_returns_list(self):
        from tools import search_listings
        result = search_listings("vintage jeans")
        assert isinstance(result, list)

    def test_keyword_match_returns_results(self):
        from tools import search_listings
        results = search_listings("vintage jeans")
        assert len(results) > 0

    def test_keyword_no_match_returns_empty(self):
        from tools import search_listings
        results = search_listings("xyzzy gobbledygook")
        assert results == []

    def test_max_price_filters_out_expensive(self):
        from tools import search_listings
        results = search_listings("vintage", max_price=1.00)
        assert all(item["price"] <= 1.00 for item in results)

    def test_max_price_inclusive(self):
        from tools import search_listings
        # Use a real listing's price to confirm inclusive boundary
        results = search_listings("vintage jeans", max_price=38.0)
        prices = [item["price"] for item in results]
        assert any(p == 38.0 for p in prices), "Inclusive boundary should include price=38.0"

    def test_size_filter_exact(self):
        from tools import search_listings
        results = search_listings("jeans", size="W30")
        assert all("w30" in item.get("size", "").lower() for item in results)

    def test_size_filter_no_match(self):
        from tools import search_listings
        results = search_listings("jeans", size="XXXXL_NONEXISTENT")
        assert results == []

    def test_size_filter_case_insensitive(self):
        from tools import search_listings
        lower = search_listings("jeans", size="w30")
        upper = search_listings("jeans", size="W30")
        assert [i["id"] for i in lower] == [i["id"] for i in upper]

    def test_sorted_by_relevance(self):
        from tools import search_listings
        results = search_listings("vintage denim streetwear")
        # First result should score >= last result (already sorted desc)
        if len(results) >= 2:
            first_score = sum(
                1 for kw in ["vintage", "denim", "streetwear"]
                if kw in (results[0].get("title", "") + " ".join(results[0].get("style_tags", []))).lower()
            )
            last_score = sum(
                1 for kw in ["vintage", "denim", "streetwear"]
                if kw in (results[-1].get("title", "") + " ".join(results[-1].get("style_tags", []))).lower()
            )
            assert first_score >= last_score

    def test_combined_filters(self):
        from tools import search_listings
        results = search_listings("jeans", size="W30", max_price=50.0)
        for item in results:
            assert item["price"] <= 50.0
            assert "w30" in item.get("size", "").lower()

    def test_never_raises(self):
        from tools import search_listings
        # Should not raise even with weird input
        try:
            search_listings("", size=None, max_price=None)
            search_listings("   ", size="M", max_price=0)
        except Exception as e:
            pytest.fail(f"search_listings raised unexpectedly: {e}")

    def test_returns_dicts_with_expected_keys(self):
        from tools import search_listings
        results = search_listings("vintage")
        if results:
            keys = {"id", "title", "price", "platform", "category"}
            assert keys.issubset(results[0].keys())


# ══════════════════════════════════════════════════════════════════════════════
# Tool 2: suggest_outfit
# ══════════════════════════════════════════════════════════════════════════════

class TestSuggestOutfit:

    @patch("tools._get_groq_client")
    def test_returns_string_with_wardrobe(self, mock_client_fn):
        mock_client_fn.return_value.chat.completions.create.return_value = (
            _make_groq_response("Pair the Levi's with your white oversized tee and chunky sneakers.")
        )
        from tools import suggest_outfit
        result = suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("tools._get_groq_client")
    def test_returns_string_with_empty_wardrobe(self, mock_client_fn):
        mock_client_fn.return_value.chat.completions.create.return_value = (
            _make_groq_response("These vintage jeans pair well with a simple white tee.")
        )
        from tools import suggest_outfit
        result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)
        assert isinstance(result, str)
        assert len(result) > 0

    @patch("tools._get_groq_client")
    def test_wardrobe_items_referenced_in_prompt(self, mock_client_fn):
        """Confirm wardrobe item names are passed to the LLM prompt."""
        captured_prompts = []

        def capture_call(**kwargs):
            msgs = kwargs.get("messages", [])
            captured_prompts.extend(msgs)
            return _make_groq_response("Some outfit suggestion.")

        mock_client_fn.return_value.chat.completions.create.side_effect = capture_call

        from tools import suggest_outfit
        suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)

        full_prompt = " ".join(m["content"] for m in captured_prompts)
        assert "Baggy straight-leg jeans" in full_prompt or "White oversized tee" in full_prompt

    @patch("tools._get_groq_client")
    def test_empty_wardrobe_does_not_crash(self, mock_client_fn):
        mock_client_fn.return_value.chat.completions.create.return_value = (
            _make_groq_response("General styling advice here.")
        )
        from tools import suggest_outfit
        try:
            result = suggest_outfit(SAMPLE_ITEM, EMPTY_WARDROBE)
            assert result != ""
        except Exception as e:
            pytest.fail(f"suggest_outfit raised with empty wardrobe: {e}")

    @patch("tools._get_groq_client")
    def test_uses_correct_model(self, mock_client_fn):
        called_with = {}

        def capture(**kwargs):
            called_with.update(kwargs)
            return _make_groq_response("outfit")

        mock_client_fn.return_value.chat.completions.create.side_effect = capture

        from tools import suggest_outfit
        suggest_outfit(SAMPLE_ITEM, SAMPLE_WARDROBE)

        assert called_with.get("model") == "llama-3.3-70b-versatile"


# ══════════════════════════════════════════════════════════════════════════════
# Tool 3: create_fit_card
# ══════════════════════════════════════════════════════════════════════════════

OUTFIT_STR = "Pair the Levi's with your white tee and chunky sneakers for a clean streetwear look."
ERROR_MSG = "Could not generate fit card — outfit data is incomplete."


class TestCreateFitCard:

    @patch("tools._get_groq_client")
    def test_returns_string_on_valid_input(self, mock_client_fn):
        mock_client_fn.return_value.chat.completions.create.return_value = (
            _make_groq_response("Thrifted these Levi's on depop for $38 and couldn't be happier.")
        )
        from tools import create_fit_card
        result = create_fit_card(OUTFIT_STR, SAMPLE_ITEM)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_outfit_returns_error(self):
        from tools import create_fit_card
        assert create_fit_card("", SAMPLE_ITEM) == ERROR_MSG

    def test_whitespace_only_outfit_returns_error(self):
        from tools import create_fit_card
        assert create_fit_card("   ", SAMPLE_ITEM) == ERROR_MSG

    def test_missing_title_returns_error(self):
        from tools import create_fit_card
        bad_item = {**SAMPLE_ITEM, "title": ""}
        assert create_fit_card(OUTFIT_STR, bad_item) == ERROR_MSG

    def test_missing_price_returns_error(self):
        from tools import create_fit_card
        bad_item = {k: v for k, v in SAMPLE_ITEM.items() if k != "price"}
        assert create_fit_card(OUTFIT_STR, bad_item) == ERROR_MSG

    def test_missing_platform_returns_error(self):
        from tools import create_fit_card
        bad_item = {**SAMPLE_ITEM, "platform": ""}
        assert create_fit_card(OUTFIT_STR, bad_item) == ERROR_MSG

    @patch("tools._get_groq_client")
    def test_uses_high_temperature(self, mock_client_fn):
        called_with = {}

        def capture(**kwargs):
            called_with.update(kwargs)
            return _make_groq_response("caption text")

        mock_client_fn.return_value.chat.completions.create.side_effect = capture

        from tools import create_fit_card
        create_fit_card(OUTFIT_STR, SAMPLE_ITEM)

        assert called_with.get("temperature", 0) >= 0.9

    @patch("tools._get_groq_client")
    def test_uses_correct_model(self, mock_client_fn):
        called_with = {}

        def capture(**kwargs):
            called_with.update(kwargs)
            return _make_groq_response("caption text")

        mock_client_fn.return_value.chat.completions.create.side_effect = capture

        from tools import create_fit_card
        create_fit_card(OUTFIT_STR, SAMPLE_ITEM)

        assert called_with.get("model") == "llama-3.3-70b-versatile"

    @patch("tools._get_groq_client")
    def test_item_details_in_prompt(self, mock_client_fn):
        captured = []

        def capture(**kwargs):
            captured.extend(kwargs.get("messages", []))
            return _make_groq_response("caption")

        mock_client_fn.return_value.chat.completions.create.side_effect = capture

        from tools import create_fit_card
        create_fit_card(OUTFIT_STR, SAMPLE_ITEM)

        full_prompt = " ".join(m["content"] for m in captured)
        assert "depop" in full_prompt.lower()
        assert "38" in full_prompt
        assert "levi" in full_prompt.lower()

    @patch("tools._get_groq_client")
    def test_does_not_crash_on_valid_input(self, mock_client_fn):
        mock_client_fn.return_value.chat.completions.create.return_value = (
            _make_groq_response("Great caption here.")
        )
        from tools import create_fit_card
        try:
            create_fit_card(OUTFIT_STR, SAMPLE_ITEM)
        except Exception as e:
            pytest.fail(f"create_fit_card raised unexpectedly: {e}")
