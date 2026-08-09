# AI Medical Manager Workbench Scaffold

This scaffold is the non-visual foundation for the AI full-process medical manager workbench.

Current scope:

- canonical multi-project catalog and project-scoped module route bindings for RUX, D001, MY009, MY008 PNH, MG-K10 CRSwNP, and the explicit MG-K10 SAR demo;
- shared contracts for project, evidence, data batches, risk cases, approval gates, protocol documents, and AI revision threads;
- deterministic realistic demo data, including medical-monitoring subject drilldowns for timeline, efficacy/safety trends, and timepoint risk prompts;
- minimal FastAPI service exposing dashboard, module read models, subject-level monitoring drilldown, the first real-data `证据调研与方案设计` manifest, the first real-data `数据分析与TFL` manifest, the first typed `安全信号与PV协同` manifest, and the first real-DOCX `医学写作` manifest;
- unit tests and browser QC scripts for the contract, backend services, and current frontend prototype.

Current verified foundation: real projects fail closed when a module is not configured and do not borrow another project's package or demo content. This is a routing/privacy foundation only; subsystem commercialization still requires two real studies, independent AI/OCR/VLM success paths, restart recovery, and full browser workflow evidence.

The current prototype is an implementation scaffold for local single-machine verification. It must remain deployable later to a private intranet or personal private network environment.

## UI Naming

User-facing workspace labels must use business names only.

Clinical medical subsystems:

- 证据调研与方案设计
- 入排审核
- 医学监查
- 数据分析与TFL
- 医学写作
- 安全信号与PV协同

Workbench-level surfaces:

- 项目总看板
- 审批中心

Non-medical lifecycle steps are intentionally out of scope. Do not build standalone subsystems for project startup/activation, EDC or data-collection-system construction, site operations, visit execution, or recruitment operations unless the user later changes the product boundary.

Do not show lifecycle numbers in navigation, page titles, breadcrumbs, buttons, approval lists, exports, or help text. Internal module keys may remain stable for traceability, but all visible labels must be business names.

## Frontend Experience Priority

All subsystem frontends are desktop-first production workspaces. Do not remove or simplify desktop functions, clinical context, dense tables, timelines, rich editors, review rails, or approval controls merely to improve mobile layout.

Desktop browser QC is blocking. Mobile browser checks are smoke/degradation checks only: the mobile surface should not catastrophically overlap or become completely inaccessible where feasible, but mobile limitations must not drive feature cuts unless explicitly approved by the user.

## Commands

```bash
python3 scripts/generate_demo_data.py
python3 -m unittest discover -s tests
python3 -m uvicorn services.api.app.main:app --reload --port 8910
```

## API

- `GET /api/health`
- `GET /api/projects`
- `GET /api/projects/{project_id}/dashboard`
- `GET /api/projects/{project_id}/risks`
- `GET /api/projects/{project_id}/subjects/{subject_id}/monitoring`
- `GET /api/projects/{project_id}/evidence-design/manifest`
- `GET /api/projects/{project_id}/tfl/manifest`
- `GET /api/projects/{project_id}/safety-pv/manifest`
- `GET /api/projects/{project_id}/medical-writing/manifest`
- `GET /api/projects/{project_id}/protocol`
- `GET /api/projects/{project_id}/revision-threads`
- `POST /api/projects/{project_id}/revision-threads`
- `POST /api/projects/{project_id}/revision-threads/{thread_id}/actions`
- `POST /api/projects/{project_id}/approvals/{approval_id}/actions`
- `GET /api/projects/{project_id}/data-batches`

`GET /api/projects/{project_id}/subjects/{subject_id}/monitoring` returns the internal monitoring module key with the user-facing label `医学监查`, plus:

- `subject`: subject/site/treatment/status context;
- `timeline`: visit, MH, CM, lab, efficacy score, AE, PD, and query events;
- `efficacy_trends`: metric series such as rTNSS and rTOSS;
- `safety_trends`: lab or symptom safety-follow-up series;
- `risk_prompts`: visit/timepoint-level prompts linked to source domains, risk cases, query IDs, PD IDs, and evidence spans.
