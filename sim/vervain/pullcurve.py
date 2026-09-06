"""Read GROMACS pull output and turn it into a force-extension curve.

The trajectory shows the complex coming apart; this is the number that says how
hard it was. Together they are the point of a steered run — a movie alone
cannot be compared across variants, and a curve alone cannot be looked at.

GROMACS writes two xvg files during a pull:

    pullx.xvg   the pull coordinate — here, the ACE2-to-RBD distance, in nm
    pullf.xvg   the force on that coordinate, in kJ/mol/nm

Force is converted to piconewtons, which is the unit single-molecule force
work is reported in and the one that makes the number comparable to an optical
trap or an AFM measurement.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 1 kJ/mol/nm expressed in piconewtons: 1000 / (6.02214076e23) / 1e-9 * 1e12.
KJ_PER_MOL_NM_TO_PN = 1.66053907


@dataclass
class PullCurve:
    time_ps: list[float]
    extension_nm: list[float]
    force_pn: list[float]
    rupture_force_pn: float
    rupture_time_ps: float
    rate_nm_per_ns: float

    @property
    def rupture_extension_nm(self) -> float:
        index = min(
            range(len(self.time_ps)),
            key=lambda i: abs(self.time_ps[i] - self.rupture_time_ps),
        )
        return self.extension_nm[index]


def read_xvg(path: Path) -> tuple[list[float], list[float]]:
    """First two numeric columns of an xvg. Comments start with # or @."""
    xs: list[float] = []
    ys: list[float] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] in "#@&":
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
        except ValueError:
            continue
    return xs, ys


def _smooth(values: list[float], window: int) -> list[float]:
    """Centred moving average.

    Instantaneous pull force is dominated by thermal noise — at these
    magnitudes the frame-to-frame scatter is larger than the signal, and the
    single largest raw sample is a noise spike rather than the rupture. The
    peak is read off a smoothed curve for that reason.
    """
    if window < 2 or len(values) < window:
        return list(values)
    half = window // 2
    out: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def find_outputs(work: Path) -> tuple[Path, Path] | None:
    """Locate the pull xvg pair.

    `mdrun -deffnm pull` writes `pull_pullf.xvg`, not `pullf.xvg` — the deffnm
    prefixes every output including these. Both spellings are checked so the
    lookup does not depend on how the run happened to be invoked.
    """
    for force_name, coord_name in (
        ("pull_pullf.xvg", "pull_pullx.xvg"),
        ("pullf.xvg", "pullx.xvg"),
    ):
        force, coord = work / force_name, work / coord_name
        if force.exists() and coord.exists():
            return force, coord
    return None


def read_pull(work: Path, rate_nm_per_ns: float, smooth_window: int = 21) -> PullCurve | None:
    found = find_outputs(work)
    if found is None:
        return None
    force_file, coord_file = found

    ft, force_raw = read_xvg(force_file)
    xt, extension = read_xvg(coord_file)
    if not ft or not xt:
        return None

    # The two files are written on the same schedule, but trust nothing: a
    # mismatched length would silently pair a force with the wrong extension.
    n = min(len(ft), len(xt))
    ft, force_raw, extension = ft[:n], force_raw[:n], extension[:n]

    force_pn = [f * KJ_PER_MOL_NM_TO_PN for f in force_raw]
    smoothed = _smooth(force_pn, smooth_window)

    peak = max(range(len(smoothed)), key=lambda i: smoothed[i])
    return PullCurve(
        time_ps=ft,
        extension_nm=extension,
        force_pn=force_pn,
        rupture_force_pn=smoothed[peak],
        rupture_time_ps=ft[peak],
        rate_nm_per_ns=rate_nm_per_ns,
    )


def rate_from_mdp(mdp: Path) -> float:
    """Pull rate in nm/ns, read from the mdp that produced the run."""
    for raw in mdp.read_text(encoding="utf-8").splitlines():
        line = raw.split(";", 1)[0]
        if "pull-coord1-rate" in line and "=" in line:
            try:
                return float(line.split("=", 1)[1].strip()) * 1000.0  # nm/ps -> nm/ns
            except ValueError:
                break
    return 0.0
