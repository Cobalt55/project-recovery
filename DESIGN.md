---
name: Project Recovery
description: A calm, trustworthy workspace for durable knowledge-backed chat and operations.
---

<!-- SEED: re-run $impeccable document once there's code to capture the actual tokens and components. -->

# Design System: Project Recovery

## Overview

**Creative North Star: "The Quiet Operations Room"**

Project Recovery should feel like a well-kept room where difficult work becomes manageable: bright, orderly, softly human, and confidently restrained. The interface uses familiar product patterns, generous breathing room, and clear hierarchy. It supports sustained daily work without looking clinical, theatrical, or precious.

The system rejects generic AI-tool spectacle, aggressive security-console styling, SaaS landing-page clichés, and customer-branded visual residue. Motion is responsive but minimal: short state transitions only, with no staged entrances or decorative choreography.

**Key Characteristics:**

- Restrained color with one quiet rose-plum brand voice and a supporting calm teal
- Warmly human single-sans typography
- Flat-by-default surfaces separated by tone and fine borders
- Clear focus, readable density, and calm status language
- Structural responsive behavior for chat, navigation, forms, and bounded tables

## Colors

Use a restrained strategy: near-neutral surfaces carry the layout while the rose-plum anchor appears only on primary actions, focus, and current selection. A muted teal supports informational and knowledge states; amber and rose semantic colors are reserved for warning and error feedback.

**The Quiet Color Rule.** Brand and semantic color must occupy no more than ten percent of a normal administrative screen. Neutral space creates safety; color communicates action or state.

**The One Meaning Rule.** A color must keep the same purpose across Chainlit and the administrator workspace. Never reuse warning or error colors as decoration.

## Typography

Use one warm humanist sans-serif family with reliable system fallbacks. Headings, labels, controls, tables, and prose share the family so the application feels coherent and loads efficiently. The implementation should use a tight fixed type scale suited to an authenticated product, not fluid marketing typography.

**The Plain Language Rule.** Labels and headings must describe the user's task directly. Never use decorative display type, forced all-caps paragraphs, or model jargon where ordinary language works.

## Elevation

The system is flat by default. Depth comes from neutral tonal layers and fine borders; a soft ambient shadow is reserved for transient overlays and menus where spatial separation is necessary. Focus is communicated with a high-contrast ring rather than a shadow.

**The Resting Surface Rule.** Cards and tables stay flat at rest. If a normal page resembles a stack of floating cards, elevation has been overused.

## Components

Buttons, fields, navigation items, status chips, tables, and containers should feel refined and reassuring. Use moderate corners, an eight-pixel spacing rhythm, clear hover and active states, visible keyboard focus, and short 150–200 ms state transitions. Disabled and loading states remain legible and preserve layout.

Primary buttons carry the brand anchor with light text. Secondary buttons use a neutral surface and fine border. Inputs use an explicit label, quiet surface, and strong focus ring. Navigation uses familiar side-rail and top-bar patterns, collapsing structurally at narrow widths. Tables stay bounded and responsive, preserving key identity and status fields before optional detail.

## Do's and Don'ts

### Do:

- **Do** use neutral space, restrained color, and consistent controls to create a calm daily-work environment.
- **Do** provide strong text contrast, visible keyboard focus, semantic landmarks, useful empty states, and reduced-motion behavior.
- **Do** keep chat and administrative pages visually coherent through shared tokens and component states.
- **Do** use plain labels such as “Knowledge,” “Prompt Runs,” and “Tool Use.”

### Don't:

- **Don't** use Salesforce, MyClubHub, BGCMD, School Harbor, or customer-specific branding or terminology.
- **Don't** use generic AI-tool spectacle: purple gradients, glowing effects, glassmorphism, chat-bubble mascots, or decorative “sparkle” language.
- **Don't** create an aggressive security-console aesthetic, harsh red-dominant surfaces, or dense walls of undifferentiated telemetry.
- **Don't** introduce SaaS landing-page clichés inside the authenticated product.
- **Don't** invent unfamiliar controls for visual flavor or use decorative motion that does not communicate state.
