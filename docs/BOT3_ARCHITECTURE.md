# NeetVerse Bot3 Architecture

## Product boundary

NeetVerse is the third Discord bot inside Botaaa. Discord is its only UI. Its
scope is NEET preparation: if a capability does not improve study planning,
execution, revision, measurement, resource discovery, or official awareness,
it does not belong in Bot3.

The application is a modular monolith. This keeps Wispbyte deployment simple
while preserving service boundaries that can be separated later if scale
actually requires it.

## Non-negotiable data rule

Academic profile values are user-owned facts. The system never assumes a target
year, class/status, coaching provider, availability, subject progress, mock
score, score target, Pomodoro pattern, preferred language, books, or problems.
New profiles store these fields as null/empty. Every update is scoped by Discord
user ID and audited. A student can edit the values later.

Official syllabus selection follows the same rule: an active version must match
the student's supplied target year. NeetVerse does not substitute a different
year when that version is unavailable.

## Runtime composition

`main.py` constructs one instance of each domain service around a single SQLite
database. Feature cogs translate Discord interactions into service calls. A
service cannot send Discord messages, and a cog should not contain academic
rules or direct persistence logic.

The main layers are:

1. Presentation — slash commands, mobile embeds, buttons, selects, and modals.
2. Application services — profiles, study, planner, goals, curriculum, mastery,
   practice, revision, mocks, coverage, reminders, lectures, news, AI, privacy.
3. Automation — persisted domain-event processing and reminder delivery.
4. Persistence — versioned SQLite schema, transactions, audit records, outbox.
5. Integrations — Discord, OpenRouter, YouTube Data API, and official authority pages.

## Connected academic flow

Study and academic facts are recorded once in canonical tables. The same
transaction emits a domain event. The restart-safe event processor consumes each
event once and advances matching goals. Practice, revision, mocks, and page
coverage also write mastery evidence and recalculate deterministic snapshots.

Typical flow:

`Study/practice/revision action -> canonical record -> domain event -> goal progress`

`Practice/revision/mock/coverage -> mastery evidence -> versioned mastery snapshot`

`Mistake -> revision item -> reminder -> review result -> mastery -> next interval`

AI reads these results; it is not their source of truth.

## AI authority model

All production AI requests go through `OpenRouterClient`. Configuration rejects
alternate model IDs: only the dynamic `openrouter/free` route is accepted.
The router records requested/used model provenance, token usage, failure state,
and enforces atomic per-user and global daily request limits.

The academic manager receives only the requesting student's profile and bounded
academic state: recent study, mastery, revision queue, goals, plan tasks, mocks,
mistake patterns, and syllabus progress. It never receives another student's
records.

AI tutoring and analysis are read-only. AI plan output is a proposal, validated
against structure and the student's supplied daily availability. Tasks enter
the planner only after explicit approval. This proposal pattern is the required
boundary for future AI mutations such as schedule or profile changes.

Core tracking, planning, revision, and analytics remain functional if AI is
unconfigured, rate-limited, or unavailable.

## Persistence and consistency

SQLite runs with foreign keys, WAL mode, normal synchronous mode, busy timeout,
and short explicit transactions. Schema changes are forward-only numbered
migrations. User-owned child records use foreign keys with cascading deletion.
Tables intentionally outside that graph, such as AI usage and domain events,
are explicitly removed by the privacy service.

Long live sessions above six hours are marked `review_required`, so suspicious
time does not silently enter rankings or progress summaries. Page coverage uses
the union of ranges and does not double-count overlap. Leaderboards include only
students who explicitly opt in and only live-timed sessions; manual logs remain
available for private personal analytics but cannot inflate public rankings.

## Background work and recovery

- Reminder jobs are persisted before delivery, claimed atomically, recovered
  after abandoned claims, retried, and deferred during per-user quiet hours.
- Domain events remain pending across restarts and are retried up to five times;
  poisoned events are visible in processor health instead of blocking forever.
- News polling runs every six hours and stores only links discovered through the
  configured NTA NEET and MCC authority pages.
- YouTube searches are cached for six hours to conserve quota.

Background loops begin only after a properly initialized Discord client, which
also permits offline command-tree tests without leaked tasks.

## Privacy and trust boundaries

- Responses containing student data are ephemeral except the explicitly opt-in
  ranking display.
- Interactive views verify the initiating Discord user.
- Official news filters both source page and destination host.
- Syllabus imports require a configured owner and an NTA/NMC source URL.
- Secrets are read from `.env`; no token or API key belongs in source control.
- `/mydata export` returns a private JSON export, and `/mydata delete` requires a
  second button confirmation before cascading deletion.

## Extension rules

Future work should add one domain service plus a thin feature cog and tests. New
AI mutation types must use persisted proposals with explicit approval. New
derived scores require a formula version and transparent inputs. New external
content must declare a trust policy, timeout, cache strategy, and failure mode.
No service should depend on Discord objects, and no feature should introduce a
second runtime source of truth.
