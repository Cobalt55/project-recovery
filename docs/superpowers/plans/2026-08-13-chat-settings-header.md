# Chat Settings Header Implementation Plan

1. Replace the old navigation/drawer browser contract with a failing Settings-header contract.
2. Simplify `public/chat-navigation.js` to mount one idempotent `/settings` link while retaining
   the accessibility and Send/Stop enhancements.
3. Replace navigation overlay CSS with responsive top-right Settings-link styling.
4. Run focused integration and real Chromium tests at 390, 768, and desktop widths.
5. Run the full quality gate, commit, push, deploy, and verify the production layout.
