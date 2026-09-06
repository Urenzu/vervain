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
// Decode with:  nm = (raw / 32767) * 0.5 * boxLength + 0.5 * boxLength

export const SCHEMA = "vervain.traj/1";

export interface BeadGroup {
  name: string;
  description: string;
  /** Rendering colour. Groups are the unit of visibility and colour, not species. */
  color: string;
  /** How many beads this group owns. */
  beadCount: number;
  /** Index of this group's first bead within a frame. */
  offset: number;
  /** Bead radius in nm. MARTINI beads are ~0.26 nm; larger for coarser types. */
  radiusNm: number;
}

export interface Manifest {
  schema: string;
  /** Simulated time between stored frames. Not wall-clock, not timestep. */
  frameIntervalPs: number;
  frameCount: number;
  /** Total beads per frame, after water is dropped. */
  beadCount: number;
  /** Periodic box in nm, used to decode the quantised coordinates. */
  boxNm: [number, number, number];
  forceField: string;
  /** Path to the int16 position block, relative to the manifest. */
  positions: string;
  groups: BeadGroup[];
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
  const { beadCount, boxNm } = manifest;
  const base = frame * beadCount * 3;
  for (let i = 0; i < beadCount; i++) {
    const src = base + i * 3;
    const dst = i * 3;
    // Centre on the box so the camera orbits the system rather than a corner.
    out[dst] = (raw[src] / 32767) * 0.5 * boxNm[0];
    out[dst + 1] = (raw[src + 1] / 32767) * 0.5 * boxNm[1];
    out[dst + 2] = (raw[src + 2] / 32767) * 0.5 * boxNm[2];
  }
}
