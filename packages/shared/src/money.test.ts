import { strict as assert } from "node:assert";
import { test } from "node:test";

import { formatRub, kopecksToInput, pluralMonths, rublesToKopecks } from "./money.ts";

test("formatRub groups thousands and hides zero kopecks", () => {
  assert.equal(formatRub(160000000), "1 600 000 ₽");
  assert.equal(formatRub(5000050), "50 000,50 ₽");
  assert.equal(formatRub(null), "—");
});

test("rublesToKopecks parses Russian input without float errors", () => {
  assert.equal(rublesToKopecks("1 600 000"), 160000000);
  assert.equal(rublesToKopecks("0,1"), 10);
  assert.equal(rublesToKopecks("333333,33"), 33333333);
  assert.equal(rublesToKopecks(""), null);
  assert.ok(Number.isNaN(rublesToKopecks("12,345")));
  assert.ok(Number.isNaN(rublesToKopecks("abc")));
});

test("kopecksToInput round-trips", () => {
  assert.equal(kopecksToInput(160000050), "1600000,50");
  assert.equal(rublesToKopecks(kopecksToInput(160000050)), 160000050);
});

test("pluralMonths", () => {
  assert.equal(pluralMonths(1), "1 месяц");
  assert.equal(pluralMonths(3), "3 месяца");
  assert.equal(pluralMonths(12), "12 месяцев");
  assert.equal(pluralMonths(21), "21 месяц");
  assert.equal(pluralMonths(24), "24 месяца");
});
