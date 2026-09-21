# Execution Metrics: mw_r11_decision_apply_20260922

| Role | Provider | Model | Status | Duration | Tools | Result |
|---|---|---|---|---:|---:|---|
| `worker_01` primary | `codebuddy-cli` | `deepseek-v4.1-flash:max` | no usable resumable result | recorded in runner receipt | — | manifest fallback used |
| `worker_01` fallback | `zcode` | `GLM-5.3-Flash:max` | terminal success | 1059.851 s | 34 calls | report persisted; owner revised then accepted |

Guard audit: `ok=true`, no warnings or errors. Owner verification: backend 111 passed; frontend unit inventory 110+65 passed before final hardening; final production build passed with 1971 modules; diff check passed.
