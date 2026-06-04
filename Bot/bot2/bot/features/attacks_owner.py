"""Owner-only attack catalog and assignment commands."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from bot.config import OWNER_GUILD_ID

from bot.utils.attacks_logic import (
    ATTACK_TYPES,
    attack_key,
    assigned_cards_for_attack,
    card_attack_keys,
    create_attack_entry,
    default_uses_for_type,
    ensure_attacks_structure,
    list_attacks,
    remove_attack_from_all_cards,
    rename_attack_key_everywhere,
    validate_attack_payload,
    validate_attack_type,
)
from bot.utils.checks import is_owner
from bot.utils.ui import box, e, make_embed
from bot.utils.interaction_visibility import smart_reply

OWNER_GUILD = discord.Object(id=OWNER_GUILD_ID)


class AttacksOwnerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _attack_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        ensure_attacks_structure(data)
        catalog = data["attacks"]["catalog"]
        text = current.strip().lower()
        out: list[app_commands.Choice[str]] = []
        for key, entry in catalog.items():
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", key))
            if text and text not in key.lower() and text not in name.lower():
                continue
            out.append(app_commands.Choice(name=f"{name} • {entry.get('type','')}"[:100], value=key))
            if len(out) >= 25:
                break
        return out

    async def _card_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        cards = data.get("cards", {})
        if not isinstance(cards, dict):
            return []
        text = current.strip().lower()
        out: list[app_commands.Choice[str]] = []
        for key in sorted(cards.keys()):
            if text and text not in key.lower():
                continue
            out.append(app_commands.Choice(name=key[:100], value=key))
            if len(out) >= 25:
                break
        return out

    @app_commands.command(name="o_attack_add", description="Owner: add an attack to catalog.")
    @app_commands.guilds(OWNER_GUILD)
    @app_commands.choices(attack_type=[app_commands.Choice(name=t, value=t) for t in ATTACK_TYPES])
    async def o_attack_add(
        self,
        interaction: discord.Interaction,
        name: str,
        attack_type: app_commands.Choice[str],
        power: app_commands.Range[int, 0, None],
        description: str,
        uses_per_battle: app_commands.Range[int, 1, 99] | None = None,
    ) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        attack_type_value = attack_type.value
        if not validate_attack_type(attack_type_value):
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Invalid Type", "Invalid attack_type."), ephemeral=True)
            return

        entry = create_attack_entry(name, attack_type_value, power, description, uses_per_battle)
        valid, msg = validate_attack_payload(entry["name"], entry["type"], entry["power"], entry["description"], entry["uses_per_battle"])
        if not valid:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Invalid Attack", msg), ephemeral=True)
            return

        key = attack_key(name)

        def mutate(state: dict[str, Any]) -> bool:
            ensure_attacks_structure(state)
            catalog = state["attacks"]["catalog"]
            if key in catalog:
                return False
            catalog[key] = entry
            return True

        ok = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Exists", "Attack already exists."), ephemeral=True)
            return

        await smart_reply(interaction, 
            embed=make_embed(
                data,
                f"{e('ok', data)} Attack Added",
                "Catalog entry created.",
                fields=[
                    (f"{e('attacks', data)} Name", entry["name"], False),
                    ("Type", entry["type"], False),
                    ("Power", str(entry["power"]), False),
                    (f"{e('uses', data)} Uses", "∞" if int(entry["uses_per_battle"]) == -1 else str(entry["uses_per_battle"]), False),
                    (f"{e('info', data)} Description", entry["description"] or "-", False),
                ],
            ),
            ephemeral=True,
        )

    @app_commands.command(name="o_attack_edit", description="Owner: edit attack field.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_attack_edit(self, interaction: discord.Interaction, attack_name: str, field: str, value: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        def mutate(state: dict[str, Any]) -> tuple[bool, str, str]:
            ensure_attacks_structure(state)
            catalog = state["attacks"]["catalog"]
            key = attack_name
            if key not in catalog or not isinstance(catalog[key], dict):
                return False, "not_found", ""
            entry = catalog[key]

            before = ""
            after = ""

            if field == "name":
                new_name = value.strip()
                if not new_name:
                    return False, "invalid_name", ""
                new_key = attack_key(new_name)
                if new_key != key and new_key in catalog:
                    return False, "key_exists", ""
                before = entry.get("name", key)
                entry["name"] = new_name
                after = new_name
                if new_key != key:
                    catalog[new_key] = entry
                    del catalog[key]
                    rename_attack_key_everywhere(state, key, new_key)
            elif field == "type":
                if not validate_attack_type(value.strip()):
                    return False, "invalid_type", ""
                before = str(entry.get("type", ""))
                entry["type"] = value.strip()
                after = entry["type"]
            elif field == "power":
                try:
                    p = int(value)
                except ValueError:
                    return False, "invalid_power", ""
                if p < 0:
                    return False, "invalid_power", ""
                before = str(entry.get("power", 0))
                entry["power"] = p
                after = str(p)
            elif field == "description":
                if len(value.strip()) > 300:
                    return False, "invalid_description", ""
                before = str(entry.get("description", ""))
                entry["description"] = value.strip()
                after = entry["description"]
            elif field == "uses_per_battle":
                try:
                    u = int(value)
                except ValueError:
                    return False, "invalid_uses", ""
                if u < -1:
                    return False, "invalid_uses", ""
                before = str(entry.get("uses_per_battle", -1))
                entry["uses_per_battle"] = u
                after = str(u)
            else:
                return False, "invalid_field", ""

            return True, before, after

        ok, before, after = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Edit Failed", str(before)), ephemeral=True)
            return

        await smart_reply(interaction, 
            embed=make_embed(data, f"{e('ok', data)} Attack Updated",
                box("Changes", [f"Before: {before or '-'}", f"After:  {after or '-'}"])),
            ephemeral=True,
        )

    @app_commands.command(name="o_attack_delete", description="Owner: delete attack from catalog and cards.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_attack_delete(self, interaction: discord.Interaction, attack_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        def mutate(state: dict[str, Any]) -> tuple[bool, int]:
            ensure_attacks_structure(state)
            catalog = state["attacks"]["catalog"]
            if attack_name not in catalog:
                return False, 0
            del catalog[attack_name]
            touched = remove_attack_from_all_cards(state, attack_name)
            return True, touched

        ok, touched = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Not Found", "Attack not found."), ephemeral=True)
            return
        await smart_reply(interaction, 
            embed=make_embed(data, f"{e('delete', data)} Attack Deleted",
                box("Result", ["Attack removed.", f"Cards updated: {touched}"])),
            ephemeral=True,
        )

    @app_commands.command(name="o_attack_view", description="Owner: view one attack and where it's assigned.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_attack_view(self, interaction: discord.Interaction, attack_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        ensure_attacks_structure(data)
        entry = data["attacks"]["catalog"].get(attack_name)
        if not isinstance(entry, dict):
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Not Found", "Attack not found."), ephemeral=True)
            return

        cards = assigned_cards_for_attack(data, attack_name)
        await smart_reply(interaction, 
            embed=make_embed(
                data,
                f"{e('view', data)} Attack View",
                "Attack details.",
                fields=[
                    ("Name", str(entry.get("name", attack_name)), False),
                    ("Type", str(entry.get("type", "")), False),
                    ("Power", str(entry.get("power", 0)), False),
                    (f"{e('uses', data)} Uses", "∞" if int(entry.get("uses_per_battle", -1)) == -1 else str(entry.get("uses_per_battle", 0)), False),
                    ("Description", str(entry.get("description", "")) or "-", False),
                    ("Assigned to cards", "\n".join(cards[:30]) if cards else "None", False),
                ],
            ),
            ephemeral=True,
        )

    @app_commands.command(name="o_attack_list", description="Owner: list attack catalog.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_attack_list(self, interaction: discord.Interaction) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        rows = list_attacks(data)
        if not rows:
            await smart_reply(interaction, embed=make_embed(data, f"{e('info', data)} Attack List", "Catalog is empty."), ephemeral=True)
            return

        text = []
        for key, entry in rows[:40]:
            uses = int(entry.get("uses_per_battle", -1))
            uses_txt = "∞" if uses == -1 else str(uses)
            text.append(f"{entry.get('name', key)} • {entry.get('type','')} • P:{entry.get('power',0)} • U:{uses_txt}")
        await smart_reply(interaction, embed=make_embed(data, f"{e('list', data)} Attack Catalog", box("Attacks", text)), ephemeral=True)

    @app_commands.command(name="o_assign_add", description="Owner: assign attack to card.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_assign_add(self, interaction: discord.Interaction, card_name: str, attack_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        def mutate(state: dict[str, Any]) -> bool:
            ensure_attacks_structure(state)
            cards = state.get("cards", {})
            catalog = state["attacks"]["catalog"]
            if not isinstance(cards, dict) or card_name not in cards or attack_name not in catalog:
                return False
            card = cards[card_name]
            if not isinstance(card, dict):
                return False
            card.setdefault("attacks", [])
            if attack_name not in card["attacks"]:
                card["attacks"].append(attack_name)
            return True

        ok = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Assign Failed", "Card or attack not found."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('assign', data)} Assigned", f"{attack_name} -> {card_name}"), ephemeral=True)

    @app_commands.command(name="o_assign_remove", description="Owner: remove attack from card.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_assign_remove(self, interaction: discord.Interaction, card_name: str, attack_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        def mutate(state: dict[str, Any]) -> bool:
            cards = state.get("cards", {})
            if not isinstance(cards, dict) or card_name not in cards:
                return False
            card = cards[card_name]
            if not isinstance(card, dict):
                return False
            atks = card.get("attacks", [])
            if not isinstance(atks, list):
                card["attacks"] = []
                return False
            if attack_name not in atks:
                return False
            card["attacks"] = [x for x in atks if x != attack_name]
            return True

        ok = self.bot.storage.with_lock(mutate)
        data = self.bot.storage.load()
        if not ok:
            await smart_reply(interaction, embed=make_embed(data, f"{e('warning', data)} Remove Failed", "Assignment not found."), ephemeral=True)
            return
        await smart_reply(interaction, embed=make_embed(data, f"{e('ok', data)} Assignment Removed", f"{attack_name} removed from {card_name}"), ephemeral=True)

    @app_commands.command(name="o_assign_view", description="Owner: view attacks assigned to card.")
    @app_commands.guilds(OWNER_GUILD)
    async def o_assign_view(self, interaction: discord.Interaction, card_name: str) -> None:
        data = self.bot.storage.load()
        if not is_owner(interaction):
            await smart_reply(interaction, embed=make_embed(data, f"{e('no', data)} Owner Only", "Not allowed."), ephemeral=True)
            return

        keys = card_attack_keys(data, card_name)
        catalog = data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}
        grouped: dict[str, list[str]] = {}
        for key in keys:
            entry = catalog.get(key, {}) if isinstance(catalog, dict) else {}
            t = str(entry.get("type", "unknown"))
            name = str(entry.get("name", key))
            power = int(entry.get("power", 0)) if isinstance(entry, dict) else 0
            uses = int(entry.get("uses_per_battle", -1)) if isinstance(entry, dict) else -1
            grouped.setdefault(t, []).append(f"{name} • P:{power} • U:{'∞' if uses == -1 else uses}")

        fields = []
        for t in sorted(grouped.keys()):
            fields.append((t, "\n".join(grouped[t])[:1024], False))
        if not fields:
            fields = [(f"{e('info', data)} Assigned", "None", False)]

        await smart_reply(interaction, embed=make_embed(data, f"{e('assign', data)} Card Assignments", card_name, fields=fields), ephemeral=True)

    @o_attack_edit.autocomplete("attack_name")
    @o_attack_delete.autocomplete("attack_name")
    @o_attack_view.autocomplete("attack_name")
    @o_assign_add.autocomplete("attack_name")
    async def attack_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._attack_autocomplete(interaction, current)

    @o_assign_add.autocomplete("card_name")
    @o_assign_remove.autocomplete("card_name")
    @o_assign_view.autocomplete("card_name")
    async def card_name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self._card_autocomplete(interaction, current)

    @o_assign_remove.autocomplete("attack_name")
    async def assigned_attack_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        data = self.bot.storage.load()
        card_name = str(getattr(interaction.namespace, "card_name", ""))
        keys = card_attack_keys(data, card_name)
        catalog = data.get("attacks", {}).get("catalog", {}) if isinstance(data.get("attacks", {}), dict) else {}
        text = current.strip().lower()
        out: list[app_commands.Choice[str]] = []
        for key in keys:
            entry = catalog.get(key, {}) if isinstance(catalog, dict) else {}
            name = str(entry.get("name", key))
            if text and text not in key.lower() and text not in name.lower():
                continue
            out.append(app_commands.Choice(name=f"{name} • {entry.get('type','')}"[:100], value=key))
            if len(out) >= 25:
                break
        return out


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AttacksOwnerCog(bot))
