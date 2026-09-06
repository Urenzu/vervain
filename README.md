# Vervain

Kinetic simulation of SARS-CoV-2 infection in a single ciliated human airway
epithelial cell, over ~24 simulated hours, with the innate immune response in the
loop. See [PLAN.md](PLAN.md) for the architecture and
[docs/validation.md](docs/validation.md) for what grades it.

> **v0 is uncalibrated.** Every parameter is `estimated` and unverified against
> literature. The model reproduces the *shape* of infection and a sharp
> productive/abortive boundary, but its numbers are not results. Calibration
> against the datasets in `docs/validation.md` is the next milestone.

## Platform

**The backend is Linux-native.** Verified on Ubuntu 26.04 with CPython 3.14 using
manylinux_2_28 wheels — no compiler and no system BioNetGen install required.
macOS runs the same code path. The source has no Windows-specific assumptions and
works there too, but Linux is the reference platform: it is what the numbers below
were produced on and what CI should run.

BioNetGen is a hard runtime dependency — PySB shells out to it to generate the
reaction network, and cannot produce ODEs without it. The `bionetgen` wheel ships
prebuilt binaries for all three platforms, and `ensure_bngpath()` in
`sim/vervain/solve/engine.py` selects the right one at import time. Set `BNGPATH`
only if you want to override that.

## Running it

```bash
make setup        # venv + Python deps; prints the BioNetGen path it resolved
make web-setup    # frontend deps

make serve        # terminal 1 — solver + websocket server (~30 s to pre-warm)
make web          # terminal 2 — http://localhost:5173
```

Other targets:

```bash
make test         # Python test suite, including the parameter-provenance guarantees
make typecheck    # frontend
make check        # both — what CI runs
make sweep        # interferon sweep printed against the published validation targets
```

Drag **interferon pretreatment**. Below ~10,000 ISG copies the cell goes
productive and sheds virions from the apical surface; above ~20,000 it clears the
genome and the infection is abortive. The boundary between those is sharp.

## Layout

```
sim/vervain/
  model/cell_v0.py      the kinetics: entry -> replication -> assembly -> egress,
                        plus RIG-I/IRF3/IFN/ISG and the nsp1 + ORF6 antagonists
  params/params.yaml    every constant, with units, compartment, confidence, source
  params/loader.py      p("name") - the only way a number reaches the model
  solve/engine.py       PySB -> BioNetGen -> SBML -> libRoadRunner (CVODE / Gillespie)
  server/protocol.py    Seam A: the state frame. No coordinate crosses this line.
  server/app.py         websocket streaming, run cache, slider pre-warm
  validate/sweep.py     the sweep, checked against docs/validation.md
web/src/
  net/                  protocol mirror + client
  instancer/            Seam B: counts -> positions. The ONLY place a position is invented.
  render/CellView.tsx   Three.js instanced spheres. Knows nothing above the instancer.
tests/                  parameter provenance guarantees
```

## The two rules

1. **Counts are modeled; positions are illustrative.** The solver emits molecule
   counts and simulated time, never a coordinate. Everything spatial is invented
   client-side by the instancer, and the UI says so on screen at all times.
2. **No bare constants.** Every rate lives in `params.yaml` with units, a
   compartment, a confidence flag and a source. `tests/test_param_provenance.py`
   fails the build if a model parameter is missing from the registry.

Both exist so the solver can later become spatially-resolved RDME and the renderer
can become raw WebGPU without either change touching the other.
