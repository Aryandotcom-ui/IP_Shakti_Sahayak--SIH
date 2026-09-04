"""
knowledge_graph/check.py

Fails loudly when the ontology and the corpus manifest disagree.

    python -m ai.knowledge_graph.check

Exit codes:
    0  every cited act is listed and ingested
    1  a cited act is listed but not yet ingested (expected during build-out)
    2  a cited act is absent from the manifest entirely — an act_name typo

The 1/2 split is the point. "Not ingested yet" is a normal state during a
build; "not in the manifest at all" almost always means the two files
disagree by a character, which is invisible at runtime because a Chroma
exact-match filter that matches nothing looks exactly like a topic with no
law about it. Wire this into CI so the typo cannot survive a commit.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .graph import RegulatoryGraph

DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "corpus.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--ontology", default=None)
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    graph = RegulatoryGraph.load(args.ontology)
    report = graph.validate_against_corpus(args.corpus)

    print(f"obligations : {len(graph.obligations)}")
    print(f"exemptions  : {len(graph.exemptions)}")
    print(f"regimes     : {len(graph.regimes)}")
    print(f"formulations: {len(graph.governed_by)}")
    print()
    print(f"acts cited and ingested : {len(report['ingested'])}")
    for a in report["ingested"]:
        print(f"    ok      {a}")
    if report["missing"]:
        print(f"acts cited, awaiting ingest : {len(report['missing'])}")
        for a in report["missing"]:
            print(f"    pending {a}")
    if report["unlisted"]:
        print(f"acts cited but NOT IN MANIFEST : {len(report['unlisted'])}")
        for a in report["unlisted"]:
            print(f"    DRIFT   {a}")

    # Every trigger field must be answerable, or the graph asks a question
    # the context layer has no vocabulary for and the obligation can never
    # fire. Cheap to check here, near-impossible to spot at runtime.
    from ..compliance.context import ComplianceContext

    known = {f for f in ComplianceContext.__dataclass_fields__}
    unknown = sorted(graph.context_fields() - known)
    if unknown:
        print()
        print(f"trigger fields with no ComplianceContext attribute: {unknown}")
        return 2

    if report["unlisted"]:
        return 2
    if report["missing"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
