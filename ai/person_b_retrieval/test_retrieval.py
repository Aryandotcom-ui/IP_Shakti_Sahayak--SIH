import json
import os
import sys
from pathlib import Path
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.person_b_retrieval.schema import Chunk, Classification
from ai.person_b_retrieval.embeddings import Embedder
from ai.person_b_retrieval.retrieval import retrieve, filter_chunks

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "fake_chunks.json")


@pytest.fixture
def all_chunks():
    with open(FIXTURE_PATH) as f:
        raw = json.load(f)
    return [Chunk.from_dict(d) for d in raw]


@pytest.fixture
def embedder(all_chunks):
    e = Embedder()
    e.fit([c.text for c in all_chunks])
    return e


def test_filter_by_jurisdiction_india(all_chunks):
    filtered = filter_chunks(all_chunks, jurisdiction="india")
    assert len(filtered) > 0
    assert all(c.jurisdiction == "india" for c in filtered)


def test_filter_by_jurisdiction_international(all_chunks):
    filtered = filter_chunks(all_chunks, jurisdiction="international")
    assert len(filtered) > 0
    assert all(c.jurisdiction == "international" for c in filtered)


def test_filter_by_formulation_type_narrows_to_relevant_acts(all_chunks):
    from ai.shared.taxonomy import acts_for_formulation

    classification = Classification(formulation_type="aahar")
    filtered = filter_chunks(all_chunks, classification=classification)
    # "aahar" triggers both food-safety and ABS obligations (accessing a
    # biological resource for a food product still needs NBA approval), so
    # the relevant-acts list is graph-derived and covers more than the food
    # regulation alone. The fixture only carries two of those acts.
    relevant_acts = set(acts_for_formulation("aahar"))
    assert filtered
    assert all(c.act_name in relevant_acts for c in filtered)
    assert {c.act_name for c in filtered} == {
        "The Biological Diversity Act, 2002",
        "Food Safety and Standards (Ayurveda Aahar) Regulations, 2022",
    }


def test_retrieve_relevant_india_query_returns_correct_citation(all_chunks, embedder):
    result = retrieve(
        query="Can a classical Ayurvedic formulation be patented in India?",
        all_chunks=all_chunks,
        embedder=embedder,
        jurisdiction="india",
        classification=Classification(formulation_type="classical"),
    )
    assert result.should_abstain is False
    assert result.confidence > 0
    act_names = [c.act_name for c in result.matched_chunks]
    assert "The Patents Act, 1970" in act_names


def test_retrieve_relevant_international_query(all_chunks, embedder):
    result = retrieve(
        query="What does the Nagoya Protocol require for benefit sharing?",
        all_chunks=all_chunks,
        embedder=embedder,
        jurisdiction="international",
    )
    assert result.should_abstain is False
    act_names = [c.act_name for c in result.matched_chunks]
    assert any("Nagoya Protocol" in name for name in act_names)


def test_retrieve_never_mixes_jurisdictions_when_filtered(all_chunks, embedder):
    result = retrieve(
        query="patent and biodiversity rules",
        all_chunks=all_chunks,
        embedder=embedder,
        jurisdiction="india",
    )
    assert all(c.jurisdiction == "india" for c in result.matched_chunks)


def test_retrieve_unrelated_query_abstains(all_chunks, embedder):
    result = retrieve(
        query="What is the recipe for making biryani?",
        all_chunks=all_chunks,
        embedder=embedder,
    )
    assert result.should_abstain is True
    assert result.confidence < 0.20


def test_retrieve_no_candidates_after_filter_abstains(all_chunks, embedder):
    # No chunk in the fixture is both "international" AND matches an act
    # that only exists for india jurisdiction classical formulations —
    # forcing an empty candidate set to check the abstain-on-empty path.
    result = retrieve(
        query="anything",
        all_chunks=[c for c in all_chunks if c.jurisdiction == "india"],
        embedder=embedder,
        jurisdiction="international",  # deliberately mismatched
    )
    assert result.should_abstain is True
    assert result.matched_chunks == []
