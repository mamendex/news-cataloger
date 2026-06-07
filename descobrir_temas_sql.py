"""
Descoberta de temas via FTS5 — alternativa SQL ao descobrir_temas.py.

Em vez de carregar todos os artigos em Python e tokenizar em memória,
consulta diretamente a tabela de vocabulário do índice FTS5 (news_fts_vocab),
que o SQLite mantém atualizada incrementalmente.

Vantagem de escala: O(1) em relação ao tamanho do corpus — a query é sempre
rápida independente de quantos artigos existam.

Uso:
    python descobrir_temas_sql.py
    python descobrir_temas_sql.py --min 5 --top 30 --db PATH
"""

import re
import sys
import config
from storage.database import get_conn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

# reutiliza as mesmas listas do descobrir_temas.py
from descobrir_temas import STOPWORDS, IGNORAR, _keywords_existentes, formatar_snippet


def descobrir_sql(db_path: str = config.DB_PATH,
                  min_docs: int = 3,
                  top_n:   int = 20) -> list[dict]:
    """
    Consulta o vocabulário FTS5 para obter termos frequentes sem carregar
    os artigos em Python. Retorna candidatos no mesmo formato de descobrir().
    """
    with get_conn(db_path) as conn:
        # verifica se FTS5 está disponível
        fts_ok = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_fts_vocab'"
        ).fetchone()
        if not fts_ok:
            print("[AVISO] Tabela news_fts_vocab nao encontrada.")
            print("        Recrie o banco com 'del news.db && python news.py coletar'")
            print("        ou rode 'python descobrir_temas.py' (versao Python).")
            return []

        total_docs = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        if total_docs == 0:
            return []

        # news_fts_vocab: (term, col, doc, cnt)
        # doc = numero de documentos que contêm o termo
        # cnt = total de ocorrencias
        # col='*' agrega titulo + resumo
        rows = conn.execute("""
            SELECT term, doc, cnt
            FROM news_fts_vocab
            WHERE col = '*'
              AND doc >= ?
            ORDER BY doc DESC
            LIMIT 800
        """, (min_docs,)).fetchall()

        # para cada termo candidato, precisamos exemplos de artigos
        def exemplos(term: str) -> list[str]:
            r = conn.execute("""
                SELECT n.title FROM news n
                JOIN news_fts ON news_fts.rowid = n.id
                WHERE news_fts MATCH ?
                ORDER BY n.published_at DESC
                LIMIT 3
            """, (term,)).fetchall()
            return [row[0] for row in r]

    ja_conhecidas = _keywords_existentes()

    # filtra e formata candidatos
    candidatos = []
    usados = set()

    for row in rows:
        termo = row["term"] if hasattr(row, "keys") else row[0]
        doc   = row["doc"]  if hasattr(row, "keys") else row[1]

        # aplica os mesmos filtros do descobrir_temas.py
        if len(termo) < 4:
            continue
        if not re.match(r'^[a-záéíóúâêôãõç]', termo):
            continue
        if termo in STOPWORDS or termo in IGNORAR:
            continue
        if termo in ja_conhecidas:
            continue
        if termo in usados:
            continue

        usados.add(termo)
        candidatos.append({
            "termo":    termo,
            "freq":     doc,
            "keywords": [termo],   # FTS5 não agrupa — keywords expandidas abaixo
            "exemplos": exemplos(termo),
        })

        if len(candidatos) >= top_n:
            break

    return candidatos


def _parse():
    args  = sys.argv[1:]
    db    = config.DB_PATH
    min_d = 3
    top_n = 20
    if "--db"  in args: db    = args[args.index("--db")  + 1]
    if "--min" in args: min_d = int(args[args.index("--min") + 1])
    if "--top" in args: top_n = int(args[args.index("--top") + 1])
    return db, min_d, top_n


if __name__ == "__main__":
    db, min_docs, top_n = _parse()
    print(f"Analisando '{db}' via FTS5 (min_docs={min_docs}, top={top_n})...\n")

    candidatos = descobrir_sql(db, min_docs=min_docs, top_n=top_n)
    if not candidatos:
        sys.exit(0)

    print(f"{'#':<3} {'Tema candidato':<28} {'Artigos':>7}")
    print(f"{'-'*3} {'-'*28} {'-'*7}")
    for i, c in enumerate(candidatos, 1):
        print(f"{i:<3} {c['termo']:<28} {c['freq']:>7}")

    print("\n-- Exemplos ---------------------------------------------------")
    for c in candidatos[:10]:
        print(f"\n  [{c['termo']}]")
        for ex in c["exemplos"]:
            print(f"    * {ex[:75]}")

    print("\n-- Snippet para config.THEMES ---------------------------------")
    print(formatar_snippet(candidatos))
