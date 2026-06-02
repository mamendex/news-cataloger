"""
Descoberta ad-hoc de novos temas a partir do corpus de notícias.

Uso:
    python descobrir_temas.py             # analisa news.db, top 20 candidatos
    python descobrir_temas.py --min 3     # exige ao menos 3 artigos por termo
    python descobrir_temas.py --top 30    # mostra 30 candidatos
    python descobrir_temas.py --db PATH   # banco alternativo

Saída:
    - Tabela de candidatos com frequência e artigos de exemplo
    - Snippet Python pronto para colar em config.THEMES
"""

import re
import sys
import math
from collections import Counter, defaultdict
import config
from storage.database import get_conn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


# ── stopwords português ───────────────────────────────────────────────────────
# Lista curada para cobrir o vocabulário típico de notícias em PT-BR.
STOPWORDS = {
    "a","ao","aos","aquela","aquelas","aquele","aqueles","aquilo","as","até",
    "com","como","da","das","de","dela","delas","dele","deles","depois","do",
    "dos","e","é","ela","elas","ele","eles","em","entre","era","eram","essa",
    "essas","esse","esses","esta","estas","este","estes","eu","foi","for",
    "foram","há","isso","isto","já","lhe","lhes","mais","mas","me","mesmo",
    "meu","minha","muito","na","não","nas","nem","no","nos","nós","numa",
    "num","o","os","ou","para","pela","pelas","pelo","pelos","pode","podem",
    "por","qual","quando","que","quem","ser","seu","seus","se","si","sobre",
    "sua","suas","também","te","tem","têm","ter","toda","todas","todo",
    "todos","tu","tudo","um","uma","umas","uns","vos","vós","às","à","mil",
    "vai","via","vez","ser","ter","fazer","dar","ver","querer","ficar","vir",
    "ainda","agora","após","antes","além","bem","certo","durante","então",
    "entre","isso","isto","nada","onde","outros","outra","outro","parte",
    "pois","quanto","seja","sendo","tais","tal","tanto","tendo","tipo",
    "enquanto","entanto","porém","contudo","assim","logo","cerca","frente",
    "junto","dentro","fora","apenas","mesmos","mesmas","desde","até","novo",
    "nova","novos","novas","cada","ontem","hoje","amanhã","ano","anos",
    "mês","meses","dia","dias","semana","semanas","hora","horas","vez","vezes",
    # verbos auxiliares comuns em notícias
    "disse","afirmou","declarou","anunciou","informou","revelou","destacou",
    "explicou","ressaltou","apontou","confirmou","negou","admitiu","pediu",
    "defendeu","criticou","propôs","apresentou","recebeu","realizou","fez",
}

# palavras muito genéricas em notícias que não formam temas sozinhas
IGNORAR = {
    "brasil","brasileiro","brasileira","brasileiros","brasileiras",
    "governo","federal","nacional","municipal","estadual","público","pública",
    "novo","nova","grande","maior","menor","segundo","primeiro","última",
    "real","reais","bilhões","bilhão","milhões","milhão","mil","total",
    "acordo","projeto","programa","plano","medida","lei","decreto","resolução",
    "presidente","ministro","secretário","diretor","gerente","chefe",
    "empresa","empresas","grupo","setor","área","campo","região","estado",
    "país","países","mundo","mercado","sistema","processo","resultado",
    "semana","meses","anos","período","prazo","data","preço","taxa","valor",
    "número","quantidade","percentual","índice","meta","objetivo","impacto",
    # termos de navegação/interface que aparecem em resumos RSS
    "leia","mais","veja","confira","acesse","clique","saiba","entenda",
    "nesta","neste","essa","esse","aqui","link","feiras","nota","texto",
    "artigo","reportagem","matéria","notícia","notícias",
    # dias da semana e temporais que não formam temas
    "segunda","terça","quarta","quinta","sexta","sábado","domingo",
    "feira","semestre","trimestre","bimestre","quinzena",
    # verbos e auxiliares comuns não filtrados pelo STOPWORDS
    "está","estão","será","serão","seria","foram","seria","sendo",
    "deve","devem","pode","podem","precisa","precisam","quer","querem",
    "disse","diz","dizem","afirma","afirmam","desta","deste","desta",
    # geopolíticos genéricos
    "estados","unidos","reino","unido","europa","china","rússia","índia",
    # outras palavras de alta frequência sem valor temático
    "pessoas","caso","casos","forma","formas","parte","partes",
    "ponto","pontos","lado","lados","volta","base","bases",
    "conta","contas","vista","ordem","linha","linhas",
    # cidades e estados usados como contexto, não como tema
    "paulo","janeiro","minas","gerais","brasília","paraná","bahia",
    "carioca","paulista","mineiro","gaúcho",
    # artefatos de RSS/metadados de feed
    "post","appeared","first","infomoney","feed","subscribe","newsletter",
    # nomes próprios frequentes que não formam tema
    "flávio","lula","bolsonaro","trump","donald","biden","musk","elon",
}


def _tokenizar(texto: str) -> list[str]:
    """Tokeniza em palavras minúsculas, remove pontuação e números puros."""
    tokens = re.findall(r'\b[a-záéíóúâêôãõçàü]{4,}\b', texto.lower())
    return [t for t in tokens if t not in STOPWORDS and t not in IGNORAR]


def _bigramas(tokens: list[str]) -> list[str]:
    """Gera bigramas como 'palavra1_palavra2'."""
    return [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens)-1)]


def _keywords_existentes() -> set[str]:
    """Retorna todas as keywords já mapeadas nos temas do config."""
    kws = set()
    for keywords in config.THEMES.values():
        for kw in keywords:
            for token in _tokenizar(kw):
                kws.add(token)
    return kws


def descobrir(db_path: str = config.DB_PATH, min_freq: int = 3, top_n: int = 20):
    """
    Analisa o corpus e retorna candidatos a novos temas.

    Retorna lista de dicts:
      { "termo": str, "freq": int, "exemplos": [titulo, ...], "keywords": [str] }
    """
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT title, summary FROM news"
        ).fetchall()

    if not rows:
        return []

    # frequência de termos e bigramas por artigo
    termo_artigos = defaultdict(set)   # termo → set de índices de artigos
    termo_freq    = Counter()

    for idx, row in enumerate(rows):
        texto  = f"{row['title']} {row['summary'] or ''}"
        tokens = _tokenizar(texto)
        grams  = tokens + _bigramas(tokens)
        for g in grams:
            termo_artigos[g].add(idx)
            termo_freq[g] += 1

    # filtra keywords já conhecidas
    ja_conhecidas = _keywords_existentes()

    # candidatos: termos com frequência >= min_freq, não já mapeados
    candidatos = [
        (termo, freq)
        for termo, freq in termo_freq.most_common(500)
        if freq >= min_freq
        and termo not in ja_conhecidas
        and len(termo_artigos[termo]) >= min_freq
    ]

    # ── clusterização leve por co-ocorrência ─────────────────────────────────
    # Para cada candidato, calcula quais outros candidatos aparecem nos
    # mesmos artigos (Jaccard). Agrupa os mais próximos como keywords do tema.
    top_termos = [t for t, _ in candidatos[:top_n * 4]]

    resultado = []
    usados    = set()

    for termo, freq in candidatos:
        if termo in usados or len(resultado) >= top_n:
            break

        artigos_a  = termo_artigos[termo]
        # busca termos relacionados (Jaccard > 0.2)
        relacionados = []
        for outro in top_termos:
            if outro == termo or outro in usados:
                continue
            artigos_b = termo_artigos[outro]
            intersec  = len(artigos_a & artigos_b)
            uniao     = len(artigos_a | artigos_b)
            jaccard   = intersec / uniao if uniao else 0
            if jaccard >= 0.15:
                relacionados.append((outro, jaccard, termo_freq[outro]))

        # ordena relacionados por frequência e pega os top 8
        relacionados.sort(key=lambda x: x[2], reverse=True)
        keywords = [termo] + [r[0] for r in relacionados[:7]]

        # exemplos de artigos: títulos que contêm o termo
        exemplos = [
            rows[i]["title"]
            for i in sorted(artigos_a)[:3]
        ]

        resultado.append({
            "termo":    termo,
            "freq":     len(artigos_a),
            "keywords": keywords,
            "exemplos": exemplos,
        })
        usados.update(keywords)

    return resultado


def formatar_snippet(candidatos: list[dict]) -> str:
    """Gera o snippet Python para colar em config.THEMES."""
    linhas = ["# ── temas descobertos automaticamente — revise antes de usar ──"]
    for c in candidatos:
        nome   = c["termo"].replace("_", " ")
        kws    = c["keywords"]
        # separa bigramas e unigramas, formata bonito
        items  = ', '.join(f'"{k.replace("_", " ")}"' for k in kws)
        linhas.append(f'    "{nome}": [{items}],')
    return "\n".join(linhas)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse():
    args   = sys.argv[1:]
    db     = config.DB_PATH
    min_f  = 3
    top_n  = 20
    if "--db"  in args: db    = args[args.index("--db")  + 1]
    if "--min" in args: min_f = int(args[args.index("--min") + 1])
    if "--top" in args: top_n = int(args[args.index("--top") + 1])
    return db, min_f, top_n


if __name__ == "__main__":
    db, min_freq, top_n = _parse()

    print(f"Analisando '{db}' (min_freq={min_freq}, top={top_n})...\n")
    candidatos = descobrir(db, min_freq=min_freq, top_n=top_n)

    if not candidatos:
        print("Nenhum candidato encontrado. Tente reduzir --min.")
        sys.exit(0)

    # ── tabela de candidatos ──────────────────────────────────────────────────
    print(f"{'#':<3} {'Tema candidato':<25} {'Artigos':>7}  Keywords")
    print(f"{'-'*3} {'-'*25} {'-'*7}  {'-'*40}")
    for i, c in enumerate(candidatos, 1):
        nome = c["termo"].replace("_", " ")
        kws  = ", ".join(k.replace("_", " ") for k in c["keywords"][:5])
        print(f"{i:<3} {nome:<25} {c['freq']:>7}  {kws}")

    # ── exemplos por candidato ────────────────────────────────────────────────
    print("\n-- Exemplos de artigos por candidato ----------------------------")
    for c in candidatos:
        nome = c["termo"].replace("_", " ")
        print(f"\n  [{nome}]")
        for ex in c["exemplos"]:
            print(f"    * {ex[:75]}")

    # ── snippet para config.py ────────────────────────────────────────────────
    print("\n-- Snippet para config.THEMES -----------------------------------")
    print(formatar_snippet(candidatos))
