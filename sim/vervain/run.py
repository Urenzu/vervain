"""Minimise, equilibrate and run, with the GPU actually doing the work.

    python -m vervain.run all --name rbd-ace2
    python -m vervain.run md  --name rbd-ace2 --ns 20

Each stage is skipped if its output already exists, so a failed production run
does not mean redoing equilibration.
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

from vervain.system import MDP_DIR, SYSTEMS_DIR, _run, gmx_binary

# Martini's non-solvent bead names. Everything else in the box is protein.
SOLVENT_BEADS = frozenset({"W", "WF", "NA", "CL", "ION"})


def make_index(gro: Path, ndx: Path) -> tuple[int, int]:
    """Write Protein and Solvent groups.

    Built directly from the coordinate file rather than driven through
    `gmx make_ndx`, whose group numbering shifts with the system's contents —
    scripting it means feeding indices you cannot know in advance.
    """
    lines = gro.read_text(encoding="utf-8").splitlines()
    count = int(lines[1])

    protein: list[int] = []
    solvent: list[int] = []
    for i in range(count):
        # .gro is fixed-column: residue name 5:10, atom name 10:15.
        atom_name = lines[2 + i][10:15].strip()
        (solvent if atom_name in SOLVENT_BEADS else protein).append(i + 1)

    def block(name: str, indices: list[int]) -> str:
        rows = [
            " ".join(f"{n:>6}" for n in indices[i:i + 15])
            for i in range(0, len(indices), 15)
        ]
        return f"[ {name} ]\n" + "\n".join(rows) + "\n"

    ndx.write_text(block("Protein", protein) + block("Solvent", solvent), encoding="utf-8")
    return len(protein), len(solvent)


# GROMACS refuses GPU update for reasons it states plainly; this is the text it
# uses when the topology is the problem rather than the request.
GPU_UPDATE_REFUSED = "Update task can not run on the GPU"


def _mdrun_flags(gpu: bool, gpu_update: bool) -> list[str]:
    """GPU offload, minus the parts this system cannot use.

    Martini uses reaction-field, so there is no PME to offload — passing
    `-pme gpu` is an error rather than a no-op.

    GPU update is refused outright for Martini 3 proteins: the model uses
    virtual sites for some side chains and triangle constraints, and the GPU
    update path supports neither. That is a property of the force field, not of
    any particular stage, so it cannot be enabled by dropping restraints.
    """
    if not gpu:
        return []
    flags = ["-nb", "gpu", "-bonded", "gpu"]
    if gpu_update:
        flags += ["-update", "gpu"]
    return flags


def stage(
    name: str,
    work: Path,
    mdp: Path,
    coords: Path,
    *,
    gpu: bool = True,
    restrained: bool = False,
    restraint_ref: Path | None = None,
    extra_mdrun: list[str] | None = None,
) -> Path:
    gmx = gmx_binary()
    tpr = work / f"{name}.tpr"
    out = work / f"{name}.gro"

    if out.exists():
        print(f"  {name:<10} already done ({out.name})")
        return out

    grompp = [
        gmx, "grompp", "-f", str(mdp), "-c", str(coords),
        "-p", "topol.top", "-n", "index.ndx", "-o", str(tpr), "-maxwarn", "5",
    ]
    if restrained:
        grompp += ["-r", str(restraint_ref or coords)]
    _run(grompp, cwd=work)

    threads = str(min(os.cpu_count() or 4, 12))

    def build(gpu_update: bool) -> list[str]:
        return [
            gmx, "mdrun", "-deffnm", name, "-ntmpi", "1", "-ntomp", threads,
            *_mdrun_flags(gpu, gpu_update),
            *(extra_mdrun or []),
        ]

    started = time.time()
    try:
        # Ask for GPU update; fall back rather than leave it permanently off,
        # so a future system without virtual sites picks the speedup up on its
        # own instead of inheriting this one's limitation.
        output = _run(build(gpu_update=gpu), cwd=work)
    except SystemExit as exc:
        if not gpu or GPU_UPDATE_REFUSED not in str(exc):
            raise
        print(f"  {name:<10} GPU update declined by GROMACS "
              "(Martini virtual sites); integrating on CPU")
        output = _run(build(gpu_update=False), cwd=work)
    elapsed = time.time() - started

    perf = ""
    for line in output.splitlines():
        if "Performance:" in line:
            perf = line.split("Performance:")[-1].strip()
    print(f"  {name:<10} {elapsed:>7.1f}s   {perf}")
    return out


def run_all(name: str, ns: float | None, gpu: bool = True) -> Path:
    work = SYSTEMS_DIR / name
    system = work / "system.gro"
    if not system.exists():
        raise SystemExit(f"{name}: no system.gro. Run: python -m vervain.system build")

    print(f"running {name}\n")
    ndx = work / "index.ndx"
    n_protein, n_solvent = make_index(system, ndx)
    print(f"  index      {n_protein} protein, {n_solvent} solvent beads")

    em = stage("em", work, MDP_DIR / "em.mdp", system, gpu=False)

    eq = stage(
        "eq", work, MDP_DIR / "eq.mdp", em,
        gpu=gpu, restrained=True, restraint_ref=em,
    )

    md_mdp = MDP_DIR / "md.mdp"
    if ns is not None:
        # dt is 20 fs, so steps = ns / 20 fs.
        steps = int(ns * 1000 / 0.020)
        scratch = work / "md_scaled.mdp"
        scratch.write_text(
            "\n".join(
                f"nsteps                 = {steps}" if line.strip().startswith("nsteps")
                else line
                for line in md_mdp.read_text(encoding="utf-8").splitlines()
            ) + "\n",
            encoding="utf-8",
        )
        md_mdp = scratch

    md = stage("md", work, md_mdp, eq, gpu=gpu)
    print(f"\n  {work / 'md.xtc'}")
    return md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vervain.run", description=__doc__)
    parser.add_argument("command", choices=["all"], nargs="?", default="all")
    parser.add_argument("--name", default="rbd-ace2")
    parser.add_argument("--ns", type=float, default=None,
                        help="production length in nanoseconds (default: mdp value)")
    parser.add_argument("--cpu", action="store_true", help="disable GPU offload")
    args = parser.parse_args(argv)

    if not shutil.which("mkdssp"):
        pass  # not needed at run time; only reported by doctor

    run_all(args.name, args.ns, gpu=not args.cpu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
