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

Target hardware is a laptop RTX 3060, 6 GB. That sizes the work:

| system | scale | feasible here |
| --- | --- | --- |
| spike ectodomain + membrane patch | ~300–500k beads | yes |
| ACE2 in an opposing membrane | ~200k beads | yes |
| approach, two membranes | ~1M beads | tight |
| whole virion, ~24 spikes | ~10–20M beads | no |

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
