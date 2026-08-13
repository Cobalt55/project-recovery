# Chat Settings Header Design

## Goal

Keep the native Chainlit conversation history, search, and New Chat controls fully usable,
especially on mobile, while providing a direct path to the Project Recovery Settings page.

## Design

- Remove the injected workspace navigation card, drawer, backdrop, and body offset from Chat.
- Add one Project Recovery Settings link beside Chainlit's top-right theme/account controls.
- Display a gear and the word `Settings` on wider screens.
- At phone widths, retain a 44 by 44 pixel gear control with the accessible name `Settings`.
- Link directly to `/settings`; administrator navigation remains available in the authenticated
  application shell reached from that page.
- Preserve the existing native-control labels, single-tab-stop history treatment, dialog
  semantics, and Send/Stop transition guard.

## Acceptance Criteria

- No Project Recovery overlay covers native history, search, or New Chat controls.
- The Settings link is visible and keyboard accessible on desktop, tablet, and mobile.
- The mobile Settings target is at least 44 by 44 pixels and has an accessible name.
- Native Chat controls and streaming behavior remain unchanged.
- Anonymous Chat access continues to redirect through the existing authentication guard.
