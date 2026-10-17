# Vercel Deployment Guide

This project runs on Vercel as a Python Flask app through `server.py`.
Because Vercel functions are request-driven, lightning history collection uses
an authenticated HTTP cron endpoint that an external scheduler calls
periodically.

## 1. Vercel Environment Variables

Set these variables in Vercel Project Settings:

Required:
- `FLASK_ENV=production`
- `FLASK_CONFIG=production`
- `SECRET_KEY`
- `DATABASE_URL`
- `CRON_SECRET`

Required for registration and password-reset emails (these must be copied
explicitly when moving from Cloud Run or another host):
- `MAIL_SERVER`
- `MAIL_PORT=587`
- `MAIL_USE_TLS=true`
- `MAIL_USERNAME`
- `MAIL_PASSWORD` (store as a Secret; use the sender's SMTP app password)

Redeploy after changing production environment variables. Verify delivery to
the intended recipient; a rendered confirmation page does not prove delivery.

Recommended for Vercel:
- `LIGHTNING_COLLECTOR_ENABLED=false`
- `USE_SAMPLE_WEATHER_DATA=false`
- `WEATHER_STATUS_CACHE_SECONDS=30`
- `WEATHER_API_TIMEOUT_SECONDS=4`
- `LIGHTNING_SNAPSHOT_CACHE_SECONDS=30`
- `LIGHTNING_HISTORY_CACHE_SECONDS=60`
- `DB_CONNECT_TIMEOUT=5`
- `DB_STATEMENT_TIMEOUT_MS=8000`
- `DB_POOL_TIMEOUT=10`
- `DB_POOL_RECYCLE=1800`

Feature variables:
- `NEA_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBED_MODEL`
- `CHATBOT_INTENT_API_KEY`
- `CHATBOT_INTENT_BASE_URL`
- `CHATBOT_INTENT_MODEL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_DOCS_TABLE`
- `SUPABASE_MATCH_FUNCTION`
- `SUPABASE_CHAT_LOG_TABLE`
- `SUPABASE_INTENT_LLM_FAILURE_TABLE`
- `SUPABASE_QA_LLM_FAILURE_TABLE`
- `CHATBOT_TOP_K`
- `CHATBOT_MIN_SCORE`
- `CHATBOT_MAX_CONTEXT_CHARS`
- `CHATBOT_DB_TOOL_MAX_CALLS`

## 2. Generate Secrets

Use long random values. Do not commit them to git.

PowerShell:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate one value for `SECRET_KEY` and another for `CRON_SECRET`.

## 3. Deploy to Vercel

1. Import the GitHub repository in Vercel or link the local project with
   `npx vercel link`.
2. Add the environment variables above in Vercel Project Settings.
3. Confirm `vercel.json` is deployed with `"regions": ["sin1"]` for Singapore
   users and NEA API proximity. If your production database is not in Singapore,
   choose the Vercel region closest to the database instead.
4. Deploy by pushing to the connected production branch, or run
   `deploy_update.bat` for a manual CLI production deploy.
5. Confirm the homepage loads.
6. Confirm the cron endpoint rejects public access:

```text
https://YOUR_DOMAIN/api/cron/collect-lightning
```

Expected response:

```json
{"error":"Not found."}
```

7. Confirm the cron endpoint works with the secret:

```text
https://YOUR_DOMAIN/api/cron/collect-lightning?secret=YOUR_CRON_SECRET
```

Expected response:

```json
{"ok":true}
```

## 4. Configure cron-job.org

Create a cron-job.org job:

- URL: `https://YOUR_DOMAIN/api/cron/collect-lightning?secret=YOUR_CRON_SECRET`
- Method: `GET`
- Schedule: every 2 minutes
- Timeout: default is fine
- Failure notifications: enabled

The endpoint returns a short JSON response so it stays within cron-job.org's
30-second execution limit.

### Community bot schedule

The `NTU Pool Community Bot` job (cron-job.org job `8663575`) calls
`https://www.ntupool.org/api/cron/community-posts` every 30 minutes from
07:00 through 21:30, UTC+8 (`*/30 7-21 * * *`, Asia/Shanghai).
The app still applies its operating-hours buffer and daily action limits.
Use the `Authorization: Bearer <CRON_SECRET>` request header, a 30-second
timeout, and saved responses for verification. Do not put the secret in the URL.

This replaces the GitHub Actions schedule; the repository workflow is now
manual-only. After restoring GitHub repository access, sync this workflow
change before re-enabling Actions to avoid running two schedules.

## 5. Runtime Model

Vercel functions are started on demand and may be frozen after a request, so
long-running background threads are not reliable for production collection.

With this setup:
- Vercel serves the website and Flask API.
- `LIGHTNING_COLLECTOR_ENABLED=false` prevents an unreliable background thread.
- cron-job.org calls `/api/cron/collect-lightning` every 2 minutes.
- The endpoint stores lightning snapshots in the existing database.
- `/weather/lightning-history` continues to read persisted snapshot history.
