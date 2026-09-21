import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
const source = readFileSync(new URL('../../../../../public/genoffice/bridge-shim.js', import.meta.url), 'utf8');
function bridge(responses = [], baseline = 'b'.repeat(64)) {
  const bodies = [], messages = [];
  const window = { location: { search: new URLSearchParams({ saveUrl: '/save', rev: '2', sha: 'a'.repeat(64), openedStudySha: baseline }).toString(), origin: 'http://localhost' }, parent: { postMessage: (...args) => messages.push(args) } };
  vm.runInNewContext(source, { window, URLSearchParams, crypto: webcrypto, Uint8Array, btoa,
    fetch: async (_url, options) => { bodies.push(JSON.parse(options.body)); const response = responses.shift(); if (!response) throw new Error('lost receipt'); return response; } });
  return { desktop: window.desktop, bodies, messages };
}
const ok = (revision) => ({ ok: true, json: async () => ({ operation_id: `save-${revision}`, artifact_revision: revision }) });
test('document identity and opened study identity remain distinct; parent sees save receipt', async () => {
  const b = bridge([ok(1), ok(2)]);
  await b.desktop.saveDocx('draft', new Uint8Array([1]).buffer);
  await b.desktop.saveDocx('draft', new Uint8Array([2]).buffer);
  assert.equal(b.bodies[0].expected_document_sha256, 'a'.repeat(64));
  assert.equal(b.bodies[0].opened_study_revision_sha256, 'b'.repeat(64));
  assert.equal(b.bodies[1].base_artifact_revision, 1);
  assert.equal(b.messages[1][0].receipt.artifact_revision, 2);
  assert.equal(b.messages[0][1], 'http://localhost');
});
test('missing study baseline remains null', async () => {
  const b = bridge([ok(1)], ''); await b.desktop.saveDocx('draft', new ArrayBuffer(1));
  assert.equal(b.bodies[0].opened_study_revision_sha256, null);
});
test('conflict does not silently adopt another window revision', async () => {
  const conflict = { ok: false, status: 409, json: async () => ({ detail: { code: 'manuscript_office_base_conflict', latest_snapshot: { artifact_revision: 9 } } }) };
  const b = bridge([conflict, conflict]);
  await b.desktop.saveDocx('draft', new ArrayBuffer(1));
  await b.desktop.saveDocx('draft', new ArrayBuffer(1));
  assert.equal(b.bodies[1].base_artifact_revision, 0);
  assert.equal(b.messages[0][0].type, 'protocol-office:save-failed');
});
test('a lost receipt is recovered with original bytes before later typing is saved', async () => {
  const b = bridge([null, ok(1), ok(2)]);
  const first = await b.desktop.saveDocx('draft', new Uint8Array([1]).buffer);
  assert.equal(first.ok, false);
  const next = await b.desktop.saveDocx('draft', new Uint8Array([2]).buffer);
  assert.equal(next.ok, true);
  assert.equal(b.bodies[0].operation_id, b.bodies[1].operation_id);
  assert.equal(b.bodies[0].content_base64, b.bodies[1].content_base64);
  assert.notEqual(b.bodies[1].operation_id, b.bodies[2].operation_id);
  assert.equal(b.bodies[2].content_base64, 'Ag==');
});
