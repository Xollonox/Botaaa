"""Profile embed builder and rank helpers."""

from __future__ import annotations

from typing import Any

import discord


def get_top_rank(data: dict[str, Any], user_id: str) -> tuple[bool, int]:
    """
    Determine if *user_id* is in the top 200 by trophies.

    Returns (is_top_200, rank_number). rank_number is 0 if not in top 200.
    """
    players = data.get("players", {})
    if not isinstance(players, dict):
        return False, 0

    rows = []
    for uid, player in players.items():
        if not isinstance(player, dict):
            continue
        user = player.get("user", {})
        if not isinstance(user, dict):
            continue
        rows.append((str(uid), int(user.get("trophies", 0))))

    rows.sort(key=lambda x: x[1], reverse=True)
    for rank, (uid, _) in enumerate(rows[:200], start=1):
        if uid == str(user_id):
            return True, rank

    return False, 0


def build_profile_embed(
    data: dict[str, Any],
    *,
    viewer_id: str,
    target_user_obj: Any,  # discord.User | discord.Member
    viewer_is_owner: bool = False,
) -> discord.Embed:
    """Build a profile embed for *target_user_obj*."""
    from bot.utils.ui import e, make_embed

    target_id = str(target_user_obj.id)
    players = data.get("players", {})
    player = players.get(target_id, {}) if isinstance(players, dict) else {}
    user = player.get("user", {}) if isinstance(player, dict) else {}
    if not isinstance(user, dict):
        user = {}

    privacy = user.get("privacy_settings", {})
    if not isinstance(privacy, dict):
        privacy = {}

    show_gang = bool(privacy.get("show_gang", True)) or viewer_is_owner or viewer_id == target_id

    balance = int(user.get("balance", 0))
    premium = int(user.get("premium_balance", 0))
    trophies = int(user.get("trophies", 0))
    rank = str(user.get("rank", "Copper"))
    bio = str(user.get("profile", {}).get("bio", "") if isinstance(user.get("profile"), dict) else "")

    is_top, rank_num = get_top_rank(data, target_id)

    fields: list[tuple[str, str, bool]] = []

    if bio:
        fields.append((f"{e('bio', data)} Bio", bio, False))

    fields.append((f"{e('coin', data)} Coins", str(balance), True))
    fields.append((f"{e('gem', data)} Premium", str(premium), True))
    fields.append((f"{e('trophy', data)} Trophies", str(trophies), True))
    fields.append((f"{e('rank', data)} Rank", rank, True))

    if is_top:
        fields.append((f"{e('top', data)} Global Rank", f"#{rank_num}", True))

    if show_gang:
        gang_id = player.get("gang_id") if isinstance(player, dict) else None
        alliance_id = player.get("alliance_id") if isinstance(player, dict) else None
        if gang_id:
            gangs = data.get("gangs", {})
            gang = gangs.get(str(gang_id)) if isinstance(gangs, dict) else None
            gang_name = str(gang.get("name", gang_id)) if isinstance(gang, dict) else str(gang_id)
            fields.append((f"{e('gang', data)} Gang", gang_name, True))
        if alliance_id:
            alliances = data.get("alliances", {})
            alliance = alliances.get(str(alliance_id)) if isinstance(alliances, dict) else None
            alliance_name = str(alliance.get("name", alliance_id)) if isinstance(alliance, dict) else str(alliance_id)
            fields.append((f"{e('alliance', data)} Alliance", alliance_name, True))

    # Featured card
    profile_data = user.get("profile", {}) if isinstance(user.get("profile"), dict) else {}
    showcase_uid = str(profile_data.get("showcase_uid", ""))
    if showcase_uid:
        inventory = user.get("inventory", [])
        if isinstance(inventory, list):
            instance = next(
                (item for item in inventory if isinstance(item, dict) and str(item.get("uid", "")) == showcase_uid),
                None,
            )
            if instance:
                card_name = str(instance.get("card_name", "Unknown"))
                rarity = str(instance.get("rarity", "Common"))
                stars = int(instance.get("stars", 0))
                fields.append((
                    f"{e('featured', data)} Featured Card",
                    f"{card_name} • {rarity} • {e('star', data)}x{stars}",
                    False,
                ))

    embed = make_embed(
        data,
        f"{e('profile', data)} {target_user_obj.display_name}",
        f"Registered player profile.",
        fields=fields,
    )

    avatar = target_user_obj.display_avatar if hasattr(target_user_obj, "display_avatar") else None
    if avatar:
        embed.set_thumbnail(url=avatar.url)

    # Custom background
    bg_url = str(profile_data.get("background_url", "")).strip()
    if not bg_url:
        cfg_profile = data.get("config", {}).get("profile", {})
        if isinstance(cfg_profile, dict):
            bg_url = str(cfg_profile.get("default_background_url", "")).strip()
    if bg_url:
        embed.set_image(url=bg_url)

    return embed
