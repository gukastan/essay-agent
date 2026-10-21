#!/usr/bin/env bash
set -euo pipefail
exec bash "$(dirname "$0")/run_agent_openai.sh" --frontend
