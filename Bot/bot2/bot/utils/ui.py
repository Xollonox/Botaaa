"""LOOKISM HXCC UI helpers: emoji lookup, embed construction, and view styling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import discord

from bot.data.defaults import DEFAULT_UI_EMOJIS

EMBED_COLORS = {
    "info": 0x2B2D31,
    "success": 0x57F287,
    "warning": 0xFEE75C,
    "error": 0xED4245,
    "battle": 0xE53935,
    "economy": 0xF1C40F,
    "market": 0x2ECC71,
    "profile": 0x8E44AD,
    "reward": 0xFF9F43,
    "owner": 0x5865F2,
    "premium": 0xC084FC,
}

RARITY_COLORS = {
    "common": 0xAAB2BD,
    "rare": 0x3498DB,
    "epic": 0x9B59B6,
    "legendary": 0xF39C12,
    "mythical": 0xE74C3C,
    "infernal": 0xC0392B,
    "abyssal": 0x5B2C6F,
}

_VARIANT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "battle": ("battle", "duel", "match", "attack", "queue", "friendly", "ranked", "forfeit"),
    "economy": ("coin", "balance", "reward", "daily", "weekly", "monthly", "premium", "gem", "shop", "pack"),
    "market": ("market", "listing", "sell", "buy", "store", "trade"),
    "profile": ("profile", "bio", "featured", "collection", "inventory", "league"),
    "owner": ("owner", "admin", "settings", "panel", "manage", "catalog"),
    "success": ("success", "updated", "saved", "accepted", "completed", "claimed", "registered"),
    "warning": ("warning", "missing", "invalid", "empty", "wait", "locked"),
    "error": ("error", "failed", "denied", "not allowed", "not found", "cancelled"),
}

_BUTTON_EMOJI_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("prev", "previous", "back"), "prev"),
    (("next", "forward"), "next"),
    (("home", "hub"), "help"),
    (("close", "cancel", "deny", "decline"), "cancel"),
    (("confirm", "accept", "join", "claim", "save", "apply"), "confirm"),
    (("upgrade", "star"), "star"),
    (("lock",), "lock"),
    (("unlock",), "unlock"),
    (("favorite", "favourite"), "favorite"),
    (("battle", "fight", "queue"), "battle"),
    (("attack",), "attack_special"),
    (("switch", "swap"), "switch"),
    (("filter",), "filter"),
    (("page",), "page"),
    (("set", "edit"), "edit"),
    (("delete", "remove"), "delete"),
    (("buy",), "buy"),
    (("sell",), "sell"),
)

_BUTTON_STYLE_KEYWORDS: tuple[tuple[tuple[str, ...], discord.ButtonStyle], ...] = (
    (("confirm", "accept", "join", "save", "apply", "claim"), discord.ButtonStyle.success),
    (("close", "cancel", "deny", "decline", "delete", "remove", "forfeit"), discord.ButtonStyle.danger),
    (("next",), discord.ButtonStyle.primary),
    (("upgrade",), discord.ButtonStyle.success),
)

_PREMIUM_AUTHOR = "LOOKISM HXCC"

_LEADING_EMOJI_KEYS: tuple[tuple[str, str], ...] = (
    ("⚔️", "battle"), ("⚔", "battle"),
    ("🗡️", "attack_normal"), ("🗡", "attack_normal"),
    ("🛡️", "defense"), ("🛡", "defense"),
    ("🛤️", "attack_ultimate"), ("🛤", "attack_ultimate"),
    ("❤️", "hp"), ("❤", "hp"),
    ("✅", "ok"), ("☑️", "confirm"), ("☑", "confirm"),
    ("➡️", "next"), ("➡", "next"),
    ("🔒", "locked"),
    ("🪙", "coin"), ("💰", "coin"), ("💎", "gem"),
    ("🃏", "catalog"),
    ("💥", "attack_special"), ("🌀", "attack_unique_skill"),
    ("🏆", "trophy"), ("🤝", "alliance"), ("👑", "head"),
    ("💪", "strength"), ("🏃", "speed"), ("🧱", "endurance"),
    ("🎯", "technique"), ("🧠", "iq"), ("👁️", "biq"), ("👁", "biq"),
    ("⚡", "boost"),
    ("🔵", "rare"), ("🟣", "epic"), ("🟠", "legendary"),
    ("🔴", "mythical"), ("🔥", "infernal"), ("🌌", "abyssal"),
)

_TEXT_EMOJI_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("⚡ Total Power", "squad_power"),
    ("⚡ Power", "squad_power"),
    ("💪 STR", "strength"),
    ("⚡ SPD", "speed"),
    ("🏃 SPD", "speed"),
    ("🛡️ END", "endurance"),
    ("🛡 END", "endurance"),
    ("🧱 END", "endurance"),
    ("🎯 TEC", "technique"),
    ("🧠 IQ", "iq"),
    ("🔮 BIQ", "biq"),
    ("👁️ BIQ", "biq"),
    ("👁 BIQ", "biq"),
    ("❤️ HP", "hp"),
    ("❤ HP", "hp"),
    ("⚔️", "battle"),
    ("⚔", "battle"),
    ("🛡️", "defense"),
    ("🛡", "defense"),
    ("✅", "ok"),
    ("🔒", "locked"),
    ("🪙", "coin"),
    ("💰", "coin"),
    ("💎", "gem"),
    ("🏆", "trophy"),
    ("🤝", "alliance"),
    ("👑", "head"),
    ("💪", "strength"),
    ("🏃", "speed"),
    ("🧱", "endurance"),
    ("🎯", "technique"),
    ("🧠", "iq"),
    ("👁️", "biq"),
    ("👁", "biq"),
    ("🔵", "rare"),
    ("🟣", "epic"),
    ("🟠", "legendary"),
    ("🔴", "mythical"),
    ("🔥", "infernal"),
    ("🌌", "abyssal"),
)

_TEXT_EMOJI_LABELS: dict[str, str] = {
    "⚡ Total Power": "Total Power",
    "⚡ Power": "Power",
    "💪 STR": "STR",
    "⚡ SPD": "SPD",
    "🏃 SPD": "SPD",
    "🛡️ END": "END",
    "🛡 END": "END",
    "🧱 END": "END",
    "🎯 TEC": "TEC",
    "🧠 IQ": "IQ",
    "🔮 BIQ": "BIQ",
    "👁️ BIQ": "BIQ",
    "👁 BIQ": "BIQ",
    "❤️ HP": "HP",
    "❤ HP": "HP",
}


def e(key: str, data: dict[str, Any] | None = None) -> str:
    """Return emoji string for *key* from server data, falling back to defaults."""
    emojis: dict[str, Any] = {}
    if isinstance(data, dict):
        ui = data.get("ui")
        if isinstance(ui, dict):
            emojis = ui.get("emojis", {}) if isinstance(ui.get("emojis"), dict) else {}
    return str(emojis.get(key) or DEFAULT_UI_EMOJIS.get(key) or "•")


def named_e(label: str, data: dict[str, Any] | None = None, fallback: str = "dot") -> str:
    """Resolve a display label such as ``Strength Mastery`` to an emoji key."""
    normalized = str(label or "").strip().lower().replace(" mastery", "")
    normalized = normalized.replace(" ", "_").replace("-", "_")
    value = e(normalized, data)
    return value if value != "•" else e(fallback, data)


def _safe_component_emoji(key: str, data: dict[str, Any] | None = None) -> str | None:
    """Return emoji safe for Discord component fields.

    discord.py parses custom emoji strings such as ``<:name:id>`` into a
    PartialEmoji. Unicode variation selectors are removed for select options.

    Returns a clean unicode emoji or None if it would be invalid.
    """
    raw = e(key, data)
    if not raw or raw == "•":
        return None
    cleaned = raw.replace("\uFE0F", "").replace("️", "").strip()
    if not cleaned or cleaned == "•":
        return None
    return cleaned


def _replace_text_emojis(text: Any, data: dict[str, Any] | None = None) -> str:
    """Replace legacy Unicode UI icons in embed text with configured emojis."""
    rendered = str(text or "")
    for token, key in _TEXT_EMOJI_REPLACEMENTS:
        if token in rendered:
            label = _TEXT_EMOJI_LABELS.get(token, "")
            replacement = f"{e(key, data)} {label}" if label else e(key, data)
            rendered = rendered.replace(token, replacement)
    return rendered


def _pop_leading_emoji(label: str) -> tuple[str | None, str]:
    """Return a configured key and a label with its legacy leading icon removed."""
    stripped = str(label or "").strip()
    for token, key in _LEADING_EMOJI_KEYS:
        if stripped.startswith(token):
            return key, stripped[len(token):].strip()
    return None, stripped


def _configured_component_emoji(raw: Any, data: dict[str, Any] | None = None) -> str | None:
    rendered = str(raw or "").replace("\uFE0F", "").replace("️", "").strip()
    for token, key in _LEADING_EMOJI_KEYS:
        normalized = token.replace("\uFE0F", "").replace("️", "")
        if rendered == normalized:
            return _safe_component_emoji(key, data)
    return None


def divider(data: dict[str, Any] | None = None, width: int = 18) -> str:
    line = e("line", data)
    if not line or line == "•":
        line = "━"
    return str(line) * max(3, width)

def box(title: str, lines: list[str]) -> str:
    """Format a ╭─ ... ╰──────────────── block matching the squad panel style."""
    body = "\n".join(f"│ {l}" for l in lines)
    return f"╭─ {title}\n{body}\n╰────────────────"



def mini_bar(percent: float, slots: int = 10, filled: str = "▰", empty: str = "▱") -> str:
    safe = max(0.0, min(100.0, float(percent)))
    on = round(safe / 100 * slots)
    return f"{filled * on}{empty * (slots - on)}"


def _trim(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _infer_variant(title: str, description: str, variant: str) -> str:
    candidate = str(variant or "").strip().lower()
    if candidate in EMBED_COLORS:
        return candidate

    blob = f"{title}\n{description}".lower()
    for name, words in _VARIANT_KEYWORDS.items():
        if any(word in blob for word in words):
            return name

    for rarity, color in RARITY_COLORS.items():
        if rarity in blob:
            return rarity

    return "info"


def _choose_color(title: str, description: str, color: int | None, variant: str) -> int:
    if color is not None:
        return int(color)
    inferred = _infer_variant(title, description, variant)
    if inferred in RARITY_COLORS:
        return RARITY_COLORS[inferred]
    return EMBED_COLORS.get(inferred, EMBED_COLORS["info"])


def _footer_text(data: dict[str, Any] | None) -> str:
    if isinstance(data, dict):
        cfg = data.get("config", {})
        if isinstance(cfg, dict):
            ui_cfg = cfg.get("ui", {})
            if isinstance(ui_cfg, dict):
                footer = str(ui_cfg.get("footer", "")).strip()
                if footer:
                    return footer
    return "LOOKISM HXCC • /help"


def _prepare_description(data: dict[str, Any] | None, description: str) -> str:
    desc = (description or "").strip()
    if not desc:
        return ""
    return _trim(desc, 4096)


def _decorate_field_name(data: dict[str, Any] | None, name: Any) -> str:
    clean = _trim(name, 256)
    if not clean:
        return f"{e('box', data)} Panel"
    if clean[0] in {"•", "▪", "▣", "◆", "◇"}:
        return clean
    return f"{e('box', data)} {clean}"


def _decorate_field_value(value: Any) -> str:
    text = _trim(value, 1024)
    return text or "—"


def make_embed(
    data: dict[str, Any] | None,
    title: str,
    description: str = "",
    *,
    color: int | None = None,
    variant: str = "info",
    fields: list[tuple[str, str, bool]] | None = None,
    author_name: str | None = None,
    footer: str | None = None,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
) -> discord.Embed:
    """Build a standard LOOKISM HXCC Discord embed."""
    clean_title = _trim(_replace_text_emojis(title or "Interface", data), 256)
    clean_description = _prepare_description(data, _replace_text_emojis(description, data))
    chosen_color = _choose_color(clean_title, clean_description, color, variant)

    embed = discord.Embed(
        title=clean_title,
        description=clean_description,
        color=chosen_color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=author_name or _PREMIUM_AUTHOR)
    embed.set_footer(text=footer or _footer_text(data))

    if image_url:
        embed.set_image(url=image_url)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)

    if fields:
        for name, value, inline in fields[:25]:
            embed.add_field(
                name=_decorate_field_name(data, _replace_text_emojis(name, data)),
                value=_decorate_field_value(_replace_text_emojis(value, data)),
                inline=bool(inline),
            )

    return embed


def simple_embed(description: str, color: int = 0x2B2D31, *, author: str = "", footer: str = "") -> discord.Embed:
    """Quick description-only embed with optional styling."""
    embed = discord.Embed(description=description, color=color, timestamp=datetime.now(timezone.utc))
    embed.set_author(name=author or _PREMIUM_AUTHOR)
    embed.set_footer(text=footer or "LOOKISM HXCC • /help")
    return embed


def skin_embed(embed: discord.Embed, interaction: Any | None = None, data: dict[str, Any] | None = None) -> discord.Embed:
    """Apply premium polish to embeds created elsewhere."""
    if embed is None:
        return embed

    if not embed.title:
        embed.title = "LOOKISM HXCC"
    else:
        embed.title = _trim(_replace_text_emojis(embed.title, data), 256)

    if embed.description:
        embed.description = _trim(_replace_text_emojis(embed.description, data), 4096)

    for index, field in enumerate(embed.fields):
        embed.set_field_at(
            index,
            name=_trim(_replace_text_emojis(field.name, data), 256),
            value=_trim(_replace_text_emojis(field.value, data), 1024),
            inline=field.inline,
        )

    if not embed.color or int(embed.color) == 0:
        embed.color = _choose_color(str(embed.title or ""), str(embed.description or ""), None, "info")

    if not embed.footer or not getattr(embed.footer, "text", ""):
        embed.set_footer(text=_footer_text(data))

    if not embed.author or not getattr(embed.author, "name", ""):
        command_name = getattr(getattr(interaction, "command", None), "name", "") if interaction is not None else ""
        if command_name:
            system = command_name.replace("_", " ").upper()
            author_name = f"LOOKISM HXCC • {system}"
        else:
            author_name = _PREMIUM_AUTHOR
        icon_url = None
        guild = getattr(interaction, "guild", None) if interaction is not None else None
        if guild is not None:
            guild_icon = getattr(guild, "icon", None)
            icon_url = getattr(guild_icon, "url", None) if guild_icon else None
        if icon_url:
            embed.set_author(name=author_name, icon_url=icon_url)
        else:
            embed.set_author(name=author_name)

    if getattr(embed, "timestamp", None) is None:
        embed.timestamp = datetime.now(timezone.utc)

    return embed


def _match_keyword(text: str, groups: Iterable[tuple[tuple[str, ...], Any]]) -> Any | None:
    lowered = text.lower()
    for words, value in groups:
        if any(word in lowered for word in words):
            return value
    return None


def style_view(view: discord.ui.View, data: dict[str, Any] | None = None) -> discord.ui.View:
    """Normalize buttons/selects into a richer premium interface."""
    for child in getattr(view, "children", []):
        if isinstance(child, discord.ui.Button):
            label = str(child.label or "").strip()
            explicit_key, label = _pop_leading_emoji(label)
            if explicit_key:
                child.label = label or None
            if not label and child.emoji is None:
                label = "Action"
                child.label = label

            emoji_key = _match_keyword(label, _BUTTON_EMOJI_KEYWORDS)
            configured_existing = _configured_component_emoji(child.emoji, data)
            if configured_existing:
                child.emoji = configured_existing
            elif child.emoji is None and (explicit_key or emoji_key):
                child.emoji = _safe_component_emoji(str(explicit_key or emoji_key), data)

            mapped_style = _match_keyword(label, _BUTTON_STYLE_KEYWORDS)
            if mapped_style is not None and child.style in {
                discord.ButtonStyle.secondary,
                discord.ButtonStyle.primary,
                discord.ButtonStyle.success,
                discord.ButtonStyle.danger,
            }:
                child.style = mapped_style

            if child.label:
                child.label = _trim(child.label, 80)

        elif isinstance(child, discord.ui.Select):
            placeholder = str(child.placeholder or "").strip()
            if not placeholder:
                child.placeholder = "Choose an option"
            else:
                child.placeholder = _trim(placeholder, 100)

            rebuilt: list[discord.SelectOption] = []
            for idx, opt in enumerate(list(child.options)[:25], start=1):
                label = _trim(getattr(opt, "label", "") or f"Option {idx}", 100)
                explicit_key, label = _pop_leading_emoji(label)
                label = _trim(label or f"Option {idx}", 100)
                value = str(getattr(opt, "value", "") or f"option_{idx}")
                description = getattr(opt, "description", None)
                if isinstance(description, str):
                    description = _trim(description, 100)
                emoji = getattr(opt, "emoji", None)
                configured_existing = _configured_component_emoji(emoji, data)
                if configured_existing:
                    emoji = configured_existing
                elif emoji is None:
                    emoji_key = _match_keyword(label, _BUTTON_EMOJI_KEYWORDS)
                    if explicit_key or emoji_key:
                        emoji = _safe_component_emoji(str(explicit_key or emoji_key), data)
                rebuilt.append(
                    discord.SelectOption(
                        label=label,
                        value=value,
                        description=description,
                        emoji=emoji,
                        default=bool(getattr(opt, "default", False)),
                    )
                )
            if rebuilt:
                child.options = rebuilt

    return view


def list_keys(data: dict[str, Any]) -> list[str]:
    """Return all known emoji keys from the data."""
    ui = data.get("ui")
    if isinstance(ui, dict):
        emojis = ui.get("emojis", {})
        if isinstance(emojis, dict):
            return sorted(emojis.keys())
    return sorted(DEFAULT_UI_EMOJIS.keys())


def set_emoji(data: dict[str, Any], key: str, value: str) -> None:
    """Set *key* emoji to *value* in *data*."""
    ui = data.setdefault("ui", {})
    if not isinstance(ui, dict):
        ui = {}
        data["ui"] = ui
    emojis = ui.setdefault("emojis", {})
    if not isinstance(emojis, dict):
        emojis = {}
        ui["emojis"] = emojis
    emojis[key] = value


def reset_emoji(data: dict[str, Any], key: str) -> None:
    """Reset *key* emoji to its default value."""
    default = DEFAULT_UI_EMOJIS.get(key, "•")
    set_emoji(data, key, default)


def reset_all_emojis(data: dict[str, Any]) -> None:
    """Reset all emojis to their defaults."""
    from copy import deepcopy

    ui = data.setdefault("ui", {})
    if not isinstance(ui, dict):
        ui = {}
        data["ui"] = ui
    ui["emojis"] = deepcopy(DEFAULT_UI_EMOJIS)
