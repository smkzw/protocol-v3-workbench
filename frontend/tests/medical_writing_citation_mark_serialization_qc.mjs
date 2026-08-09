import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Editor } from "@tiptap/core";
import Subscript from "@tiptap/extension-subscript";
import Superscript from "@tiptap/extension-superscript";
import StarterKit from "@tiptap/starter-kit";
import { createServer } from "vite";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const server = await createServer({
  root: frontendRoot,
  appType: "custom",
  server: { middlewareMode: true },
});

try {
  const { CitationMark, normalizeCitationMarkAttributes } = await server.ssrLoadModule("/src/App.jsx");
  const referenceId = "mwref_0123456789abcdef0123";
  const editor = new Editor({
    element: null,
    extensions: [StarterKit, Subscript, Superscript, CitationMark],
    content: { type: "doc", content: [{ type: "paragraph" }] },
  });

  editor.commands.insertContent({
    type: "text",
    text: "[待编号]",
    marks: [{ type: "citation", attrs: { referenceIds: [referenceId] } }],
  });
  const insertedMark = editor.getJSON().content[0].content[0].marks[0];
  assert.equal(insertedMark.type, "citation");
  assert.deepEqual([...insertedMark.attrs.referenceIds], [referenceId]);
  assert.deepEqual(Object.keys(insertedMark.attrs), ["referenceIds"]);
  assert.equal("referenceId" in insertedMark.attrs, false);

  const migrated = normalizeCitationMarkAttributes({
    type: "doc",
    content: [{
      type: "paragraph",
      content: [{
        type: "text",
        text: "[旧引文]",
        marks: [{ type: "citation", attrs: { referenceId } }],
      }],
    }],
  });
  editor.commands.setContent(migrated);
  const migratedMark = editor.getJSON().content[0].content[0].marks[0];
  assert.equal(migratedMark.type, "citation");
  assert.deepEqual([...migratedMark.attrs.referenceIds], [referenceId]);
  assert.deepEqual(Object.keys(migratedMark.attrs), ["referenceIds"]);
  assert.equal("referenceId" in migratedMark.attrs, false);
  editor.destroy();

  process.stdout.write("CitationMark serialization contract passed\n");
} finally {
  await server.close();
}
