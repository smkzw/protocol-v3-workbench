# Study A full-draft v0.4 contract stage record

Date: 2026-09-22

## Why this batch exists

Study A v0.3 filled 85 blank sections but independent review found unsupported blinding/unblinding and contraception rules plus generic prose hiding missing sources. The v0.4 contract changes the model's answer from “every section must contain prose” to three explicit states: complete, a scientific decision is required, or a source is missing.

## Implemented behavior

- A complete section must contain substantive source-bound prose.
- A decision-required section carries a concise question, one recommended choice, 1–2 alternatives, a rationale and the blocked section ID. It cannot be adopted as final prose.
- A source-gap section contains no filler body and names 1–4 concrete missing source classes.
- Gateway and runner validation reject malformed choices, unknown evidence, empty decision text and complete high-impact rules whose rationale admits that the rule is unsupported.
- Artifact coverage exposes exact decision/source-gap counts and chapter IDs. Either state blocks adoption before any chapter write.
- v0.3 artifacts remain immutable and readable. They are now read-only because the preserved Study A v0.3 artifact is known to contain unsupported rules.
- The wide review workspace shows blocked chapters, recommended and alternative choices, and missing-source bullet lists. It directs the user to the existing study-design flow and disables adoption until the blockers are resolved.

## Execution and verification

The bounded CodeBuddy route `deepseek-v4.1-flash:max` completed without fallback but its native plan mode prevented source edits. Codex integrated the batch and independently reviewed it. Final focused backend regression: 105 passed. Earlier in the same coherent batch the broader affected backend suite passed 163 tests, the authoritative frontend inventory passed 110 Vitest plus 65 Node tests, and the production build completed 1971 modules. `git diff --check` passed.

The worker's read-only expansion beyond the declared initial read list and its external harness plan are recorded in the Codex review; neither changed repository source or runtime data.

The Hermes review gate passed after final review completion. `audit-execution` was also run, but this older `init-task` packet has no `init-execution` immutable worker manifest, so that generic audit correctly returned a packet-shape failure. This is retained as process evidence rather than relabeled as an implementation failure or an audit pass.

## Remaining product work

No v0.4 model artifact has yet been generated. The next batch must connect each decision choice to the existing StudyDefinition confirmation path so the recommended item is preselected, save the user's explicit choice once, regenerate only affected chapters, then run the real model and a fresh medical conference review. Study A v0.3 remains unadopted.
