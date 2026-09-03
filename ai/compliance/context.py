"""
compliance/context.py

The input vocabulary for the regulatory graph.

`Classification` (Shape 2) carries what the RAG pipeline can infer from the
question: formulation type, source organism, jurisdiction. That is enough to
pick the relevant acts. It is NOT enough to decide obligations, because the
decisive facts under the Biological Diversity Act are facts about the
APPLICANT and the RESOURCE, not about the formulation:

  - is the applicant a section 3(2) person or a section 7 person?
  - was the resource accessed from India?
  - was it cultivated or wild-collected?

Two identical formulations produce opposite obligations depending on those
answers, so no amount of improvement to the classifier reaches them. They
have to be asked.

Hence: every field beyond the classification defaults to None, meaning
"unknown", and unknowns surface as questions rather than as a confident
negative. `missing_fields()` is what the API turns into follow-up prompts.
Shape 2 is unchanged -- this wraps it rather than editing a contract three
people depend on.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from typing import Any, Literal, Optional

ApplicantCategory = Literal[
    "indian_individual",           # citizen; section 7 path
    "indian_entity",               # Indian-registered, Indian-controlled; section 7 path
    "foreign_controlled_entity",   # registered in India but foreign-controlled; section 3(2)
    "non_resident_indian",         # section 3(2)
    "foreign_national",            # section 3(2)
]
ResourceOrigin = Literal["india", "outside_india", "mixed"]
ResourceCultivation = Literal["cultivated", "wild_collected", "mixed"]

# Fields that decide a blocking obligation. If one of these is unknown the
# assessment is explicitly incomplete -- reported as such, never rounded down
# to "no obligation found".
CRITICAL_FIELDS = ("applicant_category", "resource_origin")


@dataclass
class ComplianceContext:
    # -- from Classification (Shape 2) -------------------------------------
    formulation_type: Optional[str] = None
    source_organism: Optional[str] = None
    jurisdiction: Optional[str] = None

    # -- applicant facts ---------------------------------------------------
    applicant_category: Optional[ApplicantCategory] = None
    practitioner_is_registered_ayush: Optional[bool] = None

    # -- resource facts ----------------------------------------------------
    resource_origin: Optional[ResourceOrigin] = None
    resource_cultivation: Optional[ResourceCultivation] = None
    uses_biological_material: Optional[bool] = None
    uses_codified_tk: Optional[bool] = None

    # -- intent facts ------------------------------------------------------
    seeking_ipr: Optional[bool] = None
    ipr_already_granted: Optional[bool] = None
    intends_commercialisation: Optional[bool] = None

    # -- free text, used by the prior-art probe ----------------------------
    formulation_name: Optional[str] = None
    ingredients: Optional[list[str]] = None

    @classmethod
    def from_classification(cls, classification: Any, **overrides: Any) -> "ComplianceContext":
        """Build from a Shape-2 Classification plus whatever else is known.

        Accepts anything with the three Shape-2 attributes rather than
        importing Classification, because two modules define it
        (ai.shared.schema and ai.person_b_retrieval.schema) and binding to
        one of them would make this module pick a side in that duplication.
        """
        base: dict[str, Any] = {}
        if classification is not None:
            for name in ("formulation_type", "source_organism", "jurisdiction"):
                value = getattr(classification, name, None)
                if value is not None:
                    base[name] = value

        known = {f.name for f in fields(cls)}
        unknown = set(overrides) - known
        if unknown:
            raise TypeError(f"unknown context field(s): {sorted(unknown)}")

        base.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**base)

    def infer_defaults(self) -> "ComplianceContext":
        """Fill only what genuinely follows from what is already set.

        Deliberately minimal. Every inference here is a place the system can
        be confidently wrong, so the bar is that the implication has to be
        definitional rather than merely usual:

          - a plant/microbial/animal source organism IS biological material;
          - jurisdiction "india" is a statement about where the question is
            asked, NOT about where the resource came from, so it does not
            imply resource_origin.

        The second one is the tempting inference to make and the one that
        would produce wrong ABS advice most often.
        """
        if self.uses_biological_material is None and self.source_organism in (
            "plant", "microbial", "animal", "mixed",
        ):
            self.uses_biological_material = True
        return self

    def missing_fields(self, required: set[str]) -> list[str]:
        """Which fields the graph wanted but the context did not supply."""
        return sorted(
            name for name in required
            if getattr(self, name, None) is None and name in {f.name for f in fields(self)}
        )

    def missing_critical(self) -> list[str]:
        return [f for f in CRITICAL_FIELDS if getattr(self, f, None) is None]

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


# Human-readable prompts for the fields the graph can ask about. Keeping
# these next to the field definitions rather than in the API layer means a
# new trigger field cannot ship without someone deciding how to ask for it.
FIELD_QUESTIONS: dict[str, str] = {
    "applicant_category": (
        "Who is the applicant? (Indian individual / Indian-controlled entity / "
        "entity registered in India with foreign control / non-resident Indian / "
        "foreign national)"
    ),
    "resource_origin": (
        "Was the biological resource accessed from India, from outside India, or both?"
    ),
    "resource_cultivation": (
        "Was the plant material cultivated, or collected from the wild?"
    ),
    "uses_biological_material": (
        "Does the invention use biological material?"
    ),
    "uses_codified_tk": (
        "Does it rely on codified traditional knowledge (a classical Ayurvedic text)?"
    ),
    "practitioner_is_registered_ayush": (
        "Is the applicant a registered AYUSH practitioner?"
    ),
    "seeking_ipr": (
        "Are you seeking or planning to seek a patent or other IP right?"
    ),
    "ipr_already_granted": (
        "Has the IP right already been granted?"
    ),
    "intends_commercialisation": (
        "Do you intend to commercialise the resource or the resulting product?"
    ),
}


def question_for(field_name: str) -> str:
    return FIELD_QUESTIONS.get(field_name, f"Please specify {field_name.replace('_', ' ')}.")
