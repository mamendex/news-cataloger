"""Scrapers HTML para sites sem feed RSS.

Cada scraper retorna uma lista de Article (mesmo dataclass do reader.py),
garantindo compatibilidade total com o pipeline do coordinator.

Deduplicação: tratada pelo banco via url UNIQUE — o scraper não precisa
saber o que já foi coletado, apenas retornar URLs absolutas e consistentes.

Scrapers disponíveis (identificados pela coluna `scraper` da tabela feeds):
  bndes_agencia  — https://agenciadenoticias.bndes.gov.br/
  bndes_blog     — https://blogdodesenvolvimento.bndes.gov.br/
"""

import re
from datetime import datetime, timedelta
from agents.reader import Article

# mês por extenso em português → número
_MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _get_soup(url: str):
    """Faz o request e retorna um BeautifulSoup. Lança RuntimeError se falhar."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("requests e beautifulsoup4 são necessários. Execute: pip install requests beautifulsoup4")

    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0 news-cataloger/1.0"})
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _parse_data_extenso(texto: str) -> str:
    """Converte 'DD de mês, YYYY' para 'YYYY-MM-DD'. Retorna '' se não parsear."""
    m = re.search(r'(\d{1,2})\s+de\s+(\w+),?\s+(\d{4})', texto, re.IGNORECASE)
    if not m:
        return ""
    dia, mes_str, ano = m.group(1), m.group(2).lower(), m.group(3)
    mes = _MESES.get(mes_str)
    if not mes:
        return ""
    return f"{ano}-{mes:02d}-{int(dia):02d}"


def _parse_data_relativa(texto: str) -> str:
    """Converte 'há X horas/dias/semanas' para 'YYYY-MM-DD' aproximado."""
    agora = datetime.now()
    m = re.search(r'há\s+(\d+)\s+(hora|horas|dia|dias|semana|semanas)', texto, re.IGNORECASE)
    if not m:
        return agora.strftime("%Y-%m-%d")
    n, unidade = int(m.group(1)), m.group(2).lower()
    if "hora" in unidade:
        dt = agora - timedelta(hours=n)
    elif "dia" in unidade:
        dt = agora - timedelta(days=n)
    elif "semana" in unidade:
        dt = agora - timedelta(weeks=n)
    else:
        dt = agora
    return dt.strftime("%Y-%m-%d")


# ── Scraper 1: Agência BNDES de Notícias ─────────────────────────────────────

BASE_AGENCIA = "https://agenciadenoticias.bndes.gov.br"


def scrape_bndes_agencia() -> list[Article]:
    """Extrai notícias de agenciadenoticias.bndes.gov.br.

    Estrutura confirmada via inspeção do HTML real:
      <a class="card [card-main]" href="/categoria/slug/">
        <div class="card--content">
          <span class="card--tag">Categoria</span>
          <span class="card--date">há X horas</span>
          <h3 class="card--title">Título da notícia</h3>
        </div>
      </a>
    """
    soup = _get_soup(BASE_AGENCIA)
    articles = []
    seen_urls = set()

    for card in soup.find_all("a", class_="card"):
        href = card.get("href", "").strip()
        if not href or not href.startswith("/"):
            continue

        url = BASE_AGENCIA + href
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # título: <h3 class="card--title"> ou qualquer h3 dentro do card
        h3 = card.find(class_="card--title") or card.find("h3")
        titulo = h3.get_text(strip=True) if h3 else ""
        if not titulo:
            continue

        # data: <span class="card--date"> com "há X horas/dias"
        date_span = card.find(class_="card--date")
        data = _parse_data_relativa(date_span.get_text(strip=True) if date_span else "")

        articles.append(Article(
            title=titulo,
            url=url,
            summary="",
            published_at=data,
            source="Agência BNDES de Notícias",
        ))

    return articles


# ── Scraper 2: Blog do Desenvolvimento BNDES ─────────────────────────────────

BASE_BLOG = "https://blogdodesenvolvimento.bndes.gov.br"


def scrape_bndes_blog() -> list[Article]:
    """Extrai posts de blogdodesenvolvimento.bndes.gov.br.

    Estrutura confirmada via inspeção do HTML real:
      <div class="nav--menu--submenu--latest">
        <div class="label"><span>Post|Entrevista|...</span></div>
        <a href="/categoria/cat/slug/"><h3>Título</h3></a>
        <a href="/categoria/cat/slug/"><p>Resumo...</p></a>
      </div>
    """
    soup = _get_soup(BASE_BLOG)
    articles = []
    seen_urls = set()

    for container in soup.find_all(class_="nav--menu--submenu--latest"):
        # link com h3 = título
        a_titulo = container.find("a", href=True)
        if not a_titulo:
            continue
        href = a_titulo["href"].strip()
        if not href.startswith("/categoria/") and not href.startswith("/serie/"):
            continue
        if href.count("/") < 3:  # filtra links de categoria sem slug
            continue

        url = BASE_BLOG + href if href.startswith("/") else href
        if url in seen_urls:
            continue
        seen_urls.add(url)

        h3 = a_titulo.find(["h3", "h4"])
        titulo = h3.get_text(strip=True) if h3 else a_titulo.get_text(strip=True)
        if not titulo:
            continue

        # resumo: segundo <a> do container que contém <p>
        resumo = ""
        for a in container.find_all("a", href=True):
            p = a.find("p")
            if p:
                resumo = p.get_text(strip=True)
                break

        # data: <time> se existir (o blog nem sempre exibe data no card)
        time_tag = container.find("time")
        data = _parse_data_extenso(time_tag.get_text(strip=True)) if time_tag else ""

        articles.append(Article(
            title=titulo,
            url=url,
            summary=resumo,
            published_at=data,
            source="Blog do Desenvolvimento BNDES",
        ))

    return articles


# ── dispatcher ────────────────────────────────────────────────────────────────

_SCRAPERS = {
    "bndes_agencia": scrape_bndes_agencia,
    "bndes_blog":    scrape_bndes_blog,
}


def scrape(scraper_id: str) -> list[Article]:
    """Executa o scraper identificado por `scraper_id`.
    Lança ValueError se o id não for reconhecido."""
    if scraper_id not in _SCRAPERS:
        raise ValueError(f"Scraper desconhecido: '{scraper_id}'. Disponíveis: {list(_SCRAPERS)}")
    return _SCRAPERS[scraper_id]()


def scrapers_disponiveis() -> list[str]:
    return list(_SCRAPERS.keys())
