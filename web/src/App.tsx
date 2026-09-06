import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { VervainClient, type ConnectionStatus } from "./net/client";
import type { RunMeta, StateFrame } from "./net/protocol";
import { createScene, instance, type Scene } from "./instancer/instancer";
import { CellView, SPECIES_STYLE } from "./render/CellView";

const IFN_MAX = 50000;

function fmtCount(n: number): string {
  if (n <= 0) return "0";
  if (n < 1) return n.toExponential(1);
  if (n < 1000) return n.toFixed(n < 10 ? 1 : 0);
  if (n < 1e6) return `${(n / 1e3).toFixed(1)}k`;
  return `${(n / 1e6).toFixed(2)}M`;
}

function fmtTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

export default function App() {
  const sceneRef = useRef<Scene>(createScene());
  const clientRef = useRef<VervainClient | null>(null);
  const metaRef = useRef<RunMeta | null>(null);

  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [meta, setMeta] = useState<RunMeta | null>(null);
  const [frame, setFrame] = useState<StateFrame | null>(null);
  const [ifn, setIfn] = useState(0);
  const [speed, setSpeed] = useState(2400);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    const client = new VervainClient({
      onStatus: setStatus,
      onMeta: (m) => {
        metaRef.current = m;
        setMeta(m);
        // A new run starts a new scene; nothing carries over from the old one.
        sceneRef.current = createScene();
        setRunning(true);
      },
      onFrame: (f) => {
        const m = metaRef.current;
        if (m) {
          instance(f.counts, m.compartment, m.rendered_species, sceneRef.current, f.t_sec);
        }
        setFrame(f);
      },
      onDone: () => setRunning(false),
    });
    clientRef.current = client;
    return () => client.dispose();
  }, []);

  const start = useCallback(
    (ifnValue: number, speedValue: number) => {
      clientRef.current?.run({ ifn: ifnValue, moi: 10, speed: speedValue });
    },
    [],
  );

  useEffect(() => {
    if (status === "open") start(ifn, speed);
    // Re-running on ifn change is the point of the slider; speed changes restart
    // too, which is acceptable because the trajectory is cached server-side.
  }, [status, ifn, speed, start]);

  const outcome = useMemo(() => {
    if (!frame) return null;
    const f = frame.outcome_flags;
    if (f.genome_cleared) return { label: "Abortive — genome cleared", color: "#4ade80" };
    if (f.super_permissive) return { label: "Productive — super-permissive", color: "#f87171" };
    if (f.releasing) return { label: "Productive — releasing virions", color: "#fb923c" };
    if (f.dmv_established) return { label: "Replication established", color: "#fbbf24" };
    return { label: "Early infection", color: "#93c5fd" };
  }, [frame]);

  const legend = meta?.rendered_species ?? [];

  return (
    <div style={S.app}>
      <header style={S.header}>
        <div>
          <h1 style={S.h1}>Vervain</h1>
          <div style={S.sub}>SARS-CoV-2 in a single ciliated airway epithelial cell</div>
        </div>
        <div style={S.headerRight}>
          <span style={{ ...S.dot, background: status === "open" ? "#4ade80" : "#f87171" }} />
          <span style={S.status}>
            {status === "open"
              ? running
                ? "streaming"
                : "connected"
              : status === "connecting"
                ? "connecting to solver…"
                : "solver offline — start sim/vervain/server/app.py"}
          </span>
        </div>
      </header>

      <div style={S.body}>
        <div style={S.viewport}>
          <CellView sceneRef={sceneRef} />

          {/* Persistent, non-dismissible. Positions are invented; counts are not. */}
          <div style={S.disclaimer}>
            <strong style={{ color: "#fbbf24" }}>Positions are illustrative.</strong>{" "}
            Molecule counts are modeled; where each sphere sits inside the cell is not.
            {meta && (
              <>
                {" "}
                <span style={{ color: "#f87171" }}>{meta.provenance.calibration}</span>
              </>
            )}
          </div>

          <div style={S.hud}>
            <div style={S.hudTime}>{frame ? fmtTime(frame.t_sec) : "—"}</div>
            {outcome && (
              <div style={{ ...S.outcome, color: outcome.color, borderColor: outcome.color }}>
                {outcome.label}
              </div>
            )}
            {frame && (
              <div style={S.regime}>
                solver: {frame.regime.toUpperCase()}
              </div>
            )}
          </div>
        </div>

        <aside style={S.panel}>
          <section style={S.section}>
            <label style={S.label}>
              Interferon pretreatment
              <span style={S.value}>{fmtCount(ifn)} ISG copies</span>
            </label>
            <input
              type="range"
              min={0}
              max={IFN_MAX}
              step={500}
              value={ifn}
              onChange={(e) => setIfn(Number(e.target.value))}
              style={S.slider}
            />
            <div style={S.hint}>
              Drag across ~10k and the outcome flips from productive infection to
              abortive. The cell clears the genome via RNase L before replication
              establishes.
            </div>
          </section>

          <section style={S.section}>
            <label style={S.label}>
              Playback speed
              <span style={S.value}>{(speed / 60).toFixed(0)}× sim-min / s</span>
            </label>
            <input
              type="range"
              min={300}
              max={7200}
              step={300}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              style={S.slider}
            />
          </section>

          <section style={S.section}>
            <div style={S.sectionTitle}>Molecular counts</div>
            <div style={S.legend}>
              {legend.map((name) => {
                const style = SPECIES_STYLE[name];
                const layer = sceneRef.current.layers.get(name);
                const count = frame?.counts[name] ?? 0;
                if (!style) return null;
                return (
                  <div key={name} style={S.legendRow}>
                    <span
                      style={{
                        ...S.swatch,
                        background: `#${style.color.toString(16).padStart(6, "0")}`,
                      }}
                    />
                    <span style={S.legendLabel}>{style.label}</span>
                    <span style={S.legendCount}>{fmtCount(count)}</span>
                    <span style={S.legendScale}>
                      {layer && layer.moleculesPerInstance > 1
                        ? `1 sphere ≈ ${fmtCount(layer.moleculesPerInstance)}`
                        : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          <section style={S.footnote}>
            Counts come from a well-mixed kinetic model (PySB → libRoadRunner/CVODE).
            Every parameter is currently <em>estimated</em> and unverified against
            literature — see <code>docs/validation.md</code> for the calibration targets.
          </section>
        </aside>
      </div>
    </div>
  );
}

const mono = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";

const S: Record<string, React.CSSProperties> = {
  app: {
    position: "fixed",
    inset: 0,
    display: "flex",
    flexDirection: "column",
    background: "#070910",
    color: "#e6ebf5",
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "12px 18px",
    borderBottom: "1px solid #1c2333",
  },
  h1: { margin: 0, fontSize: 18, letterSpacing: 0.5, fontWeight: 600 },
  sub: { fontSize: 12, color: "#8b9ab8", marginTop: 2 },
  headerRight: { display: "flex", alignItems: "center", gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, display: "inline-block" },
  status: { fontSize: 12, color: "#8b9ab8", fontFamily: mono },
  body: { flex: 1, display: "flex", minHeight: 0 },
  viewport: { flex: 1, position: "relative", minWidth: 0 },
  disclaimer: {
    position: "absolute",
    left: 14,
    bottom: 14,
    right: 14,
    fontSize: 11.5,
    lineHeight: 1.5,
    color: "#9fb0cf",
    background: "rgba(7,9,16,0.82)",
    border: "1px solid #1c2333",
    borderRadius: 6,
    padding: "8px 10px",
    pointerEvents: "none",
  },
  hud: { position: "absolute", left: 14, top: 14, display: "flex", flexDirection: "column", gap: 8 },
  hudTime: { fontFamily: mono, fontSize: 26, fontWeight: 600, letterSpacing: 1 },
  outcome: {
    fontSize: 12,
    fontFamily: mono,
    border: "1px solid",
    borderRadius: 4,
    padding: "3px 8px",
    alignSelf: "flex-start",
  },
  regime: { fontSize: 11, fontFamily: mono, color: "#6b7a99" },
  panel: {
    width: 340,
    borderLeft: "1px solid #1c2333",
    padding: 16,
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 20,
  },
  section: { display: "flex", flexDirection: "column", gap: 8 },
  sectionTitle: { fontSize: 12, textTransform: "uppercase", letterSpacing: 1, color: "#8b9ab8" },
  label: { fontSize: 13, display: "flex", justifyContent: "space-between", alignItems: "baseline" },
  value: { fontFamily: mono, fontSize: 12, color: "#fbbf24" },
  slider: { width: "100%", accentColor: "#fbbf24" },
  hint: { fontSize: 11.5, color: "#7f8ea8", lineHeight: 1.5 },
  legend: { display: "flex", flexDirection: "column", gap: 4 },
  legendRow: { display: "flex", alignItems: "center", gap: 8, fontSize: 12 },
  swatch: { width: 10, height: 10, borderRadius: 5, flexShrink: 0 },
  legendLabel: { flex: 1, color: "#c3cfe4", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
  legendCount: { fontFamily: mono, color: "#e6ebf5", minWidth: 52, textAlign: "right" },
  legendScale: { fontFamily: mono, fontSize: 10, color: "#6b7a99", minWidth: 74, textAlign: "right" },
  footnote: { fontSize: 11, color: "#6b7a99", lineHeight: 1.6, borderTop: "1px solid #1c2333", paddingTop: 12 },
};
