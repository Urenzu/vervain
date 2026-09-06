// Seam B. The ONLY place in this codebase where a position is invented.
//
// Contract: instance(counts, prev, seed) -> Scene, deterministic given its inputs.
// The solver ships counts; nothing about geometry crosses that boundary. Every
// coordinate below is illustrative and the UI says so.
//
// Two properties this has to preserve, or the scene reads as noise rather than
// biology:
//
//   1. Temporal coherence. A particle that exists in consecutive frames keeps its
//      identity and moves continuously. Achieved by giving each particle a fixed
//      "home" inside its compartment and animating a small deterministic jitter
//      around it, rather than re-scattering every frame.
//   2. Honest magnitude. Counts reach ~10^6; we cannot draw 10^6 spheres. Each
//      species gets a molecules-per-instance divisor, rounded to a power of ten
//      and surfaced in the legend, so what is on screen is a stated sample rather
//      than an implied one-to-one.

import type { Counts } from "../net/protocol";

export const MAX_INSTANCES_PER_SPECIES = 1200;

export interface Particle {
  home: [number, number, number];
  phase: [number, number, number];
  amp: number;
}

export interface SpeciesLayer {
  species: string;
  compartment: string;
  particles: Particle[];
  /** How many real molecules each drawn sphere stands for. Shown in the legend. */
  moleculesPerInstance: number;
  /** The modeled count. This is the real quantity; the geometry is not. */
  trueCount: number;
}

export interface Scene {
  tSec: number;
  layers: Map<string, SpeciesLayer>;
}

// ---------------------------------------------------------------- geometry --

// A columnar ciliated cell: apical (airway lumen) surface at +y.
const CELL_HALF_X = 1.0;
const CELL_HALF_Z = 1.0;
const APICAL_Y = 1.6;
const BASAL_Y = -1.6;
const NUCLEUS_CENTER: [number, number, number] = [0, -0.65, 0];
const NUCLEUS_R = 0.5;

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shellPoint(
  rnd: () => number,
  center: [number, number, number],
  rMin: number,
  rMax: number,
): [number, number, number] {
  const u = rnd() * 2 - 1;
  const theta = rnd() * Math.PI * 2;
  const r = rMin + rnd() * (rMax - rMin);
  const s = Math.sqrt(1 - u * u);
  return [
    center[0] + r * s * Math.cos(theta),
    center[1] + r * u,
    center[2] + r * s * Math.sin(theta),
  ];
}

function insideNucleus(p: [number, number, number]) {
  const dx = p[0] - NUCLEUS_CENTER[0];
  const dy = p[1] - NUCLEUS_CENTER[1];
  const dz = p[2] - NUCLEUS_CENTER[2];
  return dx * dx + dy * dy + dz * dz < NUCLEUS_R * NUCLEUS_R;
}

/** Sample a home position for a species in the compartment the model assigns it. */
function sampleHome(compartment: string, rnd: () => number): [number, number, number] {
  switch (compartment) {
    case "extracellular": {
      // Above the apical surface, in the airway lumen.
      return [
        (rnd() * 2 - 1) * CELL_HALF_X * 1.3,
        APICAL_Y + 0.15 + rnd() * 1.0,
        (rnd() * 2 - 1) * CELL_HALF_Z * 1.3,
      ];
    }
    case "plasma_membrane": {
      // Overwhelmingly the apical face, which is where ACE2 sits and where
      // virions engage a ciliated cell.
      return [
        (rnd() * 2 - 1) * CELL_HALF_X * 0.95,
        APICAL_Y - 0.02,
        (rnd() * 2 - 1) * CELL_HALF_Z * 0.95,
      ];
    }
    case "endosome": {
      return [
        (rnd() * 2 - 1) * CELL_HALF_X * 0.75,
        APICAL_Y - 0.25 - rnd() * 0.5,
        (rnd() * 2 - 1) * CELL_HALF_Z * 0.75,
      ];
    }
    case "dmv": {
      // Perinuclear, where replication organelles cluster.
      return shellPoint(rnd, NUCLEUS_CENTER, NUCLEUS_R + 0.12, NUCLEUS_R + 0.55);
    }
    case "ergic": {
      // Between the nucleus and the apical pole, biased toward the Golgi side.
      const p = shellPoint(rnd, NUCLEUS_CENTER, NUCLEUS_R + 0.08, NUCLEUS_R + 0.35);
      return [p[0], p[1] + 0.35, p[2]];
    }
    case "nucleus": {
      const p = shellPoint(rnd, NUCLEUS_CENTER, 0, NUCLEUS_R * 0.85);
      return p;
    }
    case "cytoplasm":
    default: {
      // Rejection-sample the cell interior, excluding the nucleus.
      for (let i = 0; i < 24; i++) {
        const p: [number, number, number] = [
          (rnd() * 2 - 1) * CELL_HALF_X * 0.9,
          BASAL_Y + 0.15 + rnd() * (APICAL_Y - BASAL_Y - 0.3),
          (rnd() * 2 - 1) * CELL_HALF_Z * 0.9,
        ];
        if (!insideNucleus(p)) return p;
      }
      return [0.8, 0.6, 0.0];
    }
  }
}

// ------------------------------------------------------------- the mapping --

/** Molecules per drawn sphere: a power of ten, so the legend reads cleanly. */
export function molecularScale(count: number): number {
  if (count <= MAX_INSTANCES_PER_SPECIES) return 1;
  const exponent = Math.ceil(Math.log10(count / MAX_INSTANCES_PER_SPECIES));
  return Math.pow(10, exponent);
}

export function createScene(): Scene {
  return { tSec: 0, layers: new Map() };
}

/**
 * Advance the scene to a new set of counts.
 *
 * Mutates and returns `prev` for allocation reasons — the pure-function contract
 * is about *determinism given (counts, prev, seed)*, not about immutability. A
 * fresh Scene plus the same inputs always yields the same output.
 */
export function instance(
  counts: Counts,
  compartments: Record<string, string>,
  species: string[],
  prev: Scene,
  tSec: number,
  seed = 1,
): Scene {
  prev.tSec = tSec;

  for (const name of species) {
    const trueCount = Math.max(0, counts[name] ?? 0);
    const compartment = compartments[name] ?? "cytoplasm";
    const perInstance = molecularScale(trueCount);
    const target = Math.min(
      MAX_INSTANCES_PER_SPECIES,
      Math.round(trueCount / perInstance),
    );

    let layer = prev.layers.get(name);
    if (!layer) {
      layer = {
        species: name,
        compartment,
        particles: [],
        moleculesPerInstance: perInstance,
        trueCount,
      };
      prev.layers.set(name, layer);
    }
    layer.moleculesPerInstance = perInstance;
    layer.trueCount = trueCount;
    layer.compartment = compartment;

    // Grow and shrink the pool from the end, so surviving particles keep their
    // index and therefore their identity across frames.
    const rnd = mulberry32(seed * 7919 + hash(name) + layer.particles.length);
    while (layer.particles.length < target) {
      layer.particles.push({
        home: sampleHome(compartment, rnd),
        phase: [rnd() * Math.PI * 2, rnd() * Math.PI * 2, rnd() * Math.PI * 2],
        amp: 0.012 + rnd() * 0.03,
      });
    }
    if (layer.particles.length > target) layer.particles.length = target;
  }

  return prev;
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic jitter around home. `wall` is wall-clock seconds, not sim time,
 *  so molecules keep moving while the simulation is paused. */
export function particlePosition(
  p: Particle,
  wall: number,
  out: [number, number, number],
): void {
  out[0] = p.home[0] + p.amp * Math.sin(wall * 0.9 + p.phase[0]);
  out[1] = p.home[1] + p.amp * Math.sin(wall * 1.1 + p.phase[1]);
  out[2] = p.home[2] + p.amp * Math.sin(wall * 0.7 + p.phase[2]);
}

export const CELL_GEOMETRY = {
  halfX: CELL_HALF_X,
  halfZ: CELL_HALF_Z,
  apicalY: APICAL_Y,
  basalY: BASAL_Y,
  nucleusCenter: NUCLEUS_CENTER,
  nucleusR: NUCLEUS_R,
};
