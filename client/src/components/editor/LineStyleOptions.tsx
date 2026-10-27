import type { LineArrowDefaults } from "../../editor/types.ts";

const lineStyles: { label: string; arrows: LineArrowDefaults }[] = [
  { label: "Plain line", arrows: { start_arrow: false, end_arrow: false } },
  { label: "Arrow at start", arrows: { start_arrow: true, end_arrow: false } },
  { label: "Arrow at end", arrows: { start_arrow: false, end_arrow: true } },
  { label: "Arrows at both ends", arrows: { start_arrow: true, end_arrow: true } },
];

export default function LineStyleOptions({ value, disabled, onChange }: { value: LineArrowDefaults; disabled: boolean; onChange(value: LineArrowDefaults): void }) {
  return <div className="line-style-options" role="group" aria-label="Line ends">
    {lineStyles.map(({ label, arrows }) => (
      <button key={label} type="button" className={`line-style${value.start_arrow === arrows.start_arrow && value.end_arrow === arrows.end_arrow ? " is-active" : ""}`} aria-label={label} aria-pressed={value.start_arrow === arrows.start_arrow && value.end_arrow === arrows.end_arrow} title={label} disabled={disabled} onClick={() => onChange(arrows)}>
        <svg viewBox="0 0 24 28" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 4v20" />
          {arrows.start_arrow && <path d="M7 9l5-5 5 5" />}
          {arrows.end_arrow && <path d="M7 19l5 5 5-5" />}
        </svg>
      </button>
    ))}
  </div>;
}
