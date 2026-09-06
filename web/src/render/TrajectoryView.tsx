// Renderer. Consumes a Manifest and a frame index and knows nothing above it —
// no structures, no force field, no pipeline.
//
// The beads drawn here are simulated positions, not invented ones. That is the
// difference from the kinetic-model viewer this replaces, and it is why there
// is no instancer between the data and the scene.
//
// Two techniques carried over from molecular visualisation, because a dense
// bead scene is unreadable without them: ambient occlusion, which puts contact
// shadows in the crevices so overlapping spheres separate; and depth cueing,
// which fades distant beads into the ground so the eye can order them. Neither
// is decoration — they are what turn confetti into structure.

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { SSAOPass } from "three/examples/jsm/postprocessing/SSAOPass.js";

import { decodeFrame, flexColor, type ColorMode, type Manifest } from "../traj/manifest";

interface Props {
  manifest: Manifest | null;
  frame: number;
  hidden: ReadonlySet<string>;
  colorMode: ColorMode;
}

function token(name: string, fallback: number): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return fallback;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return fallback;
  // Paint and read back: browsers serialise oklch() as-is, so reading
  // ctx.fillStyle never yields a hex. getImageData resolves any CSS colour
  // syntax down to the sRGB bytes Three.js can take.
  ctx.fillStyle = raw;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return a === 0 ? fallback : (r << 16) | (g << 8) | b;
}

export function TrajectoryView({ manifest, frame, hidden, colorMode }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const positionsRef = useRef<Int16Array | null>(null);
  const frameRef = useRef(frame);
  const hiddenRef = useRef(hidden);
  const colorModeRef = useRef(colorMode);
  const manifestRef = useRef<Manifest | null>(manifest);

  frameRef.current = frame;
  hiddenRef.current = hidden;
  colorModeRef.current = colorMode;
  manifestRef.current = manifest;

  // Fetch the position block once per manifest. It is the large asset; playback
  // and the frame slider must never touch the network.
  useEffect(() => {
    if (!manifest) {
      positionsRef.current = null;
      return;
    }
    let cancelled = false;
    fetch(`/traj/${manifest.positions}`)
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
  }, [manifest]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const paper = token("--color-paper", 0x0d0b09);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(paper);

    const camera = new THREE.PerspectiveCamera(
      45,
      mount.clientWidth / mount.clientHeight,
      0.1,
      2000,
    );

    // Neutral lighting. A tinted key shifts every bead off the colour its
    // legend swatch promises.
    scene.add(new THREE.AmbientLight(0xffffff, 0.45));
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(4, 6, 4);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xffffff, 0.25);
    rim.position.set(-4, -2, -3);
    scene.add(rim);

    const meshes: THREE.InstancedMesh[] = [];
    const decoded = manifest ? new Float32Array(manifest.beadCount * 3) : null;

    // Frame on the molecule, not the periodic box. The export centres on the
    // solute and drops the solvent, so the cell is mostly empty space — and it
    // already reports the solute's half-extent, which is exactly what the
    // camera distance and the fog should key off.
    let span = 10;
    if (manifest) {
      span = Math.max(4, Math.max(...manifest.extentNm));
      for (const group of manifest.groups) {
        // A unit sphere scaled per instance, rather than one sized geometry
        // per group. Martini 3 has three bead sizes — regular, small and tiny,
        // measured here as 567/503/394 in ACE2 alone — and a single radius
        // draws a third of them 12% wrong in each direction.
        const geometry = new THREE.SphereGeometry(1, 16, 12);
        const material = new THREE.MeshStandardMaterial({
          roughness: 0.55,
          metalness: 0.0,
          // White base: per-instance colour multiplies into it, so the tint has
          // to come entirely from instanceColor.
          color: 0xffffff,
        });
        const mesh = new THREE.InstancedMesh(geometry, material, group.beadCount);
        mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        mesh.count = 0;
        mesh.frustumCulled = false;
        mesh.name = group.name;
        scene.add(mesh);
        meshes.push(mesh);
      }
    }

    // Depth cueing. The fog colour is the page ground, so distance reads as
    // recession rather than as haze. Near and far are recomputed against the
    // camera each frame — pinned to fixed distances the fog either swallows the
    // far half of the molecule at rest or stops doing anything once you zoom.
    const fog = new THREE.Fog(paper, 1, 2);
    scene.fog = fog;

    // Ambient occlusion is off by default, and that is a known gap rather than
    // a preference. Three's SSAOPass builds depth and normals by re-rendering
    // the scene with an override material, and that path does not handle
    // InstancedMesh — the result is a black frame, with no error. Every bead
    // here is instanced, so the pass cannot be used as-is.
    //
    // Worth returning to: AO is the single most valuable technique for making a
    // dense bead scene readable, and this system is small enough that a custom
    // pass respecting instance matrices is affordable. Until then, depth cueing
    // below carries the spatial ordering on its own.
    //
    // ?ssao=1 enables it, which is how the diagnosis above was made.
    const wantSSAO = new URLSearchParams(window.location.search).get("ssao") === "1";
    let composer: EffectComposer | null = null;
    if (wantSSAO) {
      try {
        composer = new EffectComposer(renderer);
        composer.addPass(new RenderPass(scene, camera));
        const ssao = new SSAOPass(scene, camera, mount.clientWidth, mount.clientHeight);
        // Tuned in scene units: beads are 0.19 nm and sit ~0.3 nm apart, so the
        // occlusion radius has to be that scale, not the pixel-ish defaults.
        ssao.kernelRadius = 0.25;
        ssao.minDistance = 0.001;
        ssao.maxDistance = 0.6;
        composer.addPass(ssao);
      } catch {
        composer = null;
      }
    }

    // Colour is recomputed only when the mode changes; it is per bead and
    // constant in time, so doing it per frame would be pure waste.
    const tint = new THREE.Color();
    const applyColors = (mode: ColorMode) => {
      const m = manifestRef.current;
      if (!m) return;
      const lo = Math.min(...m.rmsfNm);
      const hi = Math.max(...m.rmsfNm);

      m.groups.forEach((group, gi) => {
        const mesh = meshes[gi];
        if (!mesh) return;
        for (let i = 0; i < group.beadCount; i++) {
          const bead = group.offset + i;
          if (mode === "chain") {
            tint.set(group.color);
          } else if (mode === "chemistry") {
            const cls = m.chemistryPalette[m.chemistry[bead]];
            tint.set(cls ? cls.color : "#95918d");
          } else {
            const [r, g, b] = flexColor(m.rmsfNm[bead], lo, hi);
            tint.setRGB(r, g, b);
          }
          mesh.setColorAt(i, tint);
        }
        if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      });
    };
    let appliedMode: ColorMode | null = null;

    let theta = Math.PI / 4;
    let phi = 1.15;
    let radius = span * 2.1;
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
      radius = Math.min(span * 6, Math.max(span * 0.4, radius + e.deltaY * span * 0.0015));
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
      composer?.setSize(mount.clientWidth, mount.clientHeight);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    const dummy = new THREE.Object3D();
    let raf = 0;
    let lastDrawn = -1;
    let framed = false;

    const tick = () => {
      raf = requestAnimationFrame(tick);

      camera.position.set(
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(0, 0, 0);

      // Start the fog just past the molecule's near face and run it well past
      // the far one, so it orders depth without erasing the back half.
      fog.near = Math.max(0.1, radius - span * 0.85);
      fog.far = radius + span * 3.2;

      const m = manifestRef.current;
      const raw = positionsRef.current;
      const current = frameRef.current;

      // Only rebuild the instance matrices when the frame actually changes;
      // orbiting must not re-upload the whole system every animation tick.
      if (m && raw && decoded && current !== lastDrawn) {
        decodeFrame(raw, m, current, decoded);
        m.groups.forEach((group, gi) => {
          const mesh = meshes[gi];
          if (!mesh) return;
          for (let i = 0; i < group.beadCount; i++) {
            const bead = group.offset + i;
            const src = bead * 3;
            dummy.position.set(decoded[src], decoded[src + 1], decoded[src + 2]);
            dummy.scale.setScalar(m.radiusNm[bead] ?? group.radiusNm);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
          }
          mesh.count = group.beadCount;
          mesh.instanceMatrix.needsUpdate = true;
        });
        // Frame the interface on first draw. The RBD sits at one end of ACE2,
        // so an arbitrary starting angle buries it — which is the one thing in
        // this system worth looking at. Aim across the axis joining the two
        // groups, not along it.
        if (!framed && m.groups.length >= 2) {
          const centroid = (gi: number) => {
            const g = m.groups[gi];
            let x = 0, y = 0, z = 0;
            for (let i = 0; i < g.beadCount; i++) {
              const src = (g.offset + i) * 3;
              x += decoded[src];
              y += decoded[src + 1];
              z += decoded[src + 2];
            }
            return [x / g.beadCount, y / g.beadCount, z / g.beadCount];
          };
          const a = centroid(0);
          const b = centroid(1);
          const axis = Math.atan2(b[2] - a[2], b[0] - a[0]);
          theta = axis + Math.PI / 2;   // look across the pair, not down it
          phi = 1.35;
          framed = true;
        }

        lastDrawn = current;
      }

      if (appliedMode !== colorModeRef.current) {
        applyColors(colorModeRef.current);
        appliedMode = colorModeRef.current;
      }

      for (const mesh of meshes) mesh.visible = !hiddenRef.current.has(mesh.name);

      if (composer) composer.render();
      else renderer.render(scene, camera);
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
      composer?.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, [manifest]);

  return (
    <div
      ref={mountRef}
      className="stage__canvas"
      role="img"
      aria-label="Coarse-grained molecular dynamics trajectory of the SARS-CoV-2 spike receptor-binding domain bound to human ACE2. Drag to orbit, scroll to zoom."
    />
  );
}
