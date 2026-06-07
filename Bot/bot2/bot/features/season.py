"""Season system — info, pass, daily/weekly/monthly missions."""
from __future__ import annotations
import uuid
import datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import ensure_registered
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed
from bot.utils.xp_logic import make_bar, xp_progress
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.config import OWNER_GUILD_ID

OWNER_GUILD  = discord.Object(id=OWNER_GUILD_ID)
PASS_COST    = 200   # gems
SEP          = "━" * 32

def _embed(desc: str, color: int = 0x9B59B6) -> discord.Embed:
    return make_embed(None, "LOOKISM HXCC • SEASON", desc, color=color, footer="Season System")

def _ok(d: str)  -> discord.Embed: return _embed(d, 0x2ECC71)
def _err(d: str) -> discord.Embed: return _embed(d, 0xE74C3C)
def _inf(d: str) -> discord.Embed: return _embed(d, 0x9B59B6)

def _hdr(title: str) -> str:
    return f"{SEP}\n  {title}\n{SEP}"

def _season_root(data: dict[str, Any]) -> dict[str, Any]:
    s = data.setdefault("season", {})
    s.setdefault("active",         False)
    s.setdefault("current_season", 1)
    s.setdefault("name",           "Season 1")
    s.setdefault("start_time",     0)
    s.setdefault("end_time",       0)
    s.setdefault("reset_type",     "both")
    s.setdefault("pass_tiers",     {})
    s.setdefault("missions",       {})
    return s

def _get_player_cp(data: dict[str, Any], user_id: str) -> int:
    player = data.get("players", {}).get(str(user_id), {})
    user   = (player.get("user", {}) or {}) if isinstance(player, dict) else {}
    snum   = str(data.get("season", {}).get("current_season", 1))
    scp    = user.get("season_cp", {}) or {}
    return int(scp.get(snum, 0)) if isinstance(scp, dict) else 0

def _fmt_date(ts: int) -> str:
    if not ts: return "—"
    return datetime.datetime.utcfromtimestamp(ts).strftime("%b %d, %Y")

def _time_left(end_time: int) -> str:
    remaining = max(0, end_time - now_ts())
    d, rem = divmod(remaining, 86400)
    h      = rem // 3600
    return f"{d}d {h}h" if d else f"{h}h"

def _reset_key(period: str) -> str:
    """Get the current period key for daily/weekly/monthly resets."""
    now = datetime.datetime.utcnow()
    if period == "daily":
        return now.strftime("%Y-%m-%d")
    if period == "weekly":
        return f"{now.year}-W{now.isocalendar()[1]:02d}"
    if period == "monthly":
        return now.strftime("%Y-%m")
    return "season"

def _time_until_reset(period: str) -> str:
    now = datetime.datetime.utcnow()
    if period == "daily":
        tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0)
        diff = int((tomorrow - now).total_seconds())
        h, m = divmod(diff // 60, 60)
        return f"{h}h {m}m"
    if period == "weekly":
        days_left = 7 - now.weekday()
        return f"{days_left}d"
    if period == "monthly":
        import calendar
        last_day = calendar.monthrange(now.year, now.month)[1]
        days_left = last_day - now.day
        return f"{days_left}d"
    return "season end"

def _grant_reward(data: dict[str, Any], user_id: str, reward_str: str) -> str:
    """Parse and grant a reward string. Returns description of what was given.

    Handles:
    - Coins: "500 coins"
    - Gems: "50 gems"
    - Packs: "newbie pack", "amateur pack", etc. (case-insensitive)
    - Multiple rewards: "500 coins, 1 newbie_pack" (comma-separated)
    """
    import logging
    logger = logging.getLogger(__name__)

    p = data.get("players", {}).get(str(user_id), {})
    u = (p.get("user", {}) or {}) if isinstance(p, dict) else {}

    # Handle comma-separated rewards
    reward_parts = [part.strip() for part in str(reward_str).split(",")]
    descriptions = []

    for part in reward_parts:
        if not part:
            continue

        r = part.lower()
        matched = False

        # Coins
        if "coin" in r:
            digits = ''.join(filter(str.isdigit, r))
            amt = int(digits) if digits else 0
            if amt:
                u["balance"] = int(u.get("balance", 0)) + amt
                descriptions.append(f"💰 +{amt:,} coins")
                matched = True

        # Gems
        if "gem" in r:
            digits = ''.join(filter(str.isdigit, r))
            amt = int(digits) if digits else 0
            if amt:
                u["premium_balance"] = int(u.get("premium_balance", 0)) + amt
                descriptions.append(f"💎 +{amt} gems")
                matched = True

        # Packs — robust substring matching
        if not matched:
            pack_patterns = {
                "newbie": "newbie_pack",
                "amateur": "amateur_pack",
                "basic": "basic_pack",
                "intermediate": "intermediate_pack",
                "experienced": "experienced_pack",
                "veteran": "veteran_pack",
                "abyssal": "abyssal_pack",
                "infernal": "infernal_pack",
            }

            # Handle quantity prefix (e.g., "2x", "2 x", "2")
            qty = 1
            rw = r
            if rw.startswith("2x") or rw.startswith("2 x"):
                qty = 2
                rw = rw.replace("2x", "").replace("2 x", "").strip()
            elif rw.startswith("3x") or rw.startswith("3 x"):
                qty = 3
                rw = rw.replace("3x", "").replace("3 x", "").strip()

            for pattern, pack_key in pack_patterns.items():
                if pattern in rw:
                    from bot.features.packs import _add_packs_to_inventory
                    _add_packs_to_inventory(data, user_id, pack_key, qty)
                    descriptions.append(f"🎴 {qty}× {part.strip()}")
                    matched = True
                    break

        # Fallback: unknown format
        if not matched:
            logger.warning("[SEASON] Unknown reward format: %r", part)
            descriptions.append(f"🎁 {part.strip()}")

    return " + ".join(descriptions) if descriptions else f"🎁 {reward_str}"


# ── Season Info Panel ─────────────────────────────────────────────

def _build_season_embed(data: dict[str, Any], uid: str) -> discord.Embed:
    s        = _season_root(data)
    my_cp    = _get_player_cp(data, uid)
    end_time = int(s.get("end_time", 0))
    snum     = str(s.get("current_season", 1))

    # XP
    player  = data.get("players", {}).get(uid, {})
    u       = (player.get("user", {}) or {}) if isinstance(player, dict) else {}
    raw_xp  = int(u.get("xp", 0))
    lvl, xp_cur, xp_need = xp_progress(raw_xp)
    trophies = int(u.get("trophies", 0))

    # Leaderboard
    players = data.get("players", {})
    ranking = []
    for pid, p in players.items():
        if not isinstance(p, dict): continue
        pu   = (p.get("user", {}) or {})
        scp  = (pu.get("season_cp", {}) or {})
        cp   = int(scp.get(snum, 0))
        name = str(pu.get("name") or pu.get("username") or f"Player")
        ranking.append((cp, name))
    ranking.sort(reverse=True)

    medals = [e("winner",data), "🥈", "🥉"] + [f" {i}." for i in range(4, 11)]
    lb_lines = "\n".join(
        f"│  {medals[i]}  {name:<18} {cp:,} CP"
        for i, (cp, name) in enumerate(ranking[:10])
    ) or "│  No data yet."

    body = (
        f"{_hdr('🌟  ' + s.get('name', 'Season'))}\n\n"
        f"╭─ 📅 Season Info\n"
        f"│  Start  {_fmt_date(int(s.get('start_time',0)))}\n"
        f"│  End    {_fmt_date(end_time)}\n"
        f"│  ⏳ {_time_left(end_time)} remaining\n"
        f"│  🔄 Resets: Trophies + Rank\n"
        f"╰────────────────────────────────\n\n"
        f"╭─ 📊 Your Progress\n"
        f"│  🎯 Season CP:  {my_cp:,}\n"
        f"│  ⭐ Level:      {lvl}\n"
        f"│  🏆 Trophies:   {trophies:,}\n"
        f"╰────────────────────────────────\n\n"
        f"╭─ 🏆 Leaderboard\n"
        f"{lb_lines}\n"
        f"╰────────────────────────────────"
    )
    return _inf(body)


# ── Season Pass Panel ─────────────────────────────────────────────

class PassPanel(discord.ui.View):
    def __init__(self, cog: "SeasonCog", uid: str) -> None:
        super().__init__(timeout=180)
        self.cog  = cog
        self.uid  = uid
        self.page = 0  # 0-indexed, 5 tiers per page
        self.message: discord.Message | None = None
        self._rebuild()

    def _rebuild(self) -> None:
        for child in list(self.children): self.remove_item(child)
        data  = self.cog.bot.storage.load()
        s     = _season_root(data)
        tiers = sorted((s.get("pass_tiers", {}) or {}).items(),
                       key=lambda x: int(x[1].get("cp_required", 0)))
        total_pages = max(1, (len(tiers) + 4) // 5)

        prev = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0, disabled=self.page <= 0)
        next_ = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.primary, row=0, disabled=self.page >= total_pages - 1)
        prev.callback  = self._on_prev
        next_.callback = self._on_next
        self.add_item(prev)
        self.add_item(next_)

        claim_btn = discord.ui.Button(label="🎁 Claim All", style=discord.ButtonStyle.success, row=0)
        claim_btn.callback = self._on_claim
        self.add_item(claim_btn)

        # Buy pass button
        snum     = str(s.get("current_season", 1))
        player   = data.get("players", {}).get(self.uid, {})
        user     = (player.get("user", {}) or {}) if isinstance(player, dict) else {}
        has_paid = bool((user.get("season_pass_paid", {}) or {}).get(snum, False))
        if not has_paid:
            buy = discord.ui.Button(label=f"💎 Buy Pass — {PASS_COST} gems", style=discord.ButtonStyle.primary, row=1)
            buy.callback = self._on_buy
            self.add_item(buy)

    def _build_embed(self) -> discord.Embed:
        data      = self.cog.bot.storage.load()
        s         = _season_root(data)
        uid       = self.uid
        my_cp     = _get_player_cp(data, uid)
        snum      = str(s.get("current_season", 1))
        player    = data.get("players", {}).get(uid, {})
        user      = (player.get("user", {}) or {}) if isinstance(player, dict) else {}
        has_paid  = bool((user.get("season_pass_paid", {}) or {}).get(snum, False))
        claimed   = list((user.get("season_pass_claimed", {}) or {}).get(snum, []))
        tiers     = sorted((s.get("pass_tiers", {}) or {}).items(),
                           key=lambda x: int(x[1].get("cp_required", 0)))

        current_tier = sum(1 for _, t in tiers if my_cp >= int(t.get("cp_required", 0)))
        next_cp = 0
        for _, t in tiers:
            if my_cp < int(t.get("cp_required", 0)):
                next_cp = int(t.get("cp_required", 0)) - my_cp
                break

        bar = make_bar(my_cp, max(1, int(tiers[min(current_tier, len(tiers)-1)][1].get("cp_required", 1))) if tiers else 1)

        page_tiers = tiers[self.page * 5:(self.page + 1) * 5]
        total_pages = max(1, (len(tiers) + 4) // 5)

        tier_lines = []
        for tid, t in page_tiers:
            cp_req  = int(t.get("cp_required", 0))
            unlocked = my_cp >= cp_req
            free_r   = str(t.get("free_reward", "—"))
            paid_r   = str(t.get("paid_reward", "—"))
            cf       = f"{tid}_free" in claimed
            cp2      = f"{tid}_paid" in claimed
            icon     = "✅" if unlocked else "🔒"
            free_s   = "✅ CLAIMED" if cf else ("CLAIM" if unlocked else f"🔒 {cp_req-my_cp:,} CP away")
            paid_s   = "✅ CLAIMED" if cp2 else ("CLAIM" if (unlocked and has_paid) else ("🔒 Buy Pass" if unlocked else f"🔒"))
            tier_lines.append(
                f"│\n"
                f"│  {'──────────── ' if unlocked else '🔒 '}Tier {tid}  ({cp_req:,} CP){'────────────' if unlocked else ''}\n"
                f"│  🆓  {free_r:<25} {free_s}\n"
                f"│  💎  {paid_r:<25} {paid_s}"
            )

        body = (
            _hdr('🎫  SEASON PASS — ' + s.get('name', 'Season').upper()) + '\n\n'
            f"╭─ 💎 Pass Status\n"
            f"│  Paid Pass:  {'✅ Unlocked' if has_paid else f'❌ Not Unlocked  ({PASS_COST} gems)'}\n"
            f"│  Tier:       {current_tier} / {len(tiers)}\n"
            f"│  CP:         {my_cp:,}\n"
            f"│  {bar}  {my_cp:,} CP\n"
            + (f"│  Next tier:  {next_cp:,} CP away\n" if next_cp else "│  🎉 All tiers unlocked!\n")
            + f"╰────────────────────────────────\n\n"
            f"╭─ 🎁 Rewards  (Page {self.page+1}/{total_pages})\n"
            + "\n".join(tier_lines)
            + "\n╰────────────────────────────────"
        )
        return _inf(body)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return False
        return True

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction) -> None:
        data  = self.cog.bot.storage.load()
        s     = _season_root(data)
        tiers = (s.get("pass_tiers", {}) or {})
        total = max(1, (len(tiers) + 4) // 5)
        self.page = min(total - 1, self.page + 1)
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _on_buy(self, interaction: discord.Interaction) -> None:
        uid = self.uid
        def mutate(data: dict) -> tuple[bool, str]:
            s    = _season_root(data)
            sn   = str(s.get("current_season", 1))
            p    = data.get("players", {}).get(uid, {})
            u    = (p.get("user", {}) or {}) if isinstance(p, dict) else {}
            gems = int(u.get("premium_balance", 0))
            if gems < PASS_COST:
                return False, f"Need {PASS_COST} 💎 gems. You have {gems}."
            u["premium_balance"] = gems - PASS_COST
            u.setdefault("season_pass_paid", {})[sn] = True
            return True, "ok"
        ok, msg = self.cog.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        self._rebuild()
        await interaction.response.edit_message(embed=_ok(
            f"╭─ 💎 Pass Unlocked!\n"
            f"│  You spent {PASS_COST} gems\n"
            f"│  Paid tier rewards are now available!\n"
            f"│  You'll earn 250 gems back through tiers 🎉\n"
            "╰────────────────────────────────"
        ), view=self)

    async def _on_claim(self, interaction: discord.Interaction) -> None:
        uid = self.uid
        def mutate(data: dict) -> tuple[int, list[str]]:
            s    = _season_root(data)
            sn   = str(s.get("current_season", 1))
            p    = data.get("players", {}).get(uid, {})
            u    = (p.get("user", {}) or {}) if isinstance(p, dict) else {}
            cp   = _get_player_cp(data, uid)
            hp   = bool((u.get("season_pass_paid", {}) or {}).get(sn, False))
            cl   = u.setdefault("season_pass_claimed", {}).setdefault(sn, [])
            ts   = s.get("pass_tiers", {}) or {}
            count = 0
            rewards_given = []
            for tid, t in ts.items():
                if cp < int(t.get("cp_required", 0)): continue
                if f"{tid}_free" not in cl:
                    cl.append(f"{tid}_free")
                    desc = _grant_reward(data, uid, str(t.get("free_reward", "")))
                    rewards_given.append(desc)
                    count += 1
                if hp and f"{tid}_paid" not in cl:
                    cl.append(f"{tid}_paid")
                    desc = _grant_reward(data, uid, str(t.get("paid_reward", "")))
                    rewards_given.append(desc)
                    count += 1
            return count, rewards_given
        count, rewards = self.cog.bot.storage.with_lock(mutate)
        if count == 0:
            await interaction.response.send_message("Nothing to claim right now.", ephemeral=True)
            return
        reward_text = "\n".join(f"│  {r}" for r in rewards[:10])
        self._rebuild()
        await interaction.response.edit_message(
            embed=_ok(
                f"╭─ ✅ Claimed {count} Rewards!\n"
                f"{reward_text}\n"
                "╰────────────────────────────────"
            ),
            view=self,
        )


# ── Mission Panel ─────────────────────────────────────────────────

class MissionPanel(discord.ui.View):
    def __init__(self, cog: "SeasonCog", uid: str) -> None:
        super().__init__(timeout=180)
        self.cog  = cog
        self.uid  = uid
        self.message: discord.Message | None = None
        claim_btn = discord.ui.Button(label="🎁 Claim All Ready", style=discord.ButtonStyle.success, row=0)
        claim_btn.callback = self._on_claim
        self.add_item(claim_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return False
        return True

    def build_embed(self, data: dict[str, Any]) -> discord.Embed:
        s        = _season_root(data)
        uid      = self.uid
        snum     = str(s.get("current_season", 1))
        missions = s.get("missions", {}) or {}
        player   = data.get("players", {}).get(uid, {})
        user     = (player.get("user", {}) or {}) if isinstance(player, dict) else {}
        has_paid = bool((user.get("season_pass_paid", {}) or {}).get(snum, False))

        # Group missions by period
        groups: dict[str, list] = {"daily": [], "weekly": [], "monthly": [], "season": []}
        for mid, m in missions.items():
            if not isinstance(m, dict): continue
            period = str(m.get("period", "season"))
            groups.setdefault(period, []).append((mid, m))

        def _mission_lines(mlist: list, period: str) -> list[str]:
            lines = []
            pk    = _reset_key(period)
            prog_root  = (user.get("mission_progress", {}) or {})
            claim_root = (user.get("mission_claimed", {}) or {})
            m_prog   = (prog_root.get(f"{snum}_{period}_{pk}", {}) or {})
            m_claimed= (claim_root.get(f"{snum}_{period}_{pk}", []) or [])
            for mid, m in mlist:
                is_paid  = str(m.get("type", "free")) == "paid"
                title    = str(m.get("title", mid))
                target   = int(m.get("target", 1))
                cp_r     = int(m.get("reward_cp", 0))
                progress = int(m_prog.get(mid, 0))
                claimed  = mid in m_claimed
                if is_paid and not has_paid and not claimed:
                    lines.append(f"│  🔒  {title:<28} +{cp_r} CP  [Paid]")
                    continue
                bar  = make_bar(progress, target, 8)
                if claimed:
                    status = "✅"
                elif progress >= target:
                    status = "🎁 CLAIM"
                else:
                    status = f"{progress}/{target}"
                icon = e("ok",data) if claimed else (e("reward",data) if progress >= target else e("timer",data))
                lines.append(f"│  {icon}  {title:<28} +{cp_r} CP    {status}")
            return lines or ["│  No missions."]

        period_icons = {"daily": "🌅 Daily", "weekly": "📅 Weekly", "monthly": "🗓️ Monthly", "season": "🌟 Season"}
        sections = []
        for period in ["daily", "weekly", "monthly", "season"]:
            mlist = groups.get(period, [])
            if not mlist: continue
            reset_str = f"  (resets in {_time_until_reset(period)})" if period != "season" else ""
            header = f"╭─ {period_icons[period]}{reset_str}"
            lines  = _mission_lines(mlist, period)
            sections.append(header + "\n" + "\n".join(lines) + "\n╰────────────────────────────────")

        body = (
            f"{_hdr('📋  SEASON MISSIONS')}\n\n"
            + "\n\n".join(sections)
        )
        return _inf(body)

    async def _on_claim(self, interaction: discord.Interaction) -> None:
        uid = self.uid
        def mutate(data: dict) -> tuple[int, int]:
            s    = _season_root(data)
            snum = str(s.get("current_season", 1))
            ms   = s.get("missions", {}) or {}
            p    = data.get("players", {}).get(uid, {})
            u    = (p.get("user", {}) or {}) if isinstance(p, dict) else {}
            hp   = bool((u.get("season_pass_paid", {}) or {}).get(snum, False))
            scp  = u.setdefault("season_cp", {})
            total_cp = 0
            count    = 0
            for mid, m in ms.items():
                if not isinstance(m, dict): continue
                period = str(m.get("period", "season"))
                pk     = _reset_key(period)
                key    = f"{snum}_{period}_{pk}"
                prog   = (u.get("mission_progress", {}) or {}).get(key, {}) or {}
                mc     = u.setdefault("mission_claimed", {}).setdefault(key, [])
                if mid in mc: continue
                is_p   = str(m.get("type","free")) == "paid"
                if is_p and not hp: continue
                tgt    = int(m.get("target", 1))
                prg    = int(prog.get(mid, 0))
                if prg < tgt: continue
                mc.append(mid)
                cp_r   = int(m.get("reward_cp", 0))
                scp[snum] = int(scp.get(snum, 0)) + cp_r
                total_cp += cp_r
                count    += 1
            return count, total_cp

        cnt, tcp = self.cog.bot.storage.with_lock(mutate)
        data = self.cog.bot.storage.load()
        if cnt == 0:
            await interaction.response.send_message("Nothing to claim right now.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=_ok(
                f"╭─ ✅ Claimed {cnt} Missions!\n"
                f"│  🎯 +{tcp:,} Season CP earned\n"
                "╰────────────────────────────────"
            ),
            view=self,
        )


# ── Cog ───────────────────────────────────────────────────────────

class SeasonCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _check_daily_login(self, data: dict[str, Any], user_id: str) -> None:
        """Auto-complete daily login mission on any command."""
        try:
            s = _season_root(data)
            if not s.get("active"): return
            snum   = str(s.get("current_season", 1))
            ms     = s.get("missions", {}) or {}
            period = "daily"
            pk     = _reset_key(period)
            key    = f"{snum}_{period}_{pk}"
            p      = data.get("players", {}).get(str(user_id), {})
            u      = (p.get("user", {}) or {}) if isinstance(p, dict) else {}
            mp     = u.setdefault("mission_progress", {}).setdefault(key, {})
            for mid, m in ms.items():
                if not isinstance(m, dict): continue
                if str(m.get("requirement","")) == "daily_login" and str(m.get("period","")) == "daily":
                    if int(mp.get(mid, 0)) < 1:
                        mp[mid] = 1
        except Exception:
            pass

    @app_commands.command(name="season", description="View current season info, pass, and missions.")
    async def season(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        def mutate(data: dict) -> None:
            self._check_daily_login(data, str(interaction.user.id))
        self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        s    = _season_root(data)
        if not s.get("active"):
            await smart_reply(interaction, embed=_inf(
                f"{_hdr('🌟  SEASON')}\n\n"
                "╭─ No Active Season\n│  No season is running right now.\n│  Check back soon!\n╰────────────────────────────────"
            ))
            return
        uid = str(interaction.user.id)

        class SeasonNav(discord.ui.View):
            def __init__(nav_self) -> None:
                super().__init__(timeout=120)

            @discord.ui.button(label="🌟 Season Info", style=discord.ButtonStyle.primary, row=0)
            async def info_btn(nav_self, i: discord.Interaction, _: discord.ui.Button) -> None:
                data2 = self.bot.storage.load()
                await i.response.edit_message(embed=_build_season_embed(data2, uid), view=nav_self)

            @discord.ui.button(label="🎫 Season Pass", style=discord.ButtonStyle.secondary, row=0)
            async def pass_btn(nav_self, i: discord.Interaction, _: discord.ui.Button) -> None:
                panel = PassPanel(self, uid)
                await i.response.edit_message(embed=panel._build_embed(), view=panel)
                panel.message = await i.original_response()

            @discord.ui.button(label="📋 Missions", style=discord.ButtonStyle.secondary, row=0)
            async def missions_btn(nav_self, i: discord.Interaction, _: discord.ui.Button) -> None:
                data2 = self.bot.storage.load()
                panel = MissionPanel(self, uid)
                await i.response.edit_message(embed=panel.build_embed(data2), view=panel)
                panel.message = await i.original_response()

        await smart_reply(interaction, embed=_build_season_embed(data, uid), view=SeasonNav())

    @app_commands.command(name="season_pass", description="View and claim your season pass rewards.")
    async def season_pass(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()
        s    = _season_root(data)
        if not s.get("active"):
            await error_reply(interaction, embed=_err("╭─ ❌ No Active Season\n╰────────────────────────────────"))
            return
        panel = PassPanel(self, str(interaction.user.id))
        await smart_reply(interaction, embed=panel._build_embed(), view=panel)
        panel.message = await interaction.original_response()

    @app_commands.command(name="season_missions", description="View daily, weekly and monthly missions.")
    async def season_missions(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        def mutate(data: dict) -> None:
            self._check_daily_login(data, str(interaction.user.id))
        self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        s    = _season_root(data)
        if not s.get("active"):
            await error_reply(interaction, embed=_err("╭─ ❌ No Active Season\n╰────────────────────────────────"))
            return
        panel = MissionPanel(self, str(interaction.user.id))
        await smart_reply(interaction, embed=panel.build_embed(data), view=panel)
        panel.message = await interaction.original_response()

    # ── Owner commands ─────────────────────────────────────────────

    @app_commands.command(name="o_season_create", description="Owner: start a new season.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_season_create(self, interaction: discord.Interaction, name: str, duration_days: app_commands.Range[int, 1, 365] = 90, reset: str = "both") -> None:
        from bot.utils.checks import is_owner
        if not is_owner(interaction): await error_reply(interaction, embed=_err("❌ Owner only.")); return
        def mutate(data: dict) -> None:
            s = _season_root(data)
            s["active"] = True; s["name"] = name.strip()
            s["start_time"] = now_ts(); s["end_time"] = now_ts() + duration_days * 86400
            s["reset_type"] = reset
            s["pass_tiers"] = s.get("pass_tiers") or {}
            s["missions"]   = s.get("missions") or {}
        self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load(); s = _season_root(data)
        await smart_reply(interaction, embed=_ok(
            f"╭─ ✅ Season Created!\n│  📅 {name}\n│  Start: {_fmt_date(int(s['start_time']))}\n│  End:   {_fmt_date(int(s['end_time']))}\n│  🔄 Reset: {reset.title()}\n│  ⏳ {duration_days} days\n╰────────────────────────────────"
        ), ephemeral=True)

    @app_commands.command(name="o_season_end", description="Owner: end the current season.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_season_end(self, interaction: discord.Interaction) -> None:
        from bot.utils.checks import is_owner
        if not is_owner(interaction): await error_reply(interaction, embed=_err("❌ Owner only.")); return
        def mutate(data: dict) -> tuple[bool, int]:
            s = _season_root(data)
            if not s.get("active"): return False, 0
            snum  = str(s.get("current_season", 1)); reset = str(s.get("reset_type","both"))
            count = 0
            for p in data.get("players", {}).values():
                if not isinstance(p, dict): continue
                u = p.get("user", {})
                if not isinstance(u, dict): continue
                if "both" in reset or "trophies" in reset: u["trophies"] = 0
                if "both" in reset or "rank" in reset: u["rank"] = "Copper"
                u.setdefault("season_cp", {})[snum] = 0; count += 1
            s["active"] = False; s["current_season"] = int(snum) + 1
            return True, count
        ok, count = self.bot.storage.with_lock(mutate)
        if not ok: await error_reply(interaction, embed=_err("❌ No active season.")); return
        await smart_reply(interaction, embed=_ok(f"╭─ 🏁 Season Ended!\n│  🔄 {count} players reset\n│  💾 Archived\n╰────────────────────────────────"), ephemeral=True)

    @app_commands.command(name="o_season_pass_setup", description="Owner: configure a season pass tier.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_season_pass_setup(self, interaction: discord.Interaction, tier: app_commands.Range[int, 1, 100], cp_required: app_commands.Range[int, 0, 9_999_999], free_reward: str, paid_reward: str) -> None:
        from bot.utils.checks import is_owner
        if not is_owner(interaction): await error_reply(interaction, embed=_err("❌ Owner only.")); return
        def mutate(data: dict) -> None:
            _season_root(data).setdefault("pass_tiers", {})[str(tier)] = {"cp_required": cp_required, "free_reward": free_reward, "paid_reward": paid_reward}
        self.bot.storage.with_lock(mutate)
        await smart_reply(interaction, embed=_ok(f"╭─ ✅ Pass Tier Set\n│  Tier {tier}  •  {cp_required:,} CP\n│  🆓 Free: {free_reward}\n│  💎 Paid: {paid_reward}\n╰────────────────────────────────"), ephemeral=True)

    @app_commands.command(name="o_season_add_cp", description="Owner: manually add season CP to a player.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_season_add_cp(self, interaction: discord.Interaction, player: discord.User, amount: app_commands.Range[int, -9_999_999, 9_999_999]) -> None:
        from bot.utils.checks import is_owner
        if not is_owner(interaction): await error_reply(interaction, embed=_err("❌ Owner only.")); return
        uid = str(player.id)
        def mutate(data: dict) -> tuple[bool, int]:
            s = _season_root(data); sn = str(s.get("current_season", 1))
            p = data.get("players", {}).get(uid, {}); u = (p.get("user", {}) or {}) if isinstance(p, dict) else {}
            if not isinstance(u, dict): return False, 0
            scp = u.setdefault("season_cp", {}); scp[sn] = int(scp.get(sn, 0)) + amount
            return True, int(scp[sn])
        ok, total = self.bot.storage.with_lock(mutate)
        if not ok: await error_reply(interaction, embed=_err("❌ Player not found.")); return
        await smart_reply(interaction, embed=_ok(f"╭─ ✅ CP Added\n│  {player.mention}  +{amount:,} CP\n│  Total CP: {total:,}\n╰────────────────────────────────"), ephemeral=True)

    @app_commands.command(name="o_season_mission_create", description="Owner: create a season mission.")
    @app_commands.guilds(OWNER_GUILD)
    @app_commands.choices(mission_type=[app_commands.Choice(name="🆓 Free", value="free"), app_commands.Choice(name="💎 Paid", value="paid")])
    @app_commands.choices(period=[
        app_commands.Choice(name="🌅 Daily",   value="daily"),
        app_commands.Choice(name="📅 Weekly",  value="weekly"),
        app_commands.Choice(name="🗓️ Monthly", value="monthly"),
        app_commands.Choice(name="🌟 Season",  value="season"),
    ])
    @app_commands.choices(requirement=[
        app_commands.Choice(name="Daily Login",          value="daily_login"),
        app_commands.Choice(name="Play battles",         value="battles_played"),
        app_commands.Choice(name="Win ranked battles",   value="ranked_wins"),
        app_commands.Choice(name="Win tournament battles", value="tournament_wins"),
        app_commands.Choice(name="Open packs",           value="packs_opened"),
        app_commands.Choice(name="Complete trades",      value="trades_completed"),
        app_commands.Choice(name="Earn trophies",        value="trophies_earned"),
    ])
    async def o_season_mission_create(self, interaction: discord.Interaction, title: str, mission_type: app_commands.Choice[str], period: app_commands.Choice[str], requirement: app_commands.Choice[str], target: app_commands.Range[int, 1, 9_999_999], reward_cp: app_commands.Range[int, 0, 9_999_999]) -> None:
        from bot.utils.checks import is_owner
        if not is_owner(interaction): await error_reply(interaction, embed=_err("❌ Owner only.")); return
        mid = str(uuid.uuid4())[:8]
        def mutate(data: dict) -> None:
            _season_root(data).setdefault("missions", {})[mid] = {
                "title": title.strip(), "type": mission_type.value, "period": period.value,
                "requirement": requirement.value, "target": int(target), "reward_cp": int(reward_cp),
            }
        self.bot.storage.with_lock(mutate)
        icon = "🆓" if mission_type.value == "free" else "💎"
        await smart_reply(interaction, embed=_ok(
            f"╭─ ✅ Mission Created\n│  {icon} [{period.name}] {title}\n│  Req: {requirement.name} × {target}\n│  Reward: +{reward_cp:,} CP\n╰────────────────────────────────"
        ), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SeasonCog(bot))
