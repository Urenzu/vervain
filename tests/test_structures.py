"""The catalogue is the tracked artefact, so it is what gets tested.

Coordinates are gitignored and reproducible; the claims made *about* them are
not. These tests guard the provenance rule the old kinetic model enforced on
parameters: nothing enters the pipeline without a source and a confidence.
"""

from __future__ import annotations

import pytest

from vervain.structures import CRYSTALLISATION_JUNK, GLYCANS, inspect, read_catalogue, structure_path

REQUIRED_FIELDS = {"name", "method", "confidence", "source", "doi"}
VALID_CONFIDENCE = {"direct", "construct", "analogous"}


@pytest.fixture(scope="module")
def catalogue() -> dict[str, dict[str, str]]:
    entries = read_catalogue()
    assert entries, "structures.yaml parsed to nothing"
    return entries


def test_every_structure_carries_provenance(catalogue):
    for pdb_id, body in catalogue.items():
        missing = REQUIRED_FIELDS - body.keys()
        assert not missing, f"{pdb_id} is missing {sorted(missing)}"


def test_confidence_is_a_known_level(catalogue):
    for pdb_id, body in catalogue.items():
        assert body["confidence"] in VALID_CONFIDENCE, (
            f"{pdb_id} has confidence {body['confidence']!r}, "
            f"expected one of {sorted(VALID_CONFIDENCE)}"
        )


def test_pdb_ids_are_well_formed(catalogue):
    for pdb_id in catalogue:
        assert len(pdb_id) == 4 and pdb_id.isalnum() and pdb_id.isupper(), (
            f"{pdb_id!r} is not a four-character uppercase PDB id"
        )


def test_glycans_and_junk_do_not_overlap():
    # A residue counted as both shield and solvent would be silently dropped
    # from the glycan report, which is the number that decides whether the
    # shield has to be rebuilt.
    assert not (GLYCANS & CRYSTALLISATION_JUNK)


@pytest.mark.skipif(
    not structure_path("6M0J").exists(),
    reason="6M0J not downloaded; run make structures",
)
def test_inspect_finds_the_intact_rbd():
    """6M0J is the graft donor precisely because its RBD has no gaps.

    If a re-deposition ever changed that, every downstream assumption about
    repairing 6VXX's binding interface would be wrong, so it is asserted rather
    than assumed.
    """
    report = inspect("6M0J")
    chains = {c.chain_id: c for c in report.chains}
    assert "E" in chains, "expected chain E to carry the RBD"

    rbd = chains["E"]
    assert rbd.gaps == [], f"6M0J RBD has gaps at {rbd.gaps}; it is no longer a clean donor"
    assert rbd.first_seq is not None and rbd.last_seq is not None
    # The receptor-binding domain, and the region 6VXX leaves unresolved.
    assert rbd.first_seq <= 340 and rbd.last_seq >= 520
