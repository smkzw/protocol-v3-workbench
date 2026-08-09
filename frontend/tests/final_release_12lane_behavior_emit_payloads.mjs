/**
 * Emit canonical JS payload fixtures to stdout as JSON.
 * Used by Python Pydantic validation to test exact JS-emitted objects.
 *
 * Run: node frontend/tests/final_release_12lane_behavior_emit_payloads.mjs > /tmp/e3_payloads.json
 */
import { emitPayloadFixtures } from "./final_release_12lane_behavior_helpers.mjs";

const fixtures = emitPayloadFixtures("e3-test-key-0001");
console.log(JSON.stringify(fixtures, null, 2));
