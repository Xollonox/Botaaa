import json
import logging
from typing import List, Optional

import aiohttp

from config import (
    CEREBRAS_BASE_URL,
    CEREBRAS_MODEL,
    CEREBRAS_API_KEY,
    CEREBRAS_API_KEY_2,
    GROQ_BASE_URL,
    GROQ_MODEL,
    GROQ_API_KEY,
    GROQ_API_KEY_2,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_API_KEY,
    OLLAMA_API_KEY_2,
    OLLAMA_API_KEY_3,
    OLLAMA_API_KEY_4,
    OLLAMA_API_KEY_5,
    QWEN_FALLBACK_MODEL,
    SEARCH_MODEL,
)

logger = logging.getLogger("misskim")


class OpenAICompatClient:
    def __init__(self, base_url: str, model: str, keys: List[str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.keys = [k for k in keys if k]
        self._idx = 0

    def _ordered_keys(self) -> List[str]:
        if not self.keys:
            return []
        if len(self.keys) == 1:
            return self.keys
        return [self.keys[self._idx], self.keys[(self._idx + 1) % len(self.keys)]]

    def _rotate(self) -> None:
        if self.keys:
            self._idx = (self._idx + 1) % len(self.keys)

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model_override: Optional[str] = None,
    ) -> str:
        return await self.chat_messages(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model_override=model_override,
        )

    async def chat_messages(
        self,
        messages: List[dict],
        model_override: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 400,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": (model_override or self.model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        last_error = "No API key configured"
        for key in self._ordered_keys():
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=35)
                ) as session:
                    async with session.post(
                        url, json=payload, headers=headers
                    ) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            result = _parse_openai_response(text, resp.headers)
                            if result is not None:
                                return result
                        elif resp.status in (429, 401, 403):
                            last_error = f"Key rejected ({resp.status})"
                            logger.warning(
                                "OpenAI-compat API key issue | base_url=%s status=%s",
                                self.base_url,
                                resp.status,
                            )
                            self._rotate()
                            continue
                        else:
                            last_error = f"API error {resp.status}: {text[:200]}"
                            logger.error(
                                "OpenAI-compat API error | base_url=%s model=%s status=%s body=%s",
                                self.base_url,
                                payload.get("model"),
                                resp.status,
                                text[:500],
                            )
            except Exception as exc:
                last_error = f"Network error: {exc}"
                logger.exception(
                    "OpenAI-compat API call crashed | base_url=%s model=%s",
                    self.base_url,
                    payload.get("model"),
                )

        return f"I could not reach the AI backend right now ({last_error})."


def _parse_openai_response(text: str, headers) -> Optional[str]:
    content_type = headers.get("Content-Type", "").lower()
    if "text/event-stream" in content_type or text.strip().startswith("data:"):
        return _parse_sse(text)
    try:
        data = json.loads(text)
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return "I generated an empty response. Ask again."


def _parse_sse(text: str) -> str:
    parts: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            continue
        try:
            chunk = json.loads(data_str)
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content") or choices[0].get("message", {}).get(
                    "content", ""
                )
                if content:
                    parts.append(content)
        except Exception:
            pass
    return "".join(parts).strip()


class OllamaClient:
    def __init__(self, base_url: str, keys: List[str], model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.keys = [k for k in keys if k]
        self.model = model
        self._idx = 0

    def _next_key(self) -> Optional[str]:
        if not self.keys:
            return None
        key = self.keys[self._idx]
        self._idx = (self._idx + 1) % len(self.keys)
        return key

    def _url(self) -> str:
        return f"{self.base_url}/chat"

    def _headers(self, key: Optional[str] = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model_override: Optional[str] = None,
    ) -> str:
        return await self.chat_messages(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model_override=model_override,
        )

    async def chat_messages(
        self,
        messages: List[dict],
        model_override: Optional[str] = None,
    ) -> str:
        payload = {
            "model": (model_override or self.model),
            "messages": messages,
            "stream": False,
        }
        attempts = max(1, len(self.keys))
        last_error = "No API key configured"
        for _ in range(attempts):
            key = self._next_key()
            try:
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as session:
                    async with session.post(
                        self._url(), json=payload, headers=self._headers(key)
                    ) as resp:
                        text = await resp.text()
                        if resp.status == 200:
                            data = await resp.json()
                            message = data.get("message", {})
                            content = message.get("content", "")
                            if isinstance(content, str) and content.strip():
                                return content.strip()
                            return "I generated an empty response. Ask again."
                        if resp.status == 429:
                            last_error = f"Key rate-limited ({resp.status})"
                            logger.warning(
                                "Ollama API rate-limited | key_index=%s status=%s",
                                self._idx,
                                resp.status,
                            )
                            continue
                        last_error = f"Ollama {resp.status}: {text[:200]}"
                        logger.error(
                            "Ollama API error | url=%s model=%s status=%s body=%s",
                            self._url(),
                            payload.get("model"),
                            resp.status,
                            text[:500],
                        )
            except Exception as exc:
                last_error = f"Ollama error: {exc}"
                logger.exception(
                    "Ollama API call crashed | url=%s model=%s",
                    self._url(),
                    payload.get("model"),
                )
        return f"I could not reach the AI backend right now ({last_error})"


ollama_client = OllamaClient(
    base_url=OLLAMA_BASE_URL,
    keys=[
        OLLAMA_API_KEY,
        OLLAMA_API_KEY_2,
        OLLAMA_API_KEY_3,
        OLLAMA_API_KEY_4,
        OLLAMA_API_KEY_5,
    ],
    model=OLLAMA_MODEL,
)

cerebras_client = OpenAICompatClient(
    base_url=CEREBRAS_BASE_URL,
    model=CEREBRAS_MODEL,
    keys=[CEREBRAS_API_KEY, CEREBRAS_API_KEY_2],
)

groq_client = OpenAICompatClient(
    base_url=GROQ_BASE_URL,
    model=GROQ_MODEL,
    keys=[GROQ_API_KEY, GROQ_API_KEY_2],
)


def _search_model_name() -> str:
    if "/" in SEARCH_MODEL:
        return SEARCH_MODEL.split("/", 1)[1].strip() or SEARCH_MODEL.strip()
    return SEARCH_MODEL.strip()


async def chat_with_fallback(
    system_prompt: str,
    user_prompt: str,
    prefer_search: bool = False,
) -> str:
    ollama_reply = await ollama_client.chat(
        system_prompt=system_prompt, user_prompt=user_prompt
    )
    if "I could not reach the AI backend right now" not in ollama_reply:
        return ollama_reply

    if QWEN_FALLBACK_MODEL:
        qwen_reply = await ollama_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_override=QWEN_FALLBACK_MODEL,
        )
        if "I could not reach the AI backend right now" not in qwen_reply:
            return qwen_reply

    cerebras_reply = await cerebras_client.chat(
        system_prompt=system_prompt, user_prompt=user_prompt
    )
    if "I could not reach the AI backend right now" not in cerebras_reply:
        return cerebras_reply

    if prefer_search and groq_client.keys and SEARCH_MODEL:
        search_reply = await groq_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_override=_search_model_name(),
        )
        if "I could not reach the AI backend right now" not in search_reply:
            return search_reply

    if groq_client.keys:
        return await groq_client.chat(
            system_prompt=system_prompt, user_prompt=user_prompt
        )

    return ollama_reply
