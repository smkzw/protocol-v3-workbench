// Read-only review harness: execute the actual legacy callbacks with fake I/O.
// This reproduces callback semantics, not React rendering or browser acceptance.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import {
  buildLocator, createScreenGeneration, isScreenGenerationCurrent, shouldBlockStart,
} from '../../frontend/src/features/medical-writing/durableJobState.mjs';

const source = readFileSync(new URL('../../frontend/src/App.jsx', import.meta.url), 'utf8');
const extract = (name, end) => {
  const start = source.indexOf(`  const ${name} = `);
  assert.ok(start > 0);
  const stop = source.indexOf(end, start);
  assert.ok(stop > start);
  return `${source.slice(start, stop)}\n${name}();`;
};
const flush = () => new Promise(resolve => setImmediate(resolve));

// Project A request completes after project selection has changed to B.
const writes = [];
let visibleProject = 'A';
let finishRequest;
const delayed = new Promise(resolve => { finishRequest = resolve; });
const adoptContext = {
  projectId: 'A', fullDraftJob: { job_id: 'job-A' }, fullDraftArtifact: {},
  fullDraftBusy: false, workingCopyDirty: false, editorFrozen: false,
  fetch: () => delayed, readJsonOrThrow: value => value,
  setFullDraftBusy: value => writes.push({ visibleProject, field: 'busy', value }),
  setFullDraftMessage: value => writes.push({ visibleProject, field: 'message', value }),
  setWorkingCopyReloadNonce: () => writes.push({ visibleProject, field: 'reload' }),
  refreshDocumentSession: async () => {}, refreshGreenfieldState: async () => {},
  refreshFreezeReadiness: async () => {}, refreshContentQuality: async () => {},
  apiErrorText: error => error.message,
};
vm.runInNewContext(extract('adoptFullDraft', '  useEffect(() => {'), adoptContext);
visibleProject = 'B';
finishRequest({ adopted_count: 2, replayed_count: 0 });
await flush();
const staleWrites = writes.filter(item => item.visibleProject === 'B');
assert.ok(staleWrites.some(item => item.field === 'message' && item.value.includes('2')));
console.log(JSON.stringify({ case: 'adopt_response_after_project_switch', staleWrites, realNetworkCalls: 0 }));

// Creation succeeds, but status retrieval has an unknown network outcome.
const stored = new Map();
const storageEvents = [];
const startContext = {
  projectId: 'A', fullDraftStorageKey: 'mw-full-draft:A',
  isDemoWritingSession: false, editorSessionAvailable: true, fullDraftBusy: false,
  workingCopyDirty: false, editorFrozen: false, workingCopyAuthoritative: true,
  fullDraftRunRef: { current: 0 }, setFullDraftBusy: () => {},
  setFullDraftArtifact: () => {}, setFullDraftMessage: () => {}, setFullDraftJob: () => {},
  fetch: async () => ({ job_id: 'job-A' }), readJsonOrThrow: value => value,
  monitorFullDraft: async () => { throw new Error('synthetic status network loss'); },
  apiErrorText: error => error.message,
  localStorage: {
    setItem: (key, value) => { stored.set(key, value); storageEvents.push('saved'); },
    removeItem: key => { stored.delete(key); storageEvents.push('removed'); },
  },
};
vm.runInNewContext(extract('startFullDraft', '  const adoptFullDraft = '), startContext);
await flush();
assert.deepEqual(storageEvents, ['saved', 'removed']);
assert.equal(stored.has('mw-full-draft:A'), false);
console.log(JSON.stringify({ case: 'status_network_loss_drops_resume_locator', storageEvents, locatorRetained: false, realNetworkCalls: 0 }));

// The shared hook has a related integration gap: startJob compares its token
// with captured A props, not the current generation ref that now points to B.
const hookSource = readFileSync(new URL('../../frontend/src/features/medical-writing/useDurableMwJob.js', import.meta.url), 'utf8');
const hookStart = hookSource.indexOf('  const startJob = useCallback(');
const hookEnd = hookSource.indexOf('  const cancelJob = useCallback(', hookStart);
assert.ok(hookStart > 0 && hookEnd > hookStart);
const hookWrites = [];
let hookVisibleProject = 'A';
let finishHookRequest;
const hookResponse = new Promise(resolve => { finishHookRequest = resolve; });
const screenGenRef = { current: createScreenGeneration('A') };
const hookContext = {
  useCallback: fn => fn, projectId: 'A', sectionId: '', jobType: 'synthetic',
  storageKey: 'job:A', jobState: null, actionInProgressRef: { current: false },
  screenGenRef, onTerminalRef: { current: null },
  shouldBlockStart, isScreenGenerationCurrent, buildLocator,
  fetch: () => hookResponse, readJson: response => response.body,
  setError: value => hookWrites.push({ visibleProject: hookVisibleProject, field: 'error', value }),
  setJobState: value => hookWrites.push({ visibleProject: hookVisibleProject, field: 'job', value }),
  localStorage: { setItem: () => {} }, apiErrorText: error => error.message,
};
const startPromise = vm.runInNewContext(
  `${hookSource.slice(hookStart, hookEnd)}\nstartJob('/synthetic', {});`, hookContext,
);
hookVisibleProject = 'B';
screenGenRef.current = createScreenGeneration('B');
finishHookRequest({ ok: true, status: 202, body: { job_id: 'job-A', status: 'queued' } });
await startPromise;
const staleHookWrites = hookWrites.filter(item => item.visibleProject === 'B');
assert.ok(staleHookWrites.some(item => item.field === 'job' && item.value.project_id === 'A'));
console.log(JSON.stringify({ case: 'shared_hook_start_uses_captured_identity', staleWrites: staleHookWrites, realNetworkCalls: 0 }));
