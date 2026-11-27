import React, { useEffect, useMemo, useRef, useState } from "react";
import { isDiscontinuity, positionAt, routeBounds } from "./route-playback.mjs";
import { cameraProjector, surfaceHeight, terrainFaces, TEXTURE_SIZE, travelHeading } from "./route-scene.mjs";

function fillPolygon(context, points, color) {
  context.beginPath();
  points.forEach(([x, y], i) => i ? context.lineTo(x, y) : context.moveTo(x, y));
  context.closePath();
  context.fillStyle = color;
  context.fill();
}

function trace(context, project, route, start, end) {
  let previous, drew = false;
  context.beginPath();
  for (const point of route.samples) {
    if (point.t < start) continue;
    if (point.t > end) break;
    const screen = project(point.world_x, point.world_y, point.world_z);
    if (screen) {
      if (drew && previous && !isDiscontinuity(previous, point)) context.lineTo(screen[0], screen[1]);
      else context.moveTo(screen[0], screen[1]);
    }
    previous = point;
    drew = Boolean(screen);
  }
  context.stroke();
}

function drawBot(context, project, head, yaw, color) {
  const heading = [Math.cos(yaw), Math.sin(yaw)];
  const vertex = (forward, right, up) => project(
    head.world_x + heading[0] * forward + heading[1] * right,
    head.world_y + heading[1] * forward - heading[0] * right, head.world_z + up);
  const nose = vertex(2.8, 0, .6), left = vertex(-1, -1.1, .4), right = vertex(-1, 1.1, .4);
  const top = vertex(-.4, 0, 2.0), tail = vertex(-2.1, 0, .5);
  fillPolygon(context, [nose, left, tail, right], "#0b1825");
  fillPolygon(context, [nose, left, top], color);
  fillPolygon(context, [nose, right, top], "#defaff");
  fillPolygon(context, [tail, left, top, right], "#5380a0");
}

export function RouteReplay3D({ route, time, overview }) {
  const canvas = useRef(null);
  const previousAngle = useRef(0);
  const [viewport, setViewport] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [orbit, setOrbit] = useState(0);
  const [showMap, setShowMap] = useState(true);
  const [overlay, setOverlay] = useState(null);
  const head = positionAt(route.samples, time) ?? route.samples[0];
  const startZ = route.samples[0].world_z;
  const ground = showMap ? surfaceHeight(overview, head.world_x, head.world_y) : null;
  const bounds = useMemo(() => overview?.bounds ?? routeBounds([route]), [overview, route]);

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      setViewport({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(canvas.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!overview?.image_url) return;
    const image = new Image();
    image.onload = () => {
      const layer = document.createElement("canvas");
      layer.width = layer.height = TEXTURE_SIZE;
      const context = layer.getContext("2d");
      context.drawImage(image, 0, 0, TEXTURE_SIZE, TEXTURE_SIZE);
      setOverlay({ url: overview.image_url, pixels: context.getImageData(0, 0, TEXTURE_SIZE, TEXTURE_SIZE).data });
    };
    image.src = overview.image_url;
    return () => { image.onload = null; };
  }, [overview?.image_url]);

  const mesh = useMemo(() => terrainFaces(overview, bounds, startZ,
    overlay?.url === overview?.image_url ? overlay?.pixels : null), [overview, bounds, startZ, overlay]);

  useEffect(() => {
    if (!viewport?.width || !viewport?.height) return;
    const { width, height } = viewport;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const element = canvas.current;
    const screenWidth = Math.round(width * dpr), screenHeight = Math.round(height * dpr);
    if (element.width !== screenWidth || element.height !== screenHeight) {
      element.width = screenWidth;
      element.height = screenHeight;
    }
    const context = element.getContext("2d");
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    const sky = context.createLinearGradient(0, 0, 0, height);
    sky.addColorStop(0, "#101e35");
    sky.addColorStop(1, "#405971");
    context.fillStyle = sky;
    context.fillRect(0, 0, width, height);

    const heading = travelHeading(route.samples, time, head) ?? previousAngle.current;
    previousAngle.current = heading;
    const project = cameraProjector(head, heading + orbit, 90 / zoom, width, height);
    if (showMap) {
      const screen = mesh.points.map(point => point[2] === null ? null : project(...point));
      const faces = mesh.faces.flatMap(face => {
        const points = face.vertices.map(i => screen[i]);
        if (!points.every(Boolean) || points.every(p => p[0] < 0) || points.every(p => p[0] > width)
          || points.every(p => p[1] < 0) || points.every(p => p[1] > height)) return [];
        return [{ points, color: face.color, depth: points.reduce((sum, point) => sum + point[2], 0) }];
      }).sort((a, b) => b.depth - a.depth);
      for (const face of faces) {
        fillPolygon(context, face.points, face.color);
        context.strokeStyle = "rgba(206,237,231,.13)";
        context.lineWidth = .65;
        context.stroke();
      }
    }
    context.lineJoin = context.lineCap = "round";
    context.lineWidth = 1.2;
    context.strokeStyle = "rgba(167,223,252,.45)";
    trace(context, project, route, 0, Infinity);
    context.lineWidth = 2.6;
    context.strokeStyle = "#6af4fd";
    trace(context, project, route, time - 15, time);
    if (ground !== null && head.world_z >= ground) {
      const base = project(head.world_x, head.world_y, ground);
      const tip = project(head.world_x, head.world_y, head.world_z);
      if (base && tip) {
        context.beginPath();
        context.moveTo(tip[0], tip[1]); context.lineTo(base[0], base[1]);
        context.strokeStyle = "#fff3a8";
        context.lineWidth = 1;
        context.setLineDash([3, 4]); context.stroke(); context.setLineDash([]);
      }
    }
    drawBot(context, project, head, heading, route.color);
  }, [head, route, viewport, mesh, time, zoom, orbit, showMap, ground]);

  return <section className="training-replay-3d" aria-label="3D bot chase replay">
    <div className="training-map-controls">
      <div className="training-route-toggles">
        <button type="button" aria-label="Orbit camera left" onClick={() => setOrbit(value => value - Math.PI / 8)}>↶</button>
        <button type="button" aria-label="Orbit camera right" onClick={() => setOrbit(value => value + Math.PI / 8)}>↷</button>
        <button type="button" aria-label="Move chase camera closer" disabled={zoom >= 3} onClick={() => setZoom(Math.min(3, zoom * 1.4))}>+</button>
        <button type="button" aria-label="Move chase camera farther" disabled={zoom <= .45} onClick={() => setZoom(Math.max(.45, zoom / 1.4))}>−</button>
        <button type="button" onClick={() => { setOrbit(0); setZoom(1); }}>Reset camera</button>
        <button type="button" aria-pressed={showMap} onClick={() => setShowMap(!showMap)}>Map overlay</button>
      </div>
    </div>
    <div className="training-replay-3d-stage">
      <canvas ref={canvas} aria-label={`Recorded 3D route for ${route.label}`} role="img" />
      <div className="training-replay-3d-hud">
        <strong>{route.label}</strong>
        <span><b>{head.speed.toFixed(1)}</b> km/h</span>
        <span>{head.world_z.toFixed(1)} m world elevation</span>
        {ground !== null && <span>{(head.world_z - ground).toFixed(1)} m above terrain*</span>}
      </div>
    </div>
    <p className="training-route-caption">{showMap && (overview?.relief
      ? "*Estimated from the sampled terrain grid. Buildings and other props are omitted."
      : "Flat reference plane. This map has no terrain heights for the replay.")}</p>
  </section>;
}
