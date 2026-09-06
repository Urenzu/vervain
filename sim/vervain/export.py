"""Turn a GROMACS trajectory into something a browser can hold.

    python -m vervain.export --name rbd-ace2

Two reductions do the work, and both are stated in the manifest so the viewer
is not guessing:

Water is dropped. It is 83% of the beads here and nothing is learned by drawing
it — the same reduction every molecular viewer makes, for the same reason.

Coordinates are quantised to int16 against the solute's own extent. Float32
xyz for 2k beads over 1000 frames is 23 MB; int16 halves that, and the step is
sub-picometre against a 0.47 nm bead — four orders of magnitude below anything
visible. Scaling against the periodic box instead would be simpler and wrong:
ACE2 plus the RBD is longer end to end than this box's short axis, so the
extremities clip flat onto the boundary.

What survives is the protein: roughly 2,300 beads, which streams as a few MB.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from vervain import beads as beadlib
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
    """A protein-only trajectory with each molecule made whole.

    `-pbc whole` and nothing else. The obvious choice, `-pbc mol -center`,
    is wrong for a complex: it puts *each molecule's* centre inside the box
    independently, so two bound chains can land in different periodic images.
    The measured effect here was a 4.8 nm complex rendering 9.6 nm apart in
    every frame — not drifting apart, which would be dissociation, but starting
    apart, which is a wrapping artefact. Joining the groups is done in
    `_join_groups` below, where the box vectors are available per frame.
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


def _join_groups(positions, slices, box):
    """Put every group in the same periodic image as the first.

    `-pbc whole` keeps each molecule intact but says nothing about where the
    molecules sit relative to one another. For a bound complex that matters
    enormously: the RBD can be a full box-length away from the ACE2 it is
    touching, and nothing downstream would flag it.

    The fix is a minimum-image shift of each group's centroid against the
    first group's. The box is a rhombic dodecahedron, so this has to go through
    a triclinic-aware routine rather than a per-axis rounding.
    """
    from MDAnalysis.lib.distances import minimize_vectors
    import numpy as np

    reference = positions[slices[0]].mean(axis=0)
    for sl in slices[1:]:
        centroid = positions[sl].mean(axis=0)
        delta = (centroid - reference).astype(np.float32)
        wrapped = minimize_vectors(delta.reshape(1, 3), box=box)[0]
        positions[sl] += wrapped - delta
    return positions


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


def _align_to_mean(frames, iterations: int = 2):
    """Remove global rotation, so fluctuation means fluctuation.

    Without this, a complex that tumbles rigidly reports large RMSF everywhere
    and the map says nothing. Superposition is onto the *whole* complex rather
    than each group separately, deliberately: aligning per group would hide the
    RBD rocking against ACE2, which is exactly the motion worth seeing.
    """
    import numpy as np

    reference = frames[0].copy()
    for _ in range(iterations):
        for i in range(len(frames)):
            # Kabsch. Both are already centred, so only rotation is left.
            covariance = frames[i].T @ reference
            u, _, vt = np.linalg.svd(covariance)
            # Guard against a reflection: an improper rotation would mirror the
            # structure and still minimise RMSD.
            d = np.sign(np.linalg.det(u @ vt))
            correction = np.diag([1.0, 1.0, d])
            frames[i] = frames[i] @ (u @ correction @ vt)
        reference = frames.mean(axis=0)
    return frames


def _rmsf(frames):
    """Per-bead root-mean-square fluctuation about the mean position, in nm."""
    import numpy as np

    mean = frames.mean(axis=0)
    return np.sqrt(((frames - mean) ** 2).sum(axis=-1).mean(axis=0))


def _bead_properties(work: Path, groups: list[BeadGroup]) -> tuple[list[float], list[str], dict]:
    """Radius and chemical class per bead, read from the Martini topologies."""
    radii: list[float] = []
    chemistry: list[str] = []

    for index in range(len(groups)):
        itp = work / f"molecule_{index}.itp"
        if not itp.exists():
            raise SystemExit(f"missing {itp.name}; cannot size or classify beads")
        parsed = beadlib.read_topology(itp)
        if len(parsed) != groups[index].beadCount:
            raise SystemExit(
                f"{itp.name} has {len(parsed)} beads but the group has "
                f"{groups[index].beadCount}. Topology and coordinates disagree."
            )
        print(f"  {groups[index].name:<16}{beadlib.summarise(parsed)}")
        radii.extend(bead.radius_nm for bead in parsed)
        chemistry.extend(bead.chemistry for bead in parsed)

    palette = {
        key: {"label": label, "color": color}
        for key, (label, color) in beadlib.CHEMISTRY.items()
    }
    palette["?"] = {"label": beadlib.UNKNOWN[0], "color": beadlib.UNKNOWN[1]}
    return radii, chemistry, palette


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

    print(f"exporting {name}")
    print(f"  frames     {frames}")
    print(f"  beads      {beads}")
    print(f"  box        {box_nm[0]:.2f} x {box_nm[1]:.2f} x {box_nm[2]:.2f} nm")

    # Pass one: centre every frame on the solute and find the true extent.
    # Quantising against the box instead looks equivalent and silently clips —
    # ACE2 plus the RBD is longer end to end than this box's short axis, so the
    # extremities would be flattened onto the boundary.
    groups = _groups_from_cg(work, beads)
    slices = [slice(g.offset, g.offset + g.beadCount) for g in groups]

    centred = np.empty((frames, beads, 3), dtype=np.float32)
    times_ps: list[float] = []
    contacts: list[float] = []
    for i, ts in enumerate(universe.trajectory):
        times_ps.append(float(ts.time))
        pos = _join_groups(ts.positions.copy(), slices, ts.dimensions) / 10.0
        centred[i] = pos - pos.mean(axis=0)

        # Closest approach between the first two groups. Reported rather than
        # assumed: this is what separates a complex that stayed bound from one
        # that came apart, and the difference is not visible in a render.
        if len(slices) >= 2:
            a, b = pos[slices[0]], pos[slices[1]]
            contacts.append(float(np.min(np.linalg.norm(a[:, None] - b[None], axis=-1))))

    # Superpose before measuring anything: tumbling is not flexibility.
    centred = _align_to_mean(centred)
    fluctuation = _rmsf(centred)
    print(f"  rmsf       {fluctuation.min():.3f}-{fluctuation.max():.3f} nm "
          f"(median {float(np.median(fluctuation)):.3f})")

    extent = np.abs(centred).max(axis=(0, 1)) * 1.001  # a hair of headroom
    extent = np.maximum(extent, 1e-3)

    # Pass two: encode. Nothing can clip now by construction, so a nonzero
    # count here would mean the extent calculation itself is wrong.
    raw = np.clip(centred / extent * INT16_MAX, -INT16_MAX, INT16_MAX).astype(np.int16)
    residual = float(np.abs(centred / extent).max())

    print(f"  extent     {extent[0]:.2f} x {extent[1]:.2f} x {extent[2]:.2f} nm "
          f"(half-widths)")
    if residual > 1.0:
        raise SystemExit(
            f"quantisation overflow: max |scaled| = {residual:.4f}. "
            "The extent calculation and the encode disagree."
        )
    # Worst-case error from int16 on the longest axis.
    print(f"  precision  {float(extent.max()) / INT16_MAX * 1000:.4f} pm per step")

    if contacts:
        print(f"  contact    {min(contacts):.2f}-{max(contacts):.2f} nm closest approach "
              f"between {groups[0].name} and {groups[1].name}")
        if min(contacts) > 1.0:
            print("  WARNING    the two groups never come within 1 nm — either the "
                  "complex dissociated or they are in different periodic images")

    interval = (times_ps[1] - times_ps[0]) if len(times_ps) > 1 else 1.0

    VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    positions = VIEWER_DIR / "positions.bin"
    positions.write_bytes(raw.tobytes())

    radii, chemistry, palette = _bead_properties(work, groups)

    manifest = {
        "schema": SCHEMA,
        "frameIntervalPs": interval,
        "frameCount": frames,
        "beadCount": beads,
        "boxNm": box_nm,
        "extentNm": [float(v) for v in extent],
        "forceField": "Martini 3.0.0",
        "positions": positions.name,
        "groups": [asdict(g) for g in groups],
        # Per bead, in trajectory order. Radius and chemistry come from the
        # topology; flexibility is measured from this trajectory.
        "radiusNm": [round(r, 4) for r in radii],
        "chemistry": chemistry,
        "chemistryPalette": palette,
        "rmsfNm": [round(float(v), 4) for v in fluctuation],
    }
    (VIEWER_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

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
