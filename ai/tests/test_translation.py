"""
Tests for ai/translation.py — script-based language detection and the
translation edge wrapper.

    python -m pytest ai/tests/test_translation.py -v

The tests worth reading closely are the ones pinning what this module
refuses to do: NullTranslator never fabricates a translation, a
translation failure degrades to the original text rather than raising
past the request/response edge, and the exact-match citation contract is
untouched (this module has no function that would touch act_name at
all — its absence is the point, so there is no "does not translate
citations" test to write; see the module docstring instead).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.translation import (  # noqa: E402
    BhashiniTranslator,
    NullTranslator,
    TranslationError,
    TranslationResult,
    detect_language,
    get_translator,
    translate_answer_from_english,
    translate_query_to_english,
)


# ---------------------------------------------------------------------------
# detect_language: script heuristic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("क्या पारंपरिक आयुर्वेदिक फॉर्मूलेशन का पेटेंट कराया जा सकता है?", "hi"),
    ("இது தமிழ் மொழியில் ஒரு கேள்வி", "ta"),
    ("ఇది తెలుగు భాషలో ఒక ప్రశ్న", "te"),
    ("ಇದು ಕನ್ನಡ ಭಾಷೆಯಲ್ಲಿ ಒಂದು ಪ್ರಶ್ನೆ", "kn"),
    ("ഇത് മലയാളത്തിൽ ഒരു ചോദ്യമാണ്", "ml"),
    ("এটি বাংলা ভাষায় একটি প্রশ্ন", "bn"),
    ("Can a classical Ayurvedic formulation be patented in India?", "en"),
])
def test_detect_language_by_script(text, expected):
    assert detect_language(text) == expected


def test_detect_language_empty_string_defaults_to_english():
    assert detect_language("") == "en"


def test_detect_language_respects_custom_default():
    assert detect_language("", default="hi") == "hi"


def test_detect_language_mixed_script_picks_majority():
    # Mostly Hindi with a couple of Latin characters (a brand name, say)
    text = "क्या Ayurveda फॉर्मूलेशन का पेटेंट हो सकता है?"
    assert detect_language(text) == "hi"


def test_detect_language_never_raises_on_unusual_input():
    assert detect_language("12345 !@#$% 你好") == "en"  # no Indic/Arabic script -> default


# ---------------------------------------------------------------------------
# NullTranslator: the offline fallback
# ---------------------------------------------------------------------------


def test_null_translator_passes_through_unchanged_and_flags_it():
    t = NullTranslator()
    result = t.translate("क्या यह पेटेंट हो सकता है?", source_lang="hi", target_lang="en")
    assert result.text == "क्या यह पेटेंट हो सकता है?"
    assert result.translated is False
    assert result.backend == "none"


def test_null_translator_identity_when_languages_match():
    t = NullTranslator()
    result = t.translate("hello", source_lang="en", target_lang="en")
    assert result.text == "hello"
    assert result.translated is True  # trivially true, not a degraded case


def test_get_translator_without_credentials_returns_null():
    t = get_translator(None, None)
    assert isinstance(t, NullTranslator)
    t2 = get_translator("key", None)
    assert isinstance(t2, NullTranslator)
    t3 = get_translator(None, "user")
    assert isinstance(t3, NullTranslator)


def test_get_translator_with_both_credentials_returns_bhashini():
    t = get_translator("key", "user")
    assert isinstance(t, BhashiniTranslator)


# ---------------------------------------------------------------------------
# translate_query_to_english / translate_answer_from_english
# ---------------------------------------------------------------------------


def test_translate_query_uses_explicit_language_over_detection():
    t = NullTranslator()
    # Text looks Tamil, but caller says Hindi -- explicit wins.
    result = translate_query_to_english("இது ஒரு கேள்வி", translator=t, language="hi")
    assert result.source_lang == "hi"


def test_translate_query_falls_back_to_detection_when_no_language_given():
    t = NullTranslator()
    result = translate_query_to_english("இது ஒரு கேள்வி", translator=t)
    assert result.source_lang == "ta"


def test_translate_query_english_query_is_a_no_op():
    t = NullTranslator()
    result = translate_query_to_english("Can this be patented?", translator=t)
    assert result.source_lang == "en"
    assert result.target_lang == "en"
    assert result.translated is True
    assert result.text == "Can this be patented?"


def test_translate_answer_targets_requested_language():
    t = NullTranslator()
    result = translate_answer_from_english("The answer is yes.", translator=t, target_lang="hi")
    assert result.source_lang == "en"
    assert result.target_lang == "hi"
    assert result.text == "The answer is yes."  # NullTranslator: unchanged
    assert result.translated is False


class _RaisingTranslator:
    name = "raising"

    def translate(self, text, *, source_lang, target_lang):
        raise TranslationError("simulated backend outage")


def test_query_translation_degrades_to_original_text_on_error():
    result = translate_query_to_english("some query", translator=_RaisingTranslator(), language="hi")
    assert result.translated is False
    assert result.text == "some query"  # never lost, never raised past the edge


def test_answer_translation_degrades_to_english_text_on_error():
    result = translate_answer_from_english(
        "The answer.", translator=_RaisingTranslator(), target_lang="hi"
    )
    assert result.translated is False
    assert result.text == "The answer."


# ---------------------------------------------------------------------------
# BhashiniTranslator: pipeline shape handling (no live network)
# ---------------------------------------------------------------------------


def test_bhashini_translator_same_language_is_a_no_op_without_network():
    t = BhashiniTranslator("fake-key", "fake-user")
    result = t.translate("hello", source_lang="en", target_lang="en")
    assert result.text == "hello"
    assert result.translated is True


def test_bhashini_translator_empty_text_is_a_no_op_without_network():
    t = BhashiniTranslator("fake-key", "fake-user")
    result = t.translate("", source_lang="hi", target_lang="en")
    assert result.text == ""


def test_bhashini_resolve_pipeline_raises_translation_error_on_unreachable_host(monkeypatch):
    t = BhashiniTranslator("fake-key", "fake-user",
                            auth_url="https://this-host-does-not-resolve.invalid/x")
    with pytest.raises(TranslationError):
        t.translate("नमस्ते", source_lang="hi", target_lang="en")


def test_bhashini_pipeline_cache_is_keyed_by_language_pair():
    t = BhashiniTranslator("fake-key", "fake-user")
    t._pipeline_cache[("hi", "en")] = {"cached": True}
    assert t._resolve_pipeline("hi", "en") == {"cached": True}


def test_bhashini_translate_raises_on_malformed_pipeline_config(monkeypatch):
    t = BhashiniTranslator("fake-key", "fake-user")
    t._pipeline_cache[("hi", "en")] = {"unexpected": "shape"}
    with pytest.raises(TranslationError):
        t.translate("नमस्ते", source_lang="hi", target_lang="en")
