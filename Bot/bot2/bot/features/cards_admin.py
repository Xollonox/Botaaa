"""Owner card creation/editor commands for LOOKISM HXCC."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import OWNER_GUILD_ID
from bot.utils.attacks_logic import (
    CATALOG_ATTACK_TYPES,
    OWNER_DEFENSE_TYPES,
    add_attack_to_catalog,
    assigned_cards_for_attack,
    assign_attack_to_card,
    card_attack_keys,
    create_attack_entry,
    edit_attack_in_catalog,
    ensure_attacks_structure,
    list_attacks,
    remove_attack_from_all_cards,
    remove_attack_from_card,
)
from bot.utils.cards_logic import (
    add_card_def,
    build_card_def,
    delete_card_def,
    edit_card_def,
    find_catalog_key,
    mastery_list_from_flags,
    normalize_mastery_list,
)
from bot.utils.checks import is_owner
from bot.utils.ui import make_embed
from bot.utils.typing_matchup import TYPES as TYPING_TYPES, normalize_typing as _norm_typing_list, parse_typing_input
OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


RARITY_CHOICES = ["Common", "Rare", "Epic", "Legendary", "Mythical", "Infernal", "Abyssal"]
MASTERY_CHOICES = ["Strength", "Speed", "Endurance", "Technique", "IQ", "BIQ", "Conviction", "None"]
MOVE_TYPE_CHOICES = ["Normal", "Special", "Unique Skill", "Path"]
MOVE_LIMITS = {
    "Normal": 5,
    "Special": 4,
    "Unique Skill": 3,
    "Path": 2,
}


def _cards_root(data: dict[str, Any]) -> dict[str, Any]:
    cards = data.get("cards")
    if not isinstance(cards, dict):
        data["cards"] = {}
    return data["cards"]


def _norm(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _mk_stats(strength: int, speed: int, endurance: int, technique: int, iq: int, biq: int) -> dict[str, int]:
    return {
        "strength": int(strength),
        "speed": int(speed),
        "endurance": int(endurance),
        "technique": int(technique),
        "iq": int(iq),
        "battle_iq": int(biq),
    }


def _rarity_icon(rarity: str) -> str:
    from bot.data.constants import rarity_icon
    return rarity_icon(str(rarity).title()) or "⚪"


def _find_key(data: dict[str, Any], card_name: str) -> str | None:
    cards = _cards_root(data)
    if card_name in cards and isinstance(cards[card_name], dict):
        return card_name
    target = _norm(card_name).lower()
    for key, card in cards.items():
        if not isinstance(card, dict):
            continue
        if _norm(str(card.get("name", key))).lower() == target:
            return key
    return None


def _safe_int(v: str, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)


def _ensure_editor_payload(card: dict[str, Any]) -> dict[str, Any]:
    normal = card.get("normal_moves") if isinstance(card.get("normal_moves"), list) else []
    special = card.get("special_moves") if isinstance(card.get("special_moves"), list) else []
    unique_skill_moves = card.get("unique_skill_moves") if isinstance(card.get("unique_skill_moves"), list) else []
    ultimate_move = card.get("ultimate_move") if isinstance(card.get("ultimate_move"), dict) else None
    path_attack = card.get("path_attack") if isinstance(card.get("path_attack"), dict) else None
    unique_skills = card.get("unique_skills") if isinstance(card.get("unique_skills"), dict) else {"skill_names": []}
    skill_names = unique_skills.get("skill_names") if isinstance(unique_skills.get("skill_names"), list) else []

    stats_raw = card.get("stats") if isinstance(card.get("stats"), dict) else {}
    biq = int(stats_raw.get("biq", stats_raw.get("battle_iq", 0)) or 0)

    return {
        "card_id": str(card.get("card_id", _norm(card.get("name", "card")).lower().replace(" ", "_"))),
        "name": str(card.get("name", "Unknown")),
        "image_url": str(card.get("image_url", "")),
        "emoji": str(card.get("emoji", "🃏")),
        "rarity": str(card.get("rarity", "Common")),
        "mastery": str(card.get("mastery", "None")) if not isinstance(card.get("mastery"), dict) else str(card.get("mastery", {}).get("type", "None") or "None"),
        "typing": _norm_typing_list(card.get("typing", [])),
        "stats": _mk_stats(
            int(stats_raw.get("strength", 0) or 0),
            int(stats_raw.get("speed", 0) or 0),
            int(stats_raw.get("endurance", 0) or 0),
            int(stats_raw.get("technique", 0) or 0),
            int(stats_raw.get("iq", 0) or 0),
            biq,
        ),
        "dialogue_default": str(card.get("dialogue_default", card.get("dialogue", "")) or ""),
        "normal_moves": [m for m in normal if isinstance(m, dict)],
        "special_moves": [m for m in special if isinstance(m, dict)],
        "unique_skill_moves": [m for m in unique_skill_moves if isinstance(m, dict)],
        "ultimate_move": ultimate_move,
        "path_attack": path_attack,
        "path": {"path_name": str(card.get("path", {}).get("path_name", card.get("path_name", ""))) if isinstance(card.get("path"), dict) else str(card.get("path_name", ""))},
        "unique_skills": {"skill_names": [str(x) for x in skill_names][:3]},
    }


def _to_storage_card(payload: dict[str, Any]) -> dict[str, Any]:
    card = deepcopy(payload)
    stats = card.get("stats", {}) if isinstance(card.get("stats"), dict) else {}
    card["stats"] = {
        "strength": int(stats.get("strength", 0)),
        "speed": int(stats.get("speed", 0)),
        "endurance": int(stats.get("endurance", 0)),
        "technique": int(stats.get("technique", 0)),
        "iq": int(stats.get("iq", 0)),
        "battle_iq": int(stats.get("biq", stats.get("battle_iq", 0))),
    }
    card["mastery"] = {"type": str(card.get("mastery", "None")), "description": ""}
    card["typing"] = _norm_typing_list(card.get("typing", []))
    card["path_name"] = str(card.get("path", {}).get("path_name", ""))
    card["unique_path"] = str(card.get("path", {}).get("path_name", ""))
    card["unique_skill"] = ", ".join([str(x) for x in card.get("unique_skills", {}).get("skill_names", []) if str(x).strip()][:3])
    card["dialogue"] = str(card.get("dialogue_default", ""))
    # compatibility attack mirrors
    card["attacks"] = [str(m.get("name", "")) for m in card.get("normal_moves", []) if isinstance(m, dict)]
    card["special"] = [str(m.get("name", "")) for m in card.get("special_moves", []) if isinstance(m, dict)]
    card["unique_skill"] = [str(card["ultimate_move"].get("name", ""))] if isinstance(card.get("ultimate_move"), dict) else []
    card["path_attack_name"] = str(card.get("path_attack", {}).get("name", "")) if isinstance(card.get("path_attack"), dict) else ""
    return card


def _move_bucket(payload: dict[str, Any], move_type: str) -> tuple[list[dict[str, Any]] | None, str]:
    if move_type == "Normal":
        return payload["normal_moves"], "normal_moves"
    if move_type == "Special":
        return payload["special_moves"], "special_moves"
    if move_type == "Unique Skill":
        return payload["unique_skill_moves"], "unique_skill_moves"
    if move_type == "Unique Skill":
        return None, "ultimate_move"
    return None, "path_attack"


def _editor_embed(payload: dict[str, Any]) -> discord.Embed:
    stats = payload.get("stats", {})
    normal_n = len(payload.get("normal_moves", []))
    special_n = len(payload.get("special_moves", []))
    usk_n = len(payload.get("unique_skill_moves", []))
    ult_n = 1 if isinstance(payload.get("ultimate_move"), dict) else 0
    path_n = 1 if isinstance(payload.get("path_attack"), dict) else 0

    unique_skill_attacks = ", ".join([str(m.get("name", "")) for m in payload.get("unique_skill_moves", []) if isinstance(m, dict)]) or "None"
    path_attack_name = str(payload.get("path_attack", {}).get("name", "None")) if isinstance(payload.get("path_attack"), dict) else "None"

    body = (
        "╭─ CARD CORE\n"
        f"│ Name: {payload.get('name', 'Unknown')}\n"
        f"│ Rarity: {payload.get('rarity', 'Common')}\n"
        f"│ Emoji: {payload.get('emoji', '🃏')}\n"
        f"│ Mastery: {payload.get('mastery', 'None')}\n"
        f"│ Path Attack Name: {path_attack_name}\n"
        f"│ Unique Skill Attacks: {unique_skill_attacks}\n"
        "╰────────────────\n"
        "╭─ STATS\n"
        f"│ STR {int(stats.get('strength', 0))}\n"
        f"│ SPD {int(stats.get('speed', 0))}\n"
        f"│ END {int(stats.get('endurance', 0))}\n"
        f"│ TEC {int(stats.get('technique', 0))}\n"
        f"│ IQ {int(stats.get('iq', 0))}\n"
        f"│ BIQ {int(stats.get('biq', stats.get('battle_iq', 0)))}\n"
        "╰────────────────\n"
        "╭─ MOVES\n"
        f"│ NORMAL ({normal_n}/5)\n"
        f"│ SPECIAL ({special_n}/4)\n"
        f"│ UNIQUE SKILL ({usk_n}/3)\n"
        f"│ ULTIMATE ({ult_n}/1)\n"
        f"│ PATH ATTACK ({path_n}/1)\n"
        "╰────────────────\n"
        "╭─ DEFAULT DIALOGUE\n"
        f"│ {payload.get('dialogue_default', '') or '—'}\n"
        "╰────────────────"
    )

    return make_embed(
        None, "LOOKISM HXCC • CARD EDITOR", body, color=0xE11D48,
        footer="Admin Control",
        image_url=str(payload.get("image_url", "")).strip() or None,
    )


def _created_embed(payload: dict[str, Any]) -> discord.Embed:
    stats = payload.get("stats", {})
    skills = payload.get("unique_skills", {}).get("skill_names", []) if isinstance(payload.get("unique_skills"), dict) else []
    skills_text = "\n".join([f"• {s}" for s in skills if str(s).strip()]) or "• None"
    body = (
        "╭─ CARD CORE\n"
        f"│ Name: {payload.get('name', 'Unknown')}\n"
        f"│ Rarity: {payload.get('rarity', 'Common')}\n"
        f"│ Emoji: {payload.get('emoji', '🃏')}\n"
        f"│ Mastery: {payload.get('mastery', 'None')}\n"
        "╰────────────────\n"
        "╭─ STATS\n"
        f"│ STR {int(stats.get('strength', 0))}\n"
        f"│ SPD {int(stats.get('speed', 0))}\n"
        f"│ END {int(stats.get('endurance', 0))}\n"
        f"│ TEC {int(stats.get('technique', 0))}\n"
        f"│ IQ {int(stats.get('iq', 0))}\n"
        f"│ BIQ {int(stats.get('biq', stats.get('battle_iq', 0)))}\n"
        "╰────────────────\n"
        "╭─ PATH\n"
        f"│ Path Name: {payload.get('path', {}).get('path_name', 'None')}\n"
        "╰────────────────\n"
        "╭─ UNIQUE SKILLS\n"
        f"│ {skills_text.replace(chr(10), chr(10)+'│ ')}\n"
        "╰────────────────\n"
        "╭─ DEFAULT DIALOGUE\n"
        f"│ {payload.get('dialogue_default', '') or '—'}\n"
        "╰────────────────"
    )
    return make_embed(
        None, "LOOKISM HXCC • CARD CREATED", body, color=0xE11D48,
        footer="Admin Control",
        image_url=str(payload.get("image_url", "")).strip() or None,
    )


class AddCardModal(discord.ui.Modal, title="LOOKISM HXCC • Add Card"):
    basic_info = discord.ui.TextInput(
        label="Basic Info",
        style=discord.TextStyle.paragraph,
        placeholder="Name|Image URL|Emoji|Rarity",
        max_length=1000,
    )
    mastery = discord.ui.TextInput(label="Mastery Type", placeholder="Strength/Speed/Endurance/Technique/IQ/BIQ/None", max_length=32)
    path_info = discord.ui.TextInput(
        label="Path Attack",
        style=discord.TextStyle.paragraph,
        placeholder="Path Name|Path Attack Name|Path Dialogue|Path Animation(optional)",
        max_length=1000,
    )
    unique_skills = discord.ui.TextInput(
        label="Unique Skills",
        style=discord.TextStyle.paragraph,
        placeholder="Skill1 Name|Skill1 Dialogue; Skill2 Name|Skill2 Dialogue; Skill3 Name|Skill3 Dialogue",
        max_length=1200,
    )
    stats_and_dialogue = discord.ui.TextInput(
        label="Base Stats + Default Dialogue",
        style=discord.TextStyle.paragraph,
        placeholder="STR|SPD|END|TEC|IQ|BIQ|Default Dialogue",
        max_length=1200,
    )

    def __init__(self, cog: "CardsAdminCog") -> None:
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        basic = [x.strip() for x in str(self.basic_info.value).split("|")]
        if len(basic) < 4:
            await interaction.response.send_message("Basic Info format: Name|Image URL|Emoji|Rarity", ephemeral=True)
            return
        name, image_url, emoji, rarity = basic[0], basic[1], basic[2], basic[3].title()
        if rarity not in RARITY_CHOICES:
            await interaction.response.send_message(f"Rarity must be one of: {', '.join(RARITY_CHOICES)}", ephemeral=True)
            return

        mastery_type = _norm(self.mastery.value).title() or "None"
        if mastery_type not in MASTERY_CHOICES:
            await interaction.response.send_message(f"Mastery must be one of: {', '.join(MASTERY_CHOICES)}", ephemeral=True)
            return

        path_parts = [x.strip() for x in str(self.path_info.value).split("|")]
        while len(path_parts) < 4:
            path_parts.append("")
        path_name, path_attack_name, path_dialogue, path_animation = path_parts[:4]

        skills_raw = [x.strip() for x in str(self.unique_skills.value).split(";") if x.strip()]
        skill_names: list[str] = []
        unique_skill_moves: list[dict[str, Any]] = []
        for sk in skills_raw[:3]:
            parts = [x.strip() for x in sk.split("|")]
            if not parts:
                continue
            s_name = parts[0]
            s_dialogue = parts[1] if len(parts) > 1 else ""
            if s_name:
                skill_names.append(s_name)
                unique_skill_moves.append({"name": s_name, "dialogue": s_dialogue, "animation": ""})

        stat_parts = [x.strip() for x in str(self.stats_and_dialogue.value).split("|")]
        if len(stat_parts) < 7:
            await interaction.response.send_message("Stats format: STR|SPD|END|TEC|IQ|BIQ|Default Dialogue", ephemeral=True)
            return
        strength, speed, endurance, technique, iq, biq = [_safe_int(x, 0) for x in stat_parts[:6]]
        dialogue_default = "|".join(stat_parts[6:]).strip()

        payload = {
            "card_id": _norm(name).lower().replace(" ", "_"),
            "name": _norm(name),
            "image_url": image_url.strip(),
            "emoji": emoji.strip() or "🃏",
            "rarity": rarity,
            "mastery": mastery_type,
            "stats": _mk_stats(strength, speed, endurance, technique, iq, biq),
            "dialogue_default": dialogue_default,
            "normal_moves": [],
            "special_moves": [],
            "unique_skill_moves": unique_skill_moves,
            "ultimate_move": None,
            "path_attack": None,
            "path": {"path_name": path_name.strip()},
            "unique_skills": {"skill_names": skill_names[:3]},
        }
        if path_attack_name:
            payload["path_attack"] = {
                "name": path_attack_name,
                "dialogue": path_dialogue,
                "animation": path_animation,
            }

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            if _find_key(data, payload["name"]):
                return False, "Card already exists."
            _cards_root(data)[payload["name"]] = _to_storage_card(payload)
            return True, payload["name"]

        ok, msg = self.cog.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.send_message(embed=_created_embed(payload), ephemeral=True)


class CardSelect(discord.ui.Select):
    def __init__(self, panel: "CardEditorPanel", cards: dict[str, Any]) -> None:
        options: list[discord.SelectOption] = []
        for key, card in list(cards.items())[:25]:
            if not isinstance(card, dict):
                continue
            name = str(card.get("name", key))
            rarity = str(card.get("rarity", "Common"))
            options.append(discord.SelectOption(label=name[:100], description=rarity[:100], value=key))
        if not options:
            options.append(discord.SelectOption(label="No cards available", value="__none__"))
        super().__init__(placeholder="Select an existing card", min_values=1, max_values=1, options=options, row=0)
        self.panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.panel.invoker_id:
            await interaction.response.send_message("This panel belongs to another owner.", ephemeral=True)
            return
        if self.values[0] == "__none__":
            await interaction.response.send_message("No card selected.", ephemeral=True)
            return
        self.panel.card_key = self.values[0]
        data = self.panel.cog.bot.storage.load()
        card = _cards_root(data).get(self.panel.card_key, {})
        self.panel.payload = _ensure_editor_payload(card if isinstance(card, dict) else {})
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class AddMoveModal(discord.ui.Modal, title="Add Move"):
    move_name = discord.ui.TextInput(label="Move Name", max_length=80)
    move_type = discord.ui.TextInput(label="Move Type", placeholder="Normal/Special/Unique Skill/Path", max_length=32)
    move_dialogue = discord.ui.TextInput(label="Move Dialogue", style=discord.TextStyle.paragraph, max_length=500)
    move_animation = discord.ui.TextInput(label="Move Animation", required=False, max_length=120)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=300)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.panel.payload:
            await interaction.response.send_message("Select a card first.", ephemeral=True)
            return
        mt = _norm(self.move_type.value).title()
        if mt == "Path":
            mt = "Path Attack"
        if mt not in MOVE_TYPE_CHOICES:
            await interaction.response.send_message(f"Move Type must be one of: {', '.join(MOVE_TYPE_CHOICES)}", ephemeral=True)
            return

        move = {"name": _norm(self.move_name.value), "dialogue": str(self.move_dialogue.value).strip(), "animation": str(self.move_animation.value).strip()}
        if not move["name"]:
            await interaction.response.send_message("Move name required.", ephemeral=True)
            return

        bucket, key = _move_bucket(self.panel.payload, mt)
        limit = MOVE_LIMITS[mt]
        if key in {"ultimate_move", "path_attack"}:
            if self.panel.payload.get(key):
                await interaction.response.send_message(f"Maximum {mt.lower()} moves reached ({limit}).", ephemeral=True)
                return
            self.panel.payload[key] = move
        else:
            assert bucket is not None
            if len(bucket) >= limit:
                await interaction.response.send_message(f"Maximum {mt.lower()} moves reached ({limit}).", ephemeral=True)
                return
            bucket.append(move)

        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditMoveModal(discord.ui.Modal, title="Edit Move"):
    move_type = discord.ui.TextInput(label="Move Type", placeholder="Normal/Special/Unique Skill/Path", max_length=32)
    old_move_name = discord.ui.TextInput(label="Current Move Name", max_length=80)
    new_move_name = discord.ui.TextInput(label="New Move Name", max_length=80)
    move_dialogue = discord.ui.TextInput(label="Move Dialogue", style=discord.TextStyle.paragraph, max_length=500)
    move_animation = discord.ui.TextInput(label="Move Animation", required=False, max_length=120)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=300)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.panel.payload:
            await interaction.response.send_message("Select a card first.", ephemeral=True)
            return
        mt = _norm(self.move_type.value).title()
        if mt == "Path":
            mt = "Path Attack"
        old_name = _norm(self.old_move_name.value).lower()
        new_name = _norm(self.new_move_name.value)
        if mt not in MOVE_TYPE_CHOICES or not old_name or not new_name:
            await interaction.response.send_message("Invalid move edit payload.", ephemeral=True)
            return

        bucket, key = _move_bucket(self.panel.payload, mt)
        updated = False
        if key in {"ultimate_move", "path_attack"}:
            m = self.panel.payload.get(key)
            if isinstance(m, dict) and _norm(str(m.get("name", ""))).lower() == old_name:
                m["name"] = new_name
                m["dialogue"] = str(self.move_dialogue.value).strip()
                m["animation"] = str(self.move_animation.value).strip()
                updated = True
        else:
            assert bucket is not None
            for m in bucket:
                if _norm(str(m.get("name", ""))).lower() == old_name:
                    m["name"] = new_name
                    m["dialogue"] = str(self.move_dialogue.value).strip()
                    m["animation"] = str(self.move_animation.value).strip()
                    updated = True
                    break

        if not updated:
            await interaction.response.send_message("Move not found.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class DeleteMoveModal(discord.ui.Modal, title="Delete Move"):
    move_type = discord.ui.TextInput(label="Move Type", placeholder="Normal/Special/Unique Skill/Path", max_length=32)
    move_name = discord.ui.TextInput(label="Move Name", max_length=80)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=300)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.panel.payload:
            await interaction.response.send_message("Select a card first.", ephemeral=True)
            return
        mt = _norm(self.move_type.value).title()
        if mt == "Path":
            mt = "Path Attack"
        target = _norm(self.move_name.value).lower()
        if mt not in MOVE_TYPE_CHOICES or not target:
            await interaction.response.send_message("Invalid move delete payload.", ephemeral=True)
            return

        bucket, key = _move_bucket(self.panel.payload, mt)
        removed = False
        if key in {"ultimate_move", "path_attack"}:
            m = self.panel.payload.get(key)
            if isinstance(m, dict) and _norm(str(m.get("name", ""))).lower() == target:
                self.panel.payload[key] = None
                removed = True
        else:
            assert bucket is not None
            before = len(bucket)
            bucket[:] = [m for m in bucket if _norm(str(m.get("name", ""))).lower() != target]
            removed = len(bucket) != before

        if not removed:
            await interaction.response.send_message("Move not found.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditStatsModal(discord.ui.Modal, title="Edit Stats"):
    strength = discord.ui.TextInput(label="Strength", max_length=8)
    speed = discord.ui.TextInput(label="Speed", max_length=8)
    endurance = discord.ui.TextInput(label="Endurance", max_length=8)
    technique = discord.ui.TextInput(label="Technique", max_length=8)
    iq = discord.ui.TextInput(label="IQ", max_length=8)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=300)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.panel.payload["stats"].update(
            _mk_stats(
                _safe_int(self.strength.value),
                _safe_int(self.speed.value),
                _safe_int(self.endurance.value),
                _safe_int(self.technique.value),
                _safe_int(self.iq.value),
                int(self.panel.payload["stats"].get("battle_iq", self.panel.payload["stats"].get("biq", 0))),
            )
        )
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditBIQModal(discord.ui.Modal, title="Edit Battle IQ"):
    biq = discord.ui.TextInput(label="Battle IQ", max_length=8)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=180)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        biq_val = _safe_int(self.biq.value)
        self.panel.payload["stats"]["battle_iq"] = biq_val
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditPathModal(discord.ui.Modal, title="Edit Path Attack"):
    path_name = discord.ui.TextInput(label="Path Name", max_length=100)
    attack_name = discord.ui.TextInput(label="Path Attack Name", max_length=100)
    dialogue = discord.ui.TextInput(label="Path Dialogue", style=discord.TextStyle.paragraph, max_length=500)
    animation = discord.ui.TextInput(label="Path Animation", required=False, max_length=120)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=300)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.panel.payload["path"] = {"path_name": str(self.path_name.value).strip()}
        if str(self.attack_name.value).strip():
            self.panel.payload["path_attack"] = {
                "name": str(self.attack_name.value).strip(),
                "dialogue": str(self.dialogue.value).strip(),
                "animation": str(self.animation.value).strip(),
            }
        else:
            self.panel.payload["path_attack"] = None
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditUniqueSkillModal(discord.ui.Modal, title="Edit Unique Skill"):
    skill_name = discord.ui.TextInput(label="Skill Name", max_length=100)
    attack_name = discord.ui.TextInput(label="Attack Name", max_length=100)
    dialogue = discord.ui.TextInput(label="Dialogue", style=discord.TextStyle.paragraph, max_length=500)
    animation = discord.ui.TextInput(label="Animation", required=False, max_length=120)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=300)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        skills = self.panel.payload.setdefault("unique_skills", {"skill_names": []}).setdefault("skill_names", [])
        if str(self.skill_name.value).strip() and str(self.skill_name.value).strip() not in skills:
            if len(skills) >= 3:
                await interaction.response.send_message("Maximum unique skill moves reached (3).", ephemeral=True)
                return
            skills.append(str(self.skill_name.value).strip())

        moves = self.panel.payload.setdefault("unique_skill_moves", [])
        target_name = _norm(str(self.attack_name.value))
        existing = next((m for m in moves if _norm(str(m.get("name", ""))).lower() == target_name.lower()), None)
        if existing is None:
            if len(moves) >= 3:
                await interaction.response.send_message("Maximum unique skill moves reached (3).", ephemeral=True)
                return
            moves.append({
                "name": target_name,
                "dialogue": str(self.dialogue.value).strip(),
                "animation": str(self.animation.value).strip(),
            })
        else:
            existing["dialogue"] = str(self.dialogue.value).strip()
            existing["animation"] = str(self.animation.value).strip()

        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditRarityModal(discord.ui.Modal, title="Edit Rarity"):
    rarity = discord.ui.TextInput(label="Rarity", placeholder="Common/Rare/Epic/Legendary/Mythical/Infernal/Abyssal", max_length=32)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=180)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        r = _norm(self.rarity.value).title()
        if r not in RARITY_CHOICES:
            await interaction.response.send_message(f"Rarity must be one of: {', '.join(RARITY_CHOICES)}", ephemeral=True)
            return
        self.panel.payload["rarity"] = r
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditMasteryModal(discord.ui.Modal, title="Edit Mastery"):
    mastery = discord.ui.TextInput(label="Mastery", placeholder="Strength/Speed/Endurance/Technique/IQ/BIQ/None", max_length=32)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=180)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        m = _norm(self.mastery.value).title() or "None"
        if m not in MASTERY_CHOICES:
            await interaction.response.send_message(f"Mastery must be one of: {', '.join(MASTERY_CHOICES)}", ephemeral=True)
            return
        self.panel.payload["mastery"] = m
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class EditDialogueModal(discord.ui.Modal, title="Edit Dialogue"):
    dialogue = discord.ui.TextInput(label="Default Dialogue", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=180)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.panel.payload["dialogue_default"] = str(self.dialogue.value).strip()
        await interaction.response.edit_message(embed=_editor_embed(self.panel.payload), view=self.panel)


class ConfirmDeleteCardModal(discord.ui.Modal, title="Delete Card"):
    confirm_text = discord.ui.TextInput(label="Type DELETE to confirm", max_length=16)

    def __init__(self, panel: "CardEditorPanel") -> None:
        super().__init__(timeout=180)
        self.panel = panel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if str(self.confirm_text.value).strip() != "DELETE":
            await interaction.response.send_message("Deletion cancelled. You must type DELETE.", ephemeral=True)
            return
        if not self.panel.card_key:
            await interaction.response.send_message("No card selected.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> bool:
            key = _find_key(data, self.panel.card_key)
            if not key:
                return False
            _cards_root(data).pop(key, None)
            return True

        ok = self.panel.cog.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message("Card not found.", ephemeral=True)
            return
        self.panel.card_key = None
        self.panel.payload = {}
        await interaction.response.edit_message(content="Card deleted.", embed=None, view=None)


class CardEditorPanel(discord.ui.View):
    def __init__(self, cog: "CardsAdminCog", invoker_id: int, initial_key: str | None = None) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.invoker_id = invoker_id
        self.card_key = initial_key
        self.payload: dict[str, Any] = {}

        data = self.cog.bot.storage.load()
        cards = _cards_root(data)
        self.select = CardSelect(self, cards)
        self.add_item(self.select)

        if initial_key and initial_key in cards and isinstance(cards[initial_key], dict):
            self.payload = _ensure_editor_payload(cards[initial_key])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message("This editor belongs to another owner.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Add Move", style=discord.ButtonStyle.primary, row=1)
    async def add_move(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(AddMoveModal(self))

    @discord.ui.button(label="Edit Move", style=discord.ButtonStyle.primary, row=1)
    async def edit_move(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(EditMoveModal(self))

    @discord.ui.button(label="Delete Move", style=discord.ButtonStyle.danger, row=1)
    async def delete_move(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(DeleteMoveModal(self))

    @discord.ui.button(label="Edit Stats", style=discord.ButtonStyle.primary, row=2)
    async def edit_stats(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(EditStatsModal(self))

    @discord.ui.button(label="Edit Rarity", style=discord.ButtonStyle.secondary, row=2)
    async def edit_rarity(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(EditRarityModal(self))

    @discord.ui.button(label="Edit Mastery", style=discord.ButtonStyle.secondary, row=2)
    async def edit_mastery(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(EditMasteryModal(self))

    @discord.ui.button(label="Edit Path Attack", style=discord.ButtonStyle.secondary, row=3)
    async def edit_path(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(EditPathModal(self))

    @discord.ui.button(label="Edit Unique Skill", style=discord.ButtonStyle.secondary, row=3)
    async def edit_usk(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(EditUniqueSkillModal(self))

    @discord.ui.button(label="Edit Dialogue", style=discord.ButtonStyle.secondary, row=3)
    async def edit_dialogue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(EditDialogueModal(self))

    @discord.ui.button(label="Save", style=discord.ButtonStyle.success, row=4)
    async def save(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.payload:
            await interaction.response.send_message("No card selected.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> bool:
            root = _cards_root(data)
            key = self.card_key or self.payload["name"]
            if self.card_key and self.card_key != self.payload["name"]:
                root.pop(self.card_key, None)
            root[self.payload["name"]] = _to_storage_card(self.payload)
            self.card_key = self.payload["name"]
            return True

        self.cog.bot.storage.with_lock(mutate)
        await interaction.response.edit_message(embed=_editor_embed(self.payload), view=self)

    @discord.ui.button(label="Delete Card", style=discord.ButtonStyle.danger, row=4)
    async def delete_card(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ConfirmDeleteCardModal(self))


class CardsAdminCog(commands.Cog):
    o = app_commands.Group(name="o", description="Owner card and attack admin commands.", guild_ids=[OWNER_GUILD_ID])

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        cards = data.get("cards", {})
        if not isinstance(cards, dict):
            return []
        text = current.strip().lower()
        out: list[app_commands.Choice[str]] = []
        for key, card in sorted(cards.items(), key=lambda pair: str(pair[0]).lower()):
            if not isinstance(card, dict):
                continue
            name = str(card.get("name", key))
            if text and text not in key.lower() and text not in name.lower():
                continue
            rarity = str(card.get("rarity", ""))
            label = f"{name} • {rarity}" if rarity else name
            out.append(app_commands.Choice(name=label[:100], value=str(key)))
            if len(out) >= 25:
                break
        return out

    async def _attack_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        ensure_attacks_structure(data)
        catalog = data["attacks"]["catalog"]
        text = current.strip().lower()
        out: list[app_commands.Choice[str]] = []
        for key, entry in list_attacks(data):
            name = str(entry.get("name", key))
            if text and text not in key.lower() and text not in name.lower():
                continue
            out.append(app_commands.Choice(name=f"{name} • {entry.get('type', '')}"[:100], value=key))
            if len(out) >= 25:
                break
        return out

    async def _assigned_attack_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        card_name = str(getattr(interaction.namespace, "card_name", ""))
        keys = card_attack_keys(data, card_name)
        catalog = data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}
        text = current.strip().lower()
        out: list[app_commands.Choice[str]] = []
        for key in keys:
            entry = catalog.get(key, {}) if isinstance(catalog, dict) else {}
            name = str(entry.get("name", key)) if isinstance(entry, dict) else str(key)
            if text and text not in key.lower() and text not in name.lower():
                continue
            typ = str(entry.get("type", "")) if isinstance(entry, dict) else ""
            out.append(app_commands.Choice(name=f"{name} • {typ}"[:100], value=str(key)))
            if len(out) >= 25:
                break
        return out

    @o.command(name="add_card", description="Owner: create a fighter card from fields.")
    @app_commands.choices(rarity=[app_commands.Choice(name=r, value=r) for r in RARITY_CHOICES])
    async def add_card(
        self,
        interaction: discord.Interaction,
        name: str,
        rarity: app_commands.Choice[str],
        strength: app_commands.Range[int, 0, None],
        speed: app_commands.Range[int, 0, None],
        endurance: app_commands.Range[int, 0, None],
        technique: app_commands.Range[int, 0, None],
        iq: app_commands.Range[int, 0, None],
        biq: app_commands.Range[int, 0, None],
        title: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        mastery_strength: bool = False,
        mastery_speed: bool = False,
        mastery_endurance: bool = False,
        mastery_technique: bool = False,
        unique_path: str | None = None,
        unique_path_description: str | None = None,
        unique_skill: str | None = None,
        unique_skill_description: str | None = None,
        emoji: str | None = None,
        weapon_user: bool = False,
        special_stat: str | None = None,
        keystone_name: str | None = None,
    ) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return
        card = build_card_def(
            name=name,
            title=title or "",
            description=description or "",
            rarity=rarity.value,
            strength=int(strength),
            speed=int(speed),
            endurance=int(endurance),
            technique=int(technique),
            iq=int(iq),
            battle_iq=int(biq),
            mastery_list=mastery_list_from_flags(
                strength=mastery_strength,
                speed=mastery_speed,
                endurance=mastery_endurance,
                technique=mastery_technique,
            ),
            unique_path=unique_path,
            unique_path_description=unique_path_description,
            unique_skill=unique_skill,
            unique_skill_description=unique_skill_description,
            image_url=image_url,
            emoji=emoji,
            weapon_user=weapon_user,
            special_stat=special_stat,
            keystone_name=keystone_name,
        )

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            return add_card_def(data, card)

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(f"Created card **{msg}**.", ephemeral=True)

    @o.command(name="edit_card", description="Owner: edit provided fields on a fighter card.")
    @app_commands.choices(rarity=[app_commands.Choice(name=r, value=r) for r in RARITY_CHOICES])
    async def edit_card(
        self,
        interaction: discord.Interaction,
        card_name: str,
        name: str | None = None,
        rarity: app_commands.Choice[str] | None = None,
        strength: app_commands.Range[int, 0, None] | None = None,
        speed: app_commands.Range[int, 0, None] | None = None,
        endurance: app_commands.Range[int, 0, None] | None = None,
        technique: app_commands.Range[int, 0, None] | None = None,
        iq: app_commands.Range[int, 0, None] | None = None,
        biq: app_commands.Range[int, 0, None] | None = None,
        title: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        mastery_strength: bool | None = None,
        mastery_speed: bool | None = None,
        mastery_endurance: bool | None = None,
        mastery_technique: bool | None = None,
        unique_path: str | None = None,
        unique_path_description: str | None = None,
        unique_skill: str | None = None,
        unique_skill_description: str | None = None,
        emoji: str | None = None,
        weapon_user: bool | None = None,
        special_stat: str | None = None,
        keystone_name: str | None = None,
    ) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return
        data = self.bot.storage.load()
        cards = data.get("cards", {}) if isinstance(data.get("cards", {}), dict) else {}
        key = find_catalog_key(cards, card_name)
        current_mastery: list[str] = []
        if key is not None and isinstance(cards.get(key), dict):
            current_mastery = normalize_mastery_list(cards[key].get("mastery", []))

        mastery_updates = {
            "Strength": mastery_strength,
            "Speed": mastery_speed,
            "Endurance": mastery_endurance,
            "Technique": mastery_technique,
        }
        mastery: list[str] | None = None
        if any(v is not None for v in mastery_updates.values()):
            selected = set(current_mastery)
            for label, value in mastery_updates.items():
                if value is True:
                    selected.add(label)
                elif value is False:
                    selected.discard(label)
            mastery = normalize_mastery_list(selected)

        updates: dict[str, Any] = {
            "name": name,
            "title": title,
            "description": description,
            "image_url": image_url,
            "rarity": rarity.value if rarity is not None else None,
            "unique_path": unique_path,
            "unique_path_description": unique_path_description,
            "unique_skill": unique_skill,
            "unique_skill_description": unique_skill_description,
            "emoji": emoji,
            "mastery": mastery,
            "weapon_user": weapon_user,
            "special_stat": special_stat,
            "keystone_name": keystone_name,
            "stats": {
                "strength": strength,
                "speed": speed,
                "endurance": endurance,
                "technique": technique,
                "iq": iq,
                "biq": biq,
            },
        }

        def mutate(state: dict[str, Any]) -> tuple[bool, str]:
            return edit_card_def(state, card_name, updates)

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(f"Updated card **{msg}**.", ephemeral=True)

    @edit_card.autocomplete("card_name")
    async def edit_card_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._card_autocomplete(interaction, current)

    @o.command(name="add_keystone", description="Owner: create a keystone for a specific character.")
    async def add_keystone(
        self,
        interaction: discord.Interaction,
        name: str,
        character: str,
        effect: str,
        active: bool = True,
    ) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            keystones = data.setdefault("keystones", {})
            key = str(name).strip().lower()
            if key in keystones:
                return False, "A keystone with that name already exists."
            card_catalog = data.get("cards", {})
            if not find_catalog_key(card_catalog, character):
                return False, f"Card '{character}' not found in catalog."
            keystones[key] = {
                "name": str(name).strip(),
                "effect": str(effect).strip(),
                "character": str(character).strip(),
                "active": bool(active),
            }
            return True, str(name).strip()

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(f"Created keystone **{msg}**.", ephemeral=True)

    @add_keystone.autocomplete("character")
    async def add_keystone_char_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._card_autocomplete(interaction, current)

    @o.command(name="add_weapon", description="Owner: create a weapon for weapon-user cards.")
    @app_commands.choices(rarity=[app_commands.Choice(name=r, value=r) for r in RARITY_CHOICES])
    async def add_weapon(
        self,
        interaction: discord.Interaction,
        name: str,
        rarity: app_commands.Choice[str],
        compatible_cards: str,
        effect: str,
        effect_active: bool = True,
        image_url: str | None = None,
        emoji: str | None = None,
        stat_strength: int = 0,
        stat_speed: int = 0,
        stat_endurance: int = 0,
        stat_technique: int = 0,
        stat_iq: int = 0,
        stat_biq: int = 0,
    ) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return

        cards_list = [c.strip() for c in compatible_cards.split(",") if c.strip()]
        if not cards_list:
            await interaction.response.send_message("compatible_cards must list at least one card name.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            weapons = data.setdefault("weapons", {})
            key = str(name).strip().lower()
            if key in weapons:
                return False, "A weapon with that name already exists."
            weapons[key] = {
                "name": str(name).strip(),
                "rarity": rarity.value,
                "image_url": str(image_url).strip() if image_url else "",
                "emoji": str(emoji).strip() if emoji else "",
                "compatible_cards": cards_list,
                "stat_buffs": {
                    "strength": int(stat_strength),
                    "speed": int(stat_speed),
                    "endurance": int(stat_endurance),
                    "technique": int(stat_technique),
                    "iq": int(stat_iq),
                    "battle_iq": int(stat_biq),
                },
                "effect": str(effect).strip(),
                "effect_active": bool(effect_active),
            }
            return True, str(name).strip()

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(f"Created weapon **{msg}**.", ephemeral=True)

    @o.command(name="delete_card", description="Owner: delete a fighter card. Confirmation must be DELETE.")
    async def delete_card(self, interaction: discord.Interaction, card_name: str, confirm: str) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            return delete_card_def(data, card_name, confirm)

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(f"Deleted card **{msg}**.", ephemeral=True)

    @delete_card.autocomplete("card_name")
    async def delete_card_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._card_autocomplete(interaction, current)

    @o.command(name="add_attack", description="Owner: add an attack or defense to the catalog.")
    @app_commands.choices(type=[app_commands.Choice(name=t, value=t) for t in CATALOG_ATTACK_TYPES])
    async def add_attack(
        self,
        interaction: discord.Interaction,
        name: str,
        type: app_commands.Choice[str],
        power: app_commands.Range[int, 0, None],
        description: str,
        uses_per_battle: app_commands.Range[int, -1, 99] | None = None,
    ) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return
        entry = create_attack_entry(name, type.value, int(power), description, uses_per_battle)

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            return add_attack_to_catalog(data, entry)

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(f"Created attack **{entry['name']}** (`{msg}`).", ephemeral=True)

    @o.command(name="edit_attack", description="Owner: edit provided fields on a catalog attack.")
    @app_commands.choices(type=[app_commands.Choice(name=t, value=t) for t in CATALOG_ATTACK_TYPES])
    async def edit_attack(
        self,
        interaction: discord.Interaction,
        attack_name: str,
        name: str | None = None,
        type: app_commands.Choice[str] | None = None,
        power: app_commands.Range[int, 0, None] | None = None,
        description: str | None = None,
        uses_per_battle: app_commands.Range[int, -1, 99] | None = None,
    ) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return
        updates = {
            "name": name,
            "type": type.value if type is not None else None,
            "power": power,
            "description": description,
            "uses_per_battle": uses_per_battle,
        }

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            return edit_attack_in_catalog(data, attack_name, updates)

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(f"Updated attack `{msg}`.", ephemeral=True)

    @edit_attack.autocomplete("attack_name")
    async def edit_attack_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._attack_autocomplete(interaction, current)

    @o.command(name="delete_attack", description="Owner: delete an attack and remove it from all cards.")
    async def delete_attack(self, interaction: discord.Interaction, attack_name: str) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            ensure_attacks_structure(data)
            catalog = data["attacks"]["catalog"]
            key = attack_name if attack_name in catalog else attack_name.strip().lower().replace(" ", "_")
            if key not in catalog:
                return False, "Attack not found."
            del catalog[key]
            touched = remove_attack_from_all_cards(data, key)
            return True, f"{key} removed from {touched} card(s)."

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(msg, ephemeral=True)

    @delete_attack.autocomplete("attack_name")
    async def delete_attack_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._attack_autocomplete(interaction, current)

    @o.command(name="list_attacks", description="Owner: list catalog attacks.")
    async def list_attacks(self, interaction: discord.Interaction) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return
        data = self.bot.storage.load()
        rows = list_attacks(data)
        if not rows:
            await interaction.response.send_message("Attack catalog is empty.", ephemeral=True)
            return
        lines: list[str] = []
        for key, entry in rows[:40]:
            uses = int(entry.get("uses_per_battle", -1))
            uses_text = "∞" if uses == -1 else str(uses)
            lines.append(f"`{key}` • {entry.get('name', key)} • {entry.get('type', '')} • P:{entry.get('power', 0)} • U:{uses_text}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @o.command(name="assign_attack", description="Owner: assign a catalog attack to a card.")
    async def assign_attack(self, interaction: discord.Interaction, card_name: str, attack_name: str) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            return assign_attack_to_card(data, card_name, attack_name)

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(msg, ephemeral=True)

    @assign_attack.autocomplete("card_name")
    async def assign_card_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._card_autocomplete(interaction, current)

    @assign_attack.autocomplete("attack_name")
    async def assign_attack_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._attack_autocomplete(interaction, current)

    @o.command(name="remove_attack", description="Owner: remove an assigned attack from a card.")
    async def remove_attack(self, interaction: discord.Interaction, card_name: str, attack_name: str) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return

        def mutate(data: dict[str, Any]) -> tuple[bool, str]:
            return remove_attack_from_card(data, card_name, attack_name)

        ok, msg = self.bot.storage.with_lock(mutate)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_message(msg, ephemeral=True)

    @remove_attack.autocomplete("card_name")
    async def remove_card_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._card_autocomplete(interaction, current)

    @remove_attack.autocomplete("attack_name")
    async def remove_attack_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._assigned_attack_autocomplete(interaction, current)

    @o.command(name="view_card_attacks", description="Owner: view attacks assigned to a card.")
    async def view_card_attacks(self, interaction: discord.Interaction, card_name: str) -> None:
        if not is_owner(interaction):
            await interaction.response.send_message("Owner only command.", ephemeral=True)
            return
        data = self.bot.storage.load()
        keys = card_attack_keys(data, card_name)
        catalog = data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}
        if not keys:
            await interaction.response.send_message("No attacks assigned.", ephemeral=True)
            return
        grouped: dict[str, list[str]] = {}
        for key in keys:
            entry = catalog.get(key, {}) if isinstance(catalog, dict) else {}
            typ = str(entry.get("type", "unknown")) if isinstance(entry, dict) else "unknown"
            name = str(entry.get("name", key)) if isinstance(entry, dict) else str(key)
            uses = int(entry.get("uses_per_battle", -1)) if isinstance(entry, dict) else -1
            uses_text = "∞" if uses == -1 else str(uses)
            grouped.setdefault(typ, []).append(f"`{key}` • {name} • P:{entry.get('power', 0) if isinstance(entry, dict) else 0} • U:{uses_text}")
        lines: list[str] = []
        for typ in CATALOG_ATTACK_TYPES + ["unknown"]:
            if typ not in grouped:
                continue
            lines.append(f"**{typ}**")
            lines.extend(grouped[typ])
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @view_card_attacks.autocomplete("card_name")
    async def view_card_attacks_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._card_autocomplete(interaction, current)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CardsAdminCog(bot))
