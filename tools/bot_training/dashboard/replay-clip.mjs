import { clock, isDiscontinuity, positionAt } from "./route-playback.mjs";

export const CLIP_LIMIT_BYTES = 20_000_000;
export const CLIP_SECONDS = 30;
const FPS = 24;
const WIDTH = 720;
const HEIGHT = 448;
const TOP = 48;
const FOOTER = 26;
const MARKS = { "Flag contact": "◆", "Flag pickup": "▲", "Flag released": "□",
  Capture: "★", Death: "✕", "Death · last known position": "✕" };

export function clipRange(time, duration, fullReplay) {
  const start = fullReplay ? 0 : Math.max(0, Math.min(time, duration));
  const end = fullReplay ? duration : Math.min(duration, start + CLIP_SECONDS);
  return { start, end, seconds: Math.min(CLIP_SECONDS, end - start) };
}

async function loadTerrain(url, signal) {
  if (!url || new URL(url, location.href).origin !== location.origin) return null;
  const image = new Image();
  image.src = url;
  let timer;
  try {
    return await Promise.race([
      image.decode().then(() => image, () => null),
      new Promise(resolve => { timer = setTimeout(() => resolve(null), 3000); }),
    ]);
  } finally {
    clearTimeout(timer);
    signal.throwIfAborted();
  }
}

function makePainter(canvas, { routes, landmarks, events, project, terrain, image, title, focused, scaleMeters, scale }) {
  const context = canvas.getContext("2d", { alpha: false });
  const background = document.createElement("canvas");
  background.width = canvas.width;
  background.height = canvas.height;
  const base = background.getContext("2d", { alpha: false });
  const zoom = canvas.width / WIDTH;
  base.scale(zoom, zoom);
  context.scale(zoom, zoom);
  base.fillStyle = "#f6f9fa";
  base.fillRect(0, 0, WIDTH, HEIGHT + TOP + FOOTER);
  base.fillStyle = "#112a32";
  base.fillRect(0, 0, WIDTH, TOP);
  base.font = "600 18px system-ui, sans-serif";
  base.fillStyle = "#f8fafc";
  base.fillText(title, 16, 30, WIDTH - 180);

  base.save();
  base.translate(0, TOP);
  base.beginPath();
  base.rect(0, 0, WIDTH, HEIGHT);
  base.clip();
  if (image && terrain) {
    const [left, top] = project(terrain.min_x, terrain.max_y);
    const [right, bottom] = project(terrain.max_x, terrain.min_y);
    base.globalAlpha = .8;
    base.drawImage(image, left, top, right - left, bottom - top);
    base.globalAlpha = 1;
  } else {
    base.strokeStyle = "#dbe5e8";
    base.lineWidth = .65;
    base.beginPath();
    for (let x = 36; x < WIDTH; x += 36) { base.moveTo(x, 0); base.lineTo(x, HEIGHT); }
    for (let y = 36; y < HEIGHT; y += 36) { base.moveTo(0, y); base.lineTo(WIDTH, y); }
    base.stroke();
  }
  const paths = routes.map(route => {
    const points = route.samples.map((point, i) => ({
      xy: project(point.world_x, point.world_y),
      move: i === 0 || isDiscontinuity(route.samples[i - 1], point),
    }));
    const dash = route.index >= 20 ? [2, 3] : route.index >= 10 ? [5, 3] : [];
    base.globalAlpha = .2;
    base.strokeStyle = route.color;
    base.setLineDash(dash);
    base.lineWidth = 1.4;
    base.stroke(new Path2D(route.commands.join(" ")));
    return { route, points, dash, trail: new Path2D(), cursor: 0 };
  });
  base.globalAlpha = 1;
  base.setLineDash([]);
  base.font = "600 10px system-ui, sans-serif";
  for (const point of landmarks) {
    const [x, y] = project(point.x, point.y);
    base.fillStyle = point.team === 1 ? "#0875d3" : "#c91f47";
    if (point.kind === "flag") {
      base.beginPath();
      base.moveTo(x - 4, y + 6);
      base.lineTo(x - 4, y - 7);
      base.lineTo(x + 7, y - 7);
      base.lineTo(x + 2, y - 1);
      base.lineTo(x - 4, y - 1);
      base.fill();
      base.fillText(point.team === 1 ? "Blue flag" : "Red flag", x + 8, y - 1);
    } else base.fillRect(x - 2, y - 2, 4, 4);
  }
  base.restore();

  base.font = "11px system-ui, sans-serif";
  base.fillStyle = "#38515a";
  base.fillText("TRIBES 3 · Bot training   /   Recorded match routes", 16, TOP + HEIGHT + 16);
  base.textAlign = "right";
  base.fillText(scaleMeters.toLocaleString() + " m", WIDTH - 16, TOP + HEIGHT + 16);
  base.fillRect(WIDTH - 65 - scaleMeters * scale, TOP + HEIGHT + 13, scaleMeters * scale, 1.5);

  return (time, end) => {
    context.drawImage(background, 0, 0, WIDTH, HEIGHT + TOP + FOOTER);
    context.font = "600 13px system-ui, sans-serif";
    context.textAlign = "right";
    context.fillStyle = "#c3e7df";
    context.fillText(clock(time) + " / " + clock(end), WIDTH - 16, 29);
    context.save();
    context.translate(0, TOP);
    context.beginPath();
    context.rect(0, 0, WIDTH, HEIGHT);
    context.clip();
    for (const path of paths) {
      const { route, points, dash, trail } = path;
      const head = positionAt(route.samples, time);
      if (!head) continue;
      while (path.cursor <= head.index) {
        const point = points[path.cursor++];
        if (point.move) trail.moveTo(...point.xy);
        else trail.lineTo(...point.xy);
      }
      const [x, y] = project(head.world_x, head.world_y);
      context.strokeStyle = route.color;
      context.lineWidth = focused ? 2.8 : 1.8;
      context.setLineDash(dash);
      context.stroke(trail);
      context.beginPath();
      context.moveTo(...points[head.index].xy);
      context.lineTo(x, y);
      context.stroke();
      context.setLineDash([]);
      context.beginPath();
      context.arc(x, y, head.carrying ? 7 : 5, 0, 2 * Math.PI);
      context.fillStyle = route.color;
      context.fill();
      context.strokeStyle = "#fff";
      context.lineWidth = 1.6;
      context.stroke();
      if (focused || routes.length <= 8) {
        context.textAlign = "center";
        context.font = "600 10px system-ui, sans-serif";
        context.lineWidth = 2.5;
        context.strokeText(route.label, x, y - 10);
        context.fillText(route.label, x, y - 10);
      }
    }
    context.textAlign = "center";
    context.font = "600 12px system-ui, sans-serif";
    for (const event of events) {
      if (event.t > time) break;
      const [x, y] = project(event.x, event.y);
      context.beginPath();
      context.arc(x, y, 7, 0, 2 * Math.PI);
      context.fillStyle = "#f6f9fa";
      context.fill();
      context.strokeStyle = event.route.color;
      context.lineWidth = 1.5;
      context.stroke();
      context.fillStyle = "#19363f";
      context.fillText(MARKS[event.label] ?? "•", x, y + 4);
    }
    context.restore();
  };
}

export async function recordReplayClip(view, range, signal, reportProgress) {
  const canvas = document.createElement("canvas");
  if (!canvas.captureStream || typeof MediaRecorder === "undefined") {
    throw new Error("This browser cannot create MP4 clips. Open the dashboard in Safari, Chrome, or Edge.");
  }
  const mimeType = ["video/mp4;codecs=avc1.42001f", "video/mp4;codecs=avc1", "video/mp4"]
    .find(type => MediaRecorder.isTypeSupported(type));
  if (!mimeType) throw new Error("MP4 export is unavailable in this browser. Try Safari, Chrome, or Edge.");
  if (range.seconds < .25) throw new Error("Move the replay slider back a little to create a clip.");
  canvas.width = 960;
  canvas.height = (HEIGHT + TOP + FOOTER) * 4 / 3;
  const image = await loadTerrain(view.imageUrl, signal);
  signal.throwIfAborted();
  const draw = makePainter(canvas, { ...view, image });
  const stream = canvas.captureStream(FPS);
  let frame;
  try {
    const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 2_000_000 });
    const chunks = [];
    let bytes = 0;
    const blob = await new Promise((resolve, reject) => {
      function finish() {
        cancelAnimationFrame(frame);
        if (recorder.state !== "inactive") recorder.stop();
      }
      function visibility() {
        if (document.hidden) {
          finish();
          reject(new Error("Export stopped when this tab went into the background. Keep it open and try again."));
        }
      }
      function abort() { finish(); reject(signal.reason); }
      function clear() {
        document.removeEventListener("visibilitychange", visibility);
        signal.removeEventListener("abort", abort);
      }
      recorder.ondataavailable = event => {
        bytes += event.data.size;
        if (bytes < CLIP_LIMIT_BYTES && event.data.size) chunks.push(event.data);
        if (bytes >= CLIP_LIMIT_BYTES) finish();
      };
      recorder.onerror = () => { clear(); finish(); reject(new Error("The browser could not encode the MP4.")); };
      recorder.onstop = () => {
        clear();
        if (bytes >= CLIP_LIMIT_BYTES) reject(new Error("This clip exceeded 20 MB. Select a shorter section near the end of the replay."));
        else if (!bytes) reject(new Error("The browser did not produce a video. Try again."));
        else resolve(new Blob(chunks, { type: "video/mp4" }));
      };
      try {
        recorder.start(500);
      } catch (error) {
        reject(error);
        return;
      }
      document.addEventListener("visibilitychange", visibility);
      signal.addEventListener("abort", abort, { once: true });
      const began = performance.now();
      draw(range.start, view.duration);
      let previous = 0, lastPercent = -1;
      function paint(now) {
        const elapsed = Math.min(range.seconds, (now - began) / 1000);
        if (elapsed >= range.seconds || elapsed - previous >= 1 / FPS) {
          try {
            draw(range.start + (range.end - range.start) * elapsed / range.seconds, view.duration);
          } catch (error) {
            finish();
            reject(error);
            return;
          }
          previous = elapsed;
          const percent = Math.floor(elapsed / range.seconds * 20) * 5;
          if (percent !== lastPercent) { reportProgress(percent); lastPercent = percent; }
        }
        if (elapsed >= range.seconds) {
          frame = requestAnimationFrame(finish);
          return;
        }
        frame = requestAnimationFrame(paint);
      }
      frame = requestAnimationFrame(paint);
    });
    return blob;
  } finally {
    cancelAnimationFrame(frame);
    for (const track of stream.getTracks()) track.stop();
  }
}
