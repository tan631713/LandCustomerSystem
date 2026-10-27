"use strict";
// Run with: node tests/js/field_visit_helpers.test.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs.readFileSync(
  path.join(__dirname, "..", "..", "customer_mobile_web", "field-visit.js"),
  "utf8"
);
const context = { window: {}, navigator: {}, URL, Date, Math, Number, String, Promise, Error };
vm.createContext(context);
vm.runInContext(source, context);
const F = context.window.LCSFieldVisit;

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("single navigation defaults to motorcycle mode", () => {
  const url = new URL(F.buildGoogleMapsNavigationUrl({ latitude: 25.03, longitude: 121.56 }));
  assert.strictEqual(url.searchParams.get("travelmode"), "two-wheeler");
  assert.strictEqual(url.searchParams.get("destination"), "25.03,121.56");
  const driving = new URL(F.buildGoogleMapsNavigationUrl({ address: "台北市信義路 1 號" }, null, { travelMode: "driving" }));
  assert.strictEqual(driving.searchParams.get("travelmode"), "driving");
  assert.strictEqual(driving.searchParams.get("destination"), "台北市信義路 1 號");
});

test("same owner, same address or same coordinate become one stop", () => {
  const stops = F.groupFieldVisitStops([
    { id: 1, owner_id: 7, address: "A路1號", latitude: null, longitude: null },
    { id: 2, owner_id: 7, address: "A路1號", latitude: 25.01, longitude: 121.5 },
    { id: 3, owner_id: 8, address: "A路 1號" },
    { id: 4, owner_id: 9, address: "B路2號", latitude: 25.02, longitude: 121.5 },
    { id: 5, owner_id: 10, address: "C路3號", latitude: 25.02, longitude: 121.5 },
    { id: 6, owner_id: 11, address: "D路4號", latitude: 25.03, longitude: 121.5 }
  ]);
  assert.strictEqual(JSON.stringify(stops.map(stop => stop.items.map(item => item.id))), JSON.stringify([[1, 2, 3], [4, 5], [6]]));
  assert.strictEqual(stops[0].latitude, 25.01);
  assert.strictEqual(JSON.stringify(stops.map(stop => stop.number)), JSON.stringify([1, 2, 3]));
  assert.strictEqual(F.stopForIndex(stops, 4).number, 2);
});

test("route segments respect waypoint limits and chain destinations", () => {
  const stops = Array.from({ length: 9 }, (_, index) => ({ latitude: 25 + index / 100, longitude: 121.5 }));
  const segments = F.buildGoogleMapsRouteSegments(stops, { maxWaypoints: 3 });
  assert.strictEqual(JSON.stringify(segments.map(segment => segment.stopCount)), JSON.stringify([4, 4, 1]));
  const first = new URL(segments[0].url);
  assert.strictEqual(first.searchParams.get("origin"), null);
  assert.strictEqual(first.searchParams.get("waypoints").split("|").length, 3);
  assert.strictEqual(first.searchParams.get("travelmode"), "two-wheeler");
  const second = new URL(segments[1].url);
  assert.strictEqual(second.searchParams.get("origin"), first.searchParams.get("destination"));
  const third = new URL(segments[2].url);
  assert.strictEqual(third.searchParams.get("waypoints"), null);
  const withOrigin = F.buildGoogleMapsRouteSegments(stops.slice(0, 2), { origin: { latitude: 24.9, longitude: 121.4 } });
  assert.strictEqual(new URL(withOrigin[0].url).searchParams.get("origin"), "24.9,121.4");
  assert.strictEqual(F.buildGoogleMapsRouteSegments([{}]).length, 0);
});

test("schedule uses 30 km/h, 1.4 detour and 20 minutes per landowner", () => {
  const depart = new Date("2026-09-24T09:00:00+08:00");
  const stops = F.groupFieldVisitStops([
    { id: 1, owner_id: 1, latitude: 25.0, longitude: 121.5 },
    { id: 2, owner_id: 1, latitude: 25.0, longitude: 121.5 },
    { id: 3, owner_id: 2, latitude: 25.1, longitude: 121.5 }
  ]);
  const plan = F.estimateStopSchedule(stops, { origin: { latitude: 25.0, longitude: 121.5 }, departAt: depart });
  assert.strictEqual(plan.items[0].arrivalAt.getTime(), depart.getTime());
  // Two landowners at the first stop -> 40 minutes there.
  assert.strictEqual(plan.items[0].departAt.getTime() - depart.getTime(), 40 * 60000);
  const legMinutes = (plan.items[1].arrivalAt.getTime() - plan.items[0].departAt.getTime()) / 60000;
  // 0.1 degree latitude ~ 11.12 km * 1.4 / 30 km/h ~ 31 minutes.
  assert.ok(legMinutes > 30 && legMinutes < 32, String(legMinutes));
  assert.strictEqual(plan.items[1].approximate, false);
  const missing = F.estimateStopSchedule([{ items: [{}], latitude: null, longitude: null }], { departAt: depart });
  assert.strictEqual(missing.items[0].approximate, true);
});

test("coordinate paste parser accepts common Google Maps formats", () => {
  const cases = [
    ["25.0330, 121.5654", [25.033, 121.5654]],
    ["25.0330,121.5654", [25.033, 121.5654]],
    ["(25.0330，121.5654)", [25.033, 121.5654]],
    ["121.5654, 25.0330", [25.033, 121.5654]],
    ["https://www.google.com/maps/place/x/@25.0330,121.5654,17z/data=!3d25.0331!4d121.5655", [25.0331, 121.5655]],
    ["https://www.google.com/maps/@25.04,121.51,15z", [25.04, 121.51]],
    ["https://maps.google.com/?q=25.05,121.52", [25.05, 121.52]],
    ["25°01'58.8\"N 121°33'55.4\"E", [25.0330, 121.5654]]
  ];
  for (const [input, [lat, lng]] of cases) {
    const result = F.parseCoordinateInput(input);
    assert.ok(Math.abs(result.latitude - lat) < 1e-4, `${input} -> ${result.latitude}`);
    assert.ok(Math.abs(result.longitude - lng) < 1e-4, `${input} -> ${result.longitude}`);
    assert.strictEqual(result.outsideTaiwan, false);
  }
  assert.strictEqual(F.parseCoordinateInput("35.68, 139.76").outsideTaiwan, true);
  for (const bad of ["", "台北市", "https://maps.app.goo.gl/abc", "95, 200"]) {
    assert.throws(() => F.parseCoordinateInput(bad), Error, bad);
  }
});

let failed = 0;
for (const [name, fn] of tests) {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (error) {
    failed += 1;
    console.log(`not ok - ${name}\n  ${error && error.stack || error}`);
  }
}
if (failed) process.exit(1);
