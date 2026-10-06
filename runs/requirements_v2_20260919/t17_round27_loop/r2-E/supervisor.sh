#!/bin/zsh
# R2-E supervisor: relaunch the headless tester until report.md carries EXIT=OK.
R2E="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round27_loop/r2-E"
cd "$R2E" || exit 9
echo "$(date '+%F %T') SUPERVISOR start" >> supervisor.log
for i in $(seq 1 8); do
  if [ -f report.md ] && grep -q "EXIT=OK" report.md; then
    echo "$(date '+%F %T') SUPERVISOR report complete at attempt $i" >> supervisor.log
    exit 0
  fi
  echo "$(date '+%F %T') SUPERVISOR attempt $i launching" >> supervisor.log
  omp -p --no-session --model openai-codex/gpt-6.1-sol --thinking medium --auto-approve --max-time 35m --cwd "$R2E" @resume2.md >> run3.log 2>&1
  echo "$(date '+%F %T') SUPERVISOR attempt $i exited code=$?" >> supervisor.log
  if [ -f report.md ] && grep -q "EXIT=OK" report.md; then
    echo "$(date '+%F %T') SUPERVISOR report complete after attempt $i" >> supervisor.log
    exit 0
  fi
  sleep 10
done
echo "$(date '+%F %T') SUPERVISOR exhausted 8 attempts" >> supervisor.log
exit 7
