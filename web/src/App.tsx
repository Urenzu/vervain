import { useCallback, useEffect, useRef, useState } from "react";

import { ForceCurve } from "./render/ForceCurve";
import { TrajectoryView } from "./render/TrajectoryView";
import { flexColor, loadManifest, type ColorMode, type Manifest } from "./traj/manifest";

const RATES = [1, 2, 5, 15] as const;

// Each mode answers a different question about the same frame.
const COLOR_MODES: Array<{ id: ColorMode; label: string; asks: string }> = [
  { id: "chain", label: "chain", asks: "which molecule is which" },
  { id: "chemistry", label: "chemistry", asks: "where the charge and the grease sit" },
  { id: "flexibility", label: "motion", asks: "what actually moves over the run" },
];

function rgbCss([r, g, b]: [number, number, number]): string {
  const to = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 255);
  return `rgb(${to(r)}, ${to(g)}, ${to(b)})`;
}

function fmtTime(ps: number): string {
  if (ps >= 1e6) return `${(ps / 1e6).toFixed(2)} µs`;
  if (ps >= 1e3) return `${(ps / 1e3).toFixed(1)} ns`;
  return `${ps.toFixed(0)} ps`;
}

export default function App() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [rate, setRate] = useState<number>(5);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const [colorMode, setColorMode] = useState<ColorMode>("flexibility");

  useEffect(() => {
    loadManifest()
      .then(setManifest)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Playback is driven off wall-clock elapsed time rather than one frame per
  // animation tick, so the trajectory advances at the same rate on a 60 Hz
  // panel and a 144 Hz one.
  const accumulator = useRef(0);
  useEffect(() => {
    if (!manifest || !playing) return;
    let raf = 0;
    let last = performance.now();

    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const dt = (now - last) / 1000;
      last = now;
      accumulator.current += dt * rate * 10;
      if (accumulator.current >= 1) {
        const advance = Math.floor(accumulator.current);
        accumulator.current -= advance;
        setFrame((f) => (f + advance) % manifest.frameCount);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [manifest, playing, rate]);

  const toggleGroup = useCallback((name: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const link = manifest
    ? { tone: "live", word: "loaded" }
    : error
      ? { tone: "offline", word: "no data" }
      : { tone: "linking", word: "loading" };

  const elapsed = manifest ? manifest.frameIntervalPs * frame : 0;
  const total = manifest ? manifest.frameIntervalPs * (manifest.frameCount - 1) : 0;

  return (
    <div className="app">
      <header className="masthead">
        <div className="masthead__id">
          <h1 className="masthead__mark">Vervain</h1>
          <span className="masthead__bar" aria-hidden="true" />
          <span className="masthead__sub">
            Coarse-grained MD of SARS-CoV-2 entry
          </span>
        </div>
        <div className="masthead__link" role="status">
          <span className="sr-only">Trajectory: {link.word}.</span>
          <span className={`link__state link__state--${link.tone}`} aria-hidden="true">
            {link.word}
          </span>
          <span className={`link__meter link__meter--${link.tone}`} aria-hidden="true" />
        </div>
      </header>

      <div className="body">
        <div className="stage">
          <TrajectoryView
            manifest={manifest}
            frame={frame}
            hidden={hidden}
            colorMode={colorMode}
          />

          {manifest && (
            <div className="readout">
              <div className="readout__clock">{fmtTime(elapsed)}</div>
              <div className="readout__regime">
                frame {frame + 1} / {manifest.frameCount} · {manifest.forceField}
              </div>
            </div>
          )}

          <p className="provenance">
            <span className="provenance__lead">Positions are simulated.</span> Every
            coordinate comes from the integrator. Steps too slow for unbiased MD are
            driven, and labelled as driven — see <code>docs/pipeline.md</code>.
          </p>
        </div>

        <aside className="rail">
          {error && (
            <section className="rail__block">
              <span className="block__label">No trajectory</span>
              <p className="block__note">{error}</p>
              <p className="block__note">
                Build one with <code>make first-light</code>.
              </p>
            </section>
          )}

          {manifest && (
            <>
              <section className="rail__block">
                <span className="block__label">Playback</span>
                <div className="transport">
                  <button
                    type="button"
                    className="btn"
                    aria-pressed={playing}
                    onClick={() => setPlaying((p) => !p)}
                  >
                    {playing ? "pause" : "play"}
                  </button>
                  <span className="transport__rate">
                    {rate}× &middot; {fmtTime(manifest.frameIntervalPs * rate * 10)}/s
                  </span>
                </div>
                <div className="block__readout">
                  <span className="block__value">{fmtTime(elapsed)}</span>
                  <span className="block__unit">of {fmtTime(total)}</span>
                </div>
                <input
                  id="frame"
                  className="slider"
                  type="range"
                  min={0}
                  max={Math.max(0, manifest.frameCount - 1)}
                  step={1}
                  value={frame}
                  onChange={(e) => {
                    setPlaying(false);
                    setFrame(Number(e.target.value));
                  }}
                  aria-label="Trajectory frame"
                />
                <div className="transport" style={{ marginTop: "0.75rem" }}>
                  {RATES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      className="btn"
                      style={{ minWidth: "2.75rem" }}
                      aria-pressed={rate === r}
                      onClick={() => setRate(r)}
                    >
                      {r}×
                    </button>
                  ))}
                </div>
              </section>

              {manifest.pull && (
                <section className="rail__block">
                  <span className="block__label">Pull force</span>
                  <div className="block__readout">
                    <span className="block__value">
                      {manifest.pull.ruptureForcePn.toFixed(0)} pN
                    </span>
                    <span className="block__unit">rupture</span>
                  </div>
                  <ForceCurve pull={manifest.pull} timePs={elapsed} />
                  <p className="block__note">
                    Peak at {(manifest.pull.ruptureTimePs / 1000).toFixed(1)} ns,
                    {" "}{manifest.pull.ruptureExtensionNm.toFixed(2)} nm extension,
                    pulled at {manifest.pull.rateNmPerNs.toFixed(2)} nm/ns.
                  </p>
                  <p className="block__note">
                    That rate is far faster than anything physical, so this is an
                    upper bound and a relative measure — good for comparing
                    variants pulled identically, not a binding free energy.
                  </p>
                </section>
              )}

              <section className="rail__block">
                <span className="block__label">Colour</span>
                <div className="transport" style={{ flexWrap: "wrap" }}>
                  {COLOR_MODES.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      className="btn"
                      style={{ minWidth: "4rem" }}
                      aria-pressed={colorMode === mode.id}
                      title={mode.asks}
                      onClick={() => setColorMode(mode.id)}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>

                {colorMode === "chemistry" && (
                  <div className="legend" style={{ marginTop: "0.75rem" }}>
                    {Object.entries(manifest.chemistryPalette)
                      .filter(([key]) => manifest.chemistry.includes(key))
                      .map(([key, cls]) => (
                        <div key={key} className="legend__row">
                          <span
                            className="legend__swatch"
                            style={{ background: cls.color }}
                            aria-hidden="true"
                          />
                          <span className="legend__name">{cls.label}</span>
                          <span className="legend__figure">
                            <span className="legend__count">
                              {manifest.chemistry.filter((c) => c === key).length}
                            </span>
                          </span>
                        </div>
                      ))}
                  </div>
                )}

                {colorMode === "flexibility" && (() => {
                  const lo = Math.min(...manifest.rmsfNm);
                  const hi = Math.max(...manifest.rmsfNm);
                  const stops = [0, 0.25, 0.5, 0.75, 1];
                  return (
                    <div style={{ marginTop: "0.75rem" }}>
                      <div style={{ display: "flex", height: "0.5rem" }}>
                        {stops.map((t) => (
                          <span
                            key={t}
                            style={{
                              flex: 1,
                              background: rgbCss(flexColor(lo + (hi - lo) * t, lo, hi)),
                            }}
                          />
                        ))}
                      </div>
                      <div className="block__readout" style={{ marginTop: "0.375rem" }}>
                        <span className="block__unit">{lo.toFixed(2)} nm rigid</span>
                        <span className="block__unit">mobile {hi.toFixed(2)} nm</span>
                      </div>
                      <p className="block__note">
                        Root-mean-square fluctuation per bead, measured over the run
                        after superposition — so this is flexibility, not tumbling.
                      </p>
                    </div>
                  );
                })()}
              </section>

              <section className="rail__block">
                <span className="block__label">System</span>
                <div className="legend">
                  {manifest.groups.map((g) => {
                    const off = hidden.has(g.name);
                    return (
                      <button
                        key={g.name}
                        type="button"
                        className={`legend__row legend__row--button${off ? " legend__row--off" : ""}`}
                        aria-pressed={!off}
                        title={g.description}
                        onClick={() => toggleGroup(g.name)}
                      >
                        <span
                          className="legend__swatch"
                          style={{ background: g.color }}
                          aria-hidden="true"
                        />
                        <span className="legend__name">{g.name}</span>
                        <span className="legend__figure">
                          <span className="legend__count">
                            {g.beadCount.toLocaleString()}
                          </span>
                          <span className="legend__scale">beads</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
                <p className="block__note">
                  Click a row to hide it. Water is not drawn — it is 83% of the
                  simulated beads and nothing is learned from it.
                </p>
              </section>
            </>
          )}

          <section className="colophon">
            Martini 3 coarse-grained beads, roughly four heavy atoms each. Structures
            and their caveats are catalogued in <code>sim/vervain/structures.yaml</code>;
            nothing enters the pipeline without a source.
          </section>
        </aside>
      </div>
    </div>
  );
}
