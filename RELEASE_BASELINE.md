# Meta Ads MCP - Release Baseline (FROZEN)
**Frozen:** 2026-03-27T12:21:00+0200
**Status:** Release-locked. Any change to these values requires a new freeze.

---

## Canonical Numbers

| Metric | Value | Source |
|--------|-------|--------|
| Version | 2.0.0 | pyproject.toml, server.py |
| Registered MCP tools | 84 | 52 core (@mcp.tool) + 32 engine (_register_engine_tools) |
| Production-safe (read-only) | 31 | CANONICAL_TOOL_SURFACE.md |
| Supervised-only (writes) | 21 | CANONICAL_TOOL_SURFACE.md |
| Advisory-only (recommendations) | 32 | CANONICAL_TOOL_SURFACE.md |
| Tests passing | 137 | pytest (original with real accounts.yaml) |
| Tests passing (product copy) | 133 | pytest (product with fake accounts.yaml) |

## Live Validation Record

**Date:** 2026-03-27
**Account:** Test account (act_XXXXXXXXX)
**Operator:** [operator] via Claude Code

| Test | Tool | Action | Result |
|:---:|------|--------|:---:|
| 1 | update_campaign | Rename (valid naming convention) | PASS - verified |
| 2 | update_campaign | Rename (invalid "[TEST]" suffix) | BLOCKED by naming gate |
| 3 | update_campaign | Restore original name | PASS - verified |
| 4 | update_adset | Budget EUR 9 -> EUR 10 (ABO) | PASS - verified |
| 5 | update_adset | Restore budget EUR 9 | PASS - verified |
| 6 | update_ad | Rename (invalid format) | BLOCKED by naming gate |
| 7 | update_ad | Rename (valid format) | PASS - verified |
| 8 | update_ad | Restore name | PASS - verified |

**Bug found during live testing:** `detect_budget_model` called without underscore prefix and wrong argument type in update_adset. Fixed to `_detect_budget_model(parent_campaign)`. Fix verified, tests pass.

## Phase History

| Phase | What | Outcome |
|-------|------|---------|
| A | Product surface audit, scaffold cleanup, truth alignment | 7 dead scaffolds deleted, identity.py classified as internal helper, TODO intent preserved in PRODUCT_GAP_REGISTER.md |
| B | Version alignment, doc truth alignment, TOOLS.md coverage | Version 2.0.0, all 84 tools documented, phase table v1.0-v2.0 |
| B.5 | Commercial truth gate | Intended identity defined, gap prioritization, launch verdict |
| C.1 | update_campaign implementation | Registered, tested (11 tests), live validated |
| C.2 | update_adset implementation | Registered, tested (11 tests), live validated |
| C.3 | update_ad implementation | Registered, tested (10 tests), live validated |
| D | Launch hardening | Counts aligned (84/31/21/32), GAPs resolved, reporting dead code deleted, full-suite synced |

## Launch Identity

Supervised Meta Ads Operating System - core CRUD, gated writes, advisory optimization.

## Launch Copy Baseline

Canonical source: `LAUNCH_COPY_FROZEN.md` in this directory.

## Banned Claims (permanent)

- autonomous optimization
- AI-powered
- full CRUD
- replaces Meta Ads Manager
- most comprehensive
- end-to-end autonomous
- enterprise-grade
- intelligence-driven
- set it and forget it
- complete Meta Ads management
- 90 tools / 88 tools / 81 tools (correct: 84)
- production-tested (use "developed through management of" instead)

## Open Gaps (post-launch, not release blockers)

| GAP | Item | Priority |
|-----|------|----------|
| 015 | create_ad_creative | P2 |
| 016 | create_product_set | P1 |
| 017 | update_product_set | P2 |
| 005 | Image upload tool | P1 |
| 007 | Campaign duplication | P1 |

## Verification Commands

```bash
# Version
grep 'version = "2.0.0"' pyproject.toml
grep '"2.0.0"' meta_ads_mcp/server.py

# Tool count
grep -c "^@mcp.tool" meta_ads_mcp/core/*.py  # -> 52 total across files
grep -c "    mcp.tool()" meta_ads_mcp/server.py  # -> 32

# Tests
uv run --extra dev python -m pytest tests/ -v  # -> 137 passed (original) / 133 passed (product)

# Zero client data (product copy only)
# Search all .py/.yaml/.md files for real client names - must return 0 results

# Zero leaked tokens (product copy only)
grep -rE "pit-[a-f0-9]|EAA[A-Z]|sk-[a-z]" products/mcp-servers/meta-ads-mcp/ --include="*.py" --include="*.yaml" --exclude-dir=.venv  # -> 0

# Update tools registered
grep -A1 "^@mcp.tool" meta_ads_mcp/core/campaigns.py | grep "def update_campaign"
grep -A1 "^@mcp.tool" meta_ads_mcp/core/adsets.py | grep "def update_adset"
grep -A1 "^@mcp.tool" meta_ads_mcp/core/ads.py | grep "def update_ad"

# No reporting dead code (product copy only)
test ! -d products/mcp-servers/meta-ads-mcp/meta_ads_mcp/reporting && echo PASS
```
