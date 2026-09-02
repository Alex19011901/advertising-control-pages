# Advertising Control Pages

Public GitHub Pages dashboard for connecting Yandex Direct advertising spend with real Lead Control leads.

Pages URL:

https://alex19011901.github.io/advertising-control-pages/

## Data Flow

1. GitHub Actions workflow `advertising-control-refresh.yml` is started manually with `workflow_dispatch`.
2. `scripts/fetch_direct.py` reads Yandex Direct Reports API in read-only mode.
3. `scripts/build_dashboard.py` builds `data/dashboard.json` from Direct data and the public Lead Control dashboard JSON.
4. GitHub Pages is updated from the generated static artifact.

No demo advertising numbers are committed or rendered. Until Direct API access is approved and `YANDEX_DIRECT_TOKEN` is configured, the dashboard shows `Нет данных` and a clear access status.

## Secrets

Required for Yandex Direct:

`YANDEX_DIRECT_TOKEN`

The token must be stored only as a GitHub Actions secret. It must never be committed, printed, or copied into logs.

Configured Direct client login:

`e-20027205`

## Sources

- Yandex Direct Reports API: https://yandex.ru/dev/direct/doc/en/reports
- Yandex Direct request headers: https://yandex.ru/dev/direct/doc/en/concepts/headers
- Yandex Direct report fields: https://yandex.ru/dev/direct/doc/en/fields-list
- Lead Control public JSON: https://alex19011901.github.io/lead-control-pages/dashboard_view.json

## Local Build

```bash
python3 scripts/fetch_direct.py
python3 scripts/build_dashboard.py
```

Without `YANDEX_DIRECT_TOKEN`, the first command writes a clear `missing_secret` status and exits successfully.
