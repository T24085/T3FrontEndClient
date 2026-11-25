export function clock(seconds) {
  const tenths = Math.round(seconds * 10);
  return Math.floor(tenths / 600) + ":" + ((tenths % 600) / 10).toFixed(1).padStart(4, "0");
}

export function isDiscontinuity(previous, next) {
  return previous.phase.startsWith("death") ||
    Math.hypot(next.world_x - previous.world_x, next.world_y - previous.world_y) >
      Math.max(20, (next.t - previous.t) * 110);
}

export function positionAt(samples, time) {
  let low = 0, high = samples.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (samples[middle].t <= time) low = middle + 1;
    else high = middle;
  }
  const index = low - 1;
  if (index < 0) return null;
  const previous = samples[index], next = samples[index + 1];
  if (!next || isDiscontinuity(previous, next)) return { ...previous, index };
  const fraction = (time - previous.t) / (next.t - previous.t);
  const point = { ...previous, index };
  for (const key of ["world_x", "world_y", "world_z", "speed", "energy"]) {
    point[key] = previous[key] + fraction * (next[key] - previous[key]);
  }
  return point;
}

export function routeBounds(routes, landmarks = []) {
  const points = routes.flatMap(route => route.samples.map(point => [point.world_x, point.world_y]));
  points.push(...landmarks.map(point => [point.x, point.y]));
  if (!points.length) return { min_x: -100, max_x: 100, min_y: -100, max_y: 100 };
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [x, y] of points) {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  const padding = Math.max(50, Math.max(maxX - minX, maxY - minY) * .08);
  return { min_x: minX - padding, max_x: maxX + padding, min_y: minY - padding, max_y: maxY + padding };
}
