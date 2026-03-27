# Vault Schema for Meta Ads

## Per-Client Structure
```
01_CLIENTS/{slug}/meta-ads/
├── account-map.md          # IDs, mappings, archetype
├── tracking-diagnostics.md # Pixel health, event status
├── catalog-status.md       # Feed health, product sets
├── mutation-log.md         # All write actions (90-day retention)
├── rollback-index.md       # Pointers to rollback snapshots
├── reporting-preferences.md # Delivery channel, language, format
├── platform-exceptions.md  # Known quirks, workarounds
├── creative-intelligence.md # Hook patterns, format performance
├── value-intelligence.md   # Product values, revenue gaps, estimation data (v1.5)
└── url-intelligence.md     # Product-to-URL mappings, match keys (v1.5)
```

## Data Classification
- **Operational identifiers** (account IDs, pixel IDs): Allowed in vault
- **Secrets** (tokens, API keys): NEVER in vault
- **Performance data**: Summarized in vault, raw data stays local
- **Debug artifacts**: Local only (7-day retention)
- **Value intelligence**: Reusable product prices and value gap alerts
- **URL intelligence**: Reusable product-to-URL mappings

## Retention
- mutation-log.md: 90 days, then summarize
- Rollback snapshots: 30 days (local JSON files)
- Debug artifacts: 7 days
- value-intelligence.md: Entries re-verified every 30 days
- url-intelligence.md: Entries re-verified every 30 days

## v1.5: value-intelligence.md

Stores per-product value data for revenue estimation when Meta tracking is incomplete.

```markdown
## Product Values (last updated: YYYY-MM-DD)

| Product | SKU/ID | Value | Currency | Source | Confidence | Updated |
|---------|--------|-------|----------|--------|------------|---------|
| ... | ... | ... | ... | ... | ... | ... |

## Value Gap Alerts
- {campaign}: {N} purchases tracked, EUR 0 revenue. Pixel not passing value param.
```

### Write rules
- Only write when confidence >= medium.
- Never overwrite meta_tracked_value with a weaker source.
- Update timestamps on every refresh.
- Stale entries (> 30 days) re-verify before use.

## v1.5: url-intelligence.md

Stores resolved product-to-URL mappings for reuse across manifests and campaigns.

```markdown
## Product URL Mappings (last updated: YYYY-MM-DD)

| Product | Match Keys | URL | Type | Source | Confidence | Updated |
|---------|-----------|-----|------|--------|------------|---------|
| ... | ... | ... | ... | ... | ... | ... |

## Unresolved / Pending Confirmation
- "{product}" -> candidates: {url1} ({score}), {url2} ({score}). NEEDS CONFIRMATION.
```

### Write rules
- Only write when confidence >= medium.
- Never overwrite manifest_explicit or human_confirmed with a weaker source.
- Match keys: lowercase, stemmed where useful.
- Stale entries (> 30 days) re-verify before use.
- Unresolved entries stay in "Pending Confirmation" until resolved.
