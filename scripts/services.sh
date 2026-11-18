#!/usr/bin/env bash
# localragin taustapalvelut: PostgreSQL + pgvector (Docker) ja Ollama (natiivisti).
#
#   scripts/services.sh start    käynnistää tietokannan ja Ollaman sekä lataa mallit tarvittaessa
#   scripts/services.sh stop     pysäyttää tietokannan ja Ollaman, jos tämä skripti käynnisti sen
#   scripts/services.sh status   näyttää palveluiden tilan
#   scripts/services.sh createdb NIMI   luo tietokannan, jos sitä ei vielä ole (esim. demolle)
#
# Ollama ajetaan natiivisti eikä Dockerissa, koska macOS:llä Docker ei pääse käyttämään
# GPU:ta. Jos Ollama on jo käynnissä (esim. Ollama-sovellus), sitä käytetään eikä sammuteta.
# Asetukset luetaan ympäristömuuttujista tai .env-tiedostosta (LOCALRAG_*).

set -euo pipefail
cd "$(dirname "$0")/.."

STATE_DIR=.localrag
OLLAMA_PID_FILE=$STATE_DIR/ollama.pid
OLLAMA_LOG=$STATE_DIR/ollama.log

env_value() {
    local name=$1 default=$2 line
    if [[ -n "${!name:-}" ]]; then
        echo "${!name}"
        return
    fi
    if [[ -f .env ]]; then
        line=$(grep -E "^${name}=" .env | tail -n 1 || true)
        if [[ -n "$line" ]]; then
            echo "${line#*=}"
            return
        fi
    fi
    echo "$default"
}

PROVIDER=$(env_value LOCALRAG_EMBEDDING_PROVIDER ollama)
RERANKER=$(env_value LOCALRAG_RERANKER none)
MODEL=$(env_value LOCALRAG_EMBEDDING_MODEL bge-m3)
OLLAMA_URL=$(env_value LOCALRAG_OLLAMA_URL http://localhost:11434)
export OLLAMA_HOST=${OLLAMA_URL#*://}

db_running() {
    [[ -n "$(docker compose ps --status running --quiet db 2>/dev/null)" ]]
}

ollama_running() {
    curl --silent --fail --max-time 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1
}

ollama_started_by_us() {
    [[ -f "$OLLAMA_PID_FILE" ]] && kill -0 "$(cat "$OLLAMA_PID_FILE")" 2>/dev/null
}

start_db() {
    if db_running; then
        echo "Tietokanta on jo käynnissä."
    else
        echo "Käynnistetään tietokanta..."
        docker compose up --detach --wait db
    fi
}

start_ollama() {
    if [[ "$PROVIDER" != "ollama" ]]; then
        echo "Embedding-provider on $PROVIDER, Ollamaa ei tarvita."
        return
    fi
    if ollama_running; then
        echo "Ollama on jo käynnissä ($OLLAMA_URL)."
    else
        if ! command -v ollama >/dev/null; then
            echo "Ollamaa ei löydy. Asenna se: brew install ollama" >&2
            exit 1
        fi
        mkdir -p "$STATE_DIR"
        echo "Käynnistetään Ollama ($OLLAMA_URL, loki: $OLLAMA_LOG)..."
        nohup ollama serve >"$OLLAMA_LOG" 2>&1 &
        echo $! >"$OLLAMA_PID_FILE"
        for _ in $(seq 1 30); do
            ollama_running && break
            sleep 0.5
        done
        if ! ollama_running; then
            echo "Ollama ei käynnistynyt. Katso loki: $OLLAMA_LOG" >&2
            exit 1
        fi
    fi
    if ! ollama show "$MODEL" >/dev/null 2>&1; then
        echo "Ladataan embedding-malli $MODEL..."
        ollama pull "$MODEL"
    fi
}

stop_ollama() {
    if ollama_started_by_us; then
        echo "Pysäytetään Ollama..."
        kill "$(cat "$OLLAMA_PID_FILE")"
        for _ in $(seq 1 20); do
            ollama_started_by_us || break
            sleep 0.25
        done
    elif ollama_running; then
        echo "Ollamaa ei käynnistetty tällä skriptillä, jätetään se käyntiin."
    fi
    rm -f "$OLLAMA_PID_FILE"
}

stop_db() {
    if db_running; then
        echo "Pysäytetään tietokanta..."
        docker compose stop db
    fi
}

create_database() {
    local name=${1:-}
    if [[ ! "$name" =~ ^[a-z_][a-z0-9_]*$ ]]; then
        echo "Anna tietokannan nimi pienillä kirjaimilla, numeroilla ja alaviivoilla." >&2
        exit 2
    fi
    start_db
    local exists
    exists=$(docker compose exec -T db psql -U localrag -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname = '$name'")
    if [[ "$exists" == "1" ]]; then
        echo "Tietokanta $name on jo olemassa."
    else
        docker compose exec -T db createdb -U localrag "$name"
        echo "Luotiin tietokanta $name."
    fi
}

prepare_models() {
    if [[ "$RERANKER" != "none" ]]; then
        # Lataa reranker-mallin valmiiksi (ensimmäisellä kerralla noin 0,6 Gt)
        uv run --quiet localrag prepare
    fi
}

status() {
    if db_running; then echo "Tietokanta: käynnissä"; else echo "Tietokanta: pysähdyksissä"; fi
    if [[ "$PROVIDER" != "ollama" ]]; then
        echo "Ollama: ei käytössä (provider: $PROVIDER)"
    elif ollama_running; then
        local by_us=""
        ollama_started_by_us && by_us=", käynnistetty tällä skriptillä"
        echo "Ollama: käynnissä ($OLLAMA_URL$by_us)"
        if ollama show "$MODEL" >/dev/null 2>&1; then
            echo "Malli $MODEL: ladattu"
        else
            echo "Malli $MODEL: puuttuu"
        fi
    else
        echo "Ollama: pysähdyksissä"
    fi
}

case "${1:-}" in
    start) start_db; start_ollama; prepare_models ;;
    stop) stop_ollama; stop_db ;;
    status) status ;;
    createdb) create_database "${2:-}" ;;
    # Testiskriptin käyttämät apukomennot
    is-running) case "${2:-}" in db) db_running ;; ollama) ollama_running ;; *) exit 2 ;; esac ;;
    start-db) start_db ;;
    stop-db) stop_db ;;
    stop-ollama) stop_ollama ;;
    *)
        echo "Käyttö: $0 start|stop|status|createdb NIMI" >&2
        exit 2
        ;;
esac
