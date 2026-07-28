// @ts-ignore TS6133
import { expect, test } from "@jest/globals";

import * as z from "../index";

test("smoke existing email API", () => {
  expect(z.string().email().safeParse("a@b.com").success).toBe(true);
});

test("slug accepts hyphenated lowercase", () => {
  const schema = z.string().slug();
  expect(schema.parse("hello-world")).toBe("hello-world");
  expect(schema.parse("a")).toBe("a");
});

test("slug rejects invalid", () => {
  const schema = z.string().slug();
  expect(() => schema.parse("Hello")).toThrow();
  expect(() => schema.parse("-bad")).toThrow();
  expect(() => schema.parse("bad-")).toThrow();
  expect(() => schema.parse("has space")).toThrow();
});
