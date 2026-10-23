import { useEffect, useState, type FormEvent } from "react";
import { parseColorCode } from "../../editor/color.ts";
import type { Shape } from "../../editor/types.ts";
import EditorIcon from "./EditorIcon.tsx";

export const EDITOR_COLORS = [
  { name: "Blue", value: "#dce6ff" },
  { name: "Green", value: "#d9eee4" },
  { name: "Gold", value: "#f6e8bd" },
  { name: "Pink", value: "#f2dfe0" },
  { name: "White", value: "#ffffff" },
];

export default function SelectionInspector({
  selected,
  shapes,
  defaultColor,
  disabled,
  onColor,
  onDelete,
}: {
  selected: Shape | null;
  shapes: Shape[];
  defaultColor: string;
  disabled: boolean;
  onColor(color: string): void;
  onDelete(): void;
}) {
  const color = selected?.properties.color ?? defaultColor;
  const [rgb, setRgb] = useState(() => colorToChannels(color));
  const [colorError, setColorError] = useState<string | null>(null);
  const usedColors = [...new Set(shapes.map((shape) => shape.properties.color.toLowerCase()))];
  const presetColors = EDITOR_COLORS.filter((swatch) => !usedColors.includes(swatch.value));

  useEffect(() => {
    setRgb(colorToChannels(color));
    setColorError(null);
  }, [color]);

  function applyColorCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parseColorCode(`rgb(${rgb.red}, ${rgb.green}, ${rgb.blue})`);
    if (!parsed) {
      setColorError("Enter whole numbers from 0 to 255 for red, green, and blue.");
      return;
    }
    setColorError(null);
    onColor(parsed);
  }

  return (
    <aside className="editor-inspector" aria-label="Selected object properties">
      <div className="inspector-heading"><h2>Design</h2></div>
      <section className="inspector-section">
        <h3>Selected</h3>
        {selected ? (
          <div className="selected-shape">
            <span className="selected-shape-icon"><EditorIcon name={selected.kind === "rectangle" ? "rectangle" : selected.kind === "ellipse" ? "ellipse" : selected.kind === "line" ? "line" : "text"} /></span>
            <span>{selected.kind === "text" ? selected.properties.text.slice(0, 32) || "Text" : selected.kind[0].toUpperCase() + selected.kind.slice(1)}</span>
          </div>
        ) : <p className="inspector-empty">No object selected</p>}
      </section>
      <section className="inspector-section">
        <h3>{selected ? "Color" : "Default color"}</h3>
        {usedColors.length > 0 && <>
          <p className="inspector-color-label">On this canvas</p>
          <div className="editor-swatches" aria-label="Colors used on this canvas">
            {usedColors.map((value) => (
              <button key={value} className={`editor-swatch${color.toLowerCase() === value ? " is-selected" : ""}`} type="button" aria-label={`Canvas color ${value}`} aria-pressed={color.toLowerCase() === value} title={value} disabled={disabled} style={{ backgroundColor: value }} onClick={() => onColor(value)} />
            ))}
          </div>
        </>}
        <p className="inspector-color-label">Presets</p>
        <div className="editor-swatches" aria-label="Preset colors">
          {presetColors.map((swatch) => (
            <button key={swatch.value} className={`editor-swatch${color.toLowerCase() === swatch.value ? " is-selected" : ""}`} type="button" aria-label={swatch.name} aria-pressed={color.toLowerCase() === swatch.value} title={swatch.name} disabled={disabled} style={{ backgroundColor: swatch.value }} onClick={() => onColor(swatch.value)} />
          ))}
        </div>
        <form className="editor-color-code" onSubmit={applyColorCode}>
          <span className="editor-color-code-label">Custom RGB color</span>
          <div className="editor-color-code-row">
            <label>R<input aria-label="Red value" type="number" min="0" max="255" step="1" value={rgb.red} aria-invalid={colorError !== null} aria-describedby={colorError ? "editor-rgb-error" : undefined} disabled={disabled} onChange={(event) => { setRgb({ ...rgb, red: event.target.value }); setColorError(null); }} /></label>
            <label>G<input aria-label="Green value" type="number" min="0" max="255" step="1" value={rgb.green} aria-invalid={colorError !== null} aria-describedby={colorError ? "editor-rgb-error" : undefined} disabled={disabled} onChange={(event) => { setRgb({ ...rgb, green: event.target.value }); setColorError(null); }} /></label>
            <label>B<input aria-label="Blue value" type="number" min="0" max="255" step="1" value={rgb.blue} aria-invalid={colorError !== null} aria-describedby={colorError ? "editor-rgb-error" : undefined} disabled={disabled} onChange={(event) => { setRgb({ ...rgb, blue: event.target.value }); setColorError(null); }} /></label>
            <button type="submit" disabled={disabled}>Apply</button>
          </div>
          {colorError && <p className="editor-color-error" id="editor-rgb-error" role="alert">{colorError}</p>}
        </form>
      </section>
      {selected && <section className="inspector-section">
        <button className="editor-delete-button" type="button" disabled={disabled} onClick={onDelete}>
          <EditorIcon name="delete" />Delete object
        </button>
      </section>}
    </aside>
  );
}

function colorToChannels(color: string): { red: string; green: string; blue: string } {
  const parsed = parseColorCode(color);
  if (!parsed) return { red: "0", green: "0", blue: "0" };
  const channels = [0, 2, 4].map((offset) => String(Number.parseInt(parsed.slice(offset + 1, offset + 3), 16)));
  return { red: channels[0], green: channels[1], blue: channels[2] };
}
