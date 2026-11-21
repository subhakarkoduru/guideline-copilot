# guideline-copilot
Guideline Copilot

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -c constraints.txt -e ".[dev]"
APP_ENV=development uvicorn app.main:app
curl localhost:8000/health
```

`GET /health` returns:

```json
{"status": "ok", "model": "claude-sonnet-5-5", "index_size": 0, "last_ingest_at": null}
```

`/health` detail fields are only returned to authorised callers; otherwise the
response is just `{"status": "ok"}`.

Config via env:

| Var | Default | Purpose |
|---|---|---|
| `MODEL_NAME` | `claude-sonnet-5-5` | Model name reported by `/health` |
| `INDEX_DIR` | `./data` | Where `index.json` / `meta.json` live |
| `APP_ENV` | `production` | `development` enables `/docs`, `/redoc`, `/openapi.json` and detailed `/health` when no token is set |
| `HEALTH_TOKEN` | unset | If set, `/health` returns details only with `Authorization: Bearer <token>` |
| `MAX_INGEST_BYTES` | `10485760` | Max size of an ingest input file |

A corrupt `index.json` makes ingest fail with an error instead of being reset;
fix or remove the file manually.

Ingest documents (one per line): `python -m app.ingest docs.txt`

`constraints.txt` pins the tested dependency versions (regenerate with `pip list --format=freeze`); run `pip-audit` periodically.

## Test

```bash
pytest
```
