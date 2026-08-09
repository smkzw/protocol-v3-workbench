/**
 * Worker 02 isolated contract QC — conversational fact intake (no-IB path).
 *
 * Static-analysis verification that the medical writing authoring journey
 * setup implements the conversational fact intake contract:
 *   - IB is presented as optional (no warning styling for absent IB)
 *   - Conversational fact intake area exists with correct API endpoints
 *   - No duplicate "待医学确认/待医学批准" status labels (single confirmation)
 *   - No duplicate required fields beyond the three creation facts
 *   - CSS classes for new components are defined
 *
 * This test does NOT require a running backend or browser. It validates
 * the source-level contract that Worker 03's browser E2E test will
 * exercise against a live isolated runtime.
 *
 * Run: node tests/medical_writing_conversational_fact_intake_isolated_qc.mjs
 */
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { transformSync } from "esbuild";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const frontendRoot = path.resolve(__dirname, "..");

const findings = [];
let passCount = 0;
let failCount = 0;

function check(label, condition, detail = "") {
  if (condition) {
    passCount++;
  } else {
    failCount++;
    findings.push({ label, detail });
    console.error(`[FAIL] ${label}${detail ? ": " + detail : ""}`);
  }
}

async function main() {
  const jsxPath = path.join(frontendRoot, "src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx");
  const cssPath = path.join(frontendRoot, "src/styles.css");
  const appJsxPath = path.join(frontendRoot, "src/App.jsx");

  check("JSX file exists", existsSync(jsxPath));
  check("CSS file exists", existsSync(cssPath));
  check("App.jsx exists", existsSync(appJsxPath));

  const jsx = readFileSync(jsxPath, "utf8");
  const css = readFileSync(cssPath, "utf8");
  const appJsx = readFileSync(appJsxPath, "utf8");

  // 1. JSX syntax validity
  try {
    transformSync(jsx, { loader: "jsx", target: "es2020" });
    check("JSX syntax valid (esbuild transform)", true);
  } catch (error) {
    check("JSX syntax valid (esbuild transform)", false, error.message);
  }

  // 2. IB optionality — "可选：研究者手册" must appear
  check(
    "IB presented as optional (可选：研究者手册)",
    jsx.includes("可选：研究者手册"),
    "Expected IB optional label in framing identity group"
  );

  // 3. IB absent state — "暂未形成" or "稍后补充" must appear without warning tone
  check(
    "IB absent state shown as normal (暂未形成/稍后补充)",
    jsx.includes("暂未形成") || jsx.includes("稍后补充"),
    "Expected neutral IB-absent label"
  );

  // 4. IB status mapping reflects minimum_product_fact_packet.ib_status
  check(
    "IB status reads framing.minimum_product_fact_packet.ib_status",
    jsx.includes("factPacket.ib_status") && jsx.includes("minimum_product_fact_packet"),
    "Expected IB status binding to contract field"
  );

  // 5. Fact packet status label exists
  check(
    "Fact packet status labels defined",
    jsx.includes("FACT_PACKET_STATUS_LABELS") && jsx.includes("sufficient_for_research"),
    "Expected fact packet status mapping"
  );

  // 6. Conversational fact intake component exists
  check(
    "ConversationalFactIntake component defined",
    jsx.includes("function ConversationalFactIntake("),
    "Expected component definition"
  );

  // 7. Conversational fact intake rendered in framing identity group
  check(
    "ConversationalFactIntake rendered in FramingFields identity group",
    jsx.includes("<ConversationalFactIntake") && jsx.includes('group === "identity"'),
    "Expected component usage in identity group"
  );

  // 8. Fact intake turn API endpoint
  check(
    "Fact intake turn endpoint called",
    jsx.includes("/medical-writing/fact-intake/study_framing/turns"),
    "Expected POST .../fact-intake/study_framing/turns endpoint"
  );

  // 9. Fact intake apply API endpoint
  check(
    "Fact intake apply endpoint called",
    jsx.includes("/medical-writing/fact-intake/study_framing/apply"),
    "Expected POST .../fact-intake/study_framing/apply endpoint"
  );

  // 10. Confirm/edit/reject controls exist
  check(
    "Adopt control exists (adopted decision)",
    jsx.includes('"adopted"') && jsx.includes("onAdopt"),
    "Expected adopt button"
  );
  check(
    "Edit control exists (edited decision)",
    jsx.includes('"edited"') && jsx.includes("onEdit"),
    "Expected edit button"
  );
  check(
    "Reject control exists (rejected decision)",
    jsx.includes('"rejected"') && jsx.includes("onReject"),
    "Expected reject button"
  );

  // 11. Idempotency key for fact intake operations
  check(
    "Fact intake turn uses idempotency key",
    jsx.includes('stableAuthoringWriteKey') && jsx.includes('"fact-turn"'),
    "Expected idempotent write key for fact-turn"
  );
  check(
    "Fact intake apply uses idempotency key",
    jsx.includes('"fact-apply"'),
    "Expected idempotent write key for fact-apply"
  );

  // 12. Expected revision (optimistic concurrency) in fact intake calls
  check(
    "Fact intake turn sends expected_revision",
    jsx.includes("expected_revision") && jsx.includes("message_text"),
    "Expected optimistic revision check"
  );

  // 13. Per-round preservation (user_message + ai_response + decisions)
  check(
    "Turn preserves user_message",
    jsx.includes("user_message:"),
    "Expected user message preservation"
  );
  check(
    "Turn preserves ai_response",
    jsx.includes("ai_response:"),
    "Expected AI response preservation"
  );
  check(
    "Turn preserves decisions map",
    jsx.includes("decisions:"),
    "Expected decisions map preservation"
  );

  check(
    "Confirmed exact high-impact facts project into product evidence facts",
    jsx.includes("product_profile.confirmed_facts.")
      && jsx.includes("evidence_facts")
      && jsx.includes("user_confirmed: true"),
    "Expected adopted exact values to persist in the minimum product fact packet"
  );
  check(
    "Conversation high-impact gaps synchronize into minimum product fact packet",
    jsx.includes("conversationHasFactState")
      && jsx.includes("conversation.messages")
      && jsx.includes("factPacket.unresolved_high_impact_fields = allGaps")
      && jsx.includes("conversation.unresolved_high_impact_fields"),
    "Expected non-empty conversation state to synchronize without letting an empty conversation erase bootstrap gaps"
  );
  check(
    "Conversation preserves unresolved bootstrap packet gaps",
    jsx.includes("existingPacketGaps")
      && jsx.includes("unresolvedPacketGaps")
      && jsx.includes("product_profile.technology_type")
      && jsx.includes("product_profile.administration_routes"),
    "Expected a seeded conversation not to erase unresolved product-profile facts"
  );
  check(
    "Conversation readiness synchronizes research and candidate safety flags",
    jsx.includes("factPacket.safe_to_start_competitor_research")
      && jsx.includes("factPacket.safe_to_generate_protocol_candidates")
      && jsx.includes('conversationStatus === "sufficient_for_writing_candidates"'),
    "Expected adopted facts to update downstream readiness without a second save"
  );
  check(
    "Internal fact paths are rendered as medical-writing labels",
    jsx.includes("FACT_FIELD_LABELS")
      && jsx.includes("FACT_GAP_LABELS")
      && jsx.includes("factFieldLabel(proposal.field_path)")
      && jsx.includes("factGapLabel(gap)"),
    "Expected technical field paths to remain provenance metadata rather than primary user-facing text"
  );

  // 14. No "待医学确认" as a status label (single-confirmation semantics)
  // Fact candidates may wait for the current user's decision, but never for
  // a second medical-approval layer after adoption/edit.
  const medicalConfirmMatches = jsx.match(/待医学确认/g) || [];
  check(
    "No standalone 待医学确认 status label",
    medicalConfirmMatches.length === 0,
    `Found ${medicalConfirmMatches.length} occurrence(s) of 待医学确认`
  );

  // 15. The hint text explicitly states no second medical-approval layer
  check(
    "Hint states single-confirmation (no second 待医学批准)",
    jsx.includes("立即写入本项目确认事实") && jsx.includes("不再进入第二次批准"),
    "Expected explicit single-confirmation hint"
  );

  // 16. No duplicate required fields in new-project dialog (App.jsx)
  // The three creation facts are product_name, indication, study_phase.
  // Each field uses both `required` and `aria-required="true"`, so we count
  // distinct labeled inputs/selects, not raw attribute occurrences.
  const newProjectDialogSection = appJsx.slice(
    appJsx.indexOf("new-project-dialog"),
    appJsx.indexOf("</form>", appJsx.indexOf("new-project-dialog"))
  );
  const labeledRequiredFields = newProjectDialogSection.split("<label>").filter((segment) => {
    const fieldPart = segment.split("</label>")[0] || "";
    return fieldPart.includes("required");
  });
  check(
    "New-project dialog has exactly 3 required fields (product_name, indication, study_phase)",
    labeledRequiredFields.length === 3,
    `Found ${labeledRequiredFields.length} required labeled field(s) (expected 3)`
  );

  // 17. CSS classes for new components
  const requiredCssClasses = [
    ".authoring-ib-banner",
    ".authoring-ib-status",
    ".authoring-conversation",
    ".authoring-conversation-input",
    ".authoring-fact-proposal",
    ".authoring-fact-proposal-actions",
  ];
  for (const cls of requiredCssClasses) {
    check(`CSS class ${cls} defined`, css.includes(cls), `Missing CSS rule for ${cls}`);
  }

  // 18. IB optional tone does not use warning color
  const ibOptionalCss = css.match(/\.authoring-ib-status\.optional[^{]*\{[^}]*\}/g) || [];
  const hasWarningColor = ibOptionalCss.some(block => block.includes("warning") || block.includes("#ffc107") || block.includes("#856404"));
  check(
    "IB optional tone does not use warning color",
    ibOptionalCss.length > 0 && !hasWarningColor,
    ibOptionalCss.length === 0 ? "No .authoring-ib-status.optional CSS rule found" : "Warning color detected in optional IB styling"
  );

  // Summary
  console.log("");
  console.log(`Passed: ${passCount}`);
  console.log(`Failed: ${failCount}`);
  if (failCount > 0) {
    console.error("");
    console.error("FAILURES:");
    for (const f of findings) {
      console.error(`  - ${f.label}: ${f.detail}`);
    }
    process.exit(1);
  } else {
    console.log("ALL CHECKS PASSED");
    process.exit(0);
  }
}

main().catch((error) => {
  console.error("Test runner error:", error);
  process.exit(2);
});
