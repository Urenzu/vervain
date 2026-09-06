"""Wire protocol. Seam A from PLAN.md — the solver's only output.

The rule this file exists to enforce: **no coordinate ever crosses this boundary.**
The server ships molecular counts and simulated time. Every position in the render
is invented client-side by the instancer, which is why the UI can honestly say
counts are modeled and positions are illustrative.

When the solver becomes spatially resolved (RDME), `counts` gains a voxel axis and
`schema` bumps to vervain.frame/2. Nothing else here changes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA = "vervain.frame/1"

# Species the renderer draws, in the order the legend shows them. Species absent
# from this list are still streamed — the frontend charts them — but are not
# instanced as geometry.
RENDERED_SPECIES = (
    "Vout",
    "Vbound",
    "Vendo",
    "gRNA",
    "ngRNA",
    "DMV",
    "sgRNA",
    "Nprot",
    "Sprot",
    "RNP",
    "Vassembled",
    "Vreleased",
    "dsRNA_cyt",
    "ISG",
)

# Which compartment each species occupies. The instancer uses this to decide
# *where* to scatter; it is a rendering hint, not a modeled quantity.
COMPARTMENT = {
    "Vout": "extracellular",
    "Vbound": "plasma_membrane",
    "Vendo": "endosome",
    "gRNA": "cytoplasm",
    "sgRNA": "cytoplasm",
    "Nprot": "cytoplasm",
    "Sprot": "ergic",
    "RNP": "cytoplasm",
    "nsp": "cytoplasm",
    "nsp1": "cytoplasm",
    "ORF6": "cytoplasm",
    "ngRNA": "dmv",
    "dsRNA_dmv": "dmv",
    "dsRNA_cyt": "cytoplasm",
    "DMV": "cytoplasm",
    "Vassembled": "ergic",
    "Vreleased": "extracellular",
    "ISG": "cytoplasm",
    "IFN": "extracellular",
    "RIGI": "cytoplasm",
    "RIGI_a": "cytoplasm",
    "IRF3": "cytoplasm",
    "IRF3_a": "nucleus",
    "ACE2": "plasma_membrane",
    "TMPRSS2": "plasma_membrane",
}


@dataclass
class StateFrame:
    t_sec: float
    counts: dict[str, float]
    regime: str
    outcome_flags: dict[str, bool] = field(default_factory=dict)
    schema: str = SCHEMA

    def to_dict(self) -> dict:
        return asdict(self)


def outcome_flags(counts: dict[str, float]) -> dict[str, bool]:
    """Coarse qualitative state, computed server-side so the UI and the analysis
    agree on what 'productive' means rather than each inventing a threshold."""
    return {
        # smFISH stratification: >1e5 genome copies is "super-permissive".
        "super_permissive": counts.get("gRNA", 0.0) > 1e5,
        # Below one genome copy there is nothing left to replicate.
        "genome_cleared": counts.get("gRNA", 0.0) < 1.0,
        "dmv_established": counts.get("DMV", 0.0) >= 1.0,
        "antiviral_state": counts.get("ISG", 0.0) > 1e4,
        "releasing": counts.get("Vreleased", 0.0) > 1.0,
    }
