#!/usr/bin/env bash
# Python environment for the pipeline, inside WSL.
#
# The venv lives on the Linux filesystem, not in the repo. The repo sits on
# /mnt/c, and every file operation there crosses the 9p boundary into Windows —
# creating a venv takes minutes instead of seconds, and importing from one is
# slow for the life of the project. A symlink in the repo keeps it findable.
#
# The same applies to trajectories: write them under $VERVAIN_DATA on the Linux
# side, not into the repo, or GROMACS will spend its time on I/O.
#
#   bash scripts/setup-env.sh

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# WSL inherits Windows' HOME, which arrives mangled ("C:Userslevir") and sends
# pip's cache somewhere that does not exist. Pin it to the real Linux home.
if [[ ! -d "${HOME:-/nonexistent}" ]]; then
  HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"
  export HOME
fi

VENV="${VENV:-$HOME/.venvs/vervain}"
PY="$VENV/bin/python"
LINK="$REPO/.venv-wsl"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "creating $VENV"
mkdir -p "$(dirname "$VENV")"
python3 -m venv "$VENV"
ln -sfn "$VENV" "$LINK"
"$PY" -m pip install -q --upgrade pip

say "installing requirements"
"$PY" -m pip install -q -r "$REPO/requirements.txt"

say "verifying"
"$PY" - <<'PROBE'
import importlib

for module, label in [
    ("gemmi", "gemmi"),
    ("numpy", "numpy"),
    ("MDAnalysis", "MDAnalysis"),
    ("vermouth", "vermouth"),
    ("yaml", "pyyaml"),
]:
    try:
        mod = importlib.import_module(module)
        version = getattr(mod, "__version__", "?")
        print(f"  + {label:<14} {version}")
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        print(f"  x {label:<14} {type(exc).__name__}: {exc}")
PROBE

say "done"
echo "venv:      $VENV"
echo "symlinked: $LINK"
echo
echo "Use it with:  PYTHONPATH=sim ./.venv-wsl/bin/python -m vervain.doctor"
