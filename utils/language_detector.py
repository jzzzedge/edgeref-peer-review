# -*- coding: utf-8 -*-
"""Language detection module for manuscript review output."""

import re
from typing import Dict


def detect_manuscript_language(text: str) -> Dict[str, object]:
    """Detect manuscript language and choose review output language.

    The detector is intentionally lightweight and offline. It compares Chinese
    characters and English letters/words in the extracted manuscript text.
    """
    if not text or not text.strip():
        return {
            "language": "Unknown",
            "chinese_ratio": 0.0,
            "english_ratio": 0.0,
            "output_language": "English",
        }

    clean = text.strip()
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", clean))
    english_letters = len(re.findall(r"[A-Za-z]", clean))
    english_words = len(re.findall(r"[A-Za-z]+", clean))
    language_units = chinese_chars + english_letters

    if language_units == 0 or len(clean) < 50:
        language = "Unknown"
        output_language = "English"
        chinese_ratio = 0.0
        english_ratio = 0.0
    else:
        chinese_ratio = chinese_chars / language_units
        english_ratio = english_letters / language_units

        # Clear single-language cases.
        if chinese_ratio >= 0.70:
            language = "Chinese"
            output_language = "Chinese"
        elif english_ratio >= 0.70 and english_words >= 20:
            language = "English"
            output_language = "English"
        else:
            language = "Mixed"
            output_language = "Chinese" if chinese_chars >= english_letters else "English"

    return {
        "language": language,
        "chinese_ratio": round(chinese_ratio, 4),
        "english_ratio": round(english_ratio, 4),
        "output_language": output_language,
    }
