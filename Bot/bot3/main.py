"""NeetVerse Discord bot bootstrap."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    AI_DAILY_GLOBAL_LIMIT,
    AI_DAILY_USER_LIMIT,
    DATABASE_PATH,
    DISCORD_TOKEN,
    GUILD_IDS,
    LOG_LEVEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL,
    OPENROUTER_TIMEOUT_SECONDS,
    TTS_DEFAULT_VOICE,
    TTS_MAX_CHARACTERS,
    TTS_TIMEOUT_SECONDS,
    VOICE_IDLE_SECONDS,
    VOICE_QUEUE_LIMIT,
    YOUTUBE_API_BASE_URL,
    YOUTUBE_API_KEY,
    require_runtime_config,
)
from neetverse.ai import AcademicAIService, OpenRouterClient
from neetverse.analytics import AnalyticsService
from neetverse.coverage import CoverageService
from neetverse.curriculum import CurriculumService, load_bundled_syllabus
from neetverse.database import Database
from neetverse.discipline import DisciplineService
from neetverse.events import EventProcessor
from neetverse.goals import GoalService
from neetverse.mastery import MasteryService
from neetverse.lectures import LectureService
from neetverse.mocks import MockService
from neetverse.news import OfficialNewsService
from neetverse.overview import StudentOverviewService
from neetverse.planner import PlannerService
from neetverse.privacy import PrivacyService
from neetverse.practice import PracticeService
from neetverse.profiles import ProfileService
from neetverse.revision import RevisionService
from neetverse.reminders import ReminderService
from neetverse.study import StudyService
from neetverse.streaks import StreakService
from neetverse.speech import EdgeSpeechService, SpeechPreferenceService
from neetverse.voice import VoiceSessionManager


def configure_logging() -> None:
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file_handler = RotatingFileHandler("neetverse.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(stream)
    root.addHandler(file_handler)


class NeetVerseTree(app_commands.CommandTree["NeetVerseBot"]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._usage: dict[int, deque[float]] = defaultdict(deque)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.type is discord.InteractionType.autocomplete:
            return True
        now = time.monotonic()
        bucket = self._usage[int(interaction.user.id)]
        while bucket and now - bucket[0] >= 10:
            bucket.popleft()
        if len(bucket) >= 8:
            retry = max(0.1, 10 - (now - bucket[0]))
            await interaction.response.send_message(
                f"Please slow down and try again in {retry:.1f}s.", ephemeral=True
            )
            return False
        bucket.append(now)
        return True


class NeetVerseBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=discord.Intents.default(),
            help_command=None,
            tree_cls=NeetVerseTree,
        )
        self.database = Database(DATABASE_PATH)
        self.reminder_service = ReminderService(self.database)
        self.profile_service = ProfileService(self.database)
        self.study_service = StudyService(self.database, self.reminder_service)
        self.planner_service = PlannerService(self.database)
        self.privacy_service = PrivacyService(self.database)
        self.mastery_service = MasteryService(self.database)
        self.practice_service = PracticeService(self.database, self.mastery_service)
        self.revision_service = RevisionService(self.database, self.mastery_service, self.reminder_service)
        self.coverage_service = CoverageService(self.database, self.mastery_service)
        self.curriculum_service = CurriculumService(self.database)
        bundled_syllabus = load_bundled_syllabus(
            Path(__file__).resolve().parent / "data" / "neet_ug_2026.json"
        )
        self.curriculum_service.ensure_bundled_version(bundled_syllabus)
        self.analytics_service = AnalyticsService(self.database)
        self.mock_service = MockService(self.database, self.mastery_service)
        self.discipline_service = DisciplineService(self.database)
        self.streak_service = StreakService(self.database)
        self.overview_service = StudentOverviewService(
            self.database,
            self.curriculum_service,
            self.discipline_service,
            self.planner_service,
            self.streak_service,
        )
        self.goal_service = GoalService(self.database, self.reminder_service)
        self.event_processor = EventProcessor(self.database, self.reminder_service)
        self.lecture_service = LectureService(
            self.database, api_key=YOUTUBE_API_KEY, base_url=YOUTUBE_API_BASE_URL
        )
        self.news_service = OfficialNewsService(self.database)
        self.openrouter = OpenRouterClient(
            database=self.database,
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
            model=OPENROUTER_MODEL,
            timeout_seconds=OPENROUTER_TIMEOUT_SECONDS,
            daily_global_limit=AI_DAILY_GLOBAL_LIMIT,
            daily_user_limit=AI_DAILY_USER_LIMIT,
        )
        self.academic_ai = AcademicAIService(self.database, self.openrouter)
        self.speech_preferences = SpeechPreferenceService(
            self.database, default_voice=TTS_DEFAULT_VOICE
        )
        self.speech_service = EdgeSpeechService(
            timeout_seconds=TTS_TIMEOUT_SECONDS,
            max_characters=TTS_MAX_CHARACTERS,
        )
        self.voice_manager = VoiceSessionManager(
            self,
            self.speech_service,
            self.speech_preferences,
            queue_limit=VOICE_QUEUE_LIMIT,
            idle_seconds=VOICE_IDLE_SECONDS,
        )

    async def setup_hook(self) -> None:
        for extension in (
            "neetverse.features.profile",
            "neetverse.features.study",
            "neetverse.features.ai",
            "neetverse.features.voice",
            "neetverse.features.academics",
            "neetverse.features.progression",
            "neetverse.features.reminders",
            "neetverse.features.lectures",
            "neetverse.features.news",
            "neetverse.features.curriculum",
            "neetverse.features.goals",
            "neetverse.features.automation",
            "neetverse.features.privacy",
            "neetverse.features.analytics",
            "neetverse.features.help",
        ):
            await self.load_extension(extension)
            logging.getLogger(__name__).info("Loaded %s", extension)

        if GUILD_IDS:
            for guild_id in GUILD_IDS:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                logging.getLogger(__name__).info("Synced %d commands to guild %d", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            logging.getLogger(__name__).info("Synced %d global commands", len(synced))

    async def on_ready(self) -> None:
        logging.getLogger(__name__).info("NeetVerse ready as %s", self.user)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="NEET preparation",
            )
        )

    async def close(self) -> None:
        for cog_name, loop_name in (
            ("ReminderCog", "deliver_due"),
            ("NewsCog", "news_poll"),
            ("AutomationCog", "process_events"),
        ):
            cog = self.get_cog(cog_name)
            loop = getattr(cog, loop_name, None) if cog else None
            if loop is not None:
                loop.cancel()
        await self.openrouter.close()
        await self.voice_manager.close()
        await self.speech_service.close()
        await self.lecture_service.close()
        await self.news_service.close()
        await super().close()


def main() -> None:
    require_runtime_config()
    configure_logging()
    NeetVerseBot().run(DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
