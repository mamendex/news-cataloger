"""Funções de consulta e exibição do news-cataloger.

Este módulo contém apenas lógica de leitura e formatação — sem parsing de
argumentos, sem sys.exit, sem lógica de escrita. Pode ser importado por
qualquer outro módulo (CLI, testes, notebooks, API futura).
"""
import config
from storage.database import get_conn


# ── helpers ───────────────────────────────────────────────────────────────────

def _separator(title: str):
    print(f"\n{'-' * 60}")
    print(f"  {title}")
    print(f"{'-' * 60}")


def _no_data(msg="Nenhum dado encontrado."):
    print(f"  {msg}")


# ── relatórios ────────────────────────────────────────────────────────────────

def resumo_geral(db_path: str = config.DB_PATH):
    _separator("RESUMO GERAL")
    with get_conn(db_path) as conn:
        news      = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        themes    = conn.execute("SELECT COUNT(*) FROM themes").fetchone()[0]
        companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        links_nt  = conn.execute("SELECT COUNT(*) FROM news_themes").fetchone()[0]
        links_nc  = conn.execute("SELECT COUNT(*) FROM news_companies").fetchone()[0]
        feeds_on  = conn.execute("SELECT COUNT(*) FROM feeds WHERE active=1").fetchone()[0]
        feeds_off = conn.execute("SELECT COUNT(*) FROM feeds WHERE active=0").fetchone()[0]
        coocc     = conn.execute("SELECT COUNT(*) FROM entity_cooccurrence").fetchone()[0]
    print(f"  Feeds ativos   : {feeds_on}  (desativados: {feeds_off})")
    print(f"  Noticias       : {news}")
    print(f"  Temas          : {themes}")
    print(f"  Empresas       : {companies}")
    print(f"  Co-ocorrencias : {coocc}")
    print(f"  Vinculos noticia-tema    : {links_nt}")
    print(f"  Vinculos noticia-empresa : {links_nc}")


def listar_feeds(db_path: str = config.DB_PATH):
    _separator("FEEDS CADASTRADOS")
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT id, url, name, active, added_at FROM feeds ORDER BY id"
        ).fetchall()
    if not rows:
        _no_data()
        return
    for r in rows:
        status = "ativo  " if r["active"] else "inativo"
        name   = f" ({r['name']})" if r["name"] else ""
        print(f"  [{status}] #{r['id']}  {r['url']}{name}")


def noticias_por_tema(db_path: str = config.DB_PATH):
    _separator("NOTICIAS POR TEMA")
    with get_conn(db_path) as conn:
        temas = conn.execute("SELECT id, name FROM themes ORDER BY name").fetchall()
        if not temas:
            _no_data()
            return
        for tema in temas:
            rows = conn.execute("""
                SELECT n.title, n.source, n.published_at
                FROM news n
                JOIN news_themes nt ON nt.news_id = n.id
                WHERE nt.theme_id = ?
                ORDER BY n.published_at DESC
            """, (tema["id"],)).fetchall()
            print(f"\n  [{tema['name'].upper()}] — {len(rows)} noticia(s)")
            for r in rows:
                pub = r["published_at"][:10] if r["published_at"] else "—"
                print(f"    {pub}  {r['title'][:65]}")
                print(f"           Fonte: {r['source']}")


def empresas_por_tema(db_path: str = config.DB_PATH):
    _separator("EMPRESAS POR TEMA")
    with get_conn(db_path) as conn:
        temas = conn.execute("SELECT id, name FROM themes ORDER BY name").fetchall()
        if not temas:
            _no_data()
            return
        for tema in temas:
            rows = conn.execute("""
                SELECT DISTINCT c.name
                FROM companies c
                JOIN news_companies nc ON nc.company_id = c.id
                JOIN news_themes nt    ON nt.news_id    = nc.news_id
                WHERE nt.theme_id = ?
                ORDER BY c.name
            """, (tema["id"],)).fetchall()
            if not rows:
                continue
            nomes = ", ".join(r["name"] for r in rows)
            print(f"\n  [{tema['name'].upper()}]")
            print(f"    {nomes}")


def noticias_por_empresa(db_path: str = config.DB_PATH):
    _separator("NOTICIAS POR EMPRESA")
    with get_conn(db_path) as conn:
        empresas = conn.execute("""
            SELECT c.id, c.name, COUNT(nc.news_id) AS total
            FROM companies c
            JOIN news_companies nc ON nc.company_id = c.id
            GROUP BY c.id
            ORDER BY total DESC, c.name
        """).fetchall()
        if not empresas:
            _no_data()
            return
        for emp in empresas:
            rows = conn.execute("""
                SELECT n.title, n.source, n.published_at
                FROM news n
                JOIN news_companies nc ON nc.news_id = n.id
                WHERE nc.company_id = ?
                ORDER BY n.published_at DESC
            """, (emp["id"],)).fetchall()
            print(f"\n  [{emp['name']}] — {emp['total']} noticia(s)")
            for r in rows:
                pub = r["published_at"][:10] if r["published_at"] else "—"
                print(f"    {pub}  {r['title'][:65]}")
                print(f"           Fonte: {r['source']}")


# Comprimento máximo para considerar um nome suspeito (palavra única abaixo desse limite)
SUSPEITOS_MAX_CHARS = 10


def empresas_suspeitas(db_path: str = config.DB_PATH, max_chars: int = SUSPEITOS_MAX_CHARS):
    _separator(f"EMPRESAS SUSPEITAS (1 palavra, < {max_chars} chars, sem alias)")
    with get_conn(db_path) as conn:
        rows = conn.execute("""
            SELECT c.id, c.name,
                   COUNT(nc.news_id) AS total_noticias
            FROM companies c
            LEFT JOIN company_aliases ca ON ca.company_id = c.id
            JOIN news_companies nc ON nc.company_id = c.id
            WHERE ca.id IS NULL
            GROUP BY c.id
            ORDER BY total_noticias DESC, c.name
        """).fetchall()

    suspeitas = [
        r for r in rows
        if " " not in r["name"].strip()
        and len(r["name"].strip()) < max_chars
    ]

    if not suspeitas:
        _no_data(f"Nenhuma empresa suspeita (criterio: 1 palavra, < {max_chars} chars, sem alias).")
        return

    print(f"  {'Nome':<20} {'Noticias':>8}   Acao sugerida")
    print(f"  {'-'*20} {'-'*8}   {'-'*30}")
    for r in suspeitas:
        print(f"  {r['name']:<20} {r['total_noticias']:>8}   "
              f"adicionar alias em config.py ou incluir na blocklist")


def pares_coocorrentes(db_path: str = config.DB_PATH, limit: int = 30):
    from storage.database import query_cooccurrences
    _separator(f"PARES CO-OCORRENTES (top {limit} por PMI)")
    rows = query_cooccurrences(limit=limit, db_path=db_path)
    if not rows:
        _no_data()
        return
    print(f"  {'Entidade A':<28} {'Entidade B':<28} {'Noticias':>8}  {'PMI':>6}")
    print(f"  {'-'*28} {'-'*28} {'-'*8}  {'-'*6}")
    for r in rows:
        pmi_str = f"{r['pmi']:>6.2f}" if r["pmi"] is not None else "   n/a"
        print(f"  {r['name_a']:<28} {r['name_b']:<28} {r['news_count']:>8}  {pmi_str}")


def vizinhanca(entity_name: str, db_path: str = config.DB_PATH, depth: int = 2):
    from storage.database import query_neighbors
    result = query_neighbors(entity_name, depth=depth, db_path=db_path)
    _separator(f"VIZINHANCA DE '{result['centro'].upper()}'")
    if not result["grau_1"]:
        _no_data(f"Nenhuma co-ocorrencia encontrada para '{entity_name}'.")
        return
    print(f"\n  Grau 1 - mencionados na mesma noticia:")
    for r in result["grau_1"]:
        print(f"    {r['name']:<35}  {r['news_count']} noticia(s)")
    if result["grau_2"]:
        print(f"\n  Grau 2 - alcancados via vizinhos (caminho mais fraco):")
        for r in result["grau_2"][:20]:
            print(f"    {r['name']:<35}  via {r['via']}  [{r['news_count']} noticia(s)]")


def relatorio_completo(db_path: str = config.DB_PATH):
    resumo_geral(db_path)
    listar_feeds(db_path)
    noticias_por_tema(db_path)
    empresas_por_tema(db_path)
    noticias_por_empresa(db_path)
    pares_coocorrentes(db_path)
    print()
