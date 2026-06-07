"""
Benchmark: deduplicação e descoberta de temas em escala.

Compara:
  A) Dedup por URL apenas  vs  B) Dedup por URL + content_hash
  A) Descoberta Python     vs  B) Descoberta SQL (FTS5)

Uso:
    python benchmark.py              # 1.000 artigos
    python benchmark.py --n 5000     # 5.000 artigos
    python benchmark.py --n 10000    # 10.000 artigos
"""

import os
import sys
import time
import random
import sqlite3
import tempfile
import hashlib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

# ── gerador de artigos sintéticos ────────────────────────────────────────────

EMPRESAS = [
    "Petrobras", "Vale", "Embraer", "Ambev", "Itaú", "Bradesco",
    "Nubank", "Magazine Luiza", "Natura", "Gerdau", "Suzano", "JBS",
    "Totvs", "Localiza", "Weg", "BTG Pactual", "Banco do Brasil",
]

TEMAS_SEED = {
    "infraestrutura": ["rodovia", "ferrovia", "porto", "aeroporto", "obra",
                       "concessão", "licitação", "contrato"],
    "tributario":     ["imposto", "tributo", "receita", "fiscal", "alíquota",
                       "declaração", "sonegação", "arrecadação"],
    "esportes":       ["futebol", "campeonato", "gol", "clube", "atleta",
                       "olimpíadas", "copa", "seleção"],
    "defesa":         ["exército", "marinha", "aeronáutica", "armamento",
                       "segurança", "fronteira", "militar", "defesa"],
}

FONTES = ["Folha de S.Paulo", "Valor Econômico", "Exame", "InfoMoney",
          "G1", "UOL Economia", "Agência Brasil", "Reuters Brasil"]

VERBOS = ["anuncia", "registra", "divulga", "reporta", "apresenta",
          "confirma", "revela", "informa"]


def _artigo(idx: int, tema: str | None = None) -> dict:
    """Gera um artigo sintético com conteúdo variado."""
    empresa  = random.choice(EMPRESAS)
    verbo    = random.choice(VERBOS)
    if tema and tema in TEMAS_SEED:
        kw = random.choice(TEMAS_SEED[tema])
        title   = f"{empresa} {verbo} dados sobre {kw} no trimestre {idx}"
        summary = (f"A {empresa} {verbo} novidades relacionadas a {kw}. "
                   f"Resultado do período {idx} supera expectativas do mercado.")
    else:
        title   = f"{empresa} {verbo} resultado do período {idx}"
        summary = f"A {empresa} divulgou balanço referente ao ciclo {idx}."
    return {
        "title":       title,
        "url":         f"https://exemplo.com/artigo/{idx}",
        "summary":     summary,
        "published_at": f"2025-{(idx % 12)+1:02d}-{(idx % 28)+1:02d}",
        "source":      random.choice(FONTES),
    }


def gerar_corpus(n: int) -> list[dict]:
    """
    Gera n artigos, sendo:
      - 70% artigos únicos
      - 15% duplicatas de URL (mesma URL)
      - 15% duplicatas de conteúdo (URL diferente, texto idêntico)
    Distribui temas uniformemente.
    """
    temas_lista = list(TEMAS_SEED.keys()) + [None] * 2
    artigos = []
    unicos  = int(n * 0.70)
    dup_url = int(n * 0.15)
    dup_con = int(n * 0.15)

    for i in range(unicos):
        tema = temas_lista[i % len(temas_lista)]
        artigos.append(_artigo(i, tema))

    # duplicatas de URL: mesma URL de artigos já gerados
    base = artigos[:dup_url]
    for a in base:
        artigos.append(dict(a))     # cópia exata = mesma URL

    # duplicatas de conteúdo: mesmo texto, URL diferente
    base2 = artigos[:dup_con]
    for i, a in enumerate(base2):
        dup = dict(a)
        dup["url"] = f"https://outro-portal.com/artigo/{i}"
        artigos.append(dup)

    random.shuffle(artigos)
    return artigos


# ── helpers de banco ──────────────────────────────────────────────────────────

def _criar_banco_simples(db_path: str):
    """Schema mínimo SEM content_hash nem FTS5 (versão antiga)."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS news (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            url          TEXT UNIQUE NOT NULL,
            summary      TEXT,
            published_at TEXT,
            source       TEXT
        );
    """)
    conn.commit()
    conn.close()


def _criar_banco_novo(db_path: str):
    """Schema COM content_hash e FTS5 (versão nova)."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS news (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            url          TEXT UNIQUE NOT NULL,
            summary      TEXT,
            published_at TEXT,
            source       TEXT,
            content_hash TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_content_hash ON news(content_hash);
        CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
            title, summary,
            content='news', content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        );
    """)
    conn.commit()
    conn.close()


def _inserir_simples(db_path: str, artigos: list[dict]) -> tuple[int, int]:
    """Insere artigos com dedup por URL apenas. Retorna (inseridos, duplicatas)."""
    conn = sqlite3.connect(db_path)
    inseridos = 0
    duplicatas = 0
    for a in artigos:
        try:
            conn.execute(
                "INSERT INTO news (title,url,summary,published_at,source) VALUES(?,?,?,?,?)",
                (a["title"], a["url"], a["summary"], a["published_at"], a["source"]),
            )
            inseridos += 1
        except sqlite3.IntegrityError:
            duplicatas += 1
    conn.commit()
    conn.close()
    return inseridos, duplicatas


def _inserir_novo(db_path: str, artigos: list[dict]) -> tuple[int, int]:
    """Insere artigos com dedup por URL + content_hash. Retorna (inseridos, duplicatas)."""
    from storage.dedup import content_fingerprint
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    inseridos = 0
    duplicatas = 0
    for a in artigos:
        fp = content_fingerprint(a["title"], a["summary"] or "")
        # dedup URL
        if conn.execute("SELECT 1 FROM news WHERE url=?", (a["url"],)).fetchone():
            duplicatas += 1
            continue
        # dedup conteúdo
        if conn.execute("SELECT 1 FROM news WHERE content_hash=?", (fp,)).fetchone():
            duplicatas += 1
            continue
        try:
            cur = conn.execute(
                """INSERT INTO news (title,url,summary,published_at,source,content_hash)
                   VALUES(?,?,?,?,?,?)""",
                (a["title"], a["url"], a["summary"], a["published_at"], a["source"], fp),
            )
            conn.execute(
                "INSERT INTO news_fts(rowid,title,summary) VALUES(?,?,?)",
                (cur.lastrowid, a["title"], a["summary"] or ""),
            )
            inseridos += 1
        except sqlite3.IntegrityError:
            duplicatas += 1
    conn.commit()
    conn.close()
    return inseridos, duplicatas


# ── descoberta de temas ───────────────────────────────────────────────────────

def _temas_python(db_path: str) -> float:
    """Tempo da descoberta de temas carregando tudo em Python."""
    import sys as _sys
    _sys.path.insert(0, ".")
    from descobrir_temas import descobrir
    t = time.perf_counter()
    descobrir(db_path=db_path, min_freq=2, top_n=20)
    return time.perf_counter() - t


def _temas_sql(db_path: str) -> float:
    """Tempo da descoberta de temas via FTS5."""
    from descobrir_temas_sql import descobrir_sql
    t = time.perf_counter()
    descobrir_sql(db_path=db_path, min_docs=2, top_n=20)
    return time.perf_counter() - t


# ── runner do benchmark ───────────────────────────────────────────────────────

def run(n: int):
    print(f"Gerando {n} artigos sinteticos (70% unicos, 15% dup-URL, 15% dup-conteudo)...")
    corpus = gerar_corpus(n)
    dup_url_esperadas = int(n * 0.15)
    dup_con_esperadas = int(n * 0.15)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_simples = f.name
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_novo = f.name

    try:
        # ── inserção ─────────────────────────────────────────────────────────
        _criar_banco_simples(db_simples)
        t0 = time.perf_counter()
        ins_s, dup_s = _inserir_simples(db_simples, corpus)
        t_ins_simples = time.perf_counter() - t0

        _criar_banco_novo(db_novo)
        t0 = time.perf_counter()
        ins_n, dup_n = _inserir_novo(db_novo, corpus)
        t_ins_novo = time.perf_counter() - t0

        # ── descoberta de temas ───────────────────────────────────────────────
        t_py  = _temas_python(db_simples)
        t_sql = _temas_sql(db_novo)

        # ── resultados ────────────────────────────────────────────────────────
        print()
        print(f"{'='*62}")
        print(f"  RESULTADO — {n} artigos")
        print(f"{'='*62}")
        print()
        print(f"  {'':30} {'SIMPLES':>10}  {'NOVO':>10}")
        print(f"  {'-'*30} {'-'*10}  {'-'*10}")
        print(f"  {'Artigos inseridos':<30} {ins_s:>10}  {ins_n:>10}")
        print(f"  {'Duplicatas detectadas':<30} {dup_s:>10}  {dup_n:>10}")
        print(f"  {'  - dup URL esperadas':<30} {dup_url_esperadas:>10}  {dup_url_esperadas:>10}")
        print(f"  {'  - dup conteudo esperadas':<30} {'?':>10}  {dup_con_esperadas:>10}")
        print(f"  {'Tempo insercao (s)':<30} {t_ins_simples:>10.3f}  {t_ins_novo:>10.3f}")
        print(f"  {'Tempo descoberta temas (s)':<30} {t_py:>10.3f}  {t_sql:>10.3f}")
        print()

        ganho_dedup = dup_n - dup_s
        ganho_temas = t_py / t_sql if t_sql > 0 else 0
        print(f"  Dedup extra pelo fingerprint : +{ganho_dedup} artigos capturados")
        print(f"  Ganho de velocidade (temas)  : {ganho_temas:.1f}x mais rapido")
        print()

    finally:
        os.unlink(db_simples)
        os.unlink(db_novo)


def _parse():
    args = sys.argv[1:]
    n = 1000
    if "--n" in args:
        n = int(args[args.index("--n") + 1])
    return n


if __name__ == "__main__":
    run(_parse())
