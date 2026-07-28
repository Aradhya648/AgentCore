// @ts-ignore TS6133
import { expect, test } from "@jest/globals";

import * as z from "../index";

test("smoke existing uuid API", () => {
  expect(
    z.string().uuid().safeParse("123e4567-e89b-12d3-a456-426614174000").success
  ).toBe(true);
});

test("hexColor accepts #RGB and #RRGGBB", () => {
  const schema = z.string().hexColor();
  expect(schema.parse("#fff")).toBe("#fff");
  expect(schema.parse("#FF00aa")).toBe("#FF00aa");
});

test("hexColor rejects invalid", () => {
  const schema = z.string().hexColor();
  expect(() => schema.parse("fff")).toThrow();
  expect(() => schema.parse("#ffff")).toThrow();
  expect(() => schema.parse("#gg0000")).toThrow();
});
