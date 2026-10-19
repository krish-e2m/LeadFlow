# Antigravity Prompt — LeadFlow Frontend Visual Redesign Only

Read and follow `LEADFLOW_FRONTEND_DESIGN.md` in this repository as the authoritative implementation specification.

The attached `DESIGN.md` is a visual-design reference for another product. Match its general visual direction as closely as practical—clean, minimal, compact, implementation-oriented UI; restrained monochrome surfaces; subtle borders; blue interactive accents; consistent typography, spacing, radii, and explicit component states—but do not copy the other product's name, logo, brand assets, text, or documentation-site structure. Apply that visual language to LeadFlow's existing B2B SaaS dashboard.

## Absolute scope boundary

**Change frontend presentation only. Do not change functionality.**

Before editing, inspect the actual repository, current frontend routes, shared layouts/components, design tokens, installed UI libraries, and existing tests. Treat the repository code as the source of truth; do not assume a framework version from documentation alone.

Preserve all current:
- route paths and navigation behavior;
- API calls, request/response contracts, query keys, URL parameters, and server actions;
- state management, callbacks, form submission handlers, validation, loading states, error handling, and cache behavior;
- authentication, role-based visibility, route guards, organization/tenant scoping, and protected fields;
- scoring, signal mappings, lead pipeline status transitions, search behavior, approval gates, contact-reveal gates, credit-spending actions, drafting, approval, HubSpot sync, and exports;
- live data and existing business logic.

Do not introduce mock data, fake charts, placeholder buttons, nonfunctional interactions, new backend endpoints, database changes, migrations, API keys, provider changes, package upgrades, or unrelated refactors. Do not weaken or bypass permissions or confirmation gates. Do not edit backend files.

## Implementation approach

1. Inspect the current app and produce a concise list of existing routes/pages and reusable components before changing anything.
2. Find the existing theme/token entry point and extend it rather than creating a parallel design system.
3. Implement the shared theme and application shell first, then update shared controls (buttons, fields, tables, badges, cards, dropdowns, dialogs, tabs, status indicators) and apply them consistently across existing pages.
4. Keep the application compact and information-dense, but preserve readability. Use Inter or the closest existing font setup, semantic theme tokens, consistent spacing and radii, restrained blue accents, muted neutral surfaces, and visible focus states. Use semantic tokens rather than scattered raw hex values.
5. Keep all existing screens and workflow actions. Only reorganize visual layout where it does not alter interaction semantics or remove information.
6. Preserve responsive behavior across desktop, tablet, and mobile. Ensure critical tables, approval controls, and dialogs remain usable on small screens.
7. Preserve correct loading, empty, error, disabled, active, hover, focus-visible, and success states. Use accessible labels for icon-only controls and never rely on color alone to communicate a pipeline state.
8. Follow `LEADFLOW_FRONTEND_DESIGN.md` for page-specific guidance, accessibility requirements, anti-patterns, and QA.
9. Run relevant existing frontend tests, lint, and type checks if available. Do not report checks that were not actually run.
10. Inspect the diff carefully for accidental behavior changes, API-contract changes, backend edits, and removed capabilities.

## Critical workflows to regression-check

Only check routes that actually exist. Preserve their behavior while checking the visual redesign:
- Login and account setup.
- Dashboard and navigation.
- Audience/ICP management.
- Engine configuration and scoring thresholds.
- New search and search progress.
- Lead pipeline filters, bands, and bulk actions.
- Lead detail and evidence.
- Approve/reject and contact reveal.
- Draft generation, editing, approval, and HubSpot sync.
- Client portal and role restrictions.
- Super Admin organization/user/provider controls and audit trail.

## Completion report

When finished, tell me:
- what changed visually;
- which pages and shared components were updated;
- exact files changed;
- commands/checks run and their actual results;
- known gaps or visual issues;
- whether any functionality, API contract, role gate, or backend file was changed unintentionally.

If you discover a conflict between the visual reference and existing functionality, preserve functionality and explain the conflict rather than changing behavior to match the reference.
