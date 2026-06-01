"""Geração de grafos interativos com pyvis.

Responsabilidade única: consultar o banco, montar o grafo e salvar em HTML.
Sem parsing de argumentos — isso fica em news.py.

Dois modos:
  gerar_grafo()              — entidades + co-ocorrências
  gerar_grafo(temas=True)    — idem + nós de tema ligados às entidades
"""
import math
import config
from storage.database import get_conn


# ── paleta de cores por tema ──────────────────────────────────────────────────
# Temas conhecidos recebem cor fixa; demais recebem cores do ciclo automático.
TEMA_CORES = {
    "economia":    "#2196F3",   # azul
    "tecnologia":  "#9C27B0",   # roxo
    "política":    "#F44336",   # vermelho
    "saúde":       "#4CAF50",   # verde
    "energia":     "#FF9800",   # laranja
    "agronegócio": "#795548",   # marrom
    "geral":       "#9E9E9E",   # cinza
}
COR_ENTIDADE_SEM_TEMA = "#607D8B"   # cinza azulado
COR_TEMA_NO            = "#FFD700"  # dourado — nós de tema no modo --temas


def _cor_tema(nome: str) -> str:
    return TEMA_CORES.get(nome, "#E91E63")


def _escala_no(count: int, max_count: int, min_size: int = 12, max_size: int = 60) -> int:
    """Mapeia news_count para tamanho visual do nó (escala logarítmica)."""
    if max_count <= 1:
        return min_size
    ratio = math.log1p(count) / math.log1p(max_count)
    return int(min_size + ratio * (max_size - min_size))


def gerar_grafo(
    db_path:       str  = config.DB_PATH,
    min_cooc:      int  = 2,
    incluir_temas: bool = False,
    output:        str  = "grafo.html",
) -> str:
    """Gera o grafo interativo e salva em `output`. Retorna o caminho do arquivo.

    Parâmetros:
      min_cooc      — filtra co-ocorrências com contagem abaixo deste valor
      incluir_temas — adiciona nós de tema (dourados) ligados às entidades
      output        — caminho do arquivo HTML de saída
    """
    try:
        from pyvis.network import Network
    except ImportError:
        raise RuntimeError("pyvis não instalado. Execute: pip install pyvis")

    with get_conn(db_path) as conn:

        # ── entidades e sua contagem de notícias ──────────────────────────────
        entidades = {
            r["id"]: {"name": r["name"], "news_count": r["news_count"]}
            for r in conn.execute("""
                SELECT c.id, c.name, COUNT(DISTINCT nc.news_id) AS news_count
                FROM companies c
                JOIN news_companies nc ON nc.company_id = c.id
                GROUP BY c.id
            """).fetchall()
        }

        # ── co-ocorrências filtradas ──────────────────────────────────────────
        coocs = conn.execute("""
            SELECT entity_a_id, entity_b_id, news_count
            FROM entity_cooccurrence
            WHERE news_count >= ?
            ORDER BY news_count DESC
        """, (min_cooc,)).fetchall()

        # apenas entidades que participam de pelo menos uma aresta
        ids_no_grafo = set()
        for r in coocs:
            ids_no_grafo.add(r["entity_a_id"])
            ids_no_grafo.add(r["entity_b_id"])

        # ── tema dominante por entidade (para colorir os nós) ─────────────────
        tema_dominante = {}
        for r in conn.execute("""
            SELECT nc.company_id, t.name,
                   COUNT(*) AS cnt
            FROM news_companies nc
            JOIN news_themes nt ON nt.news_id = nc.news_id
            JOIN themes t ON t.id = nt.theme_id
            GROUP BY nc.company_id, t.name
            ORDER BY nc.company_id, cnt DESC
        """).fetchall():
            # só guarda o primeiro (maior cnt) por empresa
            if r["company_id"] not in tema_dominante:
                tema_dominante[r["company_id"]] = r["name"]

        # ── temas e entidades vinculadas (modo --temas) ───────────────────────
        temas = {}
        entidade_temas = {}  # entity_id → [tema_names]
        if incluir_temas:
            for r in conn.execute("""
                SELECT t.id, t.name, COUNT(DISTINCT nt.news_id) AS news_count
                FROM themes t
                JOIN news_themes nt ON nt.theme_id = t.id
                GROUP BY t.id
            """).fetchall():
                temas[r["id"]] = {"name": r["name"], "news_count": r["news_count"]}

            for r in conn.execute("""
                SELECT DISTINCT nc.company_id, nt.theme_id
                FROM news_companies nc
                JOIN news_themes nt ON nt.news_id = nc.news_id
                WHERE nc.company_id IN ({})
            """.format(",".join("?" * len(ids_no_grafo)) if ids_no_grafo else "NULL"),
                list(ids_no_grafo)
            ).fetchall():
                entidade_temas.setdefault(r["company_id"], set()).add(r["theme_id"])

    if not ids_no_grafo:
        raise ValueError(
            f"Nenhuma co-ocorrência com min_cooc >= {min_cooc}. "
            "Execute o coordinator para popular o banco ou reduza --min."
        )

    # ── monta a rede pyvis ────────────────────────────────────────────────────
    net = Network(
        height="95vh", width="100%",
        bgcolor="#1a1a2e",       # fundo escuro
        font_color="#ffffff",
        notebook=False,
    )

    # física: forceAtlas2 puxa nós conectados para perto (molas)
    net.set_options("""
    {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -60,
          "centralGravity": 0.005,
          "springLength": 120,
          "springConstant": 0.1,
          "damping": 0.4
        },
        "solver": "forceAtlas2Based",
        "stabilization": { "iterations": 200 }
      },
      "edges": {
        "smooth": { "type": "continuous" },
        "scaling": { "min": 1, "max": 12 }
      },
      "nodes": {
        "font": { "size": 13 },
        "borderWidth": 2
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100
      }
    }
    """)

    max_count = max((e["news_count"] for e in entidades.values()), default=1)

    # ── adiciona nós de entidade ──────────────────────────────────────────────
    for eid in ids_no_grafo:
        if eid not in entidades:
            continue
        e = entidades[eid]
        tema  = tema_dominante.get(eid)
        cor   = _cor_tema(tema) if tema else COR_ENTIDADE_SEM_TEMA
        size  = _escala_no(e["news_count"], max_count)
        title = (
            f"<b>{e['name']}</b><br>"
            f"Noticias: {e['news_count']}<br>"
            f"Tema principal: {tema or '—'}"
        )
        net.add_node(
            f"e_{eid}",
            label=e["name"],
            size=size,
            color=cor,
            title=title,
            shape="dot",
        )

    # ── adiciona nós de tema (modo --temas) ───────────────────────────────────
    if incluir_temas:
        for tid, t in temas.items():
            size  = _escala_no(t["news_count"], max_count, min_size=20, max_size=50)
            title = f"<b>TEMA: {t['name']}</b><br>Noticias: {t['news_count']}"
            net.add_node(
                f"t_{tid}",
                label=t["name"].upper(),
                size=size,
                color=COR_TEMA_NO,
                title=title,
                shape="diamond",
            )
        # arestas entidade → tema (tracejadas, mais finas)
        for eid, tema_ids in entidade_temas.items():
            for tid in tema_ids:
                if f"e_{eid}" in [n["id"] for n in net.nodes] and tid in temas:
                    net.add_edge(
                        f"e_{eid}", f"t_{tid}",
                        value=1,
                        color={"color": "#ffffff22"},
                        dashes=True,
                    )

    # ── adiciona arestas de co-ocorrência ─────────────────────────────────────
    for r in coocs:
        a, b, cnt = r["entity_a_id"], r["entity_b_id"], r["news_count"]
        if a not in ids_no_grafo or b not in ids_no_grafo:
            continue
        if a not in entidades or b not in entidades:
            continue
        title = (
            f"{entidades[a]['name']} ↔ {entidades[b]['name']}<br>"
            f"Co-ocorrencias: {cnt}"
        )
        net.add_edge(
            f"e_{a}", f"e_{b}",
            value=cnt,          # controla espessura E força da mola
            title=title,
            color={"color": "#ffffff55"},
        )

    net.save_graph(output)
    return output
