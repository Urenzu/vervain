"""Report what this machine's toolchain can actually do.

Every line here exists because getting it wrong costs days rather than minutes.
A GROMACS built without GPU support runs; it just runs an order of magnitude
slower, and the only way you find out is by benchmarking something you assumed
was fine. Same for SIMD: the Ubuntu package is compiled to SSE4.1 for
portability and will happily use half of an AVX2 machine forever without
complaining.

    python -m vervain.doctor
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

OK, WARN, BAD = "ok", "warn", "bad"
MARK = {OK: "+", WARN: "!", BAD: "x"}


def _run(cmd: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def _line(status: str, label: str, detail: str) -> None:
    print(f"  {MARK[status]} {label:<22} {detail}")


def check_platform() -> None:
    print("platform")
    system = platform.system()
    is_wsl = "microsoft" in platform.release().lower()
    if system == "Linux" and is_wsl:
        _line(OK, "os", f"WSL — {platform.release()}")
    elif system == "Linux":
        _line(OK, "os", f"Linux — {platform.release()}")
    else:
        _line(WARN, "os", f"{system} — the pipeline expects WSL or Linux; "
                          "GROMACS and martinize2 assume a POSIX toolchain")
    _line(OK, "python", f"{sys.version.split()[0]}  ({sys.executable})")


def check_gpu() -> None:
    print("\ngpu")
    if not shutil.which("nvidia-smi"):
        _line(BAD, "nvidia-smi", "not found — no GPU visible from here")
        return
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,compute_cap",
                "--format=csv,noheader"]).strip()
    if not out:
        _line(BAD, "nvidia-smi", "present but returned nothing")
        return
    for row in out.splitlines():
        name, mem, cap = (part.strip() for part in row.split(","))
        mib = int(mem.split()[0]) if mem.split()[0].isdigit() else 0
        # 6 GB is a real ceiling for MARTINI. A spike plus a membrane patch
        # fits; a virion does not, and finding that out at run time is a
        # wasted afternoon of system building.
        status = OK if mib >= 8192 else WARN
        note = "" if status == OK else "  (tight — sizes systems to ~1M beads)"
        _line(status, "device", f"{name}, {mem}, sm_{cap.replace('.', '')}{note}")


def check_gromacs() -> None:
    print("\ngromacs")
    # Prefer our own build over whatever apt put on PATH: the packaged binary
    # is the one with GPU support disabled, and it shadows nothing, so a bare
    # `which gmx` silently reports the slow one.
    built = Path.home() / "opt" / "gromacs" / "bin" / "gmx"
    gmx = (
        os.environ.get("VERVAIN_GMX")
        or (str(built) if built.exists() else None)
        or shutil.which("gmx")
        or shutil.which("gmx_mpi")
    )
    if not gmx:
        _line(BAD, "gmx", "not found — run: make gromacs")
        return

    out = _run([gmx, "--version"], timeout=60)
    if not out:
        _line(BAD, "gmx", f"{gmx} did not respond to --version")
        return

    version = simd = gpu = ""
    for raw in out.splitlines():
        low = raw.lower()
        if low.startswith("gromacs version"):
            version = raw.split(":", 1)[1].strip()
        elif low.startswith("gpu support"):
            gpu = raw.split(":", 1)[1].strip()
        elif low.startswith("simd instructions"):
            simd = raw.split(":", 1)[1].strip()

    _line(OK, "binary", gmx)
    _line(OK, "version", version or "unknown")

    if gpu.lower().startswith("cuda"):
        _line(OK, "gpu offload", gpu)
    else:
        _line(BAD, "gpu offload", f"{gpu or 'unknown'} — production runs will be "
                                  "CPU-only. Run: make gromacs")

    # AVX2_256 on Zen/Skylake and later; AVX_512 on some Xeons. SSE4.1 means
    # the binary was built for portability, not for this machine.
    if simd.startswith(("AVX2", "AVX_512", "AVX512")):
        _line(OK, "simd", simd)
    else:
        _line(WARN, "simd", f"{simd or 'unknown'} — roughly half throughput on an "
                            "AVX2 machine. Run: make gromacs")


def check_python_deps() -> None:
    print("\npython packages")
    wanted = [
        ("vermouth", "martinize2 — atomistic to coarse-grained"),
        ("MDAnalysis", "trajectory handling"),
        ("gemmi", "structure surgery: grafting, superposition"),
        ("numpy", ""),
        ("yaml", "catalogue parsing"),
    ]
    import importlib.util
    for module, purpose in wanted:
        found = importlib.util.find_spec(module) is not None
        detail = purpose if found else f"missing — run: make setup   ({purpose})"
        _line(OK if found else WARN, module, detail)


def check_structures() -> None:
    print("\nstructures")
    from vervain.structures import STRUCTURE_DIR, read_catalogue, structure_path

    catalogue = read_catalogue()
    if not catalogue:
        _line(BAD, "catalogue", "structures.yaml parsed to nothing")
        return

    present = [p for p in catalogue if structure_path(p).exists()]
    missing = [p for p in catalogue if p not in present]
    _line(OK, "catalogue", f"{len(catalogue)} entries")
    if missing:
        _line(WARN, "downloaded", f"{len(present)}/{len(catalogue)} — missing "
                                  f"{', '.join(missing)}. Run: make structures")
    else:
        _line(OK, "downloaded", f"{len(present)}/{len(catalogue)} in {STRUCTURE_DIR}")


def main() -> int:
    print("vervain doctor\n" + "=" * 60)
    check_platform()
    check_gpu()
    check_gromacs()
    check_python_deps()
    try:
        check_structures()
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
        print(f"  {MARK[BAD]} structures            {exc}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
