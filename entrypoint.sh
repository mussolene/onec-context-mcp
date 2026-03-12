#!/bin/sh
# If running as root: fix volume ownership and run cron as app user, then drop to app for main process.
# MCP_MODE: api = only main process (no ingest/cron/watchdog/load-snippets); full = all background jobs (default).
if [ "$(id -u)" = "0" ]; then
  _mcp_mode="${MCP_MODE:-full}"
  if [ "$_mcp_mode" = "api" ]; then
    # Режим только MCP: chown в фоне, чтобы не блокировать старт (/data может быть огромным).
    [ -d /data ] && ( chown -R app:app /data 2>/dev/null & )
  else
    [ -d /data ] && chown -R app:app /data 2>/dev/null || true
  fi
  if [ "$_mcp_mode" != "api" ]; then
    # Exclude EMBEDDING_API_KEY from .ingest_env (security: no secrets on disk)
    env | grep -E '^(QDRANT_|HELP_|INGEST_|WATCHDOG_|MEMORY_|SNIPPETS_|STANDARDS_|ONEC_CONFIG_)' | sed 's/^/export /' > /app/.ingest_env 2>/dev/null || true
    env | grep -E '^EMBEDDING_(BACKEND|MODEL|API_URL|DIMENSION|BATCH_SIZE|WORKERS|FORCE_BATCH|TIMEOUT)=' | sed 's/^/export /' >> /app/.ingest_env 2>/dev/null || true
    chown app:app /app/.ingest_env 2>/dev/null || true
    # INGEST_WORKER=1: только cron (ingest и watchdog по расписанию), без фоновых процессов
    if [ "$INGEST_WORKER" = "1" ]; then
      crontab -u app /app/crontab 2>/dev/null || true
      cron
    elif [ -d /opt/1cv8 ]; then
      crontab -u app /app/crontab 2>/dev/null || true
      cron
      # Restart ingest on exit (e.g. Bus error / OOM) so index keeps progressing
      ( gosu app sh -c '. /app/.ingest_env 2>/dev/null; cd /app && while true; do python -m onec_help ingest >> /app/var/log/ingest.log 2>&1; _e=$?; echo "[ingest] exit $_e, restart in 60s" >> /app/var/log/ingest.log; sleep 60; done' ) &
      if [ "$WATCHDOG_ENABLED" = "1" ]; then
        ( gosu app sh -c '. /app/.ingest_env 2>/dev/null; cd /app && python -m onec_help watchdog >> /app/var/log/watchdog.log 2>&1' ) &
      fi
    fi
  fi
  exec gosu app "$@"
fi
exec "$@"
