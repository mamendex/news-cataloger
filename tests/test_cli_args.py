"""Regressão: validação de argumentos da CLI (news.py).

Bug: _parse_args() acessava args[idx + 1] sem verificar se havia um valor
após --db, lançando IndexError sem mensagem útil ao usuário.

Fix: news.py/_parse_args agora valida idx + 1 < len(args) antes do acesso.
"""
import sys
import os
import subprocess
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(ok, fail):
    news_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "news.py")

    # ── --db sem valor deve sair com código de erro e mensagem clara ──────────
    result = subprocess.run(
        [sys.executable, news_py, "resumo", "--db"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        ok("cli args: '--db' sem valor retorna exit code != 0")
    else:
        fail("cli args: '--db' sem valor deveria retornar exit code != 0")

    output = result.stdout + result.stderr
    if "Erro" in output or "erro" in output or "--db" in output:
        ok("cli args: '--db' sem valor exibe mensagem de erro")
    else:
        fail("cli args: '--db' sem valor deveria exibir mensagem de erro", repr(output))

    if "IndexError" not in output and "Traceback" not in output:
        ok("cli args: '--db' sem valor nao lanca traceback")
    else:
        fail("cli args: '--db' sem valor nao deveria lançar traceback", repr(output))

    # ── --db com valor válido continua funcionando ────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name
    try:
        from storage.database import init_db
        init_db(db)

        result = subprocess.run(
            [sys.executable, news_py, "resumo", "--db", db],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            ok("cli args: '--db <path>' continua funcionando")
        else:
            fail("cli args: '--db <path>' deveria funcionar", result.stderr.strip())
    finally:
        os.unlink(db)

    # ── comando sem --db usa o banco padrão (não crasha) ─────────────────────
    result = subprocess.run(
        [sys.executable, news_py, "--help-inexistente"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0 and "IndexError" not in (result.stdout + result.stderr):
        ok("cli args: comando desconhecido retorna erro sem IndexError")
    elif "IndexError" in (result.stdout + result.stderr):
        fail("cli args: comando desconhecido lançou IndexError inesperado")
    else:
        ok("cli args: comando desconhecido tratado sem crash")

    # ── --db no meio dos argumentos funciona ─────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db2 = f.name
    try:
        from storage.database import init_db
        init_db(db2)

        result = subprocess.run(
            [sys.executable, news_py, "--db", db2, "resumo"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            ok("cli args: '--db <path> <cmd>' (db antes do comando) funciona")
        else:
            fail("cli args: '--db <path> <cmd>' deveria funcionar", result.stderr.strip())
    finally:
        os.unlink(db2)


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
