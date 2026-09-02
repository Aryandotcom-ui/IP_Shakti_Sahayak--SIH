#!/usr/bin/env python3
"""Generate synthetic legal PDFs that reproduce the layout traps real
gazette and WIPO PDFs contain: a table of contents, running headers,
page numbers, hyphenated line breaks, numbered sub-clauses, and one
image-only document that must be rejected.

    python scripts/make_test_pdfs.py data/pdfs
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

PATENTS = """THE PATENTS ACT, 1970
(39 of 1970)

An Act to amend and consolidate the law relating to patents.

BE IT ENACTED by Parliament in the Twenty-first Year of the Republic of India.

ARRANGEMENT OF SECTIONS

1. Short title, extent and commencement ................ 1
2. Definitions and interpretation ...................... 1
3. What are not inventions ............................. 2
4. Inventions relating to atomic energy ................ 3
10. Contents of specifications ......................... 3

CHAPTER I — PRELIMINARY

1. Short title, extent and commencement.
(1) This Act may be called the Patents Act, 1970.
(2) It extends to the whole of India.
(3) It shall come into force on 20th April, 1972, and different dates may be
appointed for different provisions.

2. Definitions and interpretation.
(1) In this Act, unless the context otherwise requires,
(a) "Appellate Board" means the Appellate Board referred to in section 116;
(b) "invention" means a new product or process involving an inventive step and
capable of industrial application;
(c) "new invention" means any invention or technology which has not been anti-
cipated by publication in any document or used in the country or elsewhere in
the world before the date of filing of a patent application.

CHAPTER II — INVENTIONS NOT PATENTABLE

3. What are not inventions.
The following are not inventions within the meaning of this Act, that is to say,
(a) an invention which is frivolous or which claims anything obviously contrary
to well established natural laws;
(d) the mere discovery of a new form of a known substance which does not result
in the enhancement of the known efficacy of that substance;
(e) a substance obtained by a mere admixture resulting only in the aggregation
of the properties of the components thereof, or a process for producing such
substance;
(j) plants and animals in whole or any part thereof other than micro-organisms
but including seeds, varieties and species and essentially biological processes
for production or propagation of plants and animals;
(p) an invention which, in effect, is traditional knowledge or which is an
aggregation or duplication of known properties of traditionally known component
or components.

4. Inventions relating to atomic energy not patentable.
No patent shall be granted in respect of an invention relating to atomic energy
falling within sub-section (1) of section 20 of the Atomic Energy Act, 1962.

10. Contents of specifications.
(4) Every complete specification shall fully and particularly describe the
invention and its operation or use and the method by which it is to be performed,
and shall disclose the source and geographical origin of the biological material
used in the invention, and shall end with a claim or claims defining the scope of
the invention for which protection is claimed.
"""

GRATK = """WIPO TREATY ON INTELLECTUAL PROPERTY, GENETIC RESOURCES
AND ASSOCIATED TRADITIONAL KNOWLEDGE

adopted by the Diplomatic Conference at Geneva on May 24, 2024

PREAMBLE

The Contracting Parties, recognizing the role of the intellectual property
system in fostering innovation, and desiring to enhance the efficacy,
transparency and quality of the patent system with regard to genetic resources
and traditional knowledge associated with genetic resources, have agreed as
follows.

Article 1
Objectives

The objectives of this Treaty are to enhance the efficacy, transparency and
quality of the patent system with regard to genetic resources and traditional
knowledge associated with genetic resources, and to prevent patents from being
granted erroneously for inventions that are not novel or inventive.

Article 2
Use of Terms

For the purposes of this Treaty, "genetic resources" means genetic material of
actual or potential value, and "source of genetic resources" refers to any
source from which the applicant has obtained the genetic resources.

Article 3
Disclosure Requirement

(1) Where the claimed invention in a patent application is based on genetic
resources, each Contracting Party shall require applicants to disclose the
country of origin of the genetic resources, or, where that information is not
known to the applicant, the source of the genetic resources.
(2) Where the claimed invention in a patent application is based on traditional
knowledge associated with genetic resources, each Contracting Party shall require
applicants to disclose the Indigenous Peoples or local community, as applicable,
who provided the traditional knowledge.
(3) Where the information referred to is not known to the applicant, the
Contracting Party shall require the applicant to make a declaration to that
effect.

Article 4
Non-Retroactivity

Contracting Parties shall not impose the disclosure obligation on patent
applications having a filing date or priority date that precedes the entry into
force of this Treaty in respect of that Contracting Party.

Article 5
Sanctions and Remedies

Each Contracting Party shall put in place appropriate, effective and
proportionate legal, administrative or policy measures to address a failure to
provide the information required. No Contracting Party shall revoke or render
unenforceable a patent solely on the basis of an applicant's failure to disclose
the information, unless there has been fraudulent intent.
"""


def write_pdf(path: Path, body: str, header: str, title: str) -> None:
    doc = pymupdf.open()
    lines = body.strip().splitlines()
    per_page = 22
    page_no = 0
    for start in range(0, len(lines), per_page):
        page_no += 1
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_text((60, 46), header, fontsize=8, fontname="helv", color=(0.4, 0.4, 0.4))
        y = 84
        for line in lines[start : start + per_page]:
            page.insert_text((60, y), line[:98], fontsize=9.5, fontname="tiro")
            y += 15
        page.insert_text((295, 812), str(page_no), fontsize=8, fontname="helv")
    doc.set_metadata({"title": title})
    doc.save(path)
    doc.close()


def write_scanned(path: Path) -> None:
    """An image-only PDF — no text layer at all."""
    doc = pymupdf.open()
    for _ in range(3):
        page = doc.new_page(width=595, height=842)
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 600, 850))
        pix.clear_with(200)
        page.insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pix)
    doc.save(path)
    doc.close()


def write_corrupt(path: Path) -> None:
    path.write_bytes(b"%PDF-1.7\nthis is not actually a pdf\n%%EOF\n")


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "data/pdfs")
    out.mkdir(parents=True, exist_ok=True)

    write_pdf(out / "patents-act-1970.pdf", PATENTS,
              "THE GAZETTE OF INDIA EXTRAORDINARY", "The Patents Act, 1970")
    write_pdf(out / "wipo-gratk-2024.pdf", GRATK,
              "WIPO/GRATK/DC/2024", "WIPO Treaty on Genetic Resources, 2024")
    write_scanned(out / "scanned-notification.pdf")
    write_corrupt(out / "corrupt-file.pdf")

    for p in sorted(out.glob("*.pdf")):
        print(f"  {p.name:<32} {p.stat().st_size:>7} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
