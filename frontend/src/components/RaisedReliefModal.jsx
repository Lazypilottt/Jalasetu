import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

/**
 * 3D Raised-Relief Interactive Surface Viewer
 *
 * Renders an authentic physical raised-relief terrain model using WebGL/Three.js:
 * - Real extruded 3D elevation geometry from the DEM grid
 * - Dynamic hypsometric color ramp (valleys to peaks)
 * - Directional sunlight casting shadows across ridges and hollows
 * - Interactive orbit, rotation, tilt, and vertical elevation exaggeration
 * - Pond excavation sweet-spot and catchment highlight
 */
export default function RaisedReliefModal({
  isOpen,
  onClose,
  demMesh,
  analysisData,
}) {
  const mountRef = useRef(null);
  const [exaggeration, setExaggeration] = useState(2.5);
  const [isWireframe, setIsWireframe] = useState(false);
  const [sunAngle, setSunAngle] = useState(315);
  const sceneRef = useRef(null);
  const meshRef = useRef(null);
  const lightRef = useRef(null);

  useEffect(() => {
    if (!isOpen || !mountRef.current || !demMesh || !demMesh.grid) return;

    const container = mountRef.current;
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 550;

    // 1. Scene setup
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a); // Slate-900
    sceneRef.current = scene;

    // 2. Camera setup
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.set(0, -90, 80);
    camera.lookAt(0, 0, 0);

    // 3. WebGL Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.innerHTML = '';
    container.appendChild(renderer.domElement);

    // 4. Lighting (Simulating cartographic 315° NW hillshade illumination)
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.45);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xfff7ed, 1.2);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 1024;
    dirLight.shadow.mapSize.height = 1024;
    scene.add(dirLight);
    lightRef.current = dirLight;

    const rad = (sunAngle * Math.PI) / 180;
    dirLight.position.set(Math.cos(rad) * 100, Math.sin(rad) * 100, 70);

    // 5. Construct 3D Elevation Mesh from demMesh.grid
    const grid = demMesh.grid; // 2D array [rows][cols]
    const rows = grid.length;
    const cols = grid[0].length;
    const planeWidth = 70;
    const planeHeight = (planeWidth * rows) / cols;

    const geometry = new THREE.PlaneGeometry(planeWidth, planeHeight, cols - 1, rows - 1);
    const posAttr = geometry.attributes.position;

    const minElev = demMesh.elevation_min || 0;
    const maxElev = demMesh.elevation_max || 100;
    const span = Math.max(1, maxElev - minElev);

    // Color ramp palette: Lush Valley (Teal) -> Mid Slope (Ochre) -> Ridge (Terracotta/Snow)
    const colorLow = new THREE.Color(0x10b981);  // Emerald
    const colorMid = new THREE.Color(0xf59e0b);  // Amber
    const colorHigh = new THREE.Color(0xe11d48); // Rose / Ridge
    const colors = [];

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        const elev = grid[r][c];
        const norm = Math.max(0, Math.min(1, (elev - minElev) / span));

        // Z-axis displacement (scaled by relief and exaggeration)
        const zDisplacement = norm * 15 * (exaggeration / 2.0);
        posAttr.setZ(idx, zDisplacement);

        // Hypsometric tinting color interpolation
        let vertColor;
        if (norm < 0.5) {
          vertColor = colorLow.clone().lerp(colorMid, norm * 2);
        } else {
          vertColor = colorMid.clone().lerp(colorHigh, (norm - 0.5) * 2);
        }
        colors.push(vertColor.r, vertColor.g, vertColor.b);
      }
    }

    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    geometry.computeVertexNormals();

    const material = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.65,
      metalness: 0.1,
      wireframe: isWireframe,
      side: THREE.DoubleSide,
    });

    const terrainMesh = new THREE.Mesh(geometry, material);
    terrainMesh.receiveShadow = true;
    terrainMesh.castShadow = true;
    scene.add(terrainMesh);
    meshRef.current = terrainMesh;

    // 6. Recommended Pond Marker in 3D Space
    if (analysisData?.recommended_site && demMesh.bounds) {
      const site = analysisData.recommended_site;
      const [minLon, minLat, maxLon, maxLat] = demMesh.bounds;
      const lonSpan = maxLon - minLon;
      const latSpan = maxLat - minLat;

      if (lonSpan > 0 && latSpan > 0) {
        const u = (site.longitude - minLon) / lonSpan; // 0 to 1
        const v = (site.latitude - minLat) / latSpan;   // 0 to 1

        const siteX = (u - 0.5) * planeWidth;
        const siteY = (v - 0.5) * planeHeight;
        const siteNorm = Math.max(0, Math.min(1, ((site.elevation_m || minElev) - minElev) / span));
        const siteZ = siteNorm * 15 * (exaggeration / 2.0) + 1.2;

        // Shiny cyan water reservoir cylinder marker
        const pondGeo = new THREE.CylinderGeometry(2.5, 2.5, 0.8, 24);
        const pondMat = new THREE.MeshStandardMaterial({
          color: 0x06b6d4, // Cyan water
          roughness: 0.15,
          metalness: 0.8,
          emissive: 0x0891b2,
          emissiveIntensity: 0.4,
        });
        const pondMarker = new THREE.Mesh(pondGeo, pondMat);
        pondMarker.rotation.x = Math.PI / 2;
        pondMarker.position.set(siteX, siteY, siteZ);
        scene.add(pondMarker);

        // Marker pin stem
        const pinGeo = new THREE.CylinderGeometry(0.3, 0.3, 8, 12);
        const pinMat = new THREE.MeshBasicMaterial({ color: 0xf59e0b });
        const pin = new THREE.Mesh(pinGeo, pinMat);
        pin.rotation.x = Math.PI / 2;
        pin.position.set(siteX, siteY, siteZ + 4);
        scene.add(pin);
      }
    }

    // 7. Interactive Mouse Drag / Tilt Controls
    let isDragging = false;
    let prevMouseX = 0;
    let prevMouseY = 0;
    let rotationZ = 0;
    let rotationX = -0.4;

    const onMouseDown = (e) => {
      isDragging = true;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;
    };

    const onMouseMove = (e) => {
      if (!isDragging) return;
      const dx = e.clientX - prevMouseX;
      const dy = e.clientY - prevMouseY;
      prevMouseX = e.clientX;
      prevMouseY = e.clientY;

      rotationZ += dx * 0.01;
      rotationX = Math.max(-1.4, Math.min(0.2, rotationX + dy * 0.01));

      terrainMesh.rotation.z = rotationZ;
      terrainMesh.rotation.x = rotationX;
    };

    const onMouseUp = () => {
      isDragging = false;
    };

    const onWheel = (e) => {
      e.preventDefault();
      camera.position.z = Math.max(30, Math.min(180, camera.position.z + e.deltaY * 0.08));
    };

    container.addEventListener('mousedown', onMouseDown);
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    container.addEventListener('wheel', onWheel, { passive: false });

    // 8. Animation Render Loop
    let animId;
    const animate = () => {
      animId = requestAnimationFrame(animate);
      renderer.render(scene, camera);
    };
    animate();

    // 9. Resize observer
    const resizeObserver = new ResizeObserver(() => {
      if (!container) return;
      const newW = container.clientWidth;
      const newH = container.clientHeight;
      camera.aspect = newW / newH;
      camera.updateProjectionMatrix();
      renderer.setSize(newW, newH);
    });
    resizeObserver.observe(container);

    return () => {
      cancelAnimationFrame(animId);
      container.removeEventListener('mousedown', onMouseDown);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      container.removeEventListener('wheel', onWheel);
      resizeObserver.disconnect();
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      container.innerHTML = '';
    };
  }, [isOpen, demMesh, exaggeration, isWireframe, sunAngle, analysisData]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="raised-relief-modal-card">
        {/* Modal Header */}
        <div className="modal-header">
          <div className="modal-title-group">
            <span className="modal-badge-icon">⛰️</span>
            <div>
              <h2 id="modal-title" className="modal-title">3D Raised-Relief Terrain Surface</h2>
              <span className="modal-subtitle">
                Interactive elevation mesh with hypsometric tinting, hillshade lighting, and optimal pond siting
              </span>
            </div>
          </div>
          <button type="button" className="btn-close-modal" onClick={onClose} aria-label="Close modal">
            ✕
          </button>
        </div>

        {/* Modal Controls Bar */}
        <div className="modal-toolbar">
          <div className="toolbar-group">
            <label className="toolbar-label">
              Elevation Relief Exaggeration: <strong>{exaggeration.toFixed(1)}×</strong>
              <input
                type="range"
                min="0.5"
                max="6.0"
                step="0.5"
                value={exaggeration}
                onChange={(e) => setExaggeration(parseFloat(e.target.value))}
                className="toolbar-slider"
              />
            </label>
          </div>

          <div className="toolbar-group">
            <label className="toolbar-label">
              Sun Illumination Angle: <strong>{sunAngle}°</strong>
              <input
                type="range"
                min="0"
                max="360"
                step="15"
                value={sunAngle}
                onChange={(e) => setSunAngle(parseInt(e.target.value, 10))}
                className="toolbar-slider"
              />
            </label>
          </div>

          <div className="toolbar-group-actions">
            <button
              type="button"
              className={`btn btn-sm ${isWireframe ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setIsWireframe((prev) => !prev)}
            >
              {isWireframe ? 'Shaded View' : 'Wireframe'}
            </button>
          </div>
        </div>

        {/* 3D WebGL Canvas Container */}
        <div className="webgl-canvas-container" ref={mountRef}></div>

        {/* Modal Footer Info */}
        <div className="modal-footer">
          <div className="footer-elevation-legend">
            <span className="legend-label">Elevation Scale:</span>
            <div className="color-ramp-bar"></div>
            <div className="legend-values">
              <span>{demMesh?.elevation_min ? `${demMesh.elevation_min}m (Valleys)` : 'Low'}</span>
              <span>{demMesh?.elevation_max ? `${demMesh.elevation_max}m (Ridges)` : 'High'}</span>
            </div>
          </div>
          <div className="footer-controls-hint">
            <span>🖱️ Drag to rotate & tilt | Scroll to zoom in/out</span>
          </div>
        </div>
      </div>
    </div>
  );
}
