"""Internal AI client for EdgeRef.

This module intentionally returns generic user-facing errors and never logs or
returns API keys, provider details, base URLs, or model names.
"""

from typing import Optional


_INTERNAL_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-v4-flash"


def generate_ai_review(
    prompt: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Generate a pre-submission peer review report through backend AI config.

    Args:
        prompt: Review prompt text.
        model: Backend model name resolved outside this function.
        api_key: Backend API key resolved outside this function.

    Returns:
        dict: {"status": "success", "text": "..."} or
        {"status": "error", "error": "..."}
    """
    if not api_key:
        return {
            "status": "error",
            "error": "AI review service is not configured. Please contact the administrator.",
        }

    if not prompt or not prompt.strip():
        return {
            "status": "error",
            "error": "AI review cannot start because the review prompt is empty.",
        }

    resolved_model = model or _DEFAULT_MODEL

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=_INTERNAL_BASE_URL)
        response = client.chat.completions.create(
            model=resolved_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a rigorous academic pre-submission review expert. "
                        "Output only the final review report. Do not output hidden reasoning."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            extra_body={
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
            },
        )
        text = response.choices[0].message.content or ""
        if not text.strip():
            return {
                "status": "error",
                "error": "AI review returned empty content. Please try again.",
            }
        return {"status": "success", "text": text}
    except Exception:
        return {
            "status": "error",
            "error": "AI review failed. Please try again later or contact the administrator.",
        }
