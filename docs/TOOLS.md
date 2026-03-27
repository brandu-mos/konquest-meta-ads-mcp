# Meta Ads MCP - Tool Reference

## Phase v1.0 - Foundation (6 tools)

### check_token_status [production-safe]
Check Meta API token health, permissions, and rate limit status.

### get_ad_accounts [production-safe]
List all ad accounts accessible to the authenticated user.
- `limit` (int, default 50): Maximum accounts to return.

### get_account_info [production-safe]
Get detailed information about a specific ad account.
- `account_id` (str): Ad account ID (e.g., 'act_123456789').

### get_account_pages [production-safe]
List Facebook Pages available for ads on a specific ad account.
- `account_id` (str): Ad account ID.

### get_instagram_identities [production-safe]
List Instagram accounts available for ads. Returns instagram_user_id (canonical).
- `account_id` (str): Ad account ID.

### discover_all_accounts [production-safe]
Discover all ad accounts, pages, pixels, and Instagram accounts for registry generation.

## Phase v1.1 Wave 1 - Campaign/AdSet/Ad Reads (6 tools)

### get_campaigns [production-safe]
List campaigns for an ad account with status, budget, and objective info.
- `account_id` (str): Ad account ID.
- `status_filter` (str, optional): 'ACTIVE', 'PAUSED', 'ARCHIVED', or 'ALL'.
- `limit` (int, default 50): Max results per page. Auto-paginates up to 200.

### get_campaign_details [production-safe]
Get full campaign details including bid strategy, special categories, and ad set count.
- `campaign_id` (str): Campaign ID.

### get_adsets [production-safe]
List ad sets for an account or specific campaign.
- `account_id` (str): Ad account ID.
- `campaign_id` (str, optional): Filter to a specific campaign.
- `status_filter` (str, optional): 'ACTIVE', 'PAUSED', etc.
- `limit` (int, default 50): Max results.

### get_adset_details [production-safe]
Get detailed ad set info including targeting, optimization, learning stage, and ad count.
- `adset_id` (str): Ad set ID.

### get_ads [production-safe]
List ads for an account, campaign, or ad set.
- `account_id` (str): Ad account ID.
- `campaign_id` (str, optional): Filter by campaign.
- `adset_id` (str, optional): Filter by ad set (takes precedence).
- `status_filter` (str, optional): 'ACTIVE', 'PAUSED', etc.
- `limit` (int, default 50): Max results.

### get_ad_details [production-safe]
Get full ad details with creative resolution (fetches creative spec inline).
- `ad_id` (str): Ad ID.

## Phase v1.1 Wave 2 - Insights & Performance (1 tool)

### get_insights [production-safe]
Get performance insights for any Meta Ads object with objective-aware metric normalization.
- `object_id` (str): Account (act_XXX), campaign, ad set, or ad ID.
- `time_range` (str, default 'last_7d'): Date preset or 'YYYY-MM-DD,YYYY-MM-DD'.
- `breakdowns` (str, optional): Comma-separated dimensions (e.g. 'age,gender').
- `level` (str, optional): Aggregation: 'campaign', 'adset', 'ad'.
- `archetype` (str, default 'hybrid'): 'ecommerce', 'lead_gen', 'awareness', 'traffic', 'hybrid', 'messages'.
- `compact` (bool, default true): Include operator-friendly summary.
- `limit` (int, default 50): Max rows for breakdown/level queries.

**Normalized metrics:** spend, impressions, reach, frequency, clicks, CTR, CPC, CPM, purchases, CPA, leads, CPL, ROAS, revenue, add_to_cart, initiate_checkout, landing_page_views, video_views.

**Archetype-aware:** Ecommerce gets purchases/ROAS/revenue. Lead gen gets leads/CPL. Awareness gets frequency/video_views. Hybrid gets everything.

## Phase v1.1 Wave 3 - Creative Reads (2 tools)

### get_ad_creatives [production-safe]
List creatives for an account or resolve the creative for a specific ad.
- `account_id` (str): Ad account ID (needed for image hash resolution).
- `ad_id` (str, optional): If provided, returns only the creative for that ad.
- `limit` (int, default 50): Max results for account listing.

Returns creative_mode classification (simple/dynamic/dof) and resolved media URLs.

### get_creative_details [production-safe]
Get full creative spec with mode classification, media extraction, copy parsing, and identity info.
- `creative_id` (str): Creative ID.
- `account_id` (str, optional): For image hash -> URL resolution.

Returns: creative_mode, media (images/videos with URLs), copy (message/headline/CTA/link), identity (instagram_user_id vs deprecated instagram_actor_id).

## Phase v1.1 Wave 4 - Tracking Diagnostics (5 tools)

### get_pixel_info [production-safe]
Get pixel status, creation time, last fired time, and availability.
- `pixel_id` (str): Pixel ID.

### get_pixel_events [production-safe]
Get events received by a pixel in the last 24 hours, aggregated by event type.
- `pixel_id` (str): Pixel ID.

Returns event names, counts, total fires, and hourly bucket count.

### get_event_stats [production-safe]
Get event statistics with archetype-aware diagnostic analysis.
- `pixel_id` (str): Pixel ID.
- `archetype` (str, default 'hybrid'): Account archetype for requirement matching.

Returns health classification (healthy/partial/degraded/never_fired/missing), severity-ranked issues with fix suggestions, event coverage, and value parameter checks.

### send_test_event [advisory-only]
Send a test event via the Conversions API Test Events endpoint.
- `pixel_id` (str): Pixel ID.
- `event_name` (str, default 'PageView'): Event name.
- `test_event_code` (str, optional): Code from Events Manager.
- `custom_data` (str, optional): JSON string of custom params.

### run_tracking_diagnostic [advisory-only]
Run comprehensive tracking diagnostic for an ad account - checks all pixels, events, da_checks, and objective-tracking alignment.
- `account_id` (str): Ad account ID.
- `archetype` (str, default 'hybrid'): Account archetype.

Returns aggregate health, all detected events, severity-ranked issues, and campaign-objective alignment warnings.

## Phase v1.1 Wave 5 - Catalog & Connections (6 tools)

### get_catalog_info [production-safe]
Get catalog details including product count, connected pixels, product sets, and feeds.
- `catalog_id` (str): Product catalog ID.

### get_catalog_products [production-safe]
List products with price, availability, review status, and aggregate stats.
- `catalog_id` (str): Product catalog ID.
- `limit` (int, default 25): Max products to return.
- `filter_availability` (str, optional): 'in stock', 'out of stock', 'discontinued'.

Returns price range, availability breakdown, and review status breakdown.

### get_product_sets [production-safe]
List product sets with product counts and filter rules. Flags empty sets.
- `catalog_id` (str): Product catalog ID.

### validate_catalog_connections [advisory-only]
Validate the full catalog-pixel-account-page connection chain for DPA readiness.
- `catalog_id` (str): Product catalog ID.
- `account_id` (str, optional): Ad account to verify.
- `pixel_id` (str, optional): Pixel to verify connection.
- `page_id` (str, optional): Page to verify connection.

Returns health classification, connection status map, severity-ranked issues with fix suggestions.

### create_product_set [NOT REGISTERED - code exists, disabled]
Create a product set with filter rules.
- `catalog_id` (str): Product catalog ID.
- `name` (str): Product set name.
- `filter_rules` (dict): Filter rules for the product set.

### update_product_set [NOT REGISTERED - code exists, disabled]
Update a product set name or filter rules.
- `product_set_id` (str): Product set ID.
- `name` (str, optional): New name.
- `filter_rules` (dict, optional): New filter rules.

## Phase v1.1 Wave 6 - Audiences & Targeting (4 tools)

### list_custom_audiences [production-safe]
List custom audiences with type classification, size estimates, delivery status, and diagnostic warnings.
- `account_id` (str): Ad account ID.
- `limit` (int, default 50): Max audiences.

Returns subtype breakdown, unusable count, per-audience size_class (empty/too_small/small/healthy/very_large), usability flag, and severity-ranked warnings for stale/errored/too-small audiences.

### search_interests [production-safe]
Search interest-based targeting options with audience size estimates.
- `query` (str): Search term (e.g., 'hospitality', 'skincare').
- `limit` (int, default 20): Max results.

Returns ID, name, audience size range, size_class (very_narrow to very_broad), topic, and path.

### search_behaviors [production-safe]
Search or list behavior-based targeting options.
- `query` (str, optional): Filter keyword. Omit to list all behaviors.
- `limit` (int, default 30): Max results.

Returns ID, name, audience size, and category.

### search_geo_locations [production-safe]
Search geographic locations for ad targeting.
- `query` (str): Location name (e.g., 'Greece', 'Athens', 'Crete').
- `location_type` (str, default 'country'): 'country', 'region', 'city', 'zip', 'geo_market'.
- `limit` (int, default 10): Max results.

Returns targeting_key, full_path hierarchy, country_code, and type.

## Phase v1.3 - Paused-Only Write Corridor (18 tools)

### create_campaign [supervised-only]
Create a new campaign (always PAUSED, hard enforced, no override).
- `account_id` (str): Ad account ID.
- `name` (str): Campaign name. Greek text validated for encoding integrity.
- `objective` (str): Outcome-based only: OUTCOME_AWARENESS, OUTCOME_ENGAGEMENT, OUTCOME_LEADS, OUTCOME_SALES, OUTCOME_TRAFFIC, OUTCOME_APP_PROMOTION.
- `special_ad_categories` (str, optional): Comma-separated: CREDIT, EMPLOYMENT, HOUSING, ISSUES_ELECTIONS_POLITICS.

**Safety corridor:**
1. Input validation - rejects legacy/unknown objectives, invalid categories
2. Pre-write validation (categories B, C, E, F) - blocks on fail
3. Pre-write snapshot - records account state
4. API call - creates campaign as PAUSED
5. Post-write verification - reads back and verifies status/objective/name match
6. Mutation log - human-readable summary

Returns: campaign_id, validation result, verification result, rollback reference, mutation log entry.

### update_campaign [supervised-only]
Update an existing campaign.
- `campaign_id` (str): Campaign ID.
- `name` (str, optional): New campaign name.
- `daily_budget` (float, optional): New daily budget in EUR.
- `lifetime_budget` (float, optional): New lifetime budget in EUR.
- `bid_strategy` (str, optional): New bid strategy.
- `status` (str, optional): New status.

### create_adset [supervised-only]
Create a new ad set (always PAUSED) with ABO/CBO enforcement, parent inspection, and full validation corridor.
- `account_id` (str): Ad account ID.
- `campaign_id` (str): Parent campaign ID.
- `name` (str): Ad set name. Greek text validated.
- `optimization_goal` (str): Must be compatible with parent objective (e.g., LINK_CLICKS for OUTCOME_TRAFFIC).
- `billing_event` (str, default 'IMPRESSIONS'): IMPRESSIONS, LINK_CLICKS, THRUPLAY.
- `daily_budget` (float, optional): EUR daily budget. Required for ABO, forbidden for CBO.
- `lifetime_budget` (float, optional): EUR lifetime budget. Requires end_time.
- `targeting_json` (str, optional): JSON targeting spec. Required for manual/existing_audience modes.
- `promoted_object_json` (str, optional): JSON promoted object. Required for OUTCOME_SALES/LEADS.
- `start_time` (str, optional): ISO 8601 start time.
- `end_time` (str, optional): ISO 8601 end time.
- `audience_mode` (str, default 'manual'): 'manual', 'broad', 'existing_audience'.

**ABO/CBO rules (hard enforced):**
- ABO: parent has no budget -> ad set MUST have budget -> block otherwise
- CBO: parent has budget -> ad set MUST NOT have budget -> block otherwise
- Returns: budget_model, budget_logic_reason, parent_campaign_budget_model_detected

**Safety corridor:** parent inspection, ABO/CBO enforcement, objective compatibility, pre-write validation, API create, post-write verification, mutation log.

### update_adset [supervised-only]
Update an existing ad set.
- `adset_id` (str): Ad set ID.
- `name` (str, optional): New name.
- `daily_budget` (float, optional): New daily budget in EUR.
- `targeting` (dict, optional): New targeting spec.
- `optimization_goal` (str, optional): New optimization goal.
- `status` (str, optional): New status.

### create_ad_from_manifest [supervised-only]
Create an ad from a manifest entry (always PAUSED, manifest-driven, no exceptions).
- `account_id` (str): Ad account ID.
- `adset_id` (str): Target ad set ID.
- `logical_creative_id` (str): Creative entry ID in the manifest.
- `manifest_json` (str): JSON manifest containing the creative entry.
- `ad_name` (str): Ad name. Greek text validated.
- `page_id` (str): Facebook Page ID for identity.
- `destination_url` (str): Primary destination URL.
- `primary_text` (str): Main ad copy text.
- `cta_type` (str, default 'SHOP_NOW'): Call to action type.
- `headline` (str, optional): Headline text.
- `description` (str, optional): Description text.
- `instagram_user_id` (str, optional): IG identity.
- `destination_url_override` (str, optional): Override manifest URL (logged).
- `cta_override` (str, optional): Override manifest CTA (logged).
- `primary_text_override` (str, optional): Override text (logged).
- `headline_override` (str, optional): Override headline (logged).
- `meta_video_id` (str, optional): Video ID from upload + poll. Required for video ads.
- `dry_run` (bool, default false): Validate without creating.

**Manifest-driven rules:**
- Loads manifest entry by logical_creative_id
- Detects creative mode (simple/dynamic/dof) deterministically
- v1.3 corridor: only simple mode supported (dynamic/dof blocked)
- Duplicate prevention: blocks if same ad_name exists in ad set
- All overrides explicitly logged
- Post-write verifies: status, name, creative, CTA, destination URL, identity

**Safety corridor:** manifest validation, parent inspection, duplicate check, pre-write validation (A,B,C,E,F), API create, post-write verification, mutation log.

### update_ad [supervised-only]
Update an existing ad.
- `ad_id` (str): Ad ID.
- `name` (str, optional): New ad name.
- `status` (str, optional): New status.
- `creative_id` (str, optional): New creative ID.
- `bid_amount` (int, optional): New bid amount in cents.

### create_ad_creative [NOT REGISTERED - code exists, disabled]
Create an ad creative supporting simple, dynamic, and DOF modes.
- `account_id` (str): Ad account ID.
- `page_id` (str): Facebook Page ID.
- `instagram_user_id` (str, optional): IG account ID.
- `image_hashes` (list[str], optional): Image hashes for the creative.
- `video_id` (str, optional): Video ID.
- `headlines` (list[str], optional): Headline text variants.
- `descriptions` (list[str], optional): Description text variants.
- `bodies` (list[str], optional): Body text variants.
- `link` (str, optional): Destination URL.
- `call_to_action_type` (str, optional): CTA type.
- `asset_feed_spec` (dict, optional): Full asset feed spec for dynamic creatives.
- `asset_customization_rules` (list[dict], optional): Per-placement customization.
- `optimization_type` (str, optional): Creative optimization type.

### upload_video_asset [supervised-only]
Upload a local video file to a Meta ad account for use in video ads.
- `account_id` (str): Ad account ID.
- `video_path` (str): Local filesystem path to .mp4 or .mov file.
- `title` (str, optional): Video title in Meta.
- `description` (str, optional): Video description.

Validates file (exists, extension, size), uploads via simple upload (< 1GB), returns meta_video_id and initial processing state.

### poll_video_processing [production-safe]
Poll video processing status until ready, failed, or max attempts.
- `video_id` (str): Meta video ID from upload_video_asset.
- `max_attempts` (int, default 30): Max poll attempts.
- `poll_interval_seconds` (int, default 10): Seconds between polls.

Returns: processing_status (ready/processing/failed/timeout), duration_seconds, thumbnail_uri.

### upload_video_resumable [supervised-only]
Upload a video file using resumable upload (supports files >100MB up to 4GB).
- `account_id` (str): Ad account ID.
- `video_path` (str): Local path to .mp4 or .mov file.
- `title` (str, optional): Video title (defaults to filename).
- `chunk_size_mb` (int, default 20): Chunk size in MB.

### bulk_rename_objects [supervised-only]
Rename multiple Meta Ads objects in one call.
- `renames_json` (str): JSON array of rename specs: [{object_id, new_name, object_type}, ...].

### delete_campaign_structure [supervised-only]
Delete entire campaign structure (ads -> adsets -> campaigns) in correct order.
- `account_id` (str): Ad account ID.
- `campaign_ids_json` (str, optional): JSON array of campaign IDs to delete.
- `delete_all_active` (bool, default false): If true and no campaign_ids, targets all campaigns.
- `confirm` (bool, default false): Must be true to actually delete. False = dry run.

### diagnose_pixel_on_site [advisory-only]
Diagnose pixel installation on a website via headless browser check.
- `url` (str): Website URL to check.
- `pixel_id` (str, optional): Specific pixel ID to look for.

Checks: pixel script presence, consent/cookie blocking, Lead event setup, Complianz/cookie banner status. Requires browser MCP (Puppeteer).

### resolve_page_identity [production-safe]
Resolve full identity for a Facebook Page: page details + Instagram business account.
- `page_id` (str): Facebook Page ID.
- `account_id` (str, optional): Ad account ID for improved IG resolution.

Uses the 3-step IG resolution ladder (registry -> promote_pages -> ad account).

### generate_names [advisory-only]
Generate correctly named Meta Ads object following naming convention.
- `object_type` (str): 'campaign', 'adset', or 'ad'.
- `objective` (str, optional): For campaigns: Sales, Traffic, Leads, Awareness, Engagement.
- `product` (str, optional): For campaigns: product/offer name.
- `funnel` (str, optional): For campaigns: TOFU, MOFU, BOFU, RT.
- `budget_model` (str, optional): For campaigns: ABO, CBO.
- `audience_type` (str, optional): For ad sets: Broad, Broad-Interest, RT-WV-30d, etc.
- `age_range` (str, optional): For ad sets: 24-55, 18-45, All.
- `geo` (str, default 'GR'): Country code.
- `exclusion_flag` (str, default 'None'): For ad sets: Adv, ExPurch, None.
- `hook` (str, optional): For ads: concept name in kebab-case.
- `format_code` (str, optional): For ads: REEL, VID, IMG, REEL+FEED.
- `version` (str, default 'V1'): For ads: V1, V2, V3.

### create_multi_asset_ad [supervised-only]
Create an ad with enforced identity, multi-asset support, and verification.
- `account_id` (str): Ad account ID.
- `adset_id` (str): Target ad set ID.
- `page_id` (str): Facebook Page ID.
- `ad_name` (str): Ad name.
- `primary_text` (str): Main ad copy.
- `headline` (str): Headline text.
- `destination_url` (str): CTA destination URL.
- `cta_type` (str, default 'LEARN_MORE'): CTA type.
- `video_9x16_id` (str, optional): Vertical video ID (Stories/Reels).
- `video_1x1_id` (str, optional): Square video ID (Feed).
- `description` (str, optional): Description text.
- `copy_mode` (str, default 'manual'): 'manual', 'auto' (generate from vault), 'hybrid'.
- `angle_name` (str, optional): Marketing angle for auto/hybrid copy.
- `icp_name` (str, optional): Target ICP for auto/hybrid copy.
- `funnel_stage` (str, default 'tofu'): 'tofu', 'mofu', 'bofu'.
- `placement_mode` (str, default 'full_meta'): 'full_meta', 'facebook_only', 'instagram_only'.

If both 9:16 and 1:1 videos provided: creates ONE ad with asset_feed_spec and placement mapping (no auto-crop). IG gate enforced via placement_mode.

### read_client_vault [production-safe]
Read all client intelligence from the Obsidian vault for ad operations.
- `account_id` (str): Ad account ID (resolved to client slug via registry).
- `include_context` (bool, default false): Also read campaign history, assets, constraints.

Auto-resolves: brand voice, ICPs, angles, objections, profile IDs. Returns explicit blockers if critical files missing.

### generate_copy_from_vault [advisory-only]
Generate ad copy brief from vault intelligence for a specific creative.
- `account_id` (str): Ad account ID.
- `creative_hook` (str): Hook/concept name (e.g., 'Employee-Blame').
- `funnel_stage` (str, default 'tofu'): 'tofu', 'mofu', 'bofu'.
- `target_icp` (str, optional): Specific ICP to target.
- `angle` (str, optional): Specific angle from messaging house.
- `transcript_excerpt` (str, optional): SRT text from the video.
- `destination_url` (str, optional): Landing page URL.

### validate_ad_copy [advisory-only]
Validate ad copy for Greek language, greeklish detection, and quality.
- `primary_text` (str): Main ad body text.
- `headline` (str, optional): Headline text.
- `description` (str, optional): Description text.

### run_greek_qa [advisory-only]
Run comprehensive Greek language QA on all ads in an account.
- `account_id` (str): Ad account ID or 'all' for all active accounts.
- `status_filter` (str, default 'ACTIVE'): Filter ads by status: ACTIVE, PAUSED, or ALL.
- `include_copy_check` (bool, default true): Also check copy completeness.

Scans for: Greeklish, HTML entities, mojibake, garbled text, missing headlines/descriptions, encoding issues, accent errors, spelling rules. Returns per-ad PASS/FAIL.

### run_full_diagnostic [advisory-only]
Run comprehensive account health diagnostic.
- `account_id` (str): Ad account ID.
- `archetype` (str, default 'auto'): Account archetype (ecommerce, lead_gen, awareness, hybrid, auto).
- `include_performance` (bool, default true): Include last 7d performance snapshot.

Combines: pixel health, catalog validation, Greek QA, copy completeness, tracking setup, and performance snapshot.

### fix_ad_copy [supervised-only]
Fix ad copy fields with Greek text validation before and after write.
- `ad_id` (str): Ad ID to fix.
- `account_id` (str): Ad account ID.
- `primary_text` (str, optional): New primary text. None = keep existing.
- `headline` (str, optional): New headline. None = keep existing.
- `description` (str, optional): New description. None = keep existing.
- `validate_greek` (bool, default true): Run Greek QA before writing.
- `dry_run` (bool, default true): Preview changes without writing.

Handles the video_data.image_url API quirk automatically.

### enable_product_extensions [supervised-only]
Enable product extensions (pe_product + pe_carousel) on video ads.
- `account_id` (str): Ad account ID.
- `ad_id` (str, optional): Single ad ID to enable extensions on.
- `campaign_id` (str, optional): Campaign ID to batch-enable all ads.
- `dry_run` (bool, default true): Preview without writing.

### optimize_account [advisory-only]
Run full diagnostic and optionally auto-fix issues.
- `account_id` (str): Ad account ID.
- `auto_fix` (bool, default false): Enable all auto-fixes.
- `fix_greeklish` (bool, default false): Auto-fix Greeklish copy issues.
- `fix_missing_headlines` (bool, default false): Auto-fix missing headlines.
- `fix_product_extensions` (bool, default false): Auto-enable product extensions.

Orchestrates: diagnostic -> categorize fixable issues -> apply fixes -> report manual items.

### audit_all_accounts [advisory-only]
Run diagnostics on all active ad accounts.
- `include_dormant` (bool, default false): Include dormant/blocked accounts.

Excludes ex-clients and self-managed accounts by default. Returns dashboard-style summary with per-account health scores and aggregated issues.

## Phase v1.4 - Decision & Optimization Engine (4 tools)

### run_optimization_cycle [advisory-only]
Run full optimization cycle: read insights, classify entities, recommend actions.
- `account_id` (str): Ad account ID.
- `archetype` (str, default 'hybrid'): Account archetype for thresholds.
- `time_range` (str, default 'last_7d'): Insights date range.
- `target_cpa` (float, optional): Target CPA for ecommerce classification.
- `target_cpl` (float, optional): Target CPL for lead gen classification.

**Classification labels:** WINNER (scale), TESTING (hold), WEAK (iterate), LOSER (pause).
**Minimum data thresholds:** EUR 10 spend, 1000 impressions for CTR, 20 clicks for CPC.
**Value integrity:** Tracked ROAS = high confidence. Estimated/unknown = reduced confidence.

Returns: account summary, per-campaign decisions, per-ad-set decisions, priority action list, human-readable report.

### create_launch_plan [advisory-only]
Create deterministic campaign launch plan with ABO/CBO decision, budget distribution, and execution order.
- `objective` (str): Campaign objective.
- `daily_budget_eur` (float): Total daily budget.
- `num_creatives` (int): Number of creative assets.
- `funnel_stage` (str): 'tofu', 'mofu', 'bofu'.
- `archetype` (str): Account archetype.
- `geo_countries` (str, optional): Comma-separated country codes.
- `account_maturity` (str): 'new', 'growing', 'mature'.
- `optimization_events_7d` (int): Recent optimization events.
- `has_proven_winners` (bool): Whether proven winners exist.

**ABO/CBO rules:** Budget < EUR 30/day OR new account OR < 50 events -> ABO. Scaling + mature + winners -> CBO.

Returns: structure decision, campaign config, ad set configs, creative distribution, execution order.

### build_execution_pack [advisory-only]
Build a deterministic execution pack from launch intent. Does NOT create anything.
- `account_id`, `objective`, `archetype`, `funnel_stage`, `daily_budget_eur`
- `creatives_manifest_json`: JSON with creatives array (logical_creative_id, primary_text, headline, destination_url, cta_type)
- `page_id`, `geo_countries`, `account_maturity`, `optimization_events_7d`, `has_proven_winners`
- `preferred_budget_model`: 'ABO', 'CBO', or 'auto' (system decides, warns on conflict)
- `instagram_user_id`, `promoted_object_json`, `client_slug`

Returns: campaigns_to_create[], adsets_to_create[], ads_to_create[], execution_order, dependencies, blockers, warnings, reasoning, requires_confirmation=true.

### execute_paused_launch [supervised-only]
Execute an execution pack, creating all assets in PAUSED state.
- `account_id`: Must match pack's account.
- `execution_pack_json`: JSON from build_execution_pack.
- `confirm_execute`: Must be True for writes. False = validation only.
- `dry_run`: True = validate without writing.

**Execution order:** campaigns -> ad sets -> ads. If any step fails, execution stops immediately with exact failure report.

**Returns:** final_status, temp_id_to_real_id map, created objects, verification per step, rollback references, failed step details if any.

## Phase v1.4.2 - Guarded Mutation Corridor (2 tools)

### build_mutation_pack [advisory-only]
Build safe mutation plan from optimization results or manual intent.
- `account_id` (str): Ad account ID.
- `source_mode` (str): 'optimization_cycle' or 'manual'.
- `optimization_cycle_json` (str, optional): JSON from run_optimization_cycle.
- `manual_actions_json` (str, optional): JSON array of manual mutations.
- `mutation_policy` (str, default 'balanced'): 'conservative' (+15% max), 'balanced' (+20%), 'aggressive' (+30%).

**Supported mutations:** pause_adset, pause_ad, increase/decrease_budget_adset/campaign, duplicate_adset/ad_paused, create_replacement_ad_from_manifest.
**Blocked:** activation, deletion, creative swap on active, structural rewrites.

### execute_mutation_pack [supervised-only]
Execute mutation pack with explicit confirmation gate and per-step verification.
- `account_id` (str): Must match pack.
- `mutation_pack_json` (str): JSON from build_mutation_pack.
- `confirm_execute` (bool): Must be True for writes.
- `dry_run` (bool): Validate without writing.

Returns: per-step before/after state, verification, rollback refs.

## Phase v1.5 - Activation + Rollback Corridors (4 tools)

### build_activation_pack [advisory-only]
Build preflight-checked activation plan for paused objects.
- `account_id`, `activation_targets_json` (array of {object_type, object_id, object_name})
- `activation_policy`: 'strict' (all checks must pass) or 'standard' (warnings OK).

**Preflight checks:** status=PAUSED, objective valid, parent valid, targeting present, promoted_object where required, creative attached, parent adset valid.
**Dependency order:** campaign -> adset -> ad (parent first).

### execute_activation_pack [supervised-only]
Execute activation (PAUSED -> ACTIVE) with per-step verification.
- `account_id`, `activation_pack_json`, `confirm_execute`, `dry_run`

### build_rollback_pack [advisory-only]
Build deterministic rollback plan.
- `account_id`, `rollback_targets_json` (array of {object_type, object_id, rollback_action, revert_budget_cents})
- `rollback_mode`: 'exact_revert' (undo changes) or 'safe_pause_only' (pause only, never delete).

**Auto-downgrade:** delete on active objects -> pause. Delete in safe_pause_only mode -> pause. Always explicit.

### execute_rollback_pack [supervised-only]
Execute rollback with per-step before/after verification.
- `account_id`, `rollback_pack_json`, `confirm_execute`, `dry_run`

**Rollback order:** ad -> adset -> campaign (children first, reverse of activation).

## Phase v1.6-v1.7 - Review Queue + Outcome Snapshots (7 tools)

### build_review_queue [advisory-only]
Convert optimization/mutation/activation outputs into operator review queue.
- `account_id`, `source_mode` ('optimization_cycle'|'mutation_pack'|'activation_pack'), `source_json`
- `queue_policy`: 'strict', 'balanced', 'aggressive'. Controls which confidence levels get queued.

Returns: prioritized queue items with review_item_id, recommended_action, confidence, risk_level, execution_path, status=pending.

### list_review_queue [production-safe]
List review queue items with status counts.
- `account_id`, `status_filter` (optional), `limit`

Returns: items sorted by priority, status_counts, executable_now_count, blocked_count.

### resolve_review_item [advisory-only]
Approve, reject, or expire a queue item.
- `account_id`, `review_item_id`, `resolution` ('approve'|'reject'|'expire'), `operator_note`
- `auto_build_execution`: If True + approve, auto-generates mutation/activation pack spec.

### record_outcome_snapshot [advisory-only]
Capture performance snapshot for before/after comparison.
- `account_id`, `object_type`, `object_id`, `snapshot_label`, `time_range`
- `baseline_reference`: Previous snapshot_id for delta comparison.

Returns: snapshot_data with all KPIs, value_provenance (tracked/estimated), and comparison deltas with direction (improved/stable/degraded).

### expire_stale_queue_items [advisory-only]
Auto-expire pending items past their stale_after timestamp. Persists state.
- `account_id`, `max_age_days` (optional override)

### build_operator_digest [advisory-only]
Build human-readable operator digest from persistent queue, snapshots, journal.
- `account_id`, `digest_mode` ('daily'|'weekly'|'post_execution'|'review_backlog')

Returns: structured digest with pending/approved/stale counts, top scale/pause candidates, recent snapshots, and human-readable text.

### run_scheduled_review_cycle [advisory-only]
Full scheduled cycle: optimize -> queue -> expire stale -> digest. No Meta writes.
- `account_id`, `archetype`, `time_range`, `queue_policy`, `target_cpa`, `target_cpl`

Returns: items created/superseded/expired, digest with summary.

## v1.7 Persistent Memory Model

**Storage:** `01_CLIENTS/{slug}/meta-ads/_system/`
- `review-queue.json` - all queue items (append-only status updates)
- `outcome-snapshots.json` - immutable performance snapshots
- `execution-journal.json` - execution records
- `operator-digests.json` - generated digests

**Staleness:** Default 3 days. Items auto-expire. Stale items block execution.
**Deduplication:** Same (object_id, action, source) in same window -> supersede old, create new.
**Immutability:** Snapshots never modified. Queue items only status-updated, never deleted.

## Phase v1.8 - Learning Layer + Policy Engine (5 tools)

### evaluate_execution_outcome [advisory-only]
Judge whether an executed action achieved its expected outcome.
- `account_id`, `action_type`, `baseline_snapshot_id`, `comparison_snapshot_id`, `archetype`

Returns: outcome_label (success/mixed/fail/inconclusive), confidence, positive/negative/neutral signals, policy_learning_candidate flag. Per-action evaluation rules: budget increases judged on spend scale + ROAS preservation + CPA tolerance; pauses judged on waste reduction; new creatives judged on CTR/CPC after minimum spend.

### update_policy_memory [advisory-only]
Update account and global policy memory from an evaluation.
- `account_id`, `evaluation_json`, `scope` ('account_only'|'global_only'|'account_and_global')

Computes success_rate and bounded confidence_adjustment. Global memory is abstracted (no client identifiers).

### get_policy_memory [production-safe]
Read policy memory with optional filters.
- `account_id` (optional), `archetype`, `action_type`, `scope`

Returns: account + global policies with success rates, confidence adjustments, evidence counts.

### build_learning_digest [advisory-only]
Build human-readable learning digest from policy memory.
- `account_id` (optional), `digest_mode` ('daily'|'weekly'|'cross_account')

### run_learning_cycle [advisory-only]
Full learning loop: find evaluations -> update policy -> build digest.
- `account_id`, `update_global`

## v1.8 Confidence Calibration

**Bounds:** Max upward +0.15, max downward -0.20. Minimum 3 evidence points for any adjustment.
**Sources:** Account-level preferred if sufficient evidence, global (dampened 0.7x) as fallback.
**Value integrity:** Degraded tracking suppresses positive adjustment.
**Transparency:** Every recommendation can show base_confidence + policy_adjustment + final_confidence.

## Phase v1.9 - Experimentation + Budget Governor + Creative Rotation (7 tools)

### build_experiment_plan [advisory-only]
Build structured test plan with hypothesis, success criteria, and ABO/CBO justification.
- `account_id`, `experiment_goal` (creative_test|audience_test|offer_test|budget_test|landing_page_test)
- `archetype`, `daily_budget_eur`, `num_creatives`, `hypothesis`, `testing_mode`

Tests default ABO for isolation. Persists to experiment registry.

### evaluate_experiment [advisory-only]
Judge experiment outcome from per-entity performance data.
- `account_id`, `experiment_id`, `performance_data_json`

Returns: winner/loser/mixed/inconclusive with ranked entities, promote_candidate flag.
Minimum spend threshold enforced before judgment.

### rotate_creative_set [supervised-only]
Detect stale creatives and recommend rotation.
- `account_id`, `adset_id`, `ad_metrics_json`, `rotation_mode`

Staleness: frequency > 3.5 + days > 7, or CTR < 0.5% after EUR 20 spend.

### run_budget_governor [supervised-only]
Safe budget reallocation with hard caps and experiment protection.
- `account_id`, `campaign_metrics_json`, `policy` (conservative|balanced|aggressive)

Rules: max 3 simultaneous scale-ups (balanced), experiments protected, losers cut 50%.

### promote_experiment_winner [supervised-only]
Promote winning experiment variant to scaled structure with lineage tracking.
- `account_id`, `experiment_id`, `winner_entity_id`, `promotion_type`

### get_experiment_registry [production-safe]
List experiments from persistent registry with status filters.

### run_scaling_cycle [supervised-only]
Full cycle: evaluate experiments + govern budget + build recommendations.

## v1.9 Budget Governor Policies

| Policy | Max Increase | Max Simultaneous | Protect Experiments |
|--------|-------------|-----------------|---------------------|
| conservative | +15% | 2 | Yes |
| balanced | +20% | 3 | Yes |
| aggressive | +30% | 4 | No |

## Phase v2.0 - Concept Selection + Copy Generation (3 tools)

### select_concepts [advisory-only]
Select and prioritize ad concepts from vault intelligence.
- `account_id` (str): Ad account ID.
- `funnel_stage` (str, default 'tofu'): 'tofu', 'mofu', 'bofu'.
- `available_hooks_json` (str, optional): JSON array of available creative hooks.
- `max_selected` (int, default 3): Top concepts to select for testing.
- `max_backup` (int, default 2): Backup concepts.

Generates scored concept candidates from angles x ICPs, then selects top concepts.

### generate_ad_copy_chain [advisory-only]
Generate vault-grounded ad copy for a selected concept.
- `account_id` (str): Ad account ID.
- `concept_json` (str): JSON of selected concept from select_concepts.
- `transcript_excerpt` (str, optional): SRT text for creative alignment.

Full chain: vault -> normalized data -> copy brief -> generation instructions.

### generate_auto_copy [advisory-only]
Generate vault-grounded Greek ad copy automatically.
- `account_id` (str): Ad account ID.
- `angle_name` (str): Marketing angle (e.g., 'Systems Not People').
- `icp_name` (str, optional): Target ICP (e.g., 'The Overwhelmed Owner').
- `funnel_stage` (str, default 'tofu'): 'tofu', 'mofu', 'bofu'.
- `copy_mode` (str, default 'auto'): 'auto', 'manual', 'hybrid'.
- `existing_primary_text` (str, optional): For manual/hybrid modes.
- `existing_headline` (str, optional): For manual/hybrid modes.
- `existing_description` (str, optional): For manual/hybrid modes.
- `transcript_excerpt` (str, optional): SRT text for creative alignment.

Assembles primary_text, headline, description from vault intelligence (brand voice, value props, ICP pains, offers, objections). Validates for Greek-only, greeklish, forbidden words, generic content.
