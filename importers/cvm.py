"""Importador de companhias abertas da CVM (Comissão de Valores Mobiliários).

Fonte: https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv
Atualização: diária (último dia útil).

Colunas utilizadas:
  CNPJ          — CNPJ da companhia (14 dígitos sem formatação)
  DENOM_SOCIAL  — Razão social (nome legal completo)
  DENOM_COMERC  — Nome comercial / nome fantasia (pode ser vazio)
  SIT_REG       — Situação do registro: ATIVO, CANCELADO, SUSPENSO...

Estratégia de canonicalização:
  - Nome canônico = DENOM_COMERC se preenchido, senão DENOM_SOCIAL
  - DENOM_SOCIAL vira alias seguro quando diferente do canônico
  - CNPJ formatado (XX.XXX.XXX/XXXX-XX) vira alias seguro adicional
"""

import csv
import io
import os
import urllib.request
import urllib.error
from typing import Optional

import config
from storage.database import upsert_company_with_cnpj, get_conn

CVM_CSV_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
CVM_ENCODING = "latin-1"   # encoding padrão dos arquivos CVM
CVM_SEPARATOR = ";"

SITUACOES_ATIVAS = {"ATIVO"}


def _format_cnpj(raw: str) -> str:
    """Formata CNPJ de '00000000000000' para 'XX.XXX.XXX/XXXX-XX'."""
    d = "".join(c for c in raw if c.isdigit())
    if len(d) != 14:
        return raw
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


def _canonical_name(denom_comerc: str, denom_social: str) -> str:
    """Retorna o nome mais adequado para uso em notícias."""
    name = denom_comerc.strip() if denom_comerc else ""
    return name if name else denom_social.strip()


def fetch_csv(url: str = CVM_CSV_URL, timeout: int = 30) -> io.TextIOWrapper:
    """Baixa o CSV da CVM e retorna um objeto iterável de texto.
    Lança urllib.error.URLError em caso de falha de rede."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "news-cataloger/1.0 (dados abertos CVM)"},
    )
    response = urllib.request.urlopen(req, timeout=timeout)
    return io.TextIOWrapper(response, encoding=CVM_ENCODING, errors="replace")


def parse_csv(fileobj, debug: bool = False) -> list[dict]:
    """Lê o CSV e retorna lista de dicts com os campos relevantes.
    Filtra apenas registros com SIT_REG em SITUACOES_ATIVAS."""
    reader = csv.DictReader(fileobj, delimiter=CVM_SEPARATOR)
    companies = []
    sit_values_seen: set[str] = set()

    for i, row in enumerate(reader):
        if debug and i == 0:
            print(f"[cvm:debug] colunas detectadas: {list(row.keys())}")

        sit = row.get("SIT_REG", "").strip().upper()
        sit_values_seen.add(sit)

        if sit not in SITUACOES_ATIVAS:
            continue
        cnpj_raw  = row.get("CNPJ", "").strip()
        social    = row.get("DENOM_SOCIAL", "").strip()
        comercial = row.get("DENOM_COMERC", "").strip()
        if not social:
            continue
        companies.append({
            "cnpj":          cnpj_raw,
            "denom_social":  social,
            "denom_comerc":  comercial,
        })

    if debug or len(companies) == 0:
        print(f"[cvm:debug] valores únicos de SIT_REG encontrados: {sorted(sit_values_seen)}")

    return companies


def import_into_db(
    companies: list[dict],
    db_path: str = config.DB_PATH,
    verbose: bool = False,
) -> dict:
    """Insere/atualiza empresas no banco. Retorna estatísticas da importação."""
    inserted = updated = skipped = 0

    for c in companies:
        social    = c["denom_social"]
        comercial = c["denom_comerc"]
        cnpj_raw  = c["cnpj"]
        cnpj_fmt  = _format_cnpj(cnpj_raw) if cnpj_raw else None

        canonical = _canonical_name(comercial, social)
        if not canonical:
            skipped += 1
            continue

        company_id = upsert_company_with_cnpj(
            name=canonical,
            cnpj=cnpj_raw if cnpj_raw else None,
            source="cvm",
            db_path=db_path,
        )

        # adiciona aliases: razão social e CNPJ formatado
        aliases_to_add = []
        if social and social != canonical:
            aliases_to_add.append(social)
        if cnpj_fmt and cnpj_fmt != canonical:
            aliases_to_add.append(cnpj_fmt)

        if aliases_to_add:
            with get_conn(db_path) as conn:
                for alias in aliases_to_add:
                    conn.execute(
                        "INSERT OR IGNORE INTO company_aliases (alias, company_id, is_safe) VALUES (?, ?, 1)",
                        (alias, company_id),
                    )

        if verbose:
            print(f"  [CVM] {canonical}" + (f" ({cnpj_fmt})" if cnpj_fmt else ""))

        inserted += 1

    return {"inserted": inserted, "skipped": skipped}


def run(
    db_path: str = config.DB_PATH,
    url: str = CVM_CSV_URL,
    local_file: Optional[str] = None,
    verbose: bool = False,
    debug: bool = False,
) -> dict:
    """Ponto de entrada principal.

    Se local_file for fornecido, usa esse arquivo em vez de fazer o download.
    Útil para ambientes sem acesso à internet ou para testes.
    """
    if local_file:
        if not os.path.exists(local_file):
            raise FileNotFoundError(f"Arquivo local não encontrado: {local_file}")
        print(f"[cvm] lendo arquivo local: {local_file}")
        with open(local_file, encoding=CVM_ENCODING, errors="replace") as f:
            companies = parse_csv(f, debug=debug)
    else:
        print(f"[cvm] baixando: {url}")
        try:
            fileobj = fetch_csv(url)
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Falha ao baixar dados da CVM: {e}\n"
                "Dica: baixe o arquivo manualmente e use --file <caminho>."
            ) from e
        companies = parse_csv(fileobj, debug=debug)

    print(f"[cvm] {len(companies)} companhias ativas encontradas")
    stats = import_into_db(companies, db_path=db_path, verbose=verbose)
    print(f"[cvm] importação concluída — {stats['inserted']} inseridas/atualizadas, "
          f"{stats['skipped']} ignoradas")
    return stats
