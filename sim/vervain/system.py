"""Build a coarse-grained, solvated, neutralised system ready for GROMACS.

The first target is the RBD bound to the ACE2 peptidase domain, from 6M0J. It
is the cheapest system that still contains the thing the project exists to
study: the actual receptor interface. It needs no stalk, no glycan shield and
no membrane, all of which are unresolved problems — and at roughly four
thousand beads it exercises the whole chain in hours rather than weeks.

    python -m vervain.system build --pdb 6M0J --chains A,E --name rbd-ace2

Stages, each idempotent and each leaving its output on disk:

    prepare    strip to protein, chosen chains only
    martinize  atomistic -> Martini 3, with an elastic network
    box        centre in a dodecahedron with a solvent margin
    solvate    fill with coarse-grained water
    ions       neutralise and bring to physiological salt
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from vervain import dssp, forcefield
from vervain.structures import REPO_ROOT, structure_path

SYSTEMS_DIR = REPO_ROOT / "data" / "systems"
MDP_DIR = Path(__file__).with_name("mdp")

# Martini water: 1 bead per 4 molecules, so 33.4 waters/nm^3 becomes 8.35
# beads/nm^3. Solvation only needs to land near this — the NPT step fixes the
# density properly, and starting too dense is worse than starting too sparse.
WATER_BEADS_PER_NM3 = 8.35

# gmx solvate's default vdW radius is tuned for atomistic water and packs
# Martini beads far too tightly.
CG_SOLVATE_RADIUS = 0.21

SALT_MOLAR = 0.15


@dataclass
class Stage:
    name: str
    path: Path


def gmx_binary() -> str:
    explicit = os.environ.get("VERVAIN_GMX")
    if explicit:
        return explicit
    built = Path.home() / "opt" / "gromacs" / "bin" / "gmx"
    if built.exists():
        return str(built)
    found = shutil.which("gmx")
    if not found:
        raise SystemExit("gmx not found. Run: make gromacs")
    return found


def _run(cmd: list[str], cwd: Path, stdin: str | None = None) -> str:
    """Run a command, and on failure show the output rather than a return code.

    GROMACS reports the actual problem in its own words and then exits; hiding
    that behind CalledProcessError turns a two-minute fix into an afternoon.
    """
    proc = subprocess.run(
        cmd, cwd=cwd, input=stdin, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stdout or "") + (proc.stderr or "")
        raise SystemExit(
            f"command failed: {' '.join(cmd[:3])} ...\n"
            f"  in {cwd}\n\n{tail[-3000:]}"
        )
    return (proc.stdout or "") + (proc.stderr or "")


def write_water_box(path: Path, edge_nm: float = 6.0) -> int:
    """A box of Martini W beads for gmx solvate to replicate.

    Generated rather than downloaded. Martini's own water.gro is one more
    versioned input to track, and a jittered lattice at the right density is
    equivalent once minimisation and NPT have run — solvate only needs
    something with the right number of beads per unit volume.
    """
    import numpy as np

    spacing = WATER_BEADS_PER_NM3 ** (-1 / 3)
    n = int(edge_nm / spacing)
    rng = np.random.default_rng(20240501)

    lines = ["Martini coarse-grained water (generated)", ""]
    count = 0
    body: list[str] = []
    for i in range(n):
        for j in range(n):
            for k in range(n):
                # A little jitter so the starting configuration is not a
                # crystal; minimisation converges faster from disorder.
                pos = (np.array([i, j, k]) + 0.5) * spacing + rng.normal(0, 0.04, 3)
                count += 1
                body.append(
                    f"{count % 100000:>5}{'W':<5}{'W':>5}{count % 100000:>5}"
                    f"{pos[0]:8.3f}{pos[1]:8.3f}{pos[2]:8.3f}"
                )
    lines[1] = f"{count:>5}"
    lines.extend(body)
    lines.append(f"{n * spacing:10.5f}{n * spacing:10.5f}{n * spacing:10.5f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def prepare(pdb_id: str, chains: list[str], work: Path) -> Path:
    """Strip to the protein of the requested chains.

    Everything else goes: waters, crystallisation additives, and the resolved
    glycans. The glycans are not the shield — 6M0J resolves five sugar residues
    — and carrying a fragment of a shield is worse than carrying none, because
    it looks like coverage.

    The catalytic zinc in ACE2 goes too. Martini has no model for metal
    coordination, so keeping it would place an unparameterised ion in a site
    whose geometry the force field cannot hold.
    """
    import gemmi

    source = structure_path(pdb_id)
    if not source.exists():
        raise SystemExit(f"{pdb_id} not downloaded. Run: make structures")

    structure = gemmi.read_structure(str(source))
    structure.setup_entities()
    structure.remove_alternative_conformations()
    structure.remove_hydrogens()

    wanted = set(chains)
    model = structure[0]
    for chain_name in [ch.name for ch in model]:
        if chain_name not in wanted:
            model.remove_chain(chain_name)

    for chain in model:
        for i in range(len(chain) - 1, -1, -1):
            info = gemmi.find_tabulated_residue(chain[i].name)
            if info is None or not info.is_amino_acid():
                del chain[i]

    structure.setup_entities()
    out = work / "prepared.pdb"
    structure.write_pdb(str(out))

    kept = {ch.name: len(ch) for ch in structure[0]}
    print(f"  prepared   chains {kept}")
    return out


def martinize(prepared: Path, work: Path) -> Path:
    """Atomistic to Martini 3, with an elastic network holding the fold.

    The elastic network is what makes this a rigid-domain simulation rather
    than a folding one. Martini cannot fold a protein, and without the network
    the tertiary structure drifts apart within nanoseconds. The consequence
    worth remembering: any conformational change the network forbids will not
    happen, no matter how long the run.
    """
    cg = work / "cg.pdb"
    top = work / "topol.top"

    martinize2 = shutil.which("martinize2") or str(
        REPO_ROOT / ".venv-wsl" / "bin" / "martinize2"
    )

    # Assigned here rather than by vermouth's own -dssp, which calls mkdssp
    # with flags that version 4 no longer accepts. See vervain.dssp.
    ss = dssp.secondary_structure(prepared)
    print(f"  dssp       {len(ss)} residues   {dssp.summarise(ss)}")

    _run([
        martinize2,
        "-f", str(prepared),
        "-o", str(top),
        "-x", str(cg),
        "-ff", "martini3001",
        "-ss", ss,
        "-elastic",
        "-ef", "700.0",     # elastic force constant, kJ/mol/nm^2
        "-el", "0.5",       # lower cutoff, nm
        "-eu", "0.9",       # upper cutoff, nm
        "-p", "backbone",   # position restraints on backbone, for equilibration
        "-maxwarn", "10",
    ], cwd=work)

    print(f"  martinize  {cg.name}")
    return cg


def _rewrite_topology(work: Path) -> None:
    """Point the topology at our pinned force-field files.

    martinize2 emits `#include "martini.itp"`, which resolves to whatever is
    lying around. Replacing it with explicit relative paths into
    data/forcefield means the physics is the version we recorded.
    """
    top = work / "topol.top"
    text = top.read_text(encoding="utf-8")

    ff = os.path.relpath(forcefield.FORCEFIELD_DIR, work)
    includes = "\n".join(
        f'#include "{ff}/{name}"' for name in forcefield.FILES
        if "phospholipids" not in name
    )

    lines = []
    replaced = False
    for line in text.splitlines():
        if line.strip().startswith("#include") and "martini" in line and not replaced:
            lines.append(includes)
            replaced = True
            continue
        if line.strip().startswith("#include") and "martini" in line:
            continue
        lines.append(line)
    if not replaced:
        lines.insert(0, includes)

    top.write_text("\n".join(lines) + "\n", encoding="utf-8")


def solvate(cg: Path, work: Path, margin_nm: float = 1.2) -> Path:
    gmx = gmx_binary()

    boxed = work / "box.gro"
    _run([gmx, "editconf", "-f", str(cg), "-o", str(boxed),
          "-d", str(margin_nm), "-bt", "dodecahedron"], cwd=work)

    water = work / "water.gro"
    beads = write_water_box(water)
    print(f"  waterbox   {beads} beads at {WATER_BEADS_PER_NM3}/nm^3")

    solvated = work / "solvated.gro"
    out = _run([gmx, "solvate", "-cp", str(boxed), "-cs", str(water),
                "-o", str(solvated), "-p", "topol.top",
                "-radius", str(CG_SOLVATE_RADIUS)], cwd=work)
    for line in out.splitlines():
        if "Number of solvent molecules" in line:
            print(f"  solvate    {line.split(':')[-1].strip()} water beads")
    return solvated


def add_ions(solvated: Path, work: Path) -> Path:
    gmx = gmx_binary()

    tpr = work / "ions.tpr"
    _run([gmx, "grompp", "-f", str(MDP_DIR / "ions.mdp"), "-c", str(solvated),
          "-p", "topol.top", "-o", str(tpr), "-maxwarn", "5"], cwd=work)

    ionised = work / "system.gro"
    # Martini's W bead is the only thing genion can replace here.
    out = _run([gmx, "genion", "-s", str(tpr), "-o", str(ionised), "-p", "topol.top",
                "-pname", "NA", "-nname", "CL", "-neutral",
                "-conc", str(SALT_MOLAR)], cwd=work, stdin="W\n")
    for line in out.splitlines():
        if "Replacing solvent molecule" in line or "Number of" in line:
            continue
    print(f"  ions       neutralised at {SALT_MOLAR} M")
    return ionised


def build(pdb_id: str, chains: list[str], name: str, margin_nm: float = 1.2) -> Path:
    if not forcefield.available():
        raise SystemExit(
            "Martini force field missing. Run: python -m vervain.forcefield fetch"
        )

    work = SYSTEMS_DIR / name
    work.mkdir(parents=True, exist_ok=True)
    print(f"building {name} from {pdb_id} chains {','.join(chains)}\n")

    prepared = prepare(pdb_id, chains, work)
    cg = martinize(prepared, work)
    _rewrite_topology(work)
    solvated = solvate(cg, work, margin_nm=margin_nm)
    system = add_ions(solvated, work)

    print(f"\n  {system}")
    return system


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vervain.system", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="prepare, coarse-grain, solvate, neutralise")
    p_build.add_argument("--pdb", default="6M0J")
    p_build.add_argument("--chains", default="A,E",
                         help="comma-separated; 6M0J is A=ACE2, E=RBD")
    p_build.add_argument("--name", default="rbd-ace2")
    p_build.add_argument("--margin", type=float, default=1.2,
                         help="solvent margin in nm. A pull needs far more than "
                              "an equilibrium run: the complex has to be able to "
                              "come apart without touching its own periodic image.")

    args = parser.parse_args(argv)
    build(args.pdb, [c.strip() for c in args.chains.split(",")], args.name, args.margin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
