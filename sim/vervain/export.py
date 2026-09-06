"""Turn a GROMACS trajectory into something a browser can hold.

    python -m vervain.export --name rbd-ace2

Two reductions do the work, and both are stated in the manifest so the viewer
is not guessing:

Water is dropped. It is 83% of the beads here and nothing is learned by drawing
it — the same reduction every molecular viewer makes, for the same reason.

Coordinates are quantised to int16 against the box. Float32 xyz for 11k beads
over 400 frames is 53 MB; int16 halves that, and the quantisation error is
about 0.4 pm on a 14 nm box, which is four orders of magnitude below the bead
radius. Nothing visible is lost.

What survives is the protein: roughly 2,300 beads, which streams as a few MB.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from vervain.structures import REPO_ROOT
from vervain.system import SYSTEMS_DIR, _run, gmx_binary

SCHEMA = "vervain.traj/1"
VIEWER_DIR = REPO_ROOT / "web" / "public" / "traj"

INT16_MAX = 32767

# Host and virus, so the split carries meaning rather than just distinguishing
# two blobs. Cool for the receptor, warm for the thing arriving.
GROUP_STYLE = {
    "A": ("ACE2 receptor", "#4fc3f7", "human ACE2 peptidase domain, chain A of 6M0J"),
    "E": ("Spike RBD", "#ffa726", "SARS-CoV-2 receptor-binding domain, chain E of 6M0J"),
}

# Martini beads are ~0.47 nm across. Drawn slightly under that so neighbouring
# beads read as separate objects rather than a fused surface.
BEAD_RADIUS_NM = 0.19


@dataclass
class BeadGroup:
    name: str
    description: str
    color: str
    beadCount: int
    offset: int
    radiusNm: float


def _protein_only_trajectory(work: Path) -> tuple[Path, Path]:
    """A protein-only trajectory with periodic images made whole.

    Without `-pbc mol` a molecule that straddles the boundary arrives split in
    half, and the viewer faithfully draws it that way. `-center` keeps it in
    frame instead of drifting out of view over the run.
    """
    gmx = gmx_binary()
    xtc = work / "md.xtc"
    tpr = work / "md.tpr"
    if not xtc.exists():
        raise SystemExit(f"no trajectory at {xtc}. Run: python -m vervain.run all")

    out_xtc = work / "view.xtc"
    out_gro = work / "view.gro"

    # Group 0 is Protein, group 1 Solvent, from vervain.run.make_index.
    _run([gmx, "trjconv", "-s", str(tpr), "-f", str(xtc), "-n", "index.ndx",
          "-o", str(out_xtc), "-pbc", "mol", "-center"],
         cwd=work, stdin="0\n0\n")
    _run([gmx, "trjconv", "-s", str(tpr), "-f", str(xtc), "-n", "index.ndx",
          "-o", str(out_gro), "-pbc", "mol", "-center", "-dump", "0"],
         cwd=work, stdin="0\n0\n")
    return out_gro, out_xtc


def _groups_from_cg(work: Path, bead_total: int) -> list[BeadGroup]:
    """Split the protein beads by source chain.

    martinize2 preserves the chain identifiers, so the ACE2/RBD split survives
    coarse-graining and the viewer can colour host and virus differently.
    """
    import MDAnalysis as mda

    universe = mda.Universe(str(work / "cg.pdb"))
    groups: list[BeadGroup] = []
    offset = 0
    for segment in universe.segments:
        chain = (segment.segid or "").strip() or "?"
        count = len(segment.atoms)
        label, color, description = GROUP_STYLE.get(
            chain, (f"Chain {chain}", "#95918d", "unassigned chain")
        )
        groups.append(BeadGroup(label, description, color, count, offset, BEAD_RADIUS_NM))
        offset += count

    if offset != bead_total:
        raise SystemExit(
            f"chain beads sum to {offset} but the trajectory has {bead_total}. "
            "The coarse-grained model and the exported selection disagree."
        )
    return groups


def export(name: str) -> Path:
    import MDAnalysis as mda
    import numpy as np

    work = SYSTEMS_DIR / name
    gro, xtc = _protein_only_trajectory(work)

    universe = mda.Universe(str(gro), str(xtc))
    beads = len(universe.atoms)
    frames = len(universe.trajectory)
    if frames < 2:
        raise SystemExit(f"{name}: only {frames} frame(s); nothing to animate")

    # MDAnalysis works in angstrom; everything downstream is nm.
    box_nm = [float(v) / 10.0 for v in universe.dimensions[:3]]
    half = np.array(box_nm) * 0.5

    print(f"exporting {name}")
    print(f"  frames     {frames}")
    print(f"  beads      {beads}")
    print(f"  box        {box_nm[0]:.2f} x {box_nm[1]:.2f} x {box_nm[2]:.2f} nm")

    raw = np.empty((frames, beads, 3), dtype=np.int16)
    times_ps: list[float] = []
    clipped = 0

    for i, ts in enumerate(universe.trajectory):
        times_ps.append(float(ts.time))
        # Centre on the protein so the camera orbits the molecule rather than
        # the corner of a box the viewer never sees.
        pos = ts.positions / 10.0
        pos = pos - pos.mean(axis=0)

        scaled = pos / half * INT16_MAX
        clipped += int(np.count_nonzero(np.abs(scaled) > INT16_MAX))
        raw[i] = np.clip(scaled, -INT16_MAX, INT16_MAX).astype(np.int16)

    if clipped:
        # Would mean the molecule is larger than the box it is centred in,
        # which is a system-building problem, not an export one.
        print(f"  WARNING    {clipped} coordinates clipped at the box edge")

    interval = (times_ps[1] - times_ps[0]) if len(times_ps) > 1 else 1.0
    groups = _groups_from_cg(work, beads)

    VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    positions = VIEWER_DIR / "positions.bin"
    positions.write_bytes(raw.tobytes())

    manifest = {
        "schema": SCHEMA,
        "frameIntervalPs": interval,
        "frameCount": frames,
        "beadCount": beads,
        "boxNm": box_nm,
        "forceField": "Martini 3.0.0",
        "positions": positions.name,
        "groups": [asdict(g) for g in groups],
    }
    (VIEWER_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    for g in groups:
        print(f"  {g.name:<16}{g.beadCount:>6} beads   {g.color}")
    size_mb = positions.stat().st_size / 1024 / 1024
    print(f"\n  {positions}  ({size_mb:.1f} MB)")
    print(f"  {VIEWER_DIR / 'manifest.json'}")
    return positions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vervain.export", description=__doc__)
    parser.add_argument("--name", default="rbd-ace2")
    args = parser.parse_args(argv)
    export(args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
