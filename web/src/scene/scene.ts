// The staged view of viral entry: real structures posed at real scale.
//
// This is a different kind of data from the trajectory, and the difference is
// the point. A trajectory is one system integrated forward in time — every
// position is a consequence of the previous one. A stage is an arrangement:
// coordinates that were measured, placed where the evidence says they go.
//
// Each group therefore carries an `evidence` field, and the viewer shows it.
// The alternative — drawing all of it in the same confident style — would make
// the posed parts look exactly as authoritative as the measured ones, which is
// how a scientific illustration turns into a decoration.

export const SCENE_SCHEMA = "vervain.scene/1";

/** How well we know that a thing is where it is drawn. */
export type Evidence = "measured" | "simulated" | "posed" | "interpolated";

export const EVIDENCE_NOTE: Record<Evidence, string> = {
  measured: "Deposited coordinates. This is the experiment.",
  simulated: "Motion came out of the integrator, not from an artist.",
  posed: "Real structures, plausible placement. No structure of this assembly exists.",
  interpolated: "A path drawn between two measured endpoints. The path is not measured.",
};

export interface SceneGroup {
  role: string;
  evidence: Evidence;
  source: string;
  offset: number;
  beadCount: number;
  color: string;
}

export interface SceneStage {
  id: string;
  title: string;
  caption: string;
  positions: string;
  beadCount: number;
  /** 1 for a static arrangement; more for a morph. */
  frameCount: number;
  extentNm: [number, number, number];
  spanNm: number;
  radiusNm: number[];
  groups: SceneGroup[];
}

export interface Scene {
  schema: string;
  palette: Record<string, string>;
  stages: SceneStage[];
}

export async function loadScene(): Promise<Scene> {
  const response = await fetch("/scene/scene.json", { cache: "no-cache" });
  if (!response.ok) {
    throw new Error(
      `no scene at /scene/scene.json (HTTP ${response.status}). ` +
        "Build it with: python -m vervain.scene",
    );
  }
  const scene = (await response.json()) as Scene;
  if (scene.schema !== SCENE_SCHEMA) {
    throw new Error(`scene schema ${scene.schema}, expected ${SCENE_SCHEMA}`);
  }
  return scene;
}

/** Decode one frame of a stage into nanometre coordinates. */
export function decodeStageFrame(
  raw: Int16Array,
  stage: SceneStage,
  frame: number,
  out: Float32Array,
): void {
  const { beadCount, extentNm } = stage;
  const base = Math.min(frame, stage.frameCount - 1) * beadCount * 3;
  for (let i = 0; i < beadCount; i++) {
    const src = base + i * 3;
    const dst = i * 3;
    out[dst] = (raw[src] / 32767) * extentNm[0];
    out[dst + 1] = (raw[src + 1] / 32767) * extentNm[1];
    out[dst + 2] = (raw[src + 2] / 32767) * extentNm[2];
  }
}

/** Distinct evidence classes present in a stage, in a stable order. */
export function evidenceOf(stage: SceneStage): Evidence[] {
  const order: Evidence[] = ["measured", "simulated", "interpolated", "posed"];
  const present = new Set(stage.groups.map((g) => g.evidence));
  return order.filter((e) => present.has(e));
}
