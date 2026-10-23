import type { Tool } from "../../editor/types.ts";
import EditorIcon, { type EditorIconName } from "./EditorIcon.tsx";

const tools: { tool: Tool; icon: EditorIconName; label: string; shortcut: string }[] = [
  { tool: "select", icon: "select", label: "Select", shortcut: "V" },
  { tool: "rectangle", icon: "rectangle", label: "Rectangle", shortcut: "R" },
  { tool: "ellipse", icon: "ellipse", label: "Ellipse", shortcut: "O" },
  { tool: "line", icon: "line", label: "Line", shortcut: "L" },
  { tool: "text", icon: "text", label: "Text", shortcut: "T" },
];

export default function EditorToolbar({
  activeTool,
  canUndo,
  canRedo,
  disabled,
  onTool,
  onUndo,
  onRedo,
}: {
  activeTool: Tool;
  canUndo: boolean;
  canRedo: boolean;
  disabled: boolean;
  onTool(tool: Tool): void;
  onUndo(): void;
  onRedo(): void;
}) {
  return (
    <div className="editor-toolbar" role="toolbar" aria-label="Drawing tools">
      {tools.map(({ tool, icon, label, shortcut }) => (
        <button key={tool} className={`editor-tool${activeTool === tool ? " is-active" : ""}`} type="button" aria-label={`${label} tool (${shortcut})`} aria-pressed={activeTool === tool} title={`${label} (${shortcut})`} disabled={disabled} onClick={() => onTool(tool)}>
          <EditorIcon name={icon} />
        </button>
      ))}
      <span className="editor-toolbar-separator" aria-hidden="true" />
      <button className="editor-tool" type="button" aria-label="Undo" title="Undo (Ctrl/Cmd+Z)" disabled={disabled || !canUndo} onClick={onUndo}><EditorIcon name="undo" /></button>
      <button className="editor-tool" type="button" aria-label="Redo" title="Redo (Ctrl/Cmd+Shift+Z)" disabled={disabled || !canRedo} onClick={onRedo}><EditorIcon name="redo" /></button>
    </div>
  );
}
