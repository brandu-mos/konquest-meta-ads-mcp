# Meta Ads MCP - Product Gap Register
**Created:** 2026-03-27 | **Phase:** A (truth alignment)

---

## GAP-001: Dataset Management Tools
- **Source:** `meta_ads_mcp/core/datasets.py` lines 9-13
- **Status:** Empty scaffold. @mcp.tool commented out (line 22). Module import commented in server.py (line 29). NotImplementedError on line 25.
- **Category:** production-gap
- **Original intent:** get_dataset_info, get_dataset_stats, get_dataset_events, validate_dataset_health - unified pixel/CAPI/offline tracking objects
- **Overlap:** Partially covered by `get_pixel_info`, `get_pixel_events`, `run_tracking_diagnostic` in pixels.py
- **Risk if ignored:** None - not reachable at runtime. False surface only.
- **Recommended action:** Delete file. Intent preserved here.
- **Priority:** P2

## GAP-002: Test Events API (Standalone Module)
- **Source:** `meta_ads_mcp/core/test_events.py` lines 8-11
- **Status:** Empty scaffold. @mcp.tool commented out (line 18). Module import commented in server.py (line 30). NotImplementedError on line 27.
- **Category:** delete
- **Original intent:** send_test_event, monitor_test_events - test event push and receipt polling
- **Overlap:** FULL - `send_test_event` already implemented and live in `pixels.py`. Server.py line 30 note confirms: "send_test_event in pixels.py"
- **Risk if ignored:** None - duplicate intent, fully covered.
- **Recommended action:** Delete file. Capability exists in pixels.py.
- **Priority:** P3

## GAP-003: Feed Status & Diagnostics
- **Source:** `meta_ads_mcp/core/feeds.py` lines 6-9
- **Status:** Empty scaffold. No functions defined. No @mcp.tool. Module import commented in server.py (line 32).
- **Category:** production-gap
- **Original intent:** get_feed_status, get_feed_errors, monitor_feed_freshness - catalog feed health for DPA
- **Overlap:** Partially covered by `validate_catalog_connections` in catalogs.py (checks catalog-pixel link but not feed ingestion status)
- **Risk if ignored:** Low. Feed errors surface in Commerce Manager UI.
- **Recommended action:** Delete file. Intent preserved here.
- **Priority:** P2

## GAP-004: Asset Connection Validation
- **Source:** `meta_ads_mcp/core/connections.py` lines 9-13
- **Status:** Empty scaffold. No functions defined. No @mcp.tool. Module import commented in server.py (line 33).
- **Category:** enterprise-hardening
- **Original intent:** validate_pixel_account, validate_pixel_catalog, validate_page_ig, validate_full_chain - cross-asset connection verification
- **Overlap:** Partially covered by `run_full_diagnostic` in automation.py and `validate_catalog_connections` in catalogs.py
- **Risk if ignored:** Low. Existing diagnostics catch most connection issues.
- **Recommended action:** Delete file. Intent preserved here.
- **Priority:** P3

## GAP-005: Image Upload Tools - PARTIALLY RESOLVED (Wave 1.2)
- **Status:** PARTIALLY RESOLVED. `upload_ad_image` implemented and live-validated in Wave 1.2.
- **Resolved:** URL-based image ingestion (download from URL, multipart upload to Meta). Returns image_hash for creative workflows.
- **Live validated:** 2026-03-27 on test account. Image hash returned, dimensions confirmed.
- **Tests:** 10 tests in test_images.py
- **Classification:** supervised-only
- **Still open:**
  - Local file path upload
  - get_ad_image (image retrieval)
  - Batch image upload

## GAP-006: Meta Ads Library Search
- **Source:** `meta_ads_mcp/core/ads_library.py` lines 10-12
- **Status:** Empty scaffold. No functions. Module import commented in server.py (line 47).
- **Category:** advisory-candidate
- **Original intent:** search_ads_archive (paginated), get_ad_archive_details - competitive intelligence via API
- **Overlap:** The `/meta_ads_extractor` SKILL handles Ad Library extraction via browser automation (different approach, more reliable than limited API).
- **Risk if ignored:** None. Browser extraction is superior to API for this use case.
- **Recommended action:** Delete file. Intent preserved here.
- **Priority:** P3

## GAP-007: Campaign/AdSet/Ad Duplication - PARTIALLY RESOLVED (Phase F.1)
- **Status:** PARTIALLY RESOLVED. `duplicate_campaign` implemented and live-validated in Phase F.1.
- **Resolved:** Campaign duplication + child ad set duplication. Same-account. All output PAUSED. ABO/CBO handling. Naming enforcement. Partial failure handling with orphan reporting.
- **Live validated:** 2026-03-27 on test account. 2 bugs found and fixed during validation (name suffix + bid_strategy).
- **Tests:** 14 tests in test_duplication.py
- **Classification:** supervised-only
- **Still open:**
  - duplicate_adset (standalone, into different campaign) - Phase F.2
  - duplicate_ad (standalone, into different ad set) - Phase F.2
  - Cross-account duplication - Phase F.2+
  - Ad-level duplication within campaign duplication (include_ads) - Phase F.2

## GAP-008: Reporting Templates
- **Source:** `meta_ads_mcp/reporting/templates.py` line 18-19
- **Status:** References `assets/report-templates/` directory that does not exist in the product.
- **Category:** production-gap
- **Original intent:** Load WhatsApp/HTML report templates for automated reporting
- **Overlap:** None. No live module imports `reporting/templates.py`. The `reporting/formatter.py` is also not imported.
- **Risk if ignored:** None at runtime (not imported by server.py). False capability surface.
- **Recommended action:** Note existence. Do not delete in Phase A (not a scaffold - has real code, just unreachable). Phase B decision.
- **Priority:** P2

## GAP-009: Version Drift
- **Source:** Multiple files
- **Status:** Confirmed drift between pyproject.toml (0.1.0), server.py startup (v1.9.0), actual code (v2.0), docs (v1.0-v1.4 only)
- **Category:** enterprise-hardening
- **Original intent:** N/A - accumulated drift
- **Overlap:** N/A
- **Risk if ignored:** Buyer confusion. Misleading product claims.
- **Recommended action:** Phase B - version alignment across all files
- **Priority:** P0 for Phase B

## GAP-010: TOOLS.md Coverage (Phase B addressed)
- **Source:** `docs/TOOLS.md` - updated in Phase B to cover all 81 registered tools
- **Status:** RESOLVED in Phase B
- **Category:** enterprise-hardening
- **Original intent:** N/A - tools were added after docs were written
- **Overlap:** N/A
- **Risk if ignored:** Buyer doesn't know ~28% of capabilities exist.
- **Recommended action:** Phase B - document all tools
- **Priority:** P1 for Phase B

## GAP-011: Test Failures (data mismatch)
- **Source:** `tests/test_automation.py` lines 130, 135
- **Status:** Tests expect `example_client` (underscore) and `act_1234567890` as `ecommerce`. Actual accounts.yaml has `example-brand` (dash) as `hybrid`.
- **Category:** production-gap
- **Original intent:** Tests were written for original client data, not updated after data sanitization
- **Overlap:** N/A
- **Risk if ignored:** 2 test failures. CI would fail.
- **Recommended action:** Fix in Phase A (truth alignment - tests must match actual data)
- **Priority:** P0

## GAP-012: update_campaign - RESOLVED (Phase C.1)
- **Status:** RESOLVED. Implemented and registered in Phase C.1.
- **Supported fields:** name, status, daily_budget, lifetime_budget, start_time, end_time, special_ad_categories
- **Tests:** 11 tests in test_campaigns.py
- **Classification:** supervised-only

## GAP-013: update_adset - RESOLVED (Phase C.2)
- **Status:** RESOLVED. Implemented and registered in Phase C.2.
- **Category:** production-gap
- **Original intent:** Update ad set targeting, budget, schedule, optimization goal
- **Supported fields:** name, status, daily_budget, lifetime_budget, targeting_json, start_time, end_time
- **Tests:** 11 tests in test_adsets.py
- **Classification:** supervised-only

## GAP-014: update_ad - RESOLVED (Phase C.3)
- **Status:** RESOLVED. Implemented and registered in Phase C.3.
- **Supported fields:** name, status, creative_id
- **Tests:** 10 tests in test_ads.py
- **Classification:** supervised-only

## GAP-015: create_ad_creative - PARTIALLY RESOLVED (Wave 1.3)
- **Status:** PARTIALLY RESOLVED. Single-image `create_ad_creative` implemented and live-validated in Wave 1.3.
- **Resolved:** Single-image creative creation with object_story_spec, page_id, IG auto-resolution, CTA, headline, description. Returns creative_id for downstream use.
- **Live validated:** 2026-03-27 on test account. Creative ID returned, verified, Greek text validated.
- **Tests:** 12 tests in test_creatives_wave1.py
- **Classification:** supervised-only
- **Still open:**
  - Creative update (update_ad_creative)
  - Carousel creatives
  - Video creative assembly
  - Dynamic creatives

## GAP-018: Static Multi-Dimension Single-Ad Support - RESOLVED (Wave 2.0)
- **Status:** RESOLVED. `create_multi_asset_ad` extended with static image multi-dimension support.
- **Resolved:** 1:1, 4:5, 9:16 static image ratios. 2+ image hashes -> ONE ad with asset_feed_spec + asset_customization_rules + placement mapping. Mixed video+image blocked. Single image blocked (use create_ad_creative).
- **Live validated:** 2026-03-27 on test account. 1:1 + 9:16 confirmed: one ad, two images, two rules, correct labels.
- **Tests:** 13 tests in test_multi_image.py
- **Still open:**
  - Image crops (buyer provides pre-cropped images)
  - Mixed video + image in one ad
  - Carousel creatives
  - Additional ratios beyond 1:1, 4:5, 9:16

## GAP-016: create_product_set - RESOLVED (Convenience Wave)
- **Status:** RESOLVED. Scaffold replaced with real implementation. Live-validated on test catalog.
- **Tests:** Included in test_convenience_wave.py
- **Classification:** supervised-only

## GAP-017: update_product_set - RESOLVED (Convenience Wave)
- **Status:** RESOLVED. Scaffold replaced with real implementation. Live-validated on test catalog.
- **Category:** production-gap
- **Original intent:** Update product set filters and rules
- **Overlap:** None
- **Risk if ignored:** Cannot modify product sets via MCP
- **Recommended action:** Implement and register.
- **Priority:** P1
