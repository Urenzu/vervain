"""Fetch the MARTINI 3 force-field files GROMACS needs.

vermouth ships the martini3001 *mapping* — how atoms become beads — but not the
GROMACS `.itp` files that define bead interactions, solvent, and ions. Those
come from the Marrink lab's own distribution, and they are a scientific input
like any other: the version determines the physics, so it is pinned and
recorded rather than fetched from whatever is current.

    python -m vervain.forcefield fetch
    python -m vervain.forcefield list
"""

from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from pathlib import Path

from vervain.structures import REPO_ROOT

FORCEFIELD_DIR = REPO_ROOT / "data" / "forcefield"

VERSION = "3.0.0"
SOURCE_REPO = "https://github.com/marrink-lab/martini-forcefields"
BASE = (
    "https://raw.githubusercontent.com/marrink-lab/martini-forcefields/"
    "main/martini_forcefields/regular/v3.0.0/gmx_files"
)

# What each file is for, so a future reader does not have to open them to find
# out which ones a given system actually needs.
FILES = {
    "martini_v3.0.0.itp": "bead types and nonbonded interaction matrix — always needed",
    "martini_v3.0.0_solvents_v1.itp": "W water and antifreeze",
    "martini_v3.0.0_ions_v1.itp": "NA, CL and friends",
    "martini_v3.0.0_phospholipids_v1.itp": "lipids — needed once a membrane exists",
}

CITATION = (
    "Souza et al., Martini 3: a general purpose force field for coarse-grained "
    "molecular dynamics. Nature Methods 2021;18:382-388. doi:10.1038/s41592-021-01098-3"
)


def fetch(force: bool = False) -> list[Path]:
    FORCEFIELD_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name in FILES:
        dest = FORCEFIELD_DIR / name
        if dest.exists() and not force:
            written.append(dest)
            continue
        url = f"{BASE}/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": "vervain/0"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                dest.write_bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"{name}: HTTP {exc.code} from {url}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"{name}: could not reach the source ({exc.reason})") from exc
        written.append(dest)

    # A provenance note beside the files, so the directory is self-describing
    # even when someone finds it outside the repo.
    (FORCEFIELD_DIR / "PROVENANCE.txt").write_text(
        f"Martini {VERSION}\n"
        f"source: {SOURCE_REPO}\n"
        f"path:   martini_forcefields/regular/v{VERSION}/gmx_files\n"
        f"cite:   {CITATION}\n\n"
        + "\n".join(f"{n}\n    {purpose}" for n, purpose in FILES.items())
        + "\n",
        encoding="utf-8",
    )
    return written


def available() -> bool:
    return all((FORCEFIELD_DIR / name).exists() for name in FILES)


def _cmd_list() -> int:
    print(f"Martini {VERSION}  —  {SOURCE_REPO}\n")
    for name, purpose in FILES.items():
        path = FORCEFIELD_DIR / name
        mark = "*" if path.exists() else " "
        size = f"{path.stat().st_size / 1024:.0f} KB" if path.exists() else "-"
        print(f"  {mark} {name:<42}{size:>9}  {purpose}")
    print(f"\n  * = present in {FORCEFIELD_DIR}")
    print(f"\n  {CITATION}")
    return 0


def _cmd_fetch(force: bool) -> int:
    for path in fetch(force=force):
        print(f"  {path.name:<42}{path.stat().st_size / 1024:>8.0f} KB")
    print(f"\n  {FORCEFIELD_DIR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vervain.forcefield", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="what is needed and what is present")
    p_fetch = sub.add_parser("fetch", help="download the force-field files")
    p_fetch.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    return _cmd_list() if args.command == "list" else _cmd_fetch(args.force)


if __name__ == "__main__":
    raise SystemExit(main())
