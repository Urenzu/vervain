"""The structural guarantee behind the provenance claim.

If these pass, no number reaches the solver without a registry entry carrying
units, a compartment, a confidence flag, and a source field.
"""

import pytest

from vervain.params.loader import CONFIDENCE_LEVELS, liabilities, registry, value


def test_registry_loads_and_validates():
    records = registry()
    assert records, "parameter registry is empty"
    for name, rec in records.items():
        assert rec.confidence in CONFIDENCE_LEVELS, name
        assert rec.units, f"{name} has no units"
        assert rec.compartment, f"{name} has no compartment"
        assert rec.source, f"{name} has no source field"


def test_unregistered_parameter_is_refused():
    with pytest.raises(KeyError, match="not in the parameter registry"):
        value("kf_entirely_made_up")


def test_liabilities_are_enumerable():
    """The sensitivity sweep needs this list; it must never silently be empty
    while unverified values remain."""
    names = {r.name for r in liabilities()}
    unverified = {n for n, r in registry().items() if r.source == "UNVERIFIED"}
    assert unverified <= names


# Run conditions, not biology: these are set per-run by the UI and have no
# literature source by construction. Everything else must be registered.
RUN_INPUTS = {"MOI_virions", "IFN_pretreatment"}


@pytest.mark.parametrize("model_module", ["vervain.model.cell_v0"])
def test_every_model_parameter_is_registered(model_module):
    """The rule that actually forbids bare constants.

    Walks the assembled PySB model and asserts every Parameter name appears in
    the registry. A rate constant typed directly into a Rule fails here.
    """
    import importlib

    model = importlib.import_module(model_module).model
    unregistered = sorted(
        p.name
        for p in model.parameters
        if p.name not in registry() and p.name not in RUN_INPUTS
    )
    assert not unregistered, f"parameters missing from params.yaml: {unregistered}"


def test_v0_is_honestly_flagged_as_uncalibrated():
    """v0 claims nothing. If a parameter ever gets a real source, this test is the
    reminder to update the UI banner and README rather than leave them stale."""
    records = registry()
    sourced = {n for n, r in records.items() if r.source != "UNVERIFIED"}
    assert not sourced, (
        f"{sorted(sourced)} now carry sources — update the 'v0 uncalibrated' "
        "banner in server/app.py, README.md and params.yaml, then narrow this test"
    )
