"""Websocket server: streams StateFrames to the frontend.

Client -> server messages:
    {"type": "run", "ifn": <float>, "moi": <float>, "speed": <float>}
        Solve (or hit cache) and stream the whole trajectory.
    {"type": "seek", "t_sec": <float>}   -- not yet implemented client-side

Server -> client messages:
    {"type": "meta",  ...}     once per run: species list, compartments, duration
    {"type": "frame", ...}     a StateFrame
    {"type": "done"}

Runs are cached by RunSpec so dragging the slider back over a value it has already
seen is instant. The IFN grid is pre-warmed at startup for the same reason: the
slider has to feel immediate, and solving 24 h on drag does not.
"""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

from vervain.server.protocol import (
    COMPARTMENT,
    RENDERED_SPECIES,
    SCHEMA,
    StateFrame,
    outcome_flags,
)
from vervain.solve.engine import RunSpec, Trajectory, run_ode

log = logging.getLogger("vervain.server")

# IFN pretreatment values pre-solved at startup. Chosen to straddle the outcome
# boundary densely, since that is the part of the slider people will drag over.
IFN_GRID = [0, 1e3, 2e3, 3e3, 5e3, 7e3, 9e3, 1.1e4, 1.3e4, 1.5e4, 2e4, 3e4, 5e4]

_cache: dict[RunSpec, Trajectory] = {}


def solve(spec: RunSpec) -> Trajectory:
    if spec not in _cache:
        log.info("solving %s", spec)
        _cache[spec] = run_ode(spec)
    return _cache[spec]


def _nearest_grid_ifn(value: float) -> float:
    return min(IFN_GRID, key=lambda g: abs(g - value))


async def prewarm() -> None:
    """Solve the slider grid up front so dragging never waits on CVODE."""
    loop = asyncio.get_running_loop()
    for ifn in IFN_GRID:
        await loop.run_in_executor(None, solve, RunSpec(ifn_pretreatment=ifn))
    log.info("prewarmed %d trajectories", len(IFN_GRID))


async def _stream(ws, spec: RunSpec, speed: float) -> None:
    loop = asyncio.get_running_loop()
    traj = await loop.run_in_executor(None, solve, spec)

    await ws.send(json.dumps({
        "type": "meta",
        "schema": SCHEMA,
        "rendered_species": list(RENDERED_SPECIES),
        "compartment": COMPARTMENT,
        "duration_s": float(traj.t[-1]),
        "n_frames": len(traj.t),
        "ifn_pretreatment": spec.ifn_pretreatment,
        "moi": spec.moi,
        # Stated in the payload, not just in the docs: the client renders this
        # into the UI so a viewer cannot mistake positions for modeled quantities.
        "provenance": {
            "counts": "modeled",
            "positions": "illustrative",
            "calibration": "v0 uncalibrated - all parameters estimated",
        },
    }))

    # Wall-clock pacing: `speed` is simulated seconds per wall second.
    frame_dt = (traj.t[1] - traj.t[0]) if len(traj.t) > 1 else 1.0
    sleep_s = max(0.0, float(frame_dt) / max(speed, 1e-9))

    for i in range(len(traj.t)):
        counts = traj.at(i)
        frame = StateFrame(
            t_sec=float(traj.t[i]),
            counts=counts,
            regime=traj.regime[i],
            outcome_flags=outcome_flags(counts),
        )
        await ws.send(json.dumps({"type": "frame", **frame.to_dict()}))
        if sleep_s:
            await asyncio.sleep(sleep_s)

    await ws.send(json.dumps({"type": "done"}))


async def handler(ws) -> None:
    log.info("client connected")
    task: asyncio.Task | None = None
    try:
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") != "run":
                continue
            # A new run supersedes whatever is streaming — this is what makes the
            # slider feel live rather than queueing up stale trajectories.
            if task and not task.done():
                task.cancel()
            spec = RunSpec(
                moi=float(msg.get("moi", 10.0)),
                ifn_pretreatment=_nearest_grid_ifn(float(msg.get("ifn", 0.0))),
            )
            task = asyncio.create_task(_stream(ws, spec, float(msg.get("speed", 3600.0))))
    except websockets.ConnectionClosed:
        pass
    finally:
        if task and not task.done():
            task.cancel()
        log.info("client disconnected")


async def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log.info("prewarming solver cache (first run compiles the SBML model)...")
    await prewarm()
    async with websockets.serve(handler, host, port, max_size=None):
        log.info("vervain server listening on ws://%s:%d", host, port)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
