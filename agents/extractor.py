"""
Extração de empresas em 3 camadas complementares:

  1. Gazetteer  — Aho-Corasick sobre lista de empresas conhecidas (O(n) no texto)
  2. Padrões    — regex para sufixos jurídicos e frases contextuais
  3. NER        — spaCy como fallback, com filtros de falsos positivos

A ordem importa: resultados das camadas 1 e 2 têm prioridade; a camada 3
só contribui com entidades ainda não encontradas.
"""

import re
import config

# ── cache de objetos pesados (inicializados uma única vez por processo) ────────
_automaton = None   # Aho-Corasick compilado do gazetteer
_nlp = None         # modelo spaCy carregado
_suffix_re = None   # regex compilado de sufixos jurídicos


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 1 — Gazetteer (Aho-Corasick)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_automaton():
    """Constrói o autômato Aho-Corasick na primeira chamada e reutiliza depois."""
    global _automaton
    if _automaton is not None:
        return _automaton

    try:
        import ahocorasick
    except ImportError:
        return None  # biblioteca opcional; camada 1 desativada se ausente

    A = ahocorasick.Automaton()
    for idx, name in enumerate(config.COMPANY_GAZETTEER):
        # chave em minúsculas para busca case-insensitive
        A.add_word(name.lower(), name)
    A.make_automaton()
    _automaton = A
    return _automaton


def _extract_gazetteer(text: str) -> list[str]:
    """Percorre o texto uma única vez buscando todas as empresas do gazetteer."""
    automaton = _get_automaton()
    if automaton is None:
        return []

    found = []
    text_lower = text.lower()
    for _end, name in automaton.iter(text_lower):
        found.append(name)
    return found


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 2 — Padrões (sufixos jurídicos + frases contextuais)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_suffix_re():
    """Compila o regex de sufixos jurídicos na primeira chamada."""
    global _suffix_re
    if _suffix_re is None:
        suffixes = "|".join(config.COMPANY_LEGAL_SUFFIXES)
        # captura: 1-5 palavras capitalizadas imediatamente antes do sufixo
        _suffix_re = re.compile(
            r'((?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç&]*\s+){0,4}'
            r'[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç&]*)'
            r'\s+(?:' + suffixes + r')',
        )
    return _suffix_re


def _extract_patterns(text: str) -> list[str]:
    """Extrai empresas via sufixos jurídicos e frases contextuais."""
    found = []

    # sufixos jurídicos: "Empresa Tal S.A.", "Fulano Ltda"
    for m in _get_suffix_re().finditer(text):
        found.append(m.group(1).strip())

    # frases contextuais: "presidente da X", "empresa X anunciou"
    for pattern in config.COMPANY_CONTEXT_PATTERNS:
        for m in re.finditer(pattern, text):
            candidate = m.group(1).strip().rstrip(".,;:")
            if candidate:
                found.append(candidate)

    return found


# ═══════════════════════════════════════════════════════════════════════════════
# CAMADA 3 — spaCy NER (fallback)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_nlp():
    """Carrega o modelo spaCy na primeira chamada."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load(config.SPACY_MODEL)
        except OSError:
            raise RuntimeError(
                f"Modelo spaCy '{config.SPACY_MODEL}' não encontrado. "
                "Execute setup.py para instalá-lo."
            )
    return _nlp


def _is_false_positive(name: str) -> bool:
    """Retorna True se o nome não deve ser considerado uma empresa."""
    # blocklist explícita (geográficos, siglas fiscais etc.)
    if name in config.COMPANY_BLOCKLIST:
        return True

    # siglas curtas em maiúsculas: aceitar só as da whitelist
    if name.isupper() and len(name) <= 4 and name not in config.COMPANY_ACRONYM_WHITELIST:
        return True

    # strings muito curtas dificilmente são nomes de empresas
    if len(name) < 3:
        return True

    return False


def _extract_ner(text: str) -> list[str]:
    """Usa spaCy para encontrar entidades ORG; aplica filtros de qualidade."""
    nlp = _get_nlp()
    doc = nlp(text[:10_000])  # trunca para evitar estouro de memória

    found = []
    for ent in doc.ents:
        # aceita apenas organizações — ignora PER (pessoas), GPE (locais) etc.
        if ent.label_ != "ORG":
            continue
        name = ent.text.strip()
        if not _is_false_positive(name):
            found.append(name)

    return found


# ═══════════════════════════════════════════════════════════════════════════════
# PONTO DE ENTRADA — pipeline unificado
# ═══════════════════════════════════════════════════════════════════════════════

_SUFFIX_STRIP_RE = re.compile(
    r'\s+(?:S\.A\.?|S/A|Ltda\.?|LTDA\.?|ME|EPP|EIRELI|'
    r'Holdings?|Participações|Empreendimentos|Investimentos|'
    r'Tecnologia|Soluções|Group|Grupo)\s*$',
    re.IGNORECASE,
)


def _normalize_key(name: str) -> str:
    """Chave de deduplicação: minúsculas, sem sufixos jurídicos.
    Garante que 'Petrobras' e 'Petrobras S.A.' sejam tratados como o mesmo item."""
    return _SUFFIX_STRIP_RE.sub("", name.strip()).lower()


def extract_companies(text: str) -> list[str]:
    """
    Executa as 3 camadas e devolve lista deduplicada de nomes de empresas.
    Camadas 1 e 2 têm prioridade; a camada 3 acrescenta apenas o que escapou.
    A deduplicação normaliza sufixos jurídicos para evitar duplicatas como
    'Petrobras' e 'Petrobras S.A.'.
    """
    seen = {}   # chave_normalizada → nome_original (preserva capitalização)

    def _add(name: str):
        key = _normalize_key(name)
        if key and key not in seen:
            seen[key] = name.strip()

    # camada 1: gazetteer (maior precisão)
    for name in _extract_gazetteer(text):
        _add(name)

    # camada 2: padrões de sufixos e contexto
    for name in _extract_patterns(text):
        _add(name)

    # camada 3: NER como fallback para entidades fora do gazetteer
    for name in _extract_ner(text):
        _add(name)

    return list(seen.values())
