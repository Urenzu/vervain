// Renderer for the staged view. Same discipline as TrajectoryView — one
// InstancedMesh per group, a unit sphere scaled per bead, depth cueing keyed to
// the camera — but the content is an arrangement rather than an integration, so
// what it needs from the camera is different.
//
// Stages here span three orders of magnitude: the fusion morph is 23 nm across
// and the virion approach is 232. A camera framed for one is useless for the
// other, so distance is derived per stage from its own measured span rather
// than tuned once.

import { useEffect, useRef } from "react";
import * as THREE from "three";

import { decodeStageFrame, type SceneStage } from "../scene/scene";

interface Props {
  stage: SceneStage | null;
  frame: number;
  hidden: ReadonlySet<string>;
}

function token(name: string, fallback: number): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return fallback;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return fallback;
  ctx.fillStyle = raw;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return a === 0 ? fallback : (r << 16) | (g << 8) | b;
}

export function StageView({ stage, frame, hidden }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const positionsRef = useRef<Int16Array | null>(null);
  const frameRef = useRef(frame);
  const hiddenRef = useRef(hidden);

  frameRef.current = frame;
  hiddenRef.current = hidden;

  // One fetch per stage. Stages are large — the approach stage is 116k beads —
  // so switching stages is a load, and switching back must not be.
  useEffect(() => {
    if (!stage) {
      positionsRef.current = null;
      return;
    }
    let cancelled = false;
    positionsRef.current = null;
    fetch(`/scene/${stage.positions}`)
      .then((r) => r.arrayBuffer())
      .then((buf) => {
        if (!cancelled) positionsRef.current = new Int16Array(buf);
      })
      .catch(() => {
        positionsRef.current = null;
      });
    return () => {
      cancelled = true;
    };
  }, [stage]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || !stage) return;

    const paper = token("--color-paper", 0x0d0b09);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(paper);
    const camera = new THREE.PerspectiveCamera(
      42,
      mount.clientWidth / mount.clientHeight,
      0.1,
      8000,
    );

    scene.add(new THREE.AmbientLight(0xffffff, 0.42));
    const key = new THREE.DirectionalLight(0xffffff, 0.95);
    key.position.set(4, 7, 5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xffffff, 0.28);
    rim.position.set(-5, -2, -4);
    scene.add(rim);

    const span = Math.max(2, Math.max(...stage.extentNm));
    const decoded = new Float32Array(stage.beadCount * 3);

    // Segment count scales down with bead count. At 116k beads a 16x12 sphere
    // is 22M triangles and the frame rate collapses; at 1k it is free and the
    // silhouettes should be smooth.
    const detail = stage.beadCount > 40000 ? 5 : stage.beadCount > 8000 ? 8 : 16;
    const tint = new THREE.Color();
    const meshes: THREE.InstancedMesh[] = [];
    for (const group of stage.groups) {
      const geometry = new THREE.SphereGeometry(1, detail, Math.max(3, detail - 4));
      const material = new THREE.MeshStandardMaterial({
        roughness: 0.58,
        metalness: 0.0,
        color: 0xffffff,
      });
      const mesh = new THREE.InstancedMesh(geometry, material, group.beadCount);
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      mesh.count = 0;
      mesh.frustumCulled = false;
      mesh.name = group.role;
      tint.set(group.color);
      for (let i = 0; i < group.beadCount; i++) mesh.setColorAt(i, tint);
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      scene.add(mesh);
      meshes.push(mesh);
    }

    const fog = new THREE.Fog(paper, 1, 2);
    scene.fog = fog;

    let theta = Math.PI / 4;
    // Slightly above the equator, so the cell surface reads as a surface rather
    // than as a line. Distance keys off the stage's own extent because these
    // stages differ tenfold in size.
    let phi = 1.28;
    let radius = span * 3.0;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    const onDown = (e: PointerEvent) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      (e.target as Element).setPointerCapture?.(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      theta -= (e.clientX - lastX) * 0.006;
      phi = Math.min(Math.PI - 0.12, Math.max(0.12, phi - (e.clientY - lastY) * 0.006));
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onUp = () => {
      dragging = false;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      radius = Math.min(span * 8, Math.max(span * 0.25, radius + e.deltaY * span * 0.0015));
    };

    const el = renderer.domElement;
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    el.addEventListener("wheel", onWheel, { passive: false });

    const onResize = () => {
      if (!mount.clientWidth || !mount.clientHeight) return;
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    const dummy = new THREE.Object3D();
    let raf = 0;
    let lastDrawn = -1;

    const tick = () => {
      raf = requestAnimationFrame(tick);

      camera.position.set(
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(0, 0, 0);
      fog.near = Math.max(0.1, radius - span * 0.9);
      fog.far = radius + span * 3.4;

      const raw = positionsRef.current;
      const current = stage.frameCount > 1 ? frameRef.current % stage.frameCount : 0;

      if (raw && current !== lastDrawn) {
        decodeStageFrame(raw, stage, current, decoded);
        stage.groups.forEach((group, gi) => {
          const mesh = meshes[gi];
          if (!mesh) return;
          for (let i = 0; i < group.beadCount; i++) {
            const bead = group.offset + i;
            const src = bead * 3;
            dummy.position.set(decoded[src], decoded[src + 1], decoded[src + 2]);
            dummy.scale.setScalar(stage.radiusNm[bead] ?? 0.4);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
          }
          mesh.count = group.beadCount;
          mesh.instanceMatrix.needsUpdate = true;
        });
        lastDrawn = current;
      }

      for (const mesh of meshes) mesh.visible = !hiddenRef.current.has(mesh.name);
      renderer.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
      el.removeEventListener("wheel", onWheel);
      for (const mesh of meshes) {
        mesh.geometry.dispose();
        (mesh.material as THREE.Material).dispose();
      }
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, [stage]);

  return <div ref={mountRef} className="stage__canvas" />;
}
