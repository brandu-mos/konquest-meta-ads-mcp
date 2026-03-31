# Meta API Quirks

Key issues to be aware of when working with the Meta Marketing API:

1. **Frequency cap invisibility** - Only visible with REACH optimization
2. **Phantom fields** - Not in response != not set
3. **DOF silent failures** - URL in asset_feed_spec breaks multi-image
4. **FLEX mismatch error 3858355** - Can't swap creative, must create new ad
5. **Legacy objectives return 400** - Use OUTCOME_* only
6. **Budget format** - Cents as strings
7. **instagram_actor_id deprecated** - Use instagram_user_id instead
8. **BUC rate limits hit first** - `x-business-use-case-usage` exhausts before app-level limits
9. **Retrying during throttle extends the block** - Never send requests while throttled
10. **estimated_time_to_regain_access is authoritative** - Use it, not exponential backoff

## Details

### 1. Frequency Cap Invisibility
Frequency caps set on ad sets are only returned in the API response when the optimization goal is REACH. For other goals, the cap may be active but invisible in the response.

### 2. Phantom Fields
If a field is not present in the API response, it does not mean it is unset. Some fields only appear when explicitly requested via the `fields` parameter. Always request the fields you need.

### 3. DOF Silent Failures
When using Dynamic Optimized Feed (asset_feed_spec), including a URL in the spec can silently break multi-image delivery. The campaign will appear to work but only serve single images.

### 4. FLEX Mismatch Error 3858355
You cannot swap the creative on an existing ad if the new creative has a different format (e.g., image to video). You must create a new ad and pause the old one.

### 5. Legacy Objectives
API v25.0+ only accepts OUTCOME_* objectives. Legacy objectives (CONVERSIONS, LINK_CLICKS, etc.) return error 400. Use OUTCOME_SALES, OUTCOME_TRAFFIC, etc.

### 6. Budget Format
Daily and lifetime budgets must be passed as strings representing cents. EUR 10.00 = "1000".

### 7. instagram_user_id
The `instagram_actor_id` field is deprecated. Use `instagram_user_id` for setting the Instagram identity on ad creatives.

### 8. BUC Rate Limits Hit First
The Marketing API uses three rate limit systems. In practice, `x-business-use-case-usage` (BUC) is exhausted first - not the app-level `x-app-usage`. The BUC quota scales with your active ad count: `300 + (40 x active_ads)` calls/hour on Standard Access. Monitoring only `x-app-usage` gives a false sense of headroom.

Error codes for BUC throttle: **80000, 80001, 80002, 80003, 80004** (all recoverable with backoff).

### 9. Retrying During Throttle Extends the Block
Meta explicitly documents that sending API requests while throttled extends your block duration. When you receive a rate limit error, stop all requests until the block clears. The `estimated_time_to_regain_access` field in the BUC header tells you exactly how long to wait (in minutes).

### 10. estimated_time_to_regain_access is Authoritative
When throttled (80000-80004), read `estimated_time_to_regain_access` from `x-business-use-case-usage`. This field tells you the exact wait in minutes (real-world values: 32-47 min when significantly over quota). Ignore this and use short exponential backoff at your own risk - it will extend the block.
