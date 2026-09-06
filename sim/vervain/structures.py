"""Fetch and inspect the experimental structures the pipeline builds on.

Deliberately dependency-free. This is step one of the chain and it runs before
any environment is set up, so it uses nothing but the standard library. A
structure parser good enough to answer "what is actually in this file" is about
sixty lines of fixed-column parsing; pulling in gemmi or biopython to count
chains would put a wheel between us and the first useful command.

    python -m vervain.structures list
    python -m vervain.structures fetch 6VXX
    python -m vervain.structures inspect 6VXX

Structures land in data/structures/ and are gitignored. The catalogue in
structures.yaml is the tracked artefact; the coordinates are not.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

RCSB = "https://files.rcsb.org/download/{pdb_id}.{ext}"

REPO_ROOT = Path(__file__).resolve().parents[2]
STRUCTURE_DIR = REPO_ROOT / "data" / "structures"
CATALOGUE = Path(__file__).with_name("structures.yaml")

# Solvent and cryo-additives. Present in almost every deposition, never part of
# the biological assembly, and they would otherwise dominate the hetero report.
CRYSTALLISATION_JUNK = frozenset({
    "HOH", "DOD", "SO4", "PO4", "GOL", "EDO", "PEG", "MPD", "TRS", "ACT",
    "CL", "NA", "K", "MG", "CA", "ZN", "IMD", "DMS", "FMT",
})

# N-linked glycan residues. These matter — the spike's glycan shield is ~40% of
# its surface — so they are reported separately rather than lumped with junk.
GLYCANS = frozenset({"NAG", "NDG", "BMA", "MAN", "FUC", "GAL", "SIA", "GLC", "A2G"})


@dataclass
class ChainReport:
    chain_id: str
    residue_count: int = 0
    first_seq: int | None = None
    last_seq: int | None = None
    gaps: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class StructureReport:
    pdb_id: str
    title: str
    method: str
    resolution: str
    chains: list[ChainReport]
    glycan_residues: int
    hetero: dict[str, int]
    atom_count: int


def structure_path(pdb_id: str, ext: str = "pdb") -> Path:
    return STRUCTURE_DIR / f"{pdb_id.upper()}.{ext}"


def fetch(pdb_id: str, ext: str = "pdb", force: bool = False) -> Path:
    """Download a structure from RCSB. Returns the local path."""
    pdb_id = pdb_id.upper()
    dest = structure_path(pdb_id, ext)
    if dest.exists() and not force:
        return dest

    url = RCSB.format(pdb_id=pdb_id, ext=ext)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "vervain/0 (structure fetch)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{pdb_id}: RCSB returned HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{pdb_id}: could not reach RCSB ({exc.reason})") from exc

    dest.write_bytes(payload)
    return dest


def inspect(pdb_id: str) -> StructureReport:
    """Report what a downloaded structure actually contains.

    The questions worth answering before a structure enters system building:
    which chains are present, where the unresolved gaps are (they have to be
    modelled or trimmed, and silently ignoring them puts holes in the protein),
    and how much of the glycan shield was resolved.
    """
    path = structure_path(pdb_id)
    if not path.exists():
        raise SystemExit(f"{pdb_id}: not downloaded. Run: python -m vervain.structures fetch {pdb_id}")

    title_parts: list[str] = []
    method = "unknown"
    resolution = "n/a"
    atom_count = 0
    glycan_residues = 0
    hetero: dict[str, int] = {}

    chains: dict[str, ChainReport] = {}
    seen_residue: set[tuple[str, int, str]] = set()

    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        record = raw[:6].strip()

        if record == "TITLE":
            title_parts.append(raw[10:].strip())
            continue
        if record == "EXPDTA":
            method = raw[10:].strip() or method
            continue
        if raw.startswith("REMARK   2 RESOLUTION."):
            resolution = raw[23:].strip()
            continue

        if record not in ("ATOM", "HETATM"):
            continue

        atom_count += 1
        res_name = raw[17:20].strip()
        chain_id = raw[21:22].strip() or "_"
        try:
            seq = int(raw[22:26])
        except ValueError:
            continue
        icode = raw[26:27].strip()

        key = (chain_id, seq, icode)
        if key in seen_residue:
            continue
        seen_residue.add(key)

        if record == "HETATM":
            if res_name in GLYCANS:
                glycan_residues += 1
            elif res_name not in CRYSTALLISATION_JUNK:
                hetero[res_name] = hetero.get(res_name, 0) + 1
            continue

        report = chains.setdefault(chain_id, ChainReport(chain_id))
        if report.first_seq is None:
            report.first_seq = seq
        elif report.last_seq is not None and seq > report.last_seq + 1:
            report.gaps.append((report.last_seq, seq))
        report.last_seq = seq
        report.residue_count += 1

    return StructureReport(
        pdb_id=pdb_id.upper(),
        title=" ".join(title_parts).strip() or "(no title)",
        method=method,
        resolution=resolution,
        chains=sorted(chains.values(), key=lambda c: c.chain_id),
        glycan_residues=glycan_residues,
        hetero=hetero,
        atom_count=atom_count,
    )


def read_catalogue() -> dict[str, dict[str, str]]:
    """Parse the id -> {field: value} entries from structures.yaml.

    A four-line reader rather than a yaml dependency, for the same reason the
    parser above is hand-rolled. It reads the flat scalar fields it needs and
    ignores block scalars; `list` only has to print a summary line.
    """
    entries: dict[str, dict[str, str]] = {}
    current: str | None = None
    in_structures = False

    for raw in CATALOGUE.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())

        if indent == 0:
            in_structures = raw.startswith("structures:")
            current = None
            continue
        if not in_structures:
            continue

        stripped = raw.strip()
        if indent == 2 and stripped.endswith(":"):
            current = stripped[:-1]
            entries[current] = {}
            continue
        if indent == 4 and current and ":" in stripped:
            key, _, value = stripped.partition(":")
            value = value.strip()
            if value and value not in (">", "|"):
                entries[current][key.strip()] = value.strip('"')

    return entries


def _cmd_list() -> int:
    entries = read_catalogue()
    print(f"{'PDB':<6} {'res':>6}  {'confidence':<10} name")
    print("-" * 78)
    for pdb_id, body in entries.items():
        local = "*" if structure_path(pdb_id).exists() else " "
        print(f"{pdb_id:<5}{local} {body.get('resolution_a', '-'):>6}  "
              f"{body.get('confidence', '-'):<10} {body.get('name', '')[:44]}")
    print("\n* = downloaded to data/structures/")
    return 0


def _cmd_fetch(pdb_ids: list[str], force: bool) -> int:
    catalogue = read_catalogue()
    targets = pdb_ids or list(catalogue)
    for pdb_id in targets:
        if pdb_id.upper() not in catalogue:
            print(f"warning: {pdb_id} is not in structures.yaml — add it with a source "
                  f"before it enters the pipeline", file=sys.stderr)
        path = fetch(pdb_id, "pdb", force=force)
        print(f"{pdb_id.upper():<6} {path.stat().st_size / 1024:>8.0f} KB  {path}")
    return 0


def _cmd_inspect(pdb_id: str) -> int:
    r = inspect(pdb_id)
    print(f"{r.pdb_id} — {r.title}")
    print(f"  method      {r.method}")
    print(f"  resolution  {r.resolution}")
    print(f"  atoms       {r.atom_count:,}")
    print()
    print(f"  {'chain':<7}{'residues':>9}{'range':>16}{'gaps':>7}")
    for c in r.chains:
        span = f"{c.first_seq}-{c.last_seq}" if c.first_seq is not None else "-"
        print(f"  {c.chain_id:<7}{c.residue_count:>9}{span:>16}{len(c.gaps):>7}")

    unresolved = [(c.chain_id, g) for c in r.chains for g in c.gaps]
    if unresolved:
        print(f"\n  unresolved gaps ({len(unresolved)}) — these need modelling or trimming")
        for chain_id, (a, b) in unresolved[:12]:
            print(f"    chain {chain_id}: {a + 1}-{b - 1}  ({b - a - 1} residues)")
        if len(unresolved) > 12:
            print(f"    ... and {len(unresolved) - 12} more")

    print(f"\n  glycan residues resolved: {r.glycan_residues}")
    if r.hetero:
        print("  other hetero groups:")
        for name, count in sorted(r.hetero.items(), key=lambda kv: -kv[1]):
            print(f"    {name:<6}{count:>5}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vervain.structures", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show the catalogue and what is downloaded")

    p_fetch = sub.add_parser("fetch", help="download structures from RCSB")
    p_fetch.add_argument("pdb_id", nargs="*", help="default: every id in the catalogue")
    p_fetch.add_argument("--force", action="store_true", help="re-download if present")

    p_inspect = sub.add_parser("inspect", help="report chains, gaps and glycans")
    p_inspect.add_argument("pdb_id")

    args = parser.parse_args(argv)
    if args.command == "list":
        return _cmd_list()
    if args.command == "fetch":
        return _cmd_fetch(args.pdb_id, args.force)
    return _cmd_inspect(args.pdb_id)


if __name__ == "__main__":
    raise SystemExit(main())
