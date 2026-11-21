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
| `HEALTH_TOKEN` | unset | If set, `/health` returns details only with `Authorization: Bearer <token>` (scheme case-insensitive); if unset, `/health` is always `{"status": "ok"}`. Rules: printable ASCII, no whitespace/control characters, at least 32 chars, and not weak (>= 8 distinct chars, no repeating period, no single char over 40%, not mostly sequential, entropy >= 2.5 bits/char). `openssl rand -hex 32` and `openssl rand -base64 32` pass. See below for what happens if it is invalid |
| `MAX_INGEST_BYTES` | `10485760` | Max size of an ingest input file |

Settings are read and validated once, when the app starts (`create_app()`, i.e. on `uvicorn app.main:app` import). An invalid `HEALTH_TOKEN` makes startup fail with a `SettingsError` that names the problem but never contains the token (the value is held as a `SecretStr` and checked outside pydantic's validation, so it is also absent from `.errors()`). Changing env vars requires a restart; `/health` never re-validates, so a bad token cannot cause per-request 500s. The ingest CLI prints the same error and exits 1.

A corrupt `index.json` makes ingest fail with an error instead of being reset;
fix or remove the file manually.

Ingest documents (one per line): `python -m app.ingest docs.txt`. Ingests take an exclusive
lock (`<INDEX_DIR>/.lock`, `fcntl.flock`, POSIX only) so concurrent runs do not drop documents.
`/health` trusts the `index_size` in `meta.json` only if it matches a fingerprint of `index.json`;
otherwise (legacy meta, crash between writes, direct `add`) it recounts `index.json` (once per fingerprint, cached).
This is best-effort, not a guarantee: `meta.json` is unauthenticated and the `[size, mtime_ns, inode]`
fingerprint can in theory collide or be forged by anyone with write access to `INDEX_DIR`, so treat `index_size` as advisory.

The lock file is opened with `O_NOFOLLOW` (mode 0600) and waiting is bounded (30s, then a clear `IndexLockTimeout`). A symlinked `.lock` is refused with an `IndexLockError` naming the path; the ingest CLI reports lock errors as `error: ...` with exit 1.
`flock` is unreliable on NFS and some network filesystems; keep `INDEX_DIR` on a local disk.

`constraints.txt` pins the tested dependency versions (regenerate with `pip list --format=freeze`); run `pip-audit` periodically.

## Test

```bash
pytest
```
