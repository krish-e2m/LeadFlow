# LeadFlow Frontend Design System

## Context and goals

### Design intent
Redesign the existing LeadFlow frontend with the same overall visual direction as the supplied Deep Enrich design guide: clean, restrained, compact, implementation-oriented, high-contrast, and consistent. Apply that visual language to a B2B lead qualification dashboard rather than copying the reference product's brand, name, logo, copy, or documentation-site layout.

### Product context
- Product: LeadFlow
- Surface: Existing multi-tenant B2B lead qualification and outreach web application
- Audience: Internal operators, organization admins, client viewers, and super admins
- Main work: Review lead pipeline, inspect scores and evidence, manage audiences and scoring engines, approve leads, reveal contacts, generate and approve drafts, sync approved records to HubSpot, manage organization settings, and view permitted usage/audit information.
- Existing frontend framework and versions: Inspect the repository and use the versions already installed. Do not upgrade dependencies as part of this redesign.

### Non-negotiable scope
This is a **frontend presentation redesign only**. Existing behavior is the source of truth. Do not change backend APIs, request/response schemas, authentication, authorization, route paths, role permissions, data models, scoring rules, provider integrations, quotas, approval gates, credit-spend gates, or pipeline logic. Do not remove capabilities because they are difficult to style. Do not add fake data or new product behavior.

## Visual direction

- Prefer a clean, dark, near-black application shell with restrained neutral surfaces, subtle borders, muted secondary text, and a clear blue accent for links and primary interactive states.
- Keep the interface functional and information-dense without feeling crowded. LeadFlow is an operations dashboard, so prioritize scanability, status clarity, and readable tables over decorative marketing visuals.
- Use a consistent left navigation rail/sidebar on desktop, a clear top bar for page context and account actions, and a central content area. Reuse the existing layout and navigation structure wherever possible.
- Use small, consistent corner radii. Reserve pill-shaped elements for tags, status badges, and intentionally pill-shaped controls.
- Avoid gradients, glassmorphism, heavy shadows, ornamental illustrations, oversized hero sections, random accent colors, and one-off UI styling.
- Do not copy the Deep Enrich brand identity or content. Reuse only the design principles and the broadly described visual language.

## Design tokens and foundations

Implement semantic tokens through the project's existing theme/CSS-variable/Tailwind-token convention. Do not scatter raw color values throughout components. If the project already has a token system, extend it rather than creating a competing one.

Suggested semantic tokens (adapt names to the existing conventions):

### Color tokens
- `--color-bg`: near-black app background.
- `--color-surface`: main content surface, subtly distinct from the background.
- `--color-surface-raised`: menus, dialogs, popovers, and elevated panels.
- `--color-surface-muted`: muted neutral background for grouped content and secondary controls.
- `--color-border`: subtle border for panels, inputs, rows, and dividers.
- `--color-border-strong`: higher-contrast border for selected or focused containers.
- `--color-text-primary`: high-contrast text for titles and body copy.
- `--color-text-secondary`: muted but readable supporting text.
- `--color-text-tertiary`: low-emphasis metadata that must still meet contrast requirements for its rendered size.
- `--color-text-inverse`: text used on accent-filled controls.
- `--color-accent`: restrained blue for links and primary actions.
- `--color-accent-hover`: hover state for accent controls.
- `--color-accent-subtle`: low-emphasis accent background for selected navigation and informational highlights.
- `--color-success`, `--color-warning`, `--color-danger`, `--color-info`: semantic status colors. Never use status colors decoratively.
- `--color-focus-ring`: clearly visible keyboard focus color.

Start from the reference's black base (`#000000`), muted surface (`#f5f5f5`), slate-like secondary text (`#626f86`), and blue interaction accents (`#0000ee` / `#3069b0`) only as directional input. Adapt the final token values to maintain contrast and avoid raw values in component styles. Use a deliberate, cohesive dark theme rather than applying these example values mechanically where they cause poor contrast.

### Typography
- Primary font: `Inter`, with system fallbacks: `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`.
- Body text baseline: 14–16px on the application; do not make essential dashboard content smaller than comfortably readable text.
- Compact metadata may use 12–13px only where contrast is sufficient.
- Use a consistent typographic scale for page title, section title, body, labels, input text, helper text, and metadata.
- Base line height should be around 1.5 for paragraph/body content; use tighter line height for compact table cells and headings where appropriate.
- Use weight and spacing to create hierarchy rather than excessive font-size variation.
- Keep numbers, scores, percentages, dates, and costs aligned and easy to compare; use tabular numerals where supported.

### Spacing, radius, and elevation
- Base spacing unit: 4px.
- Preferred spacing steps: 4, 8, 12, 16, 20, 24, 32px. Use these consistently; avoid arbitrary one-off values.
- Small control/panel radius: 8px.
- Standard panel radius: 10–12px if already consistent with the codebase.
- Pill radius: fully rounded only for badges and intentionally pill-shaped controls.
- Motion: quick, subtle transitions around 150–250ms. Respect `prefers-reduced-motion`.
- Use borders and tonal surface differences first; shadows must remain subtle and purposeful.

### Layout
- Desktop: persistent sidebar/navigation, top bar, and flexible main content area.
- Tablet: collapsible sidebar or existing responsive navigation pattern; preserve access to every existing route/action.
- Mobile: stack layouts, allow table-to-card or horizontally scrollable table behavior where needed, make dialogs fit the viewport, and prevent clipped controls.
- Keep page content width and padding consistent across routes. Do not force long operational tables into narrow layouts.
- Keep the main workflow visible above the fold when practical, but do not remove fields or information to achieve this.

## Application shell

### Sidebar/navigation
- Use a restrained dark navigation surface and clear active-route indicator.
- Group related existing routes into meaningful navigation sections without changing paths or permissions.
- Use icons consistently and pair them with accessible labels. Icons must not be the sole label for critical actions at narrow widths unless an accessible name is provided.
- Active, hover, focus-visible, collapsed, and mobile states must be implemented.
- Do not display links/routes to roles that are not allowed to access them. Preserve existing role-aware navigation and server-side/API authorization assumptions.

### Top bar
- Display the current page title/breadcrumb where supported by existing routing.
- Preserve existing organization switcher, account controls, notifications, or context controls if they exist.
- Do not introduce fake search, notifications, user information, or controls that have no working behavior.
- Dropdowns must support keyboard operation and escape-to-close where appropriate.

### Page headers
- Use consistent page title, supporting description where currently available, and right-aligned primary actions where appropriate.
- Keep actions descriptive and consistent. Destructive and credit-consuming actions must not be visually conflated with ordinary navigation.

## Component-level rules

Every interactive component must define and implement default, hover, focus-visible, active, disabled, loading, and error behavior where applicable. If a state does not apply to a component, document why rather than silently omitting it.

### Buttons
- Variants: primary, secondary, subtle/ghost, danger, and icon-only only where needed by existing functionality.
- One clear primary action per local action group where practical.
- Loading state must prevent accidental duplicate submissions and preserve a clear progress label.
- Disabled state must remain legible and must not appear clickable.
- Icon-only buttons require accessible names and a tooltip when the meaning is not obvious.
- Keyboard: native button semantics; Enter/Space activation; visible focus.
- Pointer/touch: comfortable hit target, ideally around 40–44px for key controls.

### Links
- Use the semantic accent color and visible hover/focus states.
- Do not style ordinary text as a link when it is not interactive.
- Focus indicators must not rely only on color changes.
- External links must retain their existing destinations and semantics.

### Inputs and forms
- Labels must be visible and programmatically associated with controls.
- Helper text and validation messages must remain associated with the relevant input.
- Include default, hover, focus-visible, active, disabled, loading/submitting, and error styles.
- Do not clear user-entered values after validation errors unless existing behavior explicitly requires it.
- Preserve validation rules, field names, form submission handlers, and backend payloads.
- Support keyboard navigation, proper tab order, and mobile touch interaction.

### Tables and lead lists
- Keep tables compact but readable and aligned. Avoid excessive cell padding or tiny text.
- Preserve existing columns, sorting, filtering, pagination, row actions, selection, and bulk-action logic.
- Use a stable status/band treatment for sourced, enriched, scored, review, qualified, approved, drafted, synced, disqualified, and archived states according to existing statuses.
- Status badges must include text; never communicate status by color alone.
- Long company names, domains, email addresses, and evidence must wrap or truncate with a way to inspect the full value.
- Empty states must explain what is empty and show an existing next action only if that action is actually available.
- Loading states should preserve layout and indicate progress. Error states must support retry only if the existing interface supports retry.
- On mobile, use an existing responsive table pattern, controlled horizontal scrolling, or a card layout that preserves all key fields and actions. Do not drop actions silently.

### Cards, metrics, and dashboard summaries
- Use consistent surface, border, padding, and heading rules.
- Avoid exaggerated KPI cards. Prioritize readable metrics and contextual labels.
- Preserve current API-backed counts and calculations. Do not hardcode illustrative numbers.
- Distinguish zero from loading, unavailable, and error states.

### Tabs, filters, dropdowns, and pagination
- Preserve current selected values and state behavior.
- Include focus-visible, selected, disabled, empty, and loading states as applicable.
- Multi-select filters, clear/reset controls, and AND/OR/exclude behavior must retain their present semantics.
- Menus/dialogs must work with keyboard, pointer, and touch; handle escape and outside-click according to the existing component/library convention.

### Dialogs and confirmations
- Use consistent dark surfaces, borders, spacing, and readable action hierarchy.
- Preserve all existing confirmation gates for contact reveal, drafting, syncing, exports, and other consequential actions.
- Credit-spending or destructive actions must clearly state the action and relevant warning using existing data; do not invent cost estimates.
- Trap focus appropriately, return focus to the triggering element after close, and prevent controls from being clipped on smaller screens.

### Lead detail and score evidence
- Preserve current score, band, ideal-client indicators, website/marketing breakdowns, evidence, provenance, missing-signal indication, and actions.
- Show unavailable/missing data distinctly from a real zero score.
- Keep detailed evidence readable, with long content expandable or otherwise inspectable.
- Do not modify score computation, weights, thresholds, or server data.

### Draft Studio
- Preserve current subject/body editing, tone selection, regeneration, approval, and HubSpot-sync behavior.
- Use a clear editor layout and separate the editable content from metadata/cost information where already available.
- Maintain confirmation and disabled/loading states. Do not enable an action that is currently blocked by workflow state.

### Client portal, operator mode, and administration
- Preserve role-specific visibility and route guards.
- A client viewer must not gain visibility into costs, disqualified leads, unrevealed personal information, exports, audit/provider administration, or other organizations just because the UI is redesigned.
- Keep the operator-enabled distinction intact.
- Preserve organization lifecycle controls, quotas, user management, provider status, and audit access only for roles that currently have them.

## Interaction and state contract

- Existing code, API calls, component state, server actions, query keys, route paths, URL parameters, and form payloads are authoritative.
- Styling changes must not alter event handlers, loading flows, optimistic updates, cache invalidation, error propagation, permission checks, or workflow order.
- Do not rename exported components or public props unless strictly necessary and fully traced; prefer adapting class names, tokens, and layout wrappers.
- Do not replace working components with static mockups.
- Do not add fake buttons, fake tables, placeholder charts, invented sample leads, or interactions that only look functional.
- Do not change global dependencies, framework versions, or package configuration for visual polish alone.
- Do not edit backend files as part of this task.

## Accessibility requirements and testable acceptance criteria

Target WCAG 2.2 AA where applicable.

- Text and interactive controls must meet minimum contrast requirements; verify normal text contrast of at least 4.5:1 and large text at least 3:1.
- Keyboard users must be able to reach and operate every interactive control in a logical order.
- Every keyboard-operable interactive element must have a visible focus indicator that is not obscured.
- Inputs must have accessible names, labels, and understandable validation errors.
- Status and pipeline states must not rely on color alone.
- Dialogs and popovers must have correct semantics and keyboard behavior.
- Use semantic heading hierarchy and landmark structure.
- Images/icons that convey meaning need accessible alternatives; decorative icons should be hidden from screen readers.
- Test at narrow mobile width, tablet width, and desktop width. No horizontal page overflow, clipped primary actions, or inaccessible off-screen controls.
- Respect reduced-motion preferences.
- Automated accessibility checks are useful but do not replace keyboard and visual checks.

## Content and tone standards

- Use concise, direct, action-oriented language consistent with the existing product terminology.
- Preserve existing labels where they correspond to domain concepts or API/workflow semantics.
- Use sentence case for controls and headings unless current product conventions differ.
- Make destructive and credit-spending actions explicit.
- Use date, currency, percentage, and score formatting consistently.
- Avoid generic placeholder text and invented business data.

## Anti-patterns and prohibited implementations

- Do not change business logic, API integration behavior, authentication, authorization, or data models.
- Do not replace live data with mock data or change real data into static preview values.
- Do not silently remove table columns or actions to make the page look cleaner.
- Do not use low-contrast muted text, hidden focus indicators, or color-only statuses.
- Do not use a different spacing or typography value for every component.
- Do not add gratuitous gradients, excessive animation, decorative charts, or oversized marketing-style hero sections.
- Do not duplicate existing navigation, toasts, modals, tables, or design-system components.
- Do not weaken confirmation gates or show protected information to unauthorized roles.
- Do not make unrelated refactors while redesigning the interface.

## Migration notes

1. Inspect the actual current frontend, framework version, routes, components, theme, and installed component libraries before editing.
2. Identify reusable shared shell/layout and theme entry points.
3. Implement semantic tokens centrally.
4. Update shared components first, then apply the theme consistently to existing pages.
5. Keep changes scoped to frontend files.
6. Review critical workflows after styling changes: login/setup, dashboard, audience creation, engine configuration, search start, pipeline filtering, lead detail, approve/reject, contact reveal, draft creation/approval, HubSpot sync, client portal, and admin controls where those routes exist.
7. Do not change underlying workflows to fit the design; adapt the design to existing behavior.
8. If the repository's actual structure differs from handbook assumptions, follow the repository and report the discrepancy.

## QA checklist

- [ ] Existing routes and navigation still work.
- [ ] All current actions and event handlers remain connected.
- [ ] Existing API calls and request/response schemas are unchanged.
- [ ] Authentication, role guards, and tenant boundaries are unchanged.
- [ ] Contact reveal, generation, approval, sync, and export gates are preserved.
- [ ] Existing live data remains live; no mock data was introduced.
- [ ] Loading, empty, error, disabled, and success states remain understandable.
- [ ] Dark theme tokens are consistent across every existing screen.
- [ ] Typography, spacing, borders, buttons, inputs, tables, badges, menus, and dialogs use shared tokens.
- [ ] Responsive layouts work at desktop, tablet, and mobile sizes.
- [ ] Keyboard navigation and focus-visible states work.
- [ ] Contrast and accessible names have been checked.
- [ ] No console errors, broken imports, or new dependency changes.
- [ ] Relevant frontend tests, type checks, and lint checks pass where available.
- [ ] Final report lists changed files, checks run, test results, and any known issues.

## Required completion report

After implementation, report:
1. Design changes completed.
2. Routes/pages updated.
3. Shared tokens/components added or reused.
4. Files changed.
5. Tests, lint, and type checks run with actual outcomes.
6. Any visual or functional issues left unresolved.
7. Explicit confirmation that backend, API contracts, permissions, data flow, and business logic were not intentionally changed.
