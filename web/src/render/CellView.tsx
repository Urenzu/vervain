// Renderer. Consumes a Scene from the instancer and knows nothing above it —
// no counts, no protocol, no solver. Swapping Three.js for raw WebGPU later
// touches only this file.

import { useEffect, useRef } from "react";
import * as THREE from "three";

import {
  CELL_GEOMETRY,
  MAX_INSTANCES_PER_SPECIES,
  particlePosition,
  type Scene as VervainScene,
} from "../instancer/instancer";

export const SPECIES_STYLE: Record<string, { color: number; radius: number; label: string }> = {
  Vout:        { color: 0xff5c5c, radius: 0.030, label: "Virion (extracellular)" },
  Vbound:      { color: 0xff8a3d, radius: 0.030, label: "Virion bound to ACE2" },
  Vendo:       { color: 0xffc247, radius: 0.028, label: "Virion in endosome" },
  gRNA:        { color: 0x4fc3f7, radius: 0.018, label: "Genomic RNA (+)" },
  ngRNA:       { color: 0x1e88e5, radius: 0.016, label: "Negative strand (−)" },
  sgRNA:       { color: 0x81d4fa, radius: 0.014, label: "Subgenomic mRNA" },
  DMV:         { color: 0x9575cd, radius: 0.075, label: "Double-membrane vesicle" },
  dsRNA_cyt:   { color: 0xff4081, radius: 0.020, label: "Cytosolic dsRNA (sensed)" },
  Nprot:       { color: 0xa5d6a7, radius: 0.012, label: "Nucleocapsid protein" },
  Sprot:       { color: 0x66bb6a, radius: 0.012, label: "Structural proteins" },
  RNP:         { color: 0x26a69a, radius: 0.022, label: "Ribonucleoprotein" },
  Vassembled:  { color: 0xffa726, radius: 0.030, label: "Assembled virion" },
  Vreleased:   { color: 0xef5350, radius: 0.030, label: "Released virion" },
  ISG:         { color: 0xfff176, radius: 0.010, label: "Antiviral state (ISG)" },
};

interface Props {
  sceneRef: React.MutableRefObject<VervainScene>;
}

export function CellView({ sceneRef }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0e14);

    const camera = new THREE.PerspectiveCamera(
      45,
      mount.clientWidth / mount.clientHeight,
      0.1,
      100,
    );
    camera.position.set(3.6, 1.4, 3.6);
    camera.lookAt(0, 0, 0);

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(4, 6, 4);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x88aaff, 0.5);
    rim.position.set(-4, -2, -3);
    scene.add(rim);

    // --- cell scaffold: a columnar ciliated cell, apical surface at +y ---
    const g = CELL_GEOMETRY;
    const cellBox = new THREE.BoxGeometry(
      g.halfX * 2,
      g.apicalY - g.basalY,
      g.halfZ * 2,
    );
    const cell = new THREE.Mesh(
      cellBox,
      new THREE.MeshStandardMaterial({
        color: 0x2a3350,
        transparent: true,
        opacity: 0.13,
        side: THREE.DoubleSide,
        depthWrite: false,
      }),
    );
    cell.position.y = (g.apicalY + g.basalY) / 2;
    scene.add(cell);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(cellBox),
      new THREE.LineBasicMaterial({ color: 0x5b6da8, transparent: true, opacity: 0.5 }),
    );
    edges.position.copy(cell.position);
    scene.add(edges);

    const nucleus = new THREE.Mesh(
      new THREE.SphereGeometry(g.nucleusR, 32, 24),
      new THREE.MeshStandardMaterial({
        color: 0x3b4a7a,
        transparent: true,
        opacity: 0.35,
        depthWrite: false,
      }),
    );
    nucleus.position.set(...g.nucleusCenter);
    scene.add(nucleus);

    // Cilia on the apical surface — the only reason to know this is a ciliated
    // cell by looking at it.
    const ciliaMat = new THREE.LineBasicMaterial({
      color: 0x6f86c9,
      transparent: true,
      opacity: 0.45,
    });
    const ciliaPts: number[] = [];
    for (let i = 0; i < 90; i++) {
      const x = (Math.random() * 2 - 1) * g.halfX * 0.92;
      const z = (Math.random() * 2 - 1) * g.halfZ * 0.92;
      const h = 0.22 + Math.random() * 0.18;
      ciliaPts.push(x, g.apicalY, z, x + (Math.random() - 0.5) * 0.1, g.apicalY + h, z);
    }
    const ciliaGeom = new THREE.BufferGeometry();
    ciliaGeom.setAttribute("position", new THREE.Float32BufferAttribute(ciliaPts, 3));
    scene.add(new THREE.LineSegments(ciliaGeom, ciliaMat));

    // --- one InstancedMesh per species ---
    const meshes = new Map<string, THREE.InstancedMesh>();
    for (const [name, style] of Object.entries(SPECIES_STYLE)) {
      const geom = new THREE.SphereGeometry(style.radius, 10, 8);
      const mat = new THREE.MeshStandardMaterial({
        color: style.color,
        emissive: new THREE.Color(style.color).multiplyScalar(0.25),
        roughness: 0.45,
      });
      const mesh = new THREE.InstancedMesh(geom, mat, MAX_INSTANCES_PER_SPECIES);
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      mesh.count = 0;
      mesh.frustumCulled = false;
      scene.add(mesh);
      meshes.set(name, mesh);
    }

    // --- interaction: drag to orbit, wheel to zoom ---
    let theta = Math.PI / 4;
    let phi = 1.15;
    let radius = 6.6;
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
      radius = Math.min(14, Math.max(1.6, radius + e.deltaY * 0.0035));
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
    const pos: [number, number, number] = [0, 0, 0];
    let raf = 0;
    const start = performance.now();

    const tick = () => {
      raf = requestAnimationFrame(tick);
      const wall = (performance.now() - start) / 1000;

      camera.position.set(
        radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta),
      );
      camera.lookAt(0, 0, 0);

      const vScene = sceneRef.current;
      for (const [name, mesh] of meshes) {
        const layer = vScene.layers.get(name);
        if (!layer) {
          mesh.count = 0;
          continue;
        }
        const n = Math.min(layer.particles.length, MAX_INSTANCES_PER_SPECIES);
        for (let i = 0; i < n; i++) {
          particlePosition(layer.particles[i], wall, pos);
          dummy.position.set(pos[0], pos[1], pos[2]);
          dummy.updateMatrix();
          mesh.setMatrixAt(i, dummy.matrix);
        }
        mesh.count = n;
        mesh.instanceMatrix.needsUpdate = true;
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
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, [sceneRef]);

  return <div ref={mountRef} style={{ width: "100%", height: "100%", cursor: "grab" }} />;
}
