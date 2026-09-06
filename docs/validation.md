# Validation targets

No single published dataset can grade this model. The requirements pull apart:
absolute molecule counts at fine time resolution come from cell lines, and the
interferon behavior in the right cell type comes at coarse resolution in relative
units. So validation is tiered, and each tier grades a different claim.

## Tier 1 — replication kinetics (primary calibration)

**Absolute quantitation of individual SARS-CoV-2 RNA molecules provides a new paradigm
for infection dynamics and variant differences.** eLife 2022;11:e74153.
<https://elifesciences.org/articles/74153>

Single-molecule FISH at ~95% detection efficiency. This is the only source that gives
what a kinetic model actually needs — **absolute molecule counts per individual cell**,
at hourly resolution across the window we simulate.

- Cell lines: Vero E6, Calu-3, A549-ACE2. MOI 1, 2 h inoculation, trypsin wash.
- Timepoints: 2, 4, 6, 8, 10, 24 hpi.
- Reports per cell: positive-sense gRNA, negative-sense gRNA, sgRNA, and replication
  factories — separately. Median ~30 gRNA/cell at 2 hpi; ~11 sgRNA copies/cell in 63% of
  infected cells at 2 hpi; sgRNA/gRNA ratio 0.5–8 over time.
- **Replication factories: 1–2 per cell at 2 hpi rising to ~30 by 10 hpi.** This directly
  grades the DMV compartment, which is why modeling DMVs as real compartments is
  falsifiable rather than decorative.
- **It already contains the outcome split we are trying to reproduce.** Cells stratify
  into "partially resistant" (<10² gRNA copies), "permissive" (10²–10⁵), and
  "super-permissive" (>10⁵), with 40% of cells still non-super-permissive at 24 hpi.
  That stratification is the productive/abortive axis, measured.

Limits: cell lines, not primary ciliated cells. Data lives on an Oxford OMERO server
rather than a public repository — expect to extract from published figures or request
access. No released-virion counts.

**Vero E6 cannot produce type I interferon.** Treat that arm of the dataset as a natural
IFN-knockout control: the model, with the IFN module disabled, must reproduce the Vero
trajectories. This is a free and unusually clean test of the replication arm in isolation.

## Tier 2 — interferon arm, correct cell type (primary validation)

**Ravindra et al., Single-cell longitudinal analysis of SARS-CoV-2 infection in human
airway epithelium.** PLOS Biology 2021. GEO **GSE166766**.
<https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.3001143>

- Primary HBECs at air-liquid interface, 28 days differentiated. MOI ~0.01. 1, 2, 3 dpi.
- **Ciliated cells identified as the major target at infection onset** — our exact cell.
- Per-cell viral UMI counts and per-cell IFNB1 / type III IFN / ISG expression, including
  ISG induction in bystander (uninfected) cells, which the IFN module must reproduce.
- Productive infection thresholded at ≥10 viral transcripts per cell.

Limits: units are UMI counts, not molecules. Converting requires a capture-efficiency
assumption (~10–30%), which is itself an `estimated` liability and must be registered as
one — it is not a free conversion. Daily resolution only. No infectious titer.

## Tier 3 — viral burden vs. IFN induction (cross-check)

**Fiege et al., Single cell resolution of SARS-CoV-2 tropism, antiviral responses, and
susceptibility to therapies in primary human airway epithelium.** PLOS Pathogens 2021.
GEO **GSE157526**.
<https://journals.plos.org/plospathogens/article?id=10.1371/journal.ppat.1009292>

- Primary nHTBE at ALI, MOI 2.5, 24 and 48 hpi.
- Strong positive correlation between replication level and IFN induction — **but with a
  population of high-viral-load, low-IFN cells**, i.e. successful antagonism by nsp1/ORF6.
  If our model cannot produce that population, the antagonist module is wrong.

## Tier 4 — burst size (order of magnitude only)

**Sender et al., The total number and mass of SARS-CoV-2 virions.** PNAS 2021.
<https://www.pnas.org/doi/10.1073/pnas.2024815118>

~10⁵–10⁶ virions or ~10–100 infectious units per cell. Derived partly from other
betacoronaviruses. Register as `estimated`; it constrains an order of magnitude, nothing
finer. Nothing found so far measures released virions per individual cell over time —
this remains the weakest link in the MVP criterion and should be stated in the UI.

## What this means for the MVP criterion

"Viral output matching published single-cell time-course data" resolves to:

1. Absolute per-cell gRNA, sgRNA, and replication-factory counts across 2–24 hpi fall
   within the eLife smFISH distributions (Tier 1).
2. With the IFN module disabled, the model reproduces the Vero E6 trajectories (Tier 1).
3. The simulated population reproduces the resistant / permissive / super-permissive
   stratification, including ~40% non-super-permissive at 24 hpi (Tier 1).
4. Per-cell ISG induction, including in bystanders, matches Tier 2 qualitatively, and the
   high-burden/low-IFN evader population from Tier 3 exists.
5. Released virions land in the 10⁵–10⁶ range (Tier 4) — an order-of-magnitude check, not
   a fit, and labeled as such.
