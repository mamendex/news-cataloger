# news-cataloger

Sistema de catalogação de notícias via RSS com extração de entidades e grafo de co-ocorrência.

## Estrutura

```
news-cataloger/
├── coordinator.py          # pipeline: reader/scraper → classifier → extractor → storage
├── news.py                 # CLI (interface de linha de comando)
├── reports.py              # funções de consulta e exibição (importável)
├── graph.py                # geração de grafo interativo HTML (pyvis)
├── config.py               # configurações: temas, gazetteer, aliases, blocklist
├── feeds.txt               # lista de feeds RSS (um por linha, # para comentários)
├── setup.py                # instala dependências e modelo spaCy
├── test.py                 # suite de testes
├── benchmark.py            # teste de carga: dedup + descoberta de temas em escala
├── requirements.txt        # dependências pip
├── descobrir_temas.py      # descoberta de temas via Python (fallback)
├── descobrir_temas_sql.py  # descoberta de temas via FTS5 — versão principal
├── agents/
│   ├── reader.py           # busca artigos via RSS (feedparser)
│   ├── classifier.py       # classifica temas por keywords
│   ├── extractor.py        # extrai empresas — pipeline 3 camadas:
│   │                       #   1. Aho-Corasick (gazetteer)
│   │                       #   2. Regex (sufixos jurídicos + frases contextuais)
│   │                       #   3. spaCy NER (fallback, só ORG)
│   └── scraper.py          # scrapers HTML para sites sem RSS (BNDES, etc.)
└── storage/
    ├── database.py         # SQLite: schema, CRUD, aliases, co-ocorrência, feeds, FTS5
    └── dedup.py            # fingerprint MD5 para deduplicação de conteúdo
```

## Setup

```bash
python setup.py          # instala dependências + modelo spaCy pt_core_news_sm
```

## Uso

```bash
python news.py coletar              # busca notícias dos feeds ativos e popula o banco

python news.py resumo               # totais gerais
python news.py feeds                # lista feeds cadastrados
python news.py temas                # notícias por tema
python news.py empresas             # empresas por tema
python news.py por-empresa          # notícias por empresa
python news.py suspeitas            # empresas curtas sem alias (falsos positivos)
python news.py pares                # co-ocorrências ranqueadas por PMI
python news.py vizinhanca Petrobras # grafo de 2 graus ao redor de uma entidade
python news.py descobrir-temas      # candidatos a novos temas (via FTS5)
python news.py tudo                 # relatório completo

python news.py grafo                # gera grafo.html interativo
python news.py grafo --temas        # inclui nós de tema no grafo

python news.py feed-add <url>                    # adiciona feed RSS
python news.py feed-add <url> --scraper <id>     # adiciona site via scraper HTML
python news.py feed-off <id|trecho>              # desativa feed

python test.py                      # roda todos os testes
python benchmark.py --n 10000       # teste de carga com 10k artigos sintéticos
```

## Schema do banco (news.db)

- `feeds` — feeds RSS e scrapers com flag active, type (rss/scraper), scraper id
- `news` — artigos coletados; `content_hash` para dedup de conteúdo
- `news_fts` — índice FTS5 espelhando title+summary (tokenizador unicode61)
- `themes` — temas (economia, tecnologia, política…)
- `companies` — entidades extraídas (nome canônico)
- `company_aliases` — sinônimos/apelidos com flag is_safe
- `news_themes` — vínculo notícia ↔ tema
- `news_companies` — vínculo notícia ↔ empresa
- `entity_cooccurrence` — pares de entidades co-mencionadas com contagem e PMI

## Configuração

- **Temas e keywords:** `config.py` → `THEMES`
- **Gazetteer (camada 1):** `config.py` → `COMPANY_GAZETTEER`
- **Aliases:** `config.py` → `COMPANY_ALIASES`
- **Blocklist:** `config.py` → `COMPANY_BLOCKLIST`
- **Feeds RSS:** `feeds.txt`

## Decisões de design relevantes

- Aliases com `is_safe=False` só resolvem quando acompanhados de contexto (ex: "Receita" sozinha não resolve, "Receita Federal" sim)
- Co-ocorrência normalizada: par (A,B) e (B,A) são o mesmo registro (entity_a_id < entity_b_id sempre)
- PMI desconta entidades que aparecem em muitas notícias independentemente
- `reports.py` não tem sys.exit nem arg parsing — `news.py` é a única interface
