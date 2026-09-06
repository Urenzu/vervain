# Vervain

Coarse-grained molecular dynamics of SARS-CoV-2 entry at an airway cell
surface, rendered in the browser.

Every position on screen comes out of an integrator. Nothing is animated.

## What it is

A virion meeting a cell is one of the most-illustrated events in biology and
almost none of those illustrations are simulations. They are authored — the
spikes are rigid, the surface is bare, the motion is eased. Real spikes wave on
three-hinged stalks, they are buried under a glycan shield that is roughly 40%
of their surface area, and at that scale nothing glides because viscosity
dominates inertia.

This simulates that instead of drawing it.

## What it is not

Entry end to end. MARTINI reaches microseconds; entry takes seconds. The parts
that fit inside a microsecond are simulated unbiased, the parts that do not are
steered, and the difference is labelled. See [docs/pipeline.md](docs/pipeline.md)
for the timescale table and what it rules out.

## Layout

    sim/vervain/        the simulation pipeline (Python, runs under WSL)
      structures.yaml   experimental structures, with sources and caveats
      structures.py     fetch from RCSB, report chains / gaps / glycans
    scripts/            environment setup
    web/                the viewer (React, Three.js)
    docs/pipeline.md    stages, timescales, and the known liabilities

## Getting started

The pipeline runs under WSL. GROMACS and martinize2 assume a POSIX toolchain.

    make setup          # venv and Python dependencies
    make catalogue      # what structures the project builds on
    make structures     # download them
    make doctor         # what this machine's toolchain can actually do

For production runs you need a GROMACS built for this hardware:

    make gromacs

Ubuntu's packaged `gromacs` is compiled with GPU support disabled and SIMD
pinned to SSE4.1. It is fine for assembling and minimising a system and close
to useless for a trajectory.

## Provenance

Nothing enters the pipeline without a source and a stated confidence —
structures, lipid compositions, force-field choices alike. Inputs that are
currently guesses are written down as liabilities in `structures.yaml` under
`open_questions` rather than quietly defaulted.
