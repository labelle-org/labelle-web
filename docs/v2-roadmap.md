# labelle-web v2 — Iterative UI Overhaul

> **Status: open brainstorm, not a committed plan.** This document is an
> in-progress draft of where v2 *might* go. Directional choices (especially the
> template-first homepage thesis in Phase 2) are explicitly up for discussion
> with labelle-org and other contributors before any code lands. Feedback and
> redirection are welcome — open an issue or comment on the umbrella issues below.

## Why v2

v1's UI is a competent web port of the original labelle desktop GUI. v2 is exploring whether a **mobile-first polish** of what we already have — followed by an optional shift toward a more **template-first** experience — would be a better fit for how the tool is actually used. Both halves of that are exploratory, with the mobile-first improvements being the firmer commitment and the template-first shift being the genuinely speculative part.

### Relationship to upstream labelle

This project now lives under [labelle-org](https://github.com/labelle-org) as `labelle-org/labelle-web`, the org's web frontend for [labelle](https://github.com/labelle-org/labelle) (transferred 2026-05-22; first release on the new namespace was v1.7.0). It ships today and has hardware in regular use — a Raspberry Pi appliance accessed primarily from a phone.

Being inside the org doesn't make the v2 *direction* settled. Mobile-first polish (Phase 1) is the firmer commitment; the template-first thesis (Phase 2) is one possibility being evaluated, not a destination — input from labelle-org maintainers and other users would be valuable before committing to the larger Phase 2 slices, especially the 2.5 homepage flip.

## Sequence

**Phase 1 first, Phase 2 only if it makes sense after Phase 1 lands and the direction has been validated.** Each slice is **independently mergeable** and ships to `main` with a SemVer bump — no long-lived branches, no big-bang switchover. The most speculative slice (2.5, template-first homepage) would become a v2.0.0 cutover *if* we go that way; it's the one most likely to be reshaped or dropped after discussion.

Tracking lives in the `labelle-web v2` project; phase progress is tracked via these umbrella issues:

- **Phase 0** — [#27](https://github.com/labelle-org/labelle-web/issues/27): quick wins
- **Phase 1** — [#28](https://github.com/labelle-org/labelle-web/issues/28): mobile-first polish
- **Phase 2** — [#29](https://github.com/labelle-org/labelle-web/issues/29): template-first transition

---

## Phase 0 — Quick wins

Small, foundational improvements that later mobile-first slices will lean on. No architectural change.

### 0.1 — Roomier text editor + variable hint
- Bump `TextWidgetEditor` textarea to `rows={3}` minimum with `field-sizing: content` (auto-grow).
- Add a subtle helper line listing detected variables for that widget (seeds variable awareness ahead of templates).
- Widen the scale input.
- **Done when**: a 3-line label typed in a phone-width window shows all 3 lines without internal scroll.

### 0.2 — Tailwind breakpoint baseline
- Introduce `sm:` and `md:` usage in `App.tsx` plus a short comment in `index.css` documenting intent.
- No visual change yet — establishes the grid every later mobile slice will reach for.
- **Done when**: at least two of `sm:` / `md:` / `lg:` are referenced; visual regression set unchanged.

### 0.3 — Touch-target audit
- Raise `.btn` and `.input` minimum hit area to 44 px effective height on touch.
- Apply to the small ✕ delete, drag handle ⠿, EyeIcon (14×14) in BatchPanel, refresh ↻.
- Keep desktop density via responsive padding.
- **Done when**: Lighthouse mobile + manual check shows nothing below 44×44 CSS px.

---

## Phase 1 — Mobile-first polish

Preview stays visible while editing, settings/batch become sheets on mobile, the batch table becomes touch-friendly, and the first new widget (Spacer) validates the widget-add pipeline before Phase 2 leans on it.

### 1.1 — Sticky preview + sticky print bar (M)
- Restructure `App.tsx` so the preview stays visible while editing on mobile.
- `PrintButton` becomes a sticky bottom action bar on mobile.
- Desktop two-column layout preserved via `lg:` ordering.
- **Done when**: on 390×844 the live preview is visible while typing in any widget editor.

### 1.2 — Settings + Batch as bottom sheets (M)
- Replace inline `<details>` with a bottom-sheet/drawer pattern below `md:`.
- Above `md:` keep current inline behavior.
- Build one reusable `<Sheet>` primitive (native `<dialog>` + ~50 LOC; no library).
- Settings sheet groups: Tape & layout / Colors / Printer.
- **Done when**: on mobile both Settings and Batch open as full-width sheets with a clear close affordance; desktop unchanged.

### 1.3 — Mobile-friendly Batch table (M)
- Below `md:`, render each batch row as a stacked card (one input per variable per row) instead of a horizontal-scrolling table.
- Promote per-row delete + preview-eye to tappable icons.
- Above `md:` keep the table.
- **Done when**: 390 px viewport with 3 variables × 4 rows has no horizontal scroll and no input overlap.

### 1.4 — New widget: Spacer / divider (M)
- New `SpacerWidget` type with `widthPx` and `style` (blank / vertical-line / dotted).
- Tiny editor (slider + style toggle).
- Backend: render with a small new render engine. Start with a 30-min spike to confirm labelle accepts a raw bitmap engine or we drop in a thin one.
- Validates the widget-add pipeline end-to-end as a stepping stone for Phase 2 widgets.
- **Done when**: `[Text][Spacer 20px][QR]` shows a clear gap and round-trips through save/load.

### 1.5 — PWA polish (S)
- Maskable icon variants, mobile chrome theme match, dismissible "add to home screen" hint on first mobile visit.
- Honest offline state in `LabelPreview` when the server is unreachable (NetworkFirst SW falls back gracefully).
- **Done when**: app installs to iOS/Android home screen, opens standalone, shows a recognisable offline state if the Pi is down.

---

## Phase 2 — Template-first transition *(speculative)*

The thesis under evaluation: **if** repetitive labeling (asset tags, name badges, jar labels) is a significant share of how this tool is used, a template-first experience would make a lot of mobile flows much faster. The maintainer's own use is closer to one-off labels, so this thesis is genuinely uncertain — open to reshaping based on labelle-org input and user feedback. Phase 1 stands on its own regardless of whether Phase 2 happens.

Within Phase 2, slices 2.1–2.4 (server-saved templates, gallery as a route, sequence + date widgets) are useful features even *without* the homepage flip. Only 2.5 (template-first home) is the speculative big swing.

### 2.1 — Save labels to server, SQLite-backed (M)
- `GET/POST/DELETE /api/templates`, `GET /api/templates/:id`.
- Storage: SQLite (`templates.db` alongside the existing `LABELLE_STATE_FILE` directory). `sqlite3` is stdlib — no new dep.
- Schema (v1):
  ```
  templates(
    id TEXT PRIMARY KEY,           -- uuid
    name TEXT NOT NULL,
    description TEXT,
    body_json TEXT NOT NULL,       -- v2 label JSON, reuses labelFile.ts format
    favorite INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_printed_at INTEGER
  )
  ```
- Wrap CRUD in a tiny `server/templates_store.py` mirroring the shape of `printer_settings.py`. First call creates the table; future schema bumps use `PRAGMA user_version` + additive migrations.
- Add "Save to library" alongside the existing "Save to file" in `SaveLoadButtons` — not a replacement.
- **Done when**: user saves the current label as a named template, refreshes the page, fetches it back via API.

### 2.2 — Template gallery as a route (M)
- Add lightweight client-side routing (React Router recommended for shareable template URLs).
- `/` = current designer (unchanged for now), `/templates` = gallery with server-rendered thumbnails.
- Tap → load into the designer (`/?template=:id`).
- Mobile tab bar / desktop top nav.
- **Done when**: visiting `/templates` shows template thumbnails; tap loads into the designer.

### 2.3 — New widget: Sequence number (M)
- `SequenceWidget` with `start`, `step`, `padding` (e.g. `04d` → `0001`), `prefix`, `suffix`.
- Single-print mode: current value. Batch mode: increments per output label.
- Establishes the "resolved-at-print-time" pattern that 2.4 reuses.
- Cancellation behavior: if a batch is cancelled mid-run, the sequence restarts from `start` on the next run (documented as the chosen behavior).
- **Done when**: template with one sequence widget prints `Asset-0001`…`Asset-0050` on 50 sequential labels.

### 2.4 — New widget: Date stamp (S)
- `DateWidget` with `format` (ISO, dd-mm-yyyy, etc.) and `offsetDays` (e.g. "today + 90" for expiry).
- Resolved server-side at print time. Editor previews "as printed today".
- **Done when**: label with `Date(today+30, dd-mm-yyyy)` prints today's date plus 30 days.

### 2.5 — Template-first home + variable fill view (L, **breaking**, *most speculative slice*)

This is the speculative big swing. It may not happen; an alternative shape is to keep the designer at `/` and surface templates prominently from there. Direction here will be reshaped based on feedback before commitment.

- `/` would render the gallery; designer moves to `/design`.
- "New blank label" on the gallery for from-scratch users.
- Templates with variables → a "fill" sheet (reuses 1.2 sheet primitive + 1.3 stacked-row UI) → print without entering designer.
- "Edit template" affordance for tweaks.
- URLs: `/t/:id` (fill), `/t/:id/edit` (designer-with-template-loaded).
- If we go this way, this PR is the v2.0.0 cutover. Major bump.
- **Done when** (if pursued): first-time mobile user lands on `/`, taps a name-badge template, fills "Alice", and prints — never seeing the widget list.

---

## Open questions

0. **Is the template-first thesis right at all?** Big one. DYMO Connect / Brother P-touch open to template galleries because commercial users skew repetitive, but this project's primary maintainer use is one-off labeling — closer to designer-first. Phase 2.5 might be the wrong destination; templates as a feature alongside the designer may be the right answer. Input from labelle-org and other users would be valuable before committing.
1. **Routing library (2.2)** — React Router (~10 KB gzipped, full URL support including shareable template links) vs. TanStack Router (~35 KB but fully type-safe params/search and route-level loaders) vs. a 30-line hash router. Leaning React Router for the app's size, but happy to be persuaded.
2. **Spacer widget render path (1.4)** — labelle's render engines may not have an "empty space" primitive. 30-min spike before starting 1.4 to confirm we extend the engine list cleanly or fake it via a transparent text engine.
3. **PWA offline ambition (1.5)** — server-side render means an unreachable Pi can't show a preview. Current preference: keep server-side render, surface offline state honestly. Client-side render is significantly more work and changes the trust model (different rendering = different output).

---

## Verification (per slice)

- `npm run build -w client && npm run test -w client` and `.venv/bin/python -m pytest server/tests/` green after each change.
- Manual smoke at 390×844 (phone), 768×1024 (tablet portrait), 1280×800 (laptop) for any slice tagged `mobile`/`responsive`.
- Hardware print test on hector (the Raspberry Pi deployment) for any slice touching the print pipeline (1.4, 2.3, 2.4).
- For 2.x slices that touch the API, hit each endpoint with `curl` against a dev server before wiring up the UI consumer.

End-to-end smoke after 2.5: fresh browser on a phone → land on `/` → see template gallery → tap a template → fill values → print. No widget list ever shown.
