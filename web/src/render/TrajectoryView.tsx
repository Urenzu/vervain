// Renderer. Consumes a Manifest and a frame index and knows nothing above it —
// no structures, no force field, no pipeline. Swapping Three.js for raw WebGPU
// later touches only this file.
//
// The beads drawn here are simulated positions, not invented ones. That is the
// difference from the kinetic-model viewer this replaces, and it is why there
// is no instancer between the data and the scene.

import { useEffect, useRef } from "react";
import * as THREE from "three";

import { decodeFrame, type Manifest } from "../traj/manifest";

interface Props {
  manifest: Manifest | null;
  frame: number;
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

export function TrajectoryView({ manifest, frame }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const positionsRef = useRef<Int16Array | null>(null);
  const frameRef = useRef(frame);
  const manifestRef = useRef<Manifest | null>(manifest);

  frameRef.current = frame;
  manifestRef.current = manifest;

  // Fetch the position block once per manifest. It is the large asset; the
  // frame slider must not touch the network.
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

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(token("--color-paper", 0x0d0b09));

    const camera = new THREE.PerspectiveCamera(
      45,
      mount.clientWidth / mount.clientHeight,
      0.1,
      2000,
    );

    // Neutral lighting. A tinted key shifts every bead off the colour its
    // legend swatch promises.
    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const key = new THREE.DirectionalLight(0xffffff, 0.95);
    key.position.set(4, 6, 4);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xffffff, 0.25);
    rim.position.set(-4, -2, -3);
    scene.add(rim);

    const meshes: THREE.InstancedMesh[] = [];
    const decoded = manifest ? new Float32Array(manifest.beadCount * 3) : null;

    if (manifest) {
      for (const group of manifest.groups) {
        // Low-poly spheres on purpose: at these counts the silhouette is
        // carried by the impostor pass that replaces this, not by geometry.
        const geometry = new THREE.SphereGeometry(group.radiusNm, 8, 6);
        const material = new THREE.MeshStandardMaterial({
          color: new THREE.Color(group.color),
          roughness: 0.5,
        });
        const mesh = new THREE.InstancedMesh(geometry, material, group.beadCount);
        mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        mesh.count = 0;
        mesh.frustumCulled = false;
        scene.add(mesh);
        meshes.push(mesh);
      }
    }

    const span = manifest
      ? Math.max(manifest.boxNm[0], manifest.boxNm[1], manifest.boxNm[2])
      : 10;

    let theta = Math.PI / 4;
    let phi = 1.15;
    let radius = span * 1.6;
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
      radius = Math.min(span * 6, Math.max(span * 0.15, radius + e.deltaY * span * 0.001));
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

      const m = manifestRef.current;
      const raw = positionsRef.current;
      const current = frameRef.current;

      // Only rebuild the instance matrices when the frame actually changes;
      // orbiting must not re-upload the whole system every rAF.
      if (m && raw && decoded && current !== lastDrawn) {
        decodeFrame(raw, m, current, decoded);
        m.groups.forEach((group, gi) => {
          const mesh = meshes[gi];
          if (!mesh) return;
          for (let i = 0; i < group.beadCount; i++) {
            const src = (group.offset + i) * 3;
            dummy.position.set(decoded[src], decoded[src + 1], decoded[src + 2]);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
          }
          mesh.count = group.beadCount;
          mesh.instanceMatrix.needsUpdate = true;
        });
        lastDrawn = current;
      }

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
  }, [manifest]);

  return (
    <div
      ref={mountRef}
      className="stage__canvas"
      role="img"
      aria-label="Coarse-grained molecular dynamics trajectory. Drag to orbit, scroll to zoom."
    />
  );
}
