"""Gang system — positions, invites, management."""

from __future__ import annotations

import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import ensure_registered
from bot.utils.gang_logic import (
    GANG_CREATION_COST, MAX_MEMBERS, ROLE_ICONS, ROLE_LABELS, ROLE_ORDER,
    can_kick, can_promote, enforce_max_members, find_gang_by_name,
    format_member_line, get_role, get_role_icon, get_role_label,
    get_user_gang, has_permission_invite, is_head, remove_from_gang, set_role,
)
from bot.utils.timeutil import now_ts
from bot.utils.ui import make_embed, e
from bot.utils.interaction_visibility import smart_reply, error_reply

SEP = "━" * 28

def _embed(desc: str, color: int = 0x2B2D31) -> discord.Embed:
    return make_embed(None, "LOOKISM HXCC • GANGS", desc, color=color, footer="Gang System")

def _ok(desc: str)  -> discord.Embed: return _embed(desc, 0x2ECC71)
def _err(desc: str) -> discord.Embed: return _embed(desc, 0xE74C3C)
def _inf(desc: str) -> discord.Embed: return _embed(desc, 0x3498DB)


# ── Invite view ───────────────────────────────────────────────────

class GangInviteView(discord.ui.View):
    def __init__(self, bot: commands.Bot, invite_id: str, target_id: int, gang_name: str) -> None:
        super().__init__(timeout=600)
        self.bot       = bot
        self.invite_id = invite_id
        self.target_id = int(target_id)
        self.gang_name = gang_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target_id:
            await interaction.response.send_message("This invite isn't for you.", ephemeral=True)
            return False
        return True

    async def _handle(self, interaction: discord.Interaction, accept: bool) -> None:
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            invites = data.setdefault("gang_invites", {})
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

            gang_id = str(invite.get("gang_id", ""))
            gangs   = data.get("gangs", {})
            gang    = gangs.get(gang_id) if isinstance(gangs, dict) else None
            if not isinstance(gang, dict):
                invite["status"] = "expired"
                return False, "Gang no longer exists."
            if not enforce_max_members(gang):
                return False, "Gang is full."

            player = data.get("players", {}).get(uid, {})
            if not isinstance(player, dict):
                return False, "Player not found."
            if player.get("gang_id"):
                return False, "You are already in a gang."

            members = gang.setdefault("members", [])
            if uid not in [str(m) for m in members]:
                members.append(uid)
            player["gang_id"] = gang_id
            invite["status"]  = "accepted"
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
                embed=_inf(f"╭─ ❌ Invite Declined\n│ You declined to join **{self.gang_name}**.\n╰────────────────"), view=self)
        else:
            await interaction.response.edit_message(
                embed=_ok(f"╭─ ✅ Joined Gang!\n│ Welcome to **{self.gang_name}**!\n│ 👤 Role: Member\n╰────────────────"), view=self)

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success, row=0)
    async def accept_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle(interaction, True)

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger, row=0)
    async def decline_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle(interaction, False)


# ── Cog ───────────────────────────────────────────────────────────

class GangsCog(commands.Cog):
    gang = app_commands.Group(name="gang", description="Gang commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _member_choices(self, data: dict[str, Any], user_id: str, current: str, exclude_self: bool = True) -> list[app_commands.Choice[str]]:
        gid, gang = get_user_gang(data, user_id)
        if not gang:
            return []
        players = data.get("players", {})
        token   = current.lower()
        out: list[app_commands.Choice[str]] = []
        for uid in (gang.get("members", []) or []):
            uid = str(uid)
            if exclude_self and uid == str(user_id):
                continue
            player = players.get(uid, {}) if isinstance(players, dict) else {}
            name   = str((player.get("user") or {}).get("name", uid))
            role   = get_role_label(gang, uid)
            icon   = get_role_icon(gang, uid)
            label  = f"{icon} {name}  [{role}]"
            if token and token not in label.lower():
                continue
            out.append(app_commands.Choice(name=label[:100], value=uid))
            if len(out) >= 25:
                break
        return out

    def _all_gang_choices(self, data: dict[str, Any], current: str) -> list[app_commands.Choice[str]]:
        gangs = data.get("gangs", {})
        token = current.lower()
        out: list[app_commands.Choice[str]] = []
        for gang in (gangs.values() if isinstance(gangs, dict) else []):
            if not isinstance(gang, dict):
                continue
            name = str(gang.get("name", ""))
            if not name or (token and token not in name.lower()):
                continue
            out.append(app_commands.Choice(name=name[:100], value=name))
            if len(out) >= 25:
                break
        return out

    # ── /gang create ──────────────────────────────────────────────

    @gang.command(name="create", description=f"Create a gang (costs {GANG_CREATION_COST:,} coins).")
    async def gang_create(self, interaction: discord.Interaction, name: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            name_clean = name.strip()
            if not name_clean or len(name_clean) > 32:
                return False, "Gang name must be 1–32 characters."
            if find_gang_by_name(data, name_clean)[0]:
                return False, f"**{name_clean}** already exists."
            player = data.get("players", {}).get(uid, {})
            if not isinstance(player, dict):
                return False, "Player not found."
            if player.get("gang_id"):
                return False, "You are already in a gang."
            user = player.get("user", {})
            bal  = int((user or {}).get("balance", 0))
            if bal < GANG_CREATION_COST:
                return False, f"Need {GANG_CREATION_COST:,} coins. You have {bal:,}."
            user["balance"] = bal - GANG_CREATION_COST
            gid = str(uuid.uuid4())
            data.setdefault("gangs", {})[gid] = {
                "gang_id":    gid,
                "name":       name_clean,
                "leader_id":  uid,
                "members":    [uid],
                "roles":      {},
                "description":"",
                "status":     "open",
                "wins":       0,
                "losses":     0,
                "created_at": now_ts(),
            }
            player["gang_id"] = gid
            return True, name_clean

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Gang Create Failed\n│ {result}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_ok(
            f"╭─ ⚔️ Gang Created!\n"
            f"│ Name: {result}\n"
            f"│ 💰 Cost: -{GANG_CREATION_COST:,} coins\n"
            f"│ 👑 Role: Head\n"
            f"│ 📊 Members: 1/{MAX_MEMBERS}\n"
            "╰────────────────"
        ))

    # ── /gang info ────────────────────────────────────────────────

    @gang.command(name="info", description="Show gang info.")
    async def gang_info(self, interaction: discord.Interaction, gang_name: str | None = None) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()
        if gang_name:
            gid, gang = find_gang_by_name(data, gang_name)
        else:
            gid, gang = get_user_gang(data, str(interaction.user.id))

        if not gid or not isinstance(gang, dict):
            await error_reply(interaction, embed=_err("╭─ ❌ Not Found\n│ Gang not found.\n╰────────────────"))
            return

        members = gang.get("members", []) or []
        head_id = str(gang.get("leader_id", ""))
        status  = str(gang.get("status", "open")).title()
        status_icon = e("unlock", data) if status.lower() == "open" else e("lock", data)
        desc    = str(gang.get("description", "")) or "—"

        # Alliance info
        from bot.utils.alliance_logic import get_gang_alliance_id
        alliance_block = ""
        aid = get_gang_alliance_id(data, gid)
        if aid:
            alliance = data.get("alliances", {}).get(aid, {})
            if isinstance(alliance, dict):
                from bot.utils.alliance_logic import compute_alliance_trophies
                a_gangs  = len(alliance.get("gang_ids", []))
                a_trophy = compute_alliance_trophies(data, alliance)
                alliance_block = (
                    f"\n\n╭─ 🤝 Alliance\n"
                    f"│ {alliance.get('name','?')}\n"
                    f"│ {a_gangs} gangs  •  {a_trophy:,} 🏆\n"
                    "╰────────────────"
                )

        body = (
            f"╭─ ⚔️ {gang.get('name','?')}\n"
            f"│ 👑 Head: <@{head_id}>\n"
            f"│ 📊 Members: {len(members)}/{MAX_MEMBERS}\n"
            f"│ {status_icon} Status: {status}\n"
            f"│ 📜 {desc}\n"
            "╰────────────────"
            + alliance_block
        )
        await smart_reply(interaction, embed=_inf(body))

    # ── /gang invite ──────────────────────────────────────────────

    @gang.command(name="invite", description="Invite a user to your gang.")
    async def gang_invite(self, interaction: discord.Interaction, user: discord.User) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        actor_id  = str(interaction.user.id)
        target_id = str(user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str | None, str]:
            gid, gang = get_user_gang(data, actor_id)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang.", None, ""
            if not has_permission_invite(gang, actor_id):
                return False, "Only Head, Vice Head and Recruiters can invite.", None, ""
            if not enforce_max_members(gang):
                return False, f"Gang is full ({MAX_MEMBERS} members max).", None, ""
            target = data.get("players", {}).get(target_id, {})
            if not isinstance(target, dict):
                return False, f"{user.mention} is not registered.", None, ""
            if target.get("gang_id"):
                return False, f"{user.mention} is already in a gang.", None, ""
            iid = str(uuid.uuid4())
            data.setdefault("gang_invites", {})[iid] = {
                "invite_id":  iid,
                "gang_id":    gid,
                "from_id":    actor_id,
                "to_id":      target_id,
                "created_at": now_ts(),
                "expires_at": now_ts() + 600,
                "status":     "pending",
            }
            return True, "ok", iid, str(gang.get("name", ""))

        ok, msg, iid, gang_name = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Invite Failed\n│ {msg}\n╰────────────────"))
            return

        view = GangInviteView(self.bot, iid, user.id, gang_name)
        embed = _inf(
            f"╭─ 📨 Gang Invite\n"
            f"│ From: {interaction.user.mention} → {user.mention}\n"
            f"│ Gang: **{gang_name}**\n"
            f"│ ⏳ Expires: 10 minutes\n"
            "╰────────────────"
        )
        # Always try DM first, fallback to channel
        try:
            await user.send(embed=embed, view=view)
        except (discord.Forbidden, discord.HTTPException):
            if interaction.channel:
                await interaction.channel.send(
                    content=f"{user.mention} you have a gang invite! (Enable DMs to receive invites directly)",
                    embed=embed,
                    view=view,
                )

        await smart_reply(interaction, embed=_ok(
            f"╭─ 📨 Invite Sent\n"
            f"│ To: {user.mention}\n"
            f"│ Gang: **{gang_name}**\n"
            f"│ ⏳ Expires: 10 minutes\n"
            "╰────────────────"
        ))

    # ── /gang join ────────────────────────────────────────────────

    @gang.command(name="join", description="Join an open gang.")
    async def gang_join(self, interaction: discord.Interaction, gang_name: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            gid, gang = find_gang_by_name(data, gang_name)
            if not gid or not isinstance(gang, dict):
                return False, f"**{gang_name}** not found."
            if str(gang.get("status", "open")) != "open":
                return False, f"**{gang_name}** is closed."
            if not enforce_max_members(gang):
                return False, "Gang is full."
            player = data.get("players", {}).get(uid, {})
            if not isinstance(player, dict):
                return False, "Player not found."
            if player.get("gang_id"):
                return False, "You are already in a gang."
            members = gang.setdefault("members", [])
            if uid not in [str(m) for m in members]:
                members.append(uid)
            player["gang_id"] = gid
            return True, str(gang.get("name", gang_name))

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Join Failed\n│ {result}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_ok(
            f"╭─ ✅ Joined Gang!\n"
            f"│ Welcome to **{result}**!\n"
            f"│ 👤 Role: Member\n"
            "╰────────────────"
        ))

    # ── /gang leave ───────────────────────────────────────────────

    @gang.command(name="leave", description="Leave your gang.")
    async def gang_leave(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        uid = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str]:
            gid, gang = get_user_gang(data, uid)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang.", ""
            if is_head(gang, uid):
                return False, "Head must transfer ownership first.", ""
            role = get_role_label(gang, uid)
            remove_from_gang(gang, uid)
            player = data.get("players", {}).get(uid, {})
            if isinstance(player, dict):
                player["gang_id"]    = None
                player["alliance_id"] = None
            return True, role, str(gang.get("name", ""))

        ok, role, gang_name = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Leave Failed\n│ {role}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_inf(
            f"╭─ 👋 Left Gang\n"
            f"│ You left **{gang_name}**\n"
            f"│ Your role was: {role}\n"
            "╰────────────────"
        ))

    # ── /gang kick ────────────────────────────────────────────────

    @gang.command(name="kick", description="Kick a member from your gang.")
    async def gang_kick(self, interaction: discord.Interaction, user_id: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        actor  = str(interaction.user.id)
        target = str(user_id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str]:
            gid, gang = get_user_gang(data, actor)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang.", ""
            members = [str(m) for m in (gang.get("members") or [])]
            if target not in members:
                return False, "That player is not in your gang.", ""
            ok, err = can_kick(gang, actor, target)
            if not ok:
                return False, err, ""
            _pu = (data.get("players", {}).get(target) or {})
            _uu = (_pu.get("user") or {})
            target_name = str(_uu.get("name") or _uu.get("username") or f"<@{target}>")
            remove_from_gang(gang, target)
            player = data.get("players", {}).get(target, {})
            if isinstance(player, dict):
                player["gang_id"]    = None
                player["alliance_id"] = None
            return True, target_name, str(gang.get("name", ""))

        ok, result, gang_name = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Kick Failed\n│ {result}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_ok(
            f"╭─ 🚫 Member Kicked\n"
            f"│ @{result} removed from **{gang_name}**\n"
            f"│ By: {interaction.user.mention}\n"
            "╰────────────────"
        ))

    # ── /gang promote ─────────────────────────────────────────────

    @gang.command(name="promote", description="Promote a member to a higher role.")
    @app_commands.choices(role=[
        app_commands.Choice(name="⚔️ Vice Head",  value="vice"),
        app_commands.Choice(name="📣 Recruiter",  value="recruiter"),
        app_commands.Choice(name="🏅 Elder",       value="elder"),
    ])
    async def gang_promote(self, interaction: discord.Interaction, user_id: str, role: app_commands.Choice[str]) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        actor  = str(interaction.user.id)
        target = str(user_id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str, str]:
            gid, gang = get_user_gang(data, actor)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang.", ""
            if not can_promote(gang, actor):
                return False, "Only Head and Vice Head can promote.", ""
            if role.value == "vice" and not is_head(gang, actor):
                return False, "Only Head can assign Vice Head.", ""
            members = [str(m) for m in (gang.get("members") or [])]
            if target not in members:
                return False, "That player is not in your gang.", ""
            if is_head(gang, target):
                return False, "Cannot change the Head's role.", ""
            set_role(gang, target, role.value)
            _pu = (data.get("players", {}).get(target) or {})
            _uu = (_pu.get("user") or {})
            target_name = str(_uu.get("name") or _uu.get("username") or f"<@{target}>")
            return True, target_name, ROLE_LABELS.get(role.value, role.value)

        ok, name, role_label = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Promote Failed\n│ {name}\n╰────────────────"))
            return
        icon = ROLE_ICONS.get(role.value, "•")
        await smart_reply(interaction, embed=_ok(
            f"╭─ ⬆️ Member Promoted\n"
            f"│ @{name} → {icon} {role_label}\n"
            f"│ By: {interaction.user.mention}\n"
            "╰────────────────"
        ))

    # ── /gang demote ──────────────────────────────────────────────

    @gang.command(name="demote", description="Demote a member to regular Member.")
    async def gang_demote(self, interaction: discord.Interaction, user_id: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        actor  = str(interaction.user.id)
        target = str(user_id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            gid, gang = get_user_gang(data, actor)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang."
            if not can_promote(gang, actor):
                return False, "Only Head and Vice Head can demote."
            if is_head(gang, target):
                return False, "Cannot demote the Head."
            members = [str(m) for m in (gang.get("members") or [])]
            if target not in members:
                return False, "That player is not in your gang."
            set_role(gang, target, "member")
            _pu = (data.get("players", {}).get(target) or {})
            _uu = (_pu.get("user") or {})
            target_name = str(_uu.get("name") or _uu.get("username") or f"<@{target}>")
            return True, target_name

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Demote Failed\n│ {result}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_ok(
            f"╭─ ⬇️ Member Demoted\n"
            f"│ @{result} → 👤 Member\n"
            f"│ By: {interaction.user.mention}\n"
            "╰────────────────"
        ))

    # ── /gang members ─────────────────────────────────────────────

    @gang.command(name="members", description="List gang members.")
    async def gang_members(self, interaction: discord.Interaction, gang_name: str | None = None) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()
        if gang_name:
            gid, gang = find_gang_by_name(data, gang_name)
        else:
            gid, gang = get_user_gang(data, str(interaction.user.id))
        if not gid or not isinstance(gang, dict):
            await error_reply(interaction, embed=_err("╭─ ❌ Not Found\n│ Gang not found.\n╰────────────────"))
            return

        members = [str(m) for m in (gang.get("members") or [])]
        # Sort by role order
        def role_sort(uid: str) -> int:
            r = get_role(gang, uid)
            return ROLE_ORDER.index(r) if r in ROLE_ORDER else 99

        members_sorted = sorted(members, key=role_sort)
        lines = [format_member_line(data, gang, uid) for uid in members_sorted]
        body  = (
            f"╭─ 👥 {gang.get('name','?')} — Members ({len(members)}/{MAX_MEMBERS})\n"
            + "\n".join(f"│ {l}" for l in lines)
            + "\n╰────────────────"
        )
        await smart_reply(interaction, embed=_inf(body))

    # ── /gang transfer_owner ──────────────────────────────────────

    @gang.command(name="transfer_owner", description="Transfer gang ownership.")
    async def gang_transfer_owner(self, interaction: discord.Interaction, user_id: str) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        actor  = str(interaction.user.id)
        target = str(user_id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            gid, gang = get_user_gang(data, actor)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang."
            if not is_head(gang, actor):
                return False, "Only the Head can transfer ownership."
            members = [str(m) for m in (gang.get("members") or [])]
            if target not in members:
                return False, "That player is not in your gang."
            gang["leader_id"] = target
            set_role(gang, actor, "member")  # old head becomes member
            set_role(gang, target, "head")   # cleared by set_role (head handled by leader_id)
            _pu = (data.get("players", {}).get(target) or {})
            _uu = (_pu.get("user") or {})
            target_name = str(_uu.get("name") or _uu.get("username") or f"<@{target}>")
            return True, target_name

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Transfer Failed\n│ {result}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_ok(
            f"╭─ 👑 Ownership Transferred\n"
            f"│ New Head: @{result}\n"
            f"│ Previous Head: {interaction.user.mention}\n"
            "╰────────────────"
        ))

    # ── /gang set_description ─────────────────────────────────────

    @gang.command(name="set_description", description="Set gang description (Head only).")
    async def gang_set_description(self, interaction: discord.Interaction, text: app_commands.Range[str, 1, 200]) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        actor = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            gid, gang = get_user_gang(data, actor)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang."
            if not is_head(gang, actor):
                return False, "Only the Head can set the description."
            gang["description"] = str(text)
            return True, str(gang.get("name", ""))

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Failed\n│ {result}\n╰────────────────"))
            return
        await smart_reply(interaction, embed=_ok(
            f"╭─ 📝 Description Updated\n"
            f"│ **{result}**\n"
            f'│ "{text}"\n'
            "╰────────────────"
        ))

    # ── /gang set_status ──────────────────────────────────────────

    @gang.command(name="set_status", description="Set gang open/closed (Head only).")
    @app_commands.choices(status=[
        app_commands.Choice(name="🔓 Open",   value="open"),
        app_commands.Choice(name="🔒 Closed", value="closed"),
    ])
    async def gang_set_status(self, interaction: discord.Interaction, status: app_commands.Choice[str]) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        actor = str(interaction.user.id)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            gid, gang = get_user_gang(data, actor)
            if not gid or not isinstance(gang, dict):
                return False, "You are not in a gang."
            if not is_head(gang, actor):
                return False, "Only the Head can change status."
            gang["status"] = str(status.value)
            return True, str(gang.get("name", ""))

        ok, result = self.bot.storage.with_lock(mutate)
        if not ok:
            await error_reply(interaction, embed=_err(f"╭─ ❌ Failed\n│ {result}\n╰────────────────"))
            return
        data = self.bot.storage.load()
        icon = e("unlock", data) if status.value == "open" else e("lock", data)
        await smart_reply(interaction, embed=_ok(
            f"╭─ {icon} Gang Status Updated\n"
            f"│ **{result}** → {status.value.title()}\n"
            "╰────────────────"
        ))

    # ── /gang stats ───────────────────────────────────────────────

    @gang.command(name="stats", description="Show gang stats.")
    async def gang_stats(self, interaction: discord.Interaction) -> None:
        if not await ensure_registered(interaction, self.bot.storage):
            return
        data = self.bot.storage.load()
        gid, gang = get_user_gang(data, str(interaction.user.id))
        if not gid or not isinstance(gang, dict):
            await error_reply(interaction, embed=_err("╭─ ❌ Not in Gang\n│ You are not in a gang.\n╰────────────────"))
            return
        wins    = int(gang.get("wins", 0))
        losses  = int(gang.get("losses", 0))
        total   = wins + losses
        wr      = f"{wins/total*100:.1f}%" if total else "—"
        members = gang.get("members", []) or []
        # Total trophies
        players = data.get("players", {})
        total_trophies = sum(
            int((players.get(str(m), {}).get("user") or {}).get("trophies", 0))
            for m in members
        )
        created = int(gang.get("created_at", 0))
        days    = max(0, (now_ts() - created) // 86400)
        await smart_reply(interaction, embed=_inf(
            f"╭─ 📊 Gang Stats — {gang.get('name','?')}\n"
            f"│ 🏆 Total Trophies: {total_trophies:,}\n"
            f"│ ⚔️ Wars Won: {wins}\n"
            f"│ 💀 Wars Lost: {losses}\n"
            f"│ 📈 Win Rate: {wr}\n"
            f"│ 📅 Active Since: {days}d\n"
            "╰────────────────"
        ))

    # ── Autocomplete ──────────────────────────────────────────────

    @gang_info.autocomplete("gang_name")
    @gang_join.autocomplete("gang_name")
    @gang_members.autocomplete("gang_name")
    async def gang_name_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return self._all_gang_choices(self.bot.storage.load(), current)

    @gang_kick.autocomplete("user_id")
    async def gang_kick_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return self._member_choices(self.bot.storage.load(), str(interaction.user.id), current)

    @gang_promote.autocomplete("user_id")
    @gang_demote.autocomplete("user_id")
    @gang_transfer_owner.autocomplete("user_id")
    async def gang_member_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return self._member_choices(self.bot.storage.load(), str(interaction.user.id), current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GangsCog(bot))
