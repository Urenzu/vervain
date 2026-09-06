import { useCallback, useEffect, useRef, useState } from "react";

import { TrajectoryView } from "./render/TrajectoryView";
import { loadManifest, type Manifest } from "./traj/manifest";

const RATES = [1, 2, 5, 15] as const;

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
          <TrajectoryView manifest={manifest} frame={frame} hidden={hidden} />

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
