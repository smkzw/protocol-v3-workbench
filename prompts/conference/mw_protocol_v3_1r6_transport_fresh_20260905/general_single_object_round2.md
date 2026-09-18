This is optional continuation round 2 in the same session.

Same offline boundaries apply. Re-read zhipu_api.py and its test file. Codex
added three failing tests reproducing your findings, then fixed the resolver
exception boundary, moved schema validation before HTTP/sink, and added typed
artifact validation. Focused five-file244passed0.61s; independently verify.
Resolver exceptions now produce generic stable 'zhipu credential resolution failed'
without persisting arbitrary injected exception strings. This preserves the
existing resolver's own precise error code for direct resolver diagnostics.
No product model call yet. Actual SQLite schema was read-only verified by Codex;
availability true, no key output. Q2 remains explicitly pending until singleprobe.
Q1 clarification: installed peekApiKey/selectCredentialByType2095ff returns a
blocked fallback if all candidates blocked; getApiKey owns richer ranking/env
behavior. Thus product is not a full clone of selection. Design now explicitly
states same stored provider binding/normal order but deliberately no blocked
attempt/static substitution/rotation. This is a bounded configuration failure,
not claimed exact parity. Assess that clarified scope, no global source reads.
Assess the revision only; do not edit product files or run any network/service.

Do not restart the task or open a new session. Codex has requested this continuation because the previous output needs additional quality work. Challenge your previous answer against every requirement, source boundary, edge case, and likely user/reviewer objection. Identify concrete omissions or contradictions and propose corrections.

Return the complete updated Markdown output for your role. Keep evidence, inference,
recommendation, and uncertainty separate. Codex remains the final authority.
