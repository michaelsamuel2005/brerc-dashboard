"""``python -m curation`` — write a licence-vetted CANDIDATES file for review.

Usage:

    python -m curation --contact conservation@example.org \
        --out species_assets.candidates.json \
        "Anguis fragilis" "Erithacus rubecula"

    # or read names from a file, one per line:
    python -m curation --contact ... --names-file species.txt --out ...

The output is NOT servable as written: it is marked ``"approved": false`` and
every ``approvalReference`` is empty.  The reviewer's job, per entry:

  1. open ``sourceUrl`` and confirm the licence really covers this file,
  2. replace the generated ``alt`` with a real description of the photograph,
  3. record the sign-off in ``approvalReference`` (e.g. a ticket or initials+date),
  4. delete entries that should not be published at all,

then set ``"approved": true`` at the top and deploy the file as
``SPECIES_ASSETS_FILE``.  The server re-validates everything on load and
refuses a file that is malformed or still unapproved.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from curation.species_media import Curator

DEFAULT_ALLOWED = frozenset({"cc0", "pd", "cc-by"})


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m curation", description=__doc__)
    parser.add_argument("names", nargs="*", help="scientific names to curate")
    parser.add_argument("--names-file", help="file with one scientific name per line")
    parser.add_argument(
        "--contact",
        default=os.getenv("CURATION_CONTACT", ""),
        help="email or URL for the outbound User-Agent (or set CURATION_CONTACT)",
    )
    parser.add_argument("--out", required=True, help="path for the candidates JSON")
    parser.add_argument(
        "--allowed-licences",
        default=",".join(sorted(DEFAULT_ALLOWED)),
        help="comma-separated canonical tokens (default: %(default)s)",
    )
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=0.25,
        help="politeness gap between outbound calls (default: %(default)s)",
    )
    return parser.parse_args(argv)


def _names(args: argparse.Namespace) -> list[str]:
    names = [n.strip() for n in args.names if n.strip()]
    if args.names_file:
        for line in Path(args.names_file).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.strip().startswith("#"):
                names.append(line.strip())
    # De-duplicate, preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(name)
    return unique


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    names = _names(args)
    if not names:
        print("no species names given (positional args or --names-file)", file=sys.stderr)
        return 2
    allowed = frozenset(
        token.strip().lower() for token in args.allowed_licences.split(",") if token.strip()
    )
    curator = Curator(
        contact=args.contact,
        allowed_licences=allowed,
        min_interval_seconds=args.min_interval_seconds,
    )

    species: list[dict] = []
    found_images = 0
    for name in names:
        info = curator.fetch(name)
        entry: dict = {"scientificName": name}
        if info.image is not None:
            image = asdict(info.image)
            image.pop("licence_url_assumed", None)
            image["approvalReference"] = ""
            entry["image"] = image
            found_images += 1
        if info.description is not None and info.description_source is not None:
            entry["description"] = info.description
            entry["descriptionSource"] = info.description_source
        if info.notes:
            entry["curatorNotes"] = info.notes
        if "image" in entry or "description" in entry:
            species.append(entry)
        status = "image" if info.image else "no image"
        described = "description" if info.description else "no description"
        print(f"  {name}: {status}, {described}")

    payload = {
        "approved": False,
        "reviewInstructions": (
            "For each entry: open sourceUrl and confirm the licence covers this exact "
            "file; rewrite alt to describe the photograph; record your sign-off in "
            "approvalReference; delete anything unsuitable. Then set approved to true. "
            "The server refuses this file until that is done."
        ),
        "allowedLicences": sorted(allowed),
        "species": species,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(
        f"wrote {len(species)} candidate entr{'y' if len(species) == 1 else 'ies'} "
        f"({found_images} with images) to {args.out} — NOT servable until reviewed "
        "and marked approved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
