"""Split a legal document at section/article boundaries.

The rule is: one section in, one chunk out. A section is never merged
with its neighbour and never cut in the middle of a sentence.

Naive regex matching fails on real statute PDFs in three specific ways,
so each has an explicit guard:

  * Table-of-contents pages look exactly like a run of headings.
    Guard: `_is_toc_line` (dotted leaders / trailing page number) plus a
    density check over the front matter.
  * Numbered sub-clauses and ordinary sentences that begin with a number
    ("14. of the said Act") match the same pattern as a heading.
    Guard: `_longest_increasing` keeps only candidates whose ordinals
    form an increasing run, which is what a real section list does.
  * A section longer than the embedding window still has to be split.
    Guard: `_split_oversized` cuts at sub-clause boundaries only, and
    repeats the heading on every part so each chunk stands alone.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Target size in characters. bge-small/e5-small take 512 tokens (~2000
# chars); we allow a section to overrun that rather than split it, and
# only force a split past HARD_MAX.
SOFT_MAX_CHARS = 2000
HARD_MAX_CHARS = 3500
MIN_BODY_CHARS = 40

_ROMAN = "IVXLCDM"

# Ordered by specificity: the first pattern that matches a line wins.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # "Article 27", "ARTICLE 27bis", "Art. 5"
    ("article", re.compile(r"^\s*(?:ARTICLE|Article|Art\.)\s+(\d+\s*(?:bis|ter|quater)?|[IVXLCDM]+)\b[.\u2014:\-\s]*(.*)$")),
    # "Section 3", "SECTION 3A"
    ("section_kw", re.compile(r"^\s*(?:SECTION|Section|Sec\.)\s+(\d+[A-Z]{0,2})\b[.\u2014:\-\s]*(.*)$")),
    # "Rule 12." / "RULE 12"
    ("rule_kw", re.compile(r"^\s*(?:RULE|Rule)\s+(\d+[A-Z]{0,2})\b[.\u2014:\-\s]*(.*)$")),
    # Bare Indian statute style: "3. What are not inventions" / "3A. ..."
    ("bare", re.compile(r"^\s*(\d{1,3}[A-Z]{0,2})\.\s+([A-Z\u201c\"'(].{2,150})$")),
    # Schedules
    ("schedule", re.compile(r"^\s*(?:THE\s+)?((?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)|\d+(?:ST|ND|RD|TH))\s+SCHEDULE\b(.*)$", re.I)),
]

_CHAPTER = re.compile(r"^\s*CHAPTER\s+([IVXLCDM]+|\d+)\b[.\u2014:\-\s]*(.*)$")
_TOC_HEADING = re.compile(r"^\s*(?:TABLE OF )?CONTENTS?\s*$|^\s*ARRANGEMENT OF (?:SECTIONS|RULES|ARTICLES)\s*$", re.I)
# "3.  Short title ......... 4"  or  "3. Short title    4"
_TOC_LINE = re.compile(r"(\.\s*){4,}\s*\d{1,4}\s*$|\s{3,}\d{1,4}\s*$")

# Sub-clause starts, used only when a section must be split.
_SUBCLAUSE = re.compile(r"^\s*(\(\d+\)|\(\s*[a-z]{1,3}\s*\)|\(\s*[ivxlc]{1,5}\s*\))\s")


@dataclass
class Section:
    """One section/article, plus where it came from."""

    number: str          # "3", "3A", "27", "FIRST"
    heading: str         # "What are not inventions"
    body: str            # heading line + everything until the next section
    kind: str            # article | section_kw | rule_kw | bare | schedule | preamble
    chapter: str | None
    start_offset: int
    start_page: int = 0

    @property
    def label(self) -> str:
        """Human-readable locator used for the `section` field."""
        if self.kind == "article":
            return f"Article {self.number}"
        if self.kind == "rule_kw":
            return f"Rule {self.number}"
        if self.kind == "schedule":
            return f"{self.number} Schedule".title()
        if self.kind == "preamble":
            return "Preamble"
        return f"Section {self.number}"


def _ordinal(num: str) -> tuple[int, int]:
    """Sort key for a section number: ('3A') -> (3, 1), ('27') -> (27, 0)."""
    m = re.match(r"^(\d+)([A-Z]*)$", num)
    if m:
        suffix = m.group(2)
        letter = 0
        for ch in suffix:
            letter = letter * 26 + (ord(ch) - 64)
        return int(m.group(1)), letter
    if all(c in _ROMAN for c in num.upper()) and num:
        values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        total, prev = 0, 0
        for ch in reversed(num.upper()):
            v = values.get(ch, 0)
            total += v if v >= prev else -v
            prev = max(prev, v)
        return total, 0
    return 10**6, 0  # named schedules etc. sort last


def _tidy(text: str) -> str:
    """Collapse the blank-line runs left where TOC lines were removed."""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _is_toc_line(line: str) -> bool:
    return bool(_TOC_LINE.search(line))


def _drop_toc_lines(lines: list[str]) -> list[str]:
    """Blank out contents entries before sectioning.

    Suppressing TOC *candidates* stops spurious sections, but the lines
    themselves still land inside whatever section precedes them —
    usually the preamble, which then embeds as a list of section titles
    and matches almost every query. They have to be removed from the
    text, not merely ignored as boundaries. Lines are replaced with ""
    rather than deleted so offsets stay usable for page mapping.

    The contents block ends at the first heading that is actually
    followed by operative text. That test is what distinguishes a
    leaderless contents entry ("3. What are not inventions", nothing
    after it) from the real heading of the same section further down.
    """
    out = list(lines)
    in_toc = False

    def has_body_after(i: int) -> bool:
        chars = 0
        for ln in lines[i + 1 : i + 8]:
            if any(p.match(ln) for _, p in _PATTERNS):
                break
            chars += len(ln.strip())
        return chars >= MIN_BODY_CHARS

    for i, line in enumerate(lines):
        stripped = line.strip()
        if _TOC_HEADING.match(line):
            in_toc = True
            out[i] = ""
            continue
        if _is_toc_line(line):
            out[i] = ""
            continue
        if not in_toc or not stripped:
            continue
        if _CHAPTER.match(line) or len(stripped) > 90:
            in_toc = False
            continue
        if any(p.match(line) for _, p in _PATTERNS):
            if has_body_after(i):
                in_toc = False   # this is the real heading; the block is over
            else:
                out[i] = ""      # leaderless contents entry
            continue
        in_toc = False
    return out



@dataclass
class _Candidate:
    kind: str
    number: str
    heading: str
    line_index: int
    offset: int


def _find_candidates(lines: list[str], offsets: list[int]) -> list[_Candidate]:
    out: list[_Candidate] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > 200:
            continue
        if _is_toc_line(line):
            continue
        for kind, pat in _PATTERNS:
            m = pat.match(line)
            if not m:
                continue
            number = re.sub(r"\s+", "", m.group(1)).upper()
            heading = (m.group(2) or "").strip(" .:\u2014-")
            out.append(_Candidate(kind, number, heading, i, offsets[i]))
            break
    return out


def _suppress_toc(cands: list[_Candidate], lines: list[str], total_lines: int) -> list[_Candidate]:
    """Drop candidates that sit inside a table of contents.

    A TOC is a dense run of headings with almost no body between them,
    in the front matter, often introduced by an explicit heading.
    """
    toc_start = None
    for i, line in enumerate(lines[: max(1, total_lines // 4)]):
        if _TOC_HEADING.match(line):
            toc_start = i
            break

    kept: list[_Candidate] = []
    for idx, c in enumerate(cands):
        nxt = cands[idx + 1].line_index if idx + 1 < len(cands) else total_lines
        gap_lines = [ln for ln in lines[c.line_index + 1 : nxt] if ln.strip()]
        body_chars = sum(len(ln) for ln in gap_lines)
        in_front_matter = c.line_index < total_lines * 0.25
        after_toc_heading = toc_start is not None and c.line_index > toc_start
        # A heading with essentially no body, in the front matter, is a
        # contents entry rather than the section itself.
        if body_chars < MIN_BODY_CHARS and (in_front_matter or after_toc_heading):
            continue
        kept.append(c)
    return kept


def _longest_increasing(cands: list[_Candidate]) -> list[_Candidate]:
    """Keep the longest subsequence whose section ordinals increase.

    Real statutes number sections monotonically. Sentences that merely
    begin with a digit, and numbered sub-clauses, break that order — this
    removes them without needing a hand-written blacklist. Articles and
    bare-numeric sections are checked together per `kind`, since a treaty
    and a schedule can legitimately restart numbering.
    """
    if len(cands) < 3:
        return cands

    result: list[_Candidate] = []
    for kind in {c.kind for c in cands}:
        group = [c for c in cands if c.kind == kind]
        if len(group) < 3:
            result.extend(group)
            continue
        keys = [_ordinal(c.number) for c in group]
        n = len(group)
        best = [1] * n
        prev = [-1] * n
        for i in range(n):
            for j in range(i):
                if keys[j] < keys[i] and best[j] + 1 > best[i]:
                    best[i] = best[j] + 1
                    prev[i] = j
        end = max(range(n), key=lambda i: best[i])
        chain = []
        while end != -1:
            chain.append(group[end])
            end = prev[end]
        dropped = len(group) - len(chain)
        if dropped:
            log.debug("sectioner: dropped %d out-of-order %r candidates", dropped, kind)
        result.extend(reversed(chain))

    return sorted(result, key=lambda c: c.line_index)


def find_sections(text: str) -> list[Section]:
    """Split `text` into sections. Never returns an empty list for
    non-empty input — an unstructured document becomes one preamble
    section, which the caller can then split by size."""
    lines = _drop_toc_lines(text.splitlines())
    offsets, running = [], 0
    for ln in lines:
        offsets.append(running)
        running += len(ln) + 1

    cands = _find_candidates(lines, offsets)
    cands = _suppress_toc(cands, lines, len(lines))
    cands = _longest_increasing(cands)

    if not cands:
        body = _tidy(text)
        return [Section("0", "", body, "preamble", None, 0)] if body else []

    # Track the chapter each section sits under.
    chapters: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _CHAPTER.match(line)
        if m:
            label = f"Chapter {m.group(1)}"
            if m.group(2).strip():
                label += f" — {m.group(2).strip()}"
            chapters.append((i, label))

    def chapter_for(line_index: int) -> str | None:
        current = None
        for idx, label in chapters:
            if idx <= line_index:
                current = label
            else:
                break
        return current

    sections: list[Section] = []

    preamble = _tidy("\n".join(lines[: cands[0].line_index]))
    if len(preamble) >= MIN_BODY_CHARS:
        sections.append(Section("0", "", preamble, "preamble", None, 0))

    for i, c in enumerate(cands):
        end_line = cands[i + 1].line_index if i + 1 < len(cands) else len(lines)
        body = _tidy("\n".join(lines[c.line_index : end_line]))
        if len(body) < MIN_BODY_CHARS:
            continue
        sections.append(
            Section(
                number=c.number,
                heading=c.heading,
                body=body,
                kind=c.kind,
                chapter=chapter_for(c.line_index),
                start_offset=c.offset,
            )
        )
    return sections


def _split_oversized(section: Section) -> list[tuple[str, str]]:
    """Split one very long section at sub-clause boundaries.

    Returns [(part_suffix, text)]. A single-part section returns
    [("", body)] so the caller has one code path.
    """
    if len(section.body) <= HARD_MAX_CHARS:
        return [("", section.body)]

    lines = section.body.splitlines()
    header = lines[0] if lines else section.heading

    # Prefer sub-clause starts; fall back to blank lines; never mid-sentence.
    breakpoints = [i for i, ln in enumerate(lines) if i > 0 and _SUBCLAUSE.match(ln)]
    if not breakpoints:
        breakpoints = [i for i, ln in enumerate(lines) if i > 0 and not ln.strip()]
    if not breakpoints:
        # Last resort: sentence boundaries, so we still never cut a sentence.
        sentences = re.split(r"(?<=[.;])\s+", section.body)
        parts, buf = [], ""
        for s in sentences:
            if buf and len(buf) + len(s) > SOFT_MAX_CHARS:
                parts.append(buf.strip())
                buf = ""
            buf += s + " "
        if buf.strip():
            parts.append(buf.strip())
        return [(f"p{i+1}", f"{header}\n(part {i+1} of {len(parts)})\n{p}")
                for i, p in enumerate(parts)]

    parts: list[str] = []
    current_start = 0
    for bp in breakpoints + [len(lines)]:
        candidate = "\n".join(lines[current_start:bp])
        if len(candidate) >= SOFT_MAX_CHARS:
            parts.append(candidate)
            current_start = bp
    tail = "\n".join(lines[current_start:]).strip()
    if tail:
        if parts and len(tail) < MIN_BODY_CHARS:
            parts[-1] += "\n" + tail
        else:
            parts.append(tail)

    total = len(parts)
    if total == 1:
        return [("", parts[0])]
    out = []
    for i, p in enumerate(parts):
        prefix = "" if i == 0 else f"{header}\n"
        out.append((f"p{i+1}", f"{prefix}(part {i + 1} of {total})\n{p}".strip()))
    return out


def chunk_sections(sections: list[Section]) -> list[tuple[Section, str, str]]:
    """Turn sections into (section, part_suffix, text) triples.

    Adjacent tiny sections are *not* merged: keeping "2. Definitions" as
    its own chunk with its own citation is worth more than the packing
    efficiency, because the citation is what the user is shown.
    """
    out: list[tuple[Section, str, str]] = []
    for s in sections:
        for suffix, text in _split_oversized(s):
            if text.strip():
                out.append((s, suffix, text.strip()))
    return out
