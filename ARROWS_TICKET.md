# AR-01: Add arrowheads to line shapes

Status: implemented and reviewed on `codex/line-arrowheads`.

Design: [Arrowheads on lines](ARROWS_PLAN.md).

## Outcome

Users can draw or edit a line with an arrowhead at its start, end, both ends, or neither. Arrow settings persist, synchronize between collaborators, and support the existing undo/redo and reconnect behavior.

## Implementation contract

- Retain `kind: "line"`. Add required internal boolean properties `start_arrow` and `end_arrow`. Normalize absent legacy values to false at protocol/storage boundaries. Reject supplied non-booleans and endpoint fields on other shape kinds.
- Keep Line (L). While active, display a compact, labeled panel above the toolbar for drawing defaults. Add independent Start arrowhead and End arrowhead controls to the selected-line inspector.
- Store drawing defaults once in editor state. They last for the editor session. Capture them at pointer-down. Selected-line edits do not change defaults; default changes do not edit a selection. Each selected-line change sends only the property changed.
- Use one SVG line renderer for saved shapes and creation previews; optimistic and move/resize previews use it too. Heads are filled triangles with the line's color and group opacity. Head tips coincide with endpoint handles. Bound head size for short lines and suppress heads for collapsed lines. Preserve shaft/head selection and current board clipping.
- Normalize stored current line properties before collecting inverse values in the durable update handler. The first arrowhead edit to an old sparse line must record false as its inverse and support undo/redo.
- Preserve old pending create retries in both `_operation_replay` and `_operation_collision`. A narrow shared comparison helper treats missing new line-create flags as false on both saved and incoming requests. All other request fields and existing actor/canvas checks remain strict. Explicit true is distinct from false. Do not mutate historical requests/results.
- Reuse existing JSONB storage, shape update messages, property conflict rules, operation journal, and cross-instance delivery. No database migration is required.

## Acceptance criteria

1. Both controls are accessible by name and keyboard. All four settings appear correctly during drawing and after creation. Inspector edits update the selected line optimistically.
2. Start/end identity survives dragging in every direction and moving one endpoint past the other. Color, opacity, move, resize, layering, and deletion retain endpoint settings.
3. Shaft and heads are selectable; endpoint handles remain usable. Short/collapsed lines produce valid SVG geometry. Existing board clipping remains consistent at the edges.
4. Legacy snapshots, operation events, conflict shapes, and replay results load as plain lines. Invalid supplied endpoint values are rejected. First edits to old rows can be undone and redone.
5. Old line-create retries return the saved result through both normal replay and collision handling. A changed true/false flag with the same operation ID is rejected.
6. Independent endpoint patches merge through existing collaboration rules. Same-end stale updates retain the existing conflict behavior. Geometry edits preserve arrow settings.
7. New endpoint values persist through reload and reach a client connected to another backend instance.
8. Existing frontend tests, TypeScript/build checks, backend tests, and applicable lint checks pass. Run real UI checks and PostgreSQL integration checks when local runtimes are available. Record exact skips and gaps.
9. Complete independent bug/security and maintainability reviews with `pstack:thermos`. Resolve accepted findings before completion.

## Delivery

One Luna agent owns implementation on an exclusive feature branch. Parent owns review and live verification after implementation finishes. Keep changes focused and avoid unrelated cleanup. Do not commit, push, or deploy without user authorization.

## Completion evidence

Completed October 27, 2026. A Luna agent implemented the feature and a fresh Luna agent addressed review and browser findings.

- Frontend: `npm test` in `client/` passes 54 tests with zero skips. `npm run build` passes TypeScript and the Vite production build.
- Backend: `.venv/bin/python -m unittest discover -s tests` in `server/`, with `TEST_DATABASE_URL` pointing to an isolated local PostgreSQL database, passes 94 tests with zero skips. Coverage includes an old line's first arrow edit and undo/redo, old create retries, strict values, and endpoint conflict rules.
- Lint: targeted ESLint passes for changed frontend TypeScript files using the enclosing workspace's installed tooling. `.venv/bin/ruff check app tests` and `.venv/bin/ruff format --check app tests` pass. The nested app has no aggregate `verify` script.
- Browser: nine journeys pass through two frontend proxies and separate backend processes against the same isolated PostgreSQL database. Checks cover keyboard controls, all four variants, live previews, selected edits, independent defaults, opposite-end updates, undo/redo, head selection, move/resize, short lines, color/opacity, reload, and layout at 1440x1000 and 1280x800.
- Additional browser checks confirm collapsed persisted lines omit heads and board-edge arrows retain the existing clip behavior. These shapes were seeded through real WebSocket commands before checking the rendered UI.
- `pstack:thermos`: final independent correctness/security and maintainability reviews report no actionable findings. The initial P3 finding about overflow from extreme finite coordinates was fixed and regression-tested. Browser verification also found and verified a fix for the drawing panel's horizontal alignment.
- No-comments gate reports no new comments or suppressions requiring changes. `git diff --check` passes.

Local evidence is under `/private/tmp/relay-arrows-plan/`: `implementation-checks/`, `fix-checks/`, `browser-evidence/`, `final-correctness.md`, and `final-quality/`. The browser runner and setup use isolated local test data; production deployment has not been exercised for this feature.
