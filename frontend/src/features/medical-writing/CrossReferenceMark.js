import { Mark, mergeAttributes } from "@tiptap/core";

export const CrossReferenceMark = Mark.create({
  name: "crossReference",
  inclusive: false,
  addAttributes() {
    return {
      targetKind: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-cross-reference-kind"),
        renderHTML: (attributes) => attributes.targetKind
          ? { "data-cross-reference-kind": attributes.targetKind }
          : {},
      },
      targetId: {
        default: null,
        parseHTML: (element) => element.getAttribute("data-cross-reference-id"),
        renderHTML: (attributes) => attributes.targetId
          ? { "data-cross-reference-id": attributes.targetId }
          : {},
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-cross-reference-kind][data-cross-reference-id]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { class: "protocol-cross-reference" }), 0];
  },
});

export function insertCrossReference(editor, target) {
  const targetKind = String(target?.kind || "").trim();
  const targetId = String(target?.object_id || "").trim();
  const number = Number(target?.number);
  if (
    !editor
    || !["table", "figure"].includes(targetKind)
    || !targetId
    || !Number.isInteger(number)
    || number < 1
  ) return false;
  const label = targetKind === "table" ? "表" : "图";
  return editor.chain()
    .focus()
    .setTextSelection(editor.state.selection.to)
    .insertContent({
      type: "text",
      text: `${label} ${number}`,
      marks: [{
        type: "crossReference",
        attrs: { targetKind, targetId },
      }],
    })
    .unsetMark("crossReference")
    .run();
}
