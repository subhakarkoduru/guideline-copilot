# guideline-copilot
Guideline Copilot

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -c constraints.txt -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1
curl localhost:8000/health
```

Without `HEALTH_TOKEN`, `GET /health` always returns just `{"status": "ok"}`
(whatever `APP_ENV` is). To see details, set a token and send it:

```bash
export HEALTH_TOKEN=$(openssl rand -hex 32)
uvicorn app.main:app --host 127.0.0.1
curl -H "Authorization: Bearer $HEALTH_TOKEN" localhost:8000/health
```

```json
{"status": "ok", "model": "claude-sonnet-5-5", "index_size": 0, "last_ingest_at": null}
```

Bind to `127.0.0.1` unless you deliberately expose the service; `APP_ENV=development`
also serves `/docs`, `/redoc` and `/openapi.json`, so do not combine it with a public interface.

Config via env:

| Var | Default | Purpose |
|---|---|---|
| `MODEL_NAME` | `claude-sonnet-5-5` | Model name reported by `/health` |
| `INDEX_DIR` | `./data` | Where `index.json` / `meta.json` live |
| `APP_ENV` | `production` | `development` enables `/docs`, `/redoc`, `/openapi.json`. Has no effect on `/health` detail |
| `HEALTH_TOKEN` | unset | Min 32 chars (startup/validation error otherwise). If set, `/health` returns details only with `Authorization: Bearer <token>`; if unset, `/health` is always `{"status": "ok"}` |
| `MAX_INGEST_BYTES` | `10485760` | Max size of an ingest input file |

A corrupt `index.json` makes ingest fail with an error instead of being reset;
fix or remove the file manually.

Ingest documents (one per line): `python -m app.ingest docs.txt`. Ingests take an exclusive
lock (`<INDEX_DIR>/.lock`, `fcntl.flock`, POSIX only) so concurrent runs do not drop documents.
`/health` trusts the `index_size` in `meta.json` only if it matches a fingerprint of `index.json`;
otherwise (legacy meta, crash between writes, direct `add`) it counts the index, so it is never stale.

`constraints.txt` pins the tested dependency versions (regenerate with `pip list --format=freeze`); run `pip-audit` periodically.

## Test

```bash
pytest
```
