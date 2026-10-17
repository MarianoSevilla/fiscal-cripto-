# Privacy review preview — 17 October 2026

## Purpose and scope

User authorized continuing the privacy redesign and content review. This is an isolated visual/editorial preview, not the final approved privacy policy. Production `/privacidad` and its backend route remain unchanged. Do not merge this preview branch as a production release.

The user clarified that the customer contracts and pays the professional Rafael Ramos directly; Mariano receives a commission for intermediation. Mariano manages the website and promotion as a secondary activity alongside his employment. No claim is made that secondary activity removes platform privacy obligations.

The proposed service age is 18 or over. This is a service condition, not a claim that minors have no IRPF obligations. The user reports no current promotional campaigns and plans opt-in reminders at the beginning of the Renta period, new video notices and updates. Resource UID collection has no stated use; its removal requires a coordinated later change to form, JavaScript, API and treatment of legacy data, not a misleading copy-only promise.

## Design

Approved shared static header, no-JS fallback and footer taken from current production FAQ. Shared Home tokens, fonts and system buttons are unchanged. Privacy-specific styles are opt-in under `.apple-legal-page`, with a full-width shared hero, readable document column, sticky desktop index and inline mobile/tablet index. Eleven sections remain visible without JavaScript. Definitions replace the dense legacy table. A privacy contact action replaces a commercial acquisition CTA. Print styles remove navigation without hiding the document.

## Content boundaries and release gates

The preview corrects the old claim that no financial information is stored and that all CSV processing is memory-only. It distinguishes temporary input/output files, persisted report results, diagnostics, account data and correspondence. It explains proportionate identity verification for rights rather than a blanket DNI-copy requirement.

Several paragraphs describe requirements or current limitations rather than a completed compliance arrangement. Do not treat them as final operating promises. Before production:

1. Complete the titular identification/address. The professional's office was offered as a contact address, but the user confirmed only the professional works there. Do not label it Mariano's domicile or establishment. A home address has not been provided or authorized for publication. The personally supplied NIF is deliberately not copied into this public review branch or viewer; insert appropriate final identification only through the approved release process.
2. Verify applicable provider agreements, transfer mechanisms, processor/subprocessor scope, retention and backups. A read-only platform check found application and the production Postgres service/volume in `us-east4-eqdc4a`; that does not verify all locations or guarantees.
3. Adopt and verify a category-specific retention calendar, transverse suppression, backup handling and physical orphan-file cleanup. PDF token TTL is not proof of file removal. The retention section is a structural/editorial review and does not yet supply a final schedule for publication.
4. Complete lawful bases for additional telemetry, contacts, resource eligibility and other purposes, including necessity/balancing where appropriate. Review internal segmentation and Modelo 721 logs; do not claim universal anonymity or absence of profiling.
5. Identify the professional and contractual data flows fully. A direct professional contract does not by itself determine all GDPR roles for shared processing.
6. Implement and test optional marketing and origin-specific proof/withdrawal before promising an optional resource form or sending campaigns. Existing accounts are not retroactively subscribed. Review future access-age conditions alongside Términos and registration.
7. Fix registration links and first-layer information in a separately scoped integration; existing broken links are not changed by this presentation preview.

Pending legal/operating facts live in this review note and the user's draft, not fictitious placeholders in the page. No compliance certification or Rafa sign-off is implied.

## Isolation and static viewer

- `static/privacidad_apple.html` references unchanged shared assets and new `legal_apple.css`.
- `/privacidad-apple-preview/` is self-contained for Netlify review, with shared CSS/JS inlined. The copied navigation reads a local visitor-only `session.json`; it does not override global fetch or call a production API.
- Viewer navigation points to public production pages; in-page section links remain local. The shared production scripts are not edited.
- Both variants use `noindex,nofollow` and canonical `/privacidad`. No tracking, provider calls, forms, payment interactions or real session data are added. No new dependency or workflow installation step is introduced.
- No private NIF, home address, account or fiscal record is included. No Railway setting, service, database or variable is changed.

## Validation

`qa_privacidad_apple.py`, integrated into the existing responsive runner, exercises 27 synthetic browser scenarios: thirteen viewport widths, keyboard skip/index links, shared mobile menu, no-JS presentation, 200% text, reduced motion, user/admin roles, delayed sessions, self-contained viewer equivalence and printing. Requests remain local to the QA server; non-GET and unexpected external requests fail. No application/database import is used for privacy presentation tests.

Existing FAQ, Home, Tools, How, Resources and other required CI suites remain enabled. CI screenshots use the existing `home_*.png` artifact collection. Browser review of the deployed Netlify preview is required before delivery. Required checks are not bypassed.

## Production integration later

After content/operating gates and user review, create a clean release from then-current main. Transfer only approved production HTML/styles and necessary QA. Exclude the preview wrapper, session fixture and any preview-only files. Do not alter calculation, authentication, security controls, subscriptions, PayPal or Stripe as part of the visual release.

## Primary sources

- https://www.boe.es/buscar/doc.php?id=DOUE-L-2016-80807
- https://www.boe.es/buscar/act.php?id=BOE-A-2018-16673
- https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758
- https://www.aepd.es/preguntas-frecuentes/1-tus-derechos/3-identificacion-con-dni/FAQ-0108-para-el-ejercicio-de-estos-derechos-es-necesario-facilitar-la-copia-del-dni
- https://www.aepd.es/sites/default/files/2019-09/guia-modelo-clausula-informativa.pdf
- https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c14-adecuacion-impuesto-circunstancias-personales/ejemplos-practicos/ejemplo-2.html



## Update — 18 October 2026: describe current code

The user now explicitly requests an audit of existing behavior and wording aligned with it, updating the policy alongside future programming. The new audit `PRIVACIDAD_CODIGO_ACTUAL_20261018.md` supersedes earlier assumptions about immediate file removal, optional marketing, universal anonymization, and the availability of advisory uploads. It does not authorize data purges or storage changes.

The preview now documents persistent fiscal results, automatic diagnostic metadata, current resource fields/marketing condition, partial account erasure, active advisory requests and suspended new uploads/payments. The user permits only the locality Xirivella (Valencia); no complete private address or NIF is added. Future non-retention is not described as implemented.

The previous list of release gates identifies unresolved compliance/operating matters, not a requirement to implement all future functionality before describing existing behavior truthfully. Pending lawful bases, retention decisions and provider guarantees must not be represented as verified. Production remains unchanged in this audit; a clean release still excludes the static viewer and local session fixture.
