# Project Recovery Product Context

## Product

Project Recovery is an authenticated, knowledge-backed chatbot and operational workspace. It gives a small team a durable place to ask questions, manage shared knowledge, administer access, and understand how the assistant is behaving in production.

## Users and jobs

- Users need a dependable chat experience with resumable history, private attachments, model controls, and answers grounded in shared knowledge.
- Administrators need compact, functional pages for users, logins, prompt runs, feedback, model usage, exceptions, Knowledge, and tool use.
- Operators need deployments and diagnostics they can trust without exposing credentials, personal data, or unbounded raw logs.

## Personality

The product is calm, reassuring, capable, and plain-spoken. It should feel like a quiet operations room: orderly enough to build confidence, comfortable enough for daily use, and never clinical or severe.

## Experience principles

- Put the current task first; controls and telemetry support the work instead of competing with it.
- Use familiar product patterns, concise labels, useful empty states, and bounded data views.
- Keep model and reasoning choices understandable without requiring knowledge of the underlying SDK.
- Make security visible through good defaults and clear status, not alarming language.
- Preserve accessibility through strong contrast, keyboard operation, visible focus, and reduced motion.

## Anti-references

- No Salesforce, MyClubHub, BGCMD, School Harbor, or customer-specific branding or terminology.
- No generic AI-tool spectacle: purple gradients, glowing effects, glassmorphism, chat-bubble mascots, or decorative “sparkle” language.
- No aggressive security-console aesthetic, harsh red-dominant surfaces, or dense walls of undifferentiated telemetry.
- No SaaS landing-page clichés inside the authenticated product.
- No unfamiliar controls invented for visual flavor.

## Scope guardrails

The MVP is a generic, modular monolith built around one focused OpenAI agent. It does not include public registration, outbound email, large exports, multi-tenant organization isolation, customer integrations, or multiple cooperating agents.
