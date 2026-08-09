#!/bin/zsh

set -euo pipefail

evidence_dir="records/active_slices/medical_writing_production_rebaseline_20260722/evidence/three_project_competitor_triage_20260725"
job_url="http://127.0.0.1:8911/api/projects/proj_my009_uc/medical-writing/jobs/mwjob_837db2a00b0b73afb35cad58"
run_url="http://127.0.0.1:8911/api/projects/proj_my009_uc/medical-writing/authoring-journey/competitor-triage/ct_run_53a04b910b236c0f234d"
contract_header="X-Workbench-Api-Contract: medical-writing-api-2026-07-17.1"
job_tmp="/tmp/uc_v12_job_watch.json"
run_wrapper_tmp="/tmp/uc_v12_run_wrapper.json"
last_state=""

while true; do
  curl -fsS --max-time 20 -H "${contract_header}" "${job_url}" > "${job_tmp}"
  current_state="$(
    jq -r '[.status, (.progress.step // 0), (.progress.step_total // 0), (.progress.percent // 0), (.updated_at // "")] | @tsv' "${job_tmp}"
  )"
  if [[ "${current_state}" != "${last_state}" ]]; then
    printf '%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "${current_state}"
    last_state="${current_state}"
  fi

  job_status="$(jq -r '.status' "${job_tmp}")"
  if [[ "${job_status}" != "running" && "${job_status}" != "queued" ]]; then
    cp "${job_tmp}" "${evidence_dir}/uc_v12_job_result.json"
    curl -fsS --max-time 30 -H "${contract_header}" "${run_url}" > "${run_wrapper_tmp}"
    jq '.run // .' "${run_wrapper_tmp}" > "${evidence_dir}/uc_v12_run.json"
    shasum -a 256 \
      "${evidence_dir}/uc_v12_job_result.json" \
      "${evidence_dir}/uc_v12_run.json"
    printf 'UC_TERMINAL_FREEZE_COMPLETE\n'
    exit 0
  fi

  sleep 120
done
