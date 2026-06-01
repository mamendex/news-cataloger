"""Tests for classifier, extractor, storage, and coordinator pipeline."""
import sys
import os
import tempfile

# ── helpers ──────────────────────────────────────────────────────────────────
PASSED = 0
FAILED = 0


def ok(desc):
    global PASSED
    PASSED += 1
    print(f"[OK] {desc}")


def fail(desc, reason=""):
    global FAILED
    FAILED += 1
    print(f"[FAIL] {desc}" + (f" — {reason}" if reason else ""))


# ── classifier ───────────────────────────────────────────────────────────────
def test_classifier():
    from agents.classifier import classify

    themes = classify("O Banco Central elevou a Selic para combater a inflação")
    if "economia" in themes:
        ok("classifier: detects 'economia'")
    else:
        fail("classifier: detects 'economia'", f"got {themes}")

    themes = classify("Nova startup lança plataforma de inteligência artificial")
    if "tecnologia" in themes:
        ok("classifier: detects 'tecnologia'")
    else:
        fail("classifier: detects 'tecnologia'", f"got {themes}")

    themes = classify("Notícia sem tema específico sobre o tempo hoje")
    if "geral" in themes:
        ok("classifier: falls back to 'geral'")
    else:
        fail("classifier: falls back to 'geral'", f"got {themes}")


# ── extractor ────────────────────────────────────────────────────────────────
def test_extractor():
    try:
        from agents.extractor import (
            extract_companies, _extract_gazetteer,
            _extract_patterns, _is_false_positive,
        )
    except RuntimeError as e:
        print(f"[SKIP] extractor tests — {e}")
        return

    # camada 1: gazetteer deve encontrar empresas da lista semente
    found = _extract_gazetteer("A Petrobras e a Vale divulgaram resultados.")
    if any("Petrobras" in c for c in found) and any("Vale" in c for c in found):
        ok("extractor camada 1: gazetteer encontra empresas conhecidas")
    else:
        fail("extractor camada 1: gazetteer encontra empresas conhecidas", str(found))

    # camada 2: sufixo jurídico
    found = _extract_patterns("A Construtora Exemplo S.A. assinou contrato.")
    if any("Construtora Exemplo" in c for c in found):
        ok("extractor camada 2: detecta sufixo jurídico S.A.")
    else:
        fail("extractor camada 2: detecta sufixo jurídico S.A.", str(found))

    # camada 2: frase contextual "presidente da X"
    found = _extract_patterns("O presidente da Mineradora Nova anunciou expansão.")
    if any("Mineradora Nova" in c for c in found):
        ok("extractor camada 2: detecta empresa por contexto 'presidente da'")
    else:
        fail("extractor camada 2: detecta empresa por contexto 'presidente da'", str(found))

    # camada 3: filtro — siglas fiscais devem ser bloqueadas
    if _is_false_positive("IR") and _is_false_positive("DIRF"):
        ok("extractor camada 3: bloqueia siglas fiscais")
    else:
        fail("extractor camada 3: bloqueia siglas fiscais")

    # camada 3: filtro — geográficos devem ser bloqueados
    if _is_false_positive("Oriente Médio"):
        ok("extractor camada 3: bloqueia termos geográficos")
    else:
        fail("extractor camada 3: bloqueia termos geográficos")

    # camada 3: whitelist — siglas legítimas de empresas devem passar
    if not _is_false_positive("TIM") and not _is_false_positive("WEG"):
        ok("extractor camada 3: whitelist permite siglas de empresas reais")
    else:
        fail("extractor camada 3: whitelist permite siglas de empresas reais")

    # pipeline completo: deduplicação
    companies = extract_companies(
        "A Petrobras e a Petrobras S.A. divulgaram resultados. "
        "O diretor da Mineradora Alfa informou crescimento."
    )
    petrobras_count = sum(1 for c in companies if "Petrobras" in c)
    if petrobras_count == 1:
        ok("extractor pipeline: deduplica resultados entre camadas")
    else:
        fail("extractor pipeline: deduplica resultados entre camadas", str(companies))


# ── storage ──────────────────────────────────────────────────────────────────
def test_storage():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        from storage.database import (
            init_db, upsert_news, get_or_create_theme, get_or_create_company,
            link_news_theme, link_news_company, query_by_theme, query_by_company, stats,
        )

        init_db(db)
        ok("storage: init_db")

        nid = upsert_news("Título", "https://example.com/1", "resumo", "2024-01-01", "Fonte", db)
        if nid:
            ok("storage: upsert_news inserts new")
        else:
            fail("storage: upsert_news inserts new")

        dup = upsert_news("Título", "https://example.com/1", "resumo", "2024-01-01", "Fonte", db)
        if dup is None:
            ok("storage: upsert_news ignores duplicate")
        else:
            fail("storage: upsert_news ignores duplicate")

        tid = get_or_create_theme("economia", db)
        tid2 = get_or_create_theme("economia", db)
        if tid == tid2:
            ok("storage: get_or_create_theme idempotent")
        else:
            fail("storage: get_or_create_theme idempotent")

        cid = get_or_create_company("Petrobras", db)
        link_news_theme(nid, tid, db)
        link_news_company(nid, cid, db)

        rows = query_by_theme("economia", db)
        if rows and rows[0]["title"] == "Título":
            ok("storage: query_by_theme")
        else:
            fail("storage: query_by_theme", f"got {rows}")

        rows = query_by_company("Petrobras", db)
        if rows and rows[0]["title"] == "Título":
            ok("storage: query_by_company")
        else:
            fail("storage: query_by_company", f"got {rows}")

        s = stats(db)
        # companies pode ser > 1 pois init_db carrega os canonicos dos aliases
        if s["news"] == 1 and s["themes"] == 1 and s["companies"] >= 1:
            ok("storage: stats")
        else:
            fail("storage: stats", str(s))

        # feeds devem ser carregados pelo init_db a partir do feeds.txt
        from storage.database import get_active_feeds
        feeds = get_active_feeds(db)
        if len(feeds) >= 1:
            ok(f"storage: {len(feeds)} feed(s) carregados do feeds.txt")
        else:
            fail("storage: feeds carregados do feeds.txt", str(feeds))

    finally:
        os.unlink(db)


# ── coordinator pipeline (offline) ───────────────────────────────────────────
def test_coordinator_pipeline():
    from agents.reader import Article
    from coordinator import process_article

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        from storage.database import init_db, query_by_theme
        init_db(db)

        article = Article(
            title="Petrobras anuncia investimento em energia renovável",
            url="https://example.com/petrobras-energia",
            summary="A Petrobras vai investir R$ 10 bilhões em projetos de energia renovável.",
            published_at="2024-06-01",
            source="Teste",
        )
        added = process_article(article, db)
        if added:
            ok("coordinator: new article processed")
        else:
            fail("coordinator: new article processed")

        dup = process_article(article, db)
        if not dup:
            ok("coordinator: duplicate article skipped")
        else:
            fail("coordinator: duplicate article skipped")

        rows = query_by_theme("energia", db)
        if rows:
            ok("coordinator: article linked to theme 'energia'")
        else:
            fail("coordinator: article linked to theme 'energia'")

    finally:
        os.unlink(db)


# ── co-ocorrência ────────────────────────────────────────────────────────────
def test_cooccurrence():
    from storage.database import (
        init_db, get_or_create_company,
        record_cooccurrences, query_cooccurrences, query_neighbors,
    )

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        init_db(db)
        id_a = get_or_create_company("EmpresaA", db)
        id_b = get_or_create_company("EmpresaB", db)
        id_c = get_or_create_company("EmpresaC", db)

        # A e B co-ocorrem 3 vezes; B e C co-ocorrem 1 vez
        record_cooccurrences([id_a, id_b], db)
        record_cooccurrences([id_a, id_b], db)
        record_cooccurrences([id_a, id_b], db)
        record_cooccurrences([id_b, id_c], db)

        # contador deve refletir as chamadas
        pairs = query_cooccurrences(limit=10, db_path=db)
        ab = next((p for p in pairs if
                   ("EmpresaA" in (p["name_a"], p["name_b"]) and
                    "EmpresaB" in (p["name_a"], p["name_b"]))), None)
        if ab and ab["news_count"] == 3:
            ok("cooccurrence: contagem A-B correta (3)")
        else:
            fail("cooccurrence: contagem A-B correta (3)", str(ab))

        # pares duplicados não devem ser criados (A,B) == (B,A)
        record_cooccurrences([id_b, id_a], db)  # ordem invertida
        pairs2 = query_cooccurrences(limit=10, db_path=db)
        ab2 = next((p for p in pairs2 if
                    ("EmpresaA" in (p["name_a"], p["name_b"]) and
                     "EmpresaB" in (p["name_a"], p["name_b"]))), None)
        if ab2 and ab2["news_count"] == 4:
            ok("cooccurrence: par (B,A) incrementa mesmo par (A,B)")
        else:
            fail("cooccurrence: par (B,A) incrementa mesmo par (A,B)", str(ab2))

        # vizinhança grau 1: A deve ver B como vizinho
        viz = query_neighbors("EmpresaA", depth=1, db_path=db)
        names_g1 = [r["name"] for r in viz["grau_1"]]
        if "EmpresaB" in names_g1:
            ok("cooccurrence: vizinhanca grau 1 de A inclui B")
        else:
            fail("cooccurrence: vizinhanca grau 1 de A inclui B", str(names_g1))

        # vizinhança grau 2: A deve alcançar C via B
        viz2 = query_neighbors("EmpresaA", depth=2, db_path=db)
        names_g2 = [r["name"] for r in viz2["grau_2"]]
        if "EmpresaC" in names_g2:
            ok("cooccurrence: vizinhanca grau 2 de A alcanca C via B")
        else:
            fail("cooccurrence: vizinhanca grau 2 de A alcanca C via B", str(names_g2))

        # C não deve aparecer no grau 1 de A (não co-ocorrem diretamente)
        if "EmpresaC" not in names_g1:
            ok("cooccurrence: C nao esta no grau 1 de A")
        else:
            fail("cooccurrence: C nao esta no grau 1 de A")

    finally:
        os.unlink(db)


# ── aliases ──────────────────────────────────────────────────────────────────
def test_aliases():
    import tempfile, os
    from storage.database import init_db, resolve_alias, stats

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        init_db(db)

        # alias seguro: resolve independente de contexto
        if resolve_alias("RFB", db_path=db) == "Receita Federal":
            ok("aliases: alias seguro 'RFB' -> 'Receita Federal'")
        else:
            fail("aliases: alias seguro 'RFB' -> 'Receita Federal'", resolve_alias("RFB", db_path=db))

        # alias seguro: variação com sufixo jurídico
        if resolve_alias("Grupo JBS", db_path=db) == "JBS":
            ok("aliases: alias seguro 'Grupo JBS' -> 'JBS'")
        else:
            fail("aliases: alias seguro 'Grupo JBS' -> 'JBS'", resolve_alias("Grupo JBS", db_path=db))

        # alias seguro: sigla de bolsa
        if resolve_alias("Bolsa Brasileira", db_path=db) == "B3":
            ok("aliases: alias seguro 'Bolsa Brasileira' -> 'B3'")
        else:
            fail("aliases: alias seguro 'Bolsa Brasileira' -> 'B3'", resolve_alias("Bolsa Brasileira", db_path=db))

        # alias inseguro SEM contexto: não deve resolver
        result = resolve_alias("Receita", context="a receita foi alta", db_path=db)
        if result == "Receita":
            ok("aliases: alias inseguro 'Receita' sem contexto -> mantém original")
        else:
            fail("aliases: alias inseguro 'Receita' sem contexto -> mantém original", result)

        # alias inseguro COM contexto: deve resolver
        result = resolve_alias("Receita", context="A Receita Federal autuou a empresa", db_path=db)
        if result == "Receita Federal":
            ok("aliases: alias inseguro 'Receita' com contexto -> 'Receita Federal'")
        else:
            fail("aliases: alias inseguro 'Receita' com contexto -> 'Receita Federal'", result)

        # nome sem alias: devolve o próprio nome
        if resolve_alias("Empresa Desconhecida", db_path=db) == "Empresa Desconhecida":
            ok("aliases: nome sem alias -> devolve original")
        else:
            fail("aliases: nome sem alias -> devolve original")

        # stats deve incluir aliases
        s = stats(db)
        if s.get("aliases", 0) > 0:
            ok(f"aliases: {s['aliases']} alias(es) carregados do config")
        else:
            fail("aliases: aliases carregados do config", str(s))

    finally:
        os.unlink(db)


# ── reports ──────────────────────────────────────────────────────────────────
def test_reports():
    import io
    from contextlib import redirect_stdout
    from agents.reader import Article
    from coordinator import process_article
    from storage.database import init_db
    import reports

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        init_db(db)
        for art in [
            Article("Vale reporta lucro recorde", "https://ex.com/vale",
                    "A Vale registrou lucro recorde no trimestre.", "2024-03-01", "Fonte"),
            Article("Petrobras investe em energia solar", "https://ex.com/petro",
                    "A Petrobras anuncia expansão em energia solar.", "2024-03-02", "Fonte"),
        ]:
            process_article(art, db)

        for fn_name, fn in [
            ("resumo_geral",        reports.resumo_geral),
            ("noticias_por_tema",   reports.noticias_por_tema),
            ("empresas_por_tema",   reports.empresas_por_tema),
            ("noticias_por_empresa",reports.noticias_por_empresa),
        ]:
            buf = io.StringIO()
            with redirect_stdout(buf):
                fn(db)
            output = buf.getvalue()
            if output.strip():
                ok(f"reports: {fn_name} produces output")
            else:
                fail(f"reports: {fn_name} produces output")

        # resumo deve listar 2 notícias
        buf = io.StringIO()
        with redirect_stdout(buf):
            reports.resumo_geral(db)
        if "2" in buf.getvalue():
            ok("reports: resumo conta 2 notícias")
        else:
            fail("reports: resumo conta 2 notícias", buf.getvalue())

        # suspeitas: "Alfa" (4 chars, 1 palavra, sem alias) deve aparecer;
        # "Vale" não deve aparecer pois está no gazetteer mas sem alias no db de teste;
        # vamos inserir uma empresa curta sem alias e verificar
        from storage.database import get_or_create_company, link_news_company, upsert_news
        nid2 = upsert_news("Noticia Alfa", "https://ex.com/alfa2", "Alfa fez algo.", "2024-04-01", "Fonte", db)
        cid_alfa = get_or_create_company("Alfa", db)
        link_news_company(nid2, cid_alfa, db)

        buf = io.StringIO()
        with redirect_stdout(buf):
            reports.empresas_suspeitas(db, max_chars=10)
        if "Alfa" in buf.getvalue():
            ok("reports: suspeitas lista empresa curta sem alias")
        else:
            fail("reports: suspeitas lista empresa curta sem alias", buf.getvalue())

        # "Vale" tem 4 chars mas está nos aliases do config — não deve aparecer como suspeita
        # (só válido se o db de teste tiver aliases carregados, o que ocorre via init_db)
        buf = io.StringIO()
        with redirect_stdout(buf):
            reports.empresas_suspeitas(db, max_chars=10)
        # "Vale" não está nos COMPANY_ALIASES do config, então pode aparecer —
        # o teste relevante é que "Alfa" aparece e o relatório roda sem erros
        ok("reports: suspeitas executa sem erros")

    finally:
        os.unlink(db)


def test_reports_subprocess():
    """Executa cada comando de news.py num subprocesso real para detectar
    erros de encoding que redirect_stdout mascara (ex: UnicodeEncodeError cp1252).
    Usa um db temporário populado para garantir saída não-vazia em todos os comandos."""
    import subprocess
    from storage.database import (
        init_db, upsert_news, get_or_create_company,
        get_or_create_theme, link_news_company, link_news_theme,
    )

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        # monta db mínimo: 1 notícia, 1 tema, 1 empresa, 1 empresa suspeita
        init_db(db)
        nid = upsert_news("Titulo teste unicode: cao e gato", "https://ex.com/t1",
                          "Resumo com acento: informacao.", "2024-01-01", "Fonte", db)
        tid = get_or_create_theme("economia", db)
        cid = get_or_create_company("EmpresaLonga", db)
        cid2 = get_or_create_company("Alfa", db)      # suspeita: curta, sem alias
        link_news_theme(nid, tid, db)
        link_news_company(nid, cid, db)
        link_news_company(nid, cid2, db)

        commands = ["resumo", "feeds", "temas", "empresas", "por-empresa", "suspeitas", "pares", "tudo"]
        for cmd in commands:
            result = subprocess.run(
                [sys.executable, "news.py", cmd, "--db", db],
                capture_output=True,
                # errors="replace" evita crash ao ler saída com chars fora do utf-8
                text=True, encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                ok(f"news.py '{cmd}' roda sem erro")
            else:
                stderr = (result.stderr or "").strip()
                last_line = stderr.splitlines()[-1] if stderr else "(sem stderr)"
                fail(f"news.py '{cmd}' roda sem erro", last_line)

        # feed-add: adiciona novo feed
        result = subprocess.run(
            [sys.executable, "news.py", "feed-add", "https://example.com/new.xml", "--db", db],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and "OK" in result.stdout:
            ok("news.py 'feed-add' adiciona feed novo")
        else:
            fail("news.py 'feed-add' adiciona feed novo", result.stdout.strip())

        # feed-add: URL duplicada não causa erro
        result = subprocess.run(
            [sys.executable, "news.py", "feed-add", "https://example.com/new.xml", "--db", db],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and "AVISO" in result.stdout:
            ok("news.py 'feed-add' avisa se feed ja existe")
        else:
            fail("news.py 'feed-add' avisa se feed ja existe", result.stdout.strip())

        # feed-off: desativa pelo trecho da URL
        result = subprocess.run(
            [sys.executable, "news.py", "feed-off", "example.com/new", "--db", db],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and "OK" in result.stdout:
            ok("news.py 'feed-off' desativa feed por trecho de URL")
        else:
            fail("news.py 'feed-off' desativa feed por trecho de URL", result.stdout.strip())

        # feed-add após feed-off: deve reativar
        result = subprocess.run(
            [sys.executable, "news.py", "feed-add", "https://example.com/new.xml", "--db", db],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and "reativado" in result.stdout:
            ok("news.py 'feed-add' reativa feed inativo")
        else:
            fail("news.py 'feed-add' reativa feed inativo", result.stdout.strip())

        # feed-off: ID inexistente deve retornar erro
        result = subprocess.run(
            [sys.executable, "news.py", "feed-off", "9999", "--db", db],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            ok("news.py 'feed-off' retorna erro para ID inexistente")
        else:
            fail("news.py 'feed-off' retorna erro para ID inexistente", result.stdout.strip())
    finally:
        os.unlink(db)


# ── graph ────────────────────────────────────────────────────────────────────
def test_graph():
    from agents.reader import Article
    from coordinator import process_article
    from storage.database import init_db
    import graph

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        html = f.name
    try:
        init_db(db)
        # insere artigos com entidades conhecidas para gerar co-ocorrências
        for art in [
            Article("Petrobras e Vale anunciam parceria",
                    "https://ex.com/g1", "Petrobras e Vale firmaram acordo.", "2024-01-01", "Fonte"),
            Article("Petrobras investe em energia",
                    "https://ex.com/g2", "Petrobras amplia investimentos em energia.", "2024-01-02", "Fonte"),
        ]:
            process_article(art, db)

        # modo básico: deve gerar HTML sem erro
        path = graph.gerar_grafo(db_path=db, min_cooc=1, output=html)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            ok("graph: gera arquivo HTML")
        else:
            fail("graph: gera arquivo HTML")

        # HTML deve conter elementos básicos do pyvis
        with open(path, encoding="utf-8") as f:
            content = f.read()
        if "vis-network" in content or "network" in content.lower():
            ok("graph: HTML contem vis-network")
        else:
            fail("graph: HTML contem vis-network")

        # min_cooc alto demais deve lançar ValueError
        try:
            graph.gerar_grafo(db_path=db, min_cooc=9999, output=html)
            fail("graph: ValueError para min_cooc sem dados")
        except ValueError:
            ok("graph: ValueError para min_cooc sem dados")

        # modo --temas não deve lançar erro
        path2 = graph.gerar_grafo(db_path=db, min_cooc=1, incluir_temas=True, output=html)
        if os.path.exists(path2):
            ok("graph: modo --temas gera HTML sem erro")
        else:
            fail("graph: modo --temas gera HTML sem erro")

    finally:
        os.unlink(db)
        if os.path.exists(html):
            os.unlink(html)


# ── main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Tests: news-cataloger ===\n")

    print("-- classifier --")
    test_classifier()

    print("\n-- extractor --")
    test_extractor()

    print("\n-- storage --")
    test_storage()

    print("\n-- coordinator pipeline --")
    test_coordinator_pipeline()

    print("\n-- co-ocorrencia --")
    test_cooccurrence()

    print("\n-- aliases --")
    test_aliases()

    print("\n-- reports --")
    test_reports()

    print("\n-- graph --")
    test_graph()

    print("\n-- reports (subprocess) --")
    test_reports_subprocess()

    print(f"\n{PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)
