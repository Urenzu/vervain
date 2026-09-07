"""Build the staged view of viral entry from measured structures.

This is not a simulation and does not pretend to be. Molecular dynamics can
reach microseconds; viral entry takes seconds to minutes, and a virion is a
hundred nanometres across while a cell is ten thousand. Nothing closes that
gap, so the sequence a person actually wants to look at cannot be integrated.

What can be done honestly is what the molecular-visualisation field does:
place real experimental structures at real scale, in the arrangement the
evidence supports, and say plainly which parts are measured and which are
posed. Every bead below comes from deposited coordinates. What varies between
stages is how much of the arrangement is known:

    measured      the coordinates are the experiment (6M0J, 6XR8, 6XRA, 7MEQ)
    simulated     the motion came out of the integrator (stage 2 only)
    posed         real structures, plausible placement, no structure of the
                  assembly exists
    interpolated  a path drawn between two measured endpoints; the endpoints
                  are real, the path is not

That distinction is carried per instance into the viewer and shown there. A
picture that cannot say which of its parts are evidence is a decoration.

Coarse-graining here is one bead per residue at the alpha carbon. That is a
coarser model than the Martini beads used for the simulated stage — deliberate,
because these stages are about arrangement at tens of nanometres rather than
about physics, and a whole virion at Martini resolution is tens of millions of
beads for no gain.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .structures import STRUCTURE_DIR, local_path

REPO_ROOT = Path(__file__).resolve().parents[2]
VIEWER_DIR = REPO_ROOT / "web" / "public" / "scene"

SCHEMA = "vervain.scene/1"
INT16_MAX = 32767

# One bead per residue at the alpha carbon, drawn at a radius that reads as a
# residue rather than an atom. Not a force-field parameter — nothing here is
# integrated — so it is a single number rather than a per-type table.
RESIDUE_RADIUS_NM = 0.40

# Lipid head beads stand in for a bilayer leaflet. Real phospholipid packing is
# about 0.64 nm^2 per lipid; this is deliberately coarser, because the membrane
# here is context rather than subject and a correctly packed 100 nm patch is
# two million beads.
MEMBRANE_SPACING_NM = 1.1
MEMBRANE_RADIUS_NM = 0.34

# SARS-CoV-2 virion, from cryo-electron tomography: roughly 90-100 nm across
# including the spike corona, with on the order of 25 spikes per virion.
VIRION_RADIUS_NM = 45.0
VIRION_SPIKE_COUNT = 24

PALETTE = {
    "viral membrane": "#8a6a4f",
    "spike S1": "#e0913c",
    "spike S2": "#f0c46a",
    "RBD": "#ff8f3c",
    "ACE2": "#5aa9d6",
    "host membrane": "#3d4c56",
    "TMPRSS2": "#9b7fd4",
}


@dataclass
class Instance:
    """One placed object: beads, what they are, and how well we know it."""

    role: str
    evidence: str
    source: str
    positions: np.ndarray  # (n, 3) nm
    radii: np.ndarray  # (n,) nm


@dataclass
class Stage:
    id: str
    title: str
    caption: str
    instances: list[Instance] = field(default_factory=list)
    # A morph stage carries several frames; a static one carries a single set.
    frames: np.ndarray | None = None


# --------------------------------------------------------------------------
# Reading structures
# --------------------------------------------------------------------------


def _read_ca(pdb_id: str, chains: set[str] | None = None) -> tuple[np.ndarray, list[int], list[str]]:
    """Alpha carbons of a deposited structure, in nanometres.

    Returns positions, residue numbers and chain names, so a caller can select
    a domain by numbering the way the literature does.
    """
    import gemmi

    path = local_path(pdb_id)
    if path is None:
        raise SystemExit(
            f"{pdb_id}: not downloaded. Run: python -m vervain.structures fetch {pdb_id}"
        )
    st = gemmi.read_structure(str(path))
    st.setup_entities()
    st.remove_alternative_conformations()

    xyz: list[tuple[float, float, float]] = []
    numbers: list[int] = []
    names: list[str] = []
    for chain in st[0]:
        if chains is not None and chain.name not in chains:
            continue
        for residue in chain:
            info = gemmi.find_tabulated_residue(residue.name)
            if info is None or not info.is_amino_acid():
                continue
            atom = residue.find_atom("CA", "*")
            if atom is None:
                continue
            xyz.append((atom.pos.x / 10.0, atom.pos.y / 10.0, atom.pos.z / 10.0))
            numbers.append(residue.seqid.num)
            names.append(chain.name)
    if not xyz:
        raise SystemExit(f"{pdb_id}: no alpha carbons found")
    return np.array(xyz, dtype=np.float64), numbers, names


# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------


def _principal_axis(points: np.ndarray) -> np.ndarray:
    centred = points - points.mean(axis=0)
    _, _, vt = np.linalg.svd(centred, full_matrices=False)
    return vt[0] / np.linalg.norm(vt[0])


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Rotation matrix taking unit vector a onto unit vector b."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        # Parallel, or antiparallel: a half turn about any perpendicular axis.
        if c > 0:
            return np.eye(3)
        perp = np.array([1.0, 0.0, 0.0])
        if abs(a[0]) > 0.9:
            perp = np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, perp)
        axis /= np.linalg.norm(axis)
        return -np.eye(3) + 2 * np.outer(axis, axis)
    kmat = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + kmat + kmat @ kmat * (1.0 / (1.0 + c))


def _orient_along(points: np.ndarray, base: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rotate so the object's base-to-tip axis points along `target`.

    `base` is a point at the membrane-proximal end. The spike is a lollipop and
    it matters which way up it goes; taking the axis alone would leave that a
    coin flip.
    """
    tip = points.mean(axis=0)
    axis = tip - base
    norm = np.linalg.norm(axis)
    if norm < 1e-9:
        return points
    rot = _rotation_between(axis / norm, target)
    return (points - base) @ rot.T


def _fibonacci_points(count: int) -> np.ndarray:
    """Near-uniform directions on a sphere. Spikes are not on a lattice."""
    out = np.empty((count, 3))
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(count):
        y = 1.0 - 2.0 * i / max(count - 1, 1)
        radius = math.sqrt(max(0.0, 1.0 - y * y))
        theta = golden * i
        out[i] = (math.cos(theta) * radius, y, math.sin(theta) * radius)
    return out


# The scene is built y-up, matching the renderer. Getting this wrong is not a
# subtle error but it is an invisible one in the numbers: a membrane built in
# the x-y plane is still a perfectly good membrane, it just stands up like a
# wall once something draws it with y as the vertical.
UP = np.array([0.0, 1.0, 0.0])


def _membrane_patch(width_nm: float, height_nm: float,
                    spacing: float = MEMBRANE_SPACING_NM,
                    hole_radius_nm: float = 0.0) -> np.ndarray:
    """A flat sheet of head beads, jittered so it does not read as graph paper."""
    steps = int(width_nm / spacing)
    coords = (np.arange(steps) - steps / 2.0) * spacing
    gx, gz = np.meshgrid(coords, coords)
    pts = np.stack([gx.ravel(), np.full(gx.size, height_nm), gz.ravel()], axis=1)
    rng = np.random.default_rng(0xA1CE2)
    pts[:, 0] += rng.normal(0.0, spacing * 0.14, size=len(pts))
    pts[:, 2] += rng.normal(0.0, spacing * 0.14, size=len(pts))
    pts[:, 1] += rng.normal(0.0, 0.12, size=len(pts))
    if hole_radius_nm > 0:
        keep = np.linalg.norm(pts[:, [0, 2]], axis=1) > hole_radius_nm
        pts = pts[keep]
    return pts


def _sphere_shell(radius_nm: float, spacing: float = MEMBRANE_SPACING_NM,
                  centre: np.ndarray | None = None) -> np.ndarray:
    """Head beads on a sphere — the virion envelope."""
    area = 4.0 * math.pi * radius_nm**2
    count = max(64, int(area / (spacing**2)))
    pts = _fibonacci_points(count) * radius_nm
    rng = np.random.default_rng(0xC0F1D)
    pts += rng.normal(0.0, 0.15, size=pts.shape)
    if centre is not None:
        pts = pts + centre
    return pts


def _lipid_instance(role: str, points: np.ndarray, source: str) -> Instance:
    return Instance(
        role=role,
        evidence="posed",
        source=source,
        positions=points,
        radii=np.full(len(points), MEMBRANE_RADIUS_NM),
    )


def _protein_instance(role: str, evidence: str, source: str, points: np.ndarray) -> Instance:
    return Instance(
        role=role,
        evidence=evidence,
        source=source,
        positions=points,
        radii=np.full(len(points), RESIDUE_RADIUS_NM),
    )


# --------------------------------------------------------------------------
# Domain boundaries, in the numbering the literature uses
# --------------------------------------------------------------------------

S1_RANGE = (14, 685)      # receptor-binding half, shed when fusion fires
S2_RANGE = (686, 1273)    # the fusion machine itself
RBD_RANGE = (333, 527)    # the part that actually touches ACE2


def _spike_beads(pdb_id: str = "6XR8") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Spike alpha carbons split into S1, RBD and S2, plus its base point.

    The base is the C-terminal end. In a full-length structure that is the
    membrane-proximal stalk, and it is what has to sit on the envelope; taking
    the principal axis alone would leave the spike as likely upside down as not.
    """
    xyz, numbers, _ = _read_ca(pdb_id)
    nums = np.array(numbers)
    rbd = (nums >= RBD_RANGE[0]) & (nums <= RBD_RANGE[1])
    s1 = (nums >= S1_RANGE[0]) & (nums <= S1_RANGE[1]) & ~rbd
    s2 = nums >= S2_RANGE[0]
    base = xyz[nums >= (nums.max() - 40)].mean(axis=0)
    return xyz, np.stack([s1, rbd, s2]), base


def stage_approach() -> Stage:
    """A virion at a cell surface, both at their measured sizes.

    The point of this stage is scale. A spike is about 18 nm, a virion about
    90 across, and the cell it is landing on roughly ten thousand. Only two of
    those three fit in one frame, which is itself the thing worth seeing.
    """
    xyz, masks, base = _spike_beads()
    spike_height = float(np.linalg.norm(xyz.mean(axis=0) - base)) * 2.0
    centre = UP * (VIRION_RADIUS_NM + spike_height + 2.0)

    instances = [
        _lipid_instance("host membrane", _membrane_patch(140.0, 0.0),
                        "posed: a flat patch of airway plasma membrane"),
        _lipid_instance("viral membrane", _sphere_shell(VIRION_RADIUS_NM, centre=centre),
                        "posed: envelope at the tomography-measured radius"),
    ]

    directions = _fibonacci_points(VIRION_SPIKE_COUNT)
    role_names = ["spike S1", "RBD", "spike S2"]
    placed: dict[str, list[np.ndarray]] = {name: [] for name in role_names}
    rng = np.random.default_rng(0x5B1CE)
    for direction in directions:
        # Spikes sit on flexible stalks and do not stand to attention.
        tilted = direction + rng.normal(0.0, 0.10, size=3)
        tilted /= np.linalg.norm(tilted)
        oriented = _orient_along(xyz, base, tilted)
        anchored = oriented + centre + direction * VIRION_RADIUS_NM
        for name, mask in zip(role_names, masks):
            placed[name].append(anchored[mask])

    for name in role_names:
        instances.append(_protein_instance(
            name, "measured",
            f"6XR8 alpha carbons, {VIRION_SPIKE_COUNT} copies posed on the envelope",
            np.concatenate(placed[name]),
        ))

    return Stage(
        id="approach",
        title="Approach",
        caption=(
            "A virion at an airway cell surface, both drawn at measured scale. "
            f"{VIRION_SPIKE_COUNT} spike trimers on a {VIRION_RADIUS_NM * 2:.0f} nm "
            "envelope. The cell below is about a hundred times wider than this "
            "entire frame. Every spike is real 6XR8 coordinates; their arrangement "
            "is posed, because no structure of an intact virion at a membrane "
            "exists."
        ),
        instances=instances,
    )


def stage_attachment() -> Stage:
    """One RBD on one ACE2 - the only stage whose motion is physics."""
    xyz, numbers, chains = _read_ca("6M0J")
    nums = np.array(numbers)
    names = np.array(chains)
    # Chain A is ACE2 and chain E the RBD, per the deposition.
    ace2 = names == "A"
    rbd = ~ace2

    # Stand the pair on a membrane with ACE2's C-terminus down. In life ACE2 is
    # anchored, and drawing it floating free is exactly the error this stage
    # exists to correct.
    anchor = xyz[ace2][nums[ace2] >= nums[ace2].max() - 20].mean(axis=0)
    pts = _orient_along(xyz, anchor, UP)
    pts[:, 1] += 0.5

    return Stage(
        id="attachment",
        title="Attachment",
        caption=(
            "The receptor-binding domain bound to ACE2, from the 2.45 A crystal "
            "structure. This is the one stage the simulation covers: coarse-grained "
            "molecular dynamics under Martini 3, plus a steered run that pulls the "
            "pair apart and measures the force. Its motion is integrated, not "
            "posed - the trajectory view has it."
        ),
        instances=[
            _lipid_instance("host membrane", _membrane_patch(26.0, 0.0),
                            "posed: ACE2 is membrane-anchored, the crystal is not"),
            _protein_instance("ACE2", "measured", "6M0J chain A", pts[ace2]),
            _protein_instance("RBD", "simulated", "6M0J chain E", pts[rbd]),
        ],
    )


def stage_priming() -> Stage:
    """TMPRSS2 cutting the spike. Real structures, invented arrangement."""
    xyz, masks, base = _spike_beads()
    spike = _orient_along(xyz, base, UP)
    spike[:, 1] += 0.5

    protease, _, _ = _read_ca("7MEQ")
    protease = protease - protease.mean(axis=0)
    # Beside the stalk, near where the S2-prime site sits. Nothing measures this.
    protease = protease + np.array([7.0, 4.5, 0.0])

    instances: list[Instance] = [
        _lipid_instance("host membrane", _membrane_patch(32.0, 0.0),
                        "posed: both proteins are membrane-anchored"),
    ]
    for name, mask in zip(["spike S1", "RBD", "spike S2"], masks):
        instances.append(_protein_instance(name, "measured", "6XR8", spike[mask]))
    instances.append(_protein_instance(
        "TMPRSS2", "posed", "7MEQ, placed by hand near the cleavage site", protease))

    return Stage(
        id="priming",
        title="Priming",
        caption=(
            "TMPRSS2, a host protease living in the same membrane, cuts the spike "
            "once it has engaged the receptor. That cut is what licenses fusion. "
            "Both proteins here are real structures, at 2.9 and 1.95 A. Their "
            "arrangement is not: no structure of TMPRSS2 bound to spike exists, so "
            "this placement is a hypothesis and should be read as one."
        ),
        instances=instances,
    )


def stage_fusion(frames: int = 40) -> Stage:
    """Prefusion to postfusion, interpolated between two measured endpoints.

    This is the largest motion in the whole process and the reason the virus
    gets in at all: S2 refolds into a long bundle and hauls the two membranes
    together. Both ends are experiments from a single study and a single
    construct. The path between them is drawn, not measured, and is labelled
    that way everywhere it appears.
    """
    pre_xyz, pre_nums, pre_chains = _read_ca("6XR8")
    post_xyz, post_nums, post_chains = _read_ca("6XRA")

    def keyed(xyz, nums, chains):
        index: dict[str, int] = {}
        for name in chains:
            index.setdefault(name, len(index))
        out: dict[tuple[int, int], np.ndarray] = {}
        for pos, num, name in zip(xyz, nums, chains):
            out.setdefault((index[name], num), pos)
        return out

    pre = keyed(pre_xyz, pre_nums, pre_chains)
    post = keyed(post_xyz, post_nums, post_chains)
    shared = sorted(set(pre) & set(post))
    if len(shared) < 100:
        raise SystemExit(
            f"only {len(shared)} residues are common to 6XR8 and 6XRA - the chain "
            "pairing must be wrong, so the morph would be meaningless"
        )

    start = np.array([pre[k] for k in shared])
    end = np.array([post[k] for k in shared])
    # Superpose, so the morph reads as a refold rather than as the whole
    # molecule sliding across the frame.
    start = start - start.mean(axis=0)
    end = end - end.mean(axis=0)
    u, _, vt = np.linalg.svd(end.T @ start)
    rot = u @ np.diag([1.0, 1.0, float(np.sign(np.linalg.det(u @ vt)))]) @ vt
    end = end @ rot.T

    # Stand the refold upright. The subject of this stage is that S2 gets
    # dramatically longer; shown lying at an angle it reads as a blob rotating.
    # Both endpoints get the same rotation, so the motion between them is
    # untouched — only the viewpoint is chosen.
    _, _, axes = np.linalg.svd(end - end.mean(axis=0), full_matrices=False)
    upright = _rotation_between(axes[0], UP)
    start = start @ upright.T
    end = end @ upright.T

    path = np.stack([start + (end - start) * (i / (frames - 1)) for i in range(frames)])
    travel = float(np.linalg.norm(end - start, axis=1).max())

    stage = Stage(
        id="fusion",
        title="Fusion",
        caption=(
            f"S2 refolding from prefusion (6XR8) to postfusion (6XRA). {len(shared)} "
            "residues are common to both structures and the furthest of them moves "
            f"{travel:.1f} nm. Both endpoints are measured; everything between them "
            "is a straight-line interpolation. Real proteins do not move this way, "
            "and no experiment has caught the intermediate. Note what is absent at "
            "the end: S1, the receptor-binding half, is shed when the machine "
            "fires, which is why the postfusion structure has a third as many "
            "residues as the prefusion one."
        ),
        instances=[_protein_instance(
            "spike S2", "interpolated", "6XR8 to 6XRA, linear", path[0])],
    )
    stage.frames = path
    return stage


STAGE_BUILDERS = {
    "approach": stage_approach,
    "attachment": stage_attachment,
    "priming": stage_priming,
    "fusion": stage_fusion,
}


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def _encode(stage: Stage, out_dir: Path) -> dict:
    """Quantise one stage to int16 and write its binary.

    Same scheme as the trajectory export: positions are scaled against the
    stage's own measured extent rather than a box, so nothing can clip.
    """
    positions = np.concatenate([i.positions for i in stage.instances])
    radii = np.concatenate([i.radii for i in stage.instances])

    if stage.frames is not None:
        # A morph replaces the last instance's beads frame by frame; every
        # other instance is static and repeats.
        static = [i.positions for i in stage.instances[:-1]]
        frames = np.stack([
            np.concatenate(static + [f]) if static else f
            for f in stage.frames
        ])
    else:
        frames = positions[None, :, :]

    # Midpoint of the bounding box over every frame, not the centroid of one.
    # A centroid is a vote, and in the approach stage the virion outvotes the
    # membrane seven to one — which aims the camera inside the virus and pushes
    # the cell surface out of frame, when the gap between them is the subject.
    # Taking it over all frames keeps a morph from drifting out of shot as it
    # moves.
    lo = frames.min(axis=(0, 1))
    hi = frames.max(axis=(0, 1))
    centre = (hi + lo) / 2.0
    frames = frames - centre

    extent = np.maximum(np.abs(frames).max(axis=(0, 1)) * 1.001, 1e-3)
    raw = np.clip(frames / extent * INT16_MAX, -INT16_MAX, INT16_MAX).astype(np.int16)

    name = f"{stage.id}.bin"
    (out_dir / name).write_bytes(raw.tobytes())

    groups = []
    offset = 0
    for instance in stage.instances:
        groups.append({
            "role": instance.role,
            "evidence": instance.evidence,
            "source": instance.source,
            "offset": offset,
            "beadCount": len(instance.positions),
            "color": PALETTE.get(instance.role, "#999999"),
        })
        offset += len(instance.positions)

    span = float(np.linalg.norm(frames.max(axis=(0, 1)) - frames.min(axis=(0, 1))))
    return {
        "id": stage.id,
        "title": stage.title,
        "caption": stage.caption,
        "positions": name,
        "beadCount": int(frames.shape[1]),
        "frameCount": int(frames.shape[0]),
        "extentNm": [float(v) for v in extent],
        "spanNm": round(span, 2),
        "radiusNm": [round(float(r), 3) for r in radii],
        "groups": groups,
    }


def build(stage_ids: list[str] | None = None) -> Path:
    """Build every stage and write the scene the viewer reads."""
    wanted = stage_ids or list(STAGE_BUILDERS)
    VIEWER_DIR.mkdir(parents=True, exist_ok=True)

    stages = []
    for stage_id in wanted:
        builder = STAGE_BUILDERS.get(stage_id)
        if builder is None:
            raise SystemExit(f"unknown stage: {stage_id}")
        stage = builder()
        entry = _encode(stage, VIEWER_DIR)
        stages.append(entry)
        evidence = sorted({g["evidence"] for g in entry["groups"]})
        print(f"  {stage.title:<12} {entry['beadCount']:>7} beads  "
              f"{entry['frameCount']:>3} frame(s)  {entry['spanNm']:>6.1f} nm  "
              f"[{', '.join(evidence)}]")

    manifest = {
        "schema": SCHEMA,
        "palette": PALETTE,
        "stages": stages,
    }
    path = VIEWER_DIR / "scene.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\n  {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vervain.scene", description=__doc__)
    parser.add_argument("stages", nargs="*", help="stages to build (default: all)")
    args = parser.parse_args(argv)
    build(args.stages or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
