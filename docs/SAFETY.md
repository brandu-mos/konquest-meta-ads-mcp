# Safety Model

## Three Tiers

### Tier 1 - Mandatory Confirmation
High-risk actions requiring explicit user approval before execution.
- PAUSED -> ACTIVE
- Budget increase > 30% on active objects
- Creative swap on active ads
- Optimization event changes on active ad sets
- Pixel/dataset remapping
- Catalog connection changes
- Bulk mutations > 5 objects

### Tier 2 - Dry-Run Preview
Moderate-risk actions that show a preview before confirmation.
- Targeting changes on active ad sets
- Bid strategy changes on active campaigns
- Budget increase 15-30% on active
- Placement changes on active ads

### Tier 3 - Unrestricted
Safe actions that execute without gates.
- All reads
- Creates (always PAUSED)
- Pausing (stops spend)
- Budget decreases
- Updates to PAUSED objects

## Configurable Thresholds
Edit `config/thresholds.yaml` to adjust:
- budget_increase_confirm_pct (default: 30)
- budget_increase_preview_pct (default: 15)
- bulk_mutation_confirm_count (default: 5)

## Greek Text Safety
All Greek text passes through validation before and after API writes.
See `meta_ads_mcp/validators/greek_text.py` for the full pipeline.

## Rollback
Pre-mutation snapshots stored in `rollback/{client-slug}/`.
30-day retention. Can restore previous state on demand.
