// The contract between the MD pipeline and the viewer.
//
// A trajectory cannot be shipped whole. A 400k-bead system over 500 frames is
// 2.4 GB as float32 xyz. Two things bring that down to something a browser can
// hold: water is dropped at export (it is ~70% of the beads and nothing is
// learned by drawing it), and coordinates are quantised to int16 against the
// box. What survives — protein beads and lipid headgroups — is closer to 20k
// beads, or ~60 MB over 500 frames.
//
// Positions are stored as one interleaved int16 block per frame:
//   frame f, bead i  ->  offset ((f * beadCount) + i) * 3
// Decode with:  nm = (raw / 32767) * extentNm[axis]
//
// The scale is the molecule's own half-extent, not the box's. Quantising
// against the box looks equivalent and is not: a solute longer than the box
// half-width has its extremities clipped flat onto the edge, and the periodic
// box here is smaller in its short axis than ACE2 plus the RBD end to end.

export const SCHEMA = "vervain.traj/1";

/** How beads are coloured. Each says something different about the same frame. */
export type ColorMode = "chain" | "chemistry" | "flexibility";

export interface ChemistryClass {
  label: string;
  color: string;
}

export interface BeadGroup {
  name: string;
  description: string;
  /** Rendering colour. Groups are the unit of visibility and colour, not species. */
  color: string;
  /** How many beads this group owns. */
  beadCount: number;
  /** Index of this group's first bead within a frame. */
  offset: number;
  /** Fallback radius in nm, used only if per-bead radii are absent. */
  radiusNm: number;
}

/** Present only for a steered run. Force is in piconewtons, the unit
 *  single-molecule force work reports, so the number is comparable to an
 *  optical trap or an AFM pull rather than only to itself. */
export interface PullData {
  rateNmPerNs: number;
  ruptureForcePn: number;
  ruptureTimePs: number;
  ruptureExtensionNm: number;
  timePs: number[];
  extensionNm: number[];
  forcePn: number[];
}

export interface Manifest {
  schema: string;
  /** Simulated time between stored frames. Not wall-clock, not timestep. */
  frameIntervalPs: number;
  frameCount: number;
  /** Total beads per frame, after water is dropped. */
  beadCount: number;
  /** Periodic box in nm. Informational — the simulation cell, not the scale. */
  boxNm: [number, number, number];
  /** Half-extent the coordinates were quantised against, per axis, in nm. */
  extentNm: [number, number, number];
  forceField: string;
  /** Path to the int16 position block, relative to the manifest. */
  positions: string;
  groups: BeadGroup[];

  /** Per bead, in trajectory order. Read from the Martini topology: the force
   *  field defines three bead sizes and a chemical class per type, and drawing
   *  every bead identically throws both away. */
  radiusNm: number[];
  chemistry: string[];
  chemistryPalette: Record<string, ChemistryClass>;
  /** Root-mean-square fluctuation per bead, in nm, measured from this run
   *  after superposition. This is what distinguishes a rigid core from a
   *  mobile loop when every frame otherwise looks alike. */
  rmsfNm: number[];

  /** Absent for an equilibrium trajectory. */
  pull?: PullData;
}

/** Rigid to mobile. Deliberately not a rainbow: a sequential quantity needs a
 *  ramp that orders, and hue alone does not. Lightness climbs monotonically. */
const FLEX_RAMP: Array<[number, number, number]> = [
  [0.16, 0.20, 0.38],   // deep indigo — held in place
  [0.20, 0.52, 0.66],
  [0.42, 0.78, 0.66],
  [0.95, 0.78, 0.35],
  [1.0, 0.53, 0.24],    // hot amber — flapping
];

export function flexColor(value: number, lo: number, hi: number): [number, number, number] {
  const t = hi > lo ? Math.min(1, Math.max(0, (value - lo) / (hi - lo))) : 0;
  const scaled = t * (FLEX_RAMP.length - 1);
  const i = Math.min(FLEX_RAMP.length - 2, Math.floor(scaled));
  const f = scaled - i;
  const a = FLEX_RAMP[i];
  const b = FLEX_RAMP[i + 1];
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f];
}

const MANIFEST_URL = "/traj/manifest.json";

export async function loadManifest(): Promise<Manifest> {
  let response: Response;
  try {
    response = await fetch(MANIFEST_URL);
  } catch {
    throw new Error(`Could not reach ${MANIFEST_URL}.`);
  }
  if (!response.ok) {
    throw new Error(
      `No trajectory at ${MANIFEST_URL} (HTTP ${response.status}). ` +
        `Nothing has been exported yet.`,
    );
  }

  const manifest = (await response.json()) as Manifest;
  if (manifest.schema !== SCHEMA) {
    throw new Error(
      `Trajectory schema is ${manifest.schema}; this viewer reads ${SCHEMA}.`,
    );
  }
  return manifest;
}

/** Decode one frame of quantised coordinates into a Float32Array of nm. */
export function decodeFrame(
  raw: Int16Array,
  manifest: Manifest,
  frame: number,
  out: Float32Array,
): void {
  const { beadCount, extentNm } = manifest;
  const base = frame * beadCount * 3;
  for (let i = 0; i < beadCount; i++) {
    const src = base + i * 3;
    const dst = i * 3;
    out[dst] = (raw[src] / 32767) * extentNm[0];
    out[dst + 1] = (raw[src + 1] / 32767) * extentNm[1];
    out[dst + 2] = (raw[src + 2] / 32767) * extentNm[2];
  }
}
