"""Classifies news articles into themes using keyword matching."""
import re
import config


def classify(text: str) -> list[str]:
    text_lower = text.lower()
    matched = []
    for theme, keywords in config.THEMES.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                matched.append(theme)
                break
    return matched or ["geral"]
