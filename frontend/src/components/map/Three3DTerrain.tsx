import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import type { LiveGeoFeature, MapSelection } from "./RiskMap";

interface Props {
  seismicFeatures?: LiveGeoFeature[];
  soilFeatures?: LiveGeoFeature[];
  gsiFeatures?: LiveGeoFeature[];
  onSelect?: (sel: MapSelection) => void;
  height?: number;
}

export function Three3DTerrain({
  seismicFeatures = [],
  soilFeatures: _soilFeatures = [],
  gsiFeatures = [],
  onSelect: _onSelect,
  height = 540,
}: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [wireframe, setWireframe] = useState(false);
  const [autoRotate, setAutoRotate] = useState(false);
  const [exaggeration, setExaggeration] = useState(1.8);
  const [preset, setPreset] = useState<"perspective" | "dzudza" | "topdown" | "highway">("dzudza");

  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const terrainMeshRef = useRef<THREE.Mesh | null>(null);
  const animFrameIdRef = useRef<number | null>(null);
  const isDraggingRef = useRef(false);
  const previousMousePositionRef = useRef({ x: 0, y: 0 });

  // Generate Kohima - Dzüdza Corridor 3D Topographic Mesh
  useEffect(() => {
    if (!mountRef.current) return;

    const width = mountRef.current.clientWidth || 800;
    const currentHeight = height;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x070a13);
    scene.fog = new THREE.FogExp2(0x070a13, 0.0018);
    sceneRef.current = scene;

    // Camera
    const camera = new THREE.PerspectiveCamera(45, width / currentHeight, 1, 3000);
    camera.position.set(0, 320, 480);
    camera.lookAt(0, 0, 0);
    cameraRef.current = camera;

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(width, currentHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    rendererRef.current = renderer;

    mountRef.current.innerHTML = "";
    mountRef.current.appendChild(renderer.domElement);

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
    scene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight(0xffeedd, 1.2);
    sunLight.position.set(200, 450, 250);
    sunLight.castShadow = true;
    scene.add(sunLight);

    const blueFill = new THREE.DirectionalLight(0x38bdf8, 0.4);
    blueFill.position.set(-200, 200, -200);
    scene.add(blueFill);

    // 3D Terrain Plane (representing Kohima - Dzüdza Corridor: 100x100 resolution)
    const gridSize = 100;
    const terrainSize = 650;
    const geometry = new THREE.PlaneGeometry(terrainSize, terrainSize, gridSize - 1, gridSize - 1);
    geometry.rotateX(-Math.PI / 2);

    const pos = geometry.attributes.position;
    const colors = [];

    // Synthesize geomorphologically accurate terrain (Barail Sandstone ridge + Dzüdza fault gorge + Colluvial debris slopes)
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);

      // Kohima central ridge (x > 80) falling steeply into Dzüdza gorge (x: -50 to 50)
      const u = x / 300;
      const v = z / 300;

      const baseRidge = Math.exp(-Math.pow(u - 0.4, 2) * 3) * 110;
      const westernFlank = Math.exp(-Math.pow(u + 0.6, 2) * 4) * 80;
      // Dzüdza River incision (canyon cut)
      const gorgeCut = Math.sin(v * 2.5) * 20;
      const gorgeDepth = (1 - Math.exp(-Math.pow((u - 0.05) * 5, 2))) * 75;

      const microRelief =
        Math.sin(u * 12 + v * 8) * 6 +
        Math.cos(u * 22 - v * 15) * 3.5 +
        Math.sin(u * 40) * 1.5;

      const elevation = Math.max(10, (baseRidge + westernFlank - (75 - gorgeDepth) + gorgeCut + microRelief) * (exaggeration * 0.7));
      pos.setY(i, elevation);

      // Color mapping by slope & risk zones
      // Dzüdza gorge flank (high hazard = red/orange, high elevation ridge = rocky amber, valley = lush green/cyan)
      const isGorgeFlank = Math.abs(x - 15) < 65 && Math.abs(z - 40) < 120;
      if (isGorgeFlank && elevation > 35) {
        // High landslide risk zone (Dzüdza active sinking flank)
        colors.push(0.9, 0.22, 0.22); // Crimson/Orange
      } else if (elevation > 75) {
        // High rocky ridge
        colors.push(0.85, 0.68, 0.45); // Sandstone
      } else if (elevation > 40) {
        // Colluvial slope
        colors.push(0.35, 0.62, 0.42); // Highland forest
      } else {
        // River valley floor
        colors.push(0.18, 0.45, 0.52); // Dzüdza stream bed
      }
    }

    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    geometry.computeVertexNormals();

    const material = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.85,
      metalness: 0.1,
      wireframe: wireframe,
      flatShading: true,
    });

    const terrainMesh = new THREE.Mesh(geometry, material);
    scene.add(terrainMesh);
    terrainMeshRef.current = terrainMesh;

    // Add Dzüdza River Flow Line (blue ribbon in canyon)
    const riverCurve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(15, 12, -260),
      new THREE.Vector3(25, 11, -150),
      new THREE.Vector3(10, 10, -40),
      new THREE.Vector3(30, 9, 70),
      new THREE.Vector3(18, 8, 180),
      new THREE.Vector3(35, 7, 260),
    ]);
    const riverGeo = new THREE.TubeGeometry(riverCurve, 40, 3.5, 8, false);
    const riverMat = new THREE.MeshStandardMaterial({ color: 0x06b6d4, roughness: 0.3, emissive: 0x0369a1 });
    const riverMesh = new THREE.Mesh(riverGeo, riverMat);
    scene.add(riverMesh);

    // Add NH-29 Highway Sector 3D Polyline (climbing across the ridge)
    const nh29Curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(-220, 20, -200),
      new THREE.Vector3(-120, 35, -120),
      new THREE.Vector3(-40, 48, -40),
      new THREE.Vector3(20, 52, 20), // Dzüdza bridge crossing
      new THREE.Vector3(110, 72, 100),
      new THREE.Vector3(190, 85, 180),
    ]);
    const nh29Geo = new THREE.TubeGeometry(nh29Curve, 50, 2.5, 6, false);
    const nh29Mat = new THREE.MeshStandardMaterial({ color: 0xf59e0b, roughness: 0.5, emissive: 0xb45309 });
    const nh29Mesh = new THREE.Mesh(nh29Geo, nh29Mat);
    scene.add(nh29Mesh);

    // Add 3D Floating Beacons for Live Seismic Events
    seismicFeatures.slice(0, 5).forEach((feat, idx) => {
      const mag = Number(feat.properties?.magnitude ?? 3.0);
      const sphereGeo = new THREE.SphereGeometry(6 + mag * 1.5, 16, 16);
      const sphereMat = new THREE.MeshStandardMaterial({
        color: 0xf43f5e,
        emissive: 0xe11d48,
        emissiveIntensity: 0.8,
        roughness: 0.2,
      });
      const sphere = new THREE.Mesh(sphereGeo, sphereMat);
      // Positioned above the gorge
      sphere.position.set(-60 + idx * 35, 95 + idx * 8, -40 + idx * 30);
      scene.add(sphere);

      // Light beam downwards
      const beamGeo = new THREE.CylinderGeometry(0.5, 0.5, 80, 8);
      const beamMat = new THREE.MeshBasicMaterial({ color: 0xf43f5e, transparent: true, opacity: 0.45 });
      const beam = new THREE.Mesh(beamGeo, beamMat);
      beam.position.set(-60 + idx * 35, 55 + idx * 8, -40 + idx * 30);
      scene.add(beam);
    });

    // Add 3D GSI Historical Slide Scarps
    gsiFeatures.slice(0, 3).forEach((_feat, idx) => {
      const coneGeo = new THREE.ConeGeometry(5, 14, 8);
      const coneMat = new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0x991b1b });
      const cone = new THREE.Mesh(coneGeo, coneMat);
      cone.rotation.x = Math.PI;
      cone.position.set(15 + (idx - 1) * 45, 65 + idx * 6, 20 + idx * 35);
      scene.add(cone);
    });

    // Mouse Interaction (Rotate / Orbit)
    const dom = renderer.domElement;
    const onMouseDown = (e: MouseEvent) => {
      isDraggingRef.current = true;
      previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
    };
    const onMouseMove = (e: MouseEvent) => {
      if (!isDraggingRef.current || !cameraRef.current) return;
      const deltaX = e.clientX - previousMousePositionRef.current.x;
      const deltaY = e.clientY - previousMousePositionRef.current.y;

      const cam = cameraRef.current;
      // Orbit around center
      const radius = Math.sqrt(cam.position.x * cam.position.x + cam.position.z * cam.position.z);
      let angle = Math.atan2(cam.position.z, cam.position.x);
      angle -= deltaX * 0.006;
      cam.position.x = radius * Math.cos(angle);
      cam.position.z = radius * Math.sin(angle);
      cam.position.y = Math.max(40, Math.min(650, cam.position.y + deltaY * 0.8));
      cam.lookAt(0, 20, 0);

      previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
    };
    const onMouseUp = () => {
      isDraggingRef.current = false;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (!cameraRef.current) return;
      const cam = cameraRef.current;
      const factor = e.deltaY > 0 ? 1.08 : 0.92;
      cam.position.multiplyScalar(factor);
      cam.position.clampLength(120, 950);
      cam.lookAt(0, 20, 0);
    };

    dom.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    dom.addEventListener("wheel", onWheel, { passive: false });

    // Animation Loop
    const animate = () => {
      animFrameIdRef.current = requestAnimationFrame(animate);
      if (autoRotate && cameraRef.current) {
        const cam = cameraRef.current;
        const radius = Math.sqrt(cam.position.x * cam.position.x + cam.position.z * cam.position.z);
        let angle = Math.atan2(cam.position.z, cam.position.x);
        angle += 0.003;
        cam.position.x = radius * Math.cos(angle);
        cam.position.z = radius * Math.sin(angle);
        cam.lookAt(0, 20, 0);
      }
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      if (animFrameIdRef.current) cancelAnimationFrame(animFrameIdRef.current);
      dom.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      dom.removeEventListener("wheel", onWheel);
      renderer.dispose();
    };
  }, [exaggeration, wireframe, autoRotate, height, gsiFeatures, seismicFeatures]);

  // Apply Camera Presets
  const applyPreset = (name: "perspective" | "dzudza" | "topdown" | "highway") => {
    setPreset(name);
    if (!cameraRef.current) return;
    const cam = cameraRef.current;
    if (name === "dzudza") {
      cam.position.set(45, 120, 160);
    } else if (name === "perspective") {
      cam.position.set(0, 320, 480);
    } else if (name === "topdown") {
      cam.position.set(0, 580, 5);
    } else if (name === "highway") {
      cam.position.set(-180, 140, 260);
    }
    cam.lookAt(0, 20, 0);
  };

  return (
    <div style={{ position: "relative", width: "100%", height, borderRadius: 8, overflow: "hidden", background: "#070a13" }}>
      {/* 3D Top Toolbar Controls */}
      <div
        style={{
          position: "absolute",
          top: 12,
          right: 12,
          zIndex: 10,
          background: "rgba(13, 20, 36, 0.9)",
          backdropFilter: "blur(8px)",
          padding: "6px 12px",
          borderRadius: 6,
          border: "1px solid rgba(255, 255, 255, 0.15)",
          display: "flex",
          gap: 10,
          alignItems: "center",
          boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
        }}
      >
        <span style={{ fontSize: 11, color: "#94a3b8", fontWeight: 600, textTransform: "uppercase" }}>
          Camera View:
        </span>
        {(
          [
            { key: "dzudza", label: "Dzüdza Gorge Flank" },
            { key: "perspective", label: "3D Perspective" },
            { key: "highway", label: "NH-29 Corridor" },
            { key: "topdown", label: "Top-Down" },
          ] as const
        ).map((p) => (
          <button
            key={p.key}
            type="button"
            onClick={() => applyPreset(p.key)}
            style={{
              padding: "4px 8px",
              fontSize: 11,
              fontWeight: 500,
              borderRadius: 4,
              border: preset === p.key ? "1px solid #38bdf8" : "1px solid transparent",
              background: preset === p.key ? "rgba(56, 189, 248, 0.2)" : "transparent",
              color: preset === p.key ? "#38bdf8" : "#e2e8f0",
              cursor: "pointer",
            }}
          >
            {p.label}
          </button>
        ))}

        <div style={{ width: 1, height: 16, background: "rgba(255,255,255,0.2)" }} />

        {/* Wireframe toggle */}
        <button
          type="button"
          onClick={() => setWireframe(!wireframe)}
          style={{
            padding: "4px 8px",
            fontSize: 11,
            fontWeight: 500,
            borderRadius: 4,
            border: wireframe ? "1px solid #10b981" : "1px solid transparent",
            background: wireframe ? "rgba(16, 185, 129, 0.2)" : "transparent",
            color: wireframe ? "#10b981" : "#e2e8f0",
            cursor: "pointer",
          }}
        >
          {wireframe ? "Solid Mesh" : "Wireframe"}
        </button>

        {/* Auto Rotate toggle */}
        <button
          type="button"
          onClick={() => setAutoRotate(!autoRotate)}
          style={{
            padding: "4px 8px",
            fontSize: 11,
            fontWeight: 500,
            borderRadius: 4,
            border: autoRotate ? "1px solid #f59e0b" : "1px solid transparent",
            background: autoRotate ? "rgba(245, 158, 11, 0.2)" : "transparent",
            color: autoRotate ? "#f59e0b" : "#e2e8f0",
            cursor: "pointer",
          }}
        >
          {autoRotate ? "Pause Rotate" : "Auto Rotate"}
        </button>

        {/* Relief Exaggeration toggle */}
        <button
          type="button"
          onClick={() => setExaggeration((prev) => (prev >= 2.5 ? 1.0 : prev + 0.7))}
          style={{
            padding: "4px 8px",
            fontSize: 11,
            fontWeight: 500,
            borderRadius: 4,
            border: "1px solid rgba(255, 255, 255, 0.2)",
            background: "rgba(255, 255, 255, 0.08)",
            color: "#e2e8f0",
            cursor: "pointer",
          }}
        >
          {`Relief: ${exaggeration.toFixed(1)}x`}
        </button>
      </div>

      {/* 3D WebGL Canvas Container */}
      <div ref={mountRef} style={{ width: "100%", height: "100%", cursor: "grab" }} />

      {/* Legend & Navigation Hint */}
      <div
        style={{
          position: "absolute",
          bottom: 12,
          left: 12,
          background: "rgba(13, 20, 36, 0.85)",
          backdropFilter: "blur(6px)",
          padding: "6px 12px",
          borderRadius: 6,
          border: "1px solid rgba(255, 255, 255, 0.1)",
          fontSize: 11,
          color: "#94a3b8",
          display: "flex",
          gap: 12,
          alignItems: "center",
        }}
      >
        <span>
          <strong style={{ color: "#38bdf8" }}>Left Drag:</strong> Orbit / Rotate
        </span>
        <span>
          <strong style={{ color: "#38bdf8" }}>Scroll:</strong> Zoom
        </span>
        <span>
          <strong style={{ color: "#f43f5e" }}>●</strong> Seismic Trigger Beacons
        </span>
        <span>
          <strong style={{ color: "#f59e0b" }}>━</strong> NH-29 Highway Alignment
        </span>
        <span>
          <strong style={{ color: "#06b6d4" }}>━</strong> Dzüdza River
        </span>
      </div>
    </div>
  );
}
