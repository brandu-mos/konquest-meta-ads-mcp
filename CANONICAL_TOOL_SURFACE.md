# KonQuest Meta Ads MCP - Canonical Tool Surface
**Derived from:** actual code (server.py imports + @mcp.tool decorators + _register_engine_tools registrations)
**Date:** 2026-03-27 | **Phase:** A closeout
**Total registered MCP tools:** 98

---

## Core Tools (66) - via @mcp.tool() in imported modules

### accounts.py (6 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| check_token_status | production-safe | Read-only token health |
| get_ad_accounts | production-safe | Read-only account listing |
| get_account_info | production-safe | Read-only account details + spend |
| get_account_pages | production-safe | Read-only page listing |
| get_instagram_identities | production-safe | Read-only IG account listing |
| discover_all_accounts | production-safe | Read-only - populates local registry from API |

### campaigns.py (4 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| get_campaigns | production-safe | Read-only |
| get_campaign_details | production-safe | Read-only |
| create_campaign | supervised-only | WRITES to Meta API. Creates PAUSED campaign. |
| update_campaign | supervised-only | WRITES to Meta API. Modifies campaign. |

### adsets.py (4 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| get_adsets | production-safe | Read-only |
| get_adset_details | production-safe | Read-only |
| create_adset | supervised-only | WRITES to Meta API |
| update_adset | supervised-only | WRITES to Meta API |

### ads.py (4 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| get_ads | production-safe | Read-only |
| get_ad_details | production-safe | Read-only |
| create_ad_from_manifest | supervised-only | WRITES to Meta API. Enforces IG gate via identity.py. |
| update_ad | supervised-only | WRITES to Meta API |

### creatives.py (3 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| get_ad_creatives | production-safe | Read-only |
| get_creative_details | production-safe | Read-only |
| create_ad_creative | supervised-only | WRITES to Meta API |
| update_ad_creative | supervised-only | Updates creative name only. Meta API does not allow changing copy/headline/CTA (immutable). |

### insights.py (2 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| get_insights | production-safe | Read-only performance data |
| get_bulk_insights | production-safe | Cross-account insights aggregation. Loops all accessible accounts. |

### pixels.py (5 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| get_pixel_info | production-safe | Read-only |
| get_pixel_events | production-safe | Read-only |
| get_event_stats | production-safe | Read-only |
| send_test_event | advisory-only | WRITES test event via CAPI. Does not affect live tracking. |
| run_tracking_diagnostic | advisory-only | Read-only analysis with recommendations |

### catalogs.py (6 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| get_catalog_info | production-safe | Read-only |
| get_catalog_products | production-safe | Read-only |
| get_product_sets | production-safe | Read-only |
| validate_catalog_connections | advisory-only | Read-only validation with recommendations |
| create_product_set | supervised-only | WRITES to Meta API |
| update_product_set | supervised-only | WRITES to Meta API |

### audiences.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| list_custom_audiences | production-safe | Read-only |

### targeting.py (3 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| search_interests | production-safe | Read-only search |
| search_behaviors | production-safe | Read-only search |
| search_geo_locations | production-safe | Read-only search |

### video.py (2 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| upload_video_asset | supervised-only | WRITES - uploads video to Meta |
| poll_video_processing | production-safe | Read-only status check |

### naming.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| generate_names | advisory-only | Generates name strings. No API call. |

### images.py (2 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| upload_ad_image | supervised-only | WRITES - downloads image from URL, uploads via multipart to Meta ad images library. |
| get_ad_image | production-safe | Read-only - retrieves image metadata and URL by hash. |

### ad_builder.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| create_multi_asset_ad | supervised-only | WRITES to Meta API. Enforces IG gate via identity.py. |

### ops.py (5 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| upload_video_resumable | supervised-only | WRITES - resumable video upload |
| bulk_rename_objects | supervised-only | WRITES - batch renames campaigns/adsets/ads |
| delete_campaign_structure | supervised-only | DELETES - removes campaign tree |
| diagnose_pixel_on_site | advisory-only | Read-only pixel firing check |
| resolve_page_identity | production-safe | Read-only - resolves page + IG via identity.py |

### duplication.py (2 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| duplicate_campaign | supervised-only | WRITES - duplicates campaign + optional child ad sets + optional child ads. Same-account only. All output PAUSED. |
| duplicate_adset | supervised-only | WRITES - duplicates single ad set into target campaign. Same-account only. PAUSED. |

### vault_reader.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| read_client_vault | production-safe | Read-only - reads local vault files |

### vault_bootstrap.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| bootstrap_client_vault | production-safe | Creates vault directory + 15 canonical template files for a client. Required before write operations. |

### setup.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| run_setup_check | production-safe | Read-only readiness checker. Validates token, permissions, accounts, pages, IG, pixels, config. Returns structured pass/warn/fail with fix instructions. |

### copy_engine.py (2 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| generate_copy_from_vault | advisory-only | Generates copy text. No API call. |
| validate_ad_copy | advisory-only | Validates copy. No API call. |

### automation.py (6 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| run_greek_qa | advisory-only | Read-only analysis + fix recommendations |
| run_full_diagnostic | advisory-only | Read-only account health assessment |
| fix_ad_copy | supervised-only | WRITES - modifies live ad copy via API |
| enable_product_extensions | supervised-only | WRITES - modifies catalog product data |
| optimize_account | advisory-only | Read-only recommendations |
| audit_all_accounts | advisory-only | Read-only multi-account assessment |

---

## Engine Tools (32) - via _register_engine_tools() in server.py

### Registration path: explicit mcp.tool()() calls inside _register_engine_tools()

### loop.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| run_optimization_cycle | advisory-only | Orchestrator. Reads data, produces recommendations. |

### planner.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| create_launch_plan | advisory-only | Generates structured plan. No API writes. |

### executor.py (2 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| build_execution_pack | advisory-only | Prepares pack JSON. No API writes. |
| execute_paused_launch | supervised-only | WRITES - creates campaigns/adsets/ads via Meta API. All PAUSED. |

### mutations.py (2 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| build_mutation_pack | advisory-only | Prepares mutation JSON. No API writes. |
| execute_mutation_pack | supervised-only | WRITES - modifies budgets/targeting via API |

### activation.py (4 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| build_activation_pack | advisory-only | Prepares status change JSON. No API writes. |
| execute_activation_pack | supervised-only | WRITES - changes ad status (pause/activate) |
| build_rollback_pack | advisory-only | Prepares rollback JSON. No API writes. |
| execute_rollback_pack | supervised-only | WRITES - reverts changes via API |

### review.py (7 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| build_review_queue | advisory-only | Reads performance data, builds queue. Local file I/O only. |
| list_review_queue | production-safe | Reads local review queue file. |
| resolve_review_item | advisory-only | Updates local review queue. No API writes. |
| record_outcome_snapshot | advisory-only | Writes local snapshot file. No API writes. |
| expire_stale_queue_items | advisory-only | Cleans local queue. No API writes. |
| build_operator_digest | advisory-only | Generates digest from local data. |
| run_scheduled_review_cycle | advisory-only | Orchestrator for review. Local I/O + Meta reads. |

### learning.py (5 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| evaluate_execution_outcome | advisory-only | Compares expected vs actual. Local file I/O. |
| update_policy_memory | advisory-only | Updates local policy file. No API writes. |
| get_policy_memory | production-safe | Reads local policy file. |
| build_learning_digest | advisory-only | Generates summary. Local I/O. |
| run_learning_cycle | advisory-only | Orchestrator. Local I/O + Meta reads. |

### experiments.py (7 tools)
| Tool | Classification | Notes |
|------|---------------|-------|
| build_experiment_plan | advisory-only | Generates plan JSON. No API writes. |
| evaluate_experiment | advisory-only | Reads performance data. Local I/O. |
| rotate_creative_set | supervised-only | WRITES - swaps creatives in live ad sets |
| run_budget_governor | supervised-only | WRITES - may reduce budgets if overspend detected |
| promote_experiment_winner | supervised-only | WRITES - pauses losers, scales winner |
| get_experiment_registry | production-safe | Reads local registry file. |
| run_scaling_cycle | supervised-only | WRITES - scales budgets on winners |

### concepts.py (1 tool)
| Tool | Classification | Notes |
|------|---------------|-------|
| select_concepts | advisory-only | Selects from vault. No API writes. |

### server.py inline wrappers (2 tools)
| Tool | Classification | Registration | Notes |
|------|---------------|-------------|-------|
| generate_ad_copy_chain | advisory-only | inline wrapper in server.py lines 115-146 | Generates copy from vault. No API writes. |
| generate_auto_copy | advisory-only | inline wrapper in server.py lines 151-197 | Generates Greek copy from vault. No API writes. |

---

## Classification Summary

| Classification | Count | Description |
|----------------|:---:|-------------|
| production-safe | 38 | Read-only. No API writes. No local state changes. |
| supervised-only | 29 | WRITES to Meta API or DELETES. Require operator approval. |
| advisory-only | 31 | Generate recommendations, plans, copy, diagnostics. No Meta API writes. May write local files (review queue, policy, snapshots). |
| **Total** | **98** | |

---

## Internal Helpers (not MCP tools, support live corridors)

| Module | Role | Used By |
|--------|------|---------|
| core/identity.py | IG resolution ladder, IG gate, readiness | ad_builder, ads, ops, activation |
| core/api.py | Meta Graph API HTTP client, rate limits | All core modules |
| core/auth.py | Token verification, permissions | accounts |
| core/utils.py | Format helpers (account ID, budget, JSON) | ads, adsets, ad_builder, audiences, automation |
| engine/storage.py | Vault persistence (review queue, snapshots, policy, experiments) | review, learning, experiments |
| engine/actions.py | Action type definitions | executor, mutations, activation |
| engine/asset_gate.py | Asset validation before writes | executor |
| engine/audience.py | Audience classification | planner, executor |
| engine/classifier.py | Account/campaign classification | planner, loop |
| engine/copy_sanitizer.py | Copy text sanitization | copy_chain, copy_generator |
| engine/final_copy_gate.py | Final copy validation gate | copy_chain |
| engine/naming_gate.py | Naming convention enforcement | executor, mutations |
| engine/strategy.py | Strategy selection from vault | planner, concepts |
| engine/tracking_gate.py | Tracking verification before launch | executor |
| engine/value_prop_matcher.py | Value prop to ICP matching | concepts, copy_chain |
| engine/vault_normalizer.py | Vault data normalization | concepts, copy_chain, copy_generator |
| engine/vp_enforcement.py | Value prop enforcement | copy_generator |
| ingestion/*.py | Video manifest, pairing, scanning, transcript | Internal pipeline |
| reporting/ | DELETED in Phase D | Was dead code - never imported at runtime |
| safety/*.py | Rate limiter, rollback, dedup, file lock, tiers | Write corridors |
| validators/*.py | Compliance, creative, Greek text, operational, structure, tracking | Write corridors via runner.py |

---

## Residual Non-Tool Code (exists in repo, not part of tool surface)

| Path | Status | Notes |
|------|--------|-------|
| evals/*.py | Internal testing | 5 eval files. Not operator surface. |
| tests/*.py | Test suite | 105 tests. Not operator surface. |
| config/accounts.yaml | Runtime config | Example data. Buyer must populate with own accounts. |
| config/placement_defaults.yaml | Runtime config | Placement presets. |
| config/thresholds.yaml | Runtime config | Safety thresholds. |
