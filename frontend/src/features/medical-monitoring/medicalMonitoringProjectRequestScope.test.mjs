import assert from "node:assert/strict";

import {
  createMedicalMonitoringProjectRequestScope,
} from "./medicalMonitoringProjectRequestScope.mjs";

const scope = createMedicalMonitoringProjectRequestScope("project-a");
const first = scope.begin("status");
assert.equal(scope.isCurrent(first), true);
assert.equal(first.projectId, "project-a");

const replacement = scope.begin("status");
assert.equal(first.signal.aborted, true, "a newer request cancels the old slot");
assert.equal(scope.isCurrent(first), false);
assert.equal(scope.isCurrent(replacement), true);

const parallel = scope.begin("versions");
assert.equal(scope.isCurrent(replacement), true);
assert.equal(scope.isCurrent(parallel), true, "independent request slots coexist");

scope.finish(replacement);
assert.equal(scope.isCurrent(replacement), false);
assert.equal(scope.isCurrent(parallel), true);

scope.cancel("versions");
assert.equal(parallel.signal.aborted, true);
assert.equal(scope.isCurrent(parallel), false);

const pending = scope.begin("batch-view");
scope.dispose();
assert.equal(pending.signal.aborted, true, "project unmount aborts every request");
assert.equal(scope.isCurrent(pending), false);

const afterDispose = scope.begin("late-callback");
assert.equal(
  afterDispose.signal.aborted,
  true,
  "callbacks from an old project cannot start a live request",
);
assert.equal(scope.isCurrent(afterDispose), false);

scope.activate();
const strictModeReplay = scope.begin("strict-mode-replay");
assert.equal(
  scope.isCurrent(strictModeReplay),
  true,
  "effect setup can reactivate the same scope after a development replay",
);
scope.finish(strictModeReplay);

assert.throws(
  () => createMedicalMonitoringProjectRequestScope(""),
  /projectId is required/,
);

console.log("medicalMonitoringProjectRequestScope: 14 passed");
