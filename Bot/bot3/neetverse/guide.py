"""Single command-guide catalog shared by /start and /help."""

from __future__ import annotations


GUIDE_PAGES: tuple[tuple[str, str], ...] = (
    (
        "🚀 Getting started",
        "`/start` — create or continue onboarding\n"
        "`/profile` — post your privacy-safe public student card\n"
        "`/help` — open the command-category navigator\n"
        "`/today` — view today's active daily plan\n"
        "`/progress` — view today's study, practice, revision, and mastery\n"
        "`/reminders` — configure private DMs and quiet hours\n\n"
        "Profile answers are yours: NeetVerse never assumes your year, schedule, scores, or resources.",
    ),
    (
        "⏱️ Study and statistics",
        "`/study start` — start stopwatch, countdown, or Pomodoro\n"
        "`/study status` — view the active timer and controls\n"
        "`/study pause` • `/study resume` — control focus timing\n"
        "`/study break` — begin a break\n"
        "`/study next_phase` — advance a Pomodoro phase\n"
        "`/study finish` — complete and save the active session\n"
        "`/study log` — record focused work completed offline\n"
        "`/study history` — browse recent finished sessions\n"
        "`/stats weekly` • `/stats monthly` — detailed trends and subject balance",
    ),
    (
        "🗓️ Planning, goals, and discipline",
        "`/plan create` — create a dated plan without AI\n"
        "`/plan add_task` — add work to an active plan\n"
        "`/plan list` — view plan IDs and completion counts\n"
        "`/task complete` — finish a task using its displayed ID\n"
        "`/goal create` — create a measurable personal goal\n"
        "`/goal list` — view active goals\n"
        "`/goal progress` — manually set a goal's current value\n"
        "`/goal cancel` — cancel an active goal\n"
        "`/discipline` — explain your recent discipline score and level\n"
        "`/streak` — post your verified automatic focus streak\n"
        "`/ranking privacy` — control public profile and ranking visibility\n"
        "`/ranking weekly` — view opted-in live focus and streak rankings",
    ),
    (
        "📚 Practice, resources, and syllabus",
        "`/practice log` — record attempted/correct/incorrect/skipped questions\n"
        "`/resource add` — add your own book or module\n"
        "`/resource list` — view active resources and IDs\n"
        "`/resource pages` — record exact page ranges without overlap inflation\n"
        "`/resource coverage` — view unique coverage by activity\n"
        "`/syllabus versions` — list reviewed official versions and sources\n"
        "`/syllabus use` — select an official or reference syllabus version\n"
        "`/syllabus browse` — drill through every unit, topic, and subtopic\n"
        "`/syllabus summary` — post automatically calculated completion\n"
        "`/syllabus find` — find an official unit/topic/subtopic and its ID\n"
        "`/syllabus progress` — update a track; parent updates roll down to leaves\n"
        "`/syllabus import_version` — owner-only reviewed official syllabus import",
    ),
    (
        "🔁 Mistakes, revision, and mocks",
        "`/mistake add` — capture a mistake and schedule its first review\n"
        "`/mistake list` — browse your private mistake book\n"
        "`/revision due` — show revision items currently due\n"
        "`/revision review` — record forgotten/hard/good/easy recall\n"
        "`/mock log` — record a mock and optional subject section\n"
        "`/mock history` — view recent mock scores and movement\n\n"
        "Practice, revision, mocks, and page coverage feed deterministic mastery evidence.",
    ),
    (
        "🎥 Lectures and official news",
        "`/lecture find` — open a playable, paginated YouTube lecture deck\n"
        "`/lecture saved` — view your private lecture queue\n"
        "`/lecture status` — mark a lecture planned/watching/completed/archived\n"
        "`/news latest` — view notices collected from official authorities\n"
        "`/news status` — inspect authority-source polling health\n\n"
        "`/search web` — low-volume official, study-source, or general web links\n\n"
        "YouTube requires its API key. Official news does not use coaching-site articles. "
        "Web search is rate-limited and does not verify arbitrary results.",
    ),
    (
        "🧠 OpenRouter academic AI",
        "`/ai tutor` — ask using your own academic context\n"
        "`/ai daily_plan` — generate an availability-bounded draft\n"
        "`/ai approve_plan` — approve a proposal after its panel expires\n"
        "`/ai weekly_review` — receive evidence-based preparation feedback\n"
        "`/ai mock_analysis` — analyse your latest recorded mock\n\n"
        "Every AI request uses `openrouter/free`. AI plan changes require your explicit approval. "
        "You can also mention NeetVerse with a question in a server channel or DM.",
    ),
    (
        "🎙️ AI voice companion",
        "`/voice join` — connect NeetVerse to your current voice channel\n"
        "`/voice ask` — ask AI, post its transcript, and queue the spoken answer\n"
        "`/voice repeat` — repeat the latest explanation with your settings\n"
        "`/voice stop` — stop speaking and clear the queue\n"
        "`/voice leave` — clear the queue and disconnect\n"
        "`/voice status` — view connection, current speaker, and queue bars\n"
        "`/voice settings` — view or change your voice, rate, and pitch\n"
        "`/voice voices` — search available Edge TTS voice names\n\n"
        "Voice is text-triggered: NeetVerse speaks but does not listen to the VC.",
    ),
    (
        "🔒 Your data",
        "`/mydata export` — privately download your NeetVerse records as JSON\n"
        "`/mydata delete` — permanently delete your profile and records after confirmation\n\n"
        "Private settings, AI context, mistakes and exports stay private. Public cards hide schedules, time zones, coaching, books and blockers. "
        "Only live-timed focus can enter rankings, and only after opt-in.",
    ),
)
