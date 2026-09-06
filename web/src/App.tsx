import { useEffect, useState } from "react";

import { TrajectoryView } from "./render/TrajectoryView";
import { loadManifest, type Manifest } from "./traj/manifest";

function fmtTime(ps: number): string {
  if (ps >= 1e6) return `${(ps / 1e6).toFixed(2)} µs`;
  if (ps >= 1e3) return `${(ps / 1e3).toFixed(1)} ns`;
  return `${ps.toFixed(0)} ps`;
}

export default function App() {
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [frame, setFrame] = useState(0);

  useEffect(() => {
    loadManifest()
      .then(setManifest)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const link = manifest
    ? { tone: "live", word: "loaded" }
    : error
      ? { tone: "offline", word: "no data" }
      : { tone: "linking", word: "loading" };

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
          <TrajectoryView manifest={manifest} frame={frame} />

          {manifest && (
            <div className="readout">
              <div className="readout__clock">
                {fmtTime(manifest.frameIntervalPs * frame)}
              </div>
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
                Build one with the pipeline in <code>sim/</code>, then export it to{" "}
                <code>web/public/traj/</code>.
              </p>
            </section>
          )}

          {manifest && (
            <>
              <section className="rail__block">
                <label className="block__label" htmlFor="frame">
                  Frame
                </label>
                <div className="block__readout">
                  <span className="block__value">
                    {fmtTime(manifest.frameIntervalPs * frame)}
                  </span>
                  <span className="block__unit">
                    of {fmtTime(manifest.frameIntervalPs * (manifest.frameCount - 1))}
                  </span>
                </div>
                <input
                  id="frame"
                  className="slider"
                  type="range"
                  min={0}
                  max={Math.max(0, manifest.frameCount - 1)}
                  step={1}
                  value={frame}
                  onChange={(e) => setFrame(Number(e.target.value))}
                />
              </section>

              <section className="rail__block">
                <span className="block__label">System</span>
                <div className="legend">
                  {manifest.groups.map((g) => (
                    <div key={g.name} className="legend__row">
                      <span
                        className="legend__swatch"
                        style={{ background: g.color }}
                        aria-hidden="true"
                      />
                      <span className="legend__name" title={g.description}>
                        {g.name}
                      </span>
                      <span className="legend__figure">
                        <span className="legend__count">
                          {g.beadCount.toLocaleString()}
                        </span>
                        <span className="legend__scale">beads</span>
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          <section className="colophon">
            MARTINI 3 coarse-grained beads, roughly four heavy atoms each. Structures
            and their caveats are catalogued in <code>sim/vervain/structures.yaml</code>;
            nothing enters the pipeline without a source.
          </section>
        </aside>
      </div>
    </div>
  );
}
