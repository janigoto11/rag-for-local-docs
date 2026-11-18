#!/usr/bin/env bash
# Ajaa testit ja hoitaa niiden tarvitsemat palvelut.
#
#   scripts/test.sh              yksikkö- ja integraatiotestit (käynnistää tietokannan)
#   scripts/test.sh e2e          e2e-laatutesti (käynnistää tietokannan ja Ollaman)
#   scripts/test.sh e2e -k xyz   lisäparametrit välitetään pytestille
#
# Palvelut, jotka eivät olleet käynnissä ennen ajoa, pysäytetään lopuksi.

set -euo pipefail
cd "$(dirname "$0")/.."

services=scripts/services.sh

mode=default
if [[ "${1:-}" == "e2e" ]]; then
    mode=e2e
    shift
fi

db_was_running=false
ollama_was_running=false
$services is-running db && db_was_running=true
$services is-running ollama && ollama_was_running=true

cleanup() {
    if [[ "$mode" == "e2e" && "$ollama_was_running" == false ]]; then
        $services stop-ollama
    fi
    if [[ "$db_was_running" == false ]]; then
        $services stop-db
    fi
}
trap cleanup EXIT

if [[ "$mode" == "e2e" ]]; then
    $services start
    uv run pytest -m e2e -s "$@"
else
    $services start-db
    uv run pytest "$@"
fi
