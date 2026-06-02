"""Interface de linha de comando do news-cataloger.

Responsabilidade única: ler argumentos, chamar a função certa em reports.py
ou executar comandos de escrita (feed-add, feed-off), e sair com o código
correto. Nenhuma lógica de consulta ou formatação vive aqui.
"""
import sys
import config
import reports
from storage.database import get_conn

# Garante que o terminal aceite qualquer unicode sem travar;
# caracteres fora do codec do terminal são substituídos por '?' em vez de
# lançar UnicodeEncodeError (comum no Windows com cp1252).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


# ── comandos de escrita ───────────────────────────────────────────────────────
# Ficam aqui (e não em reports.py) por serem operações de escrita no banco,
# não relatórios de leitura.

def feed_add(url: str, db_path: str = config.DB_PATH):
    """Cadastra um novo feed RSS. Reativa se já existia inativo."""
    with get_conn(db_path) as conn:
        existing = conn.execute(
            "SELECT id, active FROM feeds WHERE url = ?", (url,)
        ).fetchone()
        if existing:
            if existing["active"]:
                print(f"  [AVISO] Feed ja cadastrado e ativo: {url}")
            else:
                conn.execute("UPDATE feeds SET active=1 WHERE url=?", (url,))
                print(f"  [OK] Feed reativado: {url}")
            return
        conn.execute("INSERT INTO feeds (url) VALUES (?)", (url,))
        print(f"  [OK] Feed adicionado: {url}")


def feed_off(url_or_id: str, db_path: str = config.DB_PATH):
    """Desativa um feed pelo ID ou por trecho da URL (histórico preservado)."""
    with get_conn(db_path) as conn:
        if url_or_id.isdigit():
            row = conn.execute(
                "SELECT id, url, active FROM feeds WHERE id=?", (int(url_or_id),)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, url, active FROM feeds WHERE url LIKE ?",
                (f"%{url_or_id}%",)
            ).fetchone()

        if not row:
            print(f"  [ERRO] Feed nao encontrado: {url_or_id}")
            print(f"  Use 'python news.py feeds' para ver os feeds cadastrados.")
            sys.exit(1)
        if not row["active"]:
            print(f"  [AVISO] Feed ja esta inativo: {row['url']}")
            return
        conn.execute("UPDATE feeds SET active=0 WHERE id=?", (row["id"],))
        print(f"  [OK] Feed desativado: {row['url']}")
        print(f"  O historico de noticias coletadas foi preservado.")


# ── parsing de argumentos ─────────────────────────────────────────────────────

def _parse_args():
    """Extrai --db PATH dos argumentos e devolve (args_restantes, db_path)."""
    args = sys.argv[1:]
    db_path = config.DB_PATH
    if "--db" in args:
        idx = args.index("--db")
        db_path = args[idx + 1]
        args = args[:idx] + args[idx + 2:]
    return args, db_path


# ── ajuda ─────────────────────────────────────────────────────────────────────

USAGE = """\
Uso: python news.py <comando> [args] [--db PATH]

Coleta:
  coletar          busca noticias dos feeds ativos e popula o banco

Relatorios:
  resumo           totais gerais da base
  feeds            feeds RSS cadastrados e seus status
  temas            noticias agrupadas por tema
  empresas         empresas citadas por tema
  por-empresa      noticias agrupadas por empresa
  suspeitas        empresas curtas sem alias (possiveis falsos positivos)
  pares            pares de entidades co-ocorrentes (ordenados por PMI)
  vizinhanca <X>   grafo de proximidade de 2 graus ao redor de X
  tudo             relatorio completo

Visualizacao:
  grafo            gera grafo.html com entidades e co-ocorrencias
  grafo --temas    idem incluindo nos de tema
  grafo --min N    filtra pares com menos de N co-ocorrencias (padrao: 2)
  grafo --out ARQ  nome do arquivo de saida (padrao: grafo.html)

Gestao de feeds:
  feed-add <url>                  cadastra novo feed RSS
  feed-add <url> --scraper <id>   cadastra site via scraper HTML
  feed-off <id|trecho>            desativa feed (historico preservado)

Scrapers disponiveis: bndes_agencia, bndes_blog
"""


# ── dispatcher ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args, db_path = _parse_args()

    if not args:
        print(USAGE)
        sys.exit(0)

    cmd, rest = args[0], args[1:]

    if cmd == "coletar":
        import coordinator
        coordinator.run(db_path=db_path)
    elif cmd == "resumo":
        reports.resumo_geral(db_path)
    elif cmd == "feeds":
        reports.listar_feeds(db_path)
    elif cmd == "temas":
        reports.noticias_por_tema(db_path)
    elif cmd == "empresas":
        reports.empresas_por_tema(db_path)
    elif cmd == "por-empresa":
        reports.noticias_por_empresa(db_path)
    elif cmd == "suspeitas":
        reports.empresas_suspeitas(db_path)
    elif cmd == "pares":
        reports.pares_coocorrentes(db_path)
    elif cmd == "vizinhanca":
        if not rest:
            print("Uso: python news.py vizinhanca <nome da entidade>")
            sys.exit(1)
        reports.vizinhanca(" ".join(rest), db_path=db_path)
    elif cmd == "tudo":
        reports.relatorio_completo(db_path)
    elif cmd == "grafo":
        import graph, webbrowser, os
        temas  = "--temas" in rest
        output = "grafo.html"
        min_c  = 2
        if "--out" in rest:
            output = rest[rest.index("--out") + 1]
        if "--min" in rest:
            min_c = int(rest[rest.index("--min") + 1])
        try:
            path = graph.gerar_grafo(
                db_path=db_path,
                min_cooc=min_c,
                incluir_temas=temas,
                output=output,
            )
            print(f"  [OK] Grafo salvo em: {os.path.abspath(path)}")
            webbrowser.open(f"file://{os.path.abspath(path)}")
        except ValueError as e:
            print(f"  [AVISO] {e}")
    elif cmd == "feed-add":
        if not rest:
            print("Uso: python news.py feed-add <url> [--scraper <id>]")
            sys.exit(1)
        if "--scraper" in rest:
            idx = rest.index("--scraper")
            scraper_id = rest[idx + 1]
            from storage.database import add_scraper_feed
            add_scraper_feed(rest[0], scraper_id, db_path)
            print(f"  [OK] Scraper '{scraper_id}' cadastrado: {rest[0]}")
        else:
            feed_add(rest[0], db_path)
    elif cmd == "feed-off":
        if not rest:
            print("Uso: python news.py feed-off <id|trecho da url>")
            sys.exit(1)
        feed_off(rest[0], db_path)
    else:
        print(f"Comando desconhecido: '{cmd}'\n")
        print(USAGE)
        sys.exit(1)
