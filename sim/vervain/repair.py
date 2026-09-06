"""Repair unresolved regions in the spike before it enters the pipeline.

6VXX is a 2.8 A cryo-EM trimer with eleven unresolved stretches per chain, and
four of them sit inside the receptor-binding domain: 445-446, 455-461, 469-488,
502. Those are ACE2 contact residues. Coarse-graining that deposition directly
would produce a binding interface with holes in it, and MARTINI's elastic
network would then hold the holes in place for the whole trajectory.

6M0J is a 2.45 A crystal structure of the isolated RBD bound to ACE2, and its
RBD (333-526) is complete. So the RBD is not modelled, it is transplanted: the
donor is superposed onto each chain's RBD using the backbone atoms the two
share, then swapped in.

What this does not fix: the NTD loops (144-164, 173-185, 246-262) and the
fusion-peptide proximal region (828-853). Those have no clean donor and need
loop modelling. They are reported, not silently left.

    python -m vervain.repair rbd
    python -m vervain.repair rbd --acceptor 6VXX --donor 6M0J
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from vervain.structures import REPO_ROOT, structure_path

PREPARED_DIR = REPO_ROOT / "data" / "prepared"

# The receptor-binding domain. Boundaries vary by a few residues between
# papers; this span covers the ACE2 interface and the RBD core without
# reaching into the neighbouring subdomains.
RBD_START, RBD_END = 333, 527

# Superposition uses backbone only. Side chains differ between the free and
# ACE2-bound states, and including them would bias the fit toward the donor's
# bound conformation rather than aligning the two RBD cores.
BACKBONE = ("N", "CA", "C", "O")

# Above this the two RBDs are not the same rigid body and the graft is not
# justified. The RBD core is rigid across free and bound states, so a clean
# transplant lands well under 1 A.
MAX_RMSD_A = 1.5


@dataclass
class GraftResult:
    chain_id: str
    rmsd: float
    matched_atoms: int
    residues_removed: int
    residues_added: int
    gaps_closed: list[tuple[int, int]]
    graft_window: tuple[int, int]
    seam_bond_a: float | None


def _require_gemmi():
    try:
        import gemmi
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        raise SystemExit(
            "repair needs gemmi. Run: bash scripts/setup-env.sh"
        ) from exc
    return gemmi


def _load(pdb_id: str):
    gemmi = _require_gemmi()
    path = structure_path(pdb_id)
    if not path.exists():
        raise SystemExit(
            f"{pdb_id}: not downloaded. Run: python -m vervain.structures fetch {pdb_id}"
        )
    structure = gemmi.read_structure(str(path))
    structure.setup_entities()
    return structure


def _polymer_chains(model) -> list:
    """Chains with a real polymer, ignoring pure-ligand and water chains."""
    return [ch for ch in model if len(ch.get_polymer()) > 20]


def _gaps(chain, lo: int, hi: int) -> list[tuple[int, int]]:
    seen = sorted(
        r.seqid.num for r in chain
        if r.name != "HOH" and lo <= r.seqid.num <= hi
    )
    out = []
    for a, b in zip(seen, seen[1:]):
        if b > a + 1:
            out.append((a + 1, b - 1))
    return out


def _seam_length(gemmi, chain, first_grafted: int) -> float | None:
    """C-N distance across the N-terminal splice point.

    A transplanted domain lands in the acceptor's frame to within the
    superposition RMSD, which leaves the peptide bond at the seam stretched.
    Around 1.33 A is a real bond; anything beyond that is strain that energy
    minimisation has to relax before coarse-graining freezes it into an
    elastic network.
    """
    by_num = {r.seqid.num: r for r in chain if r.name != "HOH"}
    before = by_num.get(first_grafted - 1)
    after = by_num.get(first_grafted)
    if before is None or after is None:
        return None
    c_atom = before.find_atom("C", "*")
    n_atom = after.find_atom("N", "*")
    if c_atom is None or n_atom is None:
        return None
    return c_atom.pos.dist(n_atom.pos)


def _clone(gemmi, residue, transform=None):
    """A detached copy of a residue, optionally moved by a transform.

    Detached matters: the originals are about to be deleted out from under us
    when the chain is rebuilt, and gemmi hands out references into the parent
    structure rather than values.
    """
    copy = gemmi.Residue()
    copy.name = residue.name
    copy.seqid = residue.seqid
    copy.het_flag = residue.het_flag
    for atom in residue:
        moved = gemmi.Atom()
        moved.name = atom.name
        moved.element = atom.element
        moved.altloc = atom.altloc
        moved.occ = atom.occ
        moved.b_iso = atom.b_iso
        moved.pos = (
            gemmi.Position(*transform.apply(atom.pos).tolist())
            if transform is not None
            else gemmi.Position(atom.pos.x, atom.pos.y, atom.pos.z)
        )
        copy.add_atom(moved)
    return copy


def _rbd_donor_chain(donor, reference):
    """The donor chain carrying the RBD, chosen by sequence agreement.

    Numbering overlap is not enough to identify it, and the failure is not
    hypothetical: 6M0J holds ACE2 in chain A spanning residues 19-615, which
    numerically *contains* the RBD's 333-527. Scored on span coverage alone
    ACE2 wins, and the pipeline cheerfully grafts the receptor onto the spike.

    So candidates are scored on how often their residue at position N has the
    same name as the acceptor's residue at position N. The real RBD scores near
    1.0; an unrelated chain that merely overlaps in numbering scores near the
    ~5% you would expect from twenty amino acids at random.
    """
    reference_names = {
        r.seqid.num: r.name for r in reference
        if r.name != "HOH" and RBD_START <= r.seqid.num <= RBD_END
    }
    if not reference_names:
        raise SystemExit(
            f"acceptor chain {reference.name} has no residues in {RBD_START}-{RBD_END}"
        )

    best = None
    for chain in _polymer_chains(donor[0]):
        overlap = agree = 0
        for residue in chain:
            expected = reference_names.get(residue.seqid.num)
            if expected is None:
                continue
            overlap += 1
            if residue.name == expected:
                agree += 1
        if overlap < 50:
            continue
        identity = agree / overlap
        if best is None or identity > best[1]:
            best = (chain, identity, overlap)

    if best is None or best[1] < 0.7:
        found = f"best identity {best[1]:.0%} on chain {best[0].name}" if best else "no candidate"
        raise SystemExit(
            f"No donor chain matches the acceptor's sequence over {RBD_START}-{RBD_END} "
            f"({found}). The donor is not the domain the catalogue claims."
        )
    return best[0]


def graft_rbd(acceptor_id: str = "6VXX", donor_id: str = "6M0J") -> tuple[Path, list[GraftResult]]:
    gemmi = _require_gemmi()

    acceptor = _load(acceptor_id)
    donor = _load(donor_id)
    # Identified against a real acceptor chain, so the choice is checked
    # against the sequence we intend to replace rather than against a range.
    donor_chain = _rbd_donor_chain(donor, _polymer_chains(acceptor[0])[0])

    donor_by_num = {
        r.seqid.num: r for r in donor_chain
        if r.name != "HOH" and RBD_START <= r.seqid.num <= RBD_END
    }
    if not donor_by_num:
        raise SystemExit(f"{donor_id}: donor chain has nothing in {RBD_START}-{RBD_END}")

    # The window is what the donor can actually replace, not the nominal RBD
    # span. 6M0J stops at 526 while RBD_END is 527, and removing a residue the
    # donor cannot supply leaves a one-residue hole exactly on the boundary --
    # where a naive gap check does not see it.
    graft_lo, graft_hi = min(donor_by_num), max(donor_by_num)

    results: list[GraftResult] = []

    for chain in _polymer_chains(acceptor[0]):
        before = _gaps(chain, RBD_START, RBD_END)

        # Match on residues present in both, by number, and only where the
        # residue name agrees — a mismatch means the numbering does not line up
        # and the graft would splice the wrong sequence in.
        fixed_pos, moving_pos = [], []
        for residue in chain:
            donor_residue = donor_by_num.get(residue.seqid.num)
            if donor_residue is None or donor_residue.name != residue.name:
                continue
            for atom_name in BACKBONE:
                a = residue.find_atom(atom_name, "*")
                b = donor_residue.find_atom(atom_name, "*")
                if a is not None and b is not None:
                    fixed_pos.append(a.pos)
                    moving_pos.append(b.pos)

        if len(fixed_pos) < 40:
            raise SystemExit(
                f"chain {chain.name}: only {len(fixed_pos)} matched backbone atoms — "
                "too few to superpose. Numbering probably does not correspond."
            )

        sup = gemmi.superpose_positions(fixed_pos, moving_pos)
        if sup.rmsd > MAX_RMSD_A:
            raise SystemExit(
                f"chain {chain.name}: superposition RMSD {sup.rmsd:.2f} A exceeds "
                f"{MAX_RMSD_A} A. The two RBDs are not the same rigid body here, so "
                "the transplant is not justified — model the loops instead."
            )

        # Rebuild the chain rather than mutating it in place. gemmi has no
        # sort_residues, and deleting while appending leaves the residue order
        # scrambled — which a PDB writer will happily emit and every downstream
        # tool will then misread as chain breaks.
        merged = []
        removed = 0
        for residue in chain:
            if residue.name != "HOH" and graft_lo <= residue.seqid.num <= graft_hi:
                removed += 1
                continue
            merged.append(_clone(gemmi, residue))

        # Insert the donor's RBD, moved onto the acceptor's frame. Protein only:
        # the donor's few resolved glycans are not the shield we need, and the
        # shield gets built properly later.
        added = 0
        for num in sorted(donor_by_num):
            source = donor_by_num[num]
            # gemmi.Residue has no is_amino_acid(); the residue table does.
            info = gemmi.find_tabulated_residue(source.name)
            if info is None or not info.is_amino_acid():
                continue
            merged.append(_clone(gemmi, source, transform=sup.transform))
            added += 1

        merged.sort(key=lambda r: (r.seqid.num, r.seqid.icode))

        present_before = {
            r.seqid.num for r in chain if r.name != "HOH"
        }

        while len(chain):
            del chain[len(chain) - 1]
        for residue in merged:
            chain.add_residue(residue)

        # A graft must not lose residues. This is not paranoia: an earlier
        # version removed 333-527 while inserting 333-526 and dropped residue
        # 527 in silence, because the hole sat on the window boundary where the
        # gap check could not see it.
        lost = present_before - {r.seqid.num for r in chain if r.name != "HOH"}
        if lost:
            raise SystemExit(
                f"chain {chain.name}: graft lost residues {sorted(lost)}. "
                "The removal window and the donor's coverage disagree."
            )

        seam = _seam_length(gemmi, chain, graft_lo)

        results.append(GraftResult(
            chain_id=chain.name,
            rmsd=sup.rmsd,
            matched_atoms=len(fixed_pos),
            residues_removed=removed,
            residues_added=added,
            gaps_closed=before,
            graft_window=(graft_lo, graft_hi),
            seam_bond_a=seam,
        ))

    acceptor.setup_entities()
    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PREPARED_DIR / f"{acceptor_id}_rbd-from-{donor_id}.pdb"
    acceptor.write_pdb(str(out_path))
    return out_path, results


def _cmd_rbd(acceptor: str, donor: str) -> int:
    out_path, results = graft_rbd(acceptor, donor)

    window = results[0].graft_window if results else (RBD_START, RBD_END)
    print(f"grafted {donor} RBD {window[0]}-{window[1]} onto {acceptor}\n")
    print(f"  {'chain':<7}{'rmsd A':>8}{'atoms':>8}{'removed':>9}{'added':>7}"
          f"{'gaps closed':>13}{'seam A':>9}")
    for r in results:
        seam = f"{r.seam_bond_a:.2f}" if r.seam_bond_a is not None else '-'
        print(f"  {r.chain_id:<7}{r.rmsd:>8.3f}{r.matched_atoms:>8}"
              f"{r.residues_removed:>9}{r.residues_added:>7}"
              f"{len(r.gaps_closed):>13}{seam:>9}")

    strained = [r for r in results if r.seam_bond_a and r.seam_bond_a > 1.6]
    if strained:
        print()
        print(f"  The splice leaves the peptide bond at residue {window[0]} stretched"
              f" (~{strained[0].seam_bond_a:.2f} A against 1.33 A nominal).")
        print("  Energy-minimise before coarse-graining, or MARTINI's elastic network")
        print("  will hold that strain for the whole trajectory.")
    print(f"\n  written: {out_path}")

    # What is still broken. Reporting this is the point — a repair step that
    # quietly leaves holes elsewhere is worse than no repair step.
    from vervain.structures import inspect
    remaining = inspect(acceptor)
    outside = [
        (c.chain_id, gap)
        for c in remaining.chains
        for gap in c.gaps
        if not (RBD_START <= gap[0] <= RBD_END)
    ]
    per_chain = len(outside) // max(1, len(results))
    print(f"\n  still unresolved outside the RBD: ~{per_chain} stretches per chain")
    seen: set[tuple[int, int]] = set()
    for _, (a, b) in outside:
        if (a, b) not in seen:
            seen.add((a, b))
            print(f"    {a + 1}-{b - 1}  ({b - a - 1} residues)")
    print("\n  These need loop modelling; there is no clean donor for them.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vervain.repair", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_rbd = sub.add_parser("rbd", help="transplant a complete RBD into the trimer")
    p_rbd.add_argument("--acceptor", default="6VXX")
    p_rbd.add_argument("--donor", default="6M0J")

    args = parser.parse_args(argv)
    return _cmd_rbd(args.acceptor, args.donor)


if __name__ == "__main__":
    raise SystemExit(main())
