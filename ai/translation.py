"""
ai/translation.py

Thin multilingual wrapper for the request/response edge: translate a
query to English before it reaches retrieval, translate the answer back
to the requester's language afterward. Does not touch retrieval,
generation, or the corpus.

Why the edge, and why translation is not optional polish
------------------------------------------------------------
`ai/embedder.py`'s default model (`BAAI/bge-small-en-v1.5`) is
English-only — see `ai/README.md`'s note that documents are encoded with
a `passage: ` prefix and "the retrieval service must use `query: ` and
the same model". A non-English query embedded directly against an
English-embedded corpus does not retrieve reliably. Translating the
query to English first is not a UX nicety here — it is what makes
retrieval work at all for a non-English speaker.

Everything after that point — chunk text, `act_name`, citations — stays
in whatever language the corpus itself is in; only the free-text answer
and disclaimer translate back out. A citation is a legal identifier, not
prose: translating `"The Patents Act, 1970"` would break the exact-match
contract `ai/corpus.yaml`'s header describes, so `translate_answer()`
never touches `citations` or `sources`.

Script detection, not language identification
---------------------------------------------
`detect_language()` is a Unicode-script heuristic — which code block the
text's characters mostly fall in — not a trained language-ID model. It
tells Devanagari from Tamil; it cannot tell Hindi from Marathi, both of
which use Devanagari. Pass an explicit `language` when the caller knows
it (the API layer does, from the request); treat the heuristic as a
default for when nobody says, not as a source of truth.

Bhashini integration and its offline fallback
-----------------------------------------------
`BhashiniTranslator` implements the two-step ULCA pipeline documented at
bhashini.gov.in: a `getModelsPipeline` call resolves a translation task
to a service id and a compute endpoint, then a `/compute` call on that
endpoint runs it. It needs a live API key and user id this environment
does not have and cannot verify against the real service — treat the
default pipeline id and endpoint paths below as best-effort, confirm
them against current Bhashini API documentation before relying on this
in production, the same "verify before trusting" posture
`ai/patent_prep/deadlines.yaml` uses for its `review_status: draft`
rules.

`NullTranslator` is what the app runs against without configured
credentials: text passes through unchanged with `translated=False`
rather than the request failing, the same degrade-don't-crash posture
`ai/person_b_retrieval/embeddings.py` takes on a missing embedding model
and `ai/compliance/tkdl.py`'s `NullProbe` takes on an unavailable
prior-art source.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20  # seconds

# bhashini.gov.in's publicly documented default NMT (translation)
# pipeline id, widely used in integration examples. VERIFY against
# current Bhashini API documentation before depending on it — pipeline
# ids are configuration on their end, not something this module controls.
DEFAULT_BHASHINI_PIPELINE_ID = "64392f96daac500b55c543cd"
DEFAULT_BHASHINI_AUTH_URL = (
    "https://meity-auth.ulcacontrib.org/ulca/apis/v0/model/getModelsPipeline"
)


# ---------------------------------------------------------------------------
# Language (script) detection
# ---------------------------------------------------------------------------

# (first_codepoint, last_codepoint, language_code) — one dominant Indian
# language per Unicode script block. Where a script serves several
# languages (Devanagari: Hindi/Marathi/Sanskrit/Nepali; Bengali script:
# Bengali/Assamese), the code names the most widely spoken one. This is a
# default, not a determination — see the module docstring.
_SCRIPT_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x097F, "hi"),  # Devanagari
    (0x0980, 0x09FF, "bn"),  # Bengali
    (0x0A00, 0x0A7F, "pa"),  # Gurmukhi
    (0x0A80, 0x0AFF, "gu"),  # Gujarati
    (0x0B00, 0x0B7F, "or"),  # Odia
    (0x0B80, 0x0BFF, "ta"),  # Tamil
    (0x0C00, 0x0C7F, "te"),  # Telugu
    (0x0C80, 0x0CFF, "kn"),  # Kannada
    (0x0D00, 0x0D7F, "ml"),  # Malayalam
    (0x0600, 0x06FF, "ur"),  # Arabic script, used here for Urdu
)


def detect_language(text: str, *, default: str = "en") -> str:
    """Best-guess source language from the dominant Unicode script in
    `text`. Falls back to `default` (English) for Latin-script text or
    anything with no Indic/Arabic-script characters at all — never
    raises, since a bad guess here should degrade to "assume English",
    not break the request."""
    if not text:
        return default

    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for lo, hi, lang in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break

    if not counts:
        return default
    return max(counts, key=counts.get)


# ---------------------------------------------------------------------------
# Translator protocol
# ---------------------------------------------------------------------------


@dataclass
class TranslationResult:
    text: str
    source_lang: str
    target_lang: str
    translated: bool  # False means `text` was returned unchanged
    backend: str


class TranslationError(Exception):
    """A configured translator failed. Callers should catch this and
    degrade to the untranslated text (see backend/app/services/ai_service.py)
    rather than let a translation outage take down an answer the user can
    still use in the source language."""


class Translator(Protocol):
    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationResult: ...


class NullTranslator:
    """No translation backend configured. Passes text through unchanged.
    Trivially "translates" when source and target already match — that
    is not a degraded case, just the identity."""

    name = "none"

    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationResult:
        if source_lang == target_lang:
            return TranslationResult(text, source_lang, target_lang, True, self.name)
        return TranslationResult(text, source_lang, target_lang, False, self.name)


class BhashiniTranslator:
    """Real translation via the Bhashini ULCA pipeline API.

    Two HTTP calls per translation: resolve the pipeline (which service
    id and compute endpoint handle source_lang -> target_lang), then
    invoke it. Bhashini's own docs describe caching the pipeline
    resolution per language pair rather than re-resolving every call;
    this implementation does not cache across instances, so a
    long-running process should construct one BhashiniTranslator and
    reuse it rather than building a fresh one per request.
    """

    name = "bhashini"

    def __init__(
        self,
        api_key: str,
        user_id: str,
        *,
        pipeline_id: str = DEFAULT_BHASHINI_PIPELINE_ID,
        auth_url: str = DEFAULT_BHASHINI_AUTH_URL,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key
        self.user_id = user_id
        self.pipeline_id = pipeline_id
        self.auth_url = auth_url
        self.timeout = timeout
        self._pipeline_cache: dict[tuple[str, str], dict] = {}

    def _post_json(self, url: str, payload: dict, headers: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            raise TranslationError(f"Bhashini request to {url} failed: {exc}") from exc

    def _resolve_pipeline(self, source_lang: str, target_lang: str) -> dict:
        key = (source_lang, target_lang)
        if key in self._pipeline_cache:
            return self._pipeline_cache[key]

        payload = {
            "pipelineTasks": [{
                "taskType": "translation",
                "config": {
                    "language": {"sourceLanguage": source_lang, "targetLanguage": target_lang}
                },
            }],
            "pipelineRequestConfig": {"pipelineId": self.pipeline_id},
        }
        headers = {
            "Content-Type": "application/json",
            "userID": self.user_id,
            "ulcaApiKey": self.api_key,
        }
        config = self._post_json(self.auth_url, payload, headers)
        self._pipeline_cache[key] = config
        return config

    def translate(self, text: str, *, source_lang: str, target_lang: str) -> TranslationResult:
        if source_lang == target_lang or not text:
            return TranslationResult(text, source_lang, target_lang, True, self.name)

        config = self._resolve_pipeline(source_lang, target_lang)
        try:
            compute_url = config["pipelineInferenceAPIEndPoint"]["callbackUrl"]
            auth_header = config["pipelineInferenceAPIEndPoint"]["inferenceApiKey"]
            service_id = config["pipelineResponseConfig"][0]["config"][0]["serviceId"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError(
                f"unexpected Bhashini pipeline-config shape: {exc}"
            ) from exc

        headers = {
            "Content-Type": "application/json",
            auth_header["name"]: auth_header["value"],
        }
        compute_payload = {
            "pipelineTasks": [{
                "taskType": "translation",
                "config": {
                    "language": {"sourceLanguage": source_lang, "targetLanguage": target_lang},
                    "serviceId": service_id,
                },
            }],
            "inputData": {"input": [{"source": text}]},
        }
        result = self._post_json(compute_url, compute_payload, headers)
        try:
            translated = result["pipelineResponse"][0]["output"][0]["target"]
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError(f"unexpected Bhashini compute response shape: {exc}") from exc

        return TranslationResult(translated, source_lang, target_lang, True, self.name)


def get_translator(api_key: str | None, user_id: str | None) -> Translator:
    """Real Bhashini client when both credentials are configured, else
    the pass-through — mirrors ai.compliance.tkdl.get_probe()'s
    prefer-the-real-thing-else-degrade shape."""
    if api_key and user_id:
        return BhashiniTranslator(api_key, user_id)
    log.info("Bhashini credentials not configured — running with NullTranslator "
             "(queries and answers pass through untranslated)")
    return NullTranslator()


# ---------------------------------------------------------------------------
# Request/response edge helpers
# ---------------------------------------------------------------------------


def translate_query_to_english(
    query: str,
    *,
    translator: Translator,
    language: str | None = None,
) -> TranslationResult:
    """Translate an incoming query to English for retrieval. `language`
    should come from the request when the caller supplied one;
    otherwise falls back to detect_language()."""
    source_lang = language or detect_language(query)
    try:
        return translator.translate(query, source_lang=source_lang, target_lang="en")
    except TranslationError:
        log.exception("query translation failed, falling back to the original text")
        return TranslationResult(query, source_lang, "en", False, getattr(translator, "name", "?"))


def translate_answer_from_english(
    answer_text: str,
    *,
    translator: Translator,
    target_lang: str,
) -> TranslationResult:
    """Translate a generated answer back to the requester's language.
    Never touches citations/sources — see the module docstring."""
    try:
        return translator.translate(answer_text, source_lang="en", target_lang=target_lang)
    except TranslationError:
        log.exception("answer translation failed, returning the English text")
        return TranslationResult(answer_text, "en", target_lang, False, getattr(translator, "name", "?"))
