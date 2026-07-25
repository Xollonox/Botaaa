"""Profile player commands — Cinematic Overlay redesign (Option A).

Layout:
  • Full canvas = featured card art as background with dramatic lighting
  • Left glass panel: avatar, username, league icon, bio, XP bar, info rows
  • Right stats grid: 2×3 stat boxes (trophies, rank, win rate, battles, streak, cards)
  • All other logic (UI classes, setbio, setfeatured, embed fallback) untouched
"""

from __future__ import annotations

import io
import logging
import re
import traceback
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

from bot.utils.checks import ensure_registered
from bot.utils.ui import e, make_embed, simple_embed
from bot.utils.xp_logic import xp_progress

_MAX_BIO_LENGTH = 150
_LINK_RE        = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MENTION_RE     = re.compile(r"@(?:everyone|here)", re.IGNORECASE)
_CUSTOM_EMOJI_RE = re.compile(r"<a?:([A-Za-z0-9_]+):(\d+)>")

_RARITY_ORDER = {
    "mythical": 6, "legendary": 5, "epic": 4,
    "rare": 3,    "common": 2,    "basic": 1,
}

# ── Palette — Blue/Cyan ───────────────────────────────────────────────────────
_BG             = (4,    8,  18, 255)
_GLASS_BG       = (4,    10, 26, 195)   # deep navy semi-transparent
_GLASS_BORDER   = (0,   180, 255,  45)  # cyan border glow
_ACCENT         = (0,   200, 255)        # electric cyan
_ACCENT2        = (80,  140, 255)        # royal blue
_TEXT_WHITE     = (225, 245, 255)
_TEXT_SUB       = (140, 195, 230)
_TEXT_DIM       = (70,  110, 155)
_TEXT_GOLD      = (0,   220, 255)        # bright cyan
_BORDER_DIM     = (15,  45,  85)
_HP_GREEN       = (0,   220, 180)
_HP_YELLOW      = (80,  180, 255)
_HP_RED         = (0,   160, 255)
_XP_LEFT        = (0,   120, 255)        # deep blue
_XP_RIGHT       = (0,   230, 255)        # electric cyan
_BULLET_COL     = (0,   200, 255, 160)
_DISCORD_BOX_BG = (47,  49,  54, 215)


# ── Font helper ───────────────────────────────────────────────────────────────
def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
    candidates += [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _emoji_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/system/fonts/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return _font(size)


# ── Image helpers ─────────────────────────────────────────────────────────────
def _rounded_mask(size: tuple[int,int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return m

def _circle_mask(size: tuple[int,int]) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse((0, 0, size[0], size[1]), fill=255)
    return m

def _crop_cover(img: Image.Image, size: tuple[int,int]) -> Image.Image:
    sw, sh = img.size
    dw, dh = size
    if sw <= 0 or sh <= 0:
        return img.resize(size)
    if sw/sh > dw/dh:
        nw = int(sh * dw / dh)
        img = img.crop(((sw-nw)//2, 0, (sw-nw)//2+nw, sh))
    else:
        nh = int(sw * dh / dw)
        img = img.crop((0, (sh-nh)//2, sw, (sh-nh)//2+nh))
    return img.resize(size, Image.Resampling.LANCZOS)

def _emoji_cdn_url(token: str) -> str | None:
    m = _CUSTOM_EMOJI_RE.fullmatch((token or "").strip())
    if not m:
        return None
    ext = "gif" if token.startswith("<a:") else "png"
    return f"https://cdn.discordapp.com/emojis/{m.group(2)}.{ext}?quality=lossless"

async def _fetch_image(session: aiohttp.ClientSession, url: str) -> Image.Image | None:
    if not url or not url.startswith(("http://","https://")):
        return None
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*;q=0.8"}
    for candidate in [url, url.split("?",1)[0]]:
        try:
            async with session.get(candidate, timeout=aiohttp.ClientTimeout(total=12), headers=headers) as r:
                if r.status != 200:
                    continue
                return Image.open(io.BytesIO(await r.read())).convert("RGBA")
        except Exception:
            continue
    return None


# ── Data helpers (unchanged from original) ────────────────────────────────────
def _sanitize_bio(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text or "")
    text = _MENTION_RE.sub("", text)
    return text.strip()

def _display_name(target: discord.abc.User) -> str:
    return getattr(target,"display_name",None) or getattr(target,"global_name",None) or target.name

def _join_date(user_data: dict[str,Any]) -> str:
    ts = int(user_data.get("registered_at", 0) or 0)
    if ts <= 0:
        return "Unknown"
    return datetime.utcfromtimestamp(ts).strftime("%d %b %Y")

def _player_level(user_data: dict[str,Any]) -> int:
    stored = int(user_data.get("level", 0) or 0)
    if stored > 0:
        return stored
    level, _, _ = xp_progress(int(user_data.get("xp", 0) or 0))
    return max(1, int(level))

def _xp_progress_pct(user_data: dict[str,Any]) -> tuple[int, int, int, float]:
    """Returns (level, xp_current, xp_needed, pct 0-1)."""
    raw_xp = int(user_data.get("xp", 0) or 0)
    level, cur, needed = xp_progress(raw_xp)
    pct = max(0.0, min(1.0, cur / max(1, needed)))
    return int(level), cur, needed, pct

def _gang_name(data: dict[str,Any], player: dict[str,Any]) -> str:
    gang_id = player.get("gang_id") if isinstance(player,dict) else None
    gangs   = data.get("gangs", {})
    if gang_id and isinstance(gangs, dict):
        gang = gangs.get(str(gang_id), {})
        if isinstance(gang, dict):
            return str(gang.get("name", gang_id))
    return "No Gang"

def _war_points(player: dict[str,Any], user_data: dict[str,Any]) -> int:
    for src in (user_data, player if isinstance(player,dict) else {}):
        for key in ("war_points","warpoints","war_pts"):
            val = src.get(key)
            if val is not None:
                return int(val)
    return 0

def _achievements_count(user_data: dict[str,Any]) -> int:
    a = user_data.get("achievements", [])
    if isinstance(a, (list, dict)):
        return len(a)
    return int(user_data.get("achievements_count", 0) or 0)

def _cards_unlocked_count(user_data: dict[str,Any]) -> int:
    inv = user_data.get("inventory", [])
    if isinstance(inv, list):
        return len(inv)
    return int(user_data.get("cards_unlocked", 0) or 0)

def _rank_rows(data: dict[str,Any]) -> list[tuple[str,int]]:
    players = data.get("players", {})
    if not isinstance(players, dict):
        return []
    rows = []
    for uid, player in players.items():
        if not isinstance(player,dict): continue
        user = player.get("user", {})
        if not isinstance(user,dict):   continue
        rows.append((str(uid), int(user.get("trophies", 0))))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows

def _league_rank_emoji(data: dict[str,Any], league_name: str) -> str:
    normalized = str(league_name or "").strip().lower()
    fallback_map = {
        "copper":"🥉","iron":"🪙","bronze":"🥉","silver":"🥈",
        "gold":"🥇","diamond":"💎","platinum":"🔷","sapphire":"💠",
        "ruby":"🔴","unranked":"🏅",
    }
    fallback = fallback_map.get(normalized, "🏅")
    if normalized:
        value = str(e(normalized, data)).strip()
        if value and value != "•":
            return value
    val2 = str(e("league", data)).strip()
    return val2 if val2 and val2 != "•" else fallback

def _resolve_card_by_uid(inventory: list[dict[str,Any]], uid: str) -> dict[str,Any] | None:
    return next((i for i in inventory if isinstance(i,dict) and str(i.get("uid",""))==uid), None)

def _resolve_card_catalog_entry(cards_catalog: dict[str,Any], card_name: str) -> dict[str,Any]:
    if not isinstance(cards_catalog, dict): return {}
    normalized = str(card_name or "").strip()
    if not normalized: return {}
    direct = cards_catalog.get(normalized)
    if isinstance(direct, dict): return direct
    lowered = normalized.casefold()
    for key, value in cards_catalog.items():
        if not isinstance(value, dict): continue
        if any(n and n.casefold()==lowered for n in {str(key).strip(), str(value.get("name","")).strip(), str(value.get("card_name","")).strip()}):
            return value
    return {}

def _card_image_value(card: dict[str,Any] | None) -> str:
    if not isinstance(card, dict): return ""
    for key in ("image_url","image","img_url","img","card_image","art_url","thumbnail_url"):
        v = str(card.get(key) or "").strip()
        if v.startswith(("http://","https://")):
            return v
    art = card.get("art", {})
    if isinstance(art, dict):
        for key in ("image_url","image","url","thumbnail_url"):
            v = str(art.get(key) or "").strip()
            if v.startswith(("http://","https://")):
                return v
    return ""

def _featured_card_block(data: dict[str,Any], user_data: dict[str,Any]) -> tuple[str,str]:
    profile_data  = user_data.get("profile", {}) if isinstance(user_data.get("profile"),dict) else {}
    featured_uid  = str(profile_data.get("showcase_uid","")).strip()
    inventory     = user_data.get("inventory", []) if isinstance(user_data.get("inventory"),list) else []
    cards_catalog = data.get("cards", {}) if isinstance(data.get("cards"),dict) else {}
    if not featured_uid:
        return "No featured card", ""
    card = _resolve_card_by_uid(inventory, featured_uid)
    if not isinstance(card, dict):
        return "No featured card", ""
    card_name = str(card.get("card_name") or card.get("name") or "Unknown").strip() or "Unknown"
    card_def  = _resolve_card_catalog_entry(cards_catalog, card_name)
    image_url = _card_image_value(card) or _card_image_value(card_def)
    return card_name, image_url

def _profile_badges_text(data: dict[str,Any], player: dict[str,Any], user_data: dict[str,Any]) -> str:
    profile_data = user_data.get("profile", {}) if isinstance(user_data.get("profile"),dict) else {}
    cosmetics    = profile_data.get("cosmetics", {}) if isinstance(profile_data.get("cosmetics"),dict) else {}
    badge_id     = str(cosmetics.get("badge_id") or profile_data.get("badge_id") or "").strip()
    ranked_stats = player.get("ranked_stats", {}) if isinstance(player,dict) else {}
    streak       = int(ranked_stats.get("streak",0)) if isinstance(ranked_stats,dict) else 0
    trophies     = int(user_data.get("trophies",0))
    level        = _player_level(user_data)
    badges: list[str] = []
    if badge_id:
        badges.append(badge_id.replace("_"," ").strip().title())
    if trophies >= 4000: badges.append("Diamond")
    elif trophies >= 2000: badges.append("Gold")
    elif trophies >= 1000: badges.append("Silver")
    if streak >= 5:   badges.append("Hot Streak")
    if level >= 50:   badges.append("Veteran")
    gang_id = player.get("gang_id") if isinstance(player,dict) else None
    gangs   = data.get("gangs", {}) if isinstance(data.get("gangs"),dict) else {}
    if gang_id and isinstance(gangs,dict):
        try:
            from bot.utils.gang_logic import get_role_label
            gang = gangs.get(str(gang_id), {})
            if isinstance(gang,dict) and str(get_role_label(gang, str(user_data.get("id","")))).strip().lower() == "head":
                badges.append("Gang Head")
        except Exception:
            pass
    deduped: list[str] = []
    seen: set[str]     = set()
    for b in badges:
        if b.lower() not in seen:
            seen.add(b.lower()); deduped.append(b)
    if not deduped: return "No badges"
    if len(deduped) <= 3: return ", ".join(deduped)
    return f"{', '.join(deduped[:3])} +{len(deduped)-3} more"


# ── Drawing primitives ────────────────────────────────────────────────────────

def _draw_glass_panel(canvas: Image.Image, x1: int, y1: int, x2: int, y2: int, radius: int = 28) -> None:
    """Semi-transparent frosted glass panel."""
    w, h = x2 - x1, y2 - y1
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pd    = ImageDraw.Draw(panel)
    pd.rounded_rectangle((0, 0, w, h), radius=radius, fill=_GLASS_BG)
    pd.rounded_rectangle((0, 0, w, h), radius=radius, outline=_GLASS_BORDER, width=2)
    canvas.alpha_composite(panel, (x1, y1))


def _draw_gradient_bar(
    canvas: Image.Image,
    x: int, y: int, w: int, h: int,
    pct: float,
    col_left: tuple, col_right: tuple,
    bg_col: tuple = (30, 30, 44, 180),
    radius: int = 0,
) -> None:
    """Horizontal gradient progress bar."""
    # track
    track = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    td    = ImageDraw.Draw(track)
    r     = radius or h // 2
    td.rounded_rectangle((0, 0, w, h), radius=r, fill=bg_col)
    canvas.alpha_composite(track, (x, y))

    fill_w = max(0, int(w * max(0.0, min(1.0, pct))))
    if fill_w < 4:
        return

    # gradient fill pixel by pixel (fast enough for bar widths)
    bar = Image.new("RGBA", (fill_w, h), (0, 0, 0, 0))
    bd  = ImageDraw.Draw(bar)
    for px in range(fill_w):
        t = px / max(1, fill_w - 1)
        rc = int(col_left[0]*(1-t) + col_right[0]*t)
        gc = int(col_left[1]*(1-t) + col_right[1]*t)
        bc = int(col_left[2]*(1-t) + col_right[2]*t)
        bd.line([(px, 0), (px, h)], fill=(rc, gc, bc, 255))

    bar_masked = bar.copy()
    bar_masked.putalpha(_rounded_mask((fill_w, h), r))
    canvas.alpha_composite(bar_masked, (x, y))

    # bright highlight stripe
    if fill_w > 20:
        hi_w = fill_w // 3
        hi   = Image.new("RGBA", (hi_w, max(1, h//3)), (255,255,255, 55))
        hi.putalpha(_rounded_mask((hi_w, max(1,h//3)), max(1,h//6)))
        canvas.alpha_composite(hi, (x, y + 2))


def _draw_stat_box(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int, y: int, w: int, h: int,
    value: str, label: str, emoji: str,
    emoji_font, val_font, lbl_font,
) -> None:
    """Discord-style stat box with emoji, value, and label stacked cleanly."""
    panel = Image.new("RGBA", (w, h), (0,0,0,0))
    pd    = ImageDraw.Draw(panel)
    pd.rounded_rectangle((0, 0, w, h), radius=22, fill=_DISCORD_BOX_BG)
    canvas.alpha_composite(panel, (x,y))

    cx = x + w // 2

    # emoji — top, comfortably padded
    draw.text((cx, y + 34), emoji, font=emoji_font, fill=_TEXT_WHITE, anchor="ma")

    # value — large, centered in the visual middle
    draw.text((cx, y + h // 2 - 8), value, font=val_font, fill=_TEXT_WHITE, anchor="mm")

    # label — smaller and dimmer near the bottom
    draw.text((cx, y + h - 44), label, font=lbl_font, fill=(170, 174, 180), anchor="ms")


def _draw_info_row(
    draw: ImageDraw.ImageDraw,
    x: int, y: int,
    label: str, value: str,
    lbl_font, val_font,
) -> None:
    draw.text((x, y), "▪", font=lbl_font, fill=(*_ACCENT[:3], 140))
    bb = draw.textbbox((0,0), "▪ ", font=lbl_font)
    ox = bb[2]-bb[0]
    draw.text((x+ox, y), label, font=lbl_font, fill=_TEXT_DIM)
    lb = draw.textbbox((0,0), label, font=lbl_font)
    lw = lb[2]-lb[0]
    draw.text((x+ox+lw+16, y), value, font=val_font, fill=_TEXT_SUB)


def _badge_lines_from_text(badges_text: str) -> list[str]:
    text = str(badges_text or "").strip()
    if not text or text == "No badges":
        return ["• No badges yet"]
    parts = [part.strip() for part in text.split(",") if part.strip()]
    lines = [f"• {part}" for part in parts[:4]]
    return lines or ["• No badges yet"]


def _profile_card_context(data: dict[str, Any], target: discord.abc.User) -> dict[str, Any]:
    target_id = str(target.id)
    players = data.get("players", {})
    player = players.get(target_id, {}) if isinstance(players, dict) else {}
    user_data = player.get("user", {}) if isinstance(player, dict) else {}
    if not isinstance(user_data, dict):
        user_data = {}

    ranked_stats = player.get("ranked_stats", {}) if isinstance(player, dict) else {}
    wins = int(ranked_stats.get("wins", 0)) if isinstance(ranked_stats, dict) else 0
    losses = int(ranked_stats.get("losses", 0)) if isinstance(ranked_stats, dict) else 0
    battles_played = wins + losses
    league_name = str(user_data.get("rank", "Copper") or "Copper")
    profile_data = user_data.get("profile", {}) if isinstance(user_data.get("profile"), dict) else {}

    return {
        "target_id": target_id,
        "display_name": _display_name(target),
        "join_date": _join_date(user_data),
        "gang_name": _gang_name(data, player),
        "war_pts": _war_points(player, user_data),
        "achievements": _achievements_count(user_data),
        "cards_unlocked": _cards_unlocked_count(user_data),
        "badges_text": _profile_badges_text(data, player, user_data),
        "trophies": int(user_data.get("trophies", 0)),
        "league_name": league_name,
        "league_token": _league_rank_emoji(data, league_name),
        "global_rank": next((i for i, (uid, _) in enumerate(_rank_rows(data), 1) if uid == target_id), 0),
        "wins": wins,
        "losses": losses,
        "win_streak": int(ranked_stats.get("streak", 0)) if isinstance(ranked_stats, dict) else 0,
        "battles_played": battles_played,
        "win_rate": (wins / battles_played * 100.0) if battles_played > 0 else 0.0,
        "xp": _xp_progress_pct(user_data),
        "bio_text": _sanitize_bio(str(profile_data.get("bio", "") or "")),
        "featured": _featured_card_block(data, user_data),
        "avatar_url": getattr(getattr(target, "display_avatar", None), "url", None),
    }


# ── Main renderer ─────────────────────────────────────────────────────────────

async def render_profile_card(data: dict[str,Any], target: discord.abc.User) -> discord.File:
    ctx = _profile_card_context(data, target)
    target_id = ctx["target_id"]
    display_name = ctx["display_name"]
    join_date = ctx["join_date"]
    gang_name = ctx["gang_name"]
    war_pts = ctx["war_pts"]
    achievements = ctx["achievements"]
    cards_unlocked = ctx["cards_unlocked"]
    badges_text = ctx["badges_text"]
    trophies = ctx["trophies"]
    league_name = ctx["league_name"]
    league_token = ctx["league_token"]
    global_rank = ctx["global_rank"]
    wins = ctx["wins"]
    losses = ctx["losses"]
    win_streak = ctx["win_streak"]
    battles_played = ctx["battles_played"]
    win_rate = ctx["win_rate"]
    level, xp_cur, xp_needed, xp_pct = ctx["xp"]
    bio_text = ctx["bio_text"]
    featured_name, featured_image_url = ctx["featured"]
    avatar_url = ctx["avatar_url"]

    # ── Canvas ────────────────────────────────────────────────────────────────
    W, H = 3200, 1800
    canvas = Image.new("RGBA", (W, H), _BG)
    draw   = ImageDraw.Draw(canvas)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    font_title  = _font(148, bold=True)
    font_body   = _font(72)
    font_body_b = _font(72, bold=True)
    font_small  = _font(56)
    font_stat_e = _emoji_font(74)
    font_stat_v = _font(104, bold=True)
    font_stat_k = _font(44)
    font_card   = _font(68)

    # ── Fetch all remote images ───────────────────────────────────────────────
    async with aiohttp.ClientSession() as session:
        featured_img = await _fetch_image(session, featured_image_url)
        avatar_img   = await _fetch_image(session, str(avatar_url)) if avatar_url else None
        league_img   = await _fetch_image(session, _emoji_cdn_url(league_token) or "")
        trophy_img   = await _fetch_image(session, _emoji_cdn_url("<:Trophy:1469971235453665345>") or "")

    # ── Layer 1: full-bleed featured card art as background ───────────────────
    if featured_img is not None:
        bg_art = _crop_cover(featured_img, (W, H))
        bg_art = bg_art.convert("RGBA")
        # paste art first
        canvas.alpha_composite(bg_art)
        # blue tint overlay — light enough to see the art clearly
        tint = Image.new("RGBA", (W, H), (0, 8, 30, 130))
        canvas.alpha_composite(tint)
    else:
        # fallback: dark navy gradient
        for y in range(H):
            t = y / (H-1)
            r = int(4*(1-t)  + 8*t)
            g = int(8*(1-t)  + 14*t)
            b = int(18*(1-t) + 28*t)
            draw.line([(0,y),(W,y)], fill=(r,g,b,255))

    # ── Layer 2: left vignette — only dims the left panel area for readability ─
    vignette = Image.new("RGBA", (W, H), (0,0,0,0))
    vd = ImageDraw.Draw(vignette)
    for x in range(W):
        t = max(0.0, 1.0 - x / (W * 0.55))
        alpha = int(t ** 1.2 * 200)
        vd.line([(x,0),(x,H)], fill=(2, 6, 20, alpha))
    canvas.alpha_composite(vignette)

    # ── Layer 3: left glass panel ─────────────────────────────────────────────
    PAD    = 60
    PNL_X1 = PAD
    PNL_Y1 = PAD
    PNL_X2 = int(W * 0.50)
    PNL_Y2 = H - PAD

    _draw_glass_panel(canvas, PNL_X1, PNL_Y1, PNL_X2, PNL_Y2, radius=32)
    draw = ImageDraw.Draw(canvas)   # refresh after compositing

    # thin cyan accent line on left edge of panel
    accent_line = Image.new("RGBA", (4, PNL_Y2-PNL_Y1-20), (0,0,0,0))
    for i in range(accent_line.height):
        t = i / max(1, accent_line.height-1)
        alpha = int(255 * (1 - abs(t*2-1)**2))
        r = int(_XP_LEFT[0]*(1-t) + _XP_RIGHT[0]*t)
        g = int(_XP_LEFT[1]*(1-t) + _XP_RIGHT[1]*t)
        b = int(_XP_LEFT[2]*(1-t) + _XP_RIGHT[2]*t)
        for px in range(4):
            a = alpha if px < 2 else alpha // 3
            ImageDraw.Draw(accent_line).point((px,i), fill=(r,g,b,a))
    canvas.alpha_composite(accent_line, (PNL_X1, PNL_Y1+10))
    draw = ImageDraw.Draw(canvas)

    # ── Avatar ────────────────────────────────────────────────────────────────
    AV_SIZE   = 220
    AV_BORDER = 4
    AV_X      = PNL_X1 + 56
    AV_Y      = PNL_Y1 + 56

    # glow ring — cyan
    glow_r = AV_SIZE//2 + 28
    glow   = Image.new("RGBA", (glow_r*2, glow_r*2), (0,0,0,0))
    for ri in range(glow_r, 0, -1):
        alpha = int(90 * (1-(ri/glow_r))**1.4)
        ImageDraw.Draw(glow).ellipse(
            (glow_r-ri, glow_r-ri, glow_r+ri, glow_r+ri),
            outline=(0, 200, 255, alpha), width=1
        )
    canvas.alpha_composite(glow, (AV_X - glow_r + AV_SIZE//2, AV_Y - glow_r + AV_SIZE//2))
    draw = ImageDraw.Draw(canvas)

    if avatar_img is not None:
        av = _crop_cover(avatar_img, (AV_SIZE, AV_SIZE))
        av.putalpha(_circle_mask((AV_SIZE, AV_SIZE)))
        canvas.alpha_composite(av, (AV_X, AV_Y))
    else:
        draw.ellipse((AV_X, AV_Y, AV_X+AV_SIZE, AV_Y+AV_SIZE), fill=(30,30,44))

    draw.ellipse(
        (AV_X-AV_BORDER, AV_Y-AV_BORDER, AV_X+AV_SIZE+AV_BORDER, AV_Y+AV_SIZE+AV_BORDER),
        outline=(0, 210, 255, 220), width=AV_BORDER
    )
    draw = ImageDraw.Draw(canvas)

    # ── Username + league icon ────────────────────────────────────────────────
    NAME_X = AV_X + AV_SIZE + 36
    NAME_Y = AV_Y + (AV_SIZE - 148)//2
    draw.text((NAME_X, NAME_Y), display_name, font=font_title, fill=_TEXT_WHITE)
    nb = draw.textbbox((NAME_X, NAME_Y), display_name, font=font_title)

    if league_img is not None:
        li = league_img.resize((AV_SIZE, AV_SIZE), Image.Resampling.LANCZOS)
        canvas.alpha_composite(li, (nb[2]+20, AV_Y))
        draw = ImageDraw.Draw(canvas)

    # ── Thin rule ─────────────────────────────────────────────────────────────
    RULE_Y = AV_Y + AV_SIZE + 36
    draw.line((PNL_X1+40, RULE_Y, PNL_X2-40, RULE_Y), fill=(255,255,255,30), width=1)

    # ── XP bar ────────────────────────────────────────────────────────────────
    IX     = PNL_X1 + 56
    IY     = RULE_Y + 44
    IW     = PNL_X2 - PNL_X1 - 112

    # Level label
    draw.text((IX, IY), f"Lv. {level}", font=font_body_b, fill=_TEXT_GOLD)
    xp_label = f"{xp_cur:,}  /  {xp_needed:,} XP"
    xb = draw.textbbox((0,0), xp_label, font=font_small)
    draw.text((PNL_X2 - 40 - (xb[2]-xb[0]), IY+8), xp_label, font=font_small, fill=_TEXT_DIM)

    XP_BAR_Y = IY + 84
    XP_BAR_H = 20
    _draw_gradient_bar(canvas, IX, XP_BAR_Y, IW, XP_BAR_H, xp_pct,
                       _XP_LEFT, _XP_RIGHT, bg_col=(255,255,255,18))
    draw = ImageDraw.Draw(canvas)

    # ── Bio ───────────────────────────────────────────────────────────────────
    BIO_Y = XP_BAR_Y + XP_BAR_H + 36
    if bio_text:
        # accent left bar
        draw.rounded_rectangle((IX, BIO_Y, IX+3, BIO_Y+76), radius=2, fill=(*_ACCENT[:3], 160))
        draw.text((IX+20, BIO_Y+6), f'"{bio_text[:60]}"', font=font_small, fill=_TEXT_DIM)
        INFO_Y = BIO_Y + 96
    else:
        INFO_Y = BIO_Y

    # ── Thin rule ─────────────────────────────────────────────────────────────
    draw.line((PNL_X1+40, INFO_Y, PNL_X2-40, INFO_Y), fill=(255,255,255,20), width=1)
    INFO_Y += 36

    # ── Info rows ─────────────────────────────────────────────────────────────
    GAP = 82
    _draw_info_row(draw, IX, INFO_Y,           "Joined:",       join_date,          font_body, font_body_b)
    _draw_info_row(draw, IX, INFO_Y+GAP,       "Gang:",         gang_name,          font_body, font_body_b)
    _draw_info_row(draw, IX, INFO_Y+GAP*2,     "War Points:",   f"{war_pts:,}",     font_body, font_body_b)
    _draw_info_row(draw, IX, INFO_Y+GAP*3,     "Achievements:", f"{achievements}",  font_body, font_body_b)

    # ── Dedicated badges section ─────────────────────────────────────────────
    BADGE_DIVIDER_Y = INFO_Y + GAP*4 + 18
    draw.line((PNL_X1+40, BADGE_DIVIDER_Y, PNL_X2-40, BADGE_DIVIDER_Y), fill=(255,255,255,20), width=1)

    BADGE_TITLE_Y = BADGE_DIVIDER_Y + 24
    draw.text((IX, BADGE_TITLE_Y), "🏅 Badges", font=font_body_b, fill=_TEXT_WHITE)

    badge_lines = _badge_lines_from_text(badges_text)
    BADGE_LINES_Y = BADGE_TITLE_Y + 84
    BADGE_LINE_GAP = 72
    BADGE_MIN_LINES = 4
    for idx, line in enumerate(badge_lines[:BADGE_MIN_LINES]):
        draw.text((IX, BADGE_LINES_Y + idx * BADGE_LINE_GAP), line, font=font_small, fill=_TEXT_SUB)

    # keep reserved empty vertical room for future badges even when the list is short
    BADGE_BLOCK_BOTTOM = BADGE_LINES_Y + BADGE_LINE_GAP * BADGE_MIN_LINES + 8
    draw.line((PNL_X1+40, BADGE_BLOCK_BOTTOM, PNL_X2-40, BADGE_BLOCK_BOTTOM), fill=(255,255,255,20), width=1)

    # ── League + trophies row (bottom of panel) ──────────────────────────────
    LG_Y = BADGE_BLOCK_BOTTOM + 28
    LG_X = IX
    if league_img is not None:
        li_sm = league_img.resize((80, 80), Image.Resampling.LANCZOS)
        canvas.alpha_composite(li_sm, (LG_X, LG_Y))
        LG_X += 96
        draw = ImageDraw.Draw(canvas)
    draw.text((LG_X, LG_Y+6), league_name, font=font_body_b, fill=_TEXT_GOLD)
    LG_X += draw.textbbox((0,0), league_name+" ", font=font_body_b)[2]
    # trophies
    TR_TEXT = f"{trophies:,}"
    if trophy_img is not None:
        ti = trophy_img.resize((72, 72), Image.Resampling.LANCZOS)
        canvas.alpha_composite(ti, (LG_X, LG_Y + 4))
        draw = ImageDraw.Draw(canvas)
        LG_X += 80
    draw.text((LG_X, LG_Y+6), TR_TEXT, font=font_body_b, fill=_TEXT_SUB)

    # ── Right side: 2×3 stat boxes ────────────────────────────────────────────
    SB_X1    = int(W * 0.54)
    SB_Y1    = PAD + 60
    SB_W_TOT = W - PAD - SB_X1
    SB_H_TOT = H - PAD*2 - 120
    COLS, ROWS = 2, 3
    SB_GAP   = 28
    SB_W     = (SB_W_TOT - SB_GAP*(COLS-1)) // COLS
    SB_H     = (SB_H_TOT - SB_GAP*(ROWS-1)) // ROWS

    stat_boxes = [
        (f"{trophies:,}",                           "TROPHIES",    "🏆"),
        (f"#{global_rank if global_rank else '—'}", "GLOBAL RANK", "🌐"),
        (f"{win_rate:.1f}%",                        "WIN RATE",    "📈"),
        (f"{battles_played:,}",                     "BATTLES",     "⚔️"),
        (f"{win_streak}",                           "STREAK",      "🔥"),
        (f"{cards_unlocked}",                       "CARDS",       "🃏"),
    ]

    for i, (val, lbl, emoji) in enumerate(stat_boxes):
        col = i % COLS
        row = i // COLS
        bx  = SB_X1 + col*(SB_W+SB_GAP)
        by  = SB_Y1 + row*(SB_H+SB_GAP)
        _draw_stat_box(
            canvas, draw, bx, by, SB_W, SB_H,
            val, lbl, emoji,
            font_stat_e, font_stat_v, font_stat_k,
        )
        draw = ImageDraw.Draw(canvas)

    # (featured card name label removed)

    # ── Outer card border — cyan glow ─────────────────────────────────────────
    border_img = Image.new("RGBA", (W, H), (0,0,0,0))
    ImageDraw.Draw(border_img).rounded_rectangle(
        (0, 0, W, H), radius=40,
        outline=(0, 200, 255, 70), width=4
    )
    canvas.alpha_composite(border_img)

    # ── Encode ────────────────────────────────────────────────────────────────
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    out.seek(0)
    return discord.File(out, filename="profile_card.png")


# ── Embed fallback ────────────────────────────────────────────────────────────

def build_profile_embed(data: dict[str,Any], target: discord.abc.User) -> discord.Embed:
    from bot.utils.xp_logic import xp_progress

    target_id  = str(target.id)
    players    = data.get("players", {})
    player     = players.get(target_id, {}) if isinstance(players,dict) else {}
    user_data  = player.get("user", {}) if isinstance(player,dict) else {}
    if not isinstance(user_data, dict): user_data = {}

    display_name   = _display_name(target)
    join_date      = _join_date(user_data)
    level          = _player_level(user_data)
    gang_name      = _gang_name(data, player)
    badges_text    = _profile_badges_text(data, player, user_data)
    trophies       = int(user_data.get("trophies", 0))
    league_name    = str(user_data.get("rank","Copper") or "Copper")
    rows           = _rank_rows(data)
    global_rank    = next((i for i,(uid,_) in enumerate(rows,1) if uid==target_id), 0)
    ranked_stats   = player.get("ranked_stats", {}) if isinstance(player,dict) else {}
    wins           = int(ranked_stats.get("wins",0))   if isinstance(ranked_stats,dict) else 0
    losses         = int(ranked_stats.get("losses",0)) if isinstance(ranked_stats,dict) else 0
    win_streak     = int(ranked_stats.get("streak",0)) if isinstance(ranked_stats,dict) else 0
    battles_played = wins + losses
    win_rate       = (wins/battles_played*100.0) if battles_played>0 else 0.0
    league_emoji   = _league_rank_emoji(data, league_name)
    war_pts        = _war_points(player, user_data)
    achievements   = _achievements_count(user_data)
    cards_unlocked = _cards_unlocked_count(user_data)
    profile_data   = user_data.get("profile",{}) if isinstance(user_data.get("profile"),dict) else {}
    bio_text       = _sanitize_bio(str(profile_data.get("bio","") or ""))

    # Login streak
    streak = int(user_data.get("login_streak", 0))
    streak_text = f"🔥 {streak} day streak" if streak > 1 else "No active streak"

    # Level progress bar
    xp = int(user_data.get("xp", 0))
    xp_level, xp_cur, xp_needed = xp_progress(xp)
    progress_pct = min(100, int((xp_cur / max(1, xp_needed)) * 100))
    bar_filled = int(progress_pct / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)
    xp_text = f"Lv.{xp_level} [{bar}] {progress_pct}%"

    # Badges list
    badges = user_data.get("badges", [])
    badges_text_list = " • ".join(str(b) for b in badges) if badges else "No badges yet"

    # Tutorial progress
    tutorial = user_data.get("tutorial", {}) if isinstance(user_data.get("tutorial"), dict) else {}
    tutorial_step = int(tutorial.get("step", 0))

    desc = (
        f"**{display_name}**\n\n"
        f"Joined: {join_date}  •  Lv. {level}\n"
        f"Gang: {gang_name}\n"
        f"Login Streak: {streak_text}\n"
        f"Tutorial Progress: Step {tutorial_step}\n\n"
        f"{badges_text}\n\n"
        f"{league_emoji} {league_name} • {trophies:,} trophies\n"
        f"Global Rank: #{global_rank if global_rank else '—'}\n"
        f"Win Rate: {win_rate:.1f}%  •  Battles: {battles_played:,}  •  Streak: {win_streak}\n"
        f"War Points: {war_pts:,}  •  Achievements: {achievements}  •  Cards: {cards_unlocked}\n\n"
        f"Level Progress: {xp_text}\n"
        f"Badges: {badges_text_list}"
    )
    if bio_text:
        desc = f'*"{bio_text}"*\n\n' + desc

    embed = simple_embed(desc, footer="Player Profile")
    av    = getattr(target,"display_avatar",None)
    av_url = getattr(av,"url",None) if av is not None else None
    if av_url:
        embed.set_thumbnail(url=av_url)
    return embed


def build_featured_card_embed(data: dict[str,Any], target: discord.abc.User) -> discord.Embed:
    target_id  = str(target.id)
    players    = data.get("players",{})
    player     = players.get(target_id,{}) if isinstance(players,dict) else {}
    user_data  = player.get("user",{}) if isinstance(player,dict) else {}
    if not isinstance(user_data,dict): user_data={}
    featured_name, featured_image_url = _featured_card_block(data, user_data)
    if featured_image_url.startswith(("http://","https://")):
        return make_embed(None, featured_name or "No featured card", "", footer="Featured Card", image_url=featured_image_url)
    return make_embed(None, featured_name or "No featured card", "No featured card selected.", footer="Featured Card")

