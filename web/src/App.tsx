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
    // Every colour resolves to a named token — no inline values (gate 48).
    if (f.genome_cleared) return { label: "Abortive · genome cleared", token: "--color-ok" };
    if (f.super_permissive) return { label: "Productive · super-permissive", token: "--color-hot" };
    if (f.releasing) return { label: "Productive · releasing virions", token: "--color-signal" };
    if (f.dmv_established) return { label: "Replication established", token: "--color-warn" };
    return { label: "Early infection", token: "--color-cool" };
  }, [frame]);

  const legend = meta?.rendered_species ?? [];

  // One word per state, so the masthead's right edge never shifts. The long
  // form is what a screen reader gets; the meter beside it is decorative.
  const link =
    status === "open"
      ? running
        ? { tone: "live", word: "live", full: "streaming from the solver" }
        : { tone: "idle", word: "idle", full: "connected, run complete" }
      : status === "connecting"
        ? { tone: "linking", word: "linking", full: "connecting to the solver" }
        : { tone: "offline", word: "offline", full: "solver offline — start sim/vervain/server/app.py" };

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead__id">
          <h1 className="masthead__mark">Vervain</h1>
          <span className="masthead__bar" aria-hidden="true" />
          <span className="masthead__sub">
            SARS-CoV-2 in a single ciliated airway epithelial cell
          </span>
        </div>
        <div className="masthead__link" role="status">
          <span className="sr-only">Solver link: {link.full}.</span>
          <span className={`link__state link__state--${link.tone}`} aria-hidden="true">
            {link.word}
          </span>
          <span className={`link__meter link__meter--${link.tone}`} aria-hidden="true" />
        </div>
      </header>

      <div className="body">
        <div className="stage">
          <CellView sceneRef={sceneRef} />

          <div className="readout">
            <div className="readout__clock">{frame ? fmtTime(frame.t_sec) : "—"}</div>
            {outcome && (
              <div className="readout__state">
                <span
                  className="dot"
                  style={{ background: `var(${outcome.token})` }}
                  aria-hidden="true"
                />
                {outcome.label}
              </div>
            )}
            {frame && <div className="readout__regime">solver · {frame.regime}</div>}
          </div>

          {/* Persistent, non-dismissible. Positions are invented; counts are not. */}
          <p className="provenance">
            <span className="provenance__lead">Positions are illustrative.</span> Molecule
            counts are modeled; where each sphere sits inside the cell is not.
            {meta && <span className="provenance__flag"> {meta.provenance.calibration}</span>}
          </p>
        </div>

        <aside className="rail">
          <section className="rail__block">
            <label className="block__label" htmlFor="ifn">
              Interferon pretreatment
            </label>
            <div className="block__readout">
              <span className="block__value">{fmtCount(ifn)}</span>
              <span className="block__unit">ISG copies</span>
            </div>
            <input
              id="ifn"
              className="slider"
              type="range"
              min={0}
              max={IFN_MAX}
              step={500}
              value={ifn}
              onChange={(e) => setIfn(Number(e.target.value))}
            />
            <p className="block__note">
              Drag across ~10k and the outcome flips from productive infection to abortive.
              The cell clears the genome via RNase L before replication establishes.
            </p>
          </section>

          <section className="rail__block">
            <label className="block__label" htmlFor="speed">
              Playback speed
            </label>
            <div className="block__readout">
              <span className="block__value">{(speed / 60).toFixed(0)}&times;</span>
              <span className="block__unit">sim-min / s</span>
            </div>
            <input
              id="speed"
              className="slider"
              type="range"
              min={300}
              max={7200}
              step={300}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            />
          </section>

          <section className="rail__block">
            <span className="block__label">Molecular counts</span>
            <div className="legend">
              {legend.map((name) => {
                const style = SPECIES_STYLE[name];
                const layer = sceneRef.current.layers.get(name);
                const count = frame?.counts[name] ?? 0;
                if (!style) return null;
                return (
                  <div key={name} className="legend__row">
                    <span
                      className="legend__swatch"
                      // Species colours are the data encoding, shared with the WebGL
                      // scene via SPECIES_STYLE — not chrome, so not a theme token.
                      style={{ background: `#${style.color.toString(16).padStart(6, "0")}` }}
                      aria-hidden="true"
                    />
                    <span className="legend__name" title={style.label}>
                      {style.label}
                    </span>
                    <span className="legend__figure">
                      <span className="legend__count">{fmtCount(count)}</span>
                      {layer && layer.moleculesPerInstance > 1 && (
                        <span className="legend__scale">
                          1 sphere &asymp; {fmtCount(layer.moleculesPerInstance)}
                        </span>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="colophon">
            Counts come from a well-mixed kinetic model (PySB &rarr; libRoadRunner/CVODE).
            Every parameter is currently <em>estimated</em> and unverified against
            literature — see <code>docs/validation.md</code> for the calibration targets.
          </section>
        </aside>
      </div>
    </div>
  );
}
