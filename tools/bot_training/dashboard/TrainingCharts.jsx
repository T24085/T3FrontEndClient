import React, { useEffect, useState } from "react";
import { DataComponent, DataTable, EvidenceChart } from "../../data-app-public.jsx";
import { format, groups, outcome, percent, queryId, rolling, routeLabel } from "./training-metrics.js";
import { MatchRoutes } from "./MatchRoutes.jsx";

const teal = "#129886";
const blue = "#607af3";
const outcomeColors = { Capture: teal, "Grab only": "#d18322", Miss: "#8d82c4" };
const axisLabels = { showXAxisLabel: true, showYAxisLabel: true };
const number = (key, label, unit = "") => ({ key, label, renderCell: (value) => format(value, unit) });
const count = (key, label) => ({ key, label, renderCell: (value) => format(value, "", 0) });
const rate = (key, label) => ({ key, label, renderCell: percent });

function speedBins(rows, field) {
  const counts = new Map();
  for (const row of rows) {
    if (!Number.isFinite(row[field])) continue;
    const lower = Math.floor(row[field] / 10) * 10;
    counts.set(lower, (counts.get(lower) ?? 0) + 1);
  }
  if (!counts.size) return [];
  const keys = [...counts.keys()];
  return Array.from({ length: (Math.max(...keys) - Math.min(...keys)) / 10 + 1 }, (_, i) => {
    const lower = Math.min(...keys) + i * 10;
    return { range: `${lower}–${lower + 10}`, count: counts.get(lower) ?? 0 };
  });
}

function Chart({ id, title, spec, rows, source = rows, note, height = 265, empty, query = queryId, getMarkActions }) {
  if (!rows.length) return <section className="trial-chart-empty">
    <h4>{title}</h4><p>{empty ?? "Waiting for results in this selection."}</p>
  </section>;
  return <EvidenceChart id={id} queryId={query} title={title}
    spec={{ ...axisLabels, ...spec }} rows={rows} sourceRows={source} height={height}
    chartOptions={getMarkActions ? { getMarkActions } : undefined}>
    {note && <p className="trial-note">{note}</p>}
  </EvidenceChart>;
}

function trialActions(selectTrial) {
  return ({ row }) => row.has_trace && Number.isInteger(row.campaign_attempt)
    ? [{ label: "View charts for trial " + row.campaign_attempt, onSelect: () => selectTrial(row.campaign_attempt) }]
    : [];
}

function Table({ id, title, rows, source, columns, rowKey, query = queryId, ...props }) {
  return <DataComponent id={id} title={title} kind="table" queryId={query} sourceRows={source} displayRows={rows}>
    <DataTable rows={rows} columns={columns} rowKey={rowKey} label={title} {...props} />
  </DataComponent>;
}

export function ScreeningCharts({ rows, selected, selectTrial, selectGroup, attemptsRef }) {
  const routes = new Map();
  for (const row of rows) {
    const Route = routeLabel(row.approach_route);
    const totals = routes.get(Route) ?? { Route, route: row.approach_route, Contacts: 0, Misses: 0 };
    totals[row.contact ? "Contacts" : "Misses"] += 1;
    routes.set(Route, totals);
  }
  const query = "flag-screening";
  const points = rows.filter((row) => Number.isFinite(row.pass_gap_m)).map((row) => ({
    ...row, result: row.contact ? "Contact" : "Miss", speed: row.contact_kmh ?? row.pass_speed_kmh,
  }));
  return <div className="trial-chart-stack">
    <div className="trial-chart-grid">
      <Chart id="screen-route-outcomes" query={query} title="Contacts and misses by route" rows={[...routes.values()]} source={rows}
        getMarkActions={({ row, field }) => row[field] > 0 && ["Contacts", "Misses"].includes(field)
          ? [{ label: "View " + field.toLowerCase() + " for this route", onSelect: () => selectGroup(row.route, field === "Contacts" ? "Contact" : "Miss") }]
          : []}
        spec={{ type: "bar", x: "Route", y: "Contacts", fields: ["Contacts", "Misses"], showLegend: true,
          yLabel: "Attempts", colors: { Contacts: teal, Misses: blue } }} />
      <Chart id="screen-speed-gap" query={query} title="Speed and distance at the flag" rows={points} source={rows}
        getMarkActions={trialActions(selectTrial)}
        note="Select a point to view its trial charts. The plot uses contact speed for hits and closest recorded fly-through speed for misses."
        spec={{ type: "scatter", x: "pass_gap_m", y: "speed", series: "result", showLegend: true,
          xLabel: "Closest recorded fly-through distance (m)", yLabel: "Speed (km/h)",
          colors: { Contact: teal, Miss: blue } }} />
    </div>
    <div ref={attemptsRef} tabIndex={-1}>
    <Table id="screen-attempts" query={query} title="Screening attempts" source={rows} rowKey="campaign_attempt"
      selectedRowKey={selected} onRowSelect={(row) => selectTrial(row.campaign_attempt)}
      rowActionLabel={(row) => "Inspect screening attempt " + row.campaign_attempt}
      rows={[...rows].reverse().map((row) => ({ ...row, result: row.contact ? "Contact" : "Miss",
        activeSki: row.contact ? (row.skiing ? "Yes" : "No") : "—" }))}
      columns={[count("campaign_attempt", "Attempt"), count("match", "Match"), count("bots", "Bots"), count("lane", "Bot"),
        { key: "approach_route", label: "Route", renderCell: routeLabel }, count("spawn", "Spawn"),
        { key: "result", label: "Outcome" }, number("average_kmh", "Avg km/h"), number("peak_kmh", "Peak km/h"),
        number("contact_kmh", "Contact km/h"), number("homeward_kmh", "Homeward pass km/h"), number("pass_gap_m", "Pass gap (m)"),
        { key: "activeSki", label: "Skiing at contact" }, number("seconds", "Attempt (s)")]} />
    </div>
  </div>;
}

export function ProgressCharts({ rows, selectTrial }) {
  const actions = trialActions(selectTrial);
  const points = rows.map((row) => ({ ...row, Average: row.average_kmh, Peak: row.peak_kmh }));
  const inputs = rows.filter((row) => Number.isFinite(row.jet_frames) && Number.isFinite(row.ski_frames)).map((row) => ({
    ...row, name: "Trial " + row.campaign_attempt, outcome: outcome(row),
  }));
  return <div className="trial-chart-stack">
    <Chart id="speed-by-trial" title="Average and peak speed by trial" rows={points} source={rows} getMarkActions={actions}
      spec={{ type: "line", x: "campaign_attempt", y: "Average", fields: ["Average", "Peak"],
        xLabel: "Trial", yLabel: "km/h", showLegend: true, colors: { Average: teal, Peak: blue } }} />
    <div className="trial-chart-grid">
      <Chart id="rolling-speed" title="Rolling speed trends" rows={rolling(rows)} source={rows}
        note="Up to 10 recent trials in this selection. Peak speed uses the 90th percentile."
        spec={{ type: "line", x: "campaign_attempt", y: "Median average",
          fields: ["Median average", "90th percentile peak"], xLabel: "Trial", yLabel: "km/h",
          showLegend: true, colors: { "Median average": teal, "90th percentile peak": blue } }} />
      <Chart id="average-distribution" title="Average speed distribution" rows={speedBins(rows, "average_kmh")} source={rows}
        spec={{ type: "bar", x: "range", y: "count", xLabel: "Average speed (km/h)", yLabel: "Trials" }} />
      <Chart id="jet-vs-peak" title="Jet use vs. peak speed" rows={inputs} getMarkActions={actions}
        note="Frame counts also depend on trial length and game frame rate."
        spec={{ type: "scatter", x: "jet_frames", y: "peak_kmh", series: "outcome",
          xLabel: "Jet active frames", yLabel: "Peak speed (km/h)", colors: outcomeColors }} />
      <Chart id="ski-vs-average" title="Ski use vs. average speed" rows={inputs} getMarkActions={actions}
        spec={{ type: "scatter", x: "ski_frames", y: "average_kmh", series: "outcome",
          xLabel: "Ski active frames", yLabel: "Average speed (km/h)", colors: outcomeColors }} />
    </div>
  </div>;
}

export function RouteCharts({ rows, selectTrial }) {
  const [dimension, setDimension] = useState(() => rows.some((row) => row.approach_route != null) ? "route" : rows.some((row) => row.defense_profile != null) ? "defense" : "spawn");
  const dimensions = {
    route: { label: "Route", key: (row) => row.approach_route == null ? null : routeLabel(row.approach_route) },
    defense: { label: "Defense", key: (row) => row.defense_profile == null ? null : "Profile " + row.defense_profile },
    spawn: { label: "Spawn", key: (row) => row.spawn == null ? null : "Spawn " + row.spawn },
  };
  const grouped = groups(rows, dimensions[dimension].key);
  const source = grouped.flatMap((group) => group.source);
  const outcomes = grouped.map((group) => ({ ...group, Capture: group.captures, "Grab only": group.grabOnly, Miss: group.misses }));
  const defenseRows = rows.filter((row) => Number.isFinite(row.damage_taken)).map((row) => ({
    ...row, name: "Trial " + row.campaign_attempt, outcome: outcome(row),
  }));
  const cells = [];
  for (const { group, source: routeRows } of groups(rows, dimensions.route.key)) {
    for (const defense of groups(routeRows, dimensions.defense.key)) {
      cells.push({ route: group, defense: defense.group, rate: defense.captureRate, trials: defense.trials });
    }
  }
  return <div className="trial-chart-stack">
    <label className="trial-filter">Compare by
      <select value={dimension} onChange={(event) => setDimension(event.target.value)}>
        {Object.entries(dimensions).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}
      </select>
    </label>
    <div className="trial-chart-grid">
      <Chart id="group-outcomes" title="Captures, grabs and misses" rows={outcomes} source={source}
        height={Math.max(265, 85 + 23 * grouped.length)}
        spec={{ type: "bar", x: "group", y: "Capture", fields: ["Capture", "Grab only", "Miss"],
          yLabel: "Completed trials", showLegend: true, colors: outcomeColors }} />
      <Chart id="damage-vs-speed" title="Damage taken vs. peak speed" rows={defenseRows} getMarkActions={trialActions(selectTrial)}
        empty="This batch has no recorded defense damage."
        spec={{ type: "scatter", x: "peak_kmh", y: "damage_taken", series: "outcome",
          xLabel: "Peak speed (km/h)", yLabel: "Damage taken", colors: outcomeColors }} />
    </div>
    {grouped.length > 0 && <Table id="group-summary" title="Performance by group"
      rows={grouped.map(({ source, fastestGrab, fastestCapture, fastestPeak, ...row }) => row)}
      source={source} rowKey="group" searchable={false} columns={[
        { key: "group", label: dimensions[dimension].label }, count("trials", "Trials"),
        count("captures", "Captures"), rate("captureRate", "Cap rate"),
        number("medianSpeed", "Median avg km/h"), number("medianGrabSpeed", "Median grab km/h"),
        number("medianGrabTime", "Median grab (s)"), number("medianCaptureTime", "Median cap (s)"),
        number("medianMissDistance", "Median miss (m)"), number("medianDamage", "Median damage"),
      ]} />}
    {cells.length > 0 && <>
      <Chart id="capture-heatmap" title="Capture rate by route and defense"
        rows={cells} source={rows.filter((row) => row.approach_route != null && row.defense_profile != null)}
        height={Math.max(265, 75 + 31 * new Set(cells.map((cell) => cell.route)).size)}
        note="Rate is captures divided by completed trials in each cell. Blank cells have no trials. Counts are in the table below."
        spec={{ type: "heatmap", x: "defense", y: "route", value: "rate", xLabel: "Defense profile",
          yLabel: "Approach route", showValues: true, colorDomain: [0, 1], valueFormat: { style: "percent", maximumFractionDigits: 0 } }} />
      <Table id="matchup-sample-sizes" title="Matchup sample sizes" rows={cells.map((cell) => ({
        ...cell, matchup: cell.route + " / " + cell.defense,
      }))} source={rows.filter((row) => row.approach_route != null && row.defense_profile != null)}
        rowKey="matchup" columns={[{ key: "matchup", label: "Route / defense" }, count("trials", "Trials"), rate("rate", "Cap rate")]} />
    </>}
  </div>;
}

export function FlagCharts({ rows, selectTrial }) {
  const actions = trialActions(selectTrial);
  const grabs = rows.filter((row) => row.pickup).map((row) => ({
    ...row, name: "Trial " + row.campaign_attempt,
    flag_path: row.skiing_flythrough_grab ? "Skiing fly-through" : row.recovered == null ? "Grab" : row.recovered ? "Recovery" : "First pass",
  }));
  const close = rows.filter((row) => !row.pickup && Number.isFinite(row.closest_pass_cm)).map((row) => ({
    ...row, name: "Trial " + row.campaign_attempt, missDistance: row.closest_pass_cm / 100,
  }));
  const flythroughs = rows.filter((row) => row.entered_flythrough).map((row) => ({
    ...row, name: "Trial " + row.campaign_attempt, gap_m: row.flythrough_gap_cm / 100,
    cross_m: row.flythrough_cross_cm / 100, vertical_m: row.flythrough_vertical_cm / 100,
  }));
  const captures = grabs.filter((row) => row.capture).map((row) => ({
    ...row, return_seconds: row.seconds - row.pickup_seconds,
  }));
  const records = [...grabs].sort((a, b) => b.grab_kmh - a.grab_kmh);
  const capRecords = [...captures].sort((a, b) => a.seconds - b.seconds);
  const openTrial = (row) => selectTrial(row.campaign_attempt);
  return <div className="trial-chart-stack">
    <div className="trial-chart-grid">
      <Chart id="grab-direction" title="Speed and homeward direction at the flag" getMarkActions={actions}
        rows={grabs.filter((row) => Number.isFinite(row.grab_kmh) && Number.isFinite(row.grab_homeward_kmh))}
        note="Positive homeward speed means the bot was moving back toward its base."
        spec={{ type: "scatter", x: "grab_kmh", y: "grab_homeward_kmh", series: "flag_path",
          xLabel: "Speed at grab (km/h)", yLabel: "Homeward speed (km/h)",
          colors: { "Skiing fly-through": teal, "First pass": "#d18322", Recovery: blue, Grab: teal } }} />
      <Chart id="capture-timing" title="Time to grab vs. time to return" getMarkActions={actions}
        rows={captures.filter((row) => Number.isFinite(row.pickup_seconds) && row.return_seconds >= 0)}
        note="Completed captures only. Return time is capture time minus grab time."
        empty="No completed captures with grab and return times in this selection."
        spec={{ type: "scatter", x: "pickup_seconds", y: "return_seconds",
          xLabel: "Time to grab (s)", yLabel: "Time from grab to cap (s)" }} />
      <Chart id="miss-distance" title="Miss distance vs. speed on closest pass" getMarkActions={actions}
        rows={close.filter((row) => Number.isFinite(row.closest_pass_kmh))}
        empty="No missed passes with both speed and distance in this selection."
        spec={{ type: "scatter", x: "closest_pass_kmh", y: "missDistance",
          xLabel: "Speed at closest pass (km/h)", yLabel: "Distance from flag (m)" }} />
      <Chart id="grab-speed-distribution" title="Speed at flag grab"
        rows={speedBins(grabs, "grab_kmh")} source={grabs}
        empty="No flag grabs with recorded speed in this selection."
        spec={{ type: "bar", x: "range", y: "count", xLabel: "Speed at grab (km/h)", yLabel: "Grabs" }} />
    </div>
    {flythroughs.length > 0 && <div className="trial-chart-grid">
      <Chart id="flythrough-speed-gap" title="Speed and distance on fly-through passes" rows={flythroughs} getMarkActions={actions}
        spec={{ type: "scatter", x: "flythrough_speed_kmh", y: "gap_m",
          xLabel: "Speed at closest point (km/h)", yLabel: "Distance from flag (m)" }} />
      <Chart id="flythrough-alignment" title="Fly-through alignment at closest point" rows={flythroughs} getMarkActions={actions}
        spec={{ type: "scatter", x: "cross_m", y: "vertical_m",
          xLabel: "Cross-track offset (m)", yLabel: "Height relative to flag (m)" }} />
    </div>}
    {records.length > 0 && <Table id="quickest-grabs" title="Fastest flag grabs" rows={records} source={grabs}
      rowKey="campaign_attempt" searchable={false} onRowSelect={openTrial} columns={[
        count("campaign_attempt", "Trial"), { key: "approach_route", label: "Route", renderCell: routeLabel },
        number("grab_kmh", "Grab km/h"), number("grab_homeward_kmh", "Homeward km/h"),
        number("pickup_seconds", "Time to grab (s)"), { key: "flag_path", label: "Approach" },
      ]} />}
    {capRecords.length > 0 && <Table id="quickest-captures" title="Fastest captures" rows={capRecords} source={captures} rowKey="campaign_attempt"
      searchable={false} onRowSelect={openTrial} columns={[
        count("campaign_attempt", "Trial"), { key: "approach_route", label: "Route", renderCell: routeLabel },
        number("seconds", "Time to capture (s)"), number("pickup_seconds", "Time to grab (s)"),
        number("return_seconds", "Time to return (s)"),
      ]} />}
  </div>;
}

export function EvaluationCharts({ phases, phase, decision }) {
  const validation = phases.find((item) => item.id === "validation");
  const measured = validation?.rows ?? [];
  const lookup = new Map(measured.map((row) => [row.campaign_attempt, row]));
  const pairs = (decision?.pairs ?? []).map((pair, index) => {
    const fresh = lookup.get(pair.fresh);
    const warm = lookup.get(pair.warm);
    return { pair: "Pair " + (index + 1), Fresh: fresh?.wall_seconds, Reused: warm?.wall_seconds,
      saved: pair.seconds_saved, match: pair.same_outcome ? "Yes" : "No",
      grab_delta: pair.differences?.grab_kmh, peak_delta: pair.differences?.peak_kmh };
  });
  const rows = phase.rows.filter((row) => row.held_out);
  const cohorts = groups(rows, (row) => row.evaluation_role);
  return <div className="trial-chart-stack">
    {decision && <p className="trial-decision">{decision.reset_mode === "verified"
      ? "Expansion mode: verified resets. Median time saved: " + format(decision.median_wall_seconds_saved, " s") + "."
      : "Expansion mode: fresh matches. " + (decision.reasons ?? []).join(" ")}</p>}
    <Chart id="reset-timing" title="Matched fresh and reused trial wall time"
      rows={pairs.filter((pair) => Number.isFinite(pair.Fresh) && Number.isFinite(pair.Reused))} source={measured}
      empty={decision ? "No verified reuse pairs with wall times were recorded." : "The reset decision is pending."}
      spec={{ type: "bar", x: "pair", y: "Fresh", fields: ["Fresh", "Reused"],
        yLabel: "Wall time (s)", showLegend: true, colors: { Fresh: blue, Reused: teal } }} />
    {pairs.length > 0 && <Table id="reset-pairs" title="Reset qualification pairs" rows={pairs} source={measured}
      rowKey="pair" searchable={false} columns={[{ key: "pair", label: "Pair" }, number("saved", "Wall time saved (s)"),
        { key: "match", label: "Same flag outcome" }, number("grab_delta", "Grab speed gap (km/h)"),
        number("peak_delta", "Peak speed gap (km/h)"),
      ]} />}
    {measured.length > 0 && <Table id="reset-attempts" title="Reset validation trials" source={measured}
      rows={measured.map((row) => ({ ...row, outcome: outcome(row), host: row.verified_reuse ? "Reused" : "Fresh" }))}
      rowKey="campaign_attempt" searchable={false} columns={[count("campaign_attempt", "Trial"),
        { key: "validation_role", label: "Role" }, { key: "host", label: "Host" },
        { key: "outcome", label: "Outcome" }, number("wall_seconds", "Wall time (s)"),
      ]} />}
    {cohorts.length > 0 ? <Table id="held-out-evaluation" title="Held-out evaluation by policy" source={rows}
      rows={cohorts.map(({ source, fastestGrab, fastestCapture, fastestPeak, ...row }) => row)}
      rowKey="group" searchable={false} columns={[
        { key: "group", label: "Policy" }, count("trials", "Trials"), count("grabs", "Grabs"),
        count("captures", "Captures"), rate("captureRate", "Cap rate"),
        number("medianSpeed", "Median avg km/h"), number("medianCaptureTime", "Median cap (s)"),
      ]} /> : <p className="trial-note">This batch has no completed held-out policy trials.</p>}
  </div>;
}

export function TrialTable({ rows, selectTrial, selected }) {
  return <Table id="recent-trials" title="Trial results" source={rows} rowKey="campaign_attempt"
    selectedRowKey={selected} onRowSelect={(row) => selectTrial(row.campaign_attempt)}
    rowActionLabel={(row) => "Inspect trial " + row.campaign_attempt}
    rows={[...rows].reverse().map((row) => ({ ...row, outcome: outcome(row) }))}
    columns={[
      count("campaign_attempt", "Trial"), { key: "approach_route", label: "Route", renderCell: routeLabel },
      count("spawn", "Spawn"), count("defense_profile", "Defense"),
      { key: "outcome", label: "Outcome" }, number("average_kmh", "Avg km/h"), number("peak_kmh", "Peak km/h"),
      number("grab_kmh", "Grab km/h"), number("pickup_seconds", "Grab (s)"), number("seconds", "Trial (s)"),
    ]} />;
}

export function TrialTrace({ phase, row, bot, chartPrefix = "", onReview }) {
  const [state, setState] = useState(null);
  const key = phase.id + "/" + row.campaign_attempt + (bot ? "/" + bot.bot : "");
  useEffect(() => {
    const controller = new AbortController();
    if (row.has_trace) {
      fetch("/api/trace/" + key, { signal: controller.signal, cache: "no-store" })
        .then((response) => {
          if (!response.ok) throw new Error("Trace unavailable");
          return response.json();
        })
        .then((data) => setState({ key, ...data }))
        .catch(() => { if (!controller.signal.aborted) setState({ key, error: true }); });
    }
    return () => controller.abort();
  }, [key, row.has_trace]);
  const trace = state?.key === key ? state : null;
  const samples = trace?.samples ?? [];
  const track = samples.map((sample) => ({ ...sample,
    name: format(sample.t, " s") + " · " + sample.phase, flag: sample.carrying ? "Carrying" : "Without flag",
  }));
  const timeSamples = [...new Map(samples.map((sample) => [sample.t, sample])).values()];
  return <div className="trial-chart-stack">
    <section className="trial-inspector" aria-label="Selected trial">
      <h3>{bot ? `Match ${row.campaign_attempt} · ${bot.team === 1 ? "Blue" : "Red"} bot ${bot.bot} · ${bot.role}` : `Trial ${row.campaign_attempt} · ${routeLabel(row.approach_route)}`}</h3>
      <p>{bot ? format(bot.peak_kmh, " km/h peak") : <>{phase.screening ? (row.contact ? "Flag-volume contact" : "Miss") : outcome(row)} · spawn {row.spawn ?? "—"} · {format(row.peak_kmh, " km/h peak")}</>}</p>
      {!bot && <dl>
        {(phase.screening ? [
          ["Contact speed", format(row.contact_kmh, " km/h")], ["Average speed", format(row.average_kmh, " km/h")],
          ["Pass gap", format(row.pass_gap_m, " m")], ["Homeward pass speed", format(row.homeward_kmh, " km/h")],
          ["Contact time", format(row.contact ? row.seconds : null, " s")], ["Trial time", format(row.seconds, " s")],
          ["Skiing at contact", row.contact ? (row.skiing ? "Yes" : "No") : "—"],
          ["Jet frames", format(row.jet_frames, "", 0)], ["Ski frames", format(row.ski_frames, "", 0)],
        ] : [
          ["Grab speed", format(row.grab_kmh, " km/h")], ["Homeward at grab", format(row.grab_homeward_kmh, " km/h")],
          ["Grab time", format(row.pickup_seconds, " s")], ["Trial time", format(row.seconds, " s")],
          ["Damage", format(row.damage_taken, "", 0)], ["Jet frames", format(row.jet_frames, "", 0)],
          ["Ski frames", format(row.ski_frames, "", 0)], ["Jet pulse", format(row.pulse, " s", 2)],
          ["Jet period", format(row.period, " s")], ["Braking distance", format(Number.isFinite(row.approach_cm) ? row.approach_cm / 100 : null, " m")],
        ]).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
      </dl>}
    </section>
    {samples.length ? <div className="trial-chart-grid">
      <div className="training-route-replay-block"><MatchRoutes phase={phase.id} id={chartPrefix + "trace-direction"} title="Route replay" provided={[trace]} onReview={onReview} tracks={[{
        attempt: row.campaign_attempt, bot: bot?.bot, label: bot ? "Bot " + bot.bot : "Bot route",
      }]} /></div>
      <Chart id={chartPrefix + "trace-speed"} query="trial-trace" title="Speed through the run" rows={timeSamples} source={samples}
        spec={{ type: "line", x: "t", y: "speed", xLabel: "Trial time (s)", yLabel: "Horizontal speed (km/h)" }} />
      <Chart id={chartPrefix + "trace-altitude"} query="trial-trace" title="Height through the run" rows={timeSamples} source={samples}
        spec={{ type: "line", x: "t", y: "altitude", xLabel: "Trial time (s)", yLabel: "Height relative to start (m)", startAtZero: false }} />
      <Chart id={chartPrefix + "trace-energy"} query="trial-trace" title="Jet energy through the run" rows={timeSamples} source={samples}
        spec={{ type: "line", x: "t", y: "energy", xLabel: "Trial time (s)", yLabel: "Energy" }} />
      <Chart id={chartPrefix + "trace-path"} query="trial-trace" title="Horizontal track from spawn" rows={track} source={samples}
        note="Points are sampled positions relative to spawn. Hover a point for its trial time and movement phase."
        spec={{ type: "scatter", x: "x", y: "y", series: "flag", xLabel: "X from spawn (m)",
          yLabel: "Y from spawn (m)", startAtZero: false, colors: { Carrying: teal, "Without flag": blue } }} />
    </div> : <p role="status">{!row.has_trace || trace?.error ? "Trace unavailable for this trial." : "Loading recorded movement…"}</p>}
  </div>;
}
