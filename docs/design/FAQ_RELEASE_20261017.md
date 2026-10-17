# FAQ production release — 17 October 2026

User approved FAQ preview V2 and explicitly authorized production publication.
Approved source: PR #102, commit ac2b636bd8707a04078e95bd80127f3f0af56671.

## Scope

Replace the existing static /faq presentation with the approved 20 native disclosures in four categories, shared header/footer, accessible navigation and source links. Add opt-in FAQ CSS and progressive enhancement JavaScript. Restore production index,follow metadata; retain canonical URL, favicons and WebPage structured data with matching title/description. No FAQPage rich-result promise.

No preview mocks, Netlify wrapper, duplicate preview HTML or build helpers are included. Existing backend routes, FIFO, authentication, payment integrations, database, environment variables and security controls remain unchanged.

## Validation

The CI responsive suite exercises the production FAQ HTML at /faq using synthetic sessions: 22 scenarios across 13 widths, overflow/header geometry, keyboard, native no-JavaScript disclosures/navigation, 200% text, reduced motion, deep links and user/admin navigation. Existing Home, Tools, How, Resources, backend and navigation checks remain enabled. Required checks must pass before merge; verify the automatic Railway deployment reaches SUCCESS and inspect the live public FAQ after merge.

## Editorial limits retained

Publication does not imply review or approval by Rafa. The approved answers avoid undefined free downloads, invented pricing/retention guarantees and unsupported claims of universal software consolidation. Case-specific tax answers retain qualifications and official references. Broader privacy-policy consistency and commercial definitions remain separate work; this release does not modify them.

## Rollback

Revert the release commit through the normal protected main workflow and verify the resulting automatic deployment; no database rollback is required for this presentation-only change.
