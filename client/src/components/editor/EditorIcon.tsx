export type EditorIconName = "back" | "undo" | "redo" | "delete" | "select" | "rectangle" | "ellipse" | "line" | "text" | "invite" | "account";

export default function EditorIcon({ name }: { name: EditorIconName }) {
  const common = { fill: "none", stroke: "currentColor", strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (name) {
    case "back": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12.5 4.5-5.5 5.5 5.5 5.5" strokeWidth="1.7" {...common} /></svg>;
    case "undo": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 6 4 9.5 7.5 13M4 9.5h7a5 5 0 0 1 5 5" strokeWidth="1.6" {...common} /></svg>;
    case "redo": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12.5 6 3.5 3.5-3.5 3.5M16 9.5H9a5 5 0 0 0-5 5" strokeWidth="1.6" {...common} /></svg>;
    case "delete": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 6h11M8 6V4.3h4V6m-6.5 0 .7 10h7.6l.7-10M8.5 9v4m3-4v4" strokeWidth="1.5" {...common} /></svg>;
    case "select": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 2 11 9-5 .8-2.4 4.2L4 2Z" strokeWidth="1.6" {...common} /></svg>;
    case "rectangle": return <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="4" width="14" height="12" rx="1.5" strokeWidth="1.6" {...common} /></svg>;
    case "ellipse": return <svg viewBox="0 0 20 20" aria-hidden="true"><ellipse cx="10" cy="10" rx="7" ry="5.5" strokeWidth="1.6" {...common} /></svg>;
    case "line": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 15 12-10" strokeWidth="1.7" {...common} /></svg>;
    case "text": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 5h12M10 5v11m-3 0h6" strokeWidth="1.6" {...common} /></svg>;
    case "invite": return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4v12M4 10h12" strokeWidth="1.8" {...common} /></svg>;
    case "account": return <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="6.5" r="3" strokeWidth="1.5" {...common} /><path d="M4.5 16c.7-2.5 2.6-3.8 5.5-3.8s4.8 1.3 5.5 3.8" strokeWidth="1.5" {...common} /></svg>;
  }
}
