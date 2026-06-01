# Arquivo com a lista de feeds RSS — um por linha, # para comentários.
# O banco é populado a partir deste arquivo na primeira execução (init_db).
FEEDS_FILE = "feeds.txt"

# Each theme maps to keywords used for classification
THEMES = {
    "economia": [
        "inflação", "pib", "juros", "selic", "dólar", "câmbio", "fiscal",
        "economia", "mercado", "bolsa", "investimento", "recessão", "crescimento",
        "gdp", "inflation", "interest rate", "market", "stock",
    ],
    "tecnologia": [
        "tecnologia", "inteligência artificial", "ia", "software", "startup",
        "inovação", "digital", "dados", "cloud", "cyber", "tech", "ai",
        "artificial intelligence", "machine learning", "blockchain",
    ],
    "política": [
        "governo", "presidente", "congresso", "senado", "câmara", "eleição",
        "partido", "ministro", "política", "lei", "voto", "parlamento",
        "government", "election", "parliament", "minister", "policy",
    ],
    "saúde": [
        "saúde", "hospital", "medicina", "vacina", "doença", "pandemia",
        "sus", "anvisa", "remédio", "tratamento", "paciente",
        "health", "vaccine", "disease", "pandemic", "treatment",
    ],
    "energia": [
        "petróleo", "energia", "petrobras", "gás", "renovável", "solar",
        "eólica", "combustível", "eletricidade", "carbono", "emissão",
        "oil", "energy", "fuel", "renewable", "electricity", "carbon",
    ],
    "agronegócio": [
        "agro", "soja", "milho", "café", "bovino", "exportação agrícola",
        "safra", "fazenda", "pecuária", "commodities", "grão",
        "soybean", "corn", "agriculture", "harvest", "livestock",
    ],
}

SPACY_MODEL = "pt_core_news_sm"
DB_PATH = "news.db"

# ── Extractor: camada 1 — gazetteer ──────────────────────────────────────────
# Lista semente de empresas conhecidas. Em produção, substituir / complementar
# com a base completa de CNPJs da Receita Federal (1-2M de entradas).
# O Aho-Corasick constrói o índice uma única vez e busca todas em O(n) no texto.
COMPANY_GAZETTEER = [
    "Petrobras", "Vale", "Embraer", "Ambev", "Itaú", "Bradesco", "Santander",
    "Nubank", "Magazine Luiza", "Magalu", "Natura", "Gerdau", "Suzano",
    "JBS", "BRF", "Marfrig", "Minerva", "Totvs", "Localiza", "Weg",
    "Banco do Brasil", "Caixa Econômica Federal", "BTG Pactual", "XP Inc",
    "Hapvida", "Fleury", "Dasa", "Grupo Boticário", "Arezzo", "Raia Drogasil",
    "Lojas Renner", "Grupo Carrefour Brasil", "GPA", "Assaí", "Atacadão",
    "Eletrobras", "Cemig", "Copel", "Light", "Engie", "EDP", "CPFL",
    "TIM", "Claro", "Vivo", "Oi", "Algar Telecom",
    "Azul", "Gol", "Latam",
]

# ── Extractor: camada 2 — sufixos jurídicos ──────────────────────────────────
# Sufixos que, quando encontrados, indicam que a palavra/expressão anterior
# é um nome de empresa. Usados em regex sobre o texto bruto.
COMPANY_LEGAL_SUFFIXES = [
    r"S\.A\.", r"S/A", r"Ltda\.?", r"LTDA\.?",
    r"ME", r"EPP", r"EIRELI", r"S\.A",
    r"Holdings?", r"Participações", r"Empreendimentos",
    r"Investimentos", r"Tecnologia", r"Soluções",
    r"Group", r"Grupo",
]

# Frases que precedem ou seguem um nome de empresa no texto
COMPANY_CONTEXT_PATTERNS = [
    r'(?:presidente|vice-presidente|diretor|CEO|CFO|CTO|COO|fundador|sócio)\s+d[aoe]\s+((?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]*\s*){1,5})',
    r'(?:empresa|companhia|grupo|holding|startup|corporação)\s+((?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]*\s*){1,4})',
    r'((?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wáéíóúâêôãõç]*\s*){1,5})\s+(?:anunciou|informou|divulgou|reportou|registrou)',
]

# ── Extractor: camada 3 — filtros do NER (fallback) ──────────────────────────
# Termos que o spaCy classifica erroneamente como ORG — geográficos, siglas
# fiscais, expressões genéricas. Acrescentar conforme novos falsos positivos.
COMPANY_BLOCKLIST = {
    # geográficos
    "Oriente Médio", "América Latina", "União Europeia", "Mercosul",
    "Estados Unidos", "América do Norte", "Ásia", "Europa", "África",
    # siglas fiscais / tributárias
    "IR", "DIRF", "IRPF", "IRPJ", "CSLL", "PIS", "COFINS", "ICMS",
    "IOF", "IPI", "ISS", "FGTS", "INSS", "CPF", "CNPJ",
    # siglas institucionais genéricas
    "ONU", "FMI", "OCDE", "OMC", "OMS", "PIB", "IGP", "IPCA", "INPC",
    # expressões comuns classificadas como ORG pelo modelo pequeno
    "Federal", "Nacional", "Municipal", "Estadual", "Central",
}

# Siglas curtas (≤4 chars, all-caps) que SÃO empresas legítimas
COMPANY_ACRONYM_WHITELIST = {
    "TIM", "OI", "GPA", "WEG", "EDP", "BRF", "JBS", "GOL", "XP",
    "BTG", "CSN", "CVC", "MRV", "PDG", "CCR", "CPQ",
}

# ── Aliases / sinônimos de empresas ──────────────────────────────────────────
# Cada entrada mapeia um nome canônico para suas variações.
#
# "aliases"  — seguros: qualquer ocorrência no texto é resolvida para o canônico.
# "unsafe"   — ambíguos: só resolvidos quando aparecem junto de outra palavra
#              capitalizada (ex: "Receita" sozinha é vaga; "Receita Federal" não).
#
# Regra geral: se a forma abreviada pode significar outra coisa em contexto
# diferente, coloque em "unsafe". Em caso de dúvida, prefira "unsafe".
COMPANY_ALIASES: dict[str, dict] = {
    "Receita Federal": {
        "aliases": ["Receita Federal Brasileira", "RFB"],
        "unsafe":  ["Receita"],          # "Receita" sozinha é vaga demais
    },
    "Fundo Monetário Internacional": {
        "aliases": ["FMI", "Fundo Monetário Internacional"],
        "unsafe":  ["Fundo Monetário"],  # específico o suficiente, mas multi-palavra
    },
    "B3": {
        "aliases": [
            "B3 S.A.", "Bolsa de Valores", "Bolsa Brasileira",
            "Brasil Bolsa Balcão",
        ],
    },
    "JBS": {
        "aliases": ["Grupo JBS", "JBS S.A.", "JBS Foods"],
    },
    "Petrobras": {
        "aliases": ["Petróleo Brasileiro", "Petrobras S.A.", "PETR"],
    },
    "Banco do Brasil": {
        "aliases": ["BB S.A.", "Banco do Brasil S.A."],
        "unsafe":  ["BB"],               # "BB" pode ser abreviação de outras coisas
    },
    "Banco Central": {
        "aliases": ["Banco Central do Brasil", "BCB"],
        "unsafe":  ["BC"],
    },
    "Caixa Econômica Federal": {
        "aliases": ["Caixa Econômica", "CEF"],
        "unsafe":  ["Caixa"],            # "Caixa" sozinha é ambígua
    },
}
