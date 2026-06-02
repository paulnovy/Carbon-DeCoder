# Application Flow Model

Last updated: 2026-06-01.

This document is the working model for the next UI rebuild. It is not a visual design spec yet; it defines navigation, project/run state, module ownership, and data-loading rules so implementation slices stay coherent.

## Tooling Notes

Current frontend stack:

- Next.js `15.5.18` with App Router.
- React `18.3.1`.
- Tailwind CSS `4.2.4`, with much of the UI still using local CSS/custom components.
- `igv` / igv.js `3.8.0` for genome browser behavior.

Docs checked for future implementation:

- Next.js App Router routing, layouts, and navigation:
  - https://nextjs.org/docs/app/building-your-application/routing/defining-routes
  - https://nextjs.org/docs/13/app/building-your-application/routing/linking-and-navigating
  - https://nextjs.org/docs/app/api-reference/file-conventions/layout
- React state/context:
  - https://react.dev/reference/react/createContext
  - https://react.dev/reference/react/useContext
  - https://react.dev/reference/react/hooks
- Tailwind CSS:
  - https://tailwindcss.com/docs/installation
  - https://tailwindcss.com/docs/upgrade-guide
- igv.js:
  - https://github.com/igvteam/igv.js/wiki

Implementation rule: check the relevant official docs again before changing framework-level routing/layout/state patterns.

## Navigation Model

Sidebar target order:

1. Dashboard
2. Wizard
3. Projects
4. Runs
5. Variants
6. Coverage
7. SV / CNV
8. Taxonomy
9. mtDNA
10. PRS
11. Insights
12. Genome Browser
13. Reports
14. Benchmark, disabled, with `EXPERIMENTAL`
15. Dark Matter, disabled, with `EXPERIMENTAL`
16. Settings

Removed from sidebar:

- Data Import
- References

New empty route:

- `/wizard`
- First implementation can be a blank shell with page title only.
- It belongs directly under Dashboard in the sidebar.

## Global Project And Run State

Projects becomes the primary state control surface for the app.

Global selection:

- `selectedProjectId`
- `selectedRunId`
- `selectedSampleId`, derived from selected project/run when possible

Expected behavior:

- Selecting a project changes the data scope for the rest of the app.
- Selecting a run inside that project changes the run-scoped data used by analysis screens.
- Other pages should not silently fall back to the first project/run if a global selection exists.
- Changing the selected project or selected run never interrupts backend runs.
- A running backend job remains owned by its run/project regardless of what the operator is viewing.
- If any run is active where the backend should prevent concurrent starts, the operator may inspect other projects but run-start controls must be disabled with clear state.

Implementation preference:

- Add a small app state provider rather than duplicating project/run selection in every page.
- Persist the latest selection in local storage only as UI convenience.
- Validate selected IDs against API responses on page load; stale local storage must not create phantom state.
- Keep backend run lifecycle as the source of truth for run status.

## Project Creation And Data Import

Data Import moves into Projects.

Target behavior:

- Project creation becomes a guided workflow inside `/projects`.
- Data import is a step in creating or preparing a project, not a standalone sidebar destination.
- Existing `/data-import` may remain temporarily as an internal route during migration, but it should not appear in sidebar.
- Final state should either redirect `/data-import` to Projects or remove the route once all flows are migrated.

Project page additions:

- Project list with visually prominent project names.
- Rename project action.
- Current project/run selection controls.
- Create project flow with data import step.
- Active run state indicators.

## Settings Model

Settings moves to top tabs.

Initial tabs:

- General
- Pipeline
- References
- Taxonomy Databases
- Runtime Capabilities
- Safety / Non-Diagnostic

References moves into Settings:

- `/references` disappears from sidebar.
- Reference management appears as the References tab in `/settings`.
- Existing reference APIs and data model remain unchanged during the UI move.

Runtime capabilities:

- Keep manual/on-demand loading.
- Do not reintroduce `/data/capabilities` into initial Settings load.

## Module Cleanup Rules

Variants:

- Remove mock/sample data.
- If no real variant calls exist for the selected project/run, show empty state.
- Empty state must not imply failure if the run simply has no produced variant data.

SV / CNV:

- Remove mock/sample data.
- If no real SV/CNV data exists for the selected project/run, show empty state.

PRS:

- Remove mock/sample data.
- Current known state: alignment was done to GRCh38, while PRS resources expect GRCh37.
- Until liftover/build compatibility is explicit, PRS should report non-ready/no interpretable data instead of fake scores.

Insights:

- Remove current content.
- Rebuild as top tabs.
- First working tab: ClinVar.
- ClinVar catalog should use the downloaded/local catalog if present.
- Do not bring back old monogenic/traits/overview behavior until each tab has a real data contract.

Benchmark:

- Disable in sidebar.
- Show `EXPERIMENTAL` sublabel.
- Route can remain for direct access during development, but sidebar should be non-clickable.

Dark Matter:

- Disable in sidebar.
- Show `EXPERIMENTAL` sublabel.
- Route can remain for direct access during development, but sidebar should be non-clickable.

## Coverage Model

Remove current low-signal metrics:

- `coverage anomalies detected`
- `bins overlap reference masks`
- `Median Coverage`
- `Callable`
- `>=10x`
- `>=20x`
- `>=30x`

Add tiles:

- Unexpected low coverage
- Unexpected no coverage

Interpretation:

- These tiles should be based on explicit expected coverage context, not generic threshold badges.
- If the backend does not yet expose enough data to classify unexpected regions, show empty/unknown rather than invented findings.

Coverage terrain map:

- Chromosome visual width should follow relative chromosome length.
- Bins should represent a consistent genomic resolution.
- The same bin resolution should produce visually consistent rectangles across chromosomes.
- Centromeres and comparable known low-mappability/reference mask regions should create visible constrictions or interruptions.
- The purpose is mental localization on the chromosome, not decorative heatmap density.

Implementation notes:

- Prefer a small reference cytoband/centromere metadata contract over hard-coded SVG decoration.
- Keep render stable on desktop and mobile; chromosome labels must not overlap map tiles.

## Data Loading Rules

All analysis screens should follow the same loading hierarchy:

1. Resolve global project/run/sample selection.
2. Load only data scoped to that selection.
3. Load heavy diagnostic/probe data only on demand.
4. Use DB query-layer-first endpoints for large result sets.
5. Paginate large rows server-side.
6. Do not fabricate mock results when real data is absent.

Existing validated pattern:

- Taxonomy rows are now DB query-layer-first with server pagination.
- This pattern should be reused for variants and other large result tables.

## Suggested Implementation Slices

1. Sidebar and placeholder Wizard
   - Add `/wizard`.
   - Reorder sidebar.
   - Hide Data Import and References.
   - Disable Benchmark and Dark Matter with `EXPERIMENTAL`.

2. App selection state
   - Add project/run selection provider.
   - Make Projects the selection control page.
   - Persist and validate selection.

3. Projects workflow
   - Rename project.
   - Move Data Import into project creation/preparation.
   - Keep backend runs uninterrupted by view-state changes.

4. Settings tabs
   - Convert Settings to top tabs.
   - Move References UI into Settings.
   - Preserve on-demand runtime capabilities.

5. Remove mock data
   - Variants.
   - SV / CNV.
   - PRS.

6. Coverage cleanup
   - Remove low-signal metrics.
   - Add unexpected low/no coverage tiles.
   - Rework terrain map proportions and centromere constrictions.

7. Insights rebuild
   - Remove current Insights content.
   - Add top tabs.
   - Implement ClinVar first.

## Acceptance Checks

Before a slice is complete:

- `npm run build` passes.
- Changed route has browser smoke.
- Sidebar does not expose removed/disabled destinations incorrectly.
- Project/run selection state is visible and consistent after navigation.
- No route falls back to mock data.
- API requests stay scoped to the selected project/run.
- No `localhost:8000` API requests appear in browser timings.
- Runtime deploy on remote host uses `docker-compose.yml` plus `docker-compose.remote.yml`.
