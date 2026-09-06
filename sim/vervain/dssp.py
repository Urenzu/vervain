"""Secondary structure assignment, decoupled from vermouth's DSSP handling.

martinize2 shells out to DSSP with 2.x-era flags. Ubuntu ships mkdssp 4.5,
whose command line changed, so the call fails with "unknown option" and
vermouth warns that it is only tested against 2.2.1 and 3.0.0 anyway.

Rather than pin an ancient binary, this runs mkdssp 4 in its classic output
mode and parses the result, then hands martinize2 a plain string via `-ss`.
That sidesteps the version coupling entirely and keeps the full eight-state
assignment — MDAnalysis's bundled pure-Python DSSP is an alternative but
collapses to three states (H/E/loop), and Martini maps bead types from the
finer classes.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

# DSSP leaves coil blank; Martini wants a character.
COIL = "C"

# What vermouth's Martini mapping table knows. It was written against DSSP 2/3,
# and DSSP 4 assigns codes those versions never emitted — notably P for
# polyproline II helix, which lands as a KeyError deep inside vermouth rather
# than as anything a caller could interpret.
VERMOUTH_CODES = frozenset("HBEGITS" + COIL)

# Codes DSSP 4 added, mapped to what DSSP 2/3 would have reported for the same
# residues. PPII was simply not a category then; those residues came out coil.
DSSP4_FALLBACK = {"P": COIL}

# Chain breaks. DSSP emits these as spacer rows, not residues.
BREAK_MARKERS = frozenset({"!", "!*"})


class DSSPError(RuntimeError):
    pass


def _binary() -> str:
    found = shutil.which("mkdssp") or shutil.which("dssp")
    if not found:
        raise DSSPError(
            "mkdssp not found. Install it with: sudo apt-get install -y dssp"
        )
    return found


def run_dssp(pdb: Path) -> dict[tuple[str, int], str]:
    """(chain, residue number) -> single-character secondary structure."""
    binary = _binary()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.dssp"
        proc = subprocess.run(
            [binary, "--output-format", "dssp", str(pdb), str(out)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not out.exists():
            raise DSSPError(
                f"mkdssp failed on {pdb.name}:\n{(proc.stderr or proc.stdout)[-1500:]}"
            )
        text = out.read_text(encoding="utf-8", errors="replace")

    assignment: dict[tuple[str, int], str] = {}
    in_body = False
    for line in text.splitlines():
        if not in_body:
            # The residue table starts after this header row.
            if line.startswith("  #  RESIDUE"):
                in_body = True
            continue
        if len(line) < 17:
            continue
        if line[13:14] in BREAK_MARKERS:
            continue

        chain = line[11:12].strip()
        raw_number = line[5:10].strip()
        if not raw_number:
            continue
        try:
            number = int(raw_number)
        except ValueError:
            continue

        code = line[16:17].strip() or COIL
        assignment[(chain, number)] = code

    if not assignment:
        raise DSSPError(f"mkdssp produced no residue rows for {pdb.name}")
    return assignment


def secondary_structure(pdb: Path) -> str:
    """The DSSP string in the order martinize2 will read the residues.

    Built by walking the file rather than the DSSP output, because the two can
    disagree: DSSP drops residues it cannot assign, and a string that is short
    by even one character silently shifts every downstream assignment.
    """
    import gemmi

    assignment = run_dssp(pdb)

    structure = gemmi.read_structure(str(pdb))
    structure.setup_entities()

    codes: list[str] = []
    missing = 0
    for chain in structure[0]:
        for residue in chain:
            info = gemmi.find_tabulated_residue(residue.name)
            if info is None or not info.is_amino_acid():
                continue
            code = assignment.get((chain.name, residue.seqid.num))
            if code is None:
                missing += 1
                code = COIL
            codes.append(code)

    if missing:
        # Usually terminal residues DSSP declines to assign. Worth saying out
        # loud: silently coiling a structured region would change the model.
        print(f"  dssp       {missing} residue(s) unassigned, defaulted to coil")

    return translate(codes)


def translate(codes: list[str]) -> str:
    """Bring a DSSP 4 assignment into the vocabulary vermouth understands."""
    out: list[str] = []
    remapped: dict[str, int] = {}
    for code in codes:
        if code not in VERMOUTH_CODES:
            replacement = DSSP4_FALLBACK.get(code, COIL)
            remapped[code] = remapped.get(code, 0) + 1
            code = replacement
        out.append(code)

    for code, count in sorted(remapped.items()):
        target = DSSP4_FALLBACK.get(code, COIL)
        print(f"  dssp       remapped {count} residue(s) from "
              f"DSSP-4 '{code}' to '{target}' (pre-4 DSSP had no such class)")
    return "".join(out)


def summarise(ss: str) -> str:
    counts: dict[str, int] = {}
    for code in ss:
        counts[code] = counts.get(code, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    return "  ".join(f"{code}:{n}" for code, n in ordered)
