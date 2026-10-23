import { Link } from "react-router";

const colors = [
  { name: "Blue", value: "#dce6ff", className: "blue" },
  { name: "Green", value: "#d9eee4", className: "green" },
  { name: "Gold", value: "#f6e8bd", className: "gold" },
  { name: "Pink", value: "#f2dfe0", className: "pink" },
  { name: "White", value: "#ffffff", className: "white" },
] as const;

type IconName = "back" | "undo" | "redo" | "delete" | "select" | "rectangle" | "ellipse" | "line" | "text" | "invite" | "account";

function Icon({ name }: { name: IconName }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  switch (name) {
    case "back":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12.5 4.5-5.5 5.5 5.5 5.5" strokeWidth="1.7" {...common} /></svg>;
    case "undo":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 6 4 9.5 7.5 13M4 9.5h7a5 5 0 0 1 5 5" strokeWidth="1.6" {...common} /></svg>;
    case "redo":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12.5 6 3.5 3.5-3.5 3.5M16 9.5H9a5 5 0 0 0-5 5" strokeWidth="1.6" {...common} /></svg>;
    case "delete":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 6h11M8 6V4.3h4V6m-6.5 0 .7 10h7.6l.7-10M8.5 9v4m3-4v4" strokeWidth="1.5" {...common} /></svg>;
    case "select":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 2 11 9-5 .8-2.4 4.2L4 2Z" strokeWidth="1.6" {...common} /></svg>;
    case "rectangle":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><rect x="3" y="4" width="14" height="12" rx="1.5" strokeWidth="1.6" {...common} /></svg>;
    case "ellipse":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><ellipse cx="10" cy="10" rx="7" ry="5.5" strokeWidth="1.6" {...common} /></svg>;
    case "line":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4 15 12-10" strokeWidth="1.7" {...common} /><circle cx="4" cy="15" r="1.5" fill="currentColor" /><circle cx="16" cy="5" r="1.5" fill="currentColor" /></svg>;
    case "text":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 5h12M10 5v11m-3 0h6" strokeWidth="1.6" {...common} /></svg>;
    case "invite":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 4v12M4 10h12" strokeWidth="1.8" {...common} /></svg>;
    case "account":
      return <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="6.5" r="3" strokeWidth="1.5" {...common} /><path d="M4.5 16c.7-2.5 2.6-3.8 5.5-3.8s4.8 1.3 5.5 3.8" strokeWidth="1.5" {...common} /></svg>;
    default: {
      const exhaustiveCheck: never = name;
      return exhaustiveCheck;
    }
  }
}

function BrandMark() {
  return (
    <span className="editor-brand-mark" aria-hidden="true">
      <svg viewBox="0 0 20 20" fill="none">
        <path d="M4 5.5h7.5a3 3 0 0 1 0 6H8.5a3 3 0 0 0 0 6H16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <circle cx="4" cy="5.5" r="1.5" fill="currentColor" />
        <circle cx="16" cy="17.5" r="1.5" fill="currentColor" />
      </svg>
    </span>
  );
}

function ToolbarButton({ name, label, active = false, disabled = false }: { name: IconName; label: string; active?: boolean; disabled?: boolean }) {
  return (
    <button className={`editor-tool${active ? " is-active" : ""}`} type="button" aria-label={label} aria-pressed={active} title={label} disabled={disabled}>
      <Icon name={name} />
    </button>
  );
}

function RemoteCursor({ name, className }: { name: string; className: string }) {
  return (
    <div className={`remote-cursor ${className}`} aria-label={`${name}'s cursor`}>
      <svg viewBox="0 0 18 21" fill="none" aria-hidden="true">
        <path d="M2 1.5 15.5 12l-6.2.7-3.1 5.7L2 1.5Z" fill="currentColor" stroke="white" strokeWidth="1.4" strokeLinejoin="round" />
      </svg>
      <span>{name}</span>
    </div>
  );
}

function Whiteboard() {
  return (
    <div className="editor-stage" aria-label="Whiteboard preview">
      <div className="editor-canvas-label">Checkout flow</div>
      <div className="editor-board-wrap">
        <div className="editor-board">
          <svg viewBox="0 0 820 503" role="img" aria-label="Whiteboard with a selected payment card, order status, and note">
            <g className="board-shape" transform="translate(65 208)">
              <rect width="170" height="88" rx="12" fill="#edf1ff" stroke="#c9d5fa" strokeWidth="1.5" />
              <text x="85" y="37" textAnchor="middle" fill="#2c3e78" fontSize="15" fontWeight="650">Review cart</text>
              <text x="85" y="59" textAnchor="middle" fill="#6b7da9" fontSize="11">Items · delivery · total</text>
            </g>
            <g className="board-shape is-selected" transform="translate(303 208)">
              <rect className="shape-outline" width="207" height="88" rx="12" fill="#f6e8bd" stroke="#e7d390" strokeWidth="1.5" />
              <text x="103.5" y="37" textAnchor="middle" fill="#58481c" fontSize="15" fontWeight="650">Payment details</text>
              <text x="103.5" y="59" textAnchor="middle" fill="#897746" fontSize="11">Card · billing address</text>
              <circle className="resize-handle" cx="0" cy="0" r="4" />
              <circle className="resize-handle" cx="207" cy="0" r="4" />
              <circle className="resize-handle" cx="0" cy="88" r="4" />
              <circle className="resize-handle" cx="207" cy="88" r="4" />
            </g>
            <g className="board-shape" transform="translate(575 217)">
              <ellipse cx="78" cy="42" rx="78" ry="42" fill="#d9eee4" stroke="#b6ddca" strokeWidth="1.5" />
              <text x="78" y="47" textAnchor="middle" fill="#285b49" fontSize="14" fontWeight="650">Order placed</text>
            </g>
            <g className="board-shape" transform="translate(514 345)">
              <rect width="190" height="61" rx="8" fill="#fff" stroke="#dce2e8" strokeWidth="1.5" />
              <text x="14" y="24" fill="#405064" fontSize="12" fontWeight="700">Open question</text>
              <text x="14" y="43" fill="#718092" fontSize="11">Can we offer guest checkout?</text>
            </g>
          </svg>
        </div>
      </div>
      <RemoteCursor name="Maya" className="cursor-maya" />
      <RemoteCursor name="Theo" className="cursor-theo" />
      <p className="editor-stage-hint">Select an object to see its properties</p>
      <div className="editor-toolbar" role="toolbar" aria-label="Drawing tools">
        <ToolbarButton name="select" label="Select tool (V)" active />
        <ToolbarButton name="rectangle" label="Rectangle tool (R)" />
        <ToolbarButton name="ellipse" label="Ellipse tool (O)" />
        <ToolbarButton name="line" label="Line tool (L)" />
        <ToolbarButton name="text" label="Text tool (T)" />
        <span className="editor-toolbar-separator" aria-hidden="true" />
        <ToolbarButton name="undo" label="Undo" />
        <ToolbarButton name="redo" label="Redo" disabled />
      </div>
    </div>
  );
}

function Inspector() {
  return (
    <aside className="editor-inspector" aria-label="Selected object properties">
      <div className="inspector-heading"><h2>Design</h2></div>
      <section className="inspector-section">
        <h3>Selected</h3>
        <div className="selected-shape">
          <span className="selected-shape-icon"><Icon name="rectangle" /></span>
          <span>Payment details</span>
        </div>
      </section>
      <section className="inspector-section">
        <h3>Fill color</h3>
        <div className="editor-swatches" aria-label="Fill color options">
          {colors.map((color) => (
            <span key={color.name} className={`editor-swatch ${color.className}${color.name === "Gold" ? " is-selected" : ""}`} title={color.name} aria-label={color.name} />
          ))}
        </div>
      </section>
      <section className="inspector-section">
        <button className="editor-delete-button" type="button">
          <Icon name="delete" />
          Delete object
        </button>
      </section>
    </aside>
  );
}

export default function EditorPage() {
  return (
    <>
      <style>{editorStyles}</style>
      <main className="editor-page">
        <header className="editor-topbar">
          <div className="editor-top-left">
            <Link className="editor-brand" to="/canvases" aria-label="Relay home">
              <BrandMark />
              <span>relay</span>
            </Link>
            <span className="editor-breadcrumb">My canvases /</span>
            <div className="editor-document">
              <span className="editor-document-title">Checkout flow</span>
              <span className="editor-save-status"><i aria-hidden="true" />All changes saved</span>
            </div>
          </div>
          <div className="editor-top-right">
            <button className="editor-button" type="button"><Icon name="invite" />Invite</button>
            <button className="editor-account" type="button" aria-label="Account menu"><span>LT</span><Icon name="account" /></button>
          </div>
        </header>
        <div className="editor-workspace">
          <Whiteboard />
          <Inspector />
        </div>
      </main>
    </>
  );
}

const editorStyles = `
  .editor-page {
    --editor-ink: #202b3a;
    --editor-muted: #718092;
    --editor-line: #e2e7ec;
    --editor-blue: #4968d7;
    --editor-blue-soft: #edf1ff;
    width: 100%;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    background: #f3f5f7;
    color: var(--editor-ink);
    font: 14px/1.45 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .editor-page button, .editor-page a { font: inherit; }
  .editor-page button { color: inherit; }
  .editor-page button:focus-visible, .editor-page a:focus-visible { outline: 3px solid rgb(73 104 215 / 32%); outline-offset: 2px; }
  .editor-topbar { position: relative; z-index: 3; display: flex; height: 68px; align-items: center; justify-content: space-between; gap: 16px; padding: 0 22px; border-bottom: 1px solid var(--editor-line); background: #fff; }
  .editor-top-left, .editor-top-right, .editor-brand, .editor-save-status { display: flex; align-items: center; }
  .editor-top-left { min-width: 0; gap: 24px; }
  .editor-brand { flex: 0 0 auto; gap: 10px; color: inherit; font-size: 16px; font-weight: 750; letter-spacing: -.04em; text-decoration: none; }
  .editor-brand-mark { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 9px 9px 9px 3px; background: var(--editor-blue); color: #fff; }
  .editor-brand-mark svg { width: 17px; height: 17px; }
  .editor-breadcrumb { flex: 0 0 auto; color: #91a0ae; font-size: 13px; }
  .editor-document { min-width: 0; }
  .editor-document-title { display: block; overflow: hidden; font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
  .editor-save-status { gap: 6px; color: var(--editor-muted); font-size: 12px; }
  .editor-save-status i { width: 7px; height: 7px; border-radius: 50%; background: #43a886; }
  .editor-top-right { flex: 0 0 auto; gap: 12px; }
  .editor-button { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 8px; padding: 0 13px; border: 1px solid var(--editor-line); border-radius: 8px; background: #fff; font-size: 13px !important; font-weight: 650; }
  .editor-button:hover { background: #f9fafb; }
  .editor-button svg { width: 15px; height: 15px; }
  .editor-account { display: inline-flex; width: 38px; height: 38px; align-items: center; justify-content: center; gap: 3px; border: 0; border-radius: 8px; background: transparent; }
  .editor-account:hover { background: #f0f3f6; }
  .editor-account span { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 50%; background: #637ab0; color: #fff; font-size: 10px; font-weight: 700; }
  .editor-account svg { display: none; width: 14px; height: 14px; }
  .editor-workspace { display: grid; height: calc(100% - 68px); min-height: 0; grid-template-columns: minmax(0, 1fr) 266px; }
  .editor-stage { position: relative; min-width: 0; overflow: hidden; background-color: #f0f3f6; background-image: radial-gradient(#cbd3dc 1px, transparent 1px); background-size: 22px 22px; }
  .editor-canvas-label { position: absolute; top: 22px; left: 25px; color: #8794a2; font-size: 11px; font-weight: 650; letter-spacing: .025em; }
  .editor-board-wrap { position: absolute; inset: 70px 55px 56px; display: grid; place-items: center; }
  .editor-board { position: relative; width: min(820px, 100%); aspect-ratio: 820 / 503; overflow: hidden; border: 1px solid #e7ebef; border-radius: 5px; background-color: #fff; background-image: radial-gradient(#e4e8ed .8px, transparent .8px); background-size: 18px 18px; box-shadow: 0 16px 45px rgb(31 45 64 / 9%); }
  .editor-board svg { display: block; width: 100%; height: 100%; overflow: visible; }
  .editor-board text { user-select: none; }
  .board-shape { cursor: default; }
  .shape-outline { stroke: var(--editor-blue); stroke-width: 2; stroke-dasharray: 5 4; }
  .resize-handle { fill: #fff; stroke: var(--editor-blue); stroke-width: 2; }
  .editor-toolbar { position: absolute; z-index: 4; bottom: 20px; left: 50%; display: flex; align-items: center; gap: 4px; padding: 6px; transform: translateX(-50%); border: 1px solid #e1e6eb; border-radius: 12px; background: #fff; box-shadow: 0 7px 22px rgb(29 42 60 / 12%); }
  .editor-tool { display: grid; width: 38px; height: 38px; flex: 0 0 auto; place-items: center; border: 0; border-radius: 8px; background: transparent; color: #627183; }
  .editor-tool:hover:not(:disabled) { background: #f1f4f7; color: var(--editor-ink); }
  .editor-tool.is-active { background: var(--editor-blue-soft); color: var(--editor-blue); }
  .editor-tool:disabled { opacity: .38; }
  .editor-tool svg { width: 18px; height: 18px; }
  .editor-toolbar-separator { width: 1px; height: 24px; margin: 0 3px; background: var(--editor-line); }
  .editor-stage-hint { position: absolute; right: 22px; bottom: 23px; margin: 0; color: #83909e; font-size: 11px; }
  .remote-cursor { position: absolute; z-index: 2; display: flex; align-items: flex-start; gap: 4px; color: #db7859; pointer-events: none; filter: drop-shadow(0 2px 2px rgb(25 36 48 / 20%)); }
  .remote-cursor svg { width: 17px; height: 19px; }
  .remote-cursor span { margin-top: 12px; padding: 3px 7px; border-radius: 4px 6px 6px; background: #db7859; color: #fff; font-size: 10px; font-weight: 650; white-space: nowrap; }
  .cursor-maya { top: 53%; left: 56%; }
  .cursor-theo { top: 30%; left: 77%; color: #438a76; }
  .cursor-theo span { background: #438a76; }
  .editor-inspector { z-index: 2; overflow: auto; border-left: 1px solid var(--editor-line); background: #fff; }
  .inspector-heading { padding: 19px 17px 16px; border-bottom: 1px solid #edf0f3; }
  .inspector-heading h2 { margin: 0; font-size: 13px; font-weight: 700; }
  .inspector-section { padding: 18px 17px; border-bottom: 1px solid #edf0f3; }
  .inspector-section h3 { margin: 0 0 14px; color: #82909f; font-size: 11px; font-weight: 700; letter-spacing: .035em; }
  .selected-shape { display: flex; align-items: center; gap: 9px; font-weight: 650; }
  .selected-shape-icon { display: grid; width: 29px; height: 29px; place-items: center; border: 1px solid #e5e9ee; border-radius: 7px; color: #718096; }
  .selected-shape-icon svg { width: 15px; height: 15px; }
  .editor-swatches { display: flex; align-items: center; gap: 9px; }
  .editor-swatch { width: 24px; height: 24px; flex: 0 0 auto; border: 2px solid transparent; border-radius: 50%; }
  .editor-swatch.is-selected { outline: 2px solid #fff; box-shadow: 0 0 0 2px var(--editor-blue); }
  .editor-swatch.blue { background: #dce6ff; }
  .editor-swatch.green { background: #d9eee4; }
  .editor-swatch.gold { background: #f6e8bd; }
  .editor-swatch.pink { background: #f2dfe0; }
  .editor-swatch.white { border-color: #e1e6eb; background: #fff; }
  .editor-delete-button { display: flex; width: 100%; min-height: 36px; align-items: center; gap: 8px; padding: 0; border: 0; background: transparent; color: #9a5b5b !important; text-align: left; }
  .editor-delete-button svg { width: 16px; height: 16px; }
  @media (max-width: 850px) {
    .editor-workspace { grid-template-columns: minmax(0, 1fr); }
    .editor-inspector { display: none; }
    .editor-board-wrap { inset: 76px 18px 72px; }
    .editor-stage-hint { display: none; }
  }
  @media (max-width: 560px) {
    .editor-topbar { height: 58px; padding: 0 12px; }
    .editor-top-left { gap: 12px; }
    .editor-breadcrumb, .editor-save-status { display: none; }
    .editor-top-right { gap: 6px; }
    .editor-button { min-height: 34px; padding: 0 10px; }
    .editor-workspace { height: calc(100% - 58px); }
    .editor-canvas-label { top: 14px; left: 14px; }
    .editor-board-wrap { inset: 56px 8px 82px; }
    .editor-toolbar { bottom: 13px; gap: 0; padding: 4px; }
    .editor-tool { width: 34px; height: 36px; }
    .cursor-theo { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    .editor-page *, .editor-page *::before, .editor-page *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; }
  }
`;
