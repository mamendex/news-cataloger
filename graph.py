"""Geração de grafos interativos com pyvis.

Responsabilidade única: consultar o banco, montar o grafo e salvar em HTML.
Sem parsing de argumentos — isso fica em news.py.

Dois modos:
  gerar_grafo()              — entidades + co-ocorrências
  gerar_grafo(temas=True)    — idem + nós de tema ligados às entidades

Ao clicar numa aresta, um painel lateral exibe as notícias que mencionam
ambas as entidades da aresta — com link clicável para cada artigo.
"""
import json
import math
import config
from storage.database import get_conn


# ── paleta de cores por tema ──────────────────────────────────────────────────
TEMA_CORES = {
    "economia":    "#2196F3",
    "tecnologia":  "#9C27B0",
    "política":    "#F44336",
    "saúde":       "#4CAF50",
    "energia":     "#FF9800",
    "agronegócio": "#795548",
    "geral":       "#9E9E9E",
}
COR_ENTIDADE_SEM_TEMA = "#607D8B"
COR_TEMA_NO           = "#FFD700"


def _cor_tema(nome: str) -> str:
    return TEMA_CORES.get(nome, "#E91E63")


def _escala_no(count: int, max_count: int, min_size=12, max_size=60) -> int:
    if max_count <= 1:
        return min_size
    ratio = math.log1p(count) / math.log1p(max_count)
    return int(min_size + ratio * (max_size - min_size))


# ── JavaScript injetado no HTML ───────────────────────────────────────────────
# Escuta o evento selectEdge do vis.js, busca as notícias do par no dict
# embutido e renderiza o painel lateral.

_PAINEL_JS = """
<style>
  #news-panel {
    position: fixed; top: 0; right: 0; width: 360px; height: 100%;
    background: #12122a; color: #eee; overflow-y: auto;
    border-left: 2px solid #444; padding: 16px; box-sizing: border-box;
    display: none; z-index: 1000; font-family: sans-serif;
  }
  #news-panel h2 { font-size: 14px; color: #adf; margin: 0 0 12px; }
  #news-panel .close-btn {
    position: absolute; top: 12px; right: 14px; cursor: pointer;
    font-size: 18px; color: #aaa;
  }
  #news-panel ul { list-style: none; padding: 0; margin: 0; }
  #news-panel li { margin-bottom: 10px; border-bottom: 1px solid #333; padding-bottom: 10px; }
  #news-panel a {
    color: #7cf; text-decoration: none; font-size: 13px; line-height: 1.4;
  }
  #news-panel a:hover { text-decoration: underline; }
  #news-panel .meta { font-size: 11px; color: #888; margin-top: 3px; }
  #news-panel .empty { color: #888; font-style: italic; font-size: 13px; }
</style>

<div id="news-panel">
  <span class="close-btn" onclick="document.getElementById('news-panel').style.display='none'">&#x2715;</span>
  <h2 id="panel-title">Noticias</h2>
  <ul id="panel-list"></ul>
</div>

<script>
// dict embutido: chave = "eA_eB" (ids ordenados), valor = [{title, url, date, source}]
const edgeNews = EDGE_NEWS_JSON;

function mostrarPainel(edgeKey) {
  const noticias = edgeNews[edgeKey] || [];
  const panel = document.getElementById('news-panel');
  const list  = document.getElementById('panel-list');
  const title = document.getElementById('panel-title');

  // label dos nos para o titulo
  const parts = edgeKey.split('_');
  const nomeA = nodeLabels[parts[0] + '_' + parts[1]] || parts[0];
  const nomeB = nodeLabels[parts[2] + '_' + parts[3]] || parts[2];
  title.textContent = nomeA + '  ↔  ' + nomeB;

  list.innerHTML = '';
  if (noticias.length === 0) {
    list.innerHTML = '<li><span class="empty">Nenhuma noticia encontrada.</span></li>';
  } else {
    noticias.forEach(function(n) {
      const li = document.createElement('li');
      li.innerHTML =
        '<a href="' + n.url + '" target="_blank">' + n.title + '</a>' +
        '<div class="meta">' + (n.date || '') + (n.source ? ' &bull; ' + n.source : '') + '</div>';
      list.appendChild(li);
    });
  }
  panel.style.display = 'block';
}

// aguarda o network do vis.js estar disponível
function registrarEventos() {
  if (typeof network === 'undefined') { setTimeout(registrarEventos, 300); return; }
  network.on('selectEdge', function(params) {
    if (params.edges.length === 0) return;
    const edgeId = params.edges[0];
    mostrarPainel(edgeId);
  });
  network.on('deselectEdge', function() {
    document.getElementById('news-panel').style.display = 'none';
  });
}
registrarEventos();
</script>
"""

# dict auxiliar de labels dos nós (preenchido no momento da geração)
_LABELS_JS = """
<script>
const nodeLabels = NODE_LABELS_JSON;
</script>
"""


def _query_noticias_par(conn, a_id: int, b_id: int, limit: int = 15) -> list[dict]:
    """Retorna notícias que mencionam ambas as entidades a_id e b_id."""
    rows = conn.execute("""
        SELECT n.title, n.url, n.published_at, n.source
        FROM news n
        JOIN news_companies nc1 ON nc1.news_id = n.id AND nc1.company_id = ?
        JOIN news_companies nc2 ON nc2.news_id = n.id AND nc2.company_id = ?
        ORDER BY n.published_at DESC
        LIMIT ?
    """, (a_id, b_id, limit)).fetchall()
    return [
        {"title": r["title"], "url": r["url"],
         "date": (r["published_at"] or "")[:10], "source": r["source"] or ""}
        for r in rows
    ]


def _injetar_painel(html: str, edge_news: dict, node_labels: dict) -> str:
    """Insere o painel lateral e os dados JSON no HTML gerado pelo pyvis."""
    edge_news_json   = json.dumps(edge_news,   ensure_ascii=False)
    node_labels_json = json.dumps(node_labels, ensure_ascii=False)

    painel = _PAINEL_JS.replace("EDGE_NEWS_JSON", edge_news_json)
    labels = _LABELS_JS.replace("NODE_LABELS_JSON", node_labels_json)

    # injeta antes do </body>
    return html.replace("</body>", labels + painel + "</body>")


def gerar_grafo(
    db_path:       str  = config.DB_PATH,
    min_cooc:      int  = 2,
    incluir_temas: bool = False,
    output:        str  = "grafo.html",
) -> str:
    """Gera o grafo interativo e salva em `output`. Retorna o caminho do arquivo."""
    try:
        from pyvis.network import Network
    except ImportError:
        raise RuntimeError("pyvis não instalado. Execute: pip install pyvis")

    with get_conn(db_path) as conn:

        entidades = {
            r["id"]: {"name": r["name"], "news_count": r["news_count"]}
            for r in conn.execute("""
                SELECT c.id, c.name, COUNT(DISTINCT nc.news_id) AS news_count
                FROM companies c
                JOIN news_companies nc ON nc.company_id = c.id
                GROUP BY c.id
            """).fetchall()
        }

        coocs = conn.execute("""
            SELECT entity_a_id, entity_b_id, news_count
            FROM entity_cooccurrence
            WHERE news_count >= ?
            ORDER BY news_count DESC
        """, (min_cooc,)).fetchall()

        ids_no_grafo = set()
        for r in coocs:
            ids_no_grafo.add(r["entity_a_id"])
            ids_no_grafo.add(r["entity_b_id"])

        tema_dominante = {}
        for r in conn.execute("""
            SELECT nc.company_id, t.name, COUNT(*) AS cnt
            FROM news_companies nc
            JOIN news_themes nt ON nt.news_id = nc.news_id
            JOIN themes t ON t.id = nt.theme_id
            GROUP BY nc.company_id, t.name
            ORDER BY nc.company_id, cnt DESC
        """).fetchall():
            if r["company_id"] not in tema_dominante:
                tema_dominante[r["company_id"]] = r["name"]

        temas = {}
        entidade_temas = {}
        if incluir_temas:
            for r in conn.execute("""
                SELECT t.id, t.name, COUNT(DISTINCT nt.news_id) AS news_count
                FROM themes t JOIN news_themes nt ON nt.theme_id = t.id
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

        # ── pré-carrega notícias por par de entidades ─────────────────────────
        # chave do dict: "e_A_e_B" (mesma ordem do id da aresta no vis.js)
        edge_news = {}
        for r in coocs:
            a, b = r["entity_a_id"], r["entity_b_id"]
            if a not in ids_no_grafo or b not in ids_no_grafo:
                continue
            key = f"e_{a}_e_{b}"
            edge_news[key] = _query_noticias_par(conn, a, b)

    if not ids_no_grafo:
        raise ValueError(
            f"Nenhuma co-ocorrência com min_cooc >= {min_cooc}. "
            "Execute o coordinator para popular o banco ou reduza --min."
        )

    net = Network(
        height="95vh", width="100%",
        bgcolor="#1a1a2e",
        font_color="#ffffff",
        notebook=False,
    )

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
      "nodes": { "font": { "size": 13 }, "borderWidth": 2 },
      "interaction": { "hover": true, "tooltipDelay": 100 }
    }
    """)

    max_count = max((e["news_count"] for e in entidades.values()), default=1)
    node_labels = {}  # id_vis → label — usado pelo JS do painel

    for eid in ids_no_grafo:
        if eid not in entidades:
            continue
        e     = entidades[eid]
        tema  = tema_dominante.get(eid)
        cor   = _cor_tema(tema) if tema else COR_ENTIDADE_SEM_TEMA
        size  = _escala_no(e["news_count"], max_count)
        title = (
            f"<b>{e['name']}</b><br>"
            f"Noticias: {e['news_count']}<br>"
            f"Tema principal: {tema or '-'}"
        )
        node_id = f"e_{eid}"
        net.add_node(node_id, label=e["name"], size=size, color=cor,
                     title=title, shape="dot")
        node_labels[node_id] = e["name"]

    if incluir_temas:
        for tid, t in temas.items():
            size  = _escala_no(t["news_count"], max_count, min_size=20, max_size=50)
            title = f"<b>TEMA: {t['name']}</b><br>Noticias: {t['news_count']}"
            node_id = f"t_{tid}"
            net.add_node(node_id, label=t["name"].upper(), size=size,
                         color=COR_TEMA_NO, title=title, shape="diamond")
            node_labels[node_id] = t["name"]
        for eid, tema_ids in entidade_temas.items():
            for tid in tema_ids:
                if f"e_{eid}" in [n["id"] for n in net.nodes] and tid in temas:
                    net.add_edge(f"e_{eid}", f"t_{tid}", value=1,
                                 color={"color": "#ffffff22"}, dashes=True)

    for r in coocs:
        a, b, cnt = r["entity_a_id"], r["entity_b_id"], r["news_count"]
        if a not in ids_no_grafo or b not in ids_no_grafo:
            continue
        if a not in entidades or b not in entidades:
            continue
        title = (
            f"{entidades[a]['name']} &#x2194; {entidades[b]['name']}<br>"
            f"Co-ocorrencias: {cnt}<br>"
            f"<i>Clique para ver as noticias</i>"
        )
        # id da aresta = "e_A_e_B" — deve bater com a chave do edge_news
        net.add_edge(
            f"e_{a}", f"e_{b}",
            value=cnt,
            title=title,
            color={"color": "#ffffff55"},
        )

    # salva HTML base e injeta painel
    net.save_graph(output)
    with open(output, encoding="utf-8") as f:
        html = f.read()
    html = _injetar_painel(html, edge_news, node_labels)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)

    return output
