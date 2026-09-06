"""Vervain v0 — a single ciliated airway epithelial cell, well mixed.

STATUS: v0, UNCALIBRATED. Every rate constant is `estimated` and registered as a
liability in params.yaml. This model exists to exercise the full pipeline end to
end (kinetics -> solver -> frame -> renderer) and to establish that the IFN arm is
capable of bistability. It is not yet validated against the smFISH data in
docs/validation.md. Do not present its numbers as results.

Modeling choices worth knowing before reading the rules:

- Counts, not concentrations. Compartment volume is 1 so that SBML concentrations
  are molecule counts directly. Bimolecular constants are per-molecule-per-second.
- Monomers carry no binding sites. This is deliberate for v0: it keeps BioNetGen
  network generation trivial (no combinatorial explosion) while the topology is
  still changing. Sites arrive per-module as each module gets calibrated.
- DMVs are a real compartment (see PLAN.md section 7). Negative-strand synthesis
  and the dsRNA it produces live *inside* DMVs. Sensing only sees the fraction that
  leaks out. Shielding is therefore geometric, not a tuned damping term.
"""

from pysb import Expression, Initial, Model, Monomer, Observable, Parameter, Rule

from vervain.params.loader import p

Model()

# ---------------------------------------------------------------- species ----

# Viral entry
Monomer("Vout")        # extracellular virion, available to attach
Monomer("Vbound")      # attached to ACE2 at the plasma membrane
Monomer("Vendo")       # internalised, in endosome (cathepsin L route)
Monomer("ACE2")
Monomer("TMPRSS2")

# Viral RNA and protein
Monomer("gRNA")        # (+) genome, cytoplasmic — template for translation
Monomer("nsp")         # lumped ORF1ab products / RTC capacity
Monomer("DMV")         # double-membrane vesicle: the replication compartment
Monomer("ngRNA")       # (-) strand, inside DMVs
Monomer("dsRNA_dmv")   # replication intermediate, shielded inside DMVs
Monomer("dsRNA_cyt")   # leaked into cytosol — this is what gets sensed
Monomer("sgRNA")       # subgenomic mRNA pool
Monomer("Nprot")       # nucleocapsid
Monomer("Sprot")       # lumped structural envelope proteins (S, M, E)
Monomer("RNP")         # encapsidated genome, pre-budding
Monomer("Vassembled")  # assembled at ERGIC, not yet released
Monomer("Vreleased")   # egressed — the output the MVP cares about

# Viral antagonists
Monomer("nsp1")        # blocks host translation, suppresses IFN production
Monomer("ORF6")        # blocks STAT nuclear import, suppresses ISG induction

# Innate immunity
Monomer("RIGI")
Monomer("RIGI_a")
Monomer("IRF3")
Monomer("IRF3_a")
Monomer("IFN")         # secreted type I interferon
Monomer("ISG")         # the antiviral state

# ------------------------------------------------------------- conditions ----

# Set by the run parameters, not by biology. MOI and IFN pretreatment are the
# two things the UI exposes.
Parameter("MOI_virions", 10.0)
Parameter("IFN_pretreatment", 0.0)  # ISG copies present at t=0; the slider

Initial(Vout(), MOI_virions)
Initial(ISG(), IFN_pretreatment)

Initial(ACE2(), p("ACE2_0"))
Initial(TMPRSS2(), p("TMPRSS2_0"))
Initial(RIGI(), p("RIGI_0"))
Initial(IRF3(), p("IRF3_0"))

# ------------------------------------------------------------ observables ----

Observable("o_Vout", Vout())
Observable("o_Vbound", Vbound())
Observable("o_Vendo", Vendo())
Observable("o_gRNA", gRNA())
Observable("o_nsp", nsp())
Observable("o_DMV", DMV())
Observable("o_ngRNA", ngRNA())
Observable("o_dsRNA_dmv", dsRNA_dmv())
Observable("o_dsRNA_cyt", dsRNA_cyt())
Observable("o_sgRNA", sgRNA())
Observable("o_Nprot", Nprot())
Observable("o_Sprot", Sprot())
Observable("o_RNP", RNP())
Observable("o_Vassembled", Vassembled())
Observable("o_Vreleased", Vreleased())
Observable("o_ISG", ISG())
Observable("o_IFN", IFN())
Observable("o_IRF3a", IRF3_a())
Observable("o_nsp1", nsp1())
Observable("o_ORF6", ORF6())

# -------------------------------------------------------------- couplings ----

# The antiviral state suppresses viral translation and replication. This is the
# arm that has to beat replication for an abortive outcome, so its steepness is a
# first-class liability, not an implementation detail. The Hill exponent of 2 is
# doing real work: with n=1 the block is too gradual to produce a sharp outcome
# boundary, and the slider just slides. ISGs act combinatorially on several steps,
# which justifies n>1, but the exact value is a guess and must be swept.
Expression("f_isg_block", 1.0 / (1.0 + (o_ISG / p("ISG_half_block")) ** 2))

# Finite ribosomes. Without this, per-mRNA output stays constant as mRNA piles up
# and translation runs away. Total viral mRNA competes for one pool.
Expression(
    "f_ribosome",
    1.0 / (1.0 + (o_gRNA + o_sgRNA) / p("ribosome_capacity")),
)

# Finite membrane for DMV biogenesis. Soft cap rather than a hard ceiling so the
# rate stays positive; a proper membrane-pool species is the milestone-6 version.
Expression("f_membrane", 1.0 / (1.0 + (o_DMV / p("DMV_max")) ** 4))

# Replication capacity is per-DMV, not per-template: each vesicle holds a bounded
# number of replication-transcription complexes. Saturating in template count is
# what keeps total RNA synthesis proportional to DMV count, which is the quantity
# smFISH actually measures.
Expression("f_template_pos", 1.0 / (1.0 + o_gRNA / p("K_template")))
Expression("f_template_neg", 1.0 / (1.0 + o_ngRNA / p("K_negstrand")))

# nsp1 suppresses IFN production; ORF6 suppresses ISG induction downstream of it.
Expression("f_nsp1_block", 1.0 / (1.0 + o_nsp1 / p("nsp1_half_block")))
Expression("f_orf6_block", 1.0 / (1.0 + o_ORF6 / p("ORF6_half_block")))

# ------------------------------------------------------------------ rules ----

# Entry. Two routes: TMPRSS2-dependent fusion at the surface, and the slower
# cathepsin L endosomal route. Both converge on cytoplasmic genome.
Rule("attach", Vout() + ACE2() >> Vbound() + ACE2(), p("kf_S_ACE2"))
Rule("detach", Vbound() >> Vout(), p("kr_S_ACE2"))
Rule("fuse_surface", Vbound() + TMPRSS2() >> gRNA() + TMPRSS2(), p("k_fuse_tmprss2"))
Rule("endocytose", Vbound() >> Vendo(), p("k_endocytose"))
Rule("uncoat_endosome", Vendo() >> gRNA(), p("k_uncoat_cathepsinL"))

# Translation of ORF1ab off the incoming genome. ISG-suppressed, ribosome-limited.
Expression("k_transl_eff", p("k_translate_orf1ab") * f_isg_block * f_ribosome)
Rule("translate_orf1ab", gRNA() >> gRNA() + nsp(), k_transl_eff)

# Antagonists are ORF1ab / accessory products; track them off the same pools.
Expression("k_nsp1_eff", p("k_make_nsp1") * f_isg_block * f_ribosome)
Expression("k_orf6_eff", p("k_make_orf6") * f_isg_block * f_ribosome)
Rule("make_nsp1", gRNA() >> gRNA() + nsp1(), k_nsp1_eff)
Rule("make_orf6", sgRNA() >> sgRNA() + ORF6(), k_orf6_eff)

# DMV biogenesis, driven by nsp accumulation. Validated against smFISH
# replication-factory counts: 1-2 per cell at 2 hpi, ~30 by 10 hpi.
Expression("k_dmv_eff", p("k_form_dmv") * f_membrane)
Rule("form_dmv", nsp() >> nsp() + DMV(), k_dmv_eff)

# Replication inside DMVs. Requires both a genome template and DMV capacity.
Expression("k_neg_eff", p("k_synth_negative") * f_template_pos)
Rule(
    "synth_negative",
    gRNA() + DMV() >> gRNA() + DMV() + ngRNA() + dsRNA_dmv(),
    k_neg_eff,
)

# Positive-strand and subgenomic synthesis both read off the negative template and
# both consume the same per-DMV capacity, so both are bimolecular in DMV.
Expression("k_rep_eff", p("k_synth_positive") * f_isg_block * f_template_neg)
Rule("synth_positive", ngRNA() + DMV() >> ngRNA() + DMV() + gRNA(), k_rep_eff)
Expression("k_sg_eff", p("k_synth_subgenomic") * f_isg_block * f_template_neg)
Rule("synth_subgenomic", ngRNA() + DMV() >> ngRNA() + DMV() + sgRNA(), k_sg_eff)

# dsRNA escaping the DMV is what the cell can actually sense.
Rule("dsRNA_leak", dsRNA_dmv() >> dsRNA_cyt(), p("k_dsRNA_leak"))
Rule("dsRNA_cyt_decay", dsRNA_cyt() >> None, p("k_dsRNA_decay"))

# Structural proteins from subgenomic mRNA. ISG-suppressed like all translation.
Expression("k_struct_eff", p("k_translate_struct") * f_isg_block * f_ribosome)
Rule("translate_N", sgRNA() >> sgRNA() + Nprot(), k_struct_eff)
Rule("translate_S", sgRNA() >> sgRNA() + Sprot(), k_struct_eff)

# Assembly at the ERGIC and egress. Two steps: N encapsidates the genome, then the
# RNP buds through membranes bearing S/M/E.
#
# COARSE-GRAINING: real stoichiometry is ~10^3 N per genome and ~10^2 S trimers per
# virion. v0 treats both as 1:1, which makes structural protein counts meaningless
# in absolute terms while preserving the *shape* of the assembly bottleneck. Fix
# this before comparing protein counts to anything measured.
Rule("encapsidate", gRNA() + Nprot() >> RNP(), p("k_encapsidate"))
Rule("bud", RNP() + Sprot() >> Vassembled(), p("k_bud"))
Rule("egress", Vassembled() >> Vreleased(), p("k_egress"))

# Turnover.
#
# The OAS/RNase L arm. This is not decoration: it is the only mechanism in the
# model that can *destroy* an established genome rather than merely slow its
# replication. Without it the antiviral state only delays infection and the
# outcome is monostable — pretreatment buys hours, not a different fate. With it,
# a cell that reaches a high antiviral state before replication is established
# clears the genome and stays cleared, which is the abortive outcome.
Expression(
    "k_gRNA_deg_eff",
    p("k_deg_gRNA")
    + p("k_rnasel_max") * o_ISG ** 2 / (o_ISG ** 2 + p("ISG_half_block") ** 2),
)
Expression(
    "k_sgRNA_deg_eff",
    p("k_deg_sgRNA")
    + p("k_rnasel_max") * o_ISG ** 2 / (o_ISG ** 2 + p("ISG_half_block") ** 2),
)
Rule("degrade_gRNA", gRNA() >> None, k_gRNA_deg_eff)
Rule("degrade_sgRNA", sgRNA() >> None, k_sgRNA_deg_eff)
Rule("degrade_ngRNA", ngRNA() >> None, p("k_deg_ngRNA"))
Rule("degrade_dsRNA_dmv", dsRNA_dmv() >> None, p("k_deg_dsRNA_dmv"))
Rule("degrade_nsp", nsp() >> None, p("k_deg_nsp"))
Rule("degrade_nsp1", nsp1() >> None, p("k_deg_protein"))
Rule("degrade_orf6", ORF6() >> None, p("k_deg_protein"))
Rule("degrade_Nprot", Nprot() >> None, p("k_deg_protein"))
Rule("degrade_Sprot", Sprot() >> None, p("k_deg_protein"))

# ---- innate immune arm ----

# Sensing: RIG-I/MDA5 activated by cytosolic dsRNA only.
Rule("sense_dsRNA", RIGI() + dsRNA_cyt() >> RIGI_a() + dsRNA_cyt(), p("k_sense"))
Rule("rigi_off", RIGI_a() >> RIGI(), p("k_rigi_off"))

# IRF3 activation downstream of sensing.
Rule("activate_irf3", IRF3() + RIGI_a() >> IRF3_a() + RIGI_a(), p("k_activate_irf3"))
Rule("irf3_off", IRF3_a() >> IRF3(), p("k_irf3_off"))

# IFN production, suppressed by nsp1.
Expression("k_ifn_eff", p("k_produce_ifn") * f_nsp1_block)
Rule("produce_ifn", IRF3_a() >> IRF3_a() + IFN(), k_ifn_eff)
Rule("degrade_ifn", IFN() >> None, p("k_deg_ifn"))

# ISG induction via JAK/STAT, suppressed by ORF6.
Expression("k_isg_eff", p("k_induce_isg") * f_orf6_block)
Rule("induce_isg", IFN() >> IFN() + ISG(), k_isg_eff)
Rule("degrade_isg", ISG() >> None, p("k_deg_isg"))

# The positive feedback that makes bistability possible: the antiviral state
# raises sensing capacity, which raises IFN, which raises the antiviral state.
# Without this the outcome is monostable and the slider does nothing interesting.
Rule("isg_boosts_rigi", ISG() >> ISG() + RIGI(), p("k_isg_to_rigi"))
Rule("basal_rigi", None >> RIGI(), p("k_rigi_basal"))
Rule("degrade_rigi", RIGI() >> None, p("k_deg_rigi"))
