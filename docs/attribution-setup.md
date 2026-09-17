# Attribution setup

Advertising Control is a static GitHub Pages dashboard. It does not receive Tilda webhooks directly. The chain is:

1. Tilda sends leads to Lead Control.
2. Lead Control publishes `advertising_leads.json` with hashed `metrika_client_id`.
3. This repository fetches Yandex Direct spend and Yandex Metrika `52597240` Logs API.
4. `scripts/build_dashboard_with_metrika.py` joins leads to Metrika visits by hashed ClientID and then to Direct campaign/group/ad IDs.

## Required GitHub Actions secrets

- `YANDEX_DIRECT_TOKEN`
- `YANDEX_METRIKA_READ_TOKEN`

The Direct client login is configured as `e-20027205`. The target Metrika counter is `52597240`.

## Tilda / Lead Control requirement

Every Tilda form must pass these fields into Lead Control:

- `metrika_client_id`
- `yclid`
- `utm_source`
- `utm_medium`
- `utm_campaign`
- `utm_content`
- `utm_term`
- page URL / landing URL / referrer if Lead Control supports them

Advertising Control only receives hashed identifiers from Lead Control. If `advertising_leads.json` has `has_metrika_client_id: false`, the dashboard will correctly show the lead as `Нет ClientID` and will not guess the ad source.

Use the ready snippet from `docs/tilda-clientid-snippet.html` in Tilda page/site custom code so every form receives the hidden fields before submit.

## UTM campaign fallback

If Metrika has ClientID and UTM campaign but not Direct IDs, the dashboard can use exact UTM campaign mappings from:

```text
data/utm_campaign_map.json
```

Example:

```json
{
  "schema_version": 1,
  "campaigns": {
    "Svadba_poisk": "118776779"
  }
}
```

Keep this file exact. Do not map broad labels when the same `utm_campaign` can belong to multiple campaigns.
