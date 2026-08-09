import { Extension } from "@tiptap/core";
import { redo, undo } from "@tiptap/pm/history";
import { Plugin, PluginKey } from "@tiptap/pm/state";

const wordEditingShortcutsPluginKey = new PluginKey("wordEditingShortcuts");

export const WordEditingShortcuts = Extension.create({
  name: "wordEditingShortcuts",
  priority: 1000,
  addKeyboardShortcuts() {
    return {
      "Mod-b": () => this.editor.commands.toggleBold(),
      "Mod-i": () => this.editor.commands.toggleItalic(),
      "Mod-u": () => this.editor.commands.toggleUnderline(),
      "Mod-z": () => this.editor.commands.undo(),
      "Mod-Shift-z": () => this.editor.commands.redo(),
      "Mod-y": () => this.editor.commands.redo(),
    };
  },
  addProseMirrorPlugins() {
    return [new Plugin({
      key: wordEditingShortcutsPluginKey,
      props: {
        handleKeyDown(view, event) {
          if (!(event.metaKey || event.ctrlKey) || event.altKey) return false;
          const key = String(event.key || "").toLowerCase();
          const command = key === "z"
            ? (event.shiftKey ? redo : undo)
            : key === "y" && !event.shiftKey
              ? redo
              : null;
          if (!command || !command(view.state, view.dispatch)) return false;
          event.preventDefault();
          return true;
        },
      },
    })];
  },
});

export default WordEditingShortcuts;
