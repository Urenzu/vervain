"""Solver front end: PySB model -> SBML -> libRoadRunner, ODE or stochastic.

Both regimes run through RoadRunner so there is one code path and one set of
semantics. The SSA regime uses RoadRunner's Gillespie integrator; the plan's
handoff (SSA for the low-copy first hour, CVODE thereafter) is implemented in
`run_hybrid`.

Everything here speaks in molecule counts. The model sets compartment volume to 1
so SBML concentrations are counts, and `OBSERVABLE_PREFIX` strips the `o_` we use
to keep observable names distinct from monomer names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

OBSERVABLE_PREFIX = "o_"

# PySB shells out to BioNetGen for network generation; it must be findable.
_BNG_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    ".venv", "Lib", "site-packages", "bionetgen", "bng-win",
)
os.environ.setdefault("BNGPATH", _BNG_DEFAULT)


@dataclass(frozen=True)
class RunSpec:
    """What the UI can vary. Hashable, so runs can be cached by spec."""

    moi: float = 10.0
    ifn_pretreatment: float = 0.0
    duration_s: float = 24 * 3600.0
    n_points: int = 289  # every 5 minutes over 24 h
    stochastic_until_s: float = 3600.0
    seed: int | None = None
    knockouts: tuple[str, ...] = field(default=())


@dataclass
class Trajectory:
    t: np.ndarray                      # seconds
    counts: dict[str, np.ndarray]      # observable name (prefix stripped) -> counts
    regime: list[str]                  # per timepoint: "ssa" or "ode"

    def at(self, i: int) -> dict[str, float]:
        return {k: float(v[i]) for k, v in self.counts.items()}


@lru_cache(maxsize=1)
def _sbml() -> str:
    from pysb.export import export

    from vervain.model import cell_v0

    return export(cell_v0.model, "sbml")


@lru_cache(maxsize=1)
def _observable_map() -> dict[str, str]:
    """PySB observable name -> SBML id, and back.

    PySB's SBML export anonymises everything: species become `__s0`, `__s1`, ...
    and observables become `__obs0`, `__obs1`, ... **in model.observables order**.
    Nothing downstream can interpret a frame without this mapping, so it is built
    once at export time and is the single place the naming convention is known.
    """
    from vervain.model import cell_v0

    return {
        obs.name: f"__obs{i}"
        for i, obs in enumerate(cell_v0.model.observables)
    }


@lru_cache(maxsize=1)
def _sbml_to_observable() -> dict[str, str]:
    """`__obsN` -> the readable species name used in state frames."""
    return {
        sbml_id: name[len(OBSERVABLE_PREFIX):] if name.startswith(OBSERVABLE_PREFIX) else name
        for name, sbml_id in _observable_map().items()
    }


def _load(spec: RunSpec):
    import roadrunner

    rr = roadrunner.RoadRunner(_sbml())
    rr.setIntegrator("cvode")
    _apply_spec(rr, spec)
    return rr


def _apply_spec(rr, spec: RunSpec) -> None:
    rr["MOI_virions"] = spec.moi
    rr["IFN_pretreatment"] = spec.ifn_pretreatment
    for name in spec.knockouts:
        # A knockout zeroes the production rate of the named antagonist.
        rr[name] = 0.0
    rr.reset()


def _selections() -> list[str]:
    return ["time"] + list(_observable_map().values())


def run_ode(spec: RunSpec) -> Trajectory:
    rr = _load(spec)
    rr.selections = _selections()
    rr.integrator.absolute_tolerance = 1e-8
    rr.integrator.relative_tolerance = 1e-8
    rr.integrator.setValue("stiff", True)
    result = rr.simulate(0.0, spec.duration_s, spec.n_points)
    return _to_trajectory(result, regime="ode")


def run_ssa(spec: RunSpec, duration_s: float | None = None, n_points: int = 61) -> Trajectory:
    rr = _load(spec)
    rr.selections = _selections()
    rr.setIntegrator("gillespie")
    if spec.seed is not None:
        rr.integrator.seed = spec.seed
    result = rr.simulate(0.0, duration_s or spec.stochastic_until_s, n_points)
    return _to_trajectory(result, regime="ssa")


def run_hybrid(spec: RunSpec) -> Trajectory:
    """SSA through the low-copy opening, then CVODE.

    The handoff is where a silent correctness bug is most likely to live, so the
    frame carries which regime produced it and `tests/` compares an SSA ensemble
    against SSA-throughout on the same window.
    """
    import roadrunner

    early = run_ssa(spec)
    handoff_state = {k: v[-1] for k, v in early.counts.items()}

    rr = roadrunner.RoadRunner(_sbml())
    rr.setIntegrator("cvode")
    _apply_spec(rr, spec)
    for species_id, value in _species_from_observables(handoff_state).items():
        try:
            rr[species_id] = value
        except Exception:
            # Observables that do not map 1:1 onto a species are recomputed by
            # the assignment rules; nothing to seed.
            pass
    rr.selections = _selections()
    rr.integrator.setValue("stiff", True)
    n_late = max(2, spec.n_points - len(early.t) + 1)
    late = rr.simulate(spec.stochastic_until_s, spec.duration_s, n_late)
    late_traj = _to_trajectory(late, regime="ode")

    return Trajectory(
        t=np.concatenate([early.t, late_traj.t[1:]]),
        counts={
            k: np.concatenate([early.counts[k], late_traj.counts[k][1:]])
            for k in early.counts
        },
        regime=early.regime + late_traj.regime[1:],
    )


def _species_from_observables(state: dict[str, float]) -> dict[str, float]:
    """Map observable values back onto SBML species ids for the SSA->ODE handoff.

    v0 monomers are site-free and one-to-one with species, so each observable
    corresponds to exactly one species. This function is the seam that has to be
    rewritten when monomers gain binding sites and observables become sums.
    """
    from vervain.model import cell_v0

    out: dict[str, float] = {}
    species_index = {str(s): i for i, s in enumerate(cell_v0.model.species)}
    for obs in cell_v0.model.observables:
        key = obs.name[len(OBSERVABLE_PREFIX):] if obs.name.startswith(OBSERVABLE_PREFIX) else obs.name
        if len(obs.species) != 1:
            continue
        out[f"__s{obs.species[0]}"] = state.get(key, 0.0)
    del species_index
    return out


def _to_trajectory(result, regime: str) -> Trajectory:
    lookup = _sbml_to_observable()
    colnames = [c.strip("[]") for c in result.colnames]
    t = np.asarray(result[:, 0], dtype=float)
    counts: dict[str, np.ndarray] = {}
    for i, name in enumerate(colnames):
        if name == "time":
            continue
        key = lookup.get(name, name)
        # Stochastic runs and loose ODE tolerances can dip a hair below zero;
        # counts are non-negative by definition.
        counts[key] = np.maximum(np.asarray(result[:, i], dtype=float), 0.0)
    return Trajectory(t=t, counts=counts, regime=[regime] * len(t))
