import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { clock, isDiscontinuity, positionAt, routeBounds } from "./route-playback.mjs";
import { clipRange, recordReplayClip } from "./replay-clip.mjs";
import { DataComponent, Icon } from "../../data-app-public.jsx";
import { RouteReplay3D } from "./RouteReplay3D.jsx";

const colors = ["#1883dc", "#df7822", "#2b9e78", "#a364d3", "#d65a73", "#afb232", "#3998ae", "#ac5a3a", "#6977df", "#cb5ba5"];
const eventMarks = { "Flag contact": "◆", "Flag pickup": "▲", "Flag released": "□",
  "Capture": "★", "Death": "✕", "Death · last known position": "✕" };
function ReplayDownload({ time, view, filename, pause }) {
  const [selection, setSelection] = useState("clip");
  const [progress, setProgress] = useState(null);
  const [download, setDownload] = useState(null);
  const [error, setError] = useState("");
  const recording = useRef(null);
  useEffect(() => () => recording.current?.abort(), []);
  useEffect(() => () => { if (download) URL.revokeObjectURL(download.url); }, [download]);
  const range = clipRange(time, view.duration, selection === "full");
  const active = progress !== null;

  async function create() {
    if (recording.current) return;
    const controller = new AbortController();
    recording.current = controller;
    setDownload(null);
    setError("");
    setProgress(0);
    pause();
    try {
      const video = await recordReplayClip(view, range, controller.signal, setProgress);
      if (!controller.signal.aborted) {
        const suffix = selection === "full" ? "full" : Math.floor(range.start) + "s";
        setDownload({ url: URL.createObjectURL(video), filename: filename + "-" + suffix + ".mp4", size: video.size });
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure.message || "Could not create the replay clip.");
    } finally {
      if (recording.current === controller) {
        recording.current = null;
        if (!controller.signal.aborted) setProgress(null);
      }
    }
  }

  return <div className="training-replay-download">
    <label>Video length<select value={selection} disabled={active} onChange={event => {
      setSelection(event.target.value);
      setDownload(null);
      setError("");
    }}>
      <option value="clip">30 sec from playhead</option>
      <option value="full">Full replay (up to 30 sec)</option>
    </select></label>
    {active ? <button type="button" className="training-button" onClick={() => {
      recording.current?.abort();
      setProgress(null);
    }}>Cancel</button> : <button type="button" className="training-button" disabled={range.seconds < .25}
      onClick={create}>Create MP4</button>}
    {active && <p role="status">Creating video… {progress}% · Keep this tab open.</p>}
    {error && <p role="alert">{error}</p>}
    {download && <p role="status"><a className="training-button training-primary" href={download.url}
      download={download.filename}>Download MP4</a> <span>{(download.size / 1_000_000).toFixed(2)} MB</span></p>}
  </div>;
}

export function MatchRoutes({ phase, tracks, picker, note, provided, title = "Match routes", clipTitle, id, onReview }) {
  const [result, setResult] = useState(null);
  const [focused, setFocused] = useState("");
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [overview, setOverview] = useState(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [view, setView] = useState("routes");
  const [dimension, setDimension] = useState("2d");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [panOnTouch, setPanOnTouch] = useState(false);
  const drag = useRef(null);
  const gridId = useId().replaceAll(":", "") + "-route-grid";
  const keys = tracks.map(({ attempt, bot }) => phase + "/" + attempt + (bot ? "/" + bot : "")).join(" ");
  useEffect(() => {
    setPlaying(false); setPosition(0); setSelectedEvent(null); setFocused("");
    setPan({ x: 0, y: 0 }); setZoom(1);
    if (!keys || provided) return;
    const controller = new AbortController();
    async function loadRoute(key) {
      const options = { signal: controller.signal, cache: "no-store" };
      const url = "/api/trace/" + key;
      let response;
      try {
        response = await fetch(url, options);
        if (response.status >= 500) throw new Error("Trace unavailable");
      } catch (error) {
        if (controller.signal.aborted) throw error;
        response = await fetch(url, options);
      }
      if (!response.ok) throw new Error("Trace unavailable");
      return response.json();
    }
    async function loadMatch() {
      const traces = [];
      const requests = keys.split(" ");
      for (let i = 0; i < requests.length && !controller.signal.aborted; i += 4) {
        traces.push(...await Promise.allSettled(requests.slice(i, i + 4).map(loadRoute)));
      }
      if (!controller.signal.aborted) setResult({ keys, traces });
    }
    loadMatch();
    return () => controller.abort();
  }, [keys, Boolean(provided)]);

  const traces = useMemo(() => provided ? provided.map(value => ({ status: "fulfilled", value }))
    : result?.keys === keys ? result.traces : null, [provided, result, keys]);
  const routes = useMemo(() => (traces ?? []).flatMap((trace, index) => {
    if (trace.status !== "fulfilled") return [];
    const samples = trace.value.samples.filter(point => Number.isFinite(point.world_x) &&
      Number.isFinite(point.world_y) && Number.isFinite(point.t)).sort((a, b) => a.t - b.t);
    if (!samples.length) return [];
    return [{ ...tracks[index], ...trace.value, samples, index, color: colors[index % colors.length] }];
  }), [traces, keys]);
  const mapId = routes[0]?.map_id;
  useEffect(() => {
    setOverview(null); setImageFailed(false);
    if (!mapId) return;
    const controller = new AbortController();
    fetch("/api/map/" + encodeURIComponent(mapId), { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(data => { if (!controller.signal.aborted) setOverview(data); })
      .catch(() => {});
    return () => controller.abort();
  }, [mapId]);
  const duration = routes.reduce((end, route) => Math.max(end, route.samples.at(-1).t), 0);
  const time = Math.min(position, duration);
  useEffect(() => {
    if (!playing) return;
    let frame, previous;
    function advance(now) {
      if (previous !== undefined && now - previous >= 33) {
        const elapsed = Math.min(.25, (now - previous) / 1000) * rate;
        setPosition(value => Math.min(duration, value + elapsed));
        previous = now;
      }
      if (previous === undefined) previous = now;
      frame = requestAnimationFrame(advance);
    }
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  }, [playing, rate, duration]);
  useEffect(() => { if (playing && time >= duration) setPlaying(false); }, [time, duration, playing]);

  const visible = focused ? routes.filter(route => route.label === focused) : routes;
  const elevated = useMemo(() => routes.filter(route => route.samples.every(point => Number.isFinite(point.world_z))), [routes]);
  const route3D = elevated.find(route => route.label === focused) ?? elevated[0];
  const chase = dimension === "3d" && Boolean(route3D);
  const sourceRows = useMemo(() => visible.flatMap(route => route.samples.map(sample => ({ ...sample, bot: route.label }))), [routes, focused]);
  const landmarks = overview?.landmarks ?? [];
  const bounds = useMemo(() => view === "map" && overview?.bounds ? overview.bounds
    : routeBounds(routes, landmarks.filter(point => point.kind === "flag")), [routes, overview, view]);
  const scale = Math.min(668 / (bounds.max_x - bounds.min_x), 400 / (bounds.max_y - bounds.min_y)) * zoom;
  const centerX = (bounds.min_x + bounds.max_x) / 2 + pan.x;
  const centerY = (bounds.min_y + bounds.max_y) / 2 + pan.y;
  const project = (x, y) => [360 + (x - centerX) * scale, 224 - (y - centerY) * scale];
  const geometry = useMemo(() => visible.map(route => ({ ...route,
    commands: route.samples.map((point, i) => {
      const [x, y] = project(point.world_x, point.world_y);
      return (i && !isDiscontinuity(route.samples[i - 1], point) ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1);
    }),
    arrows: route.samples.flatMap((point, i) => {
      if (!i || i % Math.max(4, Math.floor(route.samples.length / 6)) || isDiscontinuity(route.samples[i - 1], point)) return [];
      const [x, y] = project(point.world_x, point.world_y);
      const [px, py] = project(route.samples[i - 1].world_x, route.samples[i - 1].world_y);
      if (Math.hypot(x - px, y - py) < 1) return [];
      return [{ x, y, angle: Math.atan2(y - py, x - px) * 180 / Math.PI, time: point.t }];
    }),
  })), [routes, focused, scale, centerX, centerY]);
  const events = useMemo(() => {
    const shown = focused ? routes.filter(route => route.label === focused) : routes;
    return shown.flatMap(route => (route.events ?? []).map((event, index) =>
      ({ ...event, route, id: route.index + "-" + index }))).sort((a, b) => a.t - b.t);
  }, [routes, focused]);
  const shownEvents = events.filter(event => event.t <= time);
  const activeEvent = shownEvents.find(event => event.id === selectedEvent);
  const hasImage = overview?.image_url && !imageFailed;
  const imageBounds = overview?.bounds;
  const imageOrigin = imageBounds && project(imageBounds.min_x, imageBounds.max_y);
  const tickSize = 10 ** Math.floor(Math.log10(100 / scale));
  const scaleMeters = tickSize * ([5, 2, 1].find(value => value * tickSize * scale <= 100) ?? 1);
  const clipName = "tribes3-" + [mapId ?? "replay", phase, tracks[0]?.attempt].filter(Boolean).join("-")
    .replace(/[^a-z0-9_-]+/gi, "-").toLowerCase();

  function seek(value) { onReview?.(); setPlaying(false); setPosition(value); }
  function fit(next) { setView(next); setZoom(1); setPan({ x: 0, y: 0 }); }
  function inspect(event) { setSelectedEvent(event.id); seek(event.t); }
  function move(event) {
    if (!drag.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const pixels = Math.min(rect.width / 720, rect.height / 448);
    setPan({ x: drag.current.x - (event.clientX - drag.current.clientX) / pixels / scale,
      y: drag.current.y + (event.clientY - drag.current.clientY) / pixels / scale });
  }

  return <DataComponent id={id ?? "match-routes-" + phase} title={title} kind="chart" queryId="trial-trace"
    className="training-replay-card" sourceRows={sourceRows} headingLevel={3}>
    <section className="training-route-panel" aria-label={title}>
    <div className="training-session-header">
      <div>{routes.length > 0 && <span>{visible.length} / {tracks.length} routes shown</span>}</div>
      {picker}
    </div>
      <div className="training-replay-controls" aria-label="Route playback">
        <button className="training-button training-primary training-play-control" type="button" data-playing={playing}
          aria-label={playing ? "Pause route playback" : "Play route playback"}
          disabled={duration <= 0} onClick={() => {
            onReview?.();
            if (!playing && time >= duration) setPosition(0);
            setPlaying(!playing);
          }}>
          {playing ? "Pause" : "Play"}
        </button>
        <button className="training-button training-icon-button training-restart-control" type="button"
          aria-label="Restart route playback" disabled={duration <= 0} onClick={() => seek(0)}><Icon name="refresh" />Restart</button>
        <label>Speed<select aria-label="Playback speed" value={rate} onChange={event => setRate(Number(event.target.value))}>
          {[.25, .5, 1, 2, 4, 8].map(value => <option key={value} value={value}>{value}×</option>)}
        </select></label>
        <output aria-label="Replay time">{clock(time)} / {clock(duration)}</output>
        <input className="training-replay-scrubber" type="range" aria-label="Replay position" min="0" max={duration}
          disabled={duration <= 0} step="0.05" value={time} onChange={event => seek(Number(event.target.value))} />
      </div>
    {!traces ? <p role="status">Loading route traces…</p> : !routes.length ? <p role="status">No routes available for this match.</p> : <>
      {duration > 0 && <ReplayDownload key={keys} time={time} filename={clipName}
        pause={() => { onReview?.(); setPlaying(false); }}
        view={{ routes: geometry, events, landmarks, project, terrain: imageBounds, imageUrl: hasImage ? overview.image_url : null,
          title: clipTitle ?? ((overview?.label ?? mapId ?? title) + (tracks[0]?.attempt ? " · Replay " + tracks[0].attempt : "")),
          focused, scaleMeters, scale, duration }} />}
      <div className="training-route-toggles" role="group" aria-label="Replay perspective">
        <button type="button" aria-pressed={!chase} onClick={() => setDimension("2d")}>Top down</button>
        <button type="button" aria-pressed={chase} disabled={!route3D} onClick={() => setDimension("3d")}>3D chase</button>
      </div>
      {(chase ? elevated : routes).length > 1 && <label className="trial-filter training-replay-bot">Bot to follow
        <select value={chase ? route3D.label : focused} onChange={event => { setFocused(event.target.value); setSelectedEvent(null); }}>
          {!chase && <option value="">All bots</option>}
          {(chase ? elevated : routes).map(route => <option key={route.label} value={route.label}>{route.label}</option>)}
        </select>
      </label>}
      {chase ? <RouteReplay3D key={route3D.label} route={route3D} time={time} overview={overview} /> : <>
      <div className="training-map-controls" aria-label="Map view">
        <div className="training-route-toggles">
          <button type="button" aria-pressed={view === "routes"} onClick={() => fit("routes")}>Fit routes</button>
          {overview?.bounds && <button type="button" aria-pressed={view === "map"} onClick={() => fit("map")}>Full map</button>}
          <button type="button" aria-label="Zoom into map" disabled={zoom >= 16} onClick={() => setZoom(Math.min(16, zoom * 1.5))}>+</button>
          <button type="button" aria-label="Zoom out of map" disabled={zoom <= .5} onClick={() => setZoom(Math.max(.5, zoom / 1.5))}>−</button>
          <button className="training-touch-pan" type="button" aria-pressed={panOnTouch}
            onClick={() => setPanOnTouch(!panOnTouch)}>Pan map</button>
        </div>
        <span>{hasImage ? "Source terrain overview" : "World coordinates"}<span className="training-mouse-hint"> · Drag to pan</span></span>
      </div>
      <svg className="training-route-plot" data-touch-pan={panOnTouch} viewBox="0 0 720 448" role="img" aria-label="Route replay over the map. Bot markers show recorded movement."
        onPointerDown={event => { if (event.button !== 0 || (event.pointerType === "touch" && !panOnTouch)) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = { clientX: event.clientX, clientY: event.clientY, x: pan.x, y: pan.y }; }}
        onPointerMove={move} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
        <defs><pattern id={gridId} width="36" height="36" patternUnits="userSpaceOnUse">
          <path d="M 36 0 H 0 V 36" fill="none" stroke="currentColor" strokeOpacity=".1" />
        </pattern></defs>
        <rect width="720" height="448" fill="var(--background)" />
        {hasImage && <image href={overview.image_url} x={imageOrigin[0]} y={imageOrigin[1]}
          width={(imageBounds.max_x - imageBounds.min_x) * scale} height={(imageBounds.max_y - imageBounds.min_y) * scale}
          opacity=".8" preserveAspectRatio="none" onError={() => setImageFailed(true)} />}
        {!hasImage && <rect width="720" height="448" fill={`url(#${gridId})`} />}
        {landmarks.map((point, i) => {
          const [x, y] = project(point.x, point.y), color = point.team === 1 ? "#0875d3" : "#d32c4d";
          return <g key={i} transform={`translate(${x},${y})`}>
            {point.kind === "flag" ? <><circle r="11" fill="white" stroke={color} strokeWidth="2" />
              <path d="M-3,6 V-6 H5 L2,-2 H-3" fill={color} stroke={color} strokeWidth="1.5" />
              <text y="-16" textAnchor="middle" fontSize="10" fill={color} stroke="white" strokeWidth="3" paintOrder="stroke">
                {point.team === 1 ? "Blue flag stand" : "Red flag stand"}</text></> : <rect x="-2" y="-2" width="4" height="4" fill={color} />}
            <title>{point.kind === "flag" ? "Flag stand" : "Spawn"} · team {point.team} · {point.x.toFixed(1)}, {point.y.toFixed(1)} m</title>
          </g>;
        })}
        {geometry.map(route => {
          const head = positionAt(route.samples, time);
          const progress = head ? route.commands.slice(0, head.index + 1).join(" ") : "";
          const location = head && project(head.world_x, head.world_y);
          const trail = head ? progress + ` L${location[0].toFixed(1)},${location[1].toFixed(1)}` : "";
          const dash = route.index >= colors.length * 2 ? "2 3" : route.index >= colors.length ? "5 3" : undefined;
          return <g key={route.label} data-bot-route={route.label} stroke={route.color}>
            <path d={route.commands.join(" ")} fill="none" strokeWidth="1.4" opacity=".18" strokeDasharray={dash} />
            <path d={trail} fill="none" strokeWidth={focused ? 2.8 : 1.9} opacity=".95" strokeDasharray={dash} />
            {route.arrows.filter(arrow => arrow.time <= time).map((arrow, i) =>
              <path key={i} d="M-5,-3 L0,0 L-5,3" fill="none" strokeWidth="1.5"
                transform={`translate(${arrow.x},${arrow.y}) rotate(${arrow.angle})`} />)}
            {head && <g transform={`translate(${location[0]},${location[1]})`} data-playback-bot={route.label}>
              <circle r={head.carrying ? 7 : 5} fill={route.color} stroke="white" strokeWidth="2" />
              {head.phase.startsWith("death") && <path d="M-4,-4 L4,4 M-4,4 L4,-4" stroke="white" strokeWidth="2" />}
              {(focused || visible.length <= 8) && <text y="-10" textAnchor="middle" fontSize="9" fill={route.color}
                stroke="white" strokeWidth="3" paintOrder="stroke">{route.label}</text>}
              <title>{route.label} · {clock(time)} · {head.speed.toFixed(1)} km/h · {head.energy.toFixed(0)} energy{head.carrying ? " · carrying flag" : ""}</title>
            </g>}
          </g>;
        })}
        {shownEvents.filter(event => event.id !== activeEvent?.id).concat(activeEvent ? [activeEvent] : []).map(event => {
          const [x, y] = project(event.x, event.y);
          return <g key={event.id} data-route-event={event.label} transform={`translate(${x},${y})`}>
            <circle r={event.id === selectedEvent ? 12 : 8} fill="var(--background)" stroke={event.route.color} strokeWidth="2" />
            <text dy=".33em" textAnchor="middle" fill="currentColor" fontSize="10">{eventMarks[event.label]}</text>
            <title>{event.route.label} · {event.label} · {event.t.toFixed(2)} s</title>
          </g>;
        })}
        <g transform="translate(20,420)" fill="currentColor" stroke="currentColor">
          <path d={`M0,-4 V0 H${scaleMeters * scale} V-4`} fill="none" strokeWidth="2" />
          <text y="-7" stroke="none" fontSize="10">{scaleMeters.toLocaleString()} m</text>
        </g>
        <text x="700" y="22" textAnchor="end" fill="currentColor" fontSize="10">↑ +Y · +X →</text>
      </svg>
      <p className="training-route-caption">Bright trails show movement up to the replay time. Faint trails show the full recorded route.
        {hasImage && " Flags and small squares mark flag stands and spawns. The terrain comes from the map’s source heightfield."}
        {!hasImage && " A terrain image is unavailable for this map."}
        {note && " " + note}{routes.length < tracks.length && " Some bot traces could not be loaded."}</p>
      </>}
      {events.length > 0 ? <details className="training-route-events">
        <summary>Route events <span>{events.length}</span></summary>
        <div className="training-event-list">
          {events.map(event => <button type="button" key={event.id} aria-pressed={selectedEvent === event.id} onClick={() => inspect(event)}>
            <strong>{eventMarks[event.label]} {event.label}</strong>
            <span>{event.route.label} · {event.t.toFixed(2)} s · {event.speed.toFixed(1)} km/h</span>
            <span>{event.x.toFixed(1)}, {event.y.toFixed(1)}, {event.z.toFixed(1)} m · {event.source}</span>
          </button>)}
        </div>
      </details> : <p className="training-route-caption">No flag or death events were recorded in these traces.</p>}
    </>}
  </section></DataComponent>;
}
