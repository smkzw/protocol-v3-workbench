# Frontend carry-forward findings — 6R integration input

No frontend product source edited, no service or network call, no visual acceptance.
Read frontend/AGENTS.md, package.json, vite.config.mjs, main.jsx and the complete
MedicalWritingSynopsisProjectIntake.jsx and its existing four helper tests.

Source SHA256 (intake component):
1b5789fa5364b63347d04838334fe1b4039b7819c5705c2a2f90aefd15aa2968

## Reproduced lifecycle defect

The effect only sets mountedRef=false in cleanup and never restores true in setup.
main.jsx enables React.StrictMode. In an isolated jsdom test with deterministic
mocked upload/result responses, the ordinary mount reaches review; StrictMode
remains at 准备导入 with the spinner. Successful upload response is ignored because
mountedRef is false. This proves the development-effect replay case, not a claim
that production builds replay effects or that a live backend failed.

Evidence: runs/mw_protocol_v3_frontend_readonly_review_20260906/intake_mount.test.jsx
and strict_mount_attempt3.xml: 1 passed / 1 failed, 1.56s. All fetches mocked.
Fix when integrating the intake UI: initialize the live flag in effect setup,
keep abort cleanup and generation checks, preserve this StrictMode counterexample.

## Verified old requirements conflicting with current Goal

- canConfirm requires overrideReason length >=10 and textarea repeats that rule.
  Replace with AI-prepared editable rationale and meaningful confirmation, without
  arbitrary character counts. Coordinate backend validation rather than CSS-only fix.
- Footer promises no further medical approval after a single import confirmation.
  Distinguish accepting extracted facts from the applicable high-risk decision cards.
- Raw backend error_message/detail and internal missing-field suffixes reach UI.
  Map these to impact, retained work and the next business action in the v3 surface.

These are legacy intake findings; the new v3 UI is not yet implemented/accepted.

## Probe harness limitations preserved

First launch failed before collection because the installed React plugin imported
vite/internal unavailable from the resolved Vite package. No dependency changes.
Second launch collected zero tests due to the outside-frontend JSX runtime resolver;
its XML remains in the nested runs subdirectory. The third used a local isolated
config with esbuild automatic JSX and an explicit React alias, proving the component
case above. It does not prove the full frontend toolchain builds cleanly.
