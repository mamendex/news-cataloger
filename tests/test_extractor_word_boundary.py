"""Regressão: word boundary no gazetteer Aho-Corasick.

Bug: automaton.iter() fazia matching de substring pura, sem verificar bordas
de palavra. "Claro" era detectada em "declarou", "Oi" em "apoio", etc.,
corrompendo silenciosamente o banco de co-ocorrências.

Fix: extractor.py/_extract_gazetteer agora rejeita matches onde o caractere
imediatamente antes ou depois do match é alfanumérico.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(ok, fail):
    from agents.extractor import _extract_gazetteer

    # ── falsos positivos que existiam antes do fix ────────────────────────────
    fp_cases = [
        # (texto, empresa que NÃO deve ser detectada, motivo)
        ("O governo vai declarou algo importante",      "Claro",  "'claro' em 'declarou'"),
        ("O apoio popular foi decisivo",                "Oi",     "'oi' em 'apoio'"),
        ("O golfinho foi avistado no mar",              "Gol",    "'gol' em 'golfinho'"),
        ("O timing das operacoes foi ruim",             "TIM",    "'tim' em 'timing'"),
        ("O azulejo estava quebrado",                   "Azul",   "'azul' em 'azulejo'"),
        ("lightweight framework para web",              "Light",  "'light' em 'lightweight'"),
        ("A burocracia atrapalhou o processo",          "Oi",     "'oi' em 'burocracia'"),
        ("A exploração da camada pre-sal avanca",       "Oi",     "'oi' em 'exploração'"),
        ("golpe de estado foi tentado",                 "Gol",    "'gol' em 'golpe'"),
        ("esclareceu os fatos para a imprensa",         "Claro",  "'claro' em 'esclareceu'"),
    ]

    for text, company, motivo in fp_cases:
        found = _extract_gazetteer(text)
        names = [c.lower() for c in found]
        if any(company.lower() == n for n in names):
            fail(f"extractor word boundary: falso positivo '{company}' em '{text}' ({motivo})")
        else:
            ok(f"extractor word boundary: '{company}' nao detectada em texto com '{motivo}'")

    # ── verdadeiros positivos: empresas como palavras isoladas ────────────────
    # Só executa se ahocorasick estiver instalado
    try:
        import ahocorasick  # noqa: F401
    except ImportError:
        ok("extractor word boundary: ahocorasick ausente — TP ignorados (camada 1 desativada)")
        return

    tp_cases = [
        ("A Petrobras anunciou resultados recordes",      "Petrobras"),
        ("Acordo entre Gol e Latam foi firmado",          "Gol"),
        ("OI registrou crescimento no trimestre",         "OI"),
        ("A Claro lançou novo plano de dados",            "Claro"),
        ("TIM e Vivo disputam mercado mobile",            "TIM"),
        ("A Azul abrirá novas rotas no nordeste",         "Azul"),
        ("A Light anunciou corte de energia",             "Light"),
        ("Magazine Luiza divulgou resultados",            "Magazine Luiza"),
        ("Vale reportou lucro recorde",                   "Vale"),
        ("Itaú e Bradesco lideram ranking bancário",      "Itaú"),
    ]

    for text, company in tp_cases:
        found = _extract_gazetteer(text)
        names = [c.lower() for c in found]
        if any(company.lower() in n for n in names):
            ok(f"extractor word boundary: '{company}' detectada corretamente")
        else:
            fail(f"extractor word boundary: regressao — '{company}' nao detectada em '{text}'",
                 str(found))


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
