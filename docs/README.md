# KonQuest Meta Ads MCP Server

Supervised operator system for Meta Ads management via MCP protocol.

## System Classification

- **38 production-safe tools** - read-only data access, no API writes
- **29 supervised-only tools** - write/delete operations requiring operator approval
- **31 advisory-only tools** - generate recommendations, plans, copy, diagnostics (no Meta API writes, may write local files)
- **Total: 98 registered MCP tools**

All write operations create ads PAUSED. No ad goes live without explicit operator approval.

## Architecture

```
meta_ads_mcp/
  core/          # 66 tools - API read/write operations
  engine/        # 32 tools - optimization, review, learning, experiments
  validators/    # Quality gates (compliance, creative, tracking, structure)
  safety/        # Rate limiting, rollback, duplicate checking, tier access
  ingestion/     # Internal: video manifest management
  reporting/     # Internal: not currently active
```

## Phase History

| Phase | Tools Added | What It Covers |
|-------|:---:|-------------|
| v1.0 | 6 | Foundation: server, auth, accounts, token health |
| v1.1 | 26 | Read operations: campaigns, ad sets, ads, insights, pixels, catalogs, audiences, targeting |
| v1.3 | 18 | Write corridor: CRUD, video upload, naming, ad builder, vault reader, copy engine, automation |
| v1.4 | 10 | Optimization engine: loops, launch planning, execution packs, mutations |
| v1.5 | 4 | Activation + rollback corridors |
| v1.6-v1.7 | 7 | Review queue, outcome snapshots, operator digest |
| v1.8 | 5 | Learning layer: policy engine, outcome evaluation |
| v1.9 | 9 | Experiments, budget governor, creative rotation, scaling |
| v2.0 | 3 | Concept selection, copy chain, auto copy generation |

## Internal Support Modules (not MCP tools)

These modules support the tool surface but are not exposed as operator-callable tools:

- **identity.py** - Instagram resolution ladder, IG gate enforcement (used by ad_builder, ads, ops, activation)
- **api.py** - Meta Graph API HTTP client with rate limiting
- **auth.py** - Token verification and permission checks
- **utils.py** - Format helpers (account IDs, budgets, serialization)
- **safety/** - Rate limiter, rollback journal, duplicate checker, file locks, tier enforcement
- **validators/** - Pre-write validation: compliance, creative specs, Greek text, tracking, structure

## Non-Shipped Code

Code that exists in the repository but is NOT part of the active tool surface:

- `reporting/templates.py`, `reporting/formatter.py` - not imported at runtime
- `evals/` - internal evaluation stubs
- Deleted scaffolds documented in PRODUCT_GAP_REGISTER.md

## Setup

### Prerequisites
- Python 3.11+
- uv (Python package manager)
- Meta System User token with ad account access

### Installation
```bash
cd meta-ads-mcp
uv sync
```

### Configuration
1. Copy `.env.example` to `.env`, set `META_ACCESS_TOKEN`
2. Run `discover_all_accounts` to populate `config/accounts.yaml`
3. Edit `config/accounts.yaml` with your client slugs and archetypes

### MCP Registration
```json
"meta-ads": {
  "command": "uv",
  "args": ["--directory", "/path/to/meta-ads-mcp", "run", "python", "-m", "meta_ads_mcp"],
  "env": {
    "META_ACCESS_TOKEN": "your_token",
    "VAULT_PATH": "/path/to/vault"
  }
}
```

## Testing
```bash
uv run --extra dev python -m pytest tests/ -v
# Expected: 105 passed
```

## Key Principles
1. No ad goes live without operator confirmation (all created PAUSED)
2. Greek text validated before and after every write
3. All gated writes pass through validator pipeline
4. Every mutation logged with rollback capability
5. Advisory tools recommend - only supervised tools execute
