"""Serve native training results and owner-only run controls on loopback."""
import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import TextIOWrapper
import json
import math
import os
from pathlib import Path
from queue import SimpleQueue
import re
import sys
from threading import Lock, Thread
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile


APP = Path(__file__).resolve().parent
ACTIVE = (
    ("pilot", "40-trial pilot", "Campaign-FlagPass40/progress.json", 40),
    ("validation", "Reset validation", "Campaign-FlagPass108/reset-validation/progress.json", 12),
    ("expansion", "108-trial expansion", "Campaign-FlagPass108/progress.json", 108),
    ("longrunups", "Long run-ups", "Campaign-FlagPassLong18/progress.json", 18),
    ("speed500", "Speed sweep", "Campaign-FlagPassSpeed500/progress.json", 500),
)
HISTORY = (
    ("capper100", "Capper training · 100", "Campaign-100-20261113/progress.json", 100),
    ("capper1000", "Paused capper batch · 1,000", "Campaign-1000/progress.json", 1000),
    ("defense25", "Early defense · 25", "Campaign-Defense25/progress.json", 25),
    ("roles25", "Role setup · 25", "Campaign-Defense25-Roles/progress.json", 25),
    ("grounded25", "Grounded defense · 25", "Campaign-Defense25-Grounded/progress.json", 25),
    ("grounded50", "Grounded defense · 50", "Campaign-Defense50/progress.json", 50),
    ("defender100", "Defender training · 100", "Campaign-Defender100/progress.json", 100),
    ("juggernaut", "Juggernaut body block · 61", "Campaign-Juggernaut61/progress.json", 61),
    ("matchups", "Capper vs. defense matchups · 144", "Campaign-Matchups144/progress.json", 144),
)
SCREENINGS = (
    ("fiveflag", "Five-bot flag screening", "Campaign-FiveFlag50/progress.json", 50, 10),
    ("pairedflag", "Solo and paired screening", "Campaign-PairedFlag/progress.json", 4, 3),
)
TRIAL_FIELDS = (
    "campaign_attempt", "spawn", "offset_cm", "defense_profile", "average_kmh", "peak_kmh",
    "grab_kmh", "grab_homeward_kmh", "pickup_seconds", "grab_energy", "closest_pass_cm",
    "closest_pass_kmh", "seconds", "verified_reuse", "wall_seconds", "outbound_average_kmh",
    "return_average_kmh", "evaluation_role", "reward", "defender_reward", "jet_frames", "ski_frames",
    "skiing_flythrough_grab", "pass_runup_cm", "entered_flythrough", "flythrough_gap_cm",
    "flythrough_speed_kmh", "flythrough_homeward_kmh", "flythrough_cross_cm", "flythrough_vertical_cm",
)
DEFENSE_FIELDS = ("died", "damage_taken", "hof_near_flag_seconds", "ld_near_carrier_seconds",
                  "red_caps", "hof_alive_seconds", "ld_alive_seconds")
POLICY_FIELDS = ("pulse", "period", "ski", "turn", "approach_cm", "flank")
TRACE_NAME = re.compile(r"trace-[1-9]\d{0,3}\.csv")
MAX_TRAINING_BOTS = 24
BOT_ORDINAL = r"(?:[1-9]|1[0-9]|2[0-4])"
SCREEN_TRACE_NAME = re.compile(rf"lane-{BOT_ORDINAL}-trace-[1-5]\.csv")
TEAM_TRACE_NAME = re.compile(rf"(?:wave-[2-5]-)?team-bot-{BOT_ORDINAL}-trace\.csv")
SESSION_NAME = re.compile(r"training-\d{8}-\d{6}-[a-f0-9]{8}")
MAP_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
STATIC_PATHS = {"/", "/index.html"}
PROJECTILE_WEAPON_LABELS = {
    "BP_Projectile_Topaz_HeavySpinfusor_C": "Heavy Spinfusor",
    "BP_Projectile_Topaz_LightChaingun_C": "Light Chaingun",
    "BP_Projectile_Topaz_LightSpinfusor_C": "Light Spinfusor",
    "BP_Projectile_Topaz_Spinfusor_C": "Spinfusor",
}


def read_json(path):
    try:
        with path.open("rb") as source:
            raw = source.read()
            updated = os.fstat(source.fileno()).st_mtime
    except FileNotFoundError:
        return None, None
    return json.loads(raw), datetime.fromtimestamp(updated, timezone.utc).isoformat()


def trial_summary(raw, validation):
    row = {field: raw[field] for field in TRIAL_FIELDS if field in raw}
    route = raw.get("approach_route")
    if route is None and raw.get("capper_route") is not None:
        route = f"Route {raw['capper_route']}"
    if route is None:
        route = {-2: "Left back approach", -1: "Left flank", 0: "Direct approach",
                 1: "Right flank", 2: "Right back approach"}.get(raw.get("policy", {}).get("flank"))
    row.update(approach_route=route, pickup=bool(raw["pickup"]), capture=bool(raw["capture"]),
               recovered=raw.get("recovered"), held_out=bool(raw.get("held_out")),
               has_trace=bool(raw.get("trace")))
    row.update({field: raw["policy"][field] for field in POLICY_FIELDS if field in raw.get("policy", {})})
    defense = raw.get("defense", {})
    row.update({field: defense[field] for field in DEFENSE_FIELDS if field in defense})
    if validation:
        row["validation_role"] = ("Fresh control", "Primer", "Reuse candidate")[(row["campaign_attempt"] - 1) % 3]
    if not row["pickup"]:
        for field in ("grab_kmh", "grab_homeward_kmh", "pickup_seconds", "grab_energy", "return_average_kmh"):
            row[field] = None
    return row


def resolve_trace(root, path, name_pattern):
    trace = Path(path).resolve()
    if (trace.parent.parent != (root / "Sessions").resolve()
            or not SESSION_NAME.fullmatch(trace.parent.name) or not name_pattern.fullmatch(trace.name)):
        raise FileNotFoundError()
    return trace


@contextmanager
def open_replay(root, path):
    if path.is_file():
        if path.stat().st_size > 1_000_000:
            raise ValueError("Unexpected replay size")
        with path.open(newline="", encoding="utf-8") as source:
            yield source
        return
    member = path.relative_to((root / "Sessions").resolve()).as_posix()
    try:
        with ZipFile(root / "TrainingHistory.zip") as archive:
            info = archive.getinfo(member)
            if info.file_size > 1_000_000:
                raise ValueError("Unexpected replay size")
            with TextIOWrapper(archive.open(info), encoding="utf-8", newline="") as source:
                yield source
    except KeyError as error:
        raise FileNotFoundError(member) from error
    except BadZipFile as error:
        raise ValueError("The replay archive is incomplete") from error


def screening_rows(data, expected_bots=None):
    for match, wave in enumerate(data["waves"], 1):
        if (wave["bots"] != len(wave["results"]) or not 1 <= wave["bots"] <= MAX_TRAINING_BOTS
                or (expected_bots is not None and wave["bots"] != expected_bots)):
            raise ValueError("Inconsistent screening checkpoint")
        for lane, row in enumerate(wave["results"], 1):
            if row["lane"] != lane:
                raise ValueError("Out-of-order screening result")
            yield match, wave["bots"], row


SCREEN_METRICS = ("average_kmh", "jet_frames", "ski_frames")


def read_screen_metrics(root, path, lane):
    trace = resolve_trace(root, path, SCREEN_TRACE_NAME)
    trial = trace.stem.rsplit('-', 1)[1]
    if trace.name != f"lane-{lane}-trace-{trial}.csv":
        raise ValueError("Screening trace does not match its lane")
    result = trace.with_name(f"lane-{lane}-result-{trial}.csv").resolve()
    if result.parent != trace.parent:
        raise FileNotFoundError()
    with open_replay(root, result) as source:
        values = next(csv.reader(source), [])
    if len(values) != 19 or values[:3] != [trial, "0", "0"]:
        raise ValueError("Unexpected screening metrics")
    average = float(values[12])
    if not math.isfinite(average):
        raise ValueError("Unexpected screening speed")
    return dict(average_kmh=average, jet_frames=int(values[7]), ski_frames=int(values[8]))


class LegacyScreenMetrics:
    """Read old per-lane CSVs once without blocking dashboard polling."""

    def __init__(self, root):
        self.root = root
        self.pending = SimpleQueue()
        self.metrics = {}
        self.lock = Lock()
        Thread(target=self.load, daemon=True, name="legacy-screen-metrics").start()

    def get(self, path, lane):
        key = path, lane
        with self.lock:
            if key not in self.metrics:
                self.metrics[key] = {}
                self.pending.put(key)
            return self.metrics[key]

    def load(self):
        while True:
            key = self.pending.get()
            try:
                values = read_screen_metrics(self.root, *key)
            except (OSError, ValueError, OverflowError, csv.Error):
                # An unavailable historical CSV must not hide the saved trial.
                continue
            with self.lock:
                self.metrics[key] = values


def screening_summary(match, bots, raw, number, legacy_metrics):
    row = {key: raw.get(key) for key in (
        "spawn", "offset_cm", "lane", "team", "seconds", "contact", "contact_kmh", "skiing", "peak_kmh",
        "approach_entry_kmh", "approach_peak_kmh",
        "pass_gap_m", "pass_speed_kmh", "homeward_kmh", "cross_track_m", "vertical_m",
    )}
    trace = raw.get("trace")
    metrics = {key: raw[key] for key in SCREEN_METRICS if key in raw}
    if len(metrics) != len(SCREEN_METRICS) and isinstance(trace, str) and legacy_metrics is not None:
        metrics = legacy_metrics.get(trace, raw["lane"]) | metrics
    return dict(row, campaign_attempt=number, match=match, bots=bots,
                approach_route=raw["route"], has_trace=bool(trace), **metrics)


def flag_outcomes(matches):
    """Aggregate only games with observable, consistent flag opportunities."""
    sides = {team: {} for team in (1, 2)}
    for match in matches:
        events = match.get("events")
        counts = Counter((row["team"], row["event"]) for row in events) if isinstance(events, list) else None
        roster = {team: [bot for bot in match["bots"] if bot["team"] == team] for team in sides}
        for team, bots in roster.items():
            if not bots:
                continue
            enemy = 3 - team
            metrics = []
            if counts is not None:
                pickups, captures = counts[team, "flag_pickup"], counts[team, "cap"]
                if match.get("flag_returns_observed"):
                    metrics.append(("returns", counts[team, "flag_returned"], counts[team, "flag_dropped"]))
                if roster[enemy]:
                    metrics.append(("carrier_downs", counts[enemy, "carrier_down"], counts[enemy, "flag_pickup"]))
            elif all(type(bot.get(field)) is int and bot[field] >= 0
                     for bot in bots for field in ("pickups", "captures")):
                pickups = sum(bot["pickups"] for bot in bots)
                captures = sum(bot["captures"] for bot in bots)
            else:
                continue
            if captures == match["blue" if team == 1 else "red"]:
                metrics.append(("captures", captures, pickups))
            for name, successes, opportunities in metrics:
                if successes <= opportunities:
                    totals = sides[team].setdefault(name, dict(successes=0, opportunities=0, games=0))
                    totals["successes"] += successes
                    totals["opportunities"] += opportunities
                    totals["games"] += 1
    return sides


def live_results(root, runs=(), legacy_metrics=None):
    phases = []
    for key, label, path, _ in ACTIVE + HISTORY:
        data, updated = read_json(root / path)
        if data is None:
            continue
        attempts = data["attempts"]
        if data["completed"] != len(attempts) or any(row["campaign_attempt"] != index
                                                    for index, row in enumerate(attempts, 1)):
            raise ValueError("Inconsistent training checkpoint")
        rows = [trial_summary(raw, key == "validation") for raw in attempts if flythrough_result(data, raw)]
        if rows:
            phases.append(dict(id=key, label=label, total=len(rows), updated=updated, rows=rows, historical=True))
    for key, label, path, target, matches in SCREENINGS:
        data, updated = read_json(root / path)
        if data is None:
            continue
        rows = [screening_summary(*item, number, legacy_metrics)
                for number, item in enumerate(screening_rows(data), 1)]
        if len(rows) > target or len(data["waves"]) > matches:
            raise ValueError("Unexpected screening count")
        phases.append(dict(id=key, label=label, total=target, updated=updated, rows=rows,
                           matches=len(data["waves"]), target_matches=matches, screening=True,
                           historical=key == "pairedflag"))
    for request in runs:
        key, mode, target = request["id"], request["mode"], request["matches"]
        data, updated = read_json(root / "DashboardRuns" / key / "progress.json")
        phase = dict(id=key, label=request["label"], mode=mode, total=target, updated=updated, rows=[],
                     map_id=request.get("map", "HighOctane2026"),
                     provenance=request.get("provenance"), evaluation=request.get("evaluation", False),
                     aim_calibration=request.get("aim_calibration", False),
                     season=request.get("season"), season_map=request.get("season_map"), season_maps=request.get("season_maps"),
                     settings={name: request[name] for name in ("seconds", "team_size", "bots", "attackers", "defenders") if name in request},
                     status=request["status"], stoppable=request.get("stoppable", False),
                     resumable=request.get("resumable", False),
                     repeatable=request.get("repeatable", False),
                     message=request.get("message"),
                     historical=request["status"] not in ("Running", "Pausing", "Stopping"),
                     carried_forward=(data or {}).get("carried_forward"))
        phase["settings"]["capture_limit"] = 5 if mode == "season" else request.get("capture_limit")
        if mode == "flight":
            from flight_training import SCENARIO
            phase["flight"] = True
            phase["strict_flight"] = (data or {}).get("scenario") == SCENARIO
            phase["flight_course"] = request.get("course", "straight")
            phase["course_m"] = (data or {}).get("course_m")
            phase["flight_comparison"] = (data or {}).get("comparison")
            if request["status"] == "Running":
                phase["message"] = (data or {}).get("waiting") or phase["message"]
            for number, wave in enumerate((data or {}).get("waves", []), 1):
                phase["rows"].append(dict(
                    campaign_attempt=number, testing=wave.get("testing"),
                    bots=[{key: value for key, value in bot.items() if key != "trace"} for bot in wave["bots"]]))
        elif mode == "screen":
            bots = request.get("bots", 5)
            phase.update(screening=True, total=bots*target, target_matches=target, matches=0, bots=bots)
            if data:
                phase["matches"] = len(data["waves"])
                phase["reused_waves"] = sum(bool(wave.get("verified_reuse")) for wave in data["waves"])
                phase["reset_fallbacks"] = len(data.get("reset_fallbacks", []))
                phase["wall_seconds"] = (sum(wave.get("wall_seconds", 0) for wave in data["waves"])
                                         + sum(row.get("wall_seconds", 0) for row in data.get("reset_fallbacks", [])))
                phase["rows"] = [screening_summary(*item, number, legacy_metrics)
                                 for number, item in enumerate(screening_rows(data, bots), 1)]
        elif uses_team_results(request, data):
            phase["team_matches"] = True
            phase['human_reference'] = (data or {}).get('human_reference')
            phase['flight_transfer'] = (data or {}).get('flight_transfer')
            phase['pursuit_profile'] = (data or {}).get('pursuit')
            phase['pursuit_profiles'] = (data or {}).get('pursuit_profiles')
            saved_matches = (data or {}).get("matches", [])
            phase["flag_outcomes"] = flag_outcomes(saved_matches)
            if phase['evaluation']:
                phase['comparison'] = (data or {}).get('comparison')
                phase['frozen_tactics'] = (data or {}).get('frozen_tactics')
                phase['field_benchmark'] = (data or {}).get('field_benchmark',False)
                phase['opponents'] = [item['label'] for item in (data or {}).get('opponents', ())]
                phase['aim_benchmark_profile'] = (data or {}).get('aim_benchmark_profile', 0)
                phase['benchmark_aim'] = (data or {}).get('benchmark_aim')
                phase['target_pairs'] = target // 2
            if phase['aim_calibration']:
                phase['aim_comparison'] = (data or {}).get('aim_comparison')
                phase['target_pairs'] = target // 2
                phase['aim_games'] = [
                    dict(game=number, pair=row['aim_pair'], level=row['aim_level'],
                         candidate_team=row['candidate_team'], **row['aim_observations'])
                    for number,row in enumerate(saved_matches,1) if 'aim_observations' in row
                ]
            for role in ("offense", "defense"):
                field = role + "_evidence"
                samples = [row[field] for row in saved_matches if field in row]
                if samples:
                    phase[role + "_evidence"] = dict(observed_matches=len(samples), eligible_matches=sum(bool(rows) for rows in samples))
            if any("session_wave" in row for row in saved_matches):
                phase["reused_waves"] = sum(bool(row.get("verified_reuse")) for row in saved_matches)
                phase["reset_fallbacks"] = len((data or {}).get("reset_fallbacks", []))
                phase["timed_matches"] = sum(row.get("wall_seconds", 0) > 0 for row in saved_matches)
                phase["wall_seconds"] = (sum(row.get("wall_seconds", 0) for row in saved_matches)
                    + sum(row.get("wall_seconds", 0) for row in (data or {}).get("reset_fallbacks", [])))
            if mode in ("solo", "defended", "explore"):
                phase.update(attack=True, attackers=request["attackers"], defenders=request["defenders"])
                if mode == "explore":
                    phase["route_exploration"] = True
            elif mode == "offdef":
                phase.update(attack=True, attackers=4, defenders=3)
            for number, row in enumerate((data or {}).get("matches", []), 1):
                bot_fields = ("bot", "team", "role", "peak_kmh", "samples", "flag_samples", "median_kmh",
                              "pickups", "fast_pickups", "median_pickup_kmh", "releases", "captures", "deaths",
                              "ski_seconds", "jet_seconds", "airborne_seconds", "airborne_objective_advance_m", "ground_jog_seconds",
                              "open_travel_seconds", "open_travel_jog_ratio",
                              "carry_seconds", "health_lost",
                              "home_flag_seconds", "enemy_flag_seconds")
                bots = [{field: bot[field] for field in bot_fields if field in bot} for bot in row["bots"]]
                guided = [{field: item[field] for field in ("bot", "team", "route", "outcome", "pickup_kmh", "homeward_kmh",
                           "pass_gap_m", "pass_speed_kmh", "escape_seconds", "failure") if field in item}
                          for item in row.get("guided_routes", [])]
                phase["rows"].append(dict({field: row[field] for field in (
                    "blue","red","seconds","policy","blue_policy","red_policy","margin")},
                    campaign_attempt=number, bots=bots, score_timeline=row.get("score_timeline", []), guided_routes=guided,
                    base_equipment=row.get("base_equipment", []), events=row.get("events"),
                    flag_returns_observed=row.get("flag_returns_observed", False),
                    drill_pair=row.get("drill_pair"), attack_team=row.get("attack_team"),
                    lineup_pair=row.get("lineup_pair"), candidate_team=row.get("candidate_team"),
                    combat_observed="combat" in row, offense_support=row.get("offense_evidence", []), duel=row.get('duel')))
        elif data:
            phase["rows"] = [trial_summary(row, False) for row in data["attempts"] if flythrough_result(data, row)]
            if not phase["rows"] and phase["historical"] and data["completed"]:
                continue
        phases.append(phase)
    return {"phases": phases, "decision": None}


def uses_team_results(request, checkpoint):
    if checkpoint is not None:
        return "matches" in checkpoint
    mode = request["mode"]
    return mode in ("teams", "offdef", "scrimmage", "explore", "season", "solo", "defended", "duel")


def combat_results(root, phase, number):
    checkpoint, _ = read_json(root / "DashboardRuns" / phase / "progress.json")
    matches = (checkpoint or {}).get("matches", [])
    if not 1 <= number <= len(matches) or "combat" not in matches[number-1]:
        raise FileNotFoundError()
    row = matches[number-1]
    events = []
    for event in row["combat"]:
        weapon = PROJECTILE_WEAPON_LABELS.get(event.get("projectile"))
        if weapon:
            events.append(dict(event, weapon=weapon, weapon_source="projectile_class"))
        else:
            events.append(event)
    return dict(complete=row.get("combat_complete", False), events=events, aim=row.get("aim", []))


def trace_results(root, phase, number, bot=None):
    screening_path = next((path for key, _, path, _, _ in SCREENINGS if key == phase), None)
    if re.fullmatch(r"run\d{14}[a-f0-9]{8}", phase):
        folder = root / "DashboardRuns" / phase
        request, _ = read_json(folder / "request.json")
        checkpoint, _ = read_json(folder / "progress.json")
        if not request or not checkpoint:
            raise FileNotFoundError()
        mode = request["mode"]
        if mode == "flight":
            waves = checkpoint.get("waves", ())
            if bot is None or not 1 <= number <= len(waves):
                raise FileNotFoundError()
            roster = waves[number-1]["bots"]
            if not 1 <= bot <= len(roster) or roster[bot-1]["bot"] != bot:
                raise FileNotFoundError()
            trace = resolve_trace(root, roster[bot-1]["trace"], TEAM_TRACE_NAME)
        elif mode == "screen":
            rows = list(screening_rows(checkpoint, request.get("bots", 5)))
            if bot is not None or not 1 <= number <= len(rows):
                raise FileNotFoundError()
            trace = resolve_trace(root, rows[number-1][2]["trace"], SCREEN_TRACE_NAME)
        elif uses_team_results(request, checkpoint):
            if bot is None or not 1 <= number <= len(checkpoint["matches"]):
                raise FileNotFoundError()
            roster = checkpoint["matches"][number-1]["bots"]
            if not 1 <= bot <= len(roster) or roster[bot-1]["bot"] != bot:
                raise FileNotFoundError()
            trace = resolve_trace(root, roster[bot-1]["trace"], TEAM_TRACE_NAME)
        else:
            rows = checkpoint["attempts"]
            if (bot is not None or not 1 <= number <= len(rows)
                    or not flythrough_result(checkpoint, rows[number-1])):
                raise FileNotFoundError()
            trace = resolve_trace(root, rows[number-1]["trace"], TRACE_NAME)
    elif screening_path:
        checkpoint, _ = read_json(root / screening_path)
        rows = list(screening_rows(checkpoint)) if checkpoint else []
        if not 1 <= number <= len(rows):
            raise FileNotFoundError()
        trace = resolve_trace(root, rows[number - 1][2]["trace"], SCREEN_TRACE_NAME)
    else:
        path = next((path for key, _, path, _ in ACTIVE + HISTORY if key == phase), None)
        if path is None:
            raise FileNotFoundError()
        checkpoint, _ = read_json(root / path)
        if not checkpoint or not 1 <= number <= len(checkpoint["attempts"]):
            raise FileNotFoundError()
        row = checkpoint["attempts"][number - 1]
        if row["campaign_attempt"] != number or not row.get("trace") or not flythrough_result(checkpoint, row):
            raise FileNotFoundError()
        trace = resolve_trace(root, row["trace"], TRACE_NAME)
    samples, events = [], []
    with open_replay(root, trace) as source:
        origin = None
        for item in csv.DictReader(source):
            x, y, z = (float(item[field]) / 100 for field in ("x_cm", "y_cm", "z_cm"))
            if origin is None:
                origin = (x, y, z)
            speed = 0.036 * math.hypot(float(item["vx_cm_s"]), float(item["vy_cm_s"]))
            sample = dict(t=float(item["seconds"]), x=x-origin[0], y=y-origin[1],
                          world_x=x, world_y=y, world_z=z, altitude=z-origin[2],
                          speed=speed, energy=float(item["energy"]), phase=item["phase"],
                          ski=item["ski"] == "1", jet=item["jet"] == "1", carrying=item["carrying"] == "1")
            labels = {"screen_contact": "Flag contact", "screen_overlap": "Flag contact",
                      "grab": "Flag pickup", "recovery_grab": "Flag pickup", "cap": "Capture",
                      "flag_pickup": "Flag pickup", "flag_lost": "Flag released",
                      "death": "Death", "death_last_seen": "Death · last known position"}
            label = labels.get(sample["phase"])
            if not label and samples and bot is not None and samples[-1]["carrying"] != sample["carrying"]:
                label = "Flag pickup" if sample["carrying"] else "Flag released"
            if label:
                exact = sample["phase"] == "screen_overlap"
                events.append(dict(t=sample["t"], x=x, y=y, z=z, label=label,
                                   speed=speed, source="Overlap event" if exact else "Observed position"))
            samples.append(sample)
    map_id = checkpoint.get("map", "HighOctane2026")
    roster = trace.parent / "commit.roster"
    if roster.is_file():
        lines = roster.read_text(encoding="utf-8").splitlines()
        if len(lines) >= 3 and lines[0] == "T3ROSTER1" and MAP_NAME.fullmatch(lines[2]):
            map_id = lines[2]
    return {"samples": samples, "events": events, "map_id": map_id}


def map_overview(root, map_id):
    if not MAP_NAME.fullmatch(map_id):
        raise FileNotFoundError()
    path = root / "MapOverviews" / (map_id + ".json")
    if path.stat().st_size > 1_000_000:
        raise ValueError("Unexpected map overview size")
    data = json.loads(path.read_bytes())
    if not isinstance(data, dict) or data.get("map_id") != map_id:
        raise ValueError("Map overview identity does not match")
    if data.get("image_url") not in (None, "/api/map/" + map_id + "/image"):
        raise ValueError("Unexpected map image location")
    bounds = data.get("bounds")
    if bounds is not None:
        if (not isinstance(bounds, dict) or any(not isinstance(bounds.get(key), (int, float)) or not math.isfinite(bounds[key])
                for key in ("min_x", "max_x", "min_y", "max_y"))
                or bounds["min_x"] >= bounds["max_x"] or bounds["min_y"] >= bounds["max_y"]):
            raise ValueError("Invalid map overview bounds")
    if data.get("image_url") and bounds is None:
        raise ValueError("Map image requires world bounds")
    landmarks = data.get("landmarks", [])
    if not isinstance(landmarks, list) or any(not isinstance(point, dict)
            or point.get("kind") not in ("flag", "spawn") or point.get("team") not in (1, 2)
            or any(not isinstance(point.get(axis), (int, float)) or not math.isfinite(point[axis]) for axis in ("x", "y", "z"))
            for point in landmarks):
        raise ValueError("Invalid map landmarks")
    return data


def handler_for(root, index=APP / "dist" / "index.html", jobs=None, owner=None, origin=None,
                *, local_control=False, tailnet_origin=None):
    local_host = urlsplit(origin).netloc if local_control else None
    tailnet_host = urlsplit(tailnet_origin).netloc if tailnet_origin else None
    legacy_metrics = LegacyScreenMetrics(root)

    class DashboardHandler(BaseHTTPRequestHandler):
        def owner_origin(self):
            if not jobs or self.client_address[0] != "127.0.0.1":
                return None
            forwarded_host = self.headers.get("X-Forwarded-Host")
            forwarded_proto = self.headers.get("X-Forwarded-Proto")
            if local_host and self.headers.get("Host") == local_host and not (forwarded_host or forwarded_proto):
                return origin
            if owner and self.headers.get("Tailscale-User-Login") == owner:
                if not local_control:
                    return origin
                if tailnet_host and forwarded_host == tailnet_host and forwarded_proto == "https":
                    return tailnet_origin
            return None

        def is_owner(self):
            return self.owner_origin() is not None

        def send_bytes(self, content, content_type, *, status=200, send_body=True):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if send_body:
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        def do_GET(self):
            self.respond(send_body=True)

        def do_HEAD(self):
            self.respond(send_body=False)

        def do_POST(self):
            action = re.fullmatch(r"/api/runs/(run[0-9]{14}[a-f0-9]{8})/(stop|pause|resume|repeat|start|cancel)", self.path)
            clear_queue = self.path == "/api/runs/clear-queue"
            if self.path != "/api/runs" and not action and not clear_queue:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("Invalid run request.")
                body = self.rfile.read(length)
                allowed_origin = self.owner_origin()
                if allowed_origin is None or self.headers.get("Origin") != allowed_origin:
                    message = ("Open the dashboard using its local launcher link." if local_control and not tailnet_origin
                               else "Open the dashboard with the owner’s Tailscale account.")
                    self.run_reply(403, {"error": message})
                    return
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Invalid run request.")
                data = json.loads(body)
                reply_status = None
                if clear_queue:
                    if data != {}:
                        raise ValueError("Invalid training action.")
                    self.run_reply(200, {"removed": jobs.clear_queue()})
                    return
                if action:
                    if data != {}:
                        raise ValueError("Invalid training action.")
                    run_id = action[1]
                    if action[2] == "resume":
                        jobs.resume(run_id)
                    elif action[2] == "repeat":
                        run_id = jobs.repeat(run_id)
                        reply_status = run_status(jobs.directory / run_id).get("status", "Running")
                    elif action[2] in ("start", "cancel"):
                        jobs.queue_action(run_id, action[2])
                    else:
                        jobs.stop(run_id, after_match=action[2] == "pause")
                else:
                    run_id = jobs.launch(data)
                    reply_status = run_status(jobs.directory / run_id).get("status", "Running")
            except BlockingIOError as exc:
                self.run_reply(409, {"error": str(exc)})
            except ValueError as exc:
                self.run_reply(400, {"error": str(exc)})
            except OSError:
                self.run_reply(503, {"error": "The local trainer could not accept the request."})
            else:
                self.run_reply(202, {"id": run_id, "status": reply_status})

        def run_reply(self, status, data):
            self.send_bytes(json.dumps(data).encode(), "application/json", status=status)

        def results(self):
            busy, runs = jobs.runs() if jobs else (False, [])
            queued = sorted((run for run in runs if run["status"] == "Queued"), key=lambda run: run["queued_at"])
            queue = [{key: run[key] for key in ("id", "label", "map", "mode", "matches", "seconds", "bots",
                     "season", "season_map", "season_maps", "evaluation") if key in run} for run in queued]
            history = [run for run in runs if run["status"] not in ("Queued", "Cancelled")]
            season_runs = [{key: run[key] for key in ("id", "status", "map", "matches", "season",
                           "season_map", "season_maps", "evaluation") if key in run} for run in runs if run.get("season")]
            return dict(live_results(root, history, legacy_metrics), can_start=self.is_owner(), training_busy=busy, training_queue=queue,
                        season_evaluation_matches=SEASON_EVALUATION_MATCHES, training_season_runs=season_runs,
                        training_maps=jobs.maps() if jobs else {})

        def send_json(self, callback, send_body):
            status = 200
            try:
                content = json.dumps(callback(), allow_nan=False).encode()
            except FileNotFoundError:
                status, content = 404, b'{"error":"No trace is available for this trial."}'
            except (ValueError, KeyError, OSError):
                status, content = 503, b'{"error":"Training data is temporarily unavailable."}'
            self.send_bytes(content, "application/json", status=status, send_body=send_body)

        def respond(self, *, send_body):
            path = urlsplit(self.path).path
            if path == "/api/results":
                self.send_json(self.results, send_body)
                return
            combat = re.fullmatch(r"/api/combat/(run[0-9]{14}[a-f0-9]{8})/([1-9][0-9]{0,5})", path)
            if combat:
                self.send_json(lambda: combat_results(root, combat[1], int(combat[2])), send_body)
                return
            overview = re.fullmatch(r"/api/map/([A-Za-z][A-Za-z0-9_]{0,39})(/image)?", path)
            if overview:
                if not overview[2]:
                    self.send_json(lambda: map_overview(root, overview[1]), send_body)
                else:
                    try:
                        data = map_overview(root, overview[1])
                        image_path = root / "MapOverviews" / (overview[1] + ".png")
                        if not data.get("image_url") or image_path.stat().st_size > 8_000_000:
                            raise FileNotFoundError()
                        content = image_path.read_bytes()
                    except (FileNotFoundError, ValueError, OSError):
                        self.send_bytes(b"Map overview unavailable", "text/plain", status=404, send_body=send_body)
                    else:
                        self.send_bytes(content, "image/png", send_body=send_body)
                return
            match = re.fullmatch(r"/api/trace/([a-z0-9]+)/([1-9]\d{0,5})(?:/([1-9]\d?))?", path)
            if match:
                self.send_json(lambda: trace_results(root, match[1], int(match[2]), int(match[3]) if match[3] else None), send_body)
                return
            if path in STATIC_PATHS:
                self.send_bytes(index.read_bytes(),
                                "text/html; charset=utf-8", send_body=send_body)
                return
            self.send_bytes(b"Not found", "text/plain", status=404, send_body=send_body)

        def log_message(self, format, *args):
            pass

    return DashboardHandler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18863)
    parser.add_argument("--index", type=Path, default=APP / "dist" / "index.html")
    parser.add_argument("--root", type=Path, default=APP.parent, help="Local training data directory.")
    parser.add_argument("--training-settings", type=Path, required=True)
    args = parser.parse_args()
    settings = json.loads(args.training_settings.read_bytes())
    runner = Path(settings["runner"]).resolve(strict=True)
    sys.path.insert(0, str(runner.parent))
    from learning_history import flythrough_result
    from dashboard_jobs import DashboardJobs, SEASON_EVALUATION_MATCHES, run_status
    jobs = DashboardJobs(args.root, runner)
    owner, origin = settings.get("owner"), settings["origin"]
    local_control = settings.get("local_control") is True
    if local_control and origin != f"http://127.0.0.1:{args.port}":
        parser.error("Local controls require the dashboard's exact loopback origin.")
    with ThreadingHTTPServer(("127.0.0.1", args.port),
                             handler_for(args.root, args.index, jobs, owner, origin, local_control=local_control,
                                         tailnet_origin=settings.get("tailnet_origin"))) as server:
        Thread(target=jobs.queue_loop, daemon=True).start()
        server.serve_forever()
