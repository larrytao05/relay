# Arrowheads on lines

Status: implemented and reviewed locally on `codex/line-arrowheads`. See [AR-01 completion evidence](ARROWS_TICKET.md#completion-evidence).

## User experience

Keep **Line (L)** as the drawing tool. While it is active, show a compact **Line ends** panel above the drawing toolbar. It has two independent switches, **Start arrowhead** and **End arrowhead**. Both start off.

These switches cover all four appearances:

- Both off produces a plain line.
- End on produces an arrow pointing toward the end.
- Start on produces an arrow pointing toward the start.
- Both on produces a line with an arrowhead at each end.

Start is where the user presses down. End is where the user releases. These identities stay attached to their endpoints when a line points left, points up, or one endpoint moves past the other.

The drawing preview shows the chosen arrowheads. Drawing settings last for the current editor session and apply to subsequent lines. Capture these settings when drawing begins.

When the user selects an existing line, show the same two switches under **Line ends** in the inspector. Those switches edit the selected line immediately through the existing optimistic update flow. Selection edits do not change drawing defaults. Changes to drawing defaults do not edit a selected line. Keep each context labeled and keyboard accessible.

Arrowheads use the line's color and opacity. The existing move, endpoint resize, layer order, delete, undo, and redo actions continue to work. Arrow tips coincide with the endpoint handles.

## Data model

Keep the persisted shape kind as `line`. Extend its properties with independent booleans:

```ts
type LineArrows = {
	start_arrow: boolean;
	end_arrow: boolean;
};
```

`LineProperties` includes both fields. Internal line shapes always have explicit booleans. Older wire payloads and stored rows may omit them; omission means `false`. Supplied values must be booleans. Other shape kinds reject these properties.

Independent fields fit the existing property conflict rules. Updating one endpoint sends only that property. Two collaborators can edit opposite arrowheads independently. Same-property edits retain the existing conflict policy.

## Frontend changes

- `client/src/editor/types.ts` extends `LineProperties`, editor drawing defaults, and the line creation variant of `Interaction`. Arrow settings belong only to line creation interactions.
- `client/src/editor/reducer.ts` owns drawing defaults alongside the existing tool and color defaults. A settings action updates those defaults.
- `client/src/EditorPage.tsx` captures defaults at pointer-down, includes them in created and optimistic line shapes, and sends selected-line endpoint changes as ordinary `shape.update` commands.
- `client/src/components/editor/EditorToolbar.tsx` displays the drawing options panel while Line is active. `SelectionInspector.tsx` displays selected-line controls. Both receive controlled values and callbacks; they do not maintain copies of the defaults.
- `client/src/components/editor/EditorStage.tsx` uses one shared line renderer for saved lines, creation previews, optimistic shapes, and move/resize previews. Extract a small renderer file so head geometry has one implementation.
- `client/src/editor/protocol.ts` parses and preserves both fields, defaults missing values to false, and rejects malformed values. This covers snapshots, operation events, conflict shapes, and historical replay results.
- `client/src/EditorPage.css` styles the drawing options and inspector controls. Update existing line fixtures for the required internal fields.

The existing geometry transforms spread line properties, so they should preserve arrowheads. Verify those paths rather than introducing arrow-specific move or resize operations.

## Rendering behavior

Draw the shaft and filled triangular arrowheads in the same SVG group. A shared renderer calculates head direction from the endpoint coordinates and applies opacity once to the group. Head tips stay at the endpoints, with their bodies extending inward along the shaft.

Use a bounded head size that shrinks for short lines. When endpoints coincide after resize, suppress arrowheads to avoid invalid geometry. Preserve the existing generous shaft hit target and make the visible head area selectable. Keep endpoint handles usable above the drawing. Retain the board's current clipping behavior and check all edges visually.

## Backend and compatibility

`server/app/canvas_protocol.py` accepts and validates the two fields for lines. Missing values default to false when forming complete line properties.

In `server/app/canvas_ws.py`, normalize current stored line properties before recording `before_patch`. That step matters because old rows lack these keys. Without it, the first arrowhead edit can fail while the server collects inverse values. The resulting inverse must explicitly restore false so undo works on an old plain line.

Preserve retries across deployment. Create commands are normalized before their request is recorded, and retry handling compares that request with the saved request. New defaults would otherwise make an old pending create appear different. Use one narrow request comparison helper in both `_operation_replay` and `_operation_collision`. For line creates, it treats omitted arrow fields as false on both sides, while preserving all other comparisons and actor/canvas checks. Explicit true must remain different from false. Leave historical request and result records intact.

No new SQL columns, shape-kind constraint, or migration is needed. Properties already live in JSONB. Normalize legacy values at the relevant boundaries rather than relying on a one-time backfill. The operation journal, PostgreSQL notifications, and cross-instance replay already carry shape properties. Undo/redo uses the existing inverse patches.

Deploy backend support before exposing the controls to users. Existing browser tabs need a refresh to render arrowheads; active connections to an old backend need to reconnect to the updated version before editing shapes with the new properties.

## Implementation sequence and acceptance

1. Add protocol fields and legacy defaults. Cover first edits to old lines, inverse recording, and old pending create retries in both retry paths.
2. Add the shared renderer and verify all four combinations, preview consistency, every direction, short/collapsed lines, color, opacity, head clicks, endpoint handles, and board edges.
3. Wire drawing defaults and selected-line controls. Verify that each affects only its intended context and sends only the changed endpoint field.
4. Exercise two clients, including different backend instances. Confirm persistence after reload, undo/redo, retry after interruption, opposite-end merging, geometry edits concurrent with arrow changes, and existing same-field conflict behavior. Run relevant typecheck, tests, and lint checks.

This is one focused implementation ticket followed by an independent review.

## Design choice

The design comparison favored choosing arrowheads before drawing and editing them afterward. An inspector-only design required users to draw a plain line first. The chosen plan adds drawing defaults while retaining the existing line model and tool.

Separate endpoint booleans keep patches independent. A single four-value arrow mode would make opposite-end edits contend for the same property. A separate stored arrow shape kind would duplicate line geometry and persistence behavior.

Required internal booleans follow Type System Discipline. Legacy optionality stays at the protocol and storage boundaries, so rendering and editor code receive complete line properties.

## Implementation reconciliation

The pure `lineArrowheadPoints` geometry helper lives in `client/src/editor/geometry.ts` so finite, short, collapsed, reversed, and extreme-endpoint behavior can be covered in the existing geometry tests. `LineRenderer` delegates head calculations to that canonical helper. The line options panel uses the toolbar's same horizontal anchor in both the default and narrow responsive layouts.
