# guideline-copilot
Guideline Copilot

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app
curl localhost:8000/health
```

`GET /health` returns:

```json
{"status": "ok", "model": "claude-sonnet-5-5", "index_size": 0, "last_ingest_at": null}
```

Config via env: `MODEL_NAME`, `INDEX_DIR` (default `./data`).

Ingest documents (one per line): `python -m app.ingest docs.txt`

## Test

```bash
pytest
```
