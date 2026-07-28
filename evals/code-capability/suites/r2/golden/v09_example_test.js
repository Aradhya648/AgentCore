import assert from 'node:assert/strict';
import test from 'node:test';
import { Command } from '../index.js';

test('smoke existing description API', () => {
  const cmd = new Command('demo');
  cmd.description('hello');
  assert.equal(cmd.description(), 'hello');
});

test('Command.example stores and returns examples', () => {
  const cmd = new Command('demo');
  assert.deepEqual(cmd.example(), []);
  cmd.example('demo --help');
  cmd.example('demo run');
  assert.deepEqual(cmd.example(), ['demo --help', 'demo run']);
});
