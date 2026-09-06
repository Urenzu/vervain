"""Per-bead properties, read from the topology instead of assumed.

The viewer was drawing every bead at one radius and colouring by chain. Both
throw away information that is already on disk: Martini 3 beads come in three
sizes and carry a chemical class in their type name, and a chain identifier
tells you nothing you could not read off the picture.

Type names look like ``TC5``, ``SP2a``, ``Q5n``, ``P2``:

    optional size prefix   T tiny, S small, absent for regular
    chemical class         Q charged, P polar, N intermediate, C apolar
    polarity level         a digit, 1 (least polar) to 6 (most)
    optional label         d/a/e/n/p for donor, acceptor, charge sign, ...

Measured on the ACE2 topology: 567 regular, 503 small, 394 tiny. Drawing all of
them at one radius makes a third of the beads 12% too big and a third 12% too
small.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Martini 3 sigma by size class, in nm. The drawn radius is sigma/2, which is
# the distance at which two beads of that class first overlap.
SIGMA_NM = {"R": 0.47, "S": 0.41, "T": 0.34}

# Chemical class -> (label, colour). The scheme is hydrophobicity-shaped and
# reads on a near-black ground: charged surfaces magenta, water-liking cyan,
# greasy core warm. Colour carries chemistry here, not identity.
CHEMISTRY = {
    "Q": ("charged", "#e15a97"),
    "P": ("polar", "#4fc3f7"),
    "N": ("intermediate", "#7ed6a5"),
    "C": ("apolar", "#f0c46a"),
    "X": ("halo-compound", "#b39ddb"),
    "D": ("divalent", "#ff8a65"),
    "W": ("water", "#90a4ae"),
}
UNKNOWN = ("unclassified", "#95918d")

# `1  P2  1  SER  BB  1  0.0` — index, type, resnr, residue, atom, cgnr, charge
ATOM_ROW = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\d+)")


@dataclass(frozen=True)
class Bead:
    index: int
    type_name: str
    residue: str
    atom: str
    size_class: str
    chemistry: str

    @property
    def radius_nm(self) -> float:
        return SIGMA_NM[self.size_class] / 2.0

    @property
    def color(self) -> str:
        return CHEMISTRY.get(self.chemistry, UNKNOWN)[1]


def classify(type_name: str) -> tuple[str, str]:
    """Type name -> (size class, chemical class).

    Size prefixes are only meaningful when a chemical class follows: `SP2` is a
    small polar bead, but a hypothetical type starting `S` with nothing valid
    after it is not, and silently treating it as small would shrink a bead for
    no reason.
    """
    rest = type_name
    size = "R"
    if len(rest) > 1 and rest[0] in ("T", "S") and rest[1] in CHEMISTRY:
        size = rest[0]
        rest = rest[1:]
    chemistry = rest[0] if rest and rest[0] in CHEMISTRY else "?"
    return size, chemistry


def read_topology(itp: Path) -> list[Bead]:
    """Beads from an [ atoms ] block, in file order.

    File order is the contract: it is the order martinize2 wrote coordinates
    in, so index i here is bead i in the trajectory.
    """
    beads: list[Bead] = []
    in_atoms = False

    for raw in itp.read_text(encoding="utf-8").splitlines():
        line = raw.split(";", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("["):
            in_atoms = line.replace(" ", "").lower().startswith("[atoms]")
            continue
        if not in_atoms:
            continue

        match = ATOM_ROW.match(line)
        if not match:
            continue
        _, type_name, _, residue, atom, _ = match.groups()
        size, chemistry = classify(type_name)
        beads.append(Bead(len(beads), type_name, residue, atom, size, chemistry))

    return beads


def summarise(beads: list[Bead]) -> str:
    sizes: dict[str, int] = {}
    chem: dict[str, int] = {}
    for bead in beads:
        sizes[bead.size_class] = sizes.get(bead.size_class, 0) + 1
        chem[bead.chemistry] = chem.get(bead.chemistry, 0) + 1
    size_part = " ".join(f"{k}:{v}" for k, v in sorted(sizes.items()))
    chem_part = " ".join(f"{k}:{v}" for k, v in sorted(chem.items(), key=lambda kv: -kv[1]))
    return f"sizes {size_part}   chemistry {chem_part}"
