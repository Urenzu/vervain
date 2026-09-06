// Force against time for a steered run, with a marker tracking playback.
//
// The trajectory shows the complex coming apart; this says how hard it was.
// Neither is much use alone — a movie cannot be compared across variants, and
// a curve cannot be looked at. Tying the marker to the frame is the whole
// point: you watch the interface strain and see the curve spike at the moment
// it lets go.

import { useMemo } from "react";

import type { PullData } from "../traj/manifest";

interface Props {
  pull: PullData;
  /** Current playback time in picoseconds. */
  timePs: number;
}

const W = 280;
const H = 96;
const PAD_L = 4;
const PAD_R = 4;
const PAD_T = 8;
const PAD_B = 4;

export function ForceCurve({ pull, timePs }: Props) {
  const { path, xOf, yOf, maxForce, rupture } = useMemo(() => {
    const t0 = pull.timePs[0] ?? 0;
    const t1 = pull.timePs[pull.timePs.length - 1] ?? 1;
    const lo = Math.min(0, ...pull.forcePn);
    const hi = Math.max(...pull.forcePn);

    const x = (t: number) =>
      PAD_L + ((t - t0) / Math.max(1e-9, t1 - t0)) * (W - PAD_L - PAD_R);
    const y = (f: number) =>
      H - PAD_B - ((f - lo) / Math.max(1e-9, hi - lo)) * (H - PAD_T - PAD_B);

    // One point per sample would be a few thousand nodes of path data for a
    // 280px wide plot. Thin to roughly one per pixel column.
    const stride = Math.max(1, Math.floor(pull.timePs.length / (W * 2)));
    const points: string[] = [];
    for (let i = 0; i < pull.timePs.length; i += stride) {
      points.push(`${x(pull.timePs[i]).toFixed(1)},${y(pull.forcePn[i]).toFixed(1)}`);
    }

    return {
      path: `M ${points.join(" L ")}`,
      xOf: x,
      yOf: y,
      maxForce: hi,
      rupture: { x: x(pull.ruptureTimePs), y: y(pull.ruptureForcePn) },
    };
  }, [pull]);

  const cursorX = xOf(timePs);

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={
        `Pull force against time. Peak ${pull.ruptureForcePn.toFixed(0)} piconewtons ` +
        `at ${(pull.ruptureTimePs / 1000).toFixed(1)} nanoseconds.`
      }
      style={{ display: "block", overflow: "visible" }}
    >
      <line
        x1={PAD_L} y1={yOf(0)} x2={W - PAD_R} y2={yOf(0)}
        stroke="var(--color-rule)" strokeWidth="1"
      />
      <path d={path} fill="none" stroke="var(--color-muted)" strokeWidth="1" />

      {/* The peak: the number this run exists to produce. */}
      <line
        x1={PAD_L} y1={rupture.y} x2={W - PAD_R} y2={rupture.y}
        stroke="var(--color-accent)" strokeWidth="1" strokeDasharray="2 3" opacity="0.6"
      />
      <circle cx={rupture.x} cy={rupture.y} r="2.5" fill="var(--color-accent)" />

      {/* Playback position. */}
      <line
        x1={cursorX} y1={PAD_T - 4} x2={cursorX} y2={H - PAD_B}
        stroke="var(--color-ink)" strokeWidth="1"
      />
      <title>{`peak ${maxForce.toFixed(0)} pN`}</title>
    </svg>
  );
}
