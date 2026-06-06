import base64
import io
import json
import logging
import random
import re
import urllib.parse
from typing import List, Optional, Tuple

import aiohttp
import discord

from config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_FLUX_MODEL,
    CLOUDFLARE_FLUX2_DEV_IMG2IMG_MODEL,
    CLOUDFLARE_SD15_IMG2IMG_MODEL,
    OLLAMA_MODEL,
    QWEN_FALLBACK_MODEL,
    VISION_MODEL,
)

logger = logging.getLogger("misskim")

IMAGE_TRIGGER_PREFIXES = [
    "create image",
    "generate image",
    "make image",
    "draw image",
    "imagine",
    "make a photo",
    "create a photo",
]

CHAT_IMAGE_TRIGGERS = {
    "@pollo": "pollinations",
    "@imagine": "cloudflare",
}


def _normalize_text(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[^\w\s']", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def maybe_image_trigger_prompt(text: str) -> Optional[str]:
    normalized = _normalize_text(text)
    for prefix in IMAGE_TRIGGER_PREFIXES:
        p = _normalize_text(prefix)
        if normalized == p:
            return "Create a high-quality artistic image."
        if normalized.startswith(p + " "):
            prompt = text.strip()[len(prefix):].strip(" :-")
            return prompt or "Create a high-quality artistic image."
    return None


def detect_chat_image_trigger(content: str) -> Optional[Tuple[str, str]]:
    stripped = content.strip()
    for trigger, backend in CHAT_IMAGE_TRIGGERS.items():
        if stripped.lower().startswith(trigger):
            prompt = stripped[len(trigger):].strip(" :-")
            return backend, prompt or "a beautiful artistic image"
    return None


def _cf_endpoint(model: str) -> str:
    return (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model}"
    )


def _extract_cf_image_b64(payload: dict) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("result"), dict):
        image = payload["result"].get("image")
        if isinstance(image, str):
            return image
    image = payload.get("image")
    if isinstance(image, str):
        return image
    return None


async def _cf_post_json(model: str, body: dict) -> Optional[bytes]:
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=80)
        ) as session:
            async with session.post(
                _cf_endpoint(model), json=body, headers=headers
            ) as resp:
                resp_text = await resp.text()
                if resp.status != 200:
                    logger.error(
                        "Cloudflare image API failed | model=%s status=%s body=%s",
                        model, resp.status, resp_text[:500],
                    )
                    return None
                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError:
                    logger.error(
                        "Cloudflare image API non-JSON | model=%s body=%s",
                        model, resp_text[:500],
                    )
                    return None
                b64 = _extract_cf_image_b64(data)
                if not b64:
                    logger.error(
                        "Cloudflare image API missing image field | model=%s body=%s",
                        model, resp_text[:500],
                    )
                    return None
                return base64.b64decode(b64)
    except Exception:
        logger.exception("Cloudflare JSON image request crashed | model=%s", model)
        return None


async def _cf_post_multipart_flux2(
    prompt: str, image_bytes: bytes
) -> Optional[bytes]:
    headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}
    form = aiohttp.FormData()
    form.add_field("prompt", prompt)
    form.add_field("steps", "20")
    form.add_field("width", "1024")
    form.add_field("height", "1024")
    form.add_field(
        "image", image_bytes, filename="input.png", content_type="image/png"
    )
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120)
        ) as session:
            async with session.post(
                _cf_endpoint(CLOUDFLARE_FLUX2_DEV_IMG2IMG_MODEL),
                data=form,
                headers=headers,
            ) as resp:
                resp_text = await resp.text()
                if resp.status != 200:
                    logger.error(
                        "Cloudflare Flux2 img2img failed | status=%s body=%s",
                        resp.status, resp_text[:500],
                    )
                    return None
                try:
                    data = json.loads(resp_text)
                except json.JSONDecodeError:
                    logger.error(
                        "Cloudflare Flux2 img2img non-JSON | body=%s",
                        resp_text[:500],
                    )
                    return None
                b64 = _extract_cf_image_b64(data)
                if not b64:
                    logger.error(
                        "Cloudflare Flux2 img2img missing image field | body=%s",
                        resp_text[:500],
                    )
                    return None
                return base64.b64decode(b64)
    except Exception:
        logger.exception("Cloudflare Flux2 img2img request crashed")
        return None


async def generate_image_bytes(
    prompt: str, source_image_bytes: Optional[bytes] = None
) -> Optional[bytes]:
    if source_image_bytes:
        flux2 = await _cf_post_multipart_flux2(prompt, source_image_bytes)
        if flux2:
            return flux2
        sd15 = await _cf_post_json(
            CLOUDFLARE_SD15_IMG2IMG_MODEL,
            {
                "prompt": prompt,
                "image_b64": base64.b64encode(source_image_bytes).decode("utf-8"),
                "num_steps": 20,
                "strength": 0.8,
                "guidance": 7.5,
            },
        )
        if sd15:
            return sd15

    return await _cf_post_json(
        CLOUDFLARE_FLUX_MODEL,
        {
            "prompt": prompt,
            "steps": 4,
            "seed": random.randint(1, 99999999),
        },
    )


async def generate_free_image(
    prompt: str, width: int = 1024, height: int = 1024
) -> Optional[bytes]:
    cleaned_prompt = " ".join(prompt.strip().split()) or "a high quality photo"
    tuned_prompt = (
        f"Accurately depict exactly this request: {cleaned_prompt}. "
        "Keep subject, pose, clothing, colors, and scene details consistent with the request. "
        "Do not add unrelated people, objects, text, watermark, logo, extra limbs, or distortions. "
        "Photorealistic, sharp focus, natural lighting, high detail."
    )
    encoded_prompt = urllib.parse.quote(tuned_prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width={width}&height={height}"
        f"&seed={random.randint(100000, 9999999)}&safe=false&model=flux"
        f"&nologo=true&enhance=true"
    )
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=90)
        ) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
                body = await resp.text()
                logger.error(
                    "Pollinations failed | status=%s prompt=%s body=%s",
                    resp.status, prompt[:120], body[:500],
                )
                return None
    except Exception:
        logger.exception(
            "Pollinations image generation crashed | prompt=%s", prompt[:120]
        )
        return None


async def fetch_url_bytes(url: str) -> Optional[bytes]:
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(
                        "Failed to fetch attachment URL | status=%s url=%s",
                        resp.status, url,
                    )
                    return None
                return await resp.read()
    except Exception:
        logger.exception("Attachment download crashed | url=%s", url)
        return None


def _attachment_image_urls(msg: discord.Message) -> List[str]:
    return [
        att.url
        for att in msg.attachments
        if (att.content_type or "").lower().startswith("image/") and att.url
    ]


def gather_image_urls(message: discord.Message) -> List[str]:
    urls = _attachment_image_urls(message)
    if message.reference and message.reference.resolved:
        resolved = message.reference.resolved
        if isinstance(resolved, discord.Message):
            urls.extend(_attachment_image_urls(resolved))
    dedup: List[str] = []
    seen: set = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            dedup.append(u)
    return dedup[:4]


async def fetch_perchance_output(
    generator_name: str, list_name: str = "output"
) -> str:
    url = (
        f"https://perchance.org/api/downloadGenerator"
        f"?generatorName={generator_name}&listsOnly=true"
        f"&__cacheBust={random.random()}"
    )
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "Error: Unable to connect to Perchance servers right now."
                raw_text = await resp.text()
                pattern = (
                    rf"(?:^|\n){re.escape(list_name)}\s*\n"
                    rf"([\s\S]*?)(?=\n\w+\s*\n|$)"
                )
                match = re.search(pattern, raw_text)
                if not match:
                    return (
                        f"Error: Could not locate the list '{list_name}' "
                        "in that generator."
                    )
                lines = [
                    line.strip()
                    for line in match.group(1).split("\n")
                    if line.strip() and not line.strip().startswith("//")
                ]
                if not lines:
                    return "Error: The selected Perchance list is completely empty."
                return random.choice(lines)
    except Exception as exc:
        logger.exception(
            "Perchance extraction failed | generator=%s", generator_name
        )
        return f"An error occurred while connecting to Perchance: {exc}"


async def vision_chat_from_urls(
    user_text: str,
    image_urls: List[str],
    user_id: int,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    mood: str = "calm",
) -> str:
    if not image_urls:
        return ""

    from llm import ollama_client, groq_client
    from memory import add_memory_to_prompt
    from persona import build_system_prompt, detect_language, build_user_prompt_with_lore

    lang = detect_language(user_text or "", channel_id=(channel_id or 0))
    system = build_system_prompt(user_id, mood, lang) + " You can analyze images."
    prompt_text = (
        user_text.strip() or "Describe this image in detail and infer context."
    )

    mem_prompt = add_memory_to_prompt(
        user_id,
        build_user_prompt_with_lore(prompt_text),
        guild_id=guild_id,
        channel_id=channel_id,
    )

    image_b64: List[str] = []
    for u in image_urls[:4]:
        raw = await fetch_url_bytes(u)
        if raw:
            image_b64.append(base64.b64encode(raw).decode("utf-8"))

    if image_b64:
        ollama_reply = await ollama_client.chat_messages(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": mem_prompt, "images": image_b64},
            ],
            model_override=OLLAMA_MODEL,
        )
        if "I could not reach the AI backend right now" not in ollama_reply:
            return ollama_reply.strip()

        if QWEN_FALLBACK_MODEL:
            qwen_reply = await ollama_client.chat_messages(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": mem_prompt, "images": image_b64},
                ],
                model_override=QWEN_FALLBACK_MODEL,
            )
            if "I could not reach the AI backend right now" not in qwen_reply:
                return qwen_reply.strip()

    if not groq_client.keys:
        return "Vision is not available right now."

    user_content = [{"type": "text", "text": mem_prompt}]
    for u in image_urls:
        user_content.append({"type": "image_url", "image_url": {"url": u}})

    groq_reply = await groq_client.chat_messages(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        model_override=VISION_MODEL,
        temperature=0.6,
        max_tokens=700,
    )
    return groq_reply.strip()


async def vision_reply_for_message(
    message: discord.Message, mood: str = "calm"
) -> str:
    image_urls = gather_image_urls(message)
    if not image_urls:
        return ""
    return await vision_chat_from_urls(
        user_text=message.content,
        image_urls=image_urls,
        user_id=message.author.id,
        guild_id=(message.guild.id if message.guild else None),
        channel_id=message.channel.id,
        mood=mood,
    )


async def enhance_image_prompt(
    raw_prompt: str,
    image_url: Optional[str] = None,
    user_id: int = 0,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> str:
    from llm import chat_with_fallback
    from memory import add_memory_to_prompt
    from persona import build_user_prompt_with_lore

    if image_url:
        instruction = (
            "Analyze the attached reference image and the user's prompt. "
            "Rewrite into one detailed image generation prompt preserving "
            "the subject, pose, and style. "
            "Add lighting, mood, composition, and quality descriptors. "
            f"User prompt: {raw_prompt}"
        )
        enhanced = await vision_chat_from_urls(
            user_text=instruction,
            image_urls=[image_url],
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        return enhanced.strip() or raw_prompt

    system = (
        "You are an expert image generation prompt writer. "
        "Take the user's short description and expand it into one detailed, vivid prompt. "
        "Add: art style, lighting, mood, composition, color palette, quality tags. "
        "Output only the enhanced prompt, nothing else. Max 120 words."
    )
    mem_prompt = add_memory_to_prompt(
        user_id,
        build_user_prompt_with_lore(raw_prompt),
        guild_id=guild_id,
        channel_id=channel_id,
    )
    enhanced = await chat_with_fallback(system_prompt=system, user_prompt=mem_prompt)
    return enhanced.strip() or raw_prompt


async def improve_image_prompt(
    original_prompt: str,
    user_feedback: str,
    image_url: Optional[str] = None,
    user_id: int = 0,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> str:
    from llm import chat_with_fallback
    from memory import add_memory_to_prompt
    from persona import build_user_prompt_with_lore

    feedback_lower = user_feedback.lower().strip()
    is_generic = feedback_lower in {
        "improve", "better", "enhance", "make it better", "fix it", "redo"
    }

    if image_url and is_generic:
        instruction = (
            f"This image was generated from the prompt: '{original_prompt}'. "
            "Analyze what could be improved — composition, lighting, detail, style, clarity. "
            "Rewrite into a single improved image generation prompt. Output only the prompt."
        )
        improved = await vision_chat_from_urls(
            user_text=instruction,
            image_urls=[image_url],
            user_id=user_id,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        return improved.strip() or original_prompt

    system = (
        "You are an expert image generation prompt writer. "
        "Take the original prompt and user feedback, merge them into one improved prompt. "
        "Keep what worked, apply the requested changes precisely. "
        "Output only the final prompt, no explanation. Max 120 words."
    )
    user_msg = f"Original prompt: {original_prompt}\nUser feedback: {user_feedback}"
    mem_prompt = add_memory_to_prompt(
        user_id,
        build_user_prompt_with_lore(user_msg),
        guild_id=guild_id,
        channel_id=channel_id,
    )
    improved = await chat_with_fallback(system_prompt=system, user_prompt=mem_prompt)
    return improved.strip() or original_prompt


async def build_img2img_edit_prompt(
    user_prompt: str,
    image_url: Optional[str],
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    channel_id: Optional[int] = None,
) -> str:
    if not image_url:
        return user_prompt
    prompt_request = (
        "Analyze this image and rewrite the user's edit request into one precise "
        "prompt for image-to-image editing. "
        "Keep key subject identity and composition unless user asks to change them. "
        f"User request: {user_prompt}"
    )
    rewritten = await vision_chat_from_urls(
        user_text=prompt_request,
        image_urls=[image_url],
        user_id=(user_id or 0),
        guild_id=guild_id,
        channel_id=channel_id,
    )
    return rewritten.strip() or user_prompt
