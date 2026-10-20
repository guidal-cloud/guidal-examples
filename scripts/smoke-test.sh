#!/usr/bin/env bash
# Smoke-test one example image under the platform's runtime constraints, or tighter:
# read-only root filesystem with only /tmp writable, all capabilities dropped,
# no privilege escalation, numeric non-root user.
#
#   scripts/smoke-test.sh <example-dir> <image>
#
# Used by CI and runnable locally (needs docker and curl). Cleans up after itself.
set -euo pipefail

app="$1"
image="$2"
run_id="smoke-$$"
HARDENED=(--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges --user 1000)

cleanup() {
  docker ps -aq --filter "label=$run_id" | xargs -r docker rm -f >/dev/null 2>&1 || true
  docker network rm "$run_id" >/dev/null 2>&1 || true
}
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; docker ps -aq --filter "label=$run_id" | xargs -r -n1 docker logs >&2 2>&1 || true; exit 1; }

# wait_http <url> [seconds]: poll until the URL answers 2xx (the platform allows 60 s).
wait_http() {
  local url="$1" deadline=$((SECONDS + ${2:-60}))
  until curl -fsS -o /dev/null "$url" 2>/dev/null; do
    (( SECONDS < deadline )) || fail "$url not ready"
    sleep 1
  done
}

# wait_log <container> <text> [seconds]
wait_log() {
  local deadline=$((SECONDS + ${3:-30}))
  until docker logs "$1" 2>&1 | grep -q "$2"; do
    (( SECONDS < deadline )) || fail "'$2' never appeared in $1 logs"
    sleep 1
  done
}

run() { docker run -d --platform linux/amd64 --label "$run_id" "${HARDENED[@]}" "$@"; }

status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

check_image_user() {
  local user
  user=$(docker inspect -f '{{.Config.User}}' "$image")
  [[ "$user" =~ ^[1-9][0-9]*(:[0-9]+)?$ ]] || fail "image USER '$user' is not numeric non-root"
}

check_headers() {  # check_headers <url> <header>...
  local headers
  headers=$(curl -fsS -D - -o /dev/null "$1" | tr -d '\r' | tr '[:upper:]' '[:lower:]')
  shift
  for h in "$@"; do grep -q "^$h:" <<<"$headers" || fail "missing header $h"; done
  ! grep -qE '^(server|x-powered-by):' <<<"$headers" || fail "server/x-powered-by header leaks the stack"
}

# A route that raises, mounted only inside this test (the image has no such route):
# the 500 must carry the security headers, hide the exception text, and be logged as
# one JSON line with the traceback.
FORCED_500_PY='
import asyncio, io, json, sys
sys.stdout = captured = io.StringIO()
import main

@main.app.get("/__smoke_boom")
def boom():
    raise RuntimeError("detail-that-must-not-leak")

sent = []
async def receive():
    return {"type": "http.request", "body": b"", "more_body": False}
async def send(message):
    sent.append(message)
scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
         "scheme": "http", "path": "/__smoke_boom", "raw_path": b"/__smoke_boom", "query_string": b"",
         "root_path": "", "headers": [], "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000)}
asyncio.run(main.app(scope, receive, send))
sys.stdout = sys.__stdout__
headers = dict(sent[0]["headers"])
body = b"".join(m.get("body", b"") for m in sent[1:])
assert sent[0]["status"] == 500, sent[0]
assert b"content-security-policy" in headers and b"x-content-type-options" in headers, headers
assert b"must-not-leak" not in body, body
entries = [json.loads(line) for line in captured.getvalue().splitlines()]
assert any(e["msg"] == "unhandled error" and "must-not-leak" in e.get("exc", "") for e in entries), entries
print("forced 500: security headers, generic body, JSON log line with the traceback")
'
check_forced_500() {
  docker run --rm --platform linux/amd64 "${HARDENED[@]}" --entrypoint python "$image" -c "$FORCED_500_PY" \
    || fail "forced 500 check"
}

# Every line the app wrote to stdout/stderr (uvicorn's included) is one JSON object.
check_json_logs() {
  local logs
  logs=$(docker logs "$1" 2>&1) || fail "docker logs $1"
  [ -n "$logs" ] || fail "no logs from $1"
  ! grep -v '^{' <<<"$logs" || fail "non-JSON log lines in $1"
}

check_image_user
case "$app" in
  web-fastapi)
    run -p 18000:8000 --name "$run_id-web" "$image" >/dev/null
    wait_http http://localhost:18000/
    curl -fsS http://localhost:18000/ | grep -q '"status":"ok"' || fail "GET / body"
    check_headers http://localhost:18000/ x-content-type-options x-frame-options content-security-policy referrer-policy
    [ "$(status http://localhost:18000/docs)" = 404 ] || fail "/docs is exposed"
    [ "$(status http://localhost:18000/openapi.json)" = 404 ] || fail "/openapi.json is exposed"
    [ "$(status -X POST -H 'content-type: application/json' -d '{"message":"hi"}' http://localhost:18000/echo)" = 200 ] || fail "POST /echo"
    [ "$(status -X POST -H 'content-type: application/json' -d '{"message":"hi","x":1}' http://localhost:18000/echo)" = 422 ] || fail "unknown field accepted"
    big=$(head -c 70000 /dev/zero | tr '\0' a)
    [ "$(status -X POST -H 'content-type: application/json' --data-binary "{\"message\":\"$big\"}" http://localhost:18000/echo)" = 413 ] || fail "body limit"
    check_json_logs "$run_id-web"
    check_forced_500
    ;;

  web-nextjs)
    run -p 13000:3000 --name "$run_id-web" "$image" >/dev/null
    wait_http http://localhost:13000/
    curl -fsS http://localhost:13000/ | grep -q "Hello from Guidal" || fail "GET / body"
    curl -fsS http://localhost:13000/api/health | grep -q '"status":"ok"' || fail "/api/health"
    check_headers http://localhost:13000/ content-security-policy x-content-type-options x-frame-options referrer-policy
    ;;

  worker-python)
    c=$(run --name "$run_id-worker" "$image")
    wait_log "$c" '"unit done"'
    docker stop -t 10 "$c" >/dev/null
    docker logs "$c" 2>&1 | grep -q "worker stopped cleanly" || fail "no clean stop on SIGTERM"
    [ "$(docker inspect -f '{{.State.ExitCode}}' "$c")" = 0 ] || fail "worker exit code"
    ;;

  cron-python)
    # Guidal runs the cron command in place of the image's ENTRYPOINT.
    out=$(docker run --rm --platform linux/amd64 "${HARDENED[@]}" --entrypoint python "$image" job.py) || fail "job exited non-zero"
    grep -q '"msg": "job done"' <<<"$out" || fail "no result line: $out"
    ;;

  web-postgres)
    docker network create "$run_id" >/dev/null
    pg() {  # pg <name> <ssl on|off>
      docker run -d --label "$run_id" --network "$run_id" --name "$1" -e POSTGRES_PASSWORD=ci-only \
        postgres:16.15@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d \
        -c ssl="$2" -c log_connections=on -c ssl_cert_file=/etc/ssl/certs/ssl-cert-snakeoil.pem \
        -c ssl_key_file=/etc/ssl/private/ssl-cert-snakeoil.key >/dev/null
      local deadline=$((SECONDS + 60))
      until docker exec "$1" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; do
        (( SECONDS < deadline )) || fail "postgres $1 not ready"; sleep 1
      done
    }
    web() {  # web <host-port> [docker args...]
      local port="$1"; shift
      run --network "$run_id" -p "$port:8000" "$@" "$image" >/dev/null
      wait_http "http://localhost:$port/"
    }

    echo "-- without DATABASE_URL: / is 200, /notes is 503"
    web 18100
    curl -fsS http://localhost:18100/ | grep -q "DATABASE_URL not set" || fail "GET / without database"
    [ "$(status http://localhost:18100/notes)" = 503 ] || fail "/notes without database"

    echo "-- TLS server: two replicas start together, 16 parallel POSTs on a fresh database"
    pg "$run_id-pg-tls" on
    url="postgresql://postgres:ci-only@$run_id-pg-tls:5432/postgres"
    run --network "$run_id" -p 18101:8000 --name "$run_id-r1" -e DATABASE_URL="$url" "$image" >/dev/null
    run --network "$run_id" -p 18102:8000 --name "$run_id-r2" -e DATABASE_URL="$url" "$image" >/dev/null
    wait_http http://localhost:18101/
    wait_http http://localhost:18102/
    wait_log "$run_id-r1" '"schema ready"'
    wait_log "$run_id-r2" '"schema ready"'
    codes=$(for i in $(seq 1 16); do
      port=$((18101 + i % 2))
      status -X POST -H 'content-type: application/json' -d "{\"text\":\"note $i\"}" "http://localhost:$port/notes" &
    done; wait)
    [ "$(tr -d '\n' <<<"$codes")" = "$(printf '201%.0s' $(seq 1 16))" ] || fail "parallel POSTs: $codes"
    [ "$(curl -fsS 'http://localhost:18101/notes?limit=100' | grep -o '"id"' | wc -l | tr -d ' ')" = 16 ] || fail "note count"
    # log_connections records each session's TLS state: every app session must be TLS.
    authorized=$(docker logs "$run_id-pg-tls" 2>&1 | grep 'connection authorized' | grep 'application_name=web-postgres' || true)
    [ -n "$authorized" ] || fail "no app connections logged"
    ! grep -qv 'SSL enabled' <<<"$authorized" || fail "plaintext connection from the app"
    echo "app sessions logged by postgres: $(wc -l <<<"$authorized" | tr -d ' '), all with SSL enabled"
    [ "$(status -X POST -H 'content-type: application/json' -d "{\"text\":\"$(head -c 501 /dev/zero | tr '\0' a)\"}" http://localhost:18101/notes)" = 422 ] || fail "max length"
    for c in $(docker ps -aq --filter "label=$run_id"); do
      logs=$(docker logs "$c" 2>&1) || fail "docker logs $c"
      ! grep -q 'ci-only' <<<"$logs" || fail "a log line contains the database password"
    done

    echo "-- plaintext-only server: refused by the sslmode=require default, allowed by an explicit sslmode=disable"
    pg "$run_id-pg-plain" off
    web 18103 -e DATABASE_URL="postgresql://postgres:ci-only@$run_id-pg-plain:5432/postgres"
    [ "$(status http://localhost:18103/notes)" = 503 ] || fail "plaintext connection was allowed"
    web 18104 -e DATABASE_URL="postgresql://postgres:ci-only@$run_id-pg-plain:5432/postgres?sslmode=disable"
    [ "$(status http://localhost:18104/notes)" = 200 ] || fail "URL sslmode not honoured"

    echo "-- hung database (unroutable host): GET / stays fast during a burst of /notes"
    run -p 18105:8000 --name "$run_id-hung" -e DATABASE_URL="postgresql://u:p@10.255.255.1:5432/db" "$image" >/dev/null
    wait_http http://localhost:18105/
    for _ in $(seq 1 60); do curl -s -o /dev/null -m 20 http://localhost:18105/notes & done
    curl -fsS -o /dev/null -m 2 http://localhost:18105/ || fail "GET / took more than 2 s with a hung database"
    [ "$(status -m 2 http://localhost:18105/notes)" = 503 ] || fail "/notes should answer 503 quickly"
    wait
    check_json_logs "$run_id-hung"
    check_forced_500
    ;;

  *) fail "unknown example $app" ;;
esac
echo "PASS: $app"
