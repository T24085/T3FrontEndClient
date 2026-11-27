import { isDiscontinuity, positionAt } from "./route-playback.mjs";

export const TEXTURE_SIZE = 256;

export function surfaceHeight(overview, x, y) {
  const grid = overview?.relief, bounds = grid?.bounds;
  if (!grid || !bounds || x < bounds.min_x || x > bounds.max_x || y < bounds.min_y || y > bounds.max_y) return null;
  const u = (x - bounds.min_x) / (bounds.max_x - bounds.min_x) * (grid.columns - 1);
  const v = (bounds.max_y - y) / (bounds.max_y - bounds.min_y) * (grid.rows - 1);
  const c = Math.min(Math.floor(u), grid.columns - 2), r = Math.min(Math.floor(v), grid.rows - 2);
  const [nw, ne, sw, se] = [0, 1, grid.columns, grid.columns + 1].map(offset => grid.heights[r * grid.columns + c + offset]);
  if (![nw, ne, sw, se].every(Number.isFinite)) return null;
  const east = u - c, south = v - r;
  return east + south <= 1 ? nw + (ne - nw) * east + (sw - nw) * south
    : se + (sw - se) * (1 - east) + (ne - se) * (1 - south);
}

export function travelHeading(samples, time, head) {
  const ahead = positionAt(samples, time + .8);
  const behind = positionAt(samples, time - .8);
  for (const [a, b] of [[head, ahead], [behind, head]]) {
    if (!a || !b || isDiscontinuity(a, b)) continue;
    const dx = b.world_x - a.world_x, dy = b.world_y - a.world_y;
    if (Math.hypot(dx, dy) > .5) return Math.atan2(dy, dx);
  }
  return null;
}

export function cameraProjector(focus, yaw, distance, width, height) {
  const dx = Math.cos(yaw), dy = Math.sin(yaw);
  const pitch = .52;
  const cos = Math.cos(pitch), sin = Math.sin(pitch);
  const focal = Math.min(width, height) * 1.05;
  return (x, y, z) => {
    const east = x - focus.world_x, north = y - focus.world_y;
    const up = z - focus.world_z, forward = east * dx + north * dy;
    const depth = distance + forward * cos - up * sin;
    if (depth < 6) return null;
    return [width * .5 + (east * dy - north * dx) * focal / depth,
      height * .61 - (forward * sin + up * cos) * focal / depth, depth];
  };
}

export function terrainFaces(overview, bounds, planeZ, texture) {
  const grid = overview?.relief;
  const extent = grid?.bounds ?? bounds;
  const rows = grid?.rows ?? 15, cols = grid?.columns ?? 15;
  const points = Array.from({ length: rows * cols }, (_, i) => {
    const u = (i % cols) / (cols - 1), v = Math.floor(i / cols) / (rows - 1);
    return [extent.min_x + (extent.max_x - extent.min_x) * u,
      extent.max_y - (extent.max_y - extent.min_y) * v, grid ? grid.heights[i] : planeZ];
  });
  const faces = [];
  for (let y = 0; y < rows - 1; y++) {
    for (let x = 0; x < cols - 1; x++) {
      const i = y * cols + x;
      const worldU = ((points[i][0] + points[i + 1][0]) / 2 - bounds.min_x) / (bounds.max_x - bounds.min_x);
      const worldV = (bounds.max_y - (points[i][1] + points[i + cols][1]) / 2) / (bounds.max_y - bounds.min_y);
      const pixel = 4 * (Math.floor(TEXTURE_SIZE * worldV) * TEXTURE_SIZE + Math.floor(TEXTURE_SIZE * worldU));
      if (texture && !texture[pixel + 3]) continue;
      for (const vertices of [[i, i + 1, i + cols], [i + 1, i + cols + 1, i + cols]]) {
        const [a, b, c] = vertices.map(index => points[index]);
        if (![a[2], b[2], c[2]].every(Number.isFinite)) continue;
        const slope = (b[2] - a[2] + c[2] - a[2]) / Math.max(1, Math.hypot(b[0] - a[0], b[1] - a[1]));
        const light = grid ? Math.max(22, Math.min(50, 35 + slope * 24)) : 21;
        const shade = grid ? .77 + (light - 22) / 110 : .91;
        const color = texture ? `rgb(${[0, 1, 2].map(channel => Math.round(texture[pixel + channel] * shade)).join(",")})`
          : `hsl(167 19% ${light}%)`;
        faces.push({ vertices, color });
      }
    }
  }
  return { points, faces };
}
