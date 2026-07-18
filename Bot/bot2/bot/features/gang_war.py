"""Gang War system."""
from __future__ import annotations
import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.checks import ensure_registered, is_owner
from bot.utils.gang_logic import get_user_gang, find_gang_by_name
from bot.utils.squad_logic import get_player
from bot.utils.timeutil import now_ts
from bot.utils.ui import e, make_embed
from bot.utils.interaction_visibility import smart_reply, error_reply
from bot.utils.war_logic import (
    _war_root, PREP_DURATION, BATTLE_DURATION, QUEUE_TIMEOUT,
    get_player_war_pref, get_war_defense_squad, set_war_defense_squad,
    is_in_war_cooldown, get_user_active_war, get_gang_active_war,
    queue_war, find_match, create_war,
    check_phase_transition, is_battle_phase,
    can_attack, record_attack, compute_war_score,
    determine_winner, grant_war_rewards,
)

logger = logging.getLogger(__name__)
SEP = "\u2501" * 32


def _e(desc: str, color: int = 0x9B59B6) -> discord.Embed:
    return make_embed(None, "LOOKISM HXCC • GANG WAR", desc, color=color, footer="Gang Wars")

def _ok(d: str) -> discord.Embed: return _e(d, 0x2ECC71)
def _err(d: str) -> discord.Embed: return _e(d, 0xE74C3C)
def _inf(d: str) -> discord.Embed: return _e(d, 0x9B59B6)

B = "\u256d\u2500"
M = "\u2502"
E = "\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"


def _box(title: str, lines: list[str]) -> str:
    body = "\n".join(f"{M} {l}" for l in lines)
    return f"{B} {title}\n{body}\n{E}"


def _is_hv(gang: dict, uid: str) -> bool:
    roles = gang.get("roles", {}) or {}
    role  = str(roles.get(str(uid), "member")).lower()
    return role in ("head", "vice_head") or str(gang.get("leader_id", "")) == str(uid)


def _tl(ts: int) -> str:
    diff = max(0, ts - now_ts())
    h, r = divmod(diff, 3600)
    return f"{h}h {r // 60}m"


def _phase_end(war: dict) -> int:
    started = int(war.get("phase_started_at", 0))
    fmt     = int(war.get("format", 10))
    if fmt == 2:
        dur = 300 if war.get("phase") == "prep" else 600
    else:
        dur = PREP_DURATION if war.get("phase") == "prep" else BATTLE_DURATION
    return started + dur


def _status_embed(data: dict, wid: str, war: dict) -> discord.Embed:
    fmt    = int(war.get("format", 10))
    ga     = data.get("gangs", {}).get(war.get("gang_a", ""), {}) or {}
    gb     = data.get("gangs", {}).get(war.get("gang_b", ""), {}) or {}
    na, nb = ga.get("name", "A"), gb.get("name", "B")
    sa, pa = compute_war_score(war, "a")
    sb, pb = compute_war_score(war, "b")
    att_a  = sum(1 for u in war.get("participants_a", []) if u in (war.get("attacks") or {}))
    att_b  = sum(1 for u in war.get("participants_b", []) if u in (war.get("attacks") or {}))
    body = (
        f"{SEP}\n  \u2694\ufe0f GANG WAR \u2022 {fmt}v{fmt}\n{SEP}\n\n"
        + _box("Info", [
            f"Phase:     {war.get('phase','?').title()}",
            f"Time Left: {_tl(_phase_end(war))}",
            f"War ID:    {wid}",
        ]) + "\n\n"
        + _box("Score", [
            f"{na:<20} {sa}\u2b50  {pa}%",
            f"{nb:<20} {sb}\u2b50  {pb}%",
        ]) + "\n\n"
        + _box("Attacks", [
            f"{na}: {att_a}/{len(war.get('participants_a',[]))}",
            f"{nb}: {att_b}/{len(war.get('participants_b',[]))}",
        ])
    )
    return _inf(body)


# ── Participant Select ────────────────────────────────────────────

class ParticipantSelect(discord.ui.View):
    def __init__(self, cog: "GangWarCog", uid: str, gang: dict, gid: str, fmt: int, data: dict) -> None:
        super().__init__(timeout=300)
        self.cog  = cog
        self.uid  = uid
        self.gang = gang
        self.gid  = gid
        self.fmt  = fmt
        self.sel: set[str] = set()
        self.members = [str(m) for m in (gang.get("members") or []) if not is_in_war_cooldown(data, str(m))]
        self._build(data)

    def _build(self, data: dict) -> None:
        for c in list(self.children): self.remove_item(c)
        opts = []
        for mid in self.members[:25]:
            p    = data.get("players", {}).get(str(mid), {})
            u    = p.get("user", {}) if isinstance(p, dict) else {}
            name = str(u.get("name") or u.get("username") or f"<@{mid}>")
            pref = get_player_war_pref(data, mid)
            tph  = int(u.get("trophies", 0)) if isinstance(u, dict) else 0
            warn = " \u26a0" if pref == "out" else ""
            opts.append(discord.SelectOption(
                label=f"{name}{warn}"[:100],
                value=str(mid),
                description=f"\U0001f3c6{tph} | pref:{pref}"[:100],
                default=str(mid) in self.sel,
            ))
        if opts:
            s = discord.ui.Select(
                placeholder=f"Select {self.fmt} members",
                options=opts,
                min_values=self.fmt,
                max_values=min(self.fmt, len(opts)),
                row=0,
            )
            s.callback = self._on_sel
            self.add_item(s)
        go = discord.ui.Button(
            label=f"\u2694\ufe0f Queue ({len(self.sel)} selected)",
            style=discord.ButtonStyle.success,
            row=1,
            disabled=len(self.sel) < self.fmt,
        )
        go.callback = self._on_go
        self.add_item(go)
        cx = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, row=1)
        cx.callback = self._on_cx
        self.add_item(cx)

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if str(i.user.id) != self.uid:
            await i.response.send_message("Not yours.", ephemeral=True); return False
        return True

    async def _on_sel(self, i: discord.Interaction) -> None:
        self.sel = set(i.data["values"])
        data = self.cog.bot.storage.load()
        self._build(data)
        await i.response.edit_message(
            embed=_inf(_box("Select Members", [f"Selected: {len(self.sel)}/{self.fmt}", "\u26a0 = war pref OUT"])),
            view=self,
        )

    async def _on_go(self, i: discord.Interaction) -> None:
        if len(self.sel) < self.fmt:
            await i.response.send_message(f"Need {self.fmt} members.", ephemeral=True); return
        parts = list(self.sel)[:self.fmt]
        gid, fmt = self.gid, self.fmt

        def mutate(d: dict) -> tuple[bool, str, str]:
            wid2, _ = get_gang_active_war(d, gid)
            if wid2: return False, "Already in war.", ""
            w = _war_root(d)
            for q in w["queue"].values():
                if isinstance(q, dict) and q.get("gang_id") == gid:
                    return False, "Already in queue.", ""
            qid = queue_war(d, gid, fmt, parts)
            mqid = find_match(d, qid)
            if mqid:
                return True, "matched", create_war(d, qid, mqid)
            return True, "queued", qid

        ok, status, ref = self.cog.bot.storage.with_lock(mutate)
        if not ok:
            await i.response.edit_message(embed=_err(_box("Error", [status])), view=None); return
        if status == "matched":
            await i.response.edit_message(embed=_ok(_box("War Match Found!", [f"War ID: {ref}", f"Prep phase: {PREP_DURATION}s", "Set your /defensive_squad_setup!"])), view=None)
        else:
            await i.response.edit_message(embed=_ok(_box("In Queue", [f"Queue ID: {ref}", "Searching for opponents...", "Auto-cancels in 24h"])), view=None)

    async def _on_cx(self, i: discord.Interaction) -> None:
        await i.response.edit_message(embed=_inf(_box("Cancelled", [])), view=None)


# ── Attack Target ─────────────────────────────────────────────────

class AttackTargetView(discord.ui.View):
    def __init__(self, cog: "GangWarCog", uid: str, wid: str, war: dict, opp: list[str], data: dict) -> None:
        super().__init__(timeout=120)
        self.cog = cog; self.uid = uid; self.wid = wid
        attacked = war.get("attacked_targets", [])
        opts = []
        for tid in opp:
            if tid in attacked: continue
            p    = data.get("players", {}).get(str(tid), {})
            u    = p.get("user", {}) if isinstance(p, dict) else {}
            name = str(u.get("name") or u.get("username") or f"<@{tid}>")
            tph  = int(u.get("trophies", 0)) if isinstance(u, dict) else 0
            sq   = get_war_defense_squad(data, tid)
            opts.append(discord.SelectOption(
                label=name[:100], value=str(tid),
                description=f"\U0001f3c6{tph} | {len(sq)} defense cards"[:100],
            ))
        if opts:
            s = discord.ui.Select(placeholder="Pick opponent to attack", options=opts[:25], row=0)
            s.callback = self._on_pick
            self.add_item(s)
        else:
            self.add_item(discord.ui.Button(label="No targets available", disabled=True))

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if str(i.user.id) != self.uid:
            await i.response.send_message("Not yours.", ephemeral=True); return False
        return True

    async def _on_pick(self, i: discord.Interaction) -> None:
        tid = i.data["values"][0]
        uid = self.uid; wid = self.wid
        data = self.cog.bot.storage.load()
        war  = _war_root(data)["active_wars"].get(wid)
        if not isinstance(war, dict):
            await i.response.edit_message(embed=_err(_box("Error", ["War not found"])), view=None); return
        ok, reason = can_attack(war, uid, tid)
        if not ok:
            await i.response.edit_message(embed=_err(_box("Cannot Attack", [reason])), view=None); return

        def mutate(d: dict) -> bool:
            w2  = _war_root(d)
            w2r = w2["active_wars"].get(wid)
            if not isinstance(w2r, dict): return False
            ok2, _ = can_attack(w2r, uid, tid)
            if not ok2: return False
            w2r.setdefault("pending_attacks", {})[uid] = {"target_uid": tid, "started_at": now_ts()}
            p = d.get("players", {}).get(uid, {})
            u = p.get("user", {}) if isinstance(p, dict) else {}
            if isinstance(u, dict): u["pending_war_attack"] = {"wid": wid, "target_uid": tid}
            return True

        if not self.cog.bot.storage.with_lock(mutate):
            await i.response.edit_message(embed=_err(_box("Error", ["Attack no longer valid"])), view=None); return
        await i.response.edit_message(embed=_ok(_box("Attack Starting!", [
            "Target locked!",
            "Use /battle cpu in battle channel.",
            "After battle, use /gang_war record.",
        ])), view=None)


# ── Defense Squad View ────────────────────────────────────────────

class DefenseSquadView(discord.ui.View):
    def __init__(self, cog: "GangWarCog", uid: str, data: dict) -> None:
        super().__init__(timeout=180)
        self.cog = cog; self.uid = uid
        self.sel: list[str] = get_war_defense_squad(data, uid)
        self._build(data)

    def _build(self, data: dict) -> None:
        for c in list(self.children): self.remove_item(c)
        p   = get_player(data, self.uid)
        inv = (p.get("user", {}) or {}).get("inventory", []) if isinstance(p, dict) else []
        opts = []
        for card in inv[:25]:
            if not isinstance(card, dict): continue
            cuid = str(card.get("uid", ""))
            opts.append(discord.SelectOption(
                label=str(card.get("card_name", "?"))[:100],
                value=cuid,
                description=str(card.get("rarity", ""))[:100],
                default=cuid in self.sel,
            ))
        if opts:
            s = discord.ui.Select(placeholder="Select up to 4 defense cards", options=opts, min_values=1, max_values=min(4, len(opts)), row=0)
            s.callback = self._on_sel
            self.add_item(s)
        sv = discord.ui.Button(label=f"\U0001f4be Save ({len(self.sel)}/4)", style=discord.ButtonStyle.success, row=1)
        sv.callback = self._on_save
        self.add_item(sv)

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if str(i.user.id) != self.uid:
            await i.response.send_message("Not yours.", ephemeral=True); return False
        return True

    async def _on_sel(self, i: discord.Interaction) -> None:
        self.sel = i.data["values"][:4]
        data = self.cog.bot.storage.load()
        self._build(data)
        await i.response.edit_message(embed=_inf(_box("Defense Squad", [f"{len(self.sel)}/4 selected"])), view=self)

    async def _on_save(self, i: discord.Interaction) -> None:
        uid = self.uid; sel = list(self.sel)
        self.cog.bot.storage.with_lock(lambda d: set_war_defense_squad(d, uid, sel))
        await i.response.edit_message(embed=_ok(_box("Defense Squad Saved!", [f"{len(sel)} cards set"])), view=None)


# ── Cog ───────────────────────────────────────────────────────────

class GangWarCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._qt = bot.loop.create_task(self._monitor())

    def cog_unload(self) -> None:
        self._qt.cancel()

    async def _monitor(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                def mutate(data: dict) -> None:
                    w = _war_root(data)
                    for qid in list(w["queue"].keys()):
                        qe = w["queue"].get(qid)
                        if not isinstance(qe, dict): continue
                        if now_ts() - int(qe.get("queued_at", 0)) > QUEUE_TIMEOUT:
                            w["queue"].pop(qid, None); continue
                        mqid = find_match(data, qid)
                        if mqid and mqid in w["queue"]:
                            create_war(data, qid, mqid); return
                self.bot.storage.with_lock(mutate)
            except Exception as ex:
                logger.debug("war monitor: %s", ex)
            await asyncio.sleep(60)

    war = app_commands.Group(name="gang_war", description="Gang War commands")

    @war.command(name="start", description="Start a gang war — Head/Vice only.")
    @app_commands.choices(format=[
        app_commands.Choice(name="🧪 2v2 (10min test)", value=2),
        app_commands.Choice(name="10v10", value=10),
        app_commands.Choice(name="20v20", value=20),
        app_commands.Choice(name="30v30", value=30),
    ])
    async def war_start(self, i: discord.Interaction, format: app_commands.Choice[int]) -> None:
        if not await ensure_registered(i, self.bot.storage): return
        data = self.bot.storage.load()
        uid  = str(i.user.id)
        gid, gang = get_user_gang(data, uid)
        if not gid:
            await error_reply(i, embed=_err(_box("No Gang", ["You are not in a gang."]))); return
        if not _is_hv(gang, uid):
            await error_reply(i, embed=_err(_box("Permission Denied", ["Head or Vice Head only."]))); return
        fmt = format.value
        if len(gang.get("members", []) or []) < fmt:
            await error_reply(i, embed=_err(_box("Not Enough Members", [f"Need {fmt}, you have {len(gang.get('members',[]))}."]))); return
        view = ParticipantSelect(self, uid, gang, gid, fmt, data)
        await smart_reply(i, embed=_inf(_box(f"{fmt}v{fmt} Gang War", [f"Select {fmt} members.", "\u26a0 = preference OUT", "48h cooldown members excluded."])), view=view, ephemeral=True)

    @war.command(name="status", description="View current war status.")
    async def war_status(self, i: discord.Interaction) -> None:
        if not await ensure_registered(i, self.bot.storage): return
        data = self.bot.storage.load()
        uid  = str(i.user.id)
        gid, _ = get_user_gang(data, uid)
        if not gid:
            await error_reply(i, embed=_err(_box("No Gang", []))); return
        wid, war = get_gang_active_war(data, gid)
        if not wid:
            w = _war_root(data)
            for qid, qe in w.get("queue", {}).items():
                if isinstance(qe, dict) and qe.get("gang_id") == gid:
                    await smart_reply(i, embed=_inf(_box("In Queue", [
                        f"Format: {qe.get('format')}v{qe.get('format')}",
                        f"Avg\U0001f3c6: {qe.get('avg_trophies', 0):,}",
                        f"Cancels in: {_tl(int(qe.get('queued_at',0)) + QUEUE_TIMEOUT)}",
                    ]))); return
            await smart_reply(i, embed=_inf(_box("No Active War", ["Use /gang_war start to enter."]))); return
        if check_phase_transition(data, wid) == "ended":
            self.bot.storage.with_lock(lambda d: grant_war_rewards(d, wid))
            data = self.bot.storage.load()
            war  = _war_root(data)["active_wars"].get(wid, {})
        await smart_reply(i, embed=_status_embed(data, wid, war))

    @war.command(name="attack", description="Attack an opponent in the war.")
    async def war_attack(self, i: discord.Interaction) -> None:
        if not await ensure_registered(i, self.bot.storage): return
        data = self.bot.storage.load()
        uid  = str(i.user.id)
        wid, war, side = get_user_active_war(data, uid)
        if not wid:
            await error_reply(i, embed=_err(_box("Not in War", []))); return
        if not is_battle_phase(war):
            await error_reply(i, embed=_err(_box("Not Battle Phase", [f"Battle starts in: {_tl(_phase_end(war))}"]))); return
        if uid in (war.get("attacks", {}) or {}):
            await error_reply(i, embed=_err(_box("Already Attacked", ["You used your attack."]))); return
        opp_side  = "b" if side == "a" else "a"
        opp_parts = war.get(f"participants_{opp_side}", [])
        view = AttackTargetView(self, uid, wid, war, opp_parts, data)
        await smart_reply(i, embed=_inf(_box("Select Target", ["Pick 1 opponent.", "You can only attack once!", "Their squad = CPU."])), view=view, ephemeral=True)

    @war.command(name="record", description="Record your war battle result after fighting.")
    async def war_record(self, i: discord.Interaction) -> None:
        if not await ensure_registered(i, self.bot.storage): return
        data = self.bot.storage.load()
        uid  = str(i.user.id)
        p    = get_player(data, uid)
        u    = (p.get("user", {}) or {}) if isinstance(p, dict) else {}
        ctx  = u.get("pending_war_attack")
        if not isinstance(ctx, dict):
            await error_reply(i, embed=_err(_box("No Pending Attack", ["Use /gang_war attack first."]))); return
        wid = str(ctx.get("wid", "")); tid = str(ctx.get("target_uid", ""))
        war = _war_root(data)["active_wars"].get(wid)
        if not isinstance(war, dict):
            await error_reply(i, embed=_err(_box("War Not Found", []))); return
        recent = None
        for b in list((data.get("battle", {}).get("active", {}) or {}).values()):
            if isinstance(b, dict) and uid in (b.get("players", {}) or {}) and b.get("ended"):
                recent = b; break
        if not recent:
            for b in list((data.get("battle", {}).get("finished", {}) or {}).values()):
                if isinstance(b, dict) and uid in (b.get("players", {}) or {}):
                    recent = b; break
        if not recent:
            await error_reply(i, embed=_err(_box("No Battle Found", ["Complete the battle first."]))); return

        players  = recent.get("players", {}) or {}
        my_s     = players.get(uid, {}) or {}
        opp_id   = next((k for k in players if k != uid), "")
        opp_s    = players.get(opp_id, {}) or {}
        att_won  = str(recent.get("winner_id", "")) == uid

        def surv(s: dict) -> tuple[int, list[float]]:
            team = s.get("team_uids", []) or []
            hp   = s.get("hp", {}) or {}
            hpm  = s.get("hp_max", {}) or {}
            pcts = [int(hp.get(c, 0)) / max(1, int(hpm.get(c, 1))) * 100 for c in team if int(hp.get(c, 0)) > 0]
            return len(pcts), pcts

        asurv, apcts = surv(my_s)
        dsurv, dpcts = surv(opp_s)

        def mutate(d: dict) -> None:
            record_attack(d, wid, uid, tid, asurv, apcts, dsurv, dpcts, att_won)
            pp = d.get("players", {}).get(uid, {})
            uu = pp.get("user", {}) if isinstance(pp, dict) else {}
            if isinstance(uu, dict): uu.pop("pending_war_attack", None)

        self.bot.storage.with_lock(mutate)
        stars = asurv if att_won else 0
        pct   = int(sum(apcts) / max(1, len(apcts))) if att_won and apcts else 0
        result_txt = "WIN ⭐" if att_won else "LOSS ❌"
        await smart_reply(i, embed=_ok(_box("Attack Recorded!", [
            f"Result: {result_txt}",
            f"Stars: {stars}  |  %: {pct}%",
        ])))

    @war.command(name="cancel_queue", description="Cancel matchmaking — Head/Vice only.")
    async def war_cancel_queue(self, i: discord.Interaction) -> None:
        if not await ensure_registered(i, self.bot.storage): return
        data = self.bot.storage.load()
        uid  = str(i.user.id)
        gid, gang = get_user_gang(data, uid)
        if not gid or not _is_hv(gang, uid):
            await error_reply(i, embed=_err(_box("Permission Denied", []))); return
        def mutate(d: dict) -> bool:
            w = _war_root(d)
            for qid, qe in list(w["queue"].items()):
                if isinstance(qe, dict) and qe.get("gang_id") == gid:
                    del w["queue"][qid]; return True
            return False
        if not self.bot.storage.with_lock(mutate):
            await error_reply(i, embed=_err(_box("Not in Queue", []))); return
        await smart_reply(i, embed=_ok(_box("Queue Cancelled", ["You can restart anytime."])))

    @war.command(name="preference", description="Set your war participation preference.")
    @app_commands.choices(preference=[
        app_commands.Choice(name="IN  \u2014 I want to participate", value="in"),
        app_commands.Choice(name="OUT \u2014 Skip me for wars",      value="out"),
    ])
    async def war_preference(self, i: discord.Interaction, preference: app_commands.Choice[str]) -> None:
        if not await ensure_registered(i, self.bot.storage): return
        uid  = str(i.user.id)
        pref = preference.value
        def mutate(d: dict) -> None:
            p = d.get("players", {}).get(uid, {})
            u = p.get("user", {}) if isinstance(p, dict) else {}
            if isinstance(u, dict): u["war_preference"] = pref
        self.bot.storage.with_lock(mutate)
        await smart_reply(i, embed=_ok(_box("Preference Updated", [f"You are now: {pref.upper()}"])))

    @app_commands.command(name="defensive_squad_setup", description="Set your defensive squad for gang wars.")
    async def def_squad(self, i: discord.Interaction) -> None:
        if not await ensure_registered(i, self.bot.storage): return
        data = self.bot.storage.load()
        uid  = str(i.user.id)
        wid, war, _ = get_user_active_war(data, uid)
        if wid and isinstance(war, dict) and is_battle_phase(war):
            await error_reply(i, embed=_err(_box("Defense Locked", ["Battle phase started!", "Cannot change squad now."]))); return
        cur  = get_war_defense_squad(data, uid)
        view = DefenseSquadView(self, uid, data)
        await smart_reply(i, embed=_inf(_box("Defensive Squad Setup", [
            f"Current: {len(cur)} cards set" if cur else "Not set yet",
            "Select up to 4 cards.",
            "Locked once battle phase starts!",
        ])), view=view, ephemeral=True)

    # ── Owner Commands ────────────────────────────────────────────

    @app_commands.command(name="o_war_start", description="Owner: force-start a war (any format, any gangs).")
    async def o_war_start(self, i: discord.Interaction, gang_a: str, gang_b: str, format: int = 1) -> None:
        if not is_owner(i): await error_reply(i, embed=_err("\u274c Owner only.")); return
        data = self.bot.storage.load()
        gid_a, ga = find_gang_by_name(data, gang_a)
        gid_b, gb = find_gang_by_name(data, gang_b)
        if not gid_a: await error_reply(i, embed=_err(f"\u274c Gang '{gang_a}' not found.")); return
        if not gid_b: await error_reply(i, embed=_err(f"\u274c Gang '{gang_b}' not found.")); return
        ma = [str(m) for m in (ga.get("members") or [])][:format]
        mb = [str(m) for m in (gb.get("members") or [])][:format]
        if not ma or not mb: await error_reply(i, embed=_err("\u274c Need members in both gangs.")); return
        def mutate(d: dict) -> str:
            return create_war(d, queue_war(d, gid_a, format, ma), queue_war(d, gid_b, format, mb))
        wid = self.bot.storage.with_lock(mutate)
        await smart_reply(i, embed=_ok(_box("War Force-Started!", [f"{gang_a} vs {gang_b}", f"Format: {format}v{format}", f"War ID: {wid}", f"Prep: {PREP_DURATION}s"])), ephemeral=True)

    @app_commands.command(name="o_war_end", description="Owner: force-end a war.")
    async def o_war_end(self, i: discord.Interaction, war_id: str) -> None:
        if not is_owner(i): await error_reply(i, embed=_err("\u274c Owner only.")); return
        def mutate(d: dict) -> tuple[bool, str]:
            w = _war_root(d)
            war = w["active_wars"].get(war_id)
            if not isinstance(war, dict): return False, "not found"
            winner = determine_winner(war)
            grant_war_rewards(d, war_id)
            return True, winner
        ok, winner = self.bot.storage.with_lock(mutate)
        if not ok: await error_reply(i, embed=_err("\u274c War not found.")); return
        await smart_reply(i, embed=_ok(_box("War Ended!", [f"War: {war_id}", f"Winner: Side {winner.upper()}", "Rewards granted."])), ephemeral=True)

    @app_commands.command(name="o_war_set_phase", description="Owner: force phase change.")
    @app_commands.choices(phase=[app_commands.Choice(name="prep", value="prep"), app_commands.Choice(name="battle", value="battle")])
    async def o_war_set_phase(self, i: discord.Interaction, war_id: str, phase: app_commands.Choice[str]) -> None:
        if not is_owner(i): await error_reply(i, embed=_err("\u274c Owner only.")); return
        def mutate(d: dict) -> bool:
            war = _war_root(d)["active_wars"].get(war_id)
            if not isinstance(war, dict): return False
            war["phase"] = phase.value; war["phase_started_at"] = now_ts(); return True
        if not self.bot.storage.with_lock(mutate): await error_reply(i, embed=_err("\u274c War not found.")); return
        await smart_reply(i, embed=_ok(_box("Phase Set", [f"War {war_id} \u2192 {phase.value.upper()}"])), ephemeral=True)

    @app_commands.command(name="o_war_set_durations", description="Owner: set phase durations in seconds.")
    async def o_war_set_durations(self, i: discord.Interaction, prep_seconds: int = 300, battle_seconds: int = 300) -> None:
        if not is_owner(i): await error_reply(i, embed=_err("\u274c Owner only.")); return
        import bot.utils.war_logic as wl
        wl.PREP_DURATION = prep_seconds
        wl.BATTLE_DURATION = battle_seconds
        await smart_reply(i, embed=_ok(_box("Durations Updated", [f"Prep: {prep_seconds}s ({prep_seconds//60}m)", f"Battle: {battle_seconds}s ({battle_seconds//60}m)", "Resets on restart."])), ephemeral=True)

    @app_commands.command(name="o_war_list", description="Owner: list all wars and queue.")
    async def o_war_list(self, i: discord.Interaction) -> None:
        if not is_owner(i): await error_reply(i, embed=_err("\u274c Owner only.")); return
        data = self.bot.storage.load()
        w    = _war_root(data)
        wlines = []
        for wid, war in w.get("active_wars", {}).items():
            if not isinstance(war, dict): continue
            ga = data.get("gangs", {}).get(war.get("gang_a", ""), {})
            gb = data.get("gangs", {}).get(war.get("gang_b", ""), {})
            wlines.append(f"[{wid}] {ga.get('name','?')} vs {gb.get('name','?')} \u2014 {war.get('phase','?').upper()} \u2014 {war.get('format')}v{war.get('format')}")
        qlines = []
        for qid, qe in w.get("queue", {}).items():
            if not isinstance(qe, dict): continue
            g = data.get("gangs", {}).get(qe.get("gang_id", ""), {})
            qlines.append(f"[{qid}] {g.get('name','?')} \u2014 {qe.get('format')}v{qe.get('format')} \u2014 avg\U0001f3c6{qe.get('avg_trophies',0)}")
        body = _box("Active Wars", wlines or ["None"]) + "\n\n" + _box("Queue", qlines or ["Empty"])
        await smart_reply(i, embed=_inf(body), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GangWarCog(bot))
