import assert from 'node:assert/strict';
import test from 'node:test';
import { Command } from '../index.js';

test('smoke existing summary API', () => {
  const cmd = new Command('demo');
  cmd.summary('short');
  assert.equal(cmd.summary(), 'short');
});

test('Command.note stores and returns notes', () => {
  const cmd = new Command('demo');
  assert.deepEqual(cmd.note(), []);
  cmd.note('requires network');
  cmd.note('idempotent');
  assert.deepEqual(cmd.note(), ['requires network', 'idempotent']);
});
