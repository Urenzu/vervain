"""Interferon sweep against the published targets. `make sweep`.

This is the fastest way to see whether a change to the model or the parameters
moved the outcome boundary or broke a validation target. It is deliberately a
printout rather than a test: v0 is uncalibrated, so most of these targets are
*not* met yet and asserting on them would mean a permanently red suite. They
become assertions during calibration.

Targets are from docs/validation.md.
"""

from __future__ import annotations

from vervain.solve.engine import RunSpec, run_ode

IFN_GRID = (0.0, 3e3, 7e3, 1e4, 1.5e4, 2e4, 5e4)


def _at(traj, hours: float) -> dict[str, float]:
    target = hours * 3600.0
    i = min(range(len(traj.t)), key=lambda j: abs(traj.t[j] - target))
    return traj.at(i)


def main() -> None:
    print("Vervain v0 — interferon pretreatment sweep (UNCALIBRATED)\n")
    print(
        f"{'IFN_pre':>9} {'DMV@10h':>9} {'gRNA@10h':>11} {'gRNA@24h':>11} "
        f"{'sgRNA/gRNA':>11} {'released@24h':>13}  outcome"
    )
    for ifn in IFN_GRID:
        traj = run_ode(RunSpec(ifn_pretreatment=ifn))
        h10, h24 = _at(traj, 10), _at(traj, 24)
        ratio = h24["sgRNA"] / max(h24["gRNA"], 1e-30)
        if h24["gRNA"] < 1.0:
            outcome = "abortive"
        elif h24["gRNA"] > 1e5:
            outcome = "productive (super-permissive)"
        else:
            outcome = "intermediate"
        print(
            f"{ifn:9.0f} {h10['DMV']:9.3g} {h10['gRNA']:11.3g} {h24['gRNA']:11.3g} "
            f"{ratio:11.2f} {h24['Vreleased']:13.3g}  {outcome}"
        )

    base10 = _at(run_ode(RunSpec(ifn_pretreatment=0.0)), 10)
    base24 = _at(run_ode(RunSpec(ifn_pretreatment=0.0)), 24)
    ratio24 = base24["sgRNA"] / max(base24["gRNA"], 1e-30)

    print("\nAgainst docs/validation.md, untreated cell:")
    for label, got, target, ok in (
        ("replication factories @10h", base10["DMV"], "~30 (smFISH)", 20 <= base10["DMV"] <= 45),
        ("gRNA @24h, super-permissive", base24["gRNA"], ">1e5 (smFISH)", base24["gRNA"] > 1e5),
        ("sgRNA/gRNA @24h", ratio24, "0.5-8 (smFISH)", 0.5 <= ratio24 <= 8),
        ("released virions @24h", base24["Vreleased"], "1e5-1e6 (estimated)",
         1e5 <= base24["Vreleased"] <= 1e6),
    ):
        print(f"  [{'PASS' if ok else 'MISS'}] {label:<28} {got:>10.3g}   target {target}")

    print(
        "\nMISS is expected at v0: every parameter is `estimated`/UNVERIFIED and "
        "nothing has\nbeen fitted yet. These become assertions during calibration."
    )


if __name__ == "__main__":
    main()
