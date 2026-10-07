from __future__ import annotations

import os
from typing import Mapping, Optional

from learning_app.ai.base import AIProvider


def create_ai_provider(
    provider_name: Optional[str] = None,
    secrets: Optional[Mapping[str, str]] = None,
) -> AIProvider:
    values = secrets or {}
    name = (provider_name or values.get("AI_PROVIDER") or os.getenv("AI_PROVIDER") or "xai")
    name = str(name).strip().lower()

    if name == "xai":
        from learning_app.ai.xai_provider import XAIProvider

        key = str(values.get("XAI_API_KEY") or os.getenv("XAI_API_KEY") or "")
        model = str(values.get("XAI_MODEL") or os.getenv("XAI_MODEL") or "grok-4.7")
        return XAIProvider(api_key=key, model=model)

    if name == "gemini":
        from learning_app.ai.gemini_provider import GeminiProvider

        key = str(values.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or "")
        model = str(
            values.get("GEMINI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-pro"
        )
        return GeminiProvider(api_key=key, model=model)

    raise ValueError(f"Неизвестный AI_PROVIDER: {name}")
