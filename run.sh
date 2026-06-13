#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  uv run kg-viewer "$@"
  exit 0
fi

viewer_port() {
  port="${KG_VIEWER_PORT:-}"
  if [ -z "$port" ] && [ -f ".env" ]; then
    port="$(sed -n 's/^KG_VIEWER_PORT=//p' .env | tail -n 1 | tr -d "'\"")"
  fi
  port="${port:-8000}"

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --port)
        port="${2:?missing value for --port}"
        shift 2
        ;;
      --port=*)
        port="${1#--port=}"
        shift
        ;;
      *)
        shift0
        ;;
    esac
  done

  echo "$port"
}

port="$(viewer_port "$@")"

pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN || true)"
if [ -n "$pids" ]; then
  echo "Stopping existing listener on port $port: $pids"
  kill $pids
  sleep 1
fi

uv run kg-viewer "$@"
