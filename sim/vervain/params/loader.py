"""Loads the parameter registry and hands values to PySB.

Model modules never write a bare rate constant. They call `p("kf_S_ACE2")`,
which resolves through the registry and fails loudly on an unregistered name.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).with_name("params.yaml")

CONFIDENCE_LEVELS = frozenset({"measured", "analogous", "inferred", "estimated"})


@dataclass(frozen=True)
class ParamRecord:
    name: str
    value: float
    units: str
    compartment: str
    confidence: str
    source: str
    note: str = ""

    @property
    def is_liability(self) -> bool:
        """True for values the sensitivity analysis must sweep."""
        return self.confidence == "estimated" or self.source == "UNVERIFIED"


@lru_cache(maxsize=1)
def registry() -> dict[str, ParamRecord]:
    raw = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError(f"unsupported params.yaml schema_version: {raw.get('schema_version')}")

    records: dict[str, ParamRecord] = {}
    for name, body in (raw.get("parameters") or {}).items():
        missing = {"value", "units", "compartment", "confidence", "source"} - body.keys()
        if missing:
            raise ValueError(f"parameter {name!r} is missing required fields: {sorted(missing)}")
        if body["confidence"] not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"parameter {name!r} has confidence {body['confidence']!r}; "
                f"expected one of {sorted(CONFIDENCE_LEVELS)}"
            )
        records[name] = ParamRecord(
            name=name,
            value=float(body["value"]),
            units=str(body["units"]),
            compartment=str(body["compartment"]),
            confidence=str(body["confidence"]),
            source=str(body["source"]),
            note=str(body.get("note", "")).strip(),
        )
    return records


def value(name: str) -> float:
    try:
        return registry()[name].value
    except KeyError:
        raise KeyError(
            f"{name!r} is not in the parameter registry. Add it to params.yaml with a "
            f"source and a confidence flag — model code may not carry bare constants."
        ) from None


def p(name: str):
    """Declare a PySB Parameter sourced from the registry.

    Must be called inside a PySB model-definition context, like `Parameter` itself.
    Idempotent: a registry parameter shared by several rules (a common turnover
    rate, say) resolves to the same Parameter object rather than a duplicate.
    """
    from pysb import Parameter
    from pysb.core import SelfExporter

    model = SelfExporter.default_model
    if model is not None and name in model.parameters.keys():
        return model.parameters[name]
    return Parameter(name, value(name))


def liabilities() -> list[ParamRecord]:
    """Parameters the productive/abortive result must not silently depend on."""
    return sorted(
        (r for r in registry().values() if r.is_liability),
        key=lambda r: r.name,
    )
