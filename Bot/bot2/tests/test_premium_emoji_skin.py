from __future__ import annotations

import discord

from bot.data.defaults import DEFAULT_UI_EMOJIS, ensure_structure
from bot.utils.ui import make_embed, named_e, style_view


SUPPLIED_EMOJIS = {
    "<:Ultimate:1471032754245337120>",
    "<:Trophy:1469971235453665345>",
    "<:alliance:1471027139003547732>",
    "<:battle:1470382015437213697>",
    "<:boost:1470334901319635108>",
    "<:bronze:1469956844423221410>",
    "<:catalog:1470375205682548961>",
    "<:conviction:1471198977859915962>",
    "<:copper:1471033174070001849>",
    "<:currency:1469410492010463458>",
    "<:defense:1471196697659965461>",
    "<:diamond:1469958014197956659>",
    "<:elder:1470762649817186409>",
    "<:emoji_22:1470382114699743457>",
    "<:endurance:1471199091483476080>",
    "<:gang:1470719084848222368>",
    "<:gold:1469956985574264874>",
    "<:gold_bars:1470374537836232785>",
    "<:head:1470759627238019209>",
    "<:heart:1470383079548780625>",
    "<:iron:1469956766321344606>",
    "<:locked:1470383807311122615>",
    "<:mastermind:1471199662596816999>",
    "<:member:1470761309430616259>",
    "<:normal:1471030412015960269>",
    "<:platinum:1469958087359332415>",
    "<:recruiter:1470759718107746441>",
    "<:ruby:1470383178374971476>",
    "<:sapphire:1469958126462570669>",
    "<:silver:1469956922454311003>",
    "<:skill:1471196099912929443>",
    "<:special:1471032701132865566>",
    "<:speed:1471198923665178740>",
    "<:squad_power:1469972804408574033>",
    "<:stats_rank:1470382074086031505>",
    "<:strength:1471199061108588748>",
    "<:technique:1471199020989943975>",
    "<:vice_head:1470759664999207115>",
    "<:stars:1471032797551530145>",
    "<:r1:1487355065084936254>",
}


def test_all_supplied_emojis_are_registered() -> None:
    assert SUPPLIED_EMOJIS <= set(DEFAULT_UI_EMOJIS.values())


def test_legacy_defaults_upgrade_removes_unsupported_custom_emojis() -> None:
    data = {
        "ui": {
            "emojis": {
                "coin": "🪙",
                "battle": "<:owner_battle:123456789012345678>",
            }
        }
    }

    upgraded = ensure_structure(data)["ui"]["emojis"]

    assert upgraded["coin"] == "<:currency:1469410492010463458>"
    assert upgraded["battle"] == "<:battle:1470382015437213697>"


def test_embed_skin_replaces_legacy_stat_and_currency_icons() -> None:
    embed = make_embed(
        None,
        "🏆 Premium Battle",
        "💪 STR: 99 | ⚡ SPD: 88 | 🛡 END: 77 | 💎 50 | 💰 100",
    )

    assert embed.title == "<:Trophy:1469971235453665345> Premium Battle"
    assert "<:strength:1471199061108588748> STR: 99" in embed.description
    assert "<:speed:1471198923665178740> SPD: 88" in embed.description
    assert "<:endurance:1471199091483476080> END: 77" in embed.description
    assert "💎 50" in embed.description
    assert "<:currency:1469410492010463458> 100" in embed.description


def test_view_skin_moves_legacy_icons_into_component_emoji_fields() -> None:
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="⚔️ Battle"))
    view.add_item(
        discord.ui.Select(
            options=[discord.SelectOption(label="💎 Premium", value="premium")]
        )
    )

    style_view(view)

    button = view.children[0]
    select = view.children[1]
    assert isinstance(button, discord.ui.Button)
    assert isinstance(select, discord.ui.Select)
    assert button.label == "Battle"
    assert str(button.emoji) == "<:battle:1470382015437213697>"
    assert select.options[0].label == "Premium"
    assert str(select.options[0].emoji) == "💎"


def test_named_mastery_emojis_use_matching_custom_icons() -> None:
    assert named_e("Strength Mastery") == "<:strength:1471199061108588748>"
    assert named_e("Conviction Mastery") == "<:conviction:1471198977859915962>"
    assert named_e("Mastermind") == "<:mastermind:1471199662596816999>"
