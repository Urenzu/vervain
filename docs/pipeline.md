# Pipeline

Coarse-grained molecular dynamics of SARS-CoV-2 entry at an airway cell surface.

## What this is, and what it is not

This is a physics simulation. Positions come out of an integrator, not an
animator. That is the whole point, and it is what separates the output from the
scientific animations it superficially resembles.

It is **not** a simulation of viral entry end to end, and it cannot become one.
MARTINI runs at a 20–30 fs timestep with roughly a 4× effective-time speedup;
a long run reaches microseconds. Entry takes seconds. The gap is six to seven
orders of magnitude and no amount of hardware closes it.

So the pipeline simulates the parts that fit inside a microsecond, and drives
the parts that do not. Every driven step is labelled as driven.

| process | real timescale | how we handle it |
| --- | --- | --- |
| spike hinge flexing | ns – µs | unbiased |
| glycan shield motion | ns | unbiased |
| RBD open ⇄ closed | µs – ms | enhanced sampling |
| approach and engagement | ms – s | steered |
| membrane fusion | ms | steered, and see the MARTINI caveat below |
| endocytosis | minutes | out of scope |

## First light — measured

The RBD-ACE2 complex from 6M0J, run end to end on a laptop RTX 3060 (6 GB) and
an i7-11800H, with GROMACS 2025.2 built for CUDA and AVX2.

| | |
| --- | --- |
| system | 13,467 beads — 1,937 protein, 11,164 water, 366 ions |
| box | rhombic dodecahedron, 12.86 nm |
| minimisation | 4.4 s |
| equilibration | 2 ns restrained NPT, 101 s |
| production | 50 ns in 2,269 s — **1,905 ns/day** |
| exported | 1,001 frames, 11.1 MB after dropping water and quantising |

**Interface stability.** Closest approach between ACE2 and the RBD held at
0.30–0.39 nm across all 1,001 frames, against 0.36 nm in the coarse-grained
starting structure and 0.41 nm Cα–Cα in the crystal. The complex stays bound
over the simulated window.

That number is computed and printed at export, not eyeballed. It is the
difference between a bound complex and a dissociated one and it is invisible in
a render — which matters, because the first version of the export *did* render
a dissociated complex, and the cause was periodic wrapping rather than physics.
See the export module for what `-pbc mol` does to a two-chain complex.

**Where the time went.** GPU update is refused for Martini 3 proteins — virtual
sites and triangle constraints — so integration runs on CPU while nonbonded and
bonded work stays on the GPU. That is the configuration the 1,905 ns/day figure
was measured in; a system without virtual sites would go faster still.

---

## Stages

### 1 · Structures

`sim/vervain/structures.py` fetches from RCSB and reports what is actually in
each file. The catalogue is `sim/vervain/structures.yaml`; nothing enters the
pipeline without a source and a stated confidence, carried over from the
kinetic model's parameter discipline.

Two findings from the first inspection that shape everything downstream:

- **6VXX has 11 unresolved gaps per chain, and four of them are inside the
  RBD** — 445–446, 455–461, 469–488, 502. Those are contact residues. A binding
  simulation built on the raw deposition would be modelling the interface with
  holes in it.
- **6M0J's RBD (333–526) has zero gaps.** The fix is to graft the complete
  X-ray RBD onto the cryo-EM trimer, then model the remaining non-interface
  loops.

Also confirmed: 6VXX resolves 63 glycan residues against a shield that carries
22 N-linked sites per protomer. The deposited glycans are a rounding error on
the real thing, so the shield has to be built rather than inherited.

### 2 · Repair and completion

- Graft 6M0J RBD → 6VXX trimer.
- Model the remaining loops (NTD 144–164, 173–185, 246–262; FPPR 828–853).
- Decide the stalk. 6VXX ends at 1147; the three hinges and the transmembrane
  anchor are absent. Either graft a modelled stalk or adopt a published
  full-length model — unresolved, tracked in `structures.yaml`.
- Build the glycan shield.

### 3 · Coarse-graining

`martinize2` (vermouth) → MARTINI 3. Elastic network for tertiary structure.

**The caveat that matters most for this project:** MARTINI holds protein fold
with an elastic network, so it does not natively capture the prefusion →
postfusion refolding that *is* the fusion machine. A fusion simulation built on
stock MARTINI would be showing membranes merging while the protein driving it
stays rigid. Gō-MARTINI or an equivalent is required before stage 5 means
anything. Better to know now than after the membrane work.

### 4 · System assembly

CHARMM-GUI Martini Maker for membranes and protein-membrane assembly. Airway
plasma membrane lipid composition is currently unsourced and is the direct
analogue of the old model's compartment-volume liability — it is load-bearing
and it is a guess until somebody sources it.

Assembly and equilibration is 60–80% of the real work. Running is the easy part.

### 5 · Runs

GROMACS. See `scripts/setup-gromacs-cuda.sh` — the Ubuntu package is built with
GPU support disabled and SIMD pinned to SSE4.1, which on an Ampere card leaves
most of the machine idle.

Target hardware is a laptop RTX 3060, 6 GB, on an i7-11800H.

### Sizing, and where the cost actually is

Counted at MARTINI 3 resolution — ~2.3 beads per residue, 8.35 water beads per
nm³, ~12 beads per phospholipid:

| system | protein | lipid | water | total |
| --- | ---: | ---: | ---: | ---: |
| A · spike ectodomain in water, 18×16×16 nm | 6.7k (25%) | — | 20k (75%) | **27k** |
| B · spike + stalk/TM in a 25×25 nm membrane | 7.3k (5%) | 23k (16%) | 116k (79%) | **146k** |
| C · single RBD + ACE2 domain, 11×9×9 nm | 1.8k (42%) | — | 2.5k (58%) | **4.3k** |

All three fit comfortably. The 6 GB card is not the binding constraint at this
stage; wall-clock is.

**The protein is 5% of the cost and 100% of the science.** Coarsening it below
MARTINI's ~4 heavy atoms per bead — a Cα-only Gō model, say — would save
single-digit percent of the system while destroying the side-chain chemistry at
the ACE2 interface, which is the thing an entry simulation exists to resolve.
Not a trade worth making.

**Water is 75–79%.** That is the only place real savings live, and it comes with
a cost that matters here: Dry Martini's implicit solvent removes hydrodynamics,
substituting Langevin friction for solvent coupling. For a run whose entire
purpose is watching the spike's hinges move realistically, that changes the
character of the motion being observed. Reasonable for equilibrating a membrane
cheaply; not for production hinge dynamics.

So the levers on this hardware, in order of value:

1. **Full GPU offload.** GROMACS 2025 can place nonbonded, PME, bonded, and the
   update/constraint step on the GPU (`-nb gpu -pme gpu -bonded gpu -update gpu`).
   On a single-GPU machine this is the largest available win and it costs
   nothing but flags.
2. **Replicas over length.** System C is 34× smaller than B. For anything whose
   answer is a distribution — does this RBD engage, and how often — twenty short
   independent runs are worth more than one long one, and they parallelise
   across time rather than across hardware you do not have.
3. **Box discipline.** Padding is water, and water is 79%.
4. **Timestep.** MARTINI 3 runs at 20 fs; lipid-dominated systems often take 25–30.

| system | scale | feasible here |
| --- | --- | --- |
| A / B / C above | 4k – 150k beads | yes |
| approach, two membranes | ~1M beads | tight |
| whole virion, ~24 spikes | ~10–20M beads | no |

### Filesystem

The repo lives on `/mnt/c`, and every file operation from WSL crosses the 9p
boundary into Windows. A venv created there takes minutes rather than seconds.
Environments live under `$HOME/.venvs` on the Linux side and are symlinked in;
trajectories should go under `$VERVAIN_DATA` for the same reason, or GROMACS
spends its time on I/O rather than on integration.

### The VM shuts itself down under a long run

The first 20 ns steered run died at 18.2 ns with no fatal error in `pull.log`,
no stdout, and a `.xvg` truncated mid-number. Nothing was wrong with the
physics: energies and constraint RMSD were healthy at the last logged step. WSL
had torn the VM down underneath `mdrun` once the invoking shell went away —
`uptime` after the fact read `up 0 min`. Anything longer than a few minutes
needs the VM held open, or a `wsl --shutdown`-proof invocation; the checkpoint
(`pull.cpt`) is what makes the loss recoverable rather than total.

Both xvg readers already tolerated this by design — a short final line fails the
two-column check, and mismatched file lengths are truncated to the shorter — so
the curve parsed correctly from a file that had been cut off mid-write.

### Steered result, measured

| quantity | value |
| --- | --- |
| pull rate | 0.15 nm/ns |
| rupture force | 333 pN, smoothed |
| rupture time | 1.8 ns |
| extension there | 4.43 nm |
| interface contacts | 224 → 8 over 18 ns |

The rupture force is an upper bound, not a binding free energy: 0.15 nm/ns is
six or more orders of magnitude faster than any physical unbinding, so the
number is only meaningful against another variant pulled identically.

Closest approach is a poor readout for this. It moves from 0.30 to 0.47 nm
across the entire run while the complex plainly comes apart, because a handful
of beads keep grazing after the binding site has let go. The contact *count*
carries the signal, and it is the one number in the viewer that visibly changes
between the first frame and the last.

### 6 · Export and view

Trajectory → compact binary → browser. The viewer keeps the existing React /
Three.js shell and its token system; what changes is that positions arrive from
the integrator instead of being invented client-side.

Rendering technique carried over from the molecular-visualisation field:
impostor spheres (analytic ray–sphere in the fragment shader, two triangles per
bead), ambient occlusion, depth cueing. AO in particular is what makes a dense
molecular scene legible rather than confetti.

## Provenance rule

The old repo's best idea was that no rate constant could appear without a
source and a confidence flag. The same rule applies here to structures, lipid
compositions, and force-field choices. `structures.yaml` carries an
`open_questions` block for exactly this reason: the unsourced inputs are
written down as liabilities rather than quietly defaulted.
