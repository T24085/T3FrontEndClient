import React, { useEffect, useMemo, useRef, useState } from "react";
import { Dialog, Icon } from "../../data-app-public.jsx";
import { CampaignFlight, EvaluationCharts, FlagCharts, ProgressCharts, RouteCharts, ScreeningCharts, TrialTable, TrialTrace } from "./TrainingCharts.jsx";
import { best, format, median, outcome, percent, routeLabel, summarizeTrials } from "./training-metrics.js";
import { MatchRoutes } from "./MatchRoutes.jsx";
import "./dashboard.css";

const sections = [
  ["overview", "Overview"], ["matchups", "Routes & defense"], ["flags", "Grabs & captures"],
  ["evaluation", "Evaluation"], ["trials", "Trial explorer"],
];

const modeGroups = [
  ["Movement", ["flight"]],
  ["Routes", ["screen", "solo", "explore"]],
  ["Offense & Defense", ["duel", "defended", "offdef"]],
  ["Full CTF", ["teams", "scrimmage", "season"]],
];

const trainingModes = {
  flight: { label: "Flight fundamentals", objective: "Practice ski momentum, jet takeoffs, and forward flight.",
    result: "Forward distance, speed, airtime, and time below 15 km/h",
    sides: "Bots train on Blue and Red. Recovery starts with low jet energy. Flag pickups and combat are disabled." },
  screen: { label: "Route screening", objective: "Find approaches that reach the flag at speed.",
    result: "Flag contacts, approach speed, and route traces", sides: "Blue and Red approaches. One bot alternates sides between waves." },
  solo: { label: "Cappers, no defenders", objective: "Practice live grabs, returns, and captures without defenders.",
    result: "Pickups, captures, and capper traces", sides: "The same capper setup runs from Blue and Red in each pair." },
  explore: { label: "Route exploration", objective: "Try wider flanks and back routes on a live flag.",
    result: "Pickup speed, speed toward home, and captures", sides: "Cappers repeat the same routes on the opposite side in each pair." },
  defended: { label: "Cappers vs. defense", objective: "Test flag approaches against a configurable defense.",
    result: "Pickup denial, flag outcomes, and defense traces", sides: "The same route runs from both sides for each defender setup." },
  duel: { label: "Capper vs. Chaser", objective: "Escape with a live flag while a defender flies to intercept.",
    result: "Escapes, interceptions, carrier damage, and shots in flight", sides: "The capper and chaser swap sides in every pair." },
  offdef: { label: "4v3 offense vs. defense", objective: "Practice support timing around two cappers.",
    result: "Capper outcomes and offensive and defensive tactics", sides: "The four attackers and three defenders swap sides in each pair." },
  teams: { label: "Team CTF", objective: "Compare team lineups against the balanced roster.",
    result: "Score margin by lineup and per-bot match traces", sides: "Each candidate lineup plays the balanced roster on Blue and Red." },
  scrimmage: { label: "Role scrimmage", objective: "Practice role tactics with equal team rosters.",
    result: "Match scores, flag outcomes, and per-role traces", sides: "Both teams use the same competitive roster." },
  season: { label: "Super training season", objective: "Train on every map, one map at a time, to five captures or the time limit.",
    result: "Per-map CTF, flight, and base equipment results", sides: "Both teams use balanced offense and defense." },
};

const flightCourses = {
  straight: { label: "Straight flight", objective: "Practice ski momentum, jet takeoffs, and forward flight.",
    result: "Forward distance, speed, airtime, and time below 15 km/h" },
  downhill: { label: "Downhill momentum", objective: "Use the slope to gain speed and keep it through the exit.",
    result: "Course completions, entry and exit speed, and speed retained" },
  uphill: { label: "Uphill jets", objective: "Ski and jet forward up a surveyed slope.",
    result: "Course completions, height gained, and forward distance under jet power" },
  recovery: { label: "Low-energy recovery", objective: "Regain forward speed after a sideways shove with low jet energy.",
    result: "Recovery time, forward speed, starting energy, and grounded jogging" },
};

function useResults() {
  const [results, setResults] = useState(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    let previous;
    async function refresh() {
      try {
        const response = await fetch("/api/results", { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Could not refresh");
        const payload = await response.text();
        if (payload !== previous) {
          setResults(JSON.parse(payload));
          previous = payload;
        }
        setError(false);
      } catch {
        if (!controller.signal.aborted) setError(true);
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 5000);
      }
    }
    refresh();
    return () => { clearTimeout(timer); controller.abort(); };
  }, [revision]);
  return { results, error, refresh: () => setRevision((value) => value + 1) };
}

function Metric({ label, value, detail, tone }) {
  return <div className="trial-metric" data-tone={tone}>
    <span>{label}</span><strong>{value}</strong>{detail && <small>{detail}</small>}
  </div>;
}

function ScopeFilter({ label, value, onChange, options, allLabel }) {
  return <label className="trial-filter">{label}
    <select value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">{allLabel}</option>
      {options.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
    </select>
  </label>;
}

function options(rows, key, label = String) {
  return [...new Set(rows.map((row) => row[key]).filter((value) => value != null))]
    .map((value) => [String(value), label(value)])
    .sort((a, b) => a[1].localeCompare(b[1], undefined, { numeric: true }));
}

function ScreeningAnalysis({ phase, keepRun }) {
  const [match, setMatch] = useState("");
  const [route, setRoute] = useState("");
  const [result, setResult] = useState("");
  const [selected, setSelected] = useState(null);
  const [inspecting, setInspecting] = useState(false);
  const attemptsRef = useRef(null);
  const rows = phase.rows.filter((row) => (!route || row.approach_route === route) &&
    (!result || (row.contact ? "Contact" : "Miss") === result));
  const hits = rows.filter((row) => row.contact);
  const fastest = best(hits, "contact_kmh");
  const fastContacts = hits.filter((row) => row.contact_kmh >= 100).length;
  const matchNumber = Number(match) || phase.rows.at(-1)?.match;
  const matchTracks = phase.rows.filter((row) => row.match === matchNumber)
    .map((row) => ({ attempt: row.campaign_attempt,
      label: (row.team === 1 ? "Blue " : row.team === 2 ? "Red " : "") + "Bot " + row.lane }));
  const selectedTrial = rows.find((row) => row.campaign_attempt === selected) ?? fastest ?? rows.at(-1);
  function openTrial(number) {
    setSelected(number);
    setInspecting(true);
  }
  function selectGroup(routeName, outcome) {
    setRoute(routeName);
    setResult(outcome);
    attemptsRef.current?.focus({ preventScroll: true });
    attemptsRef.current?.scrollIntoView({ block: "start" });
  }
  return <>
    {matchTracks.length > 0 && <MatchRoutes key={matchNumber} phase={phase.id} tracks={matchTracks}
      onReview={() => { keepRun(); setMatch(String(matchNumber)); }}
      picker={<div className="training-match-picker">
        <ScopeFilter label="Match" value={match} onChange={setMatch}
          allLabel={"Latest match · " + phase.rows.at(-1).match}
          options={options(phase.rows, "match", (value) => "Match " + value)} />
      </div>} note="Screening records flag contact for each bot with flag pickup disabled." />}
    <div className="trial-scopes">
      <ScopeFilter label="Route" value={route} onChange={setRoute} allLabel="All routes"
        options={options(phase.rows, "approach_route", routeLabel)} />
      <ScopeFilter label="Outcome" value={result} onChange={setResult} allLabel="All outcomes"
        options={[["Contact", "Contact"], ["Miss", "Miss"]]} />
      <span className="trial-scope-count">{rows.length} of {phase.rows.length} attempts</span>
    </div>
    {rows.length ? <>
      <div className="trial-metrics" data-reviewed-rows>
        <Metric label="Flag-volume contacts" value={hits.length + " / " + rows.length}
          detail={fastContacts + " at 100+ km/h (" + percent(fastContacts / rows.length) + " of attempts)"} />
        <Metric label="Fastest flag contact" value={format(fastest?.contact_kmh, " km/h")}
          detail={fastest && "Attempt " + fastest.campaign_attempt + " · " + routeLabel(fastest.approach_route)} />
        <Metric label="Median trial speed" value={format(median(rows.map((row) => row.average_kmh)), " km/h")}
          detail={"Fastest peak " + format(best(rows, "peak_kmh")?.peak_kmh, " km/h")} />
        <Metric label="Median contact speed" value={format(median(hits.map((row) => row.contact_kmh)), " km/h")}
          detail={hits.length > 0 && "Quickest contact " + format(best(hits, "seconds", false)?.seconds, " s")} />
        {phase.wall_seconds > 0 && <Metric label="Flag contacts per hour"
          value={format(3600 * phase.rows.filter(row => row.contact).length / phase.wall_seconds)}
          detail="Based on recorded wave time, including game startup" />}
        {phase.wall_seconds > 0 && <Metric label="100+ km/h contacts per hour"
          value={format(3600 * phase.rows.filter(row => row.contact && row.contact_kmh >= 100).length / phase.wall_seconds)} />}
        {phase.reused_waves !== undefined && <Metric label="Waves using verified resets" value={phase.reused_waves}
          detail={(phase.reset_fallbacks || 0) + " resets required a fresh game"} />}
      </div>
      <ScreeningRanking rows={phase.rows} onRoute={(name) => selectGroup(name, "")} />
      <label className="trial-filter">Explore a route
        <select value={selectedTrial.campaign_attempt} onChange={(event) => setSelected(Number(event.target.value))}>
          {rows.map((row) => <option key={row.campaign_attempt} value={row.campaign_attempt}>
            {row.campaign_attempt} · {routeLabel(row.approach_route)} · {row.contact ? "Contact" : "Miss"}
          </option>)}
        </select>
      </label>
      <TrialTrace phase={phase} row={selectedTrial} onReview={() => { keepRun(); setSelected(selectedTrial.campaign_attempt); }} />
      <ScreeningCharts rows={rows} selected={selectedTrial.campaign_attempt} selectTrial={openTrial}
        selectGroup={selectGroup} attemptsRef={attemptsRef} />
    </> : <p role="status">{phase.rows.length ? "No attempts match these filters." : "Waiting for the first completed match."}</p>}
    <Dialog open={inspecting && Boolean(selectedTrial)} onClose={() => setInspecting(false)} expanded
      title={selectedTrial ? `Match ${selectedTrial.match} · Bot ${selectedTrial.lane} · Trial ${selectedTrial.campaign_attempt}` : "Trial charts"}>
      {inspecting && selectedTrial && <TrialTrace phase={phase} row={selectedTrial} chartPrefix="screen-detail-"
        onReview={keepRun} />}
    </Dialog>
  </>;
}

function ScreeningRanking({ rows, onRoute }) {
  const grouped = new Map();
  for (const row of rows) {
    const group = grouped.get(row.approach_route) ?? [];
    group.push(row);
    grouped.set(row.approach_route, group);
  }
  const ranking = Array.from(grouped, ([route, attempts]) => {
    const hits = attempts.filter((row) => row.contact);
    const entry = hits.map((row) => row.approach_entry_kmh).filter((speed) => Number.isFinite(speed));
    const retention = hits.filter((row) => row.approach_peak_kmh > 0)
      .map((row) => row.contact_kmh / row.approach_peak_kmh);
    return { route, attempts, hits: hits.length, rate: hits.length / attempts.length,
      entry: entry.length ? median(entry) : null, retention: retention.length ? median(retention) : null };
  }).sort((a, b) => b.rate - a.rate || (b.entry ?? 0) - (a.entry ?? 0) || (b.retention ?? 0) - (a.retention ?? 0));
  return <details className="training-panel training-coverage">
    <summary>Route ranking</summary>
    <p>Routes are ranked by contact rate, median approach entry speed, then speed at contact as a share of peak approach speed.</p>
    <div className="training-role-table" tabIndex="0">
      <table><thead><tr>{["Route", "Blue attempts", "Red attempts", "Contacts", "Median entry", "Median speed retained"].map(
        (heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{ranking.map((item) => <tr key={item.route}>
          <th scope="row"><button type="button" className="training-role-bot" onClick={() => onRoute(item.route)}>{routeLabel(item.route)}</button></th>
          <td>{item.attempts.filter((row) => row.team === 1).length}</td>
          <td>{item.attempts.filter((row) => row.team === 2).length}</td>
          <td>{item.hits} / {item.attempts.length} · {percent(item.rate)}</td>
          <td>{format(item.entry, " km/h")}</td>
          <td>{item.retention === null ? "—" : percent(item.retention)}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </details>;
}

function StartTraining({ allowed, busy, willQueue, onSubmit, maps, seasonEvaluationMatches }) {
  const [mode, setMode] = useState("screen");
  const [map, setMap] = useState("HighOctane2026");
  const [matches, setMatches] = useState("10");
  const [bots, setBots] = useState("24");
  const [wavesPerLaunch, setWavesPerLaunch] = useState("5");
  const [attackers, setAttackers] = useState("1");
  const [defenders, setDefenders] = useState("2");
  const [teamSize, setTeamSize] = useState("7");
  const [seconds, setSeconds] = useState("180");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [scrimmageType, setScrimmageType] = useState("train");
  const [flightBots, setFlightBots] = useState("10");
  const [flightWaves, setFlightWaves] = useState("3");
  const [flightSeconds, setFlightSeconds] = useState("30");
  const [flightCourse, setFlightCourse] = useState("straight");
  const flight = mode === "flight";
  const duel = mode === "duel";
  const course = flightCourses[flightCourse];
  const defendedMode = mode === "defended" || mode === "explore";
  const capperMode = mode === "solo" || defendedMode;
  const totalBots = Number(attackers) + (defendedMode ? Number(defenders) : 0);
  const exceedsRoster = capperMode && totalBots > 24;
  const season = mode === "season";
  const benchmark = mode === "scrimmage" && scrimmageType === "evaluate";
  const aimCalibration = mode === "scrimmage" && scrimmageType === "aim";
  const paired = benchmark || aimCalibration || duel;
  const sizedTeams = mode === "teams" || mode === "scrimmage" || season;
  const timedMode = sizedTeams || duel || mode === "offdef" || defendedMode || (mode === "solo" && Number(attackers) > 1);
  const matchCount = Number(flight ? flightWaves : matches);
  const mapCount = Object.keys(maps).length;
  const configuration = duel ? "1 capper · 1 chaser" : flight ? `${flightBots} light bots per wave` : mode === "screen" ? `${bots} cappers per wave` : capperMode
    ? `${attackers} ${Number(attackers) === 1 ? "capper" : "cappers"} · ${defendedMode ? defenders : 0} defenders`
    : mode === "offdef" ? "4 offense · 3 defense" : `${teamSize} bots per team`;
  const total = flight ? `${flightWaves} waves × ${flightBots} bots = ${(matchCount * Number(flightBots)).toLocaleString()} attempts`
    : mode === "screen" ? `${matches} waves × ${bots} cappers = ${(matchCount * Number(bots)).toLocaleString()} attempts`
    : season ? `${matches} matches per map × ${mapCount} maps = ${(matchCount * mapCount).toLocaleString()} matches`
    : paired ? `${matches} mirrored pairs × 2 games = ${(matchCount * 2).toLocaleString()} games`
    : `${matches} ${matchCount === 1 ? "match" : "matches"}`;
  const selectedMode = trainingModes[mode];
  if (!allowed) return null;
  async function submit(event) {
    event.preventDefault();
    setPending(true);
    setMessage("");
    try {
      const response = await fetch("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, ...(season ? {} : { map }), matches: paired ? matchCount * 2 : matchCount,
          seconds: flight ? Number(flightSeconds) : timedMode ? Number(seconds) : 76,
          waves_per_launch: benchmark || duel ? 1 : Number(wavesPerLaunch), ...(benchmark ? { evaluation: true } : {}),
          ...(aimCalibration ? { aim_calibration: true } : {}),
          ...(mode === "screen" ? { bots: Number(bots) } : {}),
          ...(flight ? { bots: Number(flightBots), course: flightCourse } : {}),
          ...(capperMode ? { attackers: Number(attackers) } : {}),
          ...(defendedMode ? { defenders: Number(defenders) } : {}),
          ...(sizedTeams ? { team_size: Number(teamSize) } : {}) }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error);
      onSubmit(body);
      setMessage(body.status === "Queued" ? (season ? "Season added to the queue." : "Run added to the queue.") : "Training started. Waiting for the first match.");
    } catch (error) {
      setMessage(error.message || "Could not start training.");
    } finally {
      setPending(false);
    }
  }
  return <section className="training-panel training-setup" aria-labelledby="training-setup-title">
    <div className="training-panel-intro">
      <div className="training-guide-title">
        <h3 id="training-setup-title">New training run</h3>
        <button className="training-button training-icon-button" type="button" onClick={() => setShowGuide(true)}>
          <Icon name="info" />Mode guide
        </button>
      </div>
      <p>{flight ? course.objective : selectedMode.objective}</p>
    </div>
    <Dialog open={showGuide} onClose={() => setShowGuide(false)} title="Choose a training mode">
      {modeGroups.map(([group, modes]) => <section className="training-mode-guide" key={group}>
        <h4>{group}</h4>
        <dl>{modes.map((key) => {
          const entry = trainingModes[key];
          return <React.Fragment key={key}><dt>{entry.label}</dt><dd>{entry.objective} {entry.sides}</dd></React.Fragment>;
        })}</dl>
      </section>)}
    </Dialog>
    <form className="training-form" onSubmit={submit}>
      <div className="training-fields">
        <label className="trial-filter">Mode
          <select value={mode} onChange={(event) => {
            const next = event.target.value;
            if (next === "scrimmage" && Number(teamSize) < (scrimmageType === "train" ? 7 : 2)) {
              setTeamSize(scrimmageType === "train" ? "7" : "2");
            }
            if (next === "season" && Number(teamSize) < 2) setTeamSize("2");
            if (next === "duel" && Number(seconds) > 90) setSeconds("45");
            setMode(next);
          }}>
            {modeGroups.map(([group, modes]) => <optgroup key={group} label={group}>
              {modes.map((key) => <option key={key} value={key}>{trainingModes[key].label}</option>)}
            </optgroup>)}
          </select>
        </label>
        {!season && <label className="trial-filter training-map-field">Map
          <select name="map" value={map} onChange={(event) => setMap(event.target.value)}>
            {Object.entries(maps).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>}
        {mode === "screen" && <label className="trial-filter">Cappers per wave
          <input type="number" name="bots" min="1" max="24" step="1" required value={bots} onChange={(event) => setBots(event.target.value)} />
        </label>}
        {mode === "scrimmage" && <label className="trial-filter">Run type
          <select value={scrimmageType} onChange={(event) => {
            setScrimmageType(event.target.value);
            if (event.target.value === "train" && Number(teamSize) < 7) setTeamSize("7");
          }}>
            <option value="train">Train tactics</option>
            <option value="evaluate">Compare with baseline</option>
            <option value="aim">Calibrate aiming</option>
          </select>
        </label>}
        {!benchmark && !duel && <label className="trial-filter">Waves per game launch
          <select name="waves_per_launch" value={wavesPerLaunch} onChange={event => setWavesPerLaunch(event.target.value)}>
            <option value="5">5 waves</option><option value="4">4 waves</option><option value="3">3 waves</option>
            <option value="2">2 waves</option><option value="1">1 wave</option>
          </select>
        </label>}
        {capperMode && <label className="trial-filter">Cappers
          <input type="number" name="attackers" min="1" max="24" required value={attackers} onChange={event => setAttackers(event.target.value)} />
        </label>}
        {defendedMode &&
          <label className="trial-filter">Defenders
            <input type="number" name="defenders" min="0" max="23" required value={defenders} onChange={event => setDefenders(event.target.value)} />
          </label>
        }
        {sizedTeams && <label className="trial-filter">Bots per team
          <input type="number" name="team_size" min={mode === "scrimmage" ? (paired ? 2 : 7) : season ? 2 : 1} max="12" required value={teamSize} onChange={event => setTeamSize(event.target.value)} />
        </label>}
        {!flight && <label className="trial-filter">{paired ? "Mirrored pairs" : mode === "screen" ? "Waves" : season ? "Matches per map" : "Matches"}
          <input type="number" min="1" max={paired ? 500 : 1000} required value={matches} onChange={(event) => setMatches(event.target.value)} />
        </label>}
        {flight && <>
          <label className="trial-filter training-map-field">Course
            <select name="flight_course" value={flightCourse} onChange={event => setFlightCourse(event.target.value)}>
              {Object.entries(flightCourses).map(([key, item]) => <option value={key} key={key}>{item.label}</option>)}
            </select>
          </label>
          <label className="trial-filter">Bots per wave
            <input type="number" name="flight_bots" min="4" max="24" step="2" required value={flightBots}
              onChange={event => setFlightBots(event.target.value)} />
          </label>
          <label className="trial-filter">Waves
            <input type="number" name="flight_waves" min="1" max="1000" required value={flightWaves}
              onChange={event => setFlightWaves(event.target.value)} />
          </label>
          <label className="trial-filter">Seconds per wave
            <input type="number" min="30" max="90" required value={flightSeconds} onChange={event => setFlightSeconds(event.target.value)} />
          </label>
        </>}
        {timedMode && <label className="trial-filter">Seconds per match
          <input type="number" min="30" max={duel ? 90 : 600} required value={seconds} onChange={(event) => setSeconds(event.target.value)} />
        </label>}
      </div>
      <dl className="training-run-plan">
        <dt>Roster</dt><dd>{configuration}</dd>
        <dt>Sides</dt><dd>{paired && !duel ? "The candidate plays one game from each side in every pair." : selectedMode.sides}</dd>
        <dt>Saved data</dt><dd>{flight ? course.result : aimCalibration ? "Confirmed damage per tracked projectile and native aim decisions" : benchmark ? "Paired scores and the frozen tactics used in both games" : selectedMode.result}</dd>
      </dl>
      <p>{flight ? "With three or more waves, the final two can compare a selected profile against the baseline from the same starts."
        : duel ? "A native flag pickup starts the clock. Each side gets a fresh match."
        : aimCalibration ? "Both teams use the same role tactics. Start with at least eight mirrored pairs to give both aim profiles four chances to qualify. The trainer reuses the game only after verifying a clean reset."
        : benchmark ? "Each game starts fresh. Benchmark results stay out of the learning pool."
        : "Waves per game launch controls reuse of the game instance. The run saves each completed wave."}</p>
      {season && seasonEvaluationMatches > 0 && <p>After training, the season runs {seasonEvaluationMatches} benchmark games per map · {seasonEvaluationMatches * mapCount} evaluation games in total.</p>}
      {flight && !busy && willQueue && <p>The flight drill can start now. Runs already waiting stay queued.</p>}
      {mode === "defended" && Number(defenders) > 0 && <p>Every six games test the same route against three defender setups, with a game on Blue and Red for each setup.</p>}
      <div className="training-form-footer">
        <p><strong>{total}</strong></p>
        <button className="training-button training-primary" type="submit" disabled={pending || (season ? !Object.keys(maps).length : !maps[map]) || exceedsRoster}>
          {pending ? "Saving…" : flight ? (busy ? "Queue flight drill" : "Start flight drill")
            : season ? (willQueue ? "Queue season" : "Start season") : willQueue ? "Queue run" : "Start run"}
        </button>
      </div>
      {message && <p role="status">{message}</p>}
    </form>
  </section>;
}

function TrainingQueue({ runs, busy, maps, refresh }) {
  const [pending, setPending] = useState(null);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState(5);
  const [confirmClear, setConfirmClear] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { if (!runs.length) setConfirmClear(false); }, [runs.length]);
  if (!runs.length && !message) return null;
  async function act(path, key) {
    setPending(key);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/runs/${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      if (key === "clear-queue") {
        setConfirmClear(false);
        setMessage(data.removed === 1 ? "Removed 1 waiting run." : `Removed ${data.removed} waiting runs.`);
        setLimit(5);
      }
    } catch (failure) {
      setError(failure.message || "Could not update the queue.");
    } finally {
      setPending(null);
      refresh();
    }
  }
  return <details className="training-panel training-coverage training-queue">
    <summary>Training queue <span className="training-status">{runs.length} waiting</span></summary>
    {message && <p role="status">{message}</p>}
    {runs.length > 0 && <>
    <div className="training-queue-toolbar">
      <p>{busy ? "The next run starts automatically when training completes." : "The trainer is idle. Start the next run when ready."}</p>
      <button className="training-button training-danger training-icon-button" type="button" disabled={Boolean(pending)}
        onClick={() => { setError(""); setConfirmClear(true); }}><Icon name="trash" />Clear queue</button>
    </div>
    <Dialog open={confirmClear} onClose={() => { if (!pending) setConfirmClear(false); }} title="Clear training queue?">
      <p>Remove {runs.length === 1 ? "the 1 waiting run" : `all ${runs.length} waiting runs`}.</p>
      {error && <p className="training-action-error" role="alert">{error}</p>}
      <div className="training-actions">
        <button className="training-button" type="button" disabled={Boolean(pending)} onClick={() => setConfirmClear(false)}>Cancel</button>
        <button className="training-button training-danger" type="button" disabled={Boolean(pending)}
          onClick={() => act("clear-queue", "clear-queue")}>{pending ? "Clearing…" : "Clear waiting runs"}</button>
      </div>
    </Dialog>
    <ol>
      {runs.slice(0, limit).map((run, index) => <li key={run.id}>
        <div className="training-queue-entry">
          <strong>{run.label}</strong>
          <span>{maps[run.map] ?? run.map} · {run.matches} {run.mode === "flight"
            ? (run.matches === 1 ? "wave" : "waves") : (run.matches === 1 ? "match" : "matches")}</span>
        </div>
        <div className="training-actions">
          {!busy && index === 0 && <button className="training-button training-primary" type="button"
            disabled={Boolean(pending)} onClick={() => act(`${run.id}/start`, run.id)}>Start next run</button>}
          <button className="training-button" type="button" aria-label={`Remove queued run ${index + 1}`}
            disabled={Boolean(pending)} onClick={() => act(`${run.id}/cancel`, run.id)}>Remove</button>
        </div>
      </li>)}
    </ol>
    {limit < runs.length && <button className="training-button" type="button" onClick={() => setLimit(limit + 5)}>
      Show 5 more queued runs
    </button>}
    </>}
    {error && !confirmClear && <p className="training-action-error" role="alert">{error}</p>}
  </details>;
}

function savedProgress(run) {
  const count = run.screening ? run.matches : run.rows.length;
  const total = run.screening ? run.target_matches : run.total;
  return { count, total, unit: run.screening || run.flight ? "waves" : run.team_matches ? "matches" : "trials" };
}

const activeStatuses = ["Running", "Pausing", "Stopping"];
const dateFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit" });

function RunStatus({ status }) {
  return <span className="training-status" data-status={status.toLowerCase()}>{status}</span>;
}

function TrainingControls({ run, onSelect, onResults, busy }) {
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const running = activeStatuses.includes(run.status);
  const { count, total, unit } = savedProgress(run);
  const recentMatches = onResults && run.team_matches ? run.rows.slice(-3).reverse() : [];
  const pausing = run.status === "Pausing" || pending === "pause";
  const stopping = run.status === "Stopping" || pending === "stop";
  async function act(action) {
    setPending(action);
    setError("");
    try {
      const response = await fetch(`/api/runs/${run.id}/${action}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error);
      if (action === "resume" || action === "repeat") onSelect(payload.id);
    } catch (failure) {
      setPending("");
      setError(failure.message || "Could not update the run.");
    } finally {
      if (action === "resume" || action === "repeat") setPending("");
    }
  }
  return <section className="training-panel training-session" aria-labelledby="training-session-title">
    <div className="training-session-header">
      <h3 id="training-session-title">{running ? "Active run" : onResults ? "Latest run" : "Selected run"}</h3>
      <RunStatus status={run.status} />
    </div>
    <p className="training-run-name">{run.label}</p>
    <div className="training-progress" data-reviewed-rows>
      <div className="training-progress-value">
        <strong>{count.toLocaleString()}</strong>
        <span> / {total.toLocaleString()} {unit} saved</span>
      </div>
      <progress aria-label={unit + " saved"} value={count} max={Math.max(total, 1)} />
    </div>
    {run.carried_forward > 0 && <p className="training-context">
      {run.carried_forward.toLocaleString()} earlier results used for learning
    </p>}
    {run.message && <p className="training-context">{run.message}</p>}
    {error && <p className="training-action-error" role="alert">{error}</p>}
    {recentMatches.length > 0 && <div className="training-recent-matches">
      <h4>Recent matches</h4>
      <ul>
        {recentMatches.map(match => <li key={match.campaign_attempt}>
          <button type="button" aria-label={`Replay match ${match.campaign_attempt} · Blue ${match.blue}, Red ${match.red}`}
            onClick={() => onResults(match.campaign_attempt)}>
            <span>Match {match.campaign_attempt}</span>
            <span className="training-recent-score">
              <span data-team="blue">{match.blue}</span>
              <span aria-hidden="true">–</span>
              <span data-team="red">{match.red}</span>
            </span>
            <Icon name="chevronRight" size={14} />
          </button>
        </li>)}
      </ul>
    </div>}
    <div className="training-actions">
      {onResults && <button className={"training-button training-view-results training-icon-button" + (running ? " training-primary" : "")} type="button"
        onClick={() => onResults()}>View results <Icon name="arrowUpRight" /></button>}
      {running && run.stoppable && <>
        <button className="training-button" type="button" disabled={pausing || stopping} onClick={() => act("pause")}>
          {run.screening || run.flight ? (pausing ? "Pausing after wave…" : "Pause after wave")
            : (pausing ? "Pausing after match…" : "Pause after match")}
        </button>
        <button className="training-button training-danger" type="button" disabled={stopping} onClick={() => act("stop")}>
          {stopping ? "Stopping…" : "Stop now"}
        </button>
      </>}
      {!running && run.resumable && <button className="training-button training-primary" type="button"
        disabled={busy || Boolean(pending)} onClick={() => act("resume")}>
        {pending === "resume" ? "Resuming…" : "Resume run"}
      </button>}
      {!running && run.repeatable && <button className="training-button" type="button" disabled={busy || Boolean(pending)}
        onClick={() => act("repeat")}>{pending === "repeat" ? "Starting…" : "Run again"}</button>}
    </div>
  </section>;
}

const historyPageSize = 6;

function TrainingHistory({ phases, phase, onSelect, maps }) {
  const [search, setSearch] = useState("");
  const [map, setMap] = useState("");
  const [page, setPage] = useState(0);
  const sorted = [...phases].sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""));
  const words = search.trim().toLowerCase().split(/\s+/);
  const filtered = sorted.filter(item => {
    const label = [item.label, maps[item.map_id] ?? item.map_id, item.status].join(" ").toLowerCase();
    return (!map || item.map_id === map) && words.every(word => label.includes(word));
  });
  const currentPage = Math.min(page, Math.max(0, Math.ceil(filtered.length / historyPageSize) - 1));
  const start = currentPage * historyPageSize;
  const end = Math.min(start + historyPageSize, filtered.length);
  return <section className="training-library" aria-labelledby="training-history-title">
    <div className="training-history-heading">
      <h3 id="training-history-title">Saved runs</h3>
      <div className="training-history-filters">
        <label className="trial-filter">Search runs
          <input type="search" aria-label="Search training history" placeholder="Name, map, or status" value={search}
            onChange={event => { setSearch(event.target.value); setPage(0); }} />
        </label>
        <ScopeFilter label="Map" value={map} onChange={value => { setMap(value); setPage(0); }} allLabel="All maps"
          options={options(phases, "map_id", id => maps[id] ?? id)} />
      </div>
    </div>
    {filtered.length ? <>
    <div className="training-history-columns" aria-hidden="true"><span>Run</span><span>Saved</span>
      <span>Updated</span><span>Status</span></div>
    <nav className="trial-phases training-run-list" aria-label="Previous training batches">
      {filtered.slice(start, end).map((item) => {
        const { count, total, unit } = savedProgress(item);
        return <button key={item.id} type="button" aria-pressed={item.id === phase.id} onClick={() => onSelect(item.id)}>
          <span className="training-history-name">{item.label}
            {item.map_id && <small>{maps[item.map_id] ?? item.map_id}</small>}
          </span>
          <span className="training-history-progress">{count.toLocaleString()} / {total.toLocaleString()} {unit}</span>
          {item.updated ? <time dateTime={item.updated}>{dateFormat.format(new Date(item.updated))}</time> : <span />}
          {item.status && <RunStatus status={item.status} />}
        </button>;
      })}
    </nav>
    <div className="training-history-pagination">
      <button className="training-button" type="button" aria-label="Previous history page" disabled={!currentPage}
        onClick={() => setPage(currentPage - 1)}>Previous</button>
      <output aria-live="polite">{start + 1}–{end} of {filtered.length}</output>
      <button className="training-button" type="button" aria-label="Next history page" disabled={end >= filtered.length}
        onClick={() => setPage(currentPage + 1)}>Next</button>
    </div>
    </> : <p className="training-history-empty" role="status">No saved runs match those filters.</p>}
  </section>;
}

function TeamBreakdown({ row, attackTeam, onBot }) {
  const time = (value) => format(value, " s");
  const score = (value) => Number.isFinite(value) ? value : "—";
  return <section className="training-route-panel" aria-labelledby="match-breakdown">
    <div className="training-session-header">
      <h4 id="match-breakdown">Match breakdown</h4>
      <span>Near stand means within 30 m</span>
    </div>
    {[1, 2].map((team) => {
      const roster = row.bots.filter((bot) => bot.team === team);
      if (!roster.length) return null;
      const side = team === 1 ? "Blue" : "Red";
      const title = attackTeam ? side + (team === attackTeam ? " offense" : " defense") : side + " team";
      return <div key={team} className="training-role-table" tabIndex="0" aria-label={title + " match statistics"}>
        <table>
          <caption>{title}</caption>
          <thead><tr>{["Bot and role", "Median speed", "Peak speed", "Pickups", "100+ pickups", "Flag released",
            "Captures", "Deaths", "Near home", "Near enemy", "Carrying", "Skiing", "Jetting", "Health lost"].map(
              (column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
          <tbody>{roster.map((bot) => <tr key={bot.bot}>
            <th scope="row"><button className="training-role-bot" type="button"
              onClick={() => onBot(String(bot.bot))}>Bot {bot.bot} · {bot.role}</button></th>
            <td>{format(bot.median_kmh, " km/h")}</td><td>{format(bot.peak_kmh, " km/h")}</td>
            <td>{score(bot.pickups)}</td><td>{score(bot.fast_pickups)}</td><td>{score(bot.releases)}</td>
            <td>{score(bot.captures)}</td><td>{score(bot.deaths)}</td>
            <td>{time(bot.home_flag_seconds)}</td><td>{time(bot.enemy_flag_seconds)}</td>
            <td>{time(bot.carry_seconds)}</td><td>{time(bot.ski_seconds)}</td><td>{time(bot.jet_seconds)}</td>
            <td>{format(bot.health_lost, "", 0)}</td>
          </tr>)}</tbody>
        </table>
      </div>;
    })}
    {row.score_timeline?.length > 0 && <details className="training-route-events">
      <summary>Score timeline</summary>
      <ol className="training-score-flow">{row.score_timeline.map((entry) =>
        <li key={entry.seconds}><strong>{entry.blue}–{entry.red}</strong> <span>{time(entry.seconds)}</span></li>
      )}</ol>
    </details>}
  </section>;
}

function TeamAnalysis({ phase, keepRun, initialMatch, mapLabel }) {
  const [match, setMatch] = useState(initialMatch);
  const [botIndex, setBotIndex] = useState("1");
  const [showBotTrace, setShowBotTrace] = useState(false);
  const row = phase.rows.find((item) => String(item.campaign_attempt) === match) ?? phase.rows.at(-1);
  if (!row) return <p role="status">{["Running", "Stopping"].includes(phase.status) ? "Waiting for the first match result." : "No matches were saved."}</p>;
  const bot = row.bots.find((item) => String(item.bot) === botIndex) ?? row.bots[0];
  const attackTeam = phase.attack ? (row.attack_team ?? (phase.route_exploration ? null : 1)) : null;
  function openBot(number) {
    setBotIndex(number);
    setShowBotTrace(true);
  }
  return <>
    <CampaignFlight rows={phase.rows} row={row} selectMatch={(number) => { keepRun(); setMatch(String(number)); }} />
    <MatchRoutes key={row.campaign_attempt} phase={phase.id}
      clipTitle={`${mapLabel} · Match ${row.campaign_attempt} · ${row.blue}–${row.red}`} tracks={row.bots.map((item) => ({
      attempt: row.campaign_attempt, bot: item.bot, label: (item.team === 1 ? "Blue " : "Red ") + item.bot,
    }))} onReview={() => { keepRun(); setMatch(String(row.campaign_attempt)); }}
      picker={<ScopeFilter label="Match" value={match} onChange={setMatch} allLabel={"Latest match · " + phase.rows.at(-1).campaign_attempt}
        options={phase.rows.map((item) => [String(item.campaign_attempt), `Match ${item.campaign_attempt} · ${item.blue}–${item.red}`])} />} />
    <div className="trial-metrics">
      <Metric label="Blue score" value={row.blue} detail={row.blue_policy} tone="blue" />
      <Metric label="Red score" value={row.red} detail={row.red_policy} tone="red" />
      <Metric label="Match duration" value={format(row.seconds, " s")} />
      <Metric label="Matches saved" value={phase.rows.length + " / " + phase.total} />
      {phase.reused_waves !== undefined && <Metric label="Waves using verified resets" value={phase.reused_waves}
        detail={(phase.reset_fallbacks || 0) + " resets required a fresh game"} />}
      {phase.wall_seconds > 0 && <Metric label="Matches per hour"
        value={format(3600 * phase.timed_matches / phase.wall_seconds)}
        detail="For timed matches, including startup, preparation and failed resets" />}
      {row.base_equipment?.length > 0 && <Metric label="Base equipment downed"
        value={row.base_equipment.reduce((total, side) => total + side.generators + side.turrets, 0)}
        detail={row.base_equipment.map((side) => `${side.team === 1 ? "Blue" : "Red"} base · ${side.generators} generators · ${side.turrets} turrets`).join(" / ")} />}
      {bot?.airborne_seconds !== undefined && <Metric label={`Bot ${bot.bot} airborne`} value={format(bot.airborne_seconds, " s")}
        detail={`${format(bot.airborne_objective_advance_m, " m")} toward a flag objective`} />}
      {bot?.fast_air_seconds !== undefined && <>
        <Metric label="Fast airborne time" value={format(bot.fast_air_seconds, " s")}
          detail={`${format(bot.longest_fast_air_seconds, " s")} longest stretch at 45 km/h or faster`} />
        <Metric label="Fast glide without jets" value={format(bot.fast_glide_seconds, " s")}
          detail={`${format(bot.jet_seconds, " s")} under jet power`} />
        {bot.landing_count > 0 && <Metric label="Speed retained on landing" value={percent(bot.landing_speed_retained)}
          detail={`${format(bot.landing_energy)} jet energy at landing across ${bot.landing_count} landings`} />}
      </>}
      {bot?.ground_jog_seconds !== undefined && <Metric label={`Bot ${bot.bot} grounded jogging`}
        value={format(bot.ground_jog_seconds, " s")} />}
      {bot?.open_travel_jog_ratio !== undefined && <Metric label={`Bot ${bot.bot} jogging in open travel`}
        value={percent(bot.open_travel_jog_ratio)} detail={`${format(bot.open_travel_seconds, " s")} of open travel`} />}
      {row.duel && <>
        <Metric label="Duel outcome" value={{ captured: "Captured", intercepted: "Intercepted", flag_lost: "Flag lost", timeout: "Time limit" }[row.duel.outcome]}
          detail={(row.duel.capper === 1 ? "Blue" : "Red") + " capper · " + format(row.duel.seconds, " s")} />
        <Metric label="Chaser shots in flight" value={row.duel.airborne_launches}
          detail={row.duel.combat_complete ? `${row.duel.airborne_hits} did confirmed damage` : "Combat recording incomplete"} />
        <Metric label="Confirmed damage to carrier" value={format(row.duel.carrier_damage)} />
        {Number.isFinite(row.duel.homeward_advance_m) && <Metric label="Carrier progress toward home"
          value={format(row.duel.homeward_advance_m, " m")} detail={row.duel.escape_seconds != null
            ? `${format(row.duel.escape_seconds, " s")} to make 35 m of progress` : ""} />}
        {row.duel.hit_recovery_seconds != null && <Metric label="Carrier recovery after damage" value={format(row.duel.hit_recovery_seconds, " s")} />}
      </>}
      {row.offense_support?.some(role => role.captures_after_nearby_clear > 0) &&
        <Metric label="Offense support after an equipment clear" value={format(Math.max(...row.offense_support.map(role => role.captures_after_nearby_clear ?? 0)))}
          detail="Most capture windows supported per bot in a role" />}
    </div>
    {Boolean(phase.human_reference?.recordings || Object.keys(phase.flight_transfer ?? {}).length || phase.pursuit_profile?.profile) &&
      <details className="training-panel training-coverage">
        <summary>Movement used this run</summary>
        <dl>
          {phase.human_reference?.recordings > 0 && <><dt>Human movement reference</dt>
            <dd>{phase.human_reference.recordings} recordings · {phase.human_reference.jet_reserve} energy reserve</dd></>}
          {Object.entries(phase.flight_transfer ?? {}).map(([course, plan]) => <React.Fragment key={course}>
            <dt>{flightCourses[course]?.label ?? course}</dt><dd>{flightProfiles[plan.profile]}</dd>
          </React.Fragment>)}
          {phase.pursuit_profile?.profile && <><dt>Chase timing</dt><dd>{pursuitLabel[phase.pursuit_profile.profile]}</dd></>}
        </dl>
      </details>}
    {phase.pursuit_profiles?.length > 0 && <details className="training-panel training-coverage">
      <summary>Chase timing by side</summary>
      <div className="training-role-table" tabIndex="0">
        <table><thead><tr><th scope="col">Profile</th><th scope="col">Blue evidence</th><th scope="col">Red evidence</th><th scope="col">Transfer</th></tr></thead>
          <tbody>{phase.pursuit_profiles.map(profile => <tr key={profile.profile}>
            <th scope="row">{pursuitLabel[profile.profile]}</th><td>{profile.blue_samples}</td><td>{profile.red_samples}</td>
            <td>{profile.qualified ? "Qualified" : "Needs evidence on both sides"}</td>
          </tr>)}</tbody></table>
      </div>
    </details>}
    {phase.attack && <AttackDrillReport phase={phase} />}
    {phase.mode === "teams" && <LineupReport rows={phase.rows} />}
    {row.guided_routes?.length > 0 && <details className="training-panel training-coverage">
      <summary>Capper approaches</summary>
      <div className="training-role-table" tabIndex="0">
        <table>
          <thead><tr>{["Bot and route", "Outcome", "Pickup speed", "Speed toward home", "Escape to 30 m", "Closest pass", "Where it ended"].map(
            (column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
          <tbody>{row.guided_routes.map((route) => <tr key={route.bot}>
            <th scope="row"><button className="training-role-bot" type="button"
              onClick={() => openBot(String(route.bot))}>Bot {route.bot} · {routeLabel(route.route)}</button></th>
            <td>{{ grab: "Grab", capture: "Capture", miss: "Miss", censored: "Incomplete" }[route.outcome]}</td>
            <td>{format(route.pickup_kmh > 0 ? route.pickup_kmh : null, " km/h")}</td>
            <td>{format(route.pickup_kmh > 0 ? route.homeward_kmh : null, " km/h")}</td>
            <td>{format(route.escape_seconds, " s")}</td>
            <td>{format(route.pass_gap_m, " m")}{route.pass_speed_kmh != null && " · " + format(route.pass_speed_kmh, " km/h")}</td>
            <td>{routeFailure[route.failure] ?? "—"}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </details>}
    <MatchTimeline events={row.events} onBot={openBot} />
    {row.combat_observed && <CombatReport key={row.campaign_attempt} phase={phase.id} attempt={row.campaign_attempt} onBot={openBot} />}
    <details className="training-panel training-coverage">
      <summary>Team breakdown</summary>
      <TeamBreakdown row={row} attackTeam={attackTeam} onBot={openBot} />
    </details>
    {bot && <details className="training-panel training-coverage" open={showBotTrace}
      onToggle={event => setShowBotTrace(event.currentTarget.open)}>
      <summary>Individual bot data</summary>
      {showBotTrace && <>
        <label className="trial-filter">Bot route<select value={botIndex} onChange={(event) => setBotIndex(event.target.value)}>
          {row.bots.map((item) => <option key={item.bot} value={item.bot}>
            {item.team === 1 ? "Blue" : "Red"} {item.bot} · {item.role}</option>)}
        </select></label>
        <TrialTrace phase={phase} row={{ ...row, has_trace: bot.samples > 0 }} bot={bot}
          onReview={() => { keepRun(); setMatch(String(row.campaign_attempt)); }} />
      </>}
    </details>}
  </>;
}

const flightProfiles = {
  "run-only": "Running baseline", "ski-only": "Ski only", "short-jets": "Short jets",
  "steady-jets": "Steady jets", "long-jets": "Long jets", "ski-delayed": "Delayed ski",
  "ski-gentle": "Gentle ski steering", "ski-tight": "Tight ski steering",
};
const pursuitLabel = { "short-lead": "Short lead", "balanced-lead": "Balanced lead", "long-lead": "Long lead" };

function FlightAnalysis({ phase, keepRun }) {
  const [wave, setWave] = useState("");
  const row = phase.rows.find(item => String(item.campaign_attempt) === wave) ?? phase.rows.at(-1);
  if (!row) return <p role="status">No flight waves saved yet.</p>;
  const result = phase.flight_comparison;
  const kind = phase.flight_course ?? "straight";
  const recovery = kind === "recovery";
  const hill = kind === "downhill" || kind === "uphill";
  const uphill = kind === "uphill";
  const strict = phase.strict_flight;
  const baseline = result?.baseline ?? (strict ? (kind === "downhill" ? "ski-only" : "steady-jets") : (uphill ? "ski-only" : "run-only"));
  const completed = hill ? row.bots.filter(bot => bot.finished) : [];
  const medianValue = (bots, key) => median(bots.map(bot => bot[key]).filter(Number.isFinite));
  const comparisonHeaders = recovery
    ? ["Side", "Paired starts", "Baseline recoveries", "Profile recoveries", "Median recovery"]
    : hill
    ? ["Side", "Paired starts", "Baseline finishes", "Profile finishes", ...(uphill ? ["Height gained", "Forward under jet power"] : ["Baseline exit", "Profile exit", "Speed retained"])]
    : ["Side", "Paired starts", strict ? "Baseline speed" : "Running speed", "Flight speed", "Forward distance in air"];
  const botHeaders = recovery
    ? ["Bot", "Profile", "Recovery time", "Starting jet energy", "Starting sideways speed", "Forward distance"]
    : hill
    ? ["Bot", "Profile", "Finish", "Entry speed", "Exit speed", ...(uphill ? ["Height gained", "Forward under jet power"] : ["Speed retained"]), "Forward distance"]
    : ["Bot", "Profile", "Median", "Peak", "Airtime", "Air distance", "Straight-line distance", "Below 15 km/h"];
  if (strict) {
    comparisonHeaders.push("Most time jogging");
    botHeaders.push("Grounded jogging");
  }
  const tracks = row.bots.map(bot => ({
    attempt: row.campaign_attempt, bot: bot.bot, label: `${bot.team === 1 ? "Blue" : "Red"} ${bot.bot}`,
  }));
  return <>
    <MatchRoutes key={row.campaign_attempt} phase={phase.id} tracks={tracks} title={hill || recovery ? flightCourses[kind].label + " replay" : "Flight replay"}
      onReview={() => { keepRun(); setWave(String(row.campaign_attempt)); }}
      picker={<ScopeFilter label="Wave" value={wave} onChange={setWave} allLabel={`Latest wave · ${phase.rows.at(-1).campaign_attempt}`}
        options={phase.rows.map(item => [String(item.campaign_attempt), `Wave ${item.campaign_attempt}`])} />} />
    <div className="trial-metrics">
      {recovery ? <>
        <Metric label="Recovered forward speed" value={`${row.bots.filter(bot => bot.recovered).length} / ${row.bots.length}`} />
        <Metric label="Median recovery time" value={format(medianValue(row.bots,"recovery_seconds"), " s")} />
        <Metric label="Median starting jet energy" value={format(medianValue(row.bots,"initial_energy"))} />
      </> : hill ? <>
        <Metric label="Courses completed" value={`${completed.length} / ${row.bots.length}`} />
        {uphill ? <>
          <Metric label="Median height gained" value={format(medianValue(row.bots, "elevation_gain_m"), " m")} />
          <Metric label="Median forward under jet power" value={format(medianValue(row.bots, "jet_forward_m"), " m")} />
        </> : <>
          <Metric label="Median exit speed" value={format(medianValue(completed, "exit_kmh"), " km/h")} />
          <Metric label="Median speed retained" value={percent(medianValue(completed, "retention"))} detail="Exit speed ÷ speed at 20 m" />
        </>}
      </> : <>
        <Metric label="Median cruising speed" value={format(medianValue(row.bots, "median_kmh"), " km/h")} />
        <Metric label="Median forward distance in air" value={format(medianValue(row.bots, "airborne_m"), " m")} />
        <Metric label="Median time below 15 km/h" value={format(medianValue(row.bots, "slow_seconds"), " s")} />
      </>}
      {!hill && !recovery && row.bots.some(bot => Number.isFinite(bot.fast_air_seconds)) && <>
        <Metric label="Median fast airborne advance" value={format(medianValue(row.bots, "fast_air_forward_m"), " m")}
          detail="Forward distance at 45 km/h or faster" />
        <Metric label="Median longest fast flight" value={format(medianValue(row.bots, "longest_fast_air_seconds"), " s")} />
        <Metric label="Median fast glide without jets" value={format(medianValue(row.bots, "fast_glide_seconds"), " s")} />
        <Metric label="Median speed retained on landing" value={percent(medianValue(row.bots, "landing_speed_retained"))}
          detail={`${format(medianValue(row.bots, "landing_energy"))} median jet energy at landing`} />
      </>}
      {strict && <Metric label="Worst grounded jogging" value={percent(Math.max(...row.bots.map(bot => bot.ground_jog_ratio)))}
        detail="Profiles must stay at or below 5% to pass" />}
      <Metric label="Course distance" value={format(phase.course_m, " m", 0)}
        detail={row.testing ? `${flightProfiles[baseline]} vs. ${flightProfiles[row.testing]}` : "Profile trials"} />
    </div>
    {result && <section className="training-panel">
      <h3>{result.qualified ? "Flight profile passed on both sides" : "Flight profile did not pass on both sides"}</h3>
      <p>{flightProfiles[result.profile]} compared with {flightProfiles[baseline].toLowerCase()} on the same courses.</p>
      <div className="training-role-table" tabIndex="0">
        <table><thead><tr>{comparisonHeaders.map(
          label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{result.sides.map(side => <tr key={side.team}>
            <th scope="row">{side.team === 1 ? "Blue" : "Red"}</th>
            <td>{side.pairs}</td>
            {recovery ? <>
              <td>{side.baseline_finish} / {side.pairs}</td><td>{side.candidate_finish} / {side.pairs}</td>
              <td>{format(side.recovery_seconds, " s")}</td>
            </> : hill ? <>
              <td>{side.baseline_finish} / {side.pairs}</td><td>{side.candidate_finish} / {side.pairs}</td>
              {uphill ? <><td>{format(side.elevation, " m")}</td><td>{format(side.jet_forward, " m")}</td></>
                : <><td>{format(side.baseline_exit, " km/h")}</td><td>{format(side.candidate_exit, " km/h")}</td><td>{percent(side.retention)}</td></>}
            </> : <><td>{format(side.baseline_kmh, " km/h")}</td><td>{format(side.candidate_kmh, " km/h")}</td>
              <td>{format(side.candidate_air_m, " m")}</td></>}
            {strict && <td>{percent(side.candidate_max_jog_ratio)}</td>}
          </tr>)}</tbody>
        </table>
      </div>
    </section>}
    <details className="training-panel training-coverage">
      <summary>Bot movement by profile</summary>
      <div className="training-role-table" tabIndex="0">
        <table><thead><tr>{botHeaders.map(
          label => <th key={label} scope="col">{label}</th>)}</tr></thead>
          <tbody>{row.bots.map(bot => <tr key={bot.bot}>
            <th scope="row">{bot.team === 1 ? "Blue" : "Red"} {bot.bot}</th>
            <td>{flightProfiles[bot.profile]}</td>
            {recovery ? <>
              <td>{bot.recovered ? format(bot.recovery_seconds, " s") : "Incomplete"}</td>
              <td>{format(bot.initial_energy)}</td><td>{format(bot.initial_lateral_kmh, " km/h")}</td>
              <td>{format(bot.forward_m, " m")}</td>
            </> : hill ? <>
              <td>{bot.finished ? "Finished" : "Incomplete"}</td><td>{format(bot.entry_kmh, " km/h")}</td><td>{format(bot.exit_kmh, " km/h")}</td>
              {uphill ? <><td>{format(bot.elevation_gain_m, " m")}</td><td>{format(bot.jet_forward_m, " m")}</td></>
                : <td>{percent(bot.retention)}</td>}
              <td>{format(bot.forward_m, " m")}</td>
            </> : <><td>{format(bot.median_kmh, " km/h")}</td><td>{format(bot.peak_kmh, " km/h")}</td>
              <td>{format(bot.airborne_seconds, " s")}</td><td>{format(bot.airborne_m, " m")}</td>
              <td>{format(bot.forward_m, " m")}</td><td>{format(bot.slow_seconds, " s")}</td></>}
            {strict && <td>{format(bot.ground_jog_seconds, " s")} · {percent(bot.ground_jog_ratio)}</td>}
          </tr>)}</tbody>
        </table>
      </div>
    </details>
  </>;
}

const timelineNames = {
  flag_pickup: "Flag pickup", flag_returned: "Flag returned to stand", flag_dropped: "Flag dropped",
  cap: "Capture", flag_lost: "Flag released",
  carrier_down: "Carrier went down", chase_started: "Chase started", generator_down: "Generator went down",
  turret_down: "Turret went down", cutoff_started: "Cutoff started",
};

const routeFailure = {
  outbound_death: "Went down on approach", carrier_down: "Carrier went down", flag_lost: "Lost the flag",
  other_carrier: "Another bot carried it", missed_flag: "Passed without a pickup", return_timeout: "Return timed out",
  approach_timeout: "Approach timed out", match_ended: "Match ended",
};

function AttackDrillReport({ phase }) {
  const setups = phase.mode === "defended" ? [...new Set(phase.rows.filter((row) => row.attack_team).map((row) => row.policy))] : [null];
  const groups = setups.flatMap((setup) => [1, 2].map((team) => {
    const games = phase.rows.filter((row) => row.attack_team === team && (!setup || row.policy === setup));
    const guided = games.flatMap((row) => row.guided_routes).filter((route) => route.team === team);
    const attempts = guided.filter((route) => route.outcome !== "censored");
    const grabs = attempts.filter((route) => ["grab", "capture"].includes(route.outcome)).length;
    const captures = attempts.filter((route) => route.outcome === "capture").length;
    const events = games.flatMap((row) => row.events ?? []);
    const support = games.flatMap((row) => row.offense_support ?? []).filter((row) => row.team === team);
    const returns = games.every((row) => row.flag_returns_observed)
      ? events.filter((event) => event.event === "flag_returned" && event.team === 3 - team).length : null;
    const drops = returns === null ? null : events.filter((event) => event.event === "flag_dropped" && event.team === 3 - team).length;
    return { team, setup, games: games.length, attempts: attempts.length, grabs, captures, returns, drops,
      carrierDown: attempts.filter((route) => route.failure === "carrier_down").length,
      timing: support.length ? median(support.map((row) => row.timing)) : null };
  }));
  if (groups.every((row) => !row.games)) return null;
  return <details className="training-panel training-coverage">
    <summary>Attack outcomes by side</summary>
    <div className="training-role-table" tabIndex="0">
      <table><thead><tr>{["Attack side", ...(phase.mode === "defended" ? ["Defense setup"] : []), "Games", "First-pass grabs", "No pickup", "Clean captures", "Carrier went down", "Defending flag returns", "Capper support timing"].map(
        (heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{groups.map((row) => <tr key={`${row.setup}/${row.team}`}>
          <th scope="row">{row.team === 1 ? "Blue" : "Red"}</th>
          {row.setup && <td>{row.setup}</td>}<td>{row.games}</td>
          <td>{row.attempts ? `${row.grabs} / ${row.attempts}` : "—"}</td>
          <td>{row.attempts ? `${row.attempts - row.grabs} / ${row.attempts}` : "—"}</td>
          <td>{row.grabs ? `${row.captures} / ${row.grabs}` : "—"}</td>
          <td>{row.grabs ? `${row.carrierDown} / ${row.grabs}` : "—"}</td>
          <td>{row.drops ? `${row.returns} / ${row.drops}` : "—"}</td>
          <td>{row.timing === null ? "—" : percent(row.timing)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p>First-pass counts use guided routes with observed outcomes. Support timing is the share of sampled capper approaches with support near the enemy stand. Returns count flags restored to their stand out of observed drops.</p>
  </details>;
}

function LineupReport({ rows }) {
  const pairs = new Map();
  for (const row of rows) {
    if (!row.lineup_pair) continue;
    const pair = pairs.get(row.lineup_pair) ?? { policy: row.policy };
    pair[row.candidate_team === 1 ? "blue" : "red"] = row.margin;
    pairs.set(row.lineup_pair, pair);
  }
  if (!pairs.size) return null;
  return <details className="training-panel training-coverage">
    <summary>Lineup results</summary>
    <p>Each margin is the candidate lineup’s captures minus the balanced lineup’s captures.</p>
    <div className="training-role-table" tabIndex="0">
      <table><thead><tr>{["Pair", "Candidate lineup", "Blue margin", "Red margin", "Paired margin"].map(
        (heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{[...pairs].map(([number, pair]) => <tr key={number}>
          <th scope="row">{number}</th><td>{pair.policy}</td><td>{pair.blue ?? "—"}</td><td>{pair.red ?? "—"}</td>
          <td>{pair.blue === undefined || pair.red === undefined ? "Incomplete" : pair.blue + pair.red}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </details>;
}

function CombatReport({ phase, attempt, onBot }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!open || report) return;
    const controller = new AbortController();
    async function loadCombat() {
      try {
        const response = await fetch(`/api/combat/${phase}/${attempt}`, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Combat evidence unavailable");
        setReport(await response.json());
        setFailed(false);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }
    loadCombat();
    return () => controller.abort();
  }, [open, report, phase, attempt]);
  const hits = report?.events.filter((row) => row.event === "damage") ?? [];
  const launches = report?.events.filter((row) => row.event === "launch") ?? [];
  const contacts = report?.events.filter((row) => row.event === "contact") ?? [];
  const aims = report?.aim ?? [];
  const creditedShots = new Set(hits.map((row) => row.shot));
  const contactShots = new Set(contacts.map((row) => row.shot));
  const projectileLabel = (name) => name.replace(/^BP_Projectile_(?:Topaz_)?/, "").replace(/_C$/, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2").replaceAll("_", " ");
  const byProjectile = new Map();
  for (const row of launches) {
    const count = byProjectile.get(row.projectile) ?? {
      label: row.weapon ?? projectileLabel(row.projectile), launches: 0, contacted: 0, credited: 0, angles: [],
    };
    count.launches += 1;
    count.contacted += Number(contactShots.has(row.shot));
    count.credited += Number(creditedShots.has(row.shot));
    if (Number.isFinite(row.aim_angle_deg)) count.angles.push(row.aim_angle_deg);
    byProjectile.set(row.projectile, count);
  }
  return <details className="training-panel training-coverage" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Projectile observations</summary>
    {!report && open && <p role="status">{failed ? "Combat evidence unavailable." : "Loading combat evidence…"}</p>}
    {report && <>
      <p>{launches.length} tracked launches · {contacts.length} physical enemy contacts · {hits.length} confirmed damage events{report.complete ? "" : " · Partial capture"}.</p>
      <p>Damage credit requires an observed loss of health or shields and evidence that the native projectile or effect caused it.</p>
      {aims.length > 0 && <p>The game aimed at the target in {aims.reduce((sum, row) => sum + row.aimed, 0)} of {aims.reduce((sum, row) => sum + row.decisions, 0)} native aim decisions. Projectile damage is measured separately.</p>}
      {aims.some((row) => row.adjusted > 0) && <p>The aim profile redirected {aims.reduce((sum, row) => sum + (row.adjusted ?? 0), 0)} wide aim decisions.</p>}
      {byProjectile.size > 0 && <div className="training-role-table" tabIndex="0">
        <table><thead><tr><th scope="col">Weapon or projectile</th><th scope="col">Tracked launches</th><th scope="col">Shots with enemy contact</th>
          <th scope="col">Shots with credited damage</th><th scope="col">Credited share</th><th scope="col">Median launch angle to target</th></tr></thead>
          <tbody>{[...byProjectile.entries()].map(([projectile, count]) => <tr key={projectile}>
            <th scope="row" title={projectile}>{count.label}</th><td>{count.launches}</td><td>{count.contacted}</td><td>{count.credited}</td>
            <td>{report.complete ? percent(count.credited / count.launches) : "—"}</td>
            <td>{count.angles.length ? `${format(median(count.angles), "°")} · ${count.angles.length} samples` : "—"}</td>
          </tr>)}</tbody>
        </table>
      </div>}
      {launches.some((row) => Number.isFinite(row.aim_angle_deg)) && <p>The launch angle uses the target’s position at firing time. Leading a moving target or compensating for projectile drop can increase the angle.</p>}
      {hits.length > 0 && <div className="training-role-table" tabIndex="0">
        <table><thead><tr>{["Match time", "Weapon or projectile", "Shooter", "Target", "Range", "Shooter airborne at launch", "Target airborne at impact", "Damage", "Native event"].map(
          (heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
          <tbody>{hits.map((row, index) => <tr key={index}>
            <td>{format(row.seconds, " s")}</td><td title={row.projectile}>{row.weapon ?? projectileLabel(row.projectile)}</td>
            <td><button type="button" className="training-role-bot" onClick={() => onBot(String(row.shooter))}>Bot {row.shooter}</button></td>
            <td>Bot {row.target}</td><td>{format(row.range_m, " m")}</td>
            <td>{row.shooter_airborne == null ? "—" : row.shooter_airborne ? "Yes" : "No"}</td>
            <td>{row.airborne == null ? "—" : row.airborne ? "Yes" : "No"}</td><td>{format(row.damage)}</td>
            <td>{{ contact: "Contact", projectile_stop: "Projectile stop", predicted_hit: "Predicted hit", effect_application: "Native damage effect", native_impact: "Delayed native impact" }[row.source] ?? "—"}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </>}
  </details>;
}

function MatchTimeline({ events, onBot }) {
  if (!events) return null;
  return <details className="training-panel training-coverage">
    <summary>Match events</summary>
    {events.length === 0 ? <p>No flag, pursuit, or equipment events were observed.</p> :
      <div className="training-role-table" tabIndex="0">
        <table><thead><tr><th scope="col">Match time</th><th scope="col">Event</th><th scope="col">Team</th><th scope="col">Bot</th></tr></thead>
          <tbody>{events.map((event, index) => <tr key={index}>
            <td>{format(event.seconds, " s")}</td><td>{timelineNames[event.event] ?? event.event}</td>
            <td>{event.team === 1 ? "Blue" : "Red"}</td>
            <td>{event.bot ? <button type="button" className="training-role-bot" onClick={() => onBot(String(event.bot))}>Bot {event.bot}</button> : "—"}</td>
          </tr>)}</tbody>
        </table>
      </div>}
  </details>;
}

function CampaignAnalysis({ phase, phases, decision, view, setView, keepRun }) {
  const [route, setRoute] = useState("");
  const [defense, setDefense] = useState("");
  const [spawn, setSpawn] = useState("");
  const [result, setResult] = useState("");
  const [selected, setSelected] = useState(null);
  const rows = useMemo(() => phase.rows.filter((row) =>
    (!route || row.approach_route === route) && (!defense || String(row.defense_profile) === defense)
    && (!spawn || String(row.spawn) === spawn) && (!result || outcome(row) === result)),
  [phase.rows, route, defense, spawn, result]);
  const summary = useMemo(() => summarizeTrials(rows), [rows]);
  const latest = phase.rows.at(-1);
  const trial = rows.find((row) => row.campaign_attempt === selected) ?? rows.at(-1);
  const openTrial = (number) => { setSelected(number); setView("trials"); };
  const routeOptions = options(phase.rows, "approach_route", routeLabel);
  const defenseOptions = options(phase.rows, "defense_profile", (value) => "Profile " + value);
  const spawnOptions = options(phase.rows, "spawn", (value) => "Spawn " + value);
  const hasFirstPassData = rows.some((row) => row.recovered != null);
  const skiGrabs = rows.filter((row) => row.skiing_flythrough_grab);

  return <>
    {latest && <div className="trial-latest">
      <strong>Latest trial {latest.campaign_attempt} · {routeLabel(latest.approach_route)}</strong>
      <span>{outcome(latest)} · {format(latest.peak_kmh, " km/h peak")}</span>
      <time dateTime={phase.updated}>{new Date(phase.updated).toLocaleString()}</time>
    </div>}
    <nav aria-label="Analytics view" className="trial-views">
      {sections.map(([id, label]) => <button type="button" key={id} aria-pressed={id === view}
        onClick={() => setView(id)}>{label}</button>)}
    </nav>
    {view !== "evaluation" && phase.rows.length > 0 && <div className="trial-scopes">
      {routeOptions.length > 0 && <ScopeFilter label="Route" value={route} onChange={setRoute} allLabel="All routes" options={routeOptions} />}
      {defenseOptions.length > 0 && <ScopeFilter label="Defense" value={defense} onChange={setDefense} allLabel="All profiles" options={defenseOptions} />}
      {spawnOptions.length > 0 && <ScopeFilter label="Spawn" value={spawn} onChange={setSpawn} allLabel="All spawns" options={spawnOptions} />}
      <ScopeFilter label="Outcome" value={result} onChange={setResult} allLabel="All outcomes"
        options={["Capture", "Grab only", "Miss"].map((value) => [value, value])} />
      <span className="trial-scope-count">{rows.length} of {phase.rows.length} trials</span>
    </div>}
    {view === "evaluation" ? <EvaluationCharts phase={phase} phases={phases} decision={decision} />
      : rows.length === 0 ? <p className="trial-empty" role="status">
        {phase.rows.length ? "No trials match these filters." : "Waiting for the first completed trial in this batch."}
      </p>
      : view === "overview" ? <>
        <div className="trial-metrics" data-reviewed-rows>
          <Metric label="Flag grabs" value={summary.grabs} detail={hasFirstPassData ? summary.firstPass + " first-pass grabs" : "Across " + rows.length + " trials"} />
          <Metric label="Captures" value={summary.captures + " · " + percent(summary.captureRate)}
            detail={summary.fastestCapture && "Fastest " + format(summary.fastestCapture.seconds, " s") + " · trial " + summary.fastestCapture.campaign_attempt} />
          <Metric label="Median trial speed" value={format(summary.medianSpeed, " km/h")}
            detail={"Fastest peak " + format(summary.fastestPeak?.peak_kmh, " km/h")} />
          <Metric label="Fastest flag grab" value={format(summary.fastestGrab?.grab_kmh, " km/h")}
            detail={summary.fastestGrab && "Trial " + summary.fastestGrab.campaign_attempt + " · " + routeLabel(summary.fastestGrab.approach_route)} />
        </div>
        {hasFirstPassData && <p className="trial-note">First-pass grabs moving toward home: {summary.homeward} total · {summary.fastHomeward} at 200+ km/h · {summary.eliteHomeward} at 330+ km/h.</p>}
        {rows.some((row) => row.skiing_flythrough_grab != null) && <p className="trial-note">
          Skiing fly-through grabs: {skiGrabs.length} · {skiGrabs.filter((row) => row.grab_homeward_kmh > 0).length} headed toward home.
        </p>}
        <ProgressCharts rows={rows} selectTrial={openTrial} />
      </> : view === "matchups" ? <RouteCharts rows={rows} selectTrial={openTrial} />
      : view === "flags" ? <FlagCharts rows={rows} selectTrial={openTrial} />
      : <>
        <label className="trial-filter trial-select-run">Inspect trial
          <select value={trial.campaign_attempt} onChange={(event) => setSelected(Number(event.target.value))}>
            {[...rows].reverse().map((row) => <option key={row.campaign_attempt} value={row.campaign_attempt}>
              {row.campaign_attempt} · {outcome(row)} · {routeLabel(row.approach_route)}
            </option>)}
          </select>
        </label>
        <TrialTrace phase={phase} row={trial} onReview={() => { keepRun(); setSelected(trial.campaign_attempt); }} />
        <TrialTable rows={rows} selectTrial={openTrial} selected={trial.campaign_attempt} />
      </>}
  </>;
}

function BenchmarkReport({ phase }) {
  const comparison = phase.comparison;
  const plan = phase.frozen_tactics;
  const aim = phase.benchmark_aim;
  return <section className="training-panel" aria-label="Baseline comparison">
    <h3>Baseline comparison</h3>
    {phase.field_benchmark && <p>Both sides use reserved starts. Opponents for this run include {phase.opponents?.join(", ") || "original tactics"}.</p>}
    {phase.aim_benchmark_profile > 0 && <p>The candidate uses the frozen {phase.aim_benchmark_profile}% aim profile for both games in each pair.</p>}
    <p>{comparison?.pairs.length ?? 0} of {phase.target_pairs} mirrored pairs saved.</p>
    {comparison?.pending_pairs > 0 && <p>{comparison.pending_pairs} incomplete pair waiting for its other side.</p>}
    {comparison?.excluded_pairs > 0 && <p>{comparison.excluded_pairs} pairs excluded after checking native starts and opponents.</p>}
    {plan && <details className="training-mode-guide">
      <summary>Frozen tactics</summary>
      <dl>{Object.entries(plan.candidate).map(([role, profile]) => <React.Fragment key={role}>
        <dt>{role}</dt><dd>{profile} · {plan.training_samples[role]} training samples · baseline {plan.baseline[role]}</dd>
      </React.Fragment>)}</dl>
      {!phase.field_benchmark && Object.keys(plan.candidate).every((role) => plan.candidate[role] === plan.baseline[role]) && <p>Both sides use the same tactics in this run.</p>}
    </details>}
    {comparison?.pairs.length > 0 && <>
      <div className="trial-metrics">
        <Metric label="Candidate pairs won" value={`${comparison.wins} / ${comparison.pairs.length}`} detail={`${comparison.draws} drawn · ${comparison.losses} lost`} />
        <Metric label="Mean capture margin per pair" value={format(comparison.mean_margin)}
          detail={comparison.interval95 ? `95% interval ${comparison.interval95.map((value) => format(value)).join(" to ")}` : "At least eight completed pairs needed for an interval"} />
      </div>
      <div className="training-role-table" tabIndex="0">
        <table><thead><tr><th scope="col">Pair</th>{phase.field_benchmark && <th scope="col">Opponent</th>}
          <th scope="col">Candidate on Blue</th><th scope="col">Candidate on Red</th><th scope="col">Capture margin</th></tr></thead>
          <tbody>{comparison.pairs.map((pair) => <tr key={pair.pair}>
            <th scope="row">{pair.pair}</th>{phase.field_benchmark && <td>{pair.blue.opponent}</td>}
            <td>{pair.blue.candidate}–{pair.blue.baseline}</td><td>{pair.red.candidate}–{pair.red.baseline}</td><td>{pair.margin}</td>
          </tr>)}</tbody></table>
      </div>
    </>}
    {aim && <details className="training-coverage">
      <summary>Held-out projectile accuracy</summary>
      <p>Pairs with complete evidence: {aim.qualified_pairs}{aim.excluded_pairs ? ` · ${aim.excluded_pairs} excluded` : ""}.</p>
      {aim.qualified_pairs > 0 && <>
        <p>Each side is compared across the two games, with its frozen candidate profile and tactics in one game and its frozen baseline in the other.</p>
        <div className="training-role-table" tabIndex="0">
          <table><thead><tr><th scope="col">Side</th><th scope="col">Candidate damaging shots</th>
            <th scope="col">Baseline damaging shots</th><th scope="col">Mean paired gain</th></tr></thead>
            <tbody>{aim.sides.map((row) => <tr key={row.team}>
              <th scope="row">{row.team === 1 ? "Blue" : "Red"}</th>
              <td>{row.candidate.damaged} / {row.candidate.launched}</td>
              <td>{row.baseline.damaged} / {row.baseline.launched}</td>
              <td>{format(row.mean_gain * 100, " pp")}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <p>{aim.interval95 ? `95% interval for the paired gain across both sides: ${aim.interval95.map((value) => format(value * 100, " pp")).join(" to ")}.`
          : `An interval is available after ${aim.min_interval_pairs} pairs with complete evidence.`}</p>
      </>}
    </details>}
  </section>;
}

function AimCalibrationReport({ phase }) {
  const result = phase.aim_comparison;
  const reasons = {
    qualified: "Qualified", partial_combat: "Combat recording was partial",
    no_aim_decisions: "No native aim decisions observed", baseline_adjusted: "Baseline was adjusted",
    no_adjustments: "Candidate made no aim adjustments", too_few_launches: "Fewer than five tracked launches on a side",
  };
  return <section className="training-panel" aria-label="Aim calibration results">
    <h3>Aim calibration</h3>
    <p>{phase.rows.length} of {phase.target_pairs * 2} games saved. The selected profile is {result?.selected ? `${result.selected}%` : "native aim"}.</p>
    {result && <div className="training-role-table" tabIndex="0">
      <table><thead><tr><th scope="col">Aim profile</th><th scope="col">Qualified pairs</th><th scope="col">Blue gain</th><th scope="col">Red gain</th><th scope="col">95% interval</th></tr></thead>
        <tbody>{result.profiles.map((profile) => <tr key={profile.level}>
          <th scope="row">{profile.level}% of native wide aims redirected</th>
          <td>{profile.pairs} / {result.min_pairs} needed</td>
          {[0, 1].map((index) => <td key={index}>{profile.gains[index] == null ? "—" : format(profile.gains[index] * 100, " pp")}</td>)}
          <td>{profile.interval95 ? profile.interval95.map((value) => format(value * 100, " pp")).join(" to ") : "—"}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    <p>{result && !result.same_side
      ? "This archived report compared opponents in the same game."
      : "Gains compare each side with its own baseline across the pair, using the share of tracked launches that caused confirmed enemy damage."} Earlier compatible calibration pairs count toward qualification.</p>
    {phase.aim_games?.length > 0 && <details>
      <summary>Game evidence</summary>
      <div className="training-role-table" tabIndex="0">
        <table><thead><tr><th scope="col">Game</th><th scope="col">Candidate</th><th scope="col">Adjustments</th>
          <th scope="col">Candidate shots causing damage</th><th scope="col">Baseline shots causing damage</th><th scope="col">Qualification</th></tr></thead>
          <tbody>{phase.aim_games.map((game) => {
            const candidate = game.teams[game.candidate_team];
            const baseline = game.teams[3 - game.candidate_team];
            return <tr key={game.game}>
              <th scope="row">{game.game}</th><td>{game.level}% · {game.candidate_team === 1 ? "Blue" : "Red"}</td><td>{candidate.adjusted}</td>
              <td>{candidate.damaged} / {candidate.launched}</td><td>{baseline.damaged} / {baseline.launched}</td><td>{reasons[game.reason]}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
    </details>}
  </section>;
}

function TrainingCoverage({ phases, maps }) {
  const [coverageMode, setCoverageMode] = useState("screen");
  const summary = useMemo(() => {
    const totals = new Map();
    for (const phase of phases) {
      if (!phase.mode || phase.evaluation || phase.aim_calibration || !Object.hasOwn(maps, phase.map_id)) continue;
      const key = `${phase.mode}/${phase.map_id}`;
      const current = totals.get(key) ?? { saved: 0, attempts: 0, offense: [0, 0], defense: [0, 0] };
      current.saved += phase.screening ? phase.matches : phase.rows.length;
      if (phase.screening) current.attempts += phase.rows.length;
      for (const role of ["offense", "defense"]) {
        const observed = phase[`${role}_evidence`];
        if (observed) {
          current[role][0] += observed.eligible_matches;
          current[role][1] += observed.observed_matches;
        }
      }
      totals.set(key, current);
    }
    return totals;
  }, [phases, maps]);
  const rows = Object.entries(maps).map(([id, label]) => ({ id, label, ...summary.get(`${coverageMode}/${id}`) }));
  const covered = rows.filter((row) => row.saved).length;
  const evidence = (score) => score?.[1] ? `${score[0]} / ${score[1]}` : "—";
  return <details className="training-panel training-coverage">
    <summary>Map coverage</summary>
    <div className="training-scopes">
      <label className="trial-filter">Mode
        <select value={coverageMode} onChange={(event) => setCoverageMode(event.target.value)}>
          {modeGroups.map(([group, modes]) => <optgroup key={group} label={group}>
            {modes.map((key) => <option key={key} value={key}>{trainingModes[key].label}</option>)}
          </optgroup>)}
        </select>
      </label>
      <p>{covered} of {rows.length} current maps have saved results.</p>
    </div>
    <div className="training-role-table" tabIndex="0">
      <table>
        <thead><tr><th scope="col">Map</th><th scope="col">{coverageMode === "screen" ? "Saved waves" : "Saved results"}</th>
          {coverageMode === "screen" ? <th scope="col">Capper attempts</th>
            : <><th scope="col">Offense samples</th><th scope="col">Defense samples</th></>}</tr></thead>
        <tbody>{rows.map((row) => <tr key={row.id}>
          <th scope="row">{row.label}</th><td>{(row.saved ?? 0).toLocaleString()}</td>
          {coverageMode === "screen" ? <td>{(row.attempts ?? 0).toLocaleString()}</td>
            : <><td>{evidence(row.offense)}</td><td>{evidence(row.defense)}</td></>}
        </tr>)}</tbody>
      </table>
    </div>
    {coverageMode !== "screen" && <p>Samples show matches that qualified for learning out of matches with pressure data. A dash means no pressure data was saved.</p>}
  </details>;
}

function SeasonProgress({ phases, seasonRuns, maps }) {
  const [selected, setSelected] = useState("");
  const results = new Map(phases.map((phase) => [phase.id, phase]));
  const seasons = new Map();
  for (const run of seasonRuns) {
    const stages = seasons.get(run.season) ?? new Map();
    const key = run.map;
    const stage = stages.get(key) ?? { order: run.season_map, label: maps[key] ?? key };
    stage[run.evaluation ? "evaluation" : "training"] = { ...run, ...results.get(run.id) };
    stages.set(key, stage);
    seasons.set(run.season, stages);
  }
  const ids = [...seasons.keys()].sort().reverse();
  const stages = [...(seasons.get(selected || ids[0])?.values() ?? [])].sort((a, b) => a.order - b.order);
  if (!ids.length) return null;
  const progress = (stage) => stage ? `${stage.rows?.length ?? 0} / ${stage.total ?? stage.matches} · ${stage.status}` : "—";
  const complete = stages.filter((stage) => stage.training?.status === "Complete").length;
  return <details className="training-panel training-coverage">
    <summary>Season progress</summary>
    <div className="training-scopes">
      <ScopeFilter label="Season" value={selected} onChange={setSelected} allLabel="Latest season"
        options={ids.map((id) => [id, `Season ${id.slice(3, 7)}-${id.slice(7, 9)}-${id.slice(9, 11)} ${id.slice(11, 13)}:${id.slice(13, 15)}`])} />
      <p>Training complete on {complete} of {stages.length} maps.</p>
    </div>
    <div className="training-role-table" tabIndex="0">
      <table><thead><tr><th scope="col">Map</th><th scope="col">Training games</th>
        <th scope="col">Evaluation games</th><th scope="col">Completed evaluation pairs</th></tr></thead>
        <tbody>{stages.map((stage) => <tr key={stage.order}>
          <th scope="row">{stage.label}</th><td>{progress(stage.training)}</td><td>{progress(stage.evaluation)}</td>
          <td>{stage.evaluation ? stage.evaluation.comparison?.pairs.length ?? 0 : "—"}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </details>;
}

function CompareRuns({ phases, maps, select }) {
  const [map, setMap] = useState("");
  const [revision, setRevision] = useState("");
  const [roster, setRoster] = useState("");
  const [rules, setRules] = useState("");
  const runs = phases.filter((phase) => phase.mode && !phase.flight && phase.rows.length > 0).map((phase) => {
    const settings = phase.settings;
    const mapRevision = phase.provenance?.map_revision ?? "unknown";
    const runtime = phase.provenance?.runtime_revision ?? "unknown";
    const rosterName = phase.mode === "screen" ? `${settings.bots ?? phase.bots} cappers per wave`
      : Number.isInteger(settings.attackers) ? `${settings.attackers} cappers / ${settings.defenders} defenders`
      : phase.mode === "offdef" ? "4 offense / 3 defense" : settings.team_size ? `${settings.team_size}v${settings.team_size}` : "Unknown roster";
    const mode = trainingModes[phase.mode].label;
    const ruleName = phase.screening ? `${mode} · Contact only`
      : `${mode} · ${settings.seconds ?? "?"} s${settings.capture_limit ? ` · ${settings.capture_limit} caps` : ""}${phase.evaluation ? " · Evaluation" : phase.aim_calibration ? " · Aim calibration" : ""}`;
    const sideCount = (team) => phase.rows.filter((row) => {
      if (phase.screening) return row.team === team;
      if (phase.attack) {
        const attackTeam = row.attack_team ?? (phase.route_exploration && row.blue_policy !== "Flank cappers" ? 2 : 1);
        return attackTeam === team;
      }
      return row.bots?.some((bot) => bot.team === team) ?? false;
    }).length;
    return { ...phase, mapRevision, rosterName, runtime,
      rulesKey: `${ruleName}/${runtime}`, ruleName,
      blue: sideCount(1), red: sideCount(2) };
  });
  if (!runs.length) return null;
  const choices = (items, key, label) => [...new Map(items.map((item) => [item[key], label(item)]))];
  const onMap = runs.filter((run) => !map || run.map_id === map);
  const onRevision = onMap.filter((run) => !revision || run.mapRevision === revision);
  const onRoster = onRevision.filter((run) => !roster || run.rosterName === roster);
  const visible = onRoster.filter((run) => !rules || run.rulesKey === rules);
  const outcomes = (run, metric) => [1, 2].map((team) => {
    const tally = run.flag_outcomes?.[team]?.[metric];
    const side = team === 1 ? "Blue" : "Red";
    if (!tally) return <div key={team}>{side} <span title="Telemetry unavailable">—</span></div>;
    const { successes, opportunities, games } = tally;
    return <div key={team} title={`${games} ${games === 1 ? "game" : "games"} with usable telemetry`}>
      {side} {successes.toLocaleString()} / {opportunities.toLocaleString()}
      {opportunities > 0 && ` · ${percent(successes / opportunities)}`}
    </div>;
  });
  return <details className="training-panel training-coverage">
    <summary>Compare saved runs</summary>
    <div className="trial-scopes">
      <ScopeFilter label="Map" value={map} onChange={(value) => { setMap(value); setRevision(""); setRoster(""); setRules(""); }}
        allLabel="All maps" options={choices(runs, "map_id", (run) => maps[run.map_id] ?? run.map_id)} />
      <ScopeFilter label="Map revision" value={revision} onChange={(value) => { setRevision(value); setRoster(""); setRules(""); }}
        allLabel="All revisions" options={choices(onMap, "mapRevision", (run) => run.mapRevision === "unknown" ? "Unknown revision" : run.mapRevision.slice(0, 20))} />
      <ScopeFilter label="Roster" value={roster} onChange={(value) => { setRoster(value); setRules(""); }}
        allLabel="All rosters" options={choices(onRevision, "rosterName", (run) => run.rosterName)} />
      <ScopeFilter label="Rules" value={rules} onChange={setRules} allLabel="All rules"
        options={choices(onRoster, "rulesKey", (run) => `${run.ruleName} · ${run.runtime === "unknown" ? "unknown build" : run.runtime.slice(0, 12)}`)} />
    </div>
    <p>Screening samples count bot attempts. Drills count games from the attacking side. CTF counts games played by each side.</p>
    <p>Flag rates use observed opportunities, including saved bot totals for captures in older runs. Returns include automatic returns. Carrier downs count deaths while holding the enemy flag. A dash means the required telemetry was unavailable.</p>
    <div className="training-role-table" tabIndex="0">
      <table><thead><tr>{["Run", "Map", "Blue samples", "Red samples", "Captures / pickups", "Returns / drops",
        "Carrier downs / enemy pickups", "Mirrored evaluation"].map(
        (heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>{visible.map((run) => <tr key={run.id}>
          <th scope="row"><button type="button" className="training-role-bot" onClick={() => select(run.id)}>{run.label}</button>
            <div className="training-run-provenance">
              <span title={run.mapRevision === "unknown" ? undefined : run.mapRevision}>
                {run.mapRevision === "unknown" ? "Map revision unknown"
                  : `${run.mapRevision.startsWith("catalog:") ? "Catalog" : "Map"} ${run.mapRevision.split(":").at(-1).slice(0, 10)}`}
              </span>
              {" · "}
              <span title={run.runtime === "unknown" ? undefined : run.runtime}>
                {run.runtime === "unknown" ? "Rules build unknown" : `Rules ${run.runtime.slice(0, 10)}`}
              </span>
            </div></th>
          <td>{maps[run.map_id] ?? run.map_id}</td>
          <td>{run.blue}</td><td>{run.red}</td>
          <td>{outcomes(run, "captures")}</td><td>{outcomes(run, "returns")}</td><td>{outcomes(run, "carrier_downs")}</td>
          <td>{run.comparison?.pairs.length ? `${run.comparison.pairs.length} pairs · ${format(run.comparison.mean_margin)} mean capture margin` : "—"}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </details>;
}

function TrainingMapHeader({ mapId, mapLabel, context, error }) {
  const [terrain, setTerrain] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    const path = "/api/map/" + encodeURIComponent(mapId);
    fetch(path, { signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(data => {
        if (!controller.signal.aborted && data?.image_url === path + "/image") {
          setTerrain({ mapId, url: data.image_url });
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [mapId]);
  const variant = mapLabel.match(/^(.+?)\s+\(([^()]+)\)$/);
  return <header className="trial-heading training-map-header">
    {terrain?.mapId === mapId && <img className="training-map-image" src={terrain.url} alt="" decoding="async"
      onError={() => setTerrain(null)} />}
    <div className="training-map-title">
      <span className="training-map-context">{context}</span>
      <h2>{variant?.[1] ?? mapLabel}{variant && <> <small>{variant[2]}</small></>}</h2>
    </div>
    <p role="status" className={error ? "trial-error" : "trial-live"}
      title={error ? "Showing the last saved results" : "Updates every 5 seconds"}>
      {error ? "Showing last results" : "Live updates"}
    </p>
  </header>;
}

const dashboardIcons = { training: "sliders", results: "monitor", history: "textDocument" };

export function DashboardContent() {
  const { results, error, refresh } = useResults();
  const [selection, select] = useState(null);
  const [view, setView] = useState("overview");
  const [area, setArea] = useState(null);
  const [requestedMatch, setRequestedMatch] = useState("");
  const [followVersion, setFollowVersion] = useState(0);
  const navigation = useRef(null);
  if (!results) return <p role="status">{error ? "Results temporarily unavailable. Retrying…" : "Connecting to training results…"}</p>;
  const { phases, decision, training_maps: maps = {}, training_queue: queue = [] } = results;
  const running = phases.find((phase) => activeStatuses.includes(phase.status));
  const latest = phases.filter((item) => item.repeatable)
    .sort((a, b) => b.id.localeCompare(a.id))[0]
    ?? [...phases].sort((a, b) => (b.updated ?? "").localeCompare(a.updated ?? ""))[0];
  const phase = phases.find((candidate) => candidate.id === selection) ?? running ?? latest;
  if (!phase) return <p role="status">No training results yet.</p>;
  const activeArea = area === "training" && !results.can_start ? "results" : area ?? (results.can_start ? "training" : "results");
  const areas = results.can_start ? ["Training", "Results", "History"] : ["Results", "History"];
  const reviewKey = phase.id + "/" + followVersion + "/" + requestedMatch;
  const currentRun = running ?? (latest.repeatable ? latest : null);
  const featured = activeArea === "training" ? currentRun ?? latest : phase;
  const featuredMap = featured.map_id ?? "HighOctane2026";
  function keepRun() { select(phase.id); }
  function openRun(id, match = "") {
    select(id);
    setRequestedMatch(String(match));
    setArea("results");
    requestAnimationFrame(() => {
      navigation.current?.querySelector("#training-dashboard-results")?.focus({ preventScroll: true });
      navigation.current?.scrollIntoView({ block: "start" });
    });
  }
  return <article className="trial-dashboard" data-area={activeArea}>
    <TrainingMapHeader mapId={featuredMap} mapLabel={maps[featuredMap] ?? featured.map_id ?? "High Octane (2026)"}
      context={featured === running ? "Active map" : "Selected map"} error={error} />
    <nav className="training-dashboard-nav" aria-label="Training dashboard" ref={navigation}>
      {areas.map(label => {
        const key = label.toLowerCase();
        return <button className="training-button" type="button" key={key} id={"training-dashboard-" + key}
          aria-pressed={activeArea === key} onClick={() => setArea(key)}><Icon name={dashboardIcons[key]} />{label}
          {key === "history" && <span>{phases.length}</span>}
        </button>;
      })}
    </nav>
    {results.can_start && <div className="training-console" hidden={activeArea !== "training"}>
      {currentRun && <TrainingControls key={currentRun.id + "/" + currentRun.status}
        run={currentRun} onSelect={openRun} onResults={match => openRun(currentRun.id, match)} busy={results.training_busy} />}
      <StartTraining allowed={results.can_start} busy={results.training_busy} willQueue={results.training_busy || queue.length > 0}
        onSubmit={(run) => { if (run.status !== "Queued") { select(null); setRequestedMatch(""); } refresh(); }} maps={maps}
        seasonEvaluationMatches={results.season_evaluation_matches} />
      <TrainingQueue runs={queue} busy={results.training_busy} maps={maps} refresh={refresh} />
    </div>}
    <section className="training-dashboard-section" hidden={activeArea !== "history"} aria-label="Training history">
      <TrainingHistory phases={phases} phase={phase} onSelect={openRun} maps={maps} />
      <TrainingCoverage phases={phases} maps={maps} />
      <SeasonProgress phases={phases} seasonRuns={results.training_season_runs ?? []} maps={maps} />
      <CompareRuns phases={phases} maps={maps} select={openRun} />
    </section>
    {activeArea === "results" && <section className="training-dashboard-section" aria-label="Training results">
    <div className="training-results-title">
      <h3>{phase.label} results</h3>
      {selection && <button className="training-button" type="button"
        onClick={() => { select(null); setRequestedMatch(""); setFollowVersion(followVersion + 1); }}>Follow latest</button>}
    </div>
    {phase.id === "expansion" && decision && view !== "evaluation" && <p className="trial-decision">{decision.reset_mode === "verified"
      ? "Expansion uses verified resets · median " + format(decision.median_wall_seconds_saved, " s") + " saved"
      : "Expansion uses fresh matches. " + (decision.reasons ?? []).join(" ")}</p>}
    {phase.evaluation && <BenchmarkReport phase={phase} />}
    {phase.aim_calibration && <AimCalibrationReport phase={phase} />}
    {phase.flight ? <FlightAnalysis key={reviewKey} phase={phase} keepRun={keepRun} />
      : phase.team_matches ? <TeamAnalysis key={reviewKey} phase={phase} keepRun={keepRun} initialMatch={requestedMatch}
        mapLabel={maps[phase.map_id] ?? phase.map_id ?? phase.label} />
      : phase.screening ? <ScreeningAnalysis key={reviewKey} phase={phase} keepRun={keepRun} />
      : <CampaignAnalysis key={reviewKey} phase={phase} phases={phases} decision={decision} view={view} setView={setView} keepRun={keepRun} />}
    {results.can_start && !activeStatuses.includes(phase.status) && (phase.resumable || phase.repeatable) &&
      <TrainingControls key={phase.id + "/" + phase.status} run={phase} onSelect={openRun} busy={results.training_busy} />}
    </section>}
  </article>;
}

export default DashboardContent;
