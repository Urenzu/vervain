// Mirror of sim/vervain/server/protocol.py. Seam A.
// No coordinate appears in this file. If one ever does, the seam has leaked.

export const SCHEMA = "vervain.frame/1";

export type Counts = Record<string, number>;

export interface StateFrame {
  type: "frame";
  schema: string;
  t_sec: number;
  counts: Counts;
  regime: "ssa" | "ode";
  outcome_flags: Record<string, boolean>;
}

export interface RunMeta {
  type: "meta";
  schema: string;
  rendered_species: string[];
  compartment: Record<string, string>;
  duration_s: number;
  n_frames: number;
  ifn_pretreatment: number;
  moi: number;
  provenance: {
    counts: string;
    positions: string;
    calibration: string;
  };
}

export type ServerMessage = StateFrame | RunMeta | { type: "done" };

export interface RunRequest {
  type: "run";
  ifn: number;
  moi: number;
  speed: number; // simulated seconds per wall-clock second
}
