const test = require("node:test");
const assert = require("node:assert/strict");
const units = require("../faultcrafter/gui/assets/condition-units.js");

const rotation = {
  name: "shaft_speed_rpm", label: "shaft speed", unit: "rpm",
  unit_options: [
    { unit: "rpm", factor_to_si: 1 / 60 },
    { unit: "Hz", factor_to_si: 1 },
    { unit: "kHz", factor_to_si: 1000 },
  ],
};

test("unit selection keeps the same physical request and fractional kHz", () => {
  assert.equal(units.convert(rotation, 1800, "rpm", "Hz"), 30);
  assert.equal(units.convert(rotation, 1800, "rpm", "kHz"), 0.03);
  assert.equal(units.convert(rotation, 30, "Hz", "kHz"), 0.03);
  assert.equal(units.convert(rotation, 0.03, "kHz", "rpm"), 1800);
  assert.equal(units.canonical(rotation, 0.03, "kHz"), 30);
});

test("conversions reject incompatible units and invalid numbers", () => {
  for (const value of ["", null, true, NaN, Infinity]) assert.throws(() => units.numeric(value));
  assert.throws(() => units.convert(rotation, 10, "W", "Hz"));
  assert.throws(() => units.convert(rotation, 1e308, "kHz", "rpm"));
  assert.throws(() => units.convert(rotation, 1e308, "kHz", "kHz"));
  const drive = { ...rotation, unit_options: rotation.unit_options.filter((option) => option.unit !== "rpm") };
  assert.throws(() => units.convert(drive, 1800, "rpm", "Hz"));
});

test("unit conversion does not clamp an extrapolated request", () => {
  assert.equal(units.convert(rotation, 0.1, "kHz", "rpm"), 6000);
});

test("batch validity handles unit conversion overflow without throwing or clipping", () => {
  const control = { ...rotation, minimum: 0, maximum: 6000 };
  assert.equal(units.withinLimits(control, 0.03, "kHz"), true);
  assert.equal(units.withinLimits(control, 0.1, "kHz"), true);
  for (const value of ["", null, true, NaN, Infinity, 1e308, 0.2, -0.01]) {
    assert.equal(units.withinLimits(control, value, "kHz"), false);
  }
  assert.equal(units.withinLimits(control, 10, "W"), false);
});
