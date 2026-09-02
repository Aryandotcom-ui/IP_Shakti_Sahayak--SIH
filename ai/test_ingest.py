"""Tests for the ingestion pipeline.

The ones that matter are the section-integrity tests: if a section is
ever split or merged, the citation shown to the user stops matching the
text it sits next to, and the whole grounding claim collapses.

    python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ingest.extract import PDFOpenError, ScannedPDFError, extract  # noqa: E402
from ingest.metadata import infer_effective_date, infer_instrument_type, infer_jurisdiction  # noqa: E402
from ingest.schema import Chunk, SCHEMA_KEYS, SchemaError, content_hash, validate_all  # noqa: E402
from ingest.sectioner import chunk_sections, find_sections  # noqa: E402
from ingest.store import Registry  # noqa: E402

STATUTE = """THE PATENTS ACT, 1970

An Act to amend and consolidate the law relating to patents.

ARRANGEMENT OF SECTIONS

1. Short title, extent and commencement ................ 1
3. What are not inventions ............................. 2
4. Inventions relating to atomic energy ................ 3

1. Short title, extent and commencement.
This Act may be called the Patents Act, 1970 and extends to the whole of India.
It shall come into force on 20th April, 1972.

3. What are not inventions.
The following are not inventions within the meaning of this Act, that is to say,
(a) an invention which is frivolous;
(p) an invention which, in effect, is traditional knowledge or which is an
aggregation or duplication of known properties of traditionally known components.

4. Inventions relating to atomic energy not patentable.
No patent shall be granted in respect of an invention relating to atomic energy.
"""

TREATY = """WIPO TREATY ON GENETIC RESOURCES

Article 1
Objectives

The objectives of this Treaty are to enhance the efficacy of the patent system.

Article 3
Disclosure Requirement

(1) Where the claimed invention is based on genetic resources, each Contracting
Party shall require applicants to disclose the country of origin.
(2) Where based on traditional knowledge, applicants shall disclose the
Indigenous Peoples or local community who provided it.
"""


# ---------------------------------------------------------------- sectioning

def test_sections_are_detected():
    labels = [s.label for s in find_sections(STATUTE)]
    assert "Section 1" in labels
    assert "Section 3" in labels
    assert "Section 4" in labels


def test_section_is_never_split_or_merged():
    sections = {s.label: s.body for s in find_sections(STATUTE)}
    s3 = sections["Section 3"]
    # the whole of s.3 is present...
    assert "frivolous" in s3
    assert "traditional knowledge" in s3
    # ...and none of s.4 leaked in
    assert "atomic energy" not in s3


def test_toc_entries_do_not_become_sections():
    sections = find_sections(STATUTE)
    # exactly one section per real section, not one per contents line
    assert [s.label for s in sections].count("Section 3") == 1
    for s in sections:
        assert "......" not in s.body


def test_toc_lines_are_removed_from_bodies():
    for s in find_sections(STATUTE):
        assert "ARRANGEMENT OF SECTIONS" not in s.body


def test_articles_detected_in_treaties():
    labels = [s.label for s in find_sections(TREATY)]
    assert "Article 1" in labels
    assert "Article 3" in labels
    art3 = next(s for s in find_sections(TREATY) if s.label == "Article 3")
    assert "Indigenous Peoples" in art3.body  # sub-clause (2) not lost


def test_numbered_sentence_is_not_mistaken_for_a_heading():
    text = STATUTE + "\n\n1970. This year is mentioned in passing and is not a section.\n"
    labels = [s.label for s in find_sections(text)]
    assert "Section 1970" not in labels


def test_unstructured_text_yields_a_preamble_not_an_error():
    sections = find_sections("A notification with no section numbering at all. " * 10)
    assert len(sections) == 1
    assert sections[0].label == "Preamble"


def test_oversized_section_splits_at_subclause_boundaries():
    clauses = "\n".join(
        f"({i}) " + ("This sub-clause carries operative text of a statutory provision. " * 6)
        for i in range(1, 25)
    )
    long_text = "5. A very long section.\n" + clauses
    sections = find_sections(long_text)
    parts = chunk_sections(sections)
    assert len(parts) > 1, "a 10k-character section should have been split"
    for _, suffix, text in parts[1:]:
        assert suffix.startswith("p")
        assert "(part " in text
    # no part starts mid-sentence
    for _, _, text in parts:
        body = text.split("\n")[-1] if "(part" in text else text
        assert not body.lstrip().startswith("carries operative")


def test_short_section_is_not_split():
    parts = chunk_sections(find_sections(STATUTE))
    assert all(suffix == "" for _, suffix, _ in parts)


# ---------------------------------------------------------------- schema

def _chunk(**kw) -> Chunk:
    base = dict(
        chunk_id="the-patents-act-1970--s3", text="some operative text",
        jurisdiction="india", instrument_type="statute",
        act_name="The Patents Act, 1970", section="Section 3",
        effective_date="2005-04-01", source_url="https://example.gov.in",
    )
    base.update(kw)
    return Chunk(**base)


def test_to_dict_emits_exactly_the_contract_keys():
    assert tuple(_chunk().to_dict().keys()) == SCHEMA_KEYS


def test_provenance_never_reaches_the_payload():
    c = _chunk()
    c.provenance["page"] = 3
    assert "provenance" not in c.to_dict()
    assert "page" not in c.to_dict()


@pytest.mark.parametrize("bad", [
    {"jurisdiction": "India"},           # wrong case
    {"jurisdiction": "eu"},              # not in the enum
    {"instrument_type": "act"},          # not in the enum
    {"effective_date": "01-04-2005"},    # wrong format
    {"effective_date": "2005-13-01"},    # not a real date
    {"section": "  "},                   # empty
    {"text": ""},                        # empty
    {"chunk_id": "Bad Id"},              # not a slug
])
def test_validation_rejects_bad_fields(bad):
    with pytest.raises(SchemaError):
        _chunk(**bad).validate()


def test_duplicate_chunk_ids_are_rejected():
    with pytest.raises(SchemaError, match="duplicate"):
        validate_all([_chunk(), _chunk()])


def test_content_hash_ignores_whitespace_only_changes():
    assert content_hash("a  b\nc") == content_hash("a b c")
    assert content_hash("a b c") != content_hash("a b d")


# ---------------------------------------------------------------- metadata

def test_jurisdiction_inference():
    assert infer_jurisdiction("BE IT ENACTED by Parliament, Government of India") == "india"
    assert infer_jurisdiction(
        "The Contracting Parties, WIPO diplomatic conference, member states"
    ) == "international"


def test_instrument_type_inference():
    assert infer_instrument_type("An Act to consolidate the law", "patents-act.pdf") == "statute"
    assert infer_instrument_type(
        "The Contracting Parties to this Convention", "cbd.pdf") == "treaty"
    assert infer_instrument_type(
        "In exercise of the powers conferred, the Amendment Rules, 2024", "r.pdf") == "rule"


def test_effective_date_inference_flags_low_confidence():
    date, confident = infer_effective_date(
        "It shall come into force on 20th April, 1972.", "Patents Act, 1970")
    assert date == "1972-04-20" and confident
    date, confident = infer_effective_date("no date anywhere here", "Patents Act, 1970")
    assert date == "1970-01-01" and not confident


# ---------------------------------------------------------------- errors

def test_corrupt_pdf_raises(tmp_path: Path):
    p = tmp_path / "corrupt.pdf"
    p.write_bytes(b"%PDF-1.7\nnot a pdf\n")
    with pytest.raises(PDFOpenError):
        extract(p)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(PDFOpenError):
        extract(tmp_path / "nope.pdf")


def test_scanned_pdf_raises(tmp_path: Path):
    from make_test_pdfs import write_scanned
    p = tmp_path / "scan.pdf"
    write_scanned(p)
    with pytest.raises(ScannedPDFError, match="OCR"):
        extract(p)


# ---------------------------------------------------------------- registry

def test_registry_is_idempotent_and_detects_change(tmp_path: Path):
    reg = Registry(tmp_path / "reg.sqlite3")
    try:
        stats, dirty = reg.upsert([_chunk()])
        assert (stats.new, stats.changed, stats.unchanged) == (1, 0, 0)
        assert len(dirty) == 1

        stats, dirty = reg.upsert([_chunk()])
        assert (stats.new, stats.changed, stats.unchanged) == (0, 0, 1)
        assert dirty == []

        stats, dirty = reg.upsert([_chunk(text="amended operative text")])
        assert (stats.new, stats.changed, stats.unchanged) == (0, 1, 0)

        rows = reg.conn.execute(
            "SELECT superseded_at FROM chunk_versions WHERE chunk_id=? ORDER BY id",
            ("the-patents-act-1970--s3",),
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]["superseded_at"] is not None   # old version closed
        assert rows[1]["superseded_at"] is None       # new version current
    finally:
        reg.close()


def test_registry_reports_orphans(tmp_path: Path):
    reg = Registry(tmp_path / "reg.sqlite3")
    try:
        reg.upsert([_chunk(), _chunk(chunk_id="gone--s9")])
        assert reg.orphans(["the-patents-act-1970--s3"]) == ["gone--s9"]
    finally:
        reg.close()
