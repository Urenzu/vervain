"""Regression tests for the RBD transplant.

Both of the cases below are bugs that actually shipped into a run, not
hypotheticals. They are cheap to assert and expensive to notice: neither
produced an error, and both would have propagated silently into a coarse-
grained model where MARTINI's elastic network freezes whatever it is given.
"""

from __future__ import annotations

import pytest

from vervain.structures import structure_path

gemmi = pytest.importorskip("gemmi", reason="repair needs gemmi; run scripts/setup-env.sh")

from vervain.repair import (  # noqa: E402 - import after the gemmi guard
    RBD_END,
    RBD_START,
    _polymer_chains,
    _rbd_donor_chain,
    _seam_length,
    graft_rbd,
)

HAVE_STRUCTURES = structure_path("6VXX").exists() and structure_path("6M0J").exists()
needs_structures = pytest.mark.skipif(
    not HAVE_STRUCTURES, reason="run: make structures"
)


@pytest.fixture(scope="module")
def grafted():
    path, results = graft_rbd("6VXX", "6M0J")
    structure = gemmi.read_structure(str(path))
    structure.setup_entities()
    return structure, results


@needs_structures
def test_donor_selection_is_not_fooled_by_numbering_overlap():
    """ACE2 spans 19-615, which numerically contains the RBD's 333-527.

    Selecting the donor chain on span coverage alone picks ACE2 over the RBD --
    it scores marginally higher because it covers the whole window. The
    selector must score on sequence agreement with the acceptor instead.
    """
    donor = gemmi.read_structure(str(structure_path("6M0J")))
    donor.setup_entities()
    acceptor = gemmi.read_structure(str(structure_path("6VXX")))
    acceptor.setup_entities()

    reference = _polymer_chains(acceptor[0])[0]
    chosen = _rbd_donor_chain(donor, reference)

    # Chain E is the RBD; chain A is ACE2. Assert on content, not on the letter.
    # Amino acids only: the chain also carries N-linked NAG numbered in the
    # 600s, which is glycan, not sequence, and would look like overrun.
    nums = [
        r.seqid.num for r in chosen
        if (info := gemmi.find_tabulated_residue(r.name)) and info.is_amino_acid()
    ]
    assert min(nums) >= RBD_START - 5, "donor starts well before the RBD; this is not the RBD"
    assert max(nums) <= RBD_END + 5, "donor runs well past the RBD; this looks like ACE2"


@needs_structures
def test_graft_loses_no_residues(grafted):
    """The removal window must match what the donor can supply.

    Removing 333-527 while inserting 333-526 dropped residue 527 in silence:
    the hole sat exactly on the window boundary, where a gap scan between
    consecutive present residues cannot see it.
    """
    structure, _ = grafted
    original = gemmi.read_structure(str(structure_path("6VXX")))
    original.setup_entities()

    for before, after in zip(_polymer_chains(original[0]), _polymer_chains(structure[0])):
        lost = (
            {r.seqid.num for r in before if r.name != "HOH"}
            - {r.seqid.num for r in after if r.name != "HOH"}
        )
        assert not lost, f"chain {before.name}: lost residues {sorted(lost)}"


@needs_structures
def test_rbd_has_no_gaps_after_grafting(grafted):
    structure, _ = grafted
    for chain in _polymer_chains(structure[0]):
        nums = sorted(
            r.seqid.num for r in chain
            if r.name != "HOH" and RBD_START <= r.seqid.num <= RBD_END
        )
        gaps = [(a + 1, b - 1) for a, b in zip(nums, nums[1:]) if b > a + 1]
        assert not gaps, f"chain {chain.name}: RBD still has gaps at {gaps}"


@needs_structures
def test_superposition_is_tight(grafted):
    """The RBD core is rigid between the free and ACE2-bound states.

    A drifting RMSD means the two are no longer the same rigid body and the
    transplant has stopped being justified.
    """
    _, results = grafted
    assert results, "no chains were grafted"
    for r in results:
        assert r.rmsd < 1.2, f"chain {r.chain_id}: superposition RMSD {r.rmsd:.2f} A"


@needs_structures
def test_seam_strain_is_reported_not_hidden(grafted):
    """The splice leaves a stretched peptide bond, and that is expected.

    What must not happen is it going unreported -- coarse-graining would freeze
    the strain into the elastic network. The bond is stretched but must stay
    within reach of energy minimisation.
    """
    structure, results = grafted
    for r in results:
        assert r.seam_bond_a is not None, f"chain {r.chain_id}: seam not measured"
        assert 1.3 <= r.seam_bond_a < 3.0, (
            f"chain {r.chain_id}: seam bond {r.seam_bond_a:.2f} A is beyond what "
            "minimisation will pull back"
        )

    for chain in _polymer_chains(structure[0]):
        assert _seam_length(gemmi, chain, results[0].graft_window[0]) is not None


@needs_structures
def test_graft_window_comes_from_the_donor(grafted):
    _, results = grafted
    donor = gemmi.read_structure(str(structure_path("6M0J")))
    donor.setup_entities()
    acceptor = gemmi.read_structure(str(structure_path("6VXX")))
    acceptor.setup_entities()
    chain = _rbd_donor_chain(donor, _polymer_chains(acceptor[0])[0])

    covered = [
        r.seqid.num for r in chain
        if r.name != "HOH" and RBD_START <= r.seqid.num <= RBD_END
    ]
    assert results[0].graft_window == (min(covered), max(covered))
