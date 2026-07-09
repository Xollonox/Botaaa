"""Alliance system — gangs forming alliances."""

from __future__ import annotations

import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.alliance_logic import (
    apply_alliance_id_to_gang_members,
    compute_alliance_trophies,
    cooldown_remaining,
    find_alliance_by_name,
    get_gang_alliance_id,
)
from bot.utils.checks import ensure_registered
from bot.utils.gang_logic import find_gang_by_name, get_user_gang, is_head
from bot.utils.timeutil import now_ts
from bot.utils.ui import make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply

MAX_GANGS    = 5
COOLDOWN_SEC = 86400  # 24h

def _embed(desc: str, color: int = 0x2B2D31) -> discord.Embed:
    return make_embed(None, "LOOKISM HXCC • ALLIANCE", desc, color=color, footer="Alliance System")

def _ok(desc: str)  -> discord.Embed: return _embed(desc, 0x2ECC71)
def _err(desc: str) -> discord.Embed: return _embed(desc, 0xE74C3C)
def _inf(desc: str) -> discord.Embed: return _embed(desc, 0x3498DB)


# ── Invite view ───────────────────────────────────────────────────

class AllianceInviteView(discord.ui.View):
    def __init__(self, bot: commands.Bot, invite_id: str, target_head_id: int,
                 alliance_name: str, from_gang: str) -> None:
        super().__init__(timeout=600)
        self.bot            = bot
        self.invite_id      = invite_id
        self.target_head_id = int(target_head_id)
        self.alliance_name  = alliance_name
        self.from_gang      = from_gang

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target_head_id:
            await interaction.response.send_message("This invite isn't for you.", ephemeral=True)
            return False
        return True

    async def _handle(self, interaction: discord.Interaction, accept: bool) -> None:
        actor = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            invites = data.setdefault("alliance_invites", {})
            invite  = invites.get(self.invite_id)
            if not isinstance(invite, dict):
                return False, "Invite not found."
            if str(invite.get("status", "")) != "pending":
                return False, "Invite is no longer pending."
            if int(invite.get("expires_at", 0)) < now_ts():
                invite["status"] = "expired"
                return False, "Invite has expired."
            if not accept:
                invite["status"] = "declined"
                return True, "declined"

            to_gid      = str(invite.get("to_gang_id", ""))
            alliance_id = str(invite.get("alliance_id", ""))
            gangs       = data.get("gangs", {})
            alliances   = data.get("alliances", {})
            to_gang     = gangs.get(to_gid) if isinstance(gangs, dict) else None
            alliance    = alliances.get(alliance_id) if isinstance(alliances, dict) else None

            if not isinstance(to_gang, dict) or not isinstance(alliance, dict):
                invite["status"] = "expired"
                return False, "Alliance or gang no longer exists."
            if str(to_gang.get("leader_id", "")) != actor:
                return False, "Only the Head of your gang can accept."
            if get_gang_alliance_id(data, to_gid):
                return False, "Your gang is already in an alliance."

            gang_ids = alliance.setdefault("gang_ids", [])
            if not isinstance(gang_ids, list):
                alliance["gang_ids"] = []
                gang_ids = alliance["gang_ids"]
            if len(gang_ids) >= MAX_GANGS:
                return False, f"Alliance is full ({MAX_GANGS} gangs max)."
            if to_gid not in [str(g) for g in gang_ids]:
                gang_ids.append(to_gid)
            apply_alliance_id_to_gang_members(data, to_gid, alliance_id)
            invite["status"] = "accepted"
            return True, "accepted"

        ok, result = self.bot.storage.with_lock(mutate)
        self.stop()
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

        if not ok:
            await interaction.response.edit_message(
                embed=_err(f"╭─ ❌ Invite Failed\n│ {result}\n╰────────────────"), view=self)
            return

        if result == "declined":
            await interaction.response.edit_message(
                embed=_inf(f"╭─ ❌ Invite Declined\n│ Declined to join **{self.alliance_name}**.\n╰────────────────"), view=self)
        else:
            await interaction.response.edit_message(
                embed=_ok(f"╭─ ✅ Joined Alliance!\n│ Welcome to **{self.alliance_name}**!\n╰────────────────"), view=self)

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success, row=0)
    async def accept_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle(interaction, True)

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger, row=0)
    async def decline_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle(interaction, False)


# ── Cog ───────────────────────────────────────────────────────────

class AllianceCog(commands.Cog):
    alliance = app_commands.Group(name="alliance", description="Alliance commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _gang_choices(self, data: dict[str, Any], current: str) -> list[app_commands.Choice[str]]:
        gangs = data.get("gangs", {})
        token = current.lower()
        out: list[app_commands.Choice[str]] = []
        for gang in (gangs.values() if isinstance(gangs, dict) else []):
            if not isinstance(gang, dict):
                continue
            name = str(gang.get("name", "")).strip()
            if not name or (token and token not in name.lower()):
                continue
            out.append(app_commands.Choice(name=name[:100], value=name))
            if len(out) >= 25:
                break
        return out

    def _alliance_choices(self, data: dict[str, Any], current: str) -> list[app_commands.Choice[str]]:
        alliances = data.get("alliances", {})
        token = current.lower()
        out: list[app_commands.Choice[str]] = []
        for a in (alliances.values() if isinstance(alliances, dict) else []):
            if not isinstance(a, dict):
                continue
            name = str(a.get("name", "")).strip()
            if not name or (token and token not in name.lower()):
                continue
            out.append(app_commands.Choice(name=name[:100], value=name))
            if len(out) >= 25:
                break
        return out

    # ── /alliance create ──────────────────────────────────────────

    @alliance.command(name="create", description="Create an alliance (Head only).")
    async def alliance_create(self, interaction: discord.Interaction,
                               name: str, description: str = "—") -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            gid, gang = get_user_gang(data, uid)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang."
            if not is_head(gang, uid):
                return False, "Only the gang Head can create an alliance."
            if get_gang_alliance_id(data, gid):
                return False, "Your gang is already in an alliance."

            cooldowns = data.setdefault("alliance_cooldowns", {})
            remaining = cooldown_remaining(int((cooldowns or {}).get(gid, 0)), now_ts())
            if remaining > 0:
                h, m = divmod(remaining // 60, 60)
                return False, f"Cooldown active: {h}h {m}m remaining."

            name_clean = name.strip()
            if not name_clean or len(name_clean) > 40:
                return False, "Alliance name must be 1–40 characters."
            if find_alliance_by_name(data, name_clean)[0]:
                return False, f"**{name_clean}** already exists."

            aid = str(uuid.uuid4())
            data.setdefault("alliances", {})[aid] = {
                "alliance_id":    aid,
                "name":           name_clean,
                "description":    str(description).strip() or "—",
                "founder_gang_id":gid,
                "gang_ids":       [gid],
                "created_at":     now_ts(),
            }
            apply_alliance_id_to_gang_members(data, gid, aid)
            return True, name_clean

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Alliance Create Failed\n│ {result}\n╰────────────────"))
            return
        data = self.bot.storage.load()
        gid, gang = get_user_gang(data, uid)
        await smart_reply(interaction, embed=_ok(
            f"╭─ 🤝 Alliance Created!\n"
            f"│ Name: **{result}**\n"
            f"│ 📝 {description}\n"
            f"│ 👑 Founded by: {gang.get('name','?') if gang else '?'}\n"
            f"│ 📊 Gangs: 1/{MAX_GANGS}\n"
            "╰────────────────"
        ))

    # ── /alliance info ────────────────────────────────────────────

    @alliance.command(name="info", description="Show alliance info.")
    async def alliance_info(self, interaction: discord.Interaction, alliance_name: str | None = None) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()

        aid      = None
        alliance = None
        if alliance_name:
            aid, alliance = find_alliance_by_name(data, alliance_name)
        else:
            gid, _ = get_user_gang(data, str(interaction.user.id))
            if gid:
                aid = get_gang_alliance_id(data, gid)
                if aid:
                    alliance = data.get("alliances", {}).get(aid)

        if not aid or not isinstance(alliance, dict):
            await error_reply(interaction, embed=_err("╭─ ❌ Not Found\n│ Alliance not found.\n╰────────────────"))
            return

        gangs     = data.get("gangs", {})
        gang_ids  = [str(g) for g in (alliance.get("gang_ids") or [])]
        total_t   = compute_alliance_trophies(data, alliance)
        desc      = str(alliance.get("description", "—"))

        gang_lines = []
        for gid in gang_ids:
            gang = gangs.get(gid, {}) if isinstance(gangs, dict) else {}
            if not isinstance(gang, dict):
                continue
            members = gang.get("members", []) or []
            trophies = sum(
                int((data.get("players", {}).get(str(m), {}).get("user") or {}).get("trophies", 0))
                for m in members
            )
            gang_lines.append(f"│ ⚔️ {gang.get('name','?'):<20} {trophies:,} 🏆")

        body = (
            f"╭─ 🤝 {alliance.get('name','?')}\n"
            f"│ 📝 {desc}\n"
            f"│ 📊 {len(gang_ids)}/{MAX_GANGS} Gangs  •  {total_t:,} 🏆\n"
            "│\n"
            + "\n".join(gang_lines)
            + "\n╰────────────────"
        )
        await smart_reply(interaction, embed=_inf(body))

    # ── /alliance invite ──────────────────────────────────────────

    @alliance.command(name="invite", description="Invite a gang to your alliance (Head only).")
    async def alliance_invite(self, interaction: discord.Interaction, gang_name: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str | None, str | None, str]:
            my_gid, my_gang = get_user_gang(data, uid)
            if not my_gid or not isinstance(my_gang, dict):
                return False, "You are not in a gang.", None, None, ""
            if not is_head(my_gang, uid):
                return False, "Only the gang Head can send alliance invites.", None, None, ""
            aid = get_gang_alliance_id(data, my_gid)
            if not aid:
                return False, "Your gang is not in an alliance. Create one first.", None, None, ""
            alliance = data.get("alliances", {}).get(aid, {})
            gang_ids = [str(g) for g in (alliance.get("gang_ids") or [])]
            if len(gang_ids) >= MAX_GANGS:
                return False, f"Alliance is full ({MAX_GANGS} gangs max).", None, None, ""

            tgid, tgang = find_gang_by_name(data, gang_name)
            if not tgid or not isinstance(tgang, dict):
                return False, f"Gang **{gang_name}** not found.", None, None, ""
            if tgid == my_gid:
                return False, "Cannot invite your own gang.", None, None, ""
            if get_gang_alliance_id(data, tgid):
                return False, f"**{gang_name}** is already in an alliance.", None, None, ""

            target_head = str(tgang.get("leader_id", ""))
            if not target_head:
                return False, "Target gang has no Head.", None, None, ""

            iid = str(uuid.uuid4())
            data.setdefault("alliance_invites", {})[iid] = {
                "invite_id":    iid,
                "alliance_id":  aid,
                "from_gang_id": my_gid,
                "to_gang_id":   tgid,
                "created_at":   now_ts(),
                "expires_at":   now_ts() + 600,
                "status":       "pending",
            }
            a_name = str(alliance.get("name", ""))
            return True, "ok", iid, target_head, a_name

        ok, msg, iid, target_head_id, a_name = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Invite Failed\n│ {msg}\n╰────────────────"))
            return

        data = self.bot.storage.load()
        gid, my_gang = get_user_gang(data, uid)
        my_gang_name = my_gang.get("name", "?") if my_gang else "?"

        view  = AllianceInviteView(self.bot, iid, int(target_head_id), a_name, my_gang_name)
        embed = _inf(
            f"╭─ 📨 Alliance Invite\n"
            f"│ From: **{my_gang_name}** → **{gang_name}**\n"
            f"│ Alliance: **{a_name}**\n"
            f"│ ⏳ Expires: 10 minutes\n"
            "╰────────────────"
        )
        try:
            user = await self.bot.fetch_user(int(target_head_id))
            await user.send(embed=embed, view=view)
        except Exception:
            if interaction.channel:
                await interaction.channel.send(content=f"<@{target_head_id}>", embed=embed, view=view)

        await smart_reply(interaction, embed=_ok(
            f"╭─ 📨 Alliance Invite Sent\n"
            f"│ To: **{gang_name}**\n"
            f"│ Alliance: **{a_name}**\n"
            f"│ ⏳ Expires: 10 minutes\n"
            "╰────────────────"
        ))

    # ── /alliance leave ───────────────────────────────────────────

    @alliance.command(name="leave", description="Leave your alliance (Head only).")
    async def alliance_leave(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str]:
            gid, gang = get_user_gang(data, uid)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang.", ""
            if not is_head(gang, uid):
                return False, "Only the gang Head can leave an alliance.", ""
            aid = get_gang_alliance_id(data, gid)
            if not aid:
                return False, "Your gang is not in an alliance.", ""
            alliances = data.get("alliances", {})
            alliance  = alliances.get(aid, {}) if isinstance(alliances, dict) else {}
            if not isinstance(alliance, dict):
                return False, "Alliance not found.", ""
            a_name   = str(alliance.get("name", ""))
            gang_ids = [str(g) for g in (alliance.get("gang_ids") or [])]
            alliance["gang_ids"] = [g for g in gang_ids if g != gid]
            apply_alliance_id_to_gang_members(data, gid, None)
            cooldowns = data.setdefault("alliance_cooldowns", {})
            if isinstance(cooldowns, dict):
                cooldowns[gid] = now_ts() + COOLDOWN_SEC
            if not alliance["gang_ids"] and isinstance(alliances, dict):
                alliances.pop(aid, None)
            return True, a_name, str(gang.get("name", ""))

        ok, a_name, gang_name = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Leave Failed\n│ {a_name}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_inf(
            f"╭─ 👋 Left Alliance\n"
            f"│ **{gang_name}** left **{a_name}**\n"
            f"│ ⚠️ Cannot join any alliance for 24h\n"
            "╰────────────────"
        ))

    # ── Autocomplete ──────────────────────────────────────────────

    @alliance_invite.autocomplete("gang_name")
    async def alliance_invite_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return self._gang_choices(self.bot.storage.load(), current)

    @alliance_info.autocomplete("alliance_name")
    async def alliance_info_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return self._alliance_choices(self.bot.storage.load(), current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AllianceCog(bot))
