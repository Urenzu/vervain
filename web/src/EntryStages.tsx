// The staged view of viral entry.
//
// Kept separate from the trajectory view because it is a different claim. The
// trajectory says "this is what the physics did". This says "these are the
// measured structures, and here is where the evidence puts them" — and for
// three of the four stages, part of that placement is a hypothesis.
//
// Every group in the rail carries its evidence class. That is the load-bearing
// part of this screen: an illustration that cannot distinguish its measurements
// from its guesses is worse than no illustration, because it is persuasive
// either way.

import { useCallback, useEffect, useRef, useState } from "react";

import { StageView } from "./render/StageView";
import {
  EVIDENCE_NOTE,
  evidenceOf,
  loadScene,
  type Evidence,
  type Scene,
  type SceneStage,
} from "./scene/scene";

const EVIDENCE_ORDER: Evidence[] = ["measured", "simulated", "interpolated", "posed"];

export function EntryStages() {
  const [scene, setScene] = useState<Scene | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    loadScene()
      .then(setScene)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const stage: SceneStage | null = scene ? (scene.stages[index] ?? null) : null;

  // Only a morph stage animates. Driving a single-frame stage would burn a
  // timer to redraw the same arrangement forever.
  const accumulator = useRef(0);
  useEffect(() => {
    if (!stage || stage.frameCount <= 1 || !playing) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      accumulator.current += ((now - last) / 1000) * 14;
      last = now;
      if (accumulator.current >= 1) {
        const advance = Math.floor(accumulator.current);
        accumulator.current -= advance;
        setFrame((f) => (f + advance) % stage.frameCount);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [stage, playing]);

  useEffect(() => {
    setFrame(0);
    setHidden(new Set());
  }, [index]);

  const toggle = useCallback((role: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      return next;
    });
  }, []);

  if (error) {
    return (
      <div className="body">
        <div className="stage">
          <div className="stage__empty">
            <p className="block__note">{error}</p>
            <p className="block__note">
              Build it with <code>make scene</code>.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const evidence = stage ? evidenceOf(stage) : [];

  return (
    <div className="body">
      <div className="stage">
        <StageView stage={stage} frame={frame} hidden={hidden} />

        {stage && (
          <div className="readout">
            <div className="readout__clock">{stage.title}</div>
            <div className="readout__regime">
              {/* Always nanometres. The readout is uppercased by its style, and
                  CSS maps the micro sign onto Greek capital Mu — "0.23 µm"
                  renders as "0.23 MM", which reads as millimetres and is wrong
                  by a factor of a thousand in the one label that is about
                  scale. Everything in this project is nanometres anyway. */}
              {stage.spanNm.toFixed(stage.spanNm < 100 ? 1 : 0)} nm across
              {" · "}
              {stage.beadCount.toLocaleString()} beads
              {stage.frameCount > 1 ? ` · frame ${frame + 1}/${stage.frameCount}` : ""}
            </div>
          </div>
        )}

        <p className="provenance">
          <span className="provenance__lead">Arrangements, not a simulation.</span> Every
          structure here is deposited coordinates. Where they sit relative to each
          other is measured in some stages and posed in others — the rail says
          which, per object.
        </p>
      </div>

      <aside className="rail">
        <section className="rail__block">
          <span className="block__label">Stage</span>
          <div className="transport" style={{ flexWrap: "wrap" }}>
            {(scene?.stages ?? []).map((s, i) => (
              <button
                key={s.id}
                type="button"
                className="btn"
                aria-pressed={i === index}
                onClick={() => setIndex(i)}
              >
                {i + 1}. {s.title}
              </button>
            ))}
          </div>
        </section>

        {stage && (
          <section className="rail__block">
            <span className="block__label">What this is</span>
            <p className="block__note">{stage.caption}</p>
          </section>
        )}

        {stage && stage.frameCount > 1 && (
          <section className="rail__block">
            <span className="block__label">Morph</span>
            <div className="transport">
              <button
                type="button"
                className="btn"
                aria-pressed={playing}
                onClick={() => setPlaying((p) => !p)}
              >
                {playing ? "pause" : "play"}
              </button>
              <input
                type="range"
                min={0}
                max={stage.frameCount - 1}
                value={frame}
                onChange={(e) => {
                  setPlaying(false);
                  setFrame(Number(e.target.value));
                }}
                aria-label="Morph position"
              />
            </div>
            <p className="block__note">
              Endpoints measured, path drawn. The slider is an artist's parameter,
              not a clock — there is no time axis here to put a number on.
            </p>
          </section>
        )}

        {stage && (
          <section className="rail__block">
            <span className="block__label">Objects</span>
            {stage.groups.map((group) => (
              <button
                key={group.role}
                type="button"
                className="object__row"
                aria-pressed={!hidden.has(group.role)}
                onClick={() => toggle(group.role)}
                title={group.source}
              >
                <span
                  className="object__swatch"
                  style={{ background: group.color }}
                  aria-hidden="true"
                />
                <span className="object__name">{group.role}</span>
                <span className={`evidence evidence--${group.evidence}`}>
                  {group.evidence}
                </span>
              </button>
            ))}
            <p className="block__note">
              Click a row to hide it. Hover for the source structure.
            </p>
          </section>
        )}

        {stage && (
          <section className="rail__block">
            <span className="block__label">How well this is known</span>
            {EVIDENCE_ORDER.filter((e) => evidence.includes(e)).map((e) => (
              <p key={e} className="block__note">
                <span className={`evidence evidence--${e}`}>{e}</span> {EVIDENCE_NOTE[e]}
              </p>
            ))}
          </section>
        )}

        <section className="rail__block">
          <span className="block__label">Why it is not one simulation</span>
          <p className="block__note">
            Molecular dynamics integrates in two-femtosecond steps and reaches
            microseconds. Entry takes seconds. Reaching one second would need
            about 10<sup>14</sup> steps; the 20 ns run in the trajectory view took
            forty minutes on a 3060. No amount of hardware closes six orders of
            magnitude, so the sequence is assembled from structures and only the
            attachment stage is integrated.
          </p>
        </section>
      </aside>
    </div>
  );
}
