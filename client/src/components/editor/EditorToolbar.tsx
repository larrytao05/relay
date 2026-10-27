import type { LineArrowDefaults, Tool } from "../../editor/types.ts";
import EditorIcon, { type EditorIconName } from "./EditorIcon.tsx";

const tools: { tool: Tool; icon: EditorIconName; label: string; shortcut: string }[] = [
  { tool: "select", icon: "select", label: "Select", shortcut: "V" },
  { tool: "rectangle", icon: "rectangle", label: "Rectangle", shortcut: "R" },
  { tool: "ellipse", icon: "ellipse", label: "Ellipse", shortcut: "O" },
  { tool: "line", icon: "line", label: "Line", shortcut: "L" },
  { tool: "text", icon: "text", label: "Text", shortcut: "T" },
];

const lineStyles: { label: string; arrows: LineArrowDefaults }[] = [
  { label: "Plain line", arrows: { start_arrow: false, end_arrow: false } },
  { label: "Arrow at start", arrows: { start_arrow: true, end_arrow: false } },
  { label: "Arrow at end", arrows: { start_arrow: false, end_arrow: true } },
  { label: "Arrows at both ends", arrows: { start_arrow: true, end_arrow: true } },
];

export default function EditorToolbar({
  activeTool,
  lineArrowDefaults,
  onLineArrowDefaults,
  canUndo,
  canRedo,
  disabled,
  onTool,
  onUndo,
  onRedo,
}: {
  activeTool: Tool;
  lineArrowDefaults: LineArrowDefaults;
  onLineArrowDefaults(values: LineArrowDefaults): void;
  canUndo: boolean;
  canRedo: boolean;
  disabled: boolean;
  onTool(tool: Tool): void;
  onUndo(): void;
  onRedo(): void;
}) {
  return (
    <>
    {activeTool === "line" && <div className="line-options" role="group" aria-label="Line ends">
      {lineStyles.map(({ label, arrows }) => (
        <button key={label} type="button" className={`line-style${lineArrowDefaults.start_arrow === arrows.start_arrow && lineArrowDefaults.end_arrow === arrows.end_arrow ? " is-active" : ""}`} aria-label={label} aria-pressed={lineArrowDefaults.start_arrow === arrows.start_arrow && lineArrowDefaults.end_arrow === arrows.end_arrow} title={label} disabled={disabled} onClick={() => onLineArrowDefaults(arrows)}>
          <svg viewBox="0 0 24 28" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 4v20" />
            {arrows.start_arrow && <path d="M7 9l5-5 5 5" />}
            {arrows.end_arrow && <path d="M7 19l5 5 5-5" />}
          </svg>
        </button>
      ))}
    </div>}
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
    </>
  );
}
