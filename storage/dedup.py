"""Deduplicação de conteúdo por fingerprint.

Complementa a deduplicação por URL já existente: dois artigos com URLs
diferentes mas conteúdo idêntico (ou quase) são detectados como duplicatas.

Estratégia: MD5 de texto normalizado (minúsculas, sem pontuação, primeiros
300 chars de título + resumo). Rápido e sem dependências extras.
"""

import re
import hashlib
import unicodedata


def normalizar(texto: str) -> str:
    """Remove acentos, pontuação e espaços extras; converte para minúsculas."""
    # NFD separa os caracteres base dos diacríticos
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = re.sub(r"[̀-ͯ]", "", texto)   # remove diacríticos
    texto = re.sub(r"[^\w\s]", " ", texto)            # pontuação → espaço
    return " ".join(texto.split())


def content_fingerprint(title: str, summary: str = "") -> str:
    """Retorna o MD5 do conteúdo normalizado (título + primeiros 300 chars).

    Dois artigos com o mesmo fingerprint têm conteúdo essencialmente idêntico,
    mesmo que venham de URLs diferentes.
    """
    texto = normalizar(f"{title} {summary[:300]}")
    return hashlib.md5(texto.encode()).hexdigest()
