# Project Recovery Frontend and QA Rounds Design

**Status:** Approved direction  
**Date:** 2026-08-13  
**Product:** Project Recovery  
**Target:** Existing Chainlit + FastAPI/Jinja application deployed to Azure App Service

## Purpose

Improve the existing application through repeated local and production QA rounds while preserving the proven backend, persistence, authentication, OpenAI Agents SDK integration, and Azure architecture.

The governing product principle is 80/20: fix the interface and workflow problems that materially affect ordinary users, accessibility, and operations without rebuilding Chainlit, introducing a second frontend application, or creating a new design system dependency.

## Approved Approach

Use a unified workspace shell implemented through the application's existing extension points:

- Chainlit remains the Chat client and owns its established chat, streaming, settings, history, and feedback behavior.
- FastAPI/Jinja remains the admin and account interface.
- Shared design tokens, navigation structure, and interaction language make Chat and admin feel like one product.
- Stable CSS and small JavaScript shims customize Chainlit where its public configuration does not expose a needed option.
- Backend route or repository changes are limited to verified workflow, security, pagination, or data-presentation needs.
- No React application, custom chat renderer, or duplicate state layer will be introduced.

## Visual References

- [Desktop Chat](assets/frontend-qa-rounds/desktop-chat.png)
- [Desktop Logins](assets/frontend-qa-rounds/desktop-logins.png)
- [Mobile Chat and Logins](assets/frontend-qa-rounds/mobile-states.png)

The mobile reference is directional. The navigation drawer must be closed by default and overlay the current screen when opened; it must not permanently consume half the viewport.

## Baseline QA Evidence

Four independent production testers exercised novice Chat, admin operations, mobile/accessibility, and messy human behavior. Their findings define the repair contract.

### Release-blocking findings

1. Chainlit's avatar-menu Logout clears its token but leaves `project_recovery_session` and `project_recovery_csrf` usable. Protected account and admin pages remain accessible in the same browser.
2. The required Logins page causes document-level overflow at 390 and 768 pixels and makes important columns and session actions difficult to reach.
3. Visible Chat icon controls lack accessible names, including sidebar, search, new chat, attachment, settings, send, and account controls.
4. Chat history items expose a link containing a second tabbable button, producing duplicate keyboard stops for every conversation.

### Important usability findings

1. The floating workspace navigation overlaps Chat content and the composer and covers history at tablet sizes.
2. Admin navigation becomes clipped or undiscoverable at narrow widths.
3. Rapidly clicking Send twice changes the second click into Stop and leaves a saved prompt with no response.
4. The default Chainlit logo is the central product identity instead of Project Recovery.
5. Repeated untitled `New chat` history entries make conversation scanning noisy.
6. Logins, Prompt Runs, and Tool Use need bounded retrieval controls as their row counts grow.
7. Trace and identifier values need friendly display and copy/detail affordances rather than dominating primary tables.
8. Timestamps should prioritize friendly local presentation while retaining exact values in details.
9. Chainlit emits missing dialog-title/description and invalid MIME warnings.

### Existing behavior to preserve

- Generic prompt/response streaming works and persists across reloads and App Service restarts.
- Terra is the default model; Luna and Sol remain selectable.
- Reasoning settings persist and support low, medium, and high.
- Knowledge search safely handles special characters.
- Blank Chat input remains disabled.
- Thread deep links, back/forward navigation, and history resume work.
- Admin access control, CSRF protection, and session revocation remain enforced.
- Requested admin pages and their core read-only data are functional.

## Information Architecture

### Desktop

A persistent left rail provides:

- Project Recovery identity
- Chat
- Settings
- conversation creation, search, and history on the Chat surface
- a labeled Admin group for Users, Logins, Prompt Runs, Chat Feedback, Model Usage, Exceptions, Knowledge, and Tool Use

The top bar provides the current page title, concise context, settings when relevant, and an account menu. Navigation must not float over page content.

### Mobile and tablet

A 44-pixel menu control opens an overlay drawer containing personal and admin destinations. The drawer is closed by default, traps focus while open, closes with Escape or its explicit close control, and restores focus to the menu button.

No required destination may depend on horizontal navigation scrolling.

## Visual System

### Color

- Canvas: warm off-white, close to `#f8f6f3`
- Surface: true white
- Primary text: deep slate, close to `#24313a`
- Muted text: slate gray with WCAG AA contrast
- Primary action/current state: restrained rose-plum, close to `#7a3658`
- Informational/success emphasis: calm teal, close to `#176f70`
- Borders: quiet neutral gray
- Destructive action: reserved red used only for consequential actions

No gradients, glow, decorative illustration, or color used without meaning.

### Geometry and spacing

- 8-pixel spacing rhythm
- 8–10 pixel radii
- one-pixel borders
- shadows only for overlay/drawer separation
- minimum 44 by 44 pixel touch targets for icon-only controls
- reading-width Chat content with a non-overlapping composer

### Typography

Use the existing Segoe UI–compatible stack. Deliberately specify control, navigation, table, label, body, and heading sizes; no browser-default control typography.

## Component Behavior

### Chat shell

- Replace the central Chainlit brand treatment with Project Recovery copy and restrained code-native mark treatment.
- Empty state heading: `How can I help?`
- Composer placeholder: `Message Project Recovery`
- Show two or three short generic starter prompts.
- Every icon control receives an explicit accessible name and usable focus style.
- Prevent an accidental immediate second Send click from becoming an unlabeled Stop action. Once generation is active, expose a deliberately distinct, named Stop control.
- Reserve layout space for the composer and navigation; neither may obscure messages or history.
- Each history row exposes one primary keyboard stop. Secondary actions appear through a menu or reveal pattern without nesting a tabbable button inside a link.
- Empty conversations should not crowd useful history. Prefer suppressing empty records; otherwise give them a friendly timestamp-based fallback label.

### Account logout

All visible logout surfaces must end the same application session:

1. revoke the current application session,
2. clear application and Chainlit authentication cookies,
3. redirect to `/login`,
4. deny subsequent protected-page and protected-Chat access in the same browser.

### Admin shell

- Use the same navigation order and selected-state language as Chat.
- At desktop size, show a persistent rail.
- At mobile/tablet sizes, use the closed-by-default overlay drawer.
- Keep page headings concise and operational.
- Avoid nested cards and oversized empty bands.

### Logins

Desktop uses a readable table or open list with primary columns:

- User
- Status
- Signed in
- Last active
- Expires

Secondary fields, exact timestamps, identifiers, IP, and user agent live in a disclosure/details surface. Active sessions have a confirmation-safe revoke action.

At mobile widths, replace the squeezed wide table with stacked session rows. The page must have no document-level horizontal overflow at 390 or 768 pixels.

### Bounded data pages

Logins, Prompt Runs, and Tool Use receive only the retrieval controls justified by their data:

- bounded page size,
- next/previous pagination,
- relevant status/window filters,
- user/search filtering where supported by existing repository queries.

No export feature is added.

### Identifiers and tracing

Use friendly primary labels and keep UUIDs/trace IDs secondary. Provide copy-to-clipboard controls with an accessible success message. Do not imply that a trace ID links to an external destination unless a real configured trace URL exists.

### Time presentation

Show friendly local date/time in primary tables. Preserve exact ISO/UTC values in a detail view, `datetime` attribute, title text, or copy control.

## Accessibility Requirements

- One semantic interactive control per history item.
- Explicit accessible names for all icon-only controls.
- Dialogs have visible or visually hidden titles and descriptions.
- Focus is visible and logical across keyboard navigation.
- Drawer and modal focus is contained and restored.
- Controls meet 44-pixel touch targets where practical.
- Tables or responsive rows remain usable at 390, 768, 1280, and 1440 pixels.
- Reduced-motion preferences remain respected.
- Existing form labels, notices, landmarks, CSRF behavior, and semantic headings remain intact.

## Round Strategy

### Round 1 — foundations

Implement the release-blocking findings and the unified shell:

- complete logout,
- responsive admin navigation,
- responsive Logins presentation,
- non-overlapping Chat navigation/composer,
- Project Recovery Chat identity,
- accessible Chat control naming,
- single history keyboard stops,
- targeted regression tests.

Run full local Browser QA with desktop/mobile, keyboard, anonymous/authenticated, and core Chat/admin scenarios. Do not deploy if any round-one hard fail remains.

### Round 1 production gate

Deploy through the existing Azure/GitHub workflow. Independent testers rerun novice Chat, admin operations, mobile/accessibility, and messy-user scenarios against production.

### Round 2 — evidence-driven polish

Fix only validated production findings plus the already observed high-value improvements:

- bounded retrieval controls,
- friendly timestamps and identifiers,
- trace copy/details,
- history title quality,
- dialog/MIME warnings where the application can control them,
- any deployment-only layout or routing defect.

Run local QA, deploy, then rerun the production tester matrix.

### Final gate

- full automated test suite,
- Ruff check and format,
- mypy,
- source/wheel build,
- accessibility and responsive browser scenarios,
- authenticated Chat response and persisted history,
- anonymous and post-logout denial,
- all requested admin routes,
- Azure readiness,
- GitHub Test and Deploy workflows,
- independent whole-branch security/code review.

## Testing and Evidence

Browser QA is black-box and determines product acceptance. Source inspection may guide fixes only after a failing scenario is preserved.

Each QA round records:

- tested commit and environment,
- viewport and role,
- entry route, action, and expected rendered result,
- screenshot or DOM evidence,
- console and failed-request evidence,
- findings with severity and reproduction,
- fixed, deferred, or rejected ruling.

Temporary screenshots and traces stay outside the repository. The three approved concept images are the only committed visual references.

## Non-goals

- Replacing Chainlit
- Introducing React/Vite or another SPA
- Creating a custom chat protocol or state layer
- Adding exports
- Adding integrations or domain-specific features
- Reintroducing Salesforce, MyClubHub, BGCMD, or School Harbor terminology or assets
- Adding speculative analytics, dashboards, or settings
- Matching concept pixels where Chainlit's stable public extension surface cannot do so without fragile DOM surgery

## Acceptance

The work is complete only when:

1. logout invalidates the application session,
2. Chat and every requested admin page are usable without document overflow at required viewports,
3. the named accessibility defects are resolved,
4. navigation and composer never obscure primary content,
5. core Chat/history/settings/admin behavior remains functional,
6. two local and two deployed browser-QA rounds have completed,
7. no Critical or Important security/code-review findings remain,
8. production readiness and CI deployment are green.
