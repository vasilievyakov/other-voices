"""Tests for src.recipes — recipe registry and execution."""

import json
from unittest.mock import patch, MagicMock

from src.recipes import RECIPES, get_recipe, list_recipes, run_recipe


def _mock_ollama(response_text):
    """Create a mock urlopen response."""
    body = json.dumps({"response": response_text}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# =============================================================================
# Recipe Registry (4 tests)
# =============================================================================


class TestRecipeRegistry:
    def test_all_recipes_have_required_keys(self):
        """Every recipe has name, display_name, description, prompt."""
        for name, recipe in RECIPES.items():
            assert recipe["name"] == name
            assert "display_name" in recipe
            assert "description" in recipe
            assert "prompt" in recipe
            assert len(recipe["prompt"]) > 20

    def test_get_recipe_existing(self):
        r = get_recipe("action-items")
        assert r is not None
        assert r["name"] == "action-items"

    def test_get_recipe_nonexistent(self):
        assert get_recipe("nonexistent") is None

    def test_list_recipes(self):
        recipes = list_recipes()
        assert len(recipes) == len(RECIPES)
        names = {r["name"] for r in recipes}
        assert "tldr" in names
        assert "follow-up-email" in names


# =============================================================================
# Run Recipe (6 tests)
# =============================================================================


class TestRunRecipe:
    @patch("src.recipes.urllib.request.urlopen")
    def test_run_recipe_success(self, mock_urlopen):
        """Successful recipe run returns text."""
        mock_urlopen.return_value = _mock_ollama(
            "Here are the action items:\n1. Task A"
        )
        result = run_recipe("action-items", "A" * 100)
        assert result is not None
        assert "action items" in result.lower()

    def test_run_recipe_unknown_name(self):
        """Unknown recipe returns None."""
        result = run_recipe("nonexistent", "A" * 100)
        assert result is None

    def test_run_recipe_short_transcript(self):
        """Short transcript returns None."""
        result = run_recipe("tldr", "Short")
        assert result is None

    @patch("src.recipes.urllib.request.urlopen")
    def test_run_recipe_with_summary(self, mock_urlopen):
        """Summary context is included in prompt."""
        mock_urlopen.return_value = _mock_ollama("Result with summary context")
        summary = {"summary": "Test call about project", "action_items": []}
        result = run_recipe("action-items", "A" * 100, summary_json=summary)
        assert result is not None

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert "EXISTING SUMMARY" in payload["prompt"]

    @patch("src.recipes.urllib.request.urlopen")
    def test_run_recipe_ollama_error(self, mock_urlopen):
        """URLError returns None."""
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")
        result = run_recipe("tldr", "A" * 100)
        assert result is None

    @patch("src.recipes.urllib.request.urlopen")
    def test_run_recipe_truncates_long_transcript(self, mock_urlopen):
        """Long transcript is truncated."""
        mock_urlopen.return_value = _mock_ollama("OK")
        run_recipe("tldr", "A" * 20000)

        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert len(payload["prompt"]) < 20000
