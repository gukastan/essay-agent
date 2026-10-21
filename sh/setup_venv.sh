#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null 2>&1 || { echo 'ERROR: install uv first (https://docs.astral.sh/uv/).'; exit 1; }
if [ ! -x .venv/bin/python ]; then
    uv venv --python 3.11 .venv
fi
uv pip install --python .venv/bin/python -r requirements.txt
echo 'Runtime ready. Tests: uv pip install --python .venv/bin/python -r requirements-dev.txt'
echo 'Offline demo: LLM_BACKEND=fake LANGCHAIN_TRACING_V2=false bash sh/run_agent_openai.sh'
echo 'Frontend in another terminal: bash sh/run_frontend.sh'
