# NeXa — Vercel deployment

NeXa is now a Next.js web client with a FastAPI Vercel Function and PostgreSQL
storage. The original `app.py` Streamlit interface remains only as a local
reference while the production UI is expanded; it is **not** part of the Vercel
deployment.

## Production architecture

```
Browser (Next.js) ── password ──> /api (FastAPI Vercel Function) ──> Postgres
                                      │
                                      └── existing financial calculation engine
```

The API does not use local files for data. `DATABASE_URL` takes precedence over
`POSTGRES_URL`, which lets it work with either Vercel Postgres or another managed
PostgreSQL provider. The application refuses to serve financial data if
`NEXA_PASSWORD` has not been configured.

## Deploy to Vercel

1. Import this GitHub repository in Vercel; Vercel detects Next.js.
2. Create a Vercel Postgres database and connect it to the project, or configure
   `DATABASE_URL` for a managed PostgreSQL database.
3. Add a long random `NEXA_PASSWORD` to Production, Preview, and Development
   environment variables. Do not expose it as a `NEXT_PUBLIC_*` value.
4. Deploy. Open `/api/health` to confirm database connectivity, then open `/` and
   enter the password into the unlock screen. The password is stored only in browser
   session storage.
5. If historical SQLite data needs to move and you have the connection string, take a backup, inspect source counts,
   then run `DATABASE_URL=... python scripts/data_migration/sqlite_to_postgres.py data/finance_customs.db` from a trusted local environment. Alternatively, gzip the database and upload its `.db.gz` file through the password-protected **Restore existing NeXa data** panel. The panel refuses to run when the target database already contains records.

For a financial production deployment, also enable Vercel Deployment Protection
and restrict the Vercel project to authorised team members.

## Local checks

```bash
npm ci
npm run build
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The Vercel build only needs `requirements.txt`; `requirements-dev.txt` is for
local tests. The old local Streamlit interface needs `requirements-streamlit.txt`.
