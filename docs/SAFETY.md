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

## Rate Limit Protection

All write operations are protected by a multi-layer rate limit system:

### Layer 1: Pre-write gate
`enforce_rate_gate()` runs before every campaign, ad set, and ad write. If usage is above 80% (critical) or 95% (blocked), the operation is rejected before touching the API.

### Layer 2: Inter-request throttle
Every `POST` to the Meta API includes a minimum 100ms delay. This keeps burst write rate safely under Meta's 100 QPS hard cap.

### Layer 3: Retry with backoff
Rate limit errors (codes 4, 17, 32, 613, 80000-80004) trigger automatic retry with exponential backoff (base 2s, max 5 retries, max wait 300s). When `estimated_time_to_regain_access` is set in the response, that value (in minutes) takes priority over the backoff formula.

### What gets monitored
All three rate limit headers are tracked: `x-app-usage`, `x-ad-account-usage`, and `x-business-use-case-usage`. BUC is the critical one for the Marketing API - it's what exhausts first in practice.

## Greek Text Safety
All Greek text passes through validation before and after API writes.
See `meta_ads_mcp/validators/greek_text.py` for the full pipeline.

## Rollback
Pre-mutation snapshots stored in `rollback/{client-slug}/`.
30-day retention. Can restore previous state on demand.
