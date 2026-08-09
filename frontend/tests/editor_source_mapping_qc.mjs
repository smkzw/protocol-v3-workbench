import assert from "node:assert/strict";
import { groupEditorNodesBySourceBlockId } from "../src/features/medical-writing/editorSourceMapping.js";

const blocks = [
  { block_id: "p-1", block_type: "paragraph" },
  { block_id: "table-1", block_type: "table" },
  { block_id: "p-2", block_type: "paragraph" },
  { block_id: "figure-1", block_type: "figure" },
  { block_id: "p-3", block_type: "paragraph" },
];
const bound = (type, sourceBlockId) => ({ type, attrs: { sourceBlockId } });
const paragraph = (text = "") => ({
  type: "paragraph",
  content: text ? [{ type: "text", text }] : undefined,
});
const markedParagraph = (text, marks) => ({
  type: "paragraph",
  content: [{ type: "text", text, marks }],
});
const sourceBlock = (sourceBlockId, content) => ({
  type: "sourceBlock",
  attrs: { sourceBlockId },
  content,
});
const options = {
  isEffectivelyEmptyNode: (node) => !node?.content?.some((item) => item.text),
};

const middle = groupEditorNodesBySourceBlockId(blocks, [
  bound("sourceBlock", "p-1"),
  bound("table", "table-1"),
  bound("sourceBlock", "p-2"),
  paragraph("用户在章节中部新增的段落"),
  bound("sourceDocxImage", "figure-1"),
  bound("sourceBlock", "p-3"),
], options);
assert.equal(middle.error, "");
assert.deepEqual(middle.boundSourceBlockIds, blocks.map((block) => block.block_id));
assert.equal(middle.groups[2].trailingNodes[0].content[0].text, "用户在章节中部新增的段落");
assert.equal(middle.groups[3].blockId, "figure-1");

const end = groupEditorNodesBySourceBlockId(blocks, [
  bound("sourceBlock", "p-1"),
  bound("table", "table-1"),
  bound("sourceBlock", "p-2"),
  bound("sourceDocxImage", "figure-1"),
  bound("sourceBlock", "p-3"),
  paragraph("用户在文末新增的段落"),
], options);
assert.equal(end.error, "");
assert.equal(end.groups[4].trailingNodes.length, 1);

const reordered = groupEditorNodesBySourceBlockId(blocks, [
  bound("sourceBlock", "p-1"),
  bound("sourceBlock", "p-2"),
  bound("table", "table-1"),
  bound("sourceDocxImage", "figure-1"),
  bound("sourceBlock", "p-3"),
], options);
assert.match(reordered.error, /顺序发生变化/);

const afterTable = groupEditorNodesBySourceBlockId(blocks, [
  bound("sourceBlock", "p-1"),
  bound("table", "table-1"),
  paragraph("来源不明确"),
  bound("sourceBlock", "p-2"),
  bound("sourceDocxImage", "figure-1"),
  bound("sourceBlock", "p-3"),
], options);
assert.match(afterTable.error, /无法确定正文来源/);

const missingFigure = groupEditorNodesBySourceBlockId(blocks, [
  bound("sourceBlock", "p-1"),
  bound("table", "table-1"),
  bound("sourceBlock", "p-2"),
  bound("sourceBlock", "p-3"),
], options);
assert.match(missingFigure.error, /顺序发生变化|缺少来源块/);

const headingAndBodyBlocks = [
  { block_id: "heading-1", block_type: "heading" },
  { block_id: "body-1", block_type: "paragraph" },
];
const boldMark = [{ type: "bold" }];
const enterInsideHeadingSourceBlock = groupEditorNodesBySourceBlockId(
  headingAndBodyBlocks,
  [
    sourceBlock("heading-1", [
      {
        type: "heading",
        attrs: { level: 2 },
        content: [{ type: "text", text: "疾病背景及治疗现状" }],
      },
      markedParagraph("回车后新增正文", boldMark),
    ]),
    sourceBlock("body-1", [
      {
        type: "paragraph",
        content: [{ type: "text", text: "原正文" }],
      },
    ]),
  ],
  options,
);
assert.equal(enterInsideHeadingSourceBlock.error, "");
assert.equal(enterInsideHeadingSourceBlock.groups[0].node.content.length, 1);
assert.equal(enterInsideHeadingSourceBlock.groups[0].node.content[0].type, "heading");
assert.equal(enterInsideHeadingSourceBlock.groups[0].trailingNodes.length, 0);
assert.equal(enterInsideHeadingSourceBlock.groups[1].leadingNodes.length, 1);
assert.equal(
  enterInsideHeadingSourceBlock.groups[1].leadingNodes[0].content[0].text,
  "回车后新增正文",
);
assert.deepEqual(
  enterInsideHeadingSourceBlock.groups[1].leadingNodes[0].content[0].marks,
  boldMark,
);

const enterAfterHeadingSourceBlock = groupEditorNodesBySourceBlockId(
  headingAndBodyBlocks,
  [
    sourceBlock("heading-1", [{
      type: "heading",
      attrs: { level: 2 },
      content: [{ type: "text", text: "疾病背景及治疗现状" }],
    }]),
    markedParagraph("容器外新增正文", boldMark),
    sourceBlock("body-1", [{
      type: "paragraph",
      content: [{ type: "text", text: "原正文" }],
    }]),
  ],
  options,
);
assert.equal(enterAfterHeadingSourceBlock.error, "");
assert.equal(enterAfterHeadingSourceBlock.groups[0].trailingNodes.length, 0);
assert.equal(enterAfterHeadingSourceBlock.groups[1].leadingNodes.length, 1);
assert.deepEqual(
  enterAfterHeadingSourceBlock.groups[1].leadingNodes[0].content[0].marks,
  boldMark,
);

const headingWithoutImmediateBody = groupEditorNodesBySourceBlockId(
  [
    { block_id: "heading-only", block_type: "heading" },
    { block_id: "table-only", block_type: "table" },
  ],
  [
    sourceBlock("heading-only", [
      { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "标题" }] },
      paragraph("无法安全绑定的正文"),
    ]),
    bound("table", "table-only"),
  ],
  options,
);
assert.match(headingWithoutImmediateBody.error, /标题后的新增正文|正文来源/);

console.log(JSON.stringify({
  status: "passed",
  scenarios: [
    "middle paragraph anchored to preceding stable sourceBlockId",
    "end paragraph anchored to final stable sourceBlockId",
    "canonical reorder rejected",
    "paragraph after table rejected",
    "missing figure identity rejected",
    "paragraph created inside heading source block moves to the following body block",
    "unbound paragraph after heading moves to the following body block",
    "bold marks survive source-block routing",
    "heading overflow without an immediate body block fails closed",
  ],
}, null, 2));
