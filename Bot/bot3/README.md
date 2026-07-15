# NeetVerse — Bot3

NeetVerse is Botaaa's Discord-native NEET preparation operating system. It is
a modular Python/discord.py application, not a website or standalone repo.
SQLite is the runtime authority; OpenRouter's free route supplies optional AI.

## Implemented systems

- Independent, editable per-user onboarding and academic profiles
- Persistent stopwatch, countdown, Pomodoro, and manual study sessions
- Separate focus, pause, and break accounting with restart recovery
- Manual and AI-proposed daily/weekly/monthly/custom study plans
- Measurable goals with automatic progress from domain events
- Versioned official syllabus imports and target-year-specific progress
- Personal books/modules and overlap-safe exact page coverage
- Question-practice batches with accuracy validation
- Mistake book with adaptive revision scheduling and private DM reminders
- Deterministic, versioned mastery estimates with confidence
- Mock history, subject evidence, and optional AI mock analysis
- Opt-in rankings and a transparent recent-discipline score
- YouTube lecture discovery with quota-conscious caching and saved queues
- Official-only NTA NEET and MCC notice ingestion
- OpenRouter `openrouter/free` tutor, weekly review, and plan drafts
- Explicit approval before AI-generated plans change student records
- JSON data export and guarded complete account deletion
- SQLite migrations, audit history, event outbox, retryable automation, and logs

No academic profile answer is hardcoded. Target year, current status, coaching,
time zone, availability, progress, scores, Pomodoro preferences, language,
resources, and preparation problems remain empty until that student supplies
them, and remain editable later.

## Discord entry points

- `/help`
- `/start` (nine-page profile and complete command guide), `/profile`, `/mydata export|delete`
- `/study start|log|history|status|pause|resume|break|next_phase|finish`
- `/plan create|add_task|list`, `/task complete`, `/today`
- `/goal create|list|progress|cancel`
- `/syllabus summary|find|progress|import_version`
- `/practice log`, `/mistake add|list`, `/revision due|review`
- `/resource add|list|pages|coverage`, `/progress`
- `/stats weekly|monthly`
- `/mock log|history`, `/discipline`, `/ranking privacy|weekly`
- `/lecture find|saved|status`
- `/news latest|status`, `/reminders`
- `/ai tutor|daily_plan|approve_plan|weekly_review|mock_analysis`

Commands are mobile-first presentation entry points. Academic rules live in
independent services and do not depend on Discord objects.

## Local and Wispbyte setup

1. Copy `.env.example` to `.env` inside `Bot/bot3`.
2. Put newly generated credentials in `.env`; never commit or paste them into chat.
3. Set `NEETVERSE_TOKEN`.
4. Set `OPENROUTER_API_KEY` for AI and `YOUTUBE_API_KEY` for lecture discovery.
5. Set `NEETVERSE_OWNER_IDS` for reviewed syllabus imports.
6. Install `Bot/bot3/requirements.txt` or the root requirements.
7. Run `python main.py` from `Bot/bot3`, or run the root `launcher.py`.

`OPENROUTER_MODEL` accepts only `openrouter/free`. Core study functionality
remains available during AI/API outages.

## Official syllabus import

The owner command accepts a reviewed JSON attachment with `exam` set to
`NEET-UG`, a target year, label, official NTA/NMC source URL, and a `nodes`
array. Each node supplies a unique `key`, optional `parent_key`, `node_type`,
`subject_code`, `name`, and optional `sort_order`. Activation retires only the
previous active version for the same target year.

## Validation

Run from `Bot/bot3`:

```bash
python -m compileall -q .
python -m pyflakes .
pytest -q
```

Runtime databases, `.env`, SQLite WAL files, caches, and logs are ignored by Git.
