# Batch1 diagram reference — source inspection only

Read the complete SVG XML and verified SHA256 against design-v1.3:
`/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07_研究流程图示例.svg`
`c08dc55324b92ed45e283335c1e28a7955993cd42f687c0ca1395c4730c0372c`.
The source is unchanged. This is a supporting example, not template authority,
actual project data or rendered visual acceptance.

The image is1180x780, showing screening, randomization, two arms, treatment end,
safety follow-up, study end and two gray exit branches. It contains example
1:1/block/IWRS allocation, placebo,12weeks,4weekly visits,4week follow-up and
literal n=XX / trial-drug placeholders. None may become a universal default.

Topology inspection: the early-exit arrow is physically drawn from the right
arm only; its branch box has no onward arrow to the separate follow-up box.
A real generated trial diagram must derive applicable transitions for every
arm and each discontinuation/withdrawal scenario from confirmed facts. Copying
the SVG would not prove that it represents the project's visit/exit logic.
The text also combines early withdrawal and intervention discontinuation;
preserve their distinctions according to the actual protocol scenario.

After batch1 worker completes, verify its diagram skill provenance includes
this exact supporting asset/hash and its example-only status; if absent, add a
bounded correction with source assertions. Do not edit worker-owned inputs or
JSON files mid-run. Later7R must inspect actual rendered vector/Word output,
including arrow placement, labels, wrapping and legibility.
