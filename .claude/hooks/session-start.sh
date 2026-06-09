#!/bin/bash
set -euo pipefail

# Roda apenas em sessões remotas (Claude Code na web)
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo '{"async": true, "asyncTimeout": 300000}'

VENV="$CLAUDE_PROJECT_DIR/.venv"

# Cria o venv se não existir
if [ ! -f "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

# Instala dependências do requirements.txt
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$CLAUDE_PROJECT_DIR/requirements.txt"

# Baixa o modelo spaCy se ainda não estiver instalado
if ! "$VENV/bin/python" -c "import pt_core_news_sm" 2>/dev/null; then
  "$VENV/bin/python" -m spacy download pt_core_news_sm --quiet
fi

# Expõe o python do venv como padrão da sessão
echo "export PATH=\"$VENV/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
echo "export VIRTUAL_ENV=\"$VENV\""     >> "$CLAUDE_ENV_FILE"
