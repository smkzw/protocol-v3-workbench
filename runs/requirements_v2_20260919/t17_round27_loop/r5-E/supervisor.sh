#!/bin/zsh
# R5-E supervisor: relaunch the headless tester until report.md carries EXIT=OK.
# Cap: 4 attempts x 35m ~= within the 150-minute polling budget of this dispatch.
R5E="/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round27_loop/r5-E"
cd "$R5E" || exit 9
echo "$(date '+%F %T') SUPERVISOR start" >> supervisor.log
PROMPT="prompt.md"
for i in $(seq 1 4); do
  if [ -f report.md ] && grep -q "EXIT=OK" report.md; then
    echo "$(date '+%F %T') SUPERVISOR report complete at attempt $i" >> supervisor.log
    exit 0
  fi
  if [ "$i" -gt 1 ]; then PROMPT="resume.md"; fi
  echo "$(date '+%F %T') SUPERVISOR attempt $i launching with @$PROMPT" >> supervisor.log
  omp -p --no-session --model openai-codex/gpt-6.1-sol --thinking medium --auto-approve --max-time 35m --cwd "$R5E" @"$PROMPT" >> "run$i.log" 2>&1
  echo "$(date '+%F %T') SUPERVISOR attempt $i exited code=$?" >> supervisor.log
  if [ -f report.md ] && grep -q "EXIT=OK" report.md; then
    echo "$(date '+%F %T') SUPERVISOR report complete after attempt $i" >> supervisor.log
    exit 0
  fi
  sleep 10
done
echo "$(date '+%F %T') SUPERVISOR exhausted 4 attempts" >> supervisor.log
exit 7
