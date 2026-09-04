"""
Regression test for a bug found while building the multilingual edge
(gap 7): backend/app/services/ai_service.py has always called

    generate_answer(retrieval, model=..., mock=False, api_key=...)

but generate_answer() (and the call_llm() it delegates to) accepted no
api_key parameter at all — only an ANTHROPIC_API_KEY environment
variable, per ai/person_c_generation/generate.py's own module
docstring. Every real (non-mocked, non-abstained) query has raised
TypeError since the backend was wired up. The existing test suite never
caught it because backend/tests/test_api.py's mocks of generate_answer
use a hand-written signature that happens to include api_key, diverging
from the real function.

    python -m pytest ai/tests/test_generate_api_key.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai.person_c_generation.generate import call_llm, generate_answer  # noqa: E402
from ai.person_b_retrieval.schema import MatchedChunk, RetrievalResult  # noqa: E402


def _fake_anthropic_module(captured: dict):
    """A stand-in for the `anthropic` package: records the api_key the
    client was constructed with and returns a canned response shaped
    like the real SDK's, without any network access."""
    module = MagicMock()

    def fake_anthropic_ctor(api_key):
        captured["api_key"] = api_key
        client = MagicMock()
        text_block = MagicMock(type="text", text='{"answer_text": "ok", "citations": [], "abstained": false}')
        client.messages.create.return_value = MagicMock(content=[text_block])
        return client

    module.Anthropic.side_effect = fake_anthropic_ctor
    return module


def test_call_llm_accepts_and_uses_explicit_api_key(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module(captured))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    text = call_llm("a prompt", api_key="explicit-key")

    assert captured["api_key"] == "explicit-key"
    assert "ok" in text


def test_call_llm_explicit_api_key_takes_precedence_over_env(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module(captured))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

    call_llm("a prompt", api_key="explicit-key")

    assert captured["api_key"] == "explicit-key"


def test_call_llm_falls_back_to_env_var_when_no_explicit_key(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module(captured))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

    call_llm("a prompt")  # api_key not passed -- matches the documented CLI usage

    assert captured["api_key"] == "env-key"


def test_call_llm_raises_clearly_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        call_llm("a prompt")


def test_generate_answer_forwards_api_key_to_call_llm(monkeypatch):
    """This is the exact call shape backend/app/services/ai_service.py
    uses: generate_answer(retrieval, model=..., mock=False, api_key=...).
    It must not raise TypeError."""
    captured = {}
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic_module(captured))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    chunk = MatchedChunk(
        chunk_id="c1", text="The Patents Act, 1970, section 3.",
        act_name="The Patents Act, 1970", section="3",
        jurisdiction="india", similarity_score=0.9,
    )
    retrieval = RetrievalResult(
        query="Can this be patented?", matched_chunks=[chunk],
        confidence=0.9, should_abstain=False,
    )

    result = generate_answer(retrieval, model="claude-sonnet-4-5", mock=False,
                              api_key="backend-configured-key")

    assert captured["api_key"] == "backend-configured-key"
    assert result.answer_text == "ok"


def test_generate_answer_mock_path_needs_no_api_key():
    chunk = MatchedChunk(
        chunk_id="c1", text="source text", act_name="Act", section="1",
        jurisdiction="india", similarity_score=0.9,
    )
    retrieval = RetrievalResult(
        query="q", matched_chunks=[chunk], confidence=0.9, should_abstain=False,
    )
    result = generate_answer(retrieval, mock=True)  # no api_key at all
    assert result.answer_text
