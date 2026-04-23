# KonQuest Meta Ads MCP

Supervised Meta Ads Operating System for Claude Code.
You can find the premium version here: https://farasokster.gumroad.com/l/konquest-meta-ads-mcp-premium
## Open-Core Model

KonQuest Meta Ads MCP uses an open-core model:

**Public (this repo) - 57 tools, MIT license:**
- Full CRUD for campaigns, ad sets, and ads
- Multi-asset ad creation (video + static image, multi-dimension)
- Image upload and retrieval
- Campaign and ad set duplication
- Insights and bulk cross-account analytics
- Pixel and tracking diagnostics (5 tools)
- Catalog and DPA support (6 tools, including product set create/update)
- Full targeting toolkit (6 tools)
- Setup readiness checker (42+ checks with fix instructions)
- Validation pipeline, naming enforcement, post-write verification
- Safety tiers, rate limiting, rollback references
- 215 automated tests

**Premium bundle - adds 41 tools:**
- Advisory optimization engine (review queues, learning, experiments, budget governor, creative rotation)
- Vault intelligence and copy generation (brand voice, ICP targeting, concept selection)
- Greek language QA (Greeklish detection, orthography checks)
- Automation suite (diagnostics, bulk operations, account audit)
- Vault bootstrap (15 template files per client)
- Premium tests and evaluations

Premium bundle available separately. Public tools work fully without it.

## What Makes This Different

- **Production-tested** across 37+ client campaigns with real budgets and real edge cases
- **Not a wrapper** - includes optimization engine, safety gates, validators, and rollback
- **Vault-integrated** - reads client intelligence (ICPs, brand voice, angles) to generate better ads
- **Greek language QA** built in (adaptable to any language validation)
- **All ads created PAUSED** - nothing goes live without explicit operator approval
- **Supervised, not autonomous** - operator confirms every write, every activation, every budget change

## Tool Classification

| Classification | Count | Description |
|----------------|:---:|-------------|
| production-safe | 38 | Read-only data access. No API writes, no local state changes. |
| supervised-only | 29 | Write/delete operations requiring operator approval before execution. |
| advisory-only | 31 | Generate recommendations, plans, copy, diagnostics. No Meta API writes. May write local files. |
| **Total: 98 registered** | |

## Architecture

```
meta_ads_mcp/
  core/          # 66 tools - API read/write operations
  engine/        # 32 tools - optimization, review, learning, experiments
  validators/    # Quality gates (compliance, creative specs, tracking, structure)
  safety/        # Rate limiting, rollback, duplicate checking, file locks, tier access
  ingestion/     # Internal: video manifest management
  reporting/     # Internal: not currently active (see Non-Shipped Code)
```

## Tool Categories

| Category | Tools | Description |
|----------|:---:|-------------|
| Account Management | 6 | Token health, ad accounts, pages, IG identity, discovery |
| Campaigns | 4 | Create, read, update campaigns |
| Ad Sets | 4 | Create, read, update ad sets with targeting |
| Ads | 4 | Create, read, update ads |
| Creatives | 3 | Create, read ad creatives |
| Insights & Analytics | 1 | Performance data with archetype-aware normalization |
| Pixels & Tracking | 5 | Pixel health, event diagnostics, test events, CAPI |
| Catalogs & DPA | 6 | Product catalogs, feeds, product sets, validation |
| Audiences | 1 | Custom audience listing |
| Targeting | 3 | Interest, behavior, and geo search |
| Video Management | 3 | Upload (simple + resumable) and processing status |
| Ad Builder | 1 | Multi-asset ad creation with IG gate enforcement |
| Copy Engine | 2 | Vault-driven ad copy generation and validation |
| Naming Convention | 1 | Enforced naming schema for all objects |
| Automation & Diagnostics | 6 | Greek QA, full diagnostic, bulk ops, account audit |
| Vault & Intelligence | 2 | Client vault reader, concept selection |
| Optimization Engine | 4 | Optimization cycles, launch planning, execution packs |
| Mutation Corridor | 2 | Budget/targeting changes with verification |
| Activation & Rollback | 4 | Status changes and undo with preflight checks |
| Review Queue | 7 | Operator review queue, outcome snapshots, digests |
| Learning Layer | 5 | Policy memory, outcome evaluation, learning cycles |
| Experiments | 7 | A/B testing, budget governor, creative rotation, scaling |
| Copy Generation | 2 | Auto copy chain, vault-grounded Greek copy |

## Engine Features

- **Optimization loops** - automated budget shifting based on performance signals
- **Experiment management** - A/B test tracking with statistical significance
- **Budget governors** - prevent overspend with configurable daily/lifetime limits
- **Creative rotation** - fatigue detection and automatic creative refresh triggers
- **Policy learning** - tracks action outcomes and adapts confidence over time
- **Naming gate** - hard enforcement of naming conventions before any API write

## Safety Features

- **Rate limiting** - respects Meta API rate limits with backoff
- **Rollback** - undo recent changes with execution journal
- **Duplicate checking** - prevents accidental duplicate campaigns/ads
- **File locks** - safe concurrent access to vault storage
- **Tier-based access** - safety tiers per account (sandbox, standard, production)

## Validator Suite

- **Compliance validator** - Meta ad policy pre-check
- **Creative spec validator** - image/video dimension and format validation
- **Tracking validator** - pixel and event verification before launch
- **Structure validator** - campaign structure consistency checks
- **Operational validator** - budget, schedule, and targeting sanity checks

## Non-Shipped Code

Code that exists in the repository but is NOT part of the active tool surface:

- **reporting/templates.py, reporting/formatter.py** - not imported at runtime, no active report generation
- **evals/** - internal evaluation stubs, not operator-facing
- **Internal helpers** (not MCP tools): identity.py (IG resolution), api.py (HTTP client), auth.py (token verification), utils.py (format helpers), safety/ (rate limiter, rollback, dedup), validators/ (pre-write validation pipeline)

## Setup

### 1. Install

```bash
cd meta-ads-mcp
uv sync
```

### 2. Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required:
- `META_ACCESS_TOKEN` - Meta Marketing API access token (system user token recommended)

Optional:
- `META_APP_SECRET` - for appsecret_proof (recommended for production)
- `META_APP_ID` - Meta app ID
- `VAULT_PATH` - path to your marketing vault directory (defaults to `~/marketing-vault`)

### 3. MCP Configuration

Add to your Claude Code MCP config (`.mcp.json`):

```json
{
  "mcpServers": {
    "meta-ads": {
      "command": "uv",
      "args": ["--directory", "/path/to/konquest-meta-ads-mcp", "run", "python", "-m", "meta_ads_mcp"],
      "env": {
        "META_ACCESS_TOKEN": "your_token_here",
        "VAULT_PATH": "/path/to/your/marketing-vault"
      }
    }
  }
}
```

Or, for OpenAI's codex add this to your ./codex/config.toml:
```toml
[mcp_servers.konquestmetaads]
command = "uv"
args = ["--directory", "/path/to/konquest-meta-ads-mcp", "run", "python", "-m", "meta_ads_mcp"]

[mcp_servers.konquestmetaads.env]
META_ACCESS_TOKEN = "your_token_here"
```

### 4. Vault Structure (Optional)

If using the vault integration for client intelligence:

```
your-vault/
  01_CLIENTS/{client-slug}/
    00-profile.md        # Account IDs, pixel, page, IG
    02-icp-personas.md   # Target audience profiles
    04-brand-voice.md    # Tone, language, style rules
    05-messaging-house.md # Angles, value props
    08-objections.md     # Objections + bias deployment
    matrix.md            # Decision Matrix
  02_COMPETITORS/{slug}/
    landscape.md         # Competitive landscape
```

## Testing

```bash
uv run --extra dev python -m pytest tests/ -v
# Public package: 215 passed | Full (with premium): 246 passed
```

## License

MIT - see [LICENSE](LICENSE).
