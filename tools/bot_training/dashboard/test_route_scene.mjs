import test from "node:test";
import assert from "node:assert/strict";
import { cameraProjector, surfaceHeight, terrainFaces, travelHeading } from "./route-scene.mjs";

const bounds = { min_x: -20, max_x: 20, min_y: -30, max_y: 30 };
const overview = { bounds, relief: { bounds, rows: 2, columns: 2, heights: [20, 28, 4, 12] } };

test("terrain uses north-first elevations and the rendered triangle interpolation", () => {
  assert.equal(surfaceHeight(overview, -20, 30), 20);
  assert.equal(surfaceHeight(overview, 20, -30), 12);
  assert.equal(surfaceHeight(overview, 0, 0), 16);
  assert.equal(surfaceHeight(overview, 0, 31), null);
  assert.deepEqual(terrainFaces(overview, bounds, 0).points[0], [-20, 30, 20]);
  assert.equal(terrainFaces(overview, bounds, 0).faces.length, 2);
  assert.equal(surfaceHeight({ bounds }, 0, 0), null);
});

test("camera follows measured elevation and does not choose a death jump as heading", () => {
  const samples = [
    { t: 0, world_x: 0, world_y: 0, world_z: 4, phase: "InProgress" },
    { t: 1, world_x: 20, world_y: 0, world_z: 11, phase: "death" },
    { t: 2, world_x: 500, world_y: 0, world_z: 0, phase: "InProgress" },
  ];
  assert.equal(travelHeading(samples, 0, samples[0]), 0);
  assert.equal(travelHeading(samples, 2, samples[2]), null);
  const project = cameraProjector(samples[0], 0, 90, 720, 440);
  assert.ok(project(0, 0, 15)[1] < project(0, 0, 4)[1]);
  assert.equal(project(-200, 0, 4), null);
});
