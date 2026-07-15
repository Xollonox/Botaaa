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
- Bundled official NEET (UG) 2026 catalog with 783 subject/unit/topic/subtopic nodes
- Versioned syllabus selection, mobile drill-down browser, and five-track completion roll-ups
- Personal books/modules and overlap-safe exact page coverage
- Question-practice batches with accuracy validation
- Mistake book with adaptive revision scheduling and private DM reminders
- Deterministic, versioned mastery estimates with confidence
- Mock history, subject evidence, and optional AI mock analysis
- Automatically calculated verified streaks, opt-in rankings, and a transparent discipline score
- Privacy-safe public student cards with live focus, plan, syllabus, level, and academic totals
- YouTube lecture discovery with quota-conscious caching and saved queues
- Official-only NTA NEET and MCC notice ingestion
- OpenRouter `openrouter/free` tutor, weekly review, and plan drafts
- Mention-based AI conversation in server channels and DMs
- Edge TTS voice companion with per-guild queues, transcripts, and user voice settings
- Premium mobile HUD shared by every command with semantic emoji and evidence-backed progress bars
- Public playable YouTube lecture deck with thumbnails, paging, saving, and direct-watch controls
- Explicit approval before AI-generated plans change student records
- JSON data export and guarded complete account deletion
- SQLite migrations, audit history, event outbox, retryable automation, and logs

No academic profile answer is hardcoded. Target year, current status, coaching,
time zone, availability, progress, scores, Pomodoro preferences, language,
resources, and preparation problems remain empty until that student supplies
them, and remain editable later.

## Discord entry points

- `/help`
- `/start` (private profile editor and complete command guide), `/profile`, `/mydata export|delete`
- `/study start|log|history|status|pause|resume|break|next_phase|finish`
- `/plan create|add_task|list`, `/task complete`, `/today`
- `/goal create|list|progress|cancel`
- `/syllabus versions|use|browse|summary|find|progress|import_version`
- `/practice log`, `/mistake add|list`, `/revision due|review`
- `/resource add|list|pages|coverage`, `/progress`
- `/stats weekly|monthly`
- `/mock log|history`, `/discipline`, `/streak`, `/ranking privacy|weekly`
- `/lecture find|saved|status`
- `/news latest|status`, `/reminders`
- `/ai tutor|daily_plan|approve_plan|weekly_review|mock_analysis`
- `/voice join|ask|repeat|stop|leave|status|settings|voices`

Commands are mobile-first presentation entry points. Academic rules live in
independent services and do not depend on Discord objects.

## Local and Wispbyte setup

1. Copy `.env.example` to `.env` inside `Bot/bot3`.
2. Put newly generated credentials in `.env`; never commit or paste them into chat.
3. Set `NEETVERSE_TOKEN`.
4. Set `OPENROUTER_API_KEY` for AI and `YOUTUBE_API_KEY` for lecture discovery.
5. Set `NEETVERSE_OWNER_IDS` for reviewed syllabus imports.
6. Install `Bot/bot3/requirements.txt` or the root requirements.
7. Ensure the host has the `ffmpeg` executable for Discord voice playback.
8. Run `python main.py` from `Bot/bot3`, or run the root `launcher.py`.

`OPENROUTER_MODEL` accepts only `openrouter/free`. Core study functionality
remains available during AI/API outages.

Voice answers use Edge TTS and are deliberately text-triggered. The bot does
not capture or transcribe voice-channel audio. Each guild has one bounded queue,
only members in the active voice channel can control it, and the bot disconnects
after an idle timeout. `/voice settings` stores independent voice/rate/pitch
preferences; the exact available provider voices can be searched in Discord.

All command panels use the shared presentation toolkit in `neetverse/ui.py`.
Bars represent real ratios such as focus targets, accuracy, syllabus completion,
mock scores, goals, queue capacity, or task completion; unknown values are shown
as unknown instead of receiving decorative fake percentages. `/lecture find`
posts one raw YouTube URL at a time so Discord can render its native player when
the client permits, alongside the NeetVerse result card and navigation controls.

## Official syllabus import

NeetVerse ships the NMC-finalized **NEET (UG) 2026** syllabus published for
the 2026–27 academic session. It is stored as 3 subjects, 50 units, 113 topics,
and 617 leaf subtopics. A matching NEET 2026 profile uses it automatically.
A later-year student must explicitly choose it with `/syllabus use`; every
panel labels it as a 2026 reference rather than claiming that a future syllabus
has already been published. Overall and subject completion are weighted from
leaf subtopics across lecture, reading, notes, practice, and PYQ tracks.

The owner command accepts a reviewed JSON attachment with `exam` set to
`NEET-UG`, a target year, label, official NTA/NMC source URL, and a `nodes`
array. Each node supplies a unique `key`, optional `parent_key`, `node_type`,
`subject_code`, `name`, and optional `sort_order`. Activation retires only the
previous active version for the same target year.

`/profile`, `/streak`, `/discipline`, `/ranking weekly`, `/syllabus summary`,
`/syllabus browse`, `/syllabus find`, lecture search, and official news are
public read-only displays when invoked. Viewing another student's profile or
streak requires that student's `/ranking privacy visible:true` opt-in. Public
cards never expose time zone, availability, coaching, preferred language,
books, blockers, reminders, mistakes, AI context, or exports. Mutation and
sensitive-data commands remain private.

## Validation

Run from `Bot/bot3`:

```bash
python -m compileall -q .
python -m pyflakes .
pytest -q
```

Runtime databases, `.env`, SQLite WAL files, caches, and logs are ignored by Git.
