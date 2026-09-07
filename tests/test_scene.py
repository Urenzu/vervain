"""Geometry tests for the staged view.

Every bug this file guards against rendered perfectly plausibly and raised no
error. A spike pointing into the virion instead of out of it, a membrane built
in the wrong plane so it stands up like a wall, a morph that superposes to a
translation rather than a refold — all of them produce a picture, and the
picture is the only place the mistake shows. So the geometry is measured here
rather than looked at.

These need the structures on disk. They skip rather than fail when they are
absent, because coordinates are gitignored and a fresh clone has none.
"""

from __future__ import annotations

import numpy as np
import pytest

from vervain import scene
from vervain.structures import local_path

NEEDED = ["6XR8", "6XRA", "6M0J", "7MEQ"]


@pytest.fixture(scope="module", autouse=True)
def structures_present():
    missing = [pdb_id for pdb_id in NEEDED if local_path(pdb_id) is None]
    if missing:
        pytest.skip(
            f"structures not downloaded: {', '.join(missing)}. "
            "Run: python -m vervain.structures fetch"
        )


def _roles(stage) -> dict[str, np.ndarray]:
    return {i.role: i.positions for i in stage.instances}


def test_spikes_point_outward():
    """The lollipop is the right way up.

    The base of the spike is its C-terminal stalk, which belongs in the
    envelope. Orienting on the principal axis alone leaves which end goes out
    a coin flip, and an inverted spike looks entirely convincing.
    """
    roles = _roles(scene.stage_approach())
    centre = roles["viral membrane"].mean(axis=0)

    def mean_radius(role: str) -> float:
        return float(np.linalg.norm(roles[role] - centre, axis=1).mean())

    # Tip to base: the receptor-binding domain is furthest out, the fusion
    # machine closest in, S1 between them.
    assert mean_radius("RBD") > mean_radius("spike S1") > mean_radius("spike S2")
    assert mean_radius("spike S2") > scene.VIRION_RADIUS_NM * 0.9

    # And nothing floats free of the envelope it is anchored to.
    tips = np.linalg.norm(roles["RBD"] - centre, axis=1)
    assert tips.max() < scene.VIRION_RADIUS_NM + 25.0


def test_scene_is_built_y_up():
    """Membranes lie flat.

    Three.js takes y as up. A membrane built in the x-y plane is a perfectly
    good membrane by every measurement except the one that matters: drawn, it
    stands up like a wall. The flat axis has to be the vertical one.
    """
    for stage in (scene.stage_approach(), scene.stage_attachment(), scene.stage_priming()):
        membrane = _roles(stage)["host membrane"]
        spread = membrane.max(axis=0) - membrane.min(axis=0)
        thinnest = int(np.argmin(spread))
        assert thinnest == 1, (
            f"{stage.id}: membrane is thin along axis {thinnest}, not y — "
            "it will render as a wall"
        )


def test_virion_sits_above_the_cell_surface():
    roles = _roles(scene.stage_approach())
    host = roles["host membrane"][:, 1].mean()
    envelope = roles["viral membrane"][:, 1]
    assert envelope.min() > host, "the virion has sunk through the membrane"


def test_ace2_stands_on_the_membrane_with_the_rbd_on_top():
    """ACE2 is anchored; the RBD arrives from above, not from underneath."""
    roles = _roles(scene.stage_attachment())
    ace2, rbd = roles["ACE2"][:, 1], roles["RBD"][:, 1]
    assert ace2.min() < 1.0, "ACE2 is floating above its own membrane"
    assert rbd.mean() > ace2.mean(), "the RBD is below ACE2"


def test_fusion_morph_elongates():
    """The refold gets longer, which is the entire point of the stage.

    Superposing the endpoints badly gives a morph that translates or spins
    instead. Aspect ratio is what separates the two, and it has to climb.
    """
    stage = scene.stage_fusion(frames=6)
    assert stage.frames is not None

    def aspect(points: np.ndarray) -> float:
        centred = points - points.mean(axis=0)
        _, _, axes = np.linalg.svd(centred, full_matrices=False)
        projected = centred @ axes.T
        # np.ptp, not ndarray.ptp: the method was removed in NumPy 2.0.
        length = np.ptp(projected[:, 0])
        width = np.ptp(projected[:, 1])
        return float(length / width)

    first, last = aspect(stage.frames[0]), aspect(stage.frames[-1])
    assert last > first * 1.3, f"morph did not elongate: {first:.2f} -> {last:.2f}"

    # The endpoints must be the deposited coordinates, not something smoothed
    # towards each other: the last frame is postfusion exactly.
    travel = np.linalg.norm(stage.frames[-1] - stage.frames[0], axis=1)
    assert travel.max() > 8.0, "the largest conformational change in entry barely moved"


def test_every_group_declares_its_evidence():
    """The labelling is the load-bearing part, so it is not optional."""
    valid = {"measured", "simulated", "posed", "interpolated"}
    for build in (scene.stage_approach, scene.stage_attachment,
                  scene.stage_priming, scene.stage_fusion):
        stage = build()
        assert stage.instances, f"{stage.id} has no content"
        for instance in stage.instances:
            assert instance.evidence in valid, f"{stage.id}/{instance.role}"
            assert instance.source.strip(), (
                f"{stage.id}/{instance.role} claims no source"
            )


def test_posed_placements_are_declared_posed():
    """Nothing invented is allowed to claim it was measured.

    The membranes are drawn, not observed, in every stage. TMPRSS2's position
    beside the spike is a hypothesis. If either ever gets relabelled
    'measured', this is the test that should stop it.
    """
    for build in (scene.stage_approach, scene.stage_attachment, scene.stage_priming):
        stage = build()
        for instance in stage.instances:
            if "membrane" in instance.role:
                assert instance.evidence == "posed", (
                    f"{stage.id}: {instance.role} is drawn, not observed"
                )

    priming = {i.role: i.evidence for i in scene.stage_priming().instances}
    assert priming["TMPRSS2"] == "posed"
