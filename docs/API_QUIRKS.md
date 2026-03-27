# Meta API Quirks

Key issues to be aware of when working with the Meta Marketing API:

1. **Frequency cap invisibility** - Only visible with REACH optimization
2. **Phantom fields** - Not in response != not set
3. **DOF silent failures** - URL in asset_feed_spec breaks multi-image
4. **FLEX mismatch error 3858355** - Can't swap creative, must create new ad
5. **Legacy objectives return 400** - Use OUTCOME_* only
6. **Budget format** - Cents as strings
7. **instagram_actor_id deprecated** - Use instagram_user_id instead

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
API v21.0+ only accepts OUTCOME_* objectives. Legacy objectives (CONVERSIONS, LINK_CLICKS, etc.) return error 400. Use OUTCOME_SALES, OUTCOME_TRAFFIC, etc.

### 6. Budget Format
Daily and lifetime budgets must be passed as strings representing cents. EUR 10.00 = "1000".

### 7. instagram_user_id
The `instagram_actor_id` field is deprecated. Use `instagram_user_id` for setting the Instagram identity on ad creatives.
