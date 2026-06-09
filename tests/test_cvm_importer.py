"""Testes do importador CVM (importers/cvm.py).

Usa CSV mockado em memória — sem dependência de rede.
Cobre: parsing, filtro de situação, canonicalização, aliases, CNPJ, idempotência.
"""
import sys
import os
import io
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(ok, fail):
    from importers.cvm import parse_csv, import_into_db, _format_cnpj, _canonical_name, CVM_SEPARATOR, CVM_ENCODING
    from storage.database import init_db, get_conn

    # ── _format_cnpj ─────────────────────────────────────────────────────────
    if _format_cnpj("00000000000191") == "00.000.000/0001-91":
        ok("cvm: _format_cnpj formata CNPJ corretamente")
    else:
        fail("cvm: _format_cnpj", _format_cnpj("00000000000191"))

    if _format_cnpj("invalido") == "invalido":
        ok("cvm: _format_cnpj devolve original se invalido")
    else:
        fail("cvm: _format_cnpj invalido")

    # ── _canonical_name ───────────────────────────────────────────────────────
    if _canonical_name("Petrobras", "Petroleo Brasileiro S.A.") == "Petrobras":
        ok("cvm: _canonical_name prefere nome comercial")
    else:
        fail("cvm: _canonical_name prefere nome comercial")

    if _canonical_name("", "Petroleo Brasileiro S.A.") == "Petroleo Brasileiro S.A.":
        ok("cvm: _canonical_name usa social quando comercial vazio")
    else:
        fail("cvm: _canonical_name usa social quando comercial vazio")

    # ── parse_csv ─────────────────────────────────────────────────────────────
    csv_content = (
        "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;SIT\n"
        "33000167000101;PETROLEO BRASILEIRO S.A. PETROBRAS;Petrobras;A\n"
        "60872504000123;BANCO BRADESCO S.A.;Bradesco;A\n"
        "12345678000100;EMPRESA CANCELADA LTDA;;C\n"
        "98765432000100;SEM NOME COMERCIAL S.A.;;A\n"
    )
    fileobj = io.StringIO(csv_content)
    companies = parse_csv(fileobj)

    if len(companies) == 3:
        ok("cvm: parse_csv retorna apenas registros ATIVO")
    else:
        fail("cvm: parse_csv filtro ATIVO", f"esperado 3, got {len(companies)}")

    petrobras = next((c for c in companies if "PETROBRAS" in c["denom_social"]), None)
    if petrobras and petrobras["denom_comerc"] == "Petrobras":
        ok("cvm: parse_csv preserva nome comercial")
    else:
        fail("cvm: parse_csv preserva nome comercial", str(petrobras))

    sem_comercial = next((c for c in companies if "SEM NOME" in c["denom_social"]), None)
    if sem_comercial and sem_comercial["denom_comerc"] == "":
        ok("cvm: parse_csv preserva nome comercial vazio")
    else:
        fail("cvm: parse_csv nome comercial vazio", str(sem_comercial))

    # ── import_into_db ────────────────────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        init_db(db)
        stats = import_into_db(companies, db_path=db)

        if stats["inserted"] == 3:
            ok("cvm: import_into_db insere 3 empresas ativas")
        else:
            fail("cvm: import_into_db contagem", str(stats))

        # verifica nome canônico
        with get_conn(db) as conn:
            row = conn.execute("SELECT name, cnpj, source FROM companies WHERE name = 'Petrobras'").fetchone()
        if row and row["cnpj"] == "33000167000101" and row["source"] == "cvm":
            ok("cvm: empresa salva com cnpj e source corretos")
        else:
            fail("cvm: cnpj/source", str(dict(row) if row else None))

        # verifica alias: razão social vira alias seguro
        with get_conn(db) as conn:
            alias = conn.execute(
                "SELECT ca.alias, ca.is_safe FROM company_aliases ca "
                "JOIN companies c ON c.id = ca.company_id WHERE c.name = 'Petrobras'"
            ).fetchall()
        alias_texts = [a["alias"] for a in alias]
        if "PETROLEO BRASILEIRO S.A. PETROBRAS" in alias_texts:
            ok("cvm: razao social inserida como alias")
        else:
            fail("cvm: razao social como alias", str(alias_texts))

        # verifica alias: CNPJ formatado
        if any("33.000.167/0001-01" in a for a in alias_texts):
            ok("cvm: CNPJ formatado inserido como alias")
        else:
            fail("cvm: CNPJ formatado como alias", str(alias_texts))

        # empresa sem nome comercial usa razão social como canônico, sem alias duplicado
        with get_conn(db) as conn:
            row2 = conn.execute(
                "SELECT id FROM companies WHERE name = 'SEM NOME COMERCIAL S.A.'"
            ).fetchone()
        if row2:
            ok("cvm: empresa sem nome comercial usa razao social como canonico")
        else:
            fail("cvm: empresa sem nome comercial")

        # idempotência: segunda importação não duplica
        stats2 = import_into_db(companies, db_path=db)
        with get_conn(db) as conn:
            total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        # o total pode incluir empresas de config (aliases), mas não deve ter duplicatas da CVM
        with get_conn(db) as conn:
            cvm_total = conn.execute(
                "SELECT COUNT(*) FROM companies WHERE source = 'cvm'"
            ).fetchone()[0]
        if cvm_total == 3:
            ok("cvm: import_into_db e idempotente (sem duplicatas na segunda rodada)")
        else:
            fail("cvm: idempotencia", f"esperado 3 cvm, got {cvm_total}")

    finally:
        os.unlink(db)


if __name__ == "__main__":
    passed = failed = 0

    def ok(desc):
        global passed; passed += 1; print(f"[OK] {desc}")

    def fail(desc, reason=""):
        global failed; failed += 1
        print(f"[FAIL] {desc}" + (f" — {reason}" if reason else ""))

    run(ok, fail)
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
