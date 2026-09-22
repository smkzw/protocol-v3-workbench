This is optional continuation round 2 in the same session. Do not restart or edit any file.

Codex reproduced and repaired your material findings in one batch:
- `ai_task_runner.py`: ineligible and disabled fallback profiles are skipped so a later eligible profile can run; `COMPETITIVE_INTELLIGENCE`, `PROTOCOL_DESIGN_SYNTHESIS`, and `PICOS_DESIGN_COACH` now share the comprehensive-AI fallback chain.
- `App.jsx`: selecting a fallback inherits its profile thinking/effort; each slot now exposes both thinking mode and effort; disabled profiles are hidden.
- `ai_runtime_settings.py`: the API maximum is aligned to the two fallback slots of the requested 2+1 chain.
- `medical_writing_full_draft.py`: route receipts now include route base URL plus expected and actual response-model identities; legacy inferred receipts are explicitly labelled.
- Regression tests now cover an ineligible first slot followed by a valid second slot, a disabled first slot, expanded comprehensive-AI task scope, and effective model-identity receipt fields.

Owner verification after repairs: 217 affected tests passed with 18 deprecation warnings; frontend production build passed (1971 modules, existing size warning only); `git diff --check` passed. The isolated 5304 API restarted successfully and reports MTPLX/Qwen/medium plus OpenCode/max then CMS/max.

Read the current versions of only the originally authorized source/test files. Verify whether P1-1, P1-2, P1-3, P2-1, P2-2 and P2-6 are closed and whether the repairs introduce a new material defect. You cannot rely on shell execution if denied; inspect files directly. Do not reopen P2-3/P2-4/P2-5 unless the current patch makes them worse; those are documented lower-priority provenance/versioning issues and the owner deliberately avoids a schema bump that would invalidate reusable Study A chunks. Return a concise updated verdict with file/line evidence and any remaining P0/P1/P2. Codex remains final authority.
