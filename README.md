# pow-radar

GitHub PoW/GPU mining project radar. This V1 discovers repositories, collects metadata, scores candidates, detects conservative mining signals, and optionally sends Telegram alerts.

## Safety
The system is read-only. It never executes repository code, downloads or runs miners/wallets, imports keys, or invests funds. P0 alerts require manual verification.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
pow-radar discover
pow-radar collect
pow-radar score
pow-radar detect-signals
pow-radar send-alerts
```

For PostgreSQL, set `DATABASE_URL=postgresql+psycopg://powradar:powradar@db:5432/powradar` and run `docker compose up --build`.
SQLite is supported for local development and tests. GitHub API access is rate limited; `GITHUB_TOKEN` is recommended. The collector uses the REST API and does not execute checked-out project code.

## Scoring
Team 30, development 25, GPU mining 25, timing/fairness 20. Qualified defaults are total >=75, team >=18, GPU >=16, and no hard rejection. Rules live in `config/score_rules.yaml`.

## Alerts
Telegram is skipped safely if credentials are absent. Alerts are deduplicated by event hash. P0 is intentionally conservative and requires node, PoW parameters, miner, wallet plus three independent evidence flags; review source/release correspondence, binary hashes, premine, launch parameters, and independent mining results before using any hardware.

## Tests
`pytest` runs offline unit tests. External GitHub, PostgreSQL, and Telegram integrations should be tested separately with mocks.
