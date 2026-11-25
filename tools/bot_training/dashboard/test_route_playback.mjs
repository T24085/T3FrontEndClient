import assert from "node:assert/strict";
import test from "node:test";
import { isDiscontinuity, positionAt, routeBounds } from "./route-playback.mjs";

const point = (t, x, phase = "moving", carrying = false) => ({ t, world_x: x, world_y: 0,
  world_z: 10, speed: x, energy: 100 - x, phase, carrying });

test("playback interpolates movement and changes flag ownership at the recorded event", () => {
  const samples = [point(0, 0), point(1, 10, "flag_pickup", true)];
  const halfway = positionAt(samples, .5);
  assert.equal(halfway.world_x, 5);
  assert.equal(halfway.energy, 95);
  assert.equal(halfway.carrying, false);
  assert.equal(positionAt(samples, 1).carrying, true);
});

test("death and respawn never produce a fabricated line across the map", () => {
  const samples = [point(0, 0), point(1, 10, "death"), point(2, 500)];
  assert.equal(isDiscontinuity(samples[1], samples[2]), true);
  assert.equal(positionAt(samples, 1.5).world_x, 10);
  assert.equal(positionAt(samples, 2).world_x, 500);
  assert.equal(isDiscontinuity(point(0, 0), point(.25, 500)), true);
});

test("duplicate event times use the latest recorded state", () => {
  const samples = [point(0, 0), point(1, 10), point(1, 10, "flag_pickup", true), point(2, 20)];
  assert.equal(positionAt(samples, 1).index, 2);
  assert.equal(positionAt(samples, 1).carrying, true);
  assert.equal(positionAt(samples, -.1), null);
  assert.equal(positionAt([], 0), null);
  assert.equal(positionAt(samples, 50).world_x, 20);
});

test("overview bounds include every bot and both flag stands", () => {
  const bounds = routeBounds([{ samples: [point(0, 10), point(2, 20)] },
    { samples: [point(0, -200)] }], [{ x: 1000, y: -500 }]);
  assert.ok(bounds.min_x < -200 && bounds.max_x > 1000);
  assert.ok(bounds.min_y < -500 && bounds.max_y > 0);
  const stationary = routeBounds([{ samples: [point(0, 0)] }]);
  assert.ok(stationary.max_x > stationary.min_x && stationary.max_y > stationary.min_y);
});
