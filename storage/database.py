import re
import sqlite3
from contextlib import contextmanager
from typing import Optional
import config


@contextmanager
def get_conn(db_path: str = config.DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = config.DB_PATH):
    with get_conn(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS themes (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            CREATE TABLE IF NOT EXISTS news (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                title        TEXT NOT NULL,
                url          TEXT UNIQUE NOT NULL,
                summary      TEXT,
                published_at TEXT,
                source       TEXT,
                created_at   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS companies (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );

            -- Aliases/sinônimos de empresas.
            -- is_safe=1: qualquer ocorrência resolve para o canônico.
            -- is_safe=0: só resolve se o alias aparecer com contexto suficiente
            --            (ex: "Receita" sozinha é ambígua; "Receita Federal" não).
            CREATE TABLE IF NOT EXISTS company_aliases (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                alias      TEXT UNIQUE NOT NULL,
                company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                is_safe    INTEGER NOT NULL DEFAULT 1
            );

            -- Feeds monitorados. type='rss' para feeds RSS padrão;
            -- type='scraper' para sites sem RSS (o campo scraper identifica
            -- qual função de scraping usar, ex: 'bndes_agencia').
            -- active=0 desativa sem remover o histórico de notícias.
            CREATE TABLE IF NOT EXISTS feeds (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                url        TEXT UNIQUE NOT NULL,
                name       TEXT,
                active     INTEGER NOT NULL DEFAULT 1,
                type       TEXT    NOT NULL DEFAULT 'rss',
                scraper    TEXT,
                added_at   TEXT NOT NULL DEFAULT (date('now'))
            );

            -- Co-ocorrência de entidades: registra quantas notícias mencionam
            -- A e B juntos. Armazenamos sempre com entity_a_id < entity_b_id
            -- para evitar pares duplicados (A,B) e (B,A).
            CREATE TABLE IF NOT EXISTS entity_cooccurrence (
                entity_a_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                entity_b_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
                news_count   INTEGER NOT NULL DEFAULT 1,
                last_seen_at TEXT    NOT NULL DEFAULT (date('now')),
                PRIMARY KEY (entity_a_id, entity_b_id),
                CHECK (entity_a_id < entity_b_id)
            );

            CREATE TABLE IF NOT EXISTS news_themes (
                news_id  INTEGER REFERENCES news(id) ON DELETE CASCADE,
                theme_id INTEGER REFERENCES themes(id) ON DELETE CASCADE,
                PRIMARY KEY (news_id, theme_id)
            );

            CREATE TABLE IF NOT EXISTS news_companies (
                news_id    INTEGER REFERENCES news(id) ON DELETE CASCADE,
                company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
                PRIMARY KEY (news_id, company_id)
            );
        """)
    # migração: adiciona colunas novas em bancos criados antes desta versão
    _migrate_feeds_table(db_path)
    # popula feeds e aliases definidos em config logo após criar o schema
    load_feeds_from_file(db_path)
    load_aliases_from_config(db_path)


# ── Feeds ─────────────────────────────────────────────────────────────────────

def _migrate_feeds_table(db_path: str = config.DB_PATH):
    """Adiciona colunas type/scraper em bancos criados antes desta versão.
    SQLite não suporta IF NOT EXISTS em ALTER TABLE, então usamos try/except."""
    with get_conn(db_path) as conn:
        for col, definition in [("type", "TEXT NOT NULL DEFAULT 'rss'"),
                                 ("scraper", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE feeds ADD COLUMN {col} {definition}")
            except Exception:
                pass  # coluna já existe — ignorar

def load_feeds_from_file(db_path: str = config.DB_PATH):
    """Lê feeds.txt e insere no banco URLs ainda não cadastradas.
    Idempotente: URLs já existentes são ignoradas (INSERT OR IGNORE)."""
    import os
    feeds_path = os.path.join(os.path.dirname(config.__file__), config.FEEDS_FILE)
    if not os.path.exists(feeds_path):
        return
    with open(feeds_path, encoding="utf-8") as f:
        urls = [
            line.strip() for line in f
            if line.strip() and not line.startswith("#")
        ]
    with get_conn(db_path) as conn:
        for url in urls:
            conn.execute(
                "INSERT OR IGNORE INTO feeds (url) VALUES (?)", (url,)
            )


def get_active_feeds(db_path: str = config.DB_PATH) -> list[str]:
    """Retorna URLs dos feeds RSS ativos (type='rss')."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT url FROM feeds WHERE active=1 AND type='rss' ORDER BY id"
        ).fetchall()
    return [r["url"] for r in rows]


def get_active_scrapers(db_path: str = config.DB_PATH) -> list[dict]:
    """Retorna scrapers ativos (type='scraper') como lista de dicts {url, scraper}."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT url, scraper FROM feeds WHERE active=1 AND type='scraper' ORDER BY id"
        ).fetchall()
    return [{"url": r["url"], "scraper": r["scraper"]} for r in rows]


def add_scraper_feed(url: str, scraper_id: str, db_path: str = config.DB_PATH):
    """Cadastra um feed do tipo scraper. Reativa se já existia inativo."""
    _migrate_feeds_table(db_path)  # garante colunas type/scraper em bancos antigos
    with get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT id, active FROM feeds WHERE url=?", (url,)
        ).fetchone()
        if existing:
            if not existing["active"]:
                conn.execute(
                    "UPDATE feeds SET active=1, type='scraper', scraper=? WHERE url=?",
                    (scraper_id, url)
                )
            return
        conn.execute(
            "INSERT INTO feeds (url, type, scraper) VALUES (?, 'scraper', ?)",
            (url, scraper_id)
        )


# ── Aliases ───────────────────────────────────────────────────────────────────

def load_aliases_from_config(db_path: str = config.DB_PATH):
    """Sincroniza COMPANY_ALIASES do config com a tabela company_aliases.
    Idempotente: pode ser chamada várias vezes sem duplicar dados."""
    for canonical, data in config.COMPANY_ALIASES.items():
        # garante que a empresa canônica existe
        company_id = get_or_create_company(canonical, db_path)

        safe_aliases   = data.get("aliases", [])
        unsafe_aliases = data.get("unsafe", [])

        with get_conn(db_path) as conn:
            for alias in safe_aliases:
                conn.execute(
                    "INSERT OR IGNORE INTO company_aliases (alias, company_id, is_safe) VALUES (?, ?, 1)",
                    (alias, company_id),
                )
            for alias in unsafe_aliases:
                conn.execute(
                    "INSERT OR IGNORE INTO company_aliases (alias, company_id, is_safe) VALUES (?, ?, 0)",
                    (alias, company_id),
                )


def resolve_alias(name: str, context: str = "", db_path: str = config.DB_PATH) -> str:
    """Retorna o nome canônico se o nome for um alias conhecido; caso contrário
    devolve o próprio nome.

    Para aliases inseguros (is_safe=0), a resolução só ocorre se o nome aparecer
    acompanhado de ao menos uma outra palavra capitalizada no contexto — heurística
    simples para desambiguar, ex: 'Receita Federal' resolve, 'Receita' sozinha não.
    """
    with get_conn(db_path) as conn:
        row = conn.execute("""
            SELECT c.name AS canonical, ca.is_safe
            FROM company_aliases ca
            JOIN companies c ON c.id = ca.company_id
            WHERE ca.alias = ?
        """, (name,)).fetchone()

    if not row:
        return name  # sem alias: devolve o nome original

    if row["is_safe"]:
        return row["canonical"]

    # alias inseguro: só resolve se o nome aparecer com palavra capitalizada adjacente
    if _has_capitalized_neighbor(name, context):
        return row["canonical"]

    return name  # contexto insuficiente — mantém o nome ambíguo como está


def _has_capitalized_neighbor(name: str, context: str) -> bool:
    """Verifica se 'name' aparece no contexto cercado por ao menos uma outra
    palavra que começa com letra maiúscula — indicativo de nome próprio composto."""
    if not context:
        return False
    escaped = re.escape(name)
    # padrão: palavra capitalizada antes OU depois do alias
    pattern = (
        r'(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ]\w+\s+)' + escaped +
        r'|' +
        escaped + r'(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]\w+)'
    )
    return bool(re.search(pattern, context))


# ── CRUD básico ───────────────────────────────────────────────────────────────

def upsert_news(title: str, url: str, summary: str, published_at: str, source: str,
                db_path: str = config.DB_PATH) -> Optional[int]:
    with get_conn(db_path) as conn:
        existing = conn.execute("SELECT id FROM news WHERE url = ?", (url,)).fetchone()
        if existing:
            return None  # já catalogada
        cur = conn.execute(
            "INSERT INTO news (title, url, summary, published_at, source) VALUES (?, ?, ?, ?, ?)",
            (title, url, summary, published_at, source),
        )
        return cur.lastrowid


def get_or_create_theme(name: str, db_path: str = config.DB_PATH) -> int:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT id FROM themes WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute("INSERT INTO themes (name) VALUES (?)", (name,))
        return cur.lastrowid


def get_or_create_company(name: str, db_path: str = config.DB_PATH) -> int:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute("INSERT INTO companies (name) VALUES (?)", (name,))
        return cur.lastrowid


def link_news_theme(news_id: int, theme_id: int, db_path: str = config.DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO news_themes (news_id, theme_id) VALUES (?, ?)",
            (news_id, theme_id),
        )


def link_news_company(news_id: int, company_id: int, db_path: str = config.DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO news_companies (news_id, company_id) VALUES (?, ?)",
            (news_id, company_id),
        )


# ── Consultas ─────────────────────────────────────────────────────────────────

def query_by_theme(theme_name: str, db_path: str = config.DB_PATH) -> list:
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT n.title, n.url, n.published_at, n.source
            FROM news n
            JOIN news_themes nt ON nt.news_id = n.id
            JOIN themes t ON t.id = nt.theme_id
            WHERE t.name = ?
            ORDER BY n.published_at DESC
        """, (theme_name,)).fetchall()
        return [dict(r) for r in rows]


def query_by_company(company_name: str, db_path: str = config.DB_PATH) -> list:
    """Busca notícias pelo nome canônico da empresa — aliases já foram resolvidos
    na ingestão, então a consulta não precisa saber deles."""
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT n.title, n.url, n.published_at, n.source
            FROM news n
            JOIN news_companies nc ON nc.news_id = n.id
            JOIN companies c ON c.id = nc.company_id
            WHERE c.name LIKE ?
            ORDER BY n.published_at DESC
        """, (f"%{company_name}%",)).fetchall()
        return [dict(r) for r in rows]


def stats(db_path: str = config.DB_PATH) -> dict:
    with get_conn(db_path) as conn:
        return {
            "news":         conn.execute("SELECT COUNT(*) FROM news").fetchone()[0],
            "themes":       conn.execute("SELECT COUNT(*) FROM themes").fetchone()[0],
            "companies":    conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
            "aliases":      conn.execute("SELECT COUNT(*) FROM company_aliases").fetchone()[0],
            "cooccurrences": conn.execute("SELECT COUNT(*) FROM entity_cooccurrence").fetchone()[0],
        }


# ── Co-ocorrência ─────────────────────────────────────────────────────────────

def record_cooccurrences(company_ids: list[int], db_path: str = config.DB_PATH):
    """Dado um conjunto de entidades que aparecem na mesma notícia, incrementa
    o contador de co-ocorrência para cada par único.
    Pares são normalizados com id menor primeiro para evitar duplicatas."""
    ids = sorted(set(company_ids))  # garante unicidade e ordem crescente
    with get_conn(db_path) as conn:
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                conn.execute("""
                    INSERT INTO entity_cooccurrence (entity_a_id, entity_b_id, news_count, last_seen_at)
                    VALUES (?, ?, 1, date('now'))
                    ON CONFLICT (entity_a_id, entity_b_id)
                    DO UPDATE SET
                        news_count   = news_count + 1,
                        last_seen_at = date('now')
                """, (a, b))


def query_cooccurrences(limit: int = 50, db_path: str = config.DB_PATH) -> list[dict]:
    """Retorna os pares mais frequentes com contagem bruta e PMI.

    PMI (Pointwise Mutual Information) desconta entidades que aparecem em muitas
    notícias independentemente: um PMI alto indica associação além do acaso.
    PMI = log2( P(A,B) / P(A)*P(B) ) = log2( count(A,B)*N / count(A)*count(B) )
    """
    import math
    with get_conn(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        # sem notícias no banco, PMI não é calculável — retorna por contagem bruta
        if total == 0:
            rows = conn.execute("""
                SELECT ca.name AS name_a, cb.name AS name_b,
                       ec.news_count, ec.last_seen_at
                FROM entity_cooccurrence ec
                JOIN companies ca ON ca.id = ec.entity_a_id
                JOIN companies cb ON cb.id = ec.entity_b_id
                ORDER BY ec.news_count DESC LIMIT ?
            """, (limit,)).fetchall()
            return [{"name_a": r["name_a"], "name_b": r["name_b"],
                     "news_count": r["news_count"], "pmi": None,
                     "last_seen": r["last_seen_at"]} for r in rows]

        # contagem de notícias por entidade (aparece em A ou B de qualquer par)
        freq = {}
        for row in conn.execute("""
            SELECT company_id, COUNT(*) AS cnt
            FROM news_companies
            GROUP BY company_id
        """).fetchall():
            freq[row["company_id"]] = row["cnt"]

        rows = conn.execute("""
            SELECT ca.name AS name_a, cb.name AS name_b,
                   ec.news_count, ec.last_seen_at,
                   ec.entity_a_id, ec.entity_b_id
            FROM entity_cooccurrence ec
            JOIN companies ca ON ca.id = ec.entity_a_id
            JOIN companies cb ON cb.id = ec.entity_b_id
            ORDER BY ec.news_count DESC
            LIMIT ?
        """, (limit * 3,)).fetchall()  # busca mais para ordenar por PMI depois

    result = []
    for r in rows:
        pa  = freq.get(r["entity_a_id"], 1) / total
        pb  = freq.get(r["entity_b_id"], 1) / total
        pab = r["news_count"] / total
        # PMI pode ser negativo (co-ocorrência abaixo do esperado); exibimos mesmo assim
        pmi = round(math.log2(pab / (pa * pb)), 2) if pa * pb > 0 else 0.0
        result.append({
            "name_a":     r["name_a"],
            "name_b":     r["name_b"],
            "news_count": r["news_count"],
            "pmi":        pmi,
            "last_seen":  r["last_seen_at"],
        })

    # ordena por PMI decrescente para destacar associações além do acaso
    result.sort(key=lambda x: x["pmi"], reverse=True)
    return result[:limit]


def query_neighbors(entity_name: str, depth: int = 2,
                    db_path: str = config.DB_PATH) -> dict:
    """Retorna a vizinhança de uma entidade no grafo de co-ocorrência até `depth`
    graus de separação. Profundidade 1 = vizinhos diretos; 2 = vizinhos dos vizinhos.

    Retorna: { 'centro': nome, 'grau_1': [...], 'grau_2': [...] }
    onde cada item tem name e news_count do elo mais fraco no caminho.
    """
    with get_conn(db_path) as conn:
        # resolve o id da entidade central
        row = conn.execute(
            "SELECT id FROM companies WHERE name LIKE ?", (f"%{entity_name}%",)
        ).fetchone()
        if not row:
            return {"centro": entity_name, "grau_1": [], "grau_2": []}
        center_id = row["id"]

        def _neighbors(entity_id: int) -> list[dict]:
            """Vizinhos diretos de uma entidade."""
            return conn.execute("""
                SELECT c.id, c.name, ec.news_count
                FROM entity_cooccurrence ec
                JOIN companies c ON c.id = CASE
                    WHEN ec.entity_a_id = ? THEN ec.entity_b_id
                    ELSE ec.entity_a_id END
                WHERE ec.entity_a_id = ? OR ec.entity_b_id = ?
                ORDER BY ec.news_count DESC
            """, (entity_id, entity_id, entity_id)).fetchall()

        g1 = _neighbors(center_id)
        g1_ids = {r["id"] for r in g1}

        g2 = []
        if depth >= 2:
            seen = g1_ids | {center_id}
            for neighbor in g1:
                for r in _neighbors(neighbor["id"]):
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        # força de ligação = mínimo ao longo do caminho
                        g2.append({
                            "name":       r["name"],
                            "via":        neighbor["name"],
                            "news_count": min(neighbor["news_count"], r["news_count"]),
                        })
            g2.sort(key=lambda x: x["news_count"], reverse=True)

    return {
        "centro": entity_name,
        "grau_1": [{"name": r["name"], "news_count": r["news_count"]} for r in g1],
        "grau_2": g2,
    }
