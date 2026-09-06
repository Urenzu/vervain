# Vervain — Phase One Plan

**Scope of phase one:** one ciliated human airway epithelial cell, ~24 simulated hours,
well-mixed kinetics, innate immune arm included from the start.

**MVP done criterion:** a user drags an interferon-pretreatment slider and the outcome
flips between productive and abortive infection, with released virion counts falling
inside the published single-cell time-course envelope.

---

## 1. The two contracts that must not bend

The architecture is provisional everywhere except two seams. These exist so the solver
can later become spatially-resolved RDME and the renderer can become raw WebGPU without
either change touching the other. Everything else is allowed to be rewritten.

### Seam A — the state frame (solver to everything downstream)

The solver's only output is a versioned, position-free frame:

```
StateFrame {
  schema: "vervain.frame/1",
  t_sec: float,                       // simulated time
  counts: { [species_id]: number },   // molecular counts, not concentrations
  compartment: { [species_id]: compartment_id },
  regime: "ssa" | "ode",              // which solver produced this frame
  outcome_flags: { ... }              // e.g. isg_state, dmv_established
}
```

Rules: the solver never emits a coordinate. The frame never mentions spheres, colors, or
frames-per-second. When the solver becomes RDME, it gains a **voxel** axis on `counts`
and nothing else in the contract changes.

### Seam B — the instancer (counts to scene)

The instancer is a **pure function** `(counts, prev_scene, seed) -> Scene`. It owns every
spatial decision. It is the only place in the codebase where a position is invented.

- Spatial positions are **illustrative**; counts are **modeled**. The UI must say this
  in the interface itself, not only in documentation — a persistent affordance, not a
  one-time dismissible notice.
- Temporal coherence is the instancer's hard requirement: a molecule that persists across
  two frames keeps its identity and moves continuously. Otherwise the scene boils and
  reads as noise instead of biology.
- The instancer runs client-side. The server ships counts; nothing else.

---

## 2. Parameter provenance

Every parameter carries a literature source and a confidence flag. This is enforced
structurally, not by convention:

- `sim/vervain/params/params.yaml` is the **single source of truth**.
- Model code may not contain a bare rate constant. A test walks the PySB model and fails
  on any `Parameter` whose name is absent from `params.yaml`.
- Confidence is one of `measured` (direct experimental value for SARS-CoV-2),
  `analogous` (measured for a related coronavirus or a comparable process),
  `inferred` (fit to aggregate data), `estimated` (order-of-magnitude argument from
  first principles). Every `estimated` parameter is a declared liability, listed in
  `docs/parameters.md` and surfaced in the UI's provenance panel.
- Sensitivity analysis runs over the `estimated` set specifically. If the productive /
  abortive flip is sensitive to a guessed number, that is the headline result, and the
  honest thing is to say so rather than tune until it looks right.

---

## 3. Model decomposition

Built as separable PySB modules, each independently testable against its own observable
before composition. The order below is also the build order.

| Module | Covers | Key observable to validate against |
|---|---|---|
| `entry.py` | ACE2 binding, TMPRSS2 surface route, cathepsin L endosomal route, uncoating | fraction entered vs. time; route split under protease inhibition |
| `translation.py` | ORF1ab translation, pp1a/pp1ab ribosomal frameshift, nsp cleavage | nsp appearance timing |
| `replication.py` | RTC assembly, DMV formation, (−) strand synthesis, (+) genome replication, subgenomic transcription | gRNA and sgRNA copy number over 24 h; sgRNA abundance hierarchy (N >> S) |
| `assembly.py` | structural protein synthesis, ERGIC assembly, egress | released virions over time |
| `innate.py` | RIG-I/MDA5 sensing of dsRNA, IRF3 activation, IFN-beta secretion, JAK/STAT, ISG antiviral state, nsp1 and ORF6 antagonism | IFN-beta and ISG transcript timing; antagonist knockout response |
| `cell.py` | composition, compartment volumes, initial conditions | the whole-cell outcome |

**Composition risk:** BioNetGen network generation is combinatorial in binding sites.
Keep monomer site counts minimal and check the generated species count after each module
is added. If the network exceeds a few thousand species, coarse-grain the offending
complex rather than waiting for it to become intractable at composition time.

**Where the interesting behavior lives:** the productive/abortive flip is a bistability
between viral replication and the ISG antiviral state. It only appears if the IFN arm has
real positive feedback (IFN to ISG to more sensing) racing against nsp1/ORF6 suppression.
If the model turns out monostable, the fix belongs in the feedback topology, not in the
slider — the flip must not be manufactured by clamping.

---

## 4. Solver strategy

- **Hour 0–1: Gillespie SSA.** Entry is a handful of virions; copy numbers are single
  digits. Deterministic ODEs at these counts produce fractional virions and erase the
  stochastic abortive-infection tail, which is precisely the phenomenon of interest.
  Run an ensemble here — a single trajectory is not a result.
- **Hour 1–24: libRoadRunner / CVODE.** Stiff, once counts are large.
- **Handoff:** switch when every species that gates a downstream reaction exceeds a
  threshold (start at ~100 copies). Handoff is a discrete state transfer; the frame's
  `regime` field records which side produced it. Validate that an ensemble of SSA runs
  continued into ODE matches SSA-throughout on a reduced model — this is the single most
  likely place for a silent correctness bug.
- **Known wrinkle (verified in the smoke test):** PySB's SBML export renames species to
  `__s0`, `__s1`, … The mapping from PySB observables to SBML ids must be captured at
  export time and shipped alongside the frame schema. Also confirm compartment volume is
  set such that RoadRunner's concentrations correspond to the counts we intend.

---

## 5. Transport and frontend

- Python websocket server streams `StateFrame`s; simulated time is decoupled from wall
  time, with the client requesting a playback rate.
- A run is parameterized by an input struct (MOI, IFN pretreatment dose and timing,
  knockouts). Runs are cached by parameter hash — the slider must feel immediate, which
  means pre-computing the sweep rather than solving on drag.
- React/TypeScript, Three.js instanced spheres for phase one. The renderer consumes
  `Scene` from the instancer and knows nothing above it.

---

## 6. Milestones

1. **Environment pinned.** Done — verified that PySB to BioNetGen to SBML to
   RoadRunner/CVODE works on Windows / Python 3.13. `BNGPATH` must be set; see
   `.env.example`.
2. **Parameter spine.** `params.yaml` schema, loader, and the test that forbids bare
   constants. Populate with the entry-module parameters only.
3. **Entry module** plus SSA ensemble and its validation plot. First real biology.
4. **Frame contract, websocket, and a trivial renderer.** Prove the seam end-to-end while
   the model is still small enough to reason about.
5. **Instancer** with temporal coherence, and the illustrative-position UI affordance.
6. **Replication, translation, assembly.** Full productive infection over 24 h, validated
   against published single-cell time courses.
7. **Innate immune arm.** IFN feedback and antagonists. Confirm bistability exists.
8. **The slider.** Pre-computed IFN pretreatment sweep, outcome flip, provenance panel.
9. **Sensitivity analysis** over the `estimated` parameters; publish what the result
   rests on.

Milestones 4 and 5 are deliberately early. Building the whole model before the seam is
exercised is how the seam ends up leaking.

---

## 7. Decisions taken

**Validation targets: settled.** Tiered, because no single dataset grades everything —
see `docs/validation.md`. Absolute per-cell molecule counts at hourly resolution from
smFISH (eLife 2022;11:e74153), which also supplies replication-factory counts per cell
and already contains the resistant/permissive/super-permissive stratification we are
trying to reproduce. Interferon behavior in actual ciliated cells from Ravindra et al.
2021 (GSE166766). Antagonist behavior cross-checked against Fiege et al. 2021
(GSE157526). Burst size is order-of-magnitude only, and no source found so far measures
released virions per individual cell over time — the weakest link in the MVP criterion,
and it must be stated in the UI rather than hidden.

**DMVs: modeled as real compartments**, with a volume and with replication occurring
inside them. Shielding from RIG-I/MDA5 sensing then falls out of the geometry rather than
being a tuned damping term. This costs an unsourced compartment volume — registered as an
`estimated` liability — but the smFISH dataset counts replication factories per cell over
time (1–2 at 2 hpi rising to ~30 by 10 hpi), so the compartment is directly falsifiable,
and the representation survives the move to RDME without a rewrite.

## 8. Still open before milestone 6

- Cytoplasm, ERGIC, and DMV volumes. Every bimolecular rate is defined per-volume, so
  these are load-bearing and currently unsourced. Handled as part of milestone 2.
- The scRNA-seq capture-efficiency assumption needed to convert Tier 2 UMI counts into
  molecules. This is a modeling decision, not a conversion factor — register it as
  `estimated` and sweep it.
