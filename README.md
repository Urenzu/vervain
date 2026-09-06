# Vervain

Kinetic simulation of SARS-CoV-2 infection in a single ciliated human airway
epithelial cell, over ~24 simulated hours, with the innate immune response in the
loop. See [PLAN.md](PLAN.md) for the architecture and
[docs/validation.md](docs/validation.md) for what grades it.

> **v0 is uncalibrated.** Every parameter is `estimated` and unverified against
> literature. The model reproduces the *shape* of infection and a sharp
> productive/abortive boundary, but its numbers are not results. Calibration
> against the datasets in `docs/validation.md` is the next milestone.

## Running it

Two processes. Python solves; the browser draws.

```bash
# once
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cd web && npm install && cd ..

# terminal 1 — solver + websocket server
#   pre-solves the interferon slider grid on boot, so first start takes ~30 s
PYTHONPATH=sim .venv/Scripts/python.exe -m vervain.server.app

# terminal 2 — frontend
cd web && npm run dev      # http://localhost:5173
```

On Windows, `BNGPATH` must point at BioNetGen; `sim/vervain/solve/engine.py` sets
it automatically to the copy bundled by the `bionetgen` pip package.

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
