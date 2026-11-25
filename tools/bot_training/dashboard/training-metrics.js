export const queryId = "trial-results";

export function routeLabel(value) {
  return value == null ? "Unlabeled route" : value.replaceAll("_", " ").replace(/(\d)m\b/g, "$1 m");
}

export function format(value, unit = "", digits = 1) {
  return Number.isFinite(value) ? value.toFixed(digits) + unit : "—";
}

export function outcome(row) {
  return row.capture ? "Capture" : row.pickup ? "Grab only" : "Miss";
}

export function quantile(values, fraction) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const position = (sorted.length - 1) * fraction;
  const index = Math.floor(position);
  return sorted[index] + (sorted[Math.ceil(position)] - sorted[index]) * (position - index);
}

export function median(values) {
  return quantile(values, 0.5);
}

export function best(rows, key, higher = true) {
  return rows.reduce((winner, row) => {
    if (!Number.isFinite(row[key])) return winner;
    return !winner || (higher ? row[key] > winner[key] : row[key] < winner[key]) ? row : winner;
  }, null);
}

export function summarizeTrials(rows) {
  const grabs = rows.filter((row) => row.pickup);
  const captures = rows.filter((row) => row.capture);
  const firstPass = grabs.filter((row) => row.recovered === false);
  const homeward = firstPass.filter((row) => row.grab_homeward_kmh > 0);
  return {
    trials: rows.length,
    grabs: grabs.length,
    captures: captures.length,
    misses: rows.length - grabs.length,
    grabOnly: grabs.length - captures.length,
    captureRate: rows.length ? captures.length / rows.length : null,
    firstPass: firstPass.length,
    homeward: homeward.length,
    fastHomeward: homeward.filter((row) => row.grab_kmh >= 200).length,
    eliteHomeward: homeward.filter((row) => row.grab_kmh >= 330).length,
    medianSpeed: median(rows.map((row) => row.average_kmh)),
    medianGrabSpeed: median(grabs.map((row) => row.grab_kmh)),
    medianGrabTime: median(grabs.map((row) => row.pickup_seconds)),
    medianCaptureTime: median(captures.map((row) => row.seconds)),
    medianMissDistance: median(rows.filter((row) => !row.pickup)
      .map((row) => Number.isFinite(row.closest_pass_cm) ? row.closest_pass_cm / 100 : null)),
    medianDamage: median(rows.map((row) => row.damage_taken)),
    fastestGrab: best(grabs, "grab_kmh"),
    fastestCapture: best(captures, "seconds", false),
    fastestPeak: best(rows, "peak_kmh"),
  };
}

export function groups(rows, groupKey) {
  const result = new Map();
  for (const row of rows) {
    const key = groupKey(row);
    if (key == null) continue;
    if (!result.has(key)) result.set(key, []);
    result.get(key).push(row);
  }
  return [...result].map(([group, source]) => ({ group, source, ...summarizeTrials(source) }));
}

export function rolling(rows, size = 10) {
  return rows.map((row, index) => {
    const recent = rows.slice(Math.max(0, index + 1 - size), index + 1);
    return {
      campaign_attempt: row.campaign_attempt,
      "Median average": median(recent.map((trial) => trial.average_kmh)),
      "90th percentile peak": quantile(recent.map((trial) => trial.peak_kmh), .9),
      sampled_trials: recent.length,
    };
  });
}

export const percent = (value) => format(Number.isFinite(value) ? value * 100 : null, "%", 0);
