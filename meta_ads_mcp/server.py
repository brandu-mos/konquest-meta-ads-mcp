"""
KonQuest Meta Ads MCP Server.

Supervised Meta Ads Operating System for Claude Code.
Open-core: public tools always available, premium tools require premium bundle.
"""
import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("konquest-meta-ads")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

mcp = FastMCP(
    "KonQuest Meta Ads MCP",
    instructions="Supervised Meta Ads Operating System for Claude Code. Create, read, update, duplicate campaigns, ad sets, and ads with validation gates, naming enforcement, and operator control.",
)

# ============================================================
# PUBLIC TOOLS (open-core, always available)
# ============================================================

# --- Accounts & Auth ---
from meta_ads_mcp.core import accounts  # noqa: E402, F401

# --- Campaign / Ad Set / Ad CRUD ---
from meta_ads_mcp.core import campaigns  # noqa: E402, F401
from meta_ads_mcp.core import adsets  # noqa: E402, F401
from meta_ads_mcp.core import ads  # noqa: E402, F401
from meta_ads_mcp.core import creatives  # noqa: E402, F401

# --- Read Operations ---
from meta_ads_mcp.core import insights  # noqa: E402, F401
from meta_ads_mcp.core import pixels  # noqa: E402, F401
from meta_ads_mcp.core import catalogs  # noqa: E402, F401
from meta_ads_mcp.core import audiences  # noqa: E402, F401
from meta_ads_mcp.core import targeting  # noqa: E402, F401

# --- Assets ---
from meta_ads_mcp.core import images  # noqa: E402, F401
from meta_ads_mcp.core import video  # noqa: E402, F401

# --- Write Operations ---
from meta_ads_mcp.core import naming  # noqa: E402, F401
from meta_ads_mcp.core import ad_builder  # noqa: E402, F401
from meta_ads_mcp.core import ops  # noqa: E402, F401
from meta_ads_mcp.core import vault_reader  # noqa: E402, F401
from meta_ads_mcp.core import duplication  # noqa: E402, F401

# --- Setup & Readiness ---
from meta_ads_mcp.core import setup  # noqa: E402, F401
# identity.py: active internal helper (imported by ad_builder, ads, ops). Not exposed as MCP tool.

# ============================================================
# PREMIUM TOOLS (available only in premium bundle)
# ============================================================

from meta_ads_mcp.premium import PREMIUM_AVAILABLE

if PREMIUM_AVAILABLE:
    logger.info("Premium bundle detected - loading premium tools")

    # --- Premium Core Modules ---
    from meta_ads_mcp.core import copy_engine  # noqa: E402, F401
    from meta_ads_mcp.core import automation  # noqa: E402, F401
    from meta_ads_mcp.core import vault_bootstrap  # noqa: E402, F401

    # --- Premium Engine: Decision & Optimization ---
    def _register_engine_tools():
        from meta_ads_mcp.engine.loop import run_optimization_cycle
        from meta_ads_mcp.engine.planner import create_launch_plan
        from meta_ads_mcp.engine.executor import build_execution_pack, execute_paused_launch
        from meta_ads_mcp.engine.mutations import build_mutation_pack, execute_mutation_pack
        from meta_ads_mcp.engine.activation import (
            build_activation_pack, execute_activation_pack,
            build_rollback_pack, execute_rollback_pack,
        )
        mcp.tool()(run_optimization_cycle)
        mcp.tool()(create_launch_plan)
        mcp.tool()(build_execution_pack)
        mcp.tool()(execute_paused_launch)
        mcp.tool()(build_mutation_pack)
        mcp.tool()(execute_mutation_pack)
        mcp.tool()(build_activation_pack)
        mcp.tool()(execute_activation_pack)
        mcp.tool()(build_rollback_pack)
        mcp.tool()(execute_rollback_pack)
        # Review Queue + Snapshots
        from meta_ads_mcp.engine.review import (
            build_review_queue, list_review_queue,
            resolve_review_item, record_outcome_snapshot,
            expire_stale_queue_items, build_operator_digest,
            run_scheduled_review_cycle,
        )
        mcp.tool()(build_review_queue)
        mcp.tool()(list_review_queue)
        mcp.tool()(resolve_review_item)
        mcp.tool()(record_outcome_snapshot)
        mcp.tool()(expire_stale_queue_items)
        mcp.tool()(build_operator_digest)
        mcp.tool()(run_scheduled_review_cycle)
        # Learning Layer + Policy Engine
        from meta_ads_mcp.engine.learning import (
            evaluate_execution_outcome, update_policy_memory,
            get_policy_memory, build_learning_digest, run_learning_cycle,
        )
        mcp.tool()(evaluate_execution_outcome)
        mcp.tool()(update_policy_memory)
        mcp.tool()(get_policy_memory)
        mcp.tool()(build_learning_digest)
        mcp.tool()(run_learning_cycle)
        # Experimentation + Budget Governor + Creative Rotation
        from meta_ads_mcp.engine.experiments import (
            build_experiment_plan, evaluate_experiment,
            rotate_creative_set, run_budget_governor,
            promote_experiment_winner, get_experiment_registry,
            run_scaling_cycle,
        )
        mcp.tool()(build_experiment_plan)
        mcp.tool()(evaluate_experiment)
        mcp.tool()(rotate_creative_set)
        mcp.tool()(run_budget_governor)
        mcp.tool()(promote_experiment_winner)
        mcp.tool()(get_experiment_registry)
        mcp.tool()(run_scaling_cycle)
        # Concept Selection + Copy Chain
        from meta_ads_mcp.engine.concepts import select_concepts
        from meta_ads_mcp.engine.copy_chain import generate_copy_package, validate_copy_output
        mcp.tool()(select_concepts)

        def generate_ad_copy_chain(
            account_id: str,
            concept_json: str,
            transcript_excerpt: str = None,
        ) -> dict:
            """
            Generate vault-grounded ad copy for a selected concept.

            Full chain: vault -> normalized data -> copy brief -> generation instructions.

            Args:
                account_id: Ad account ID.
                concept_json: JSON of selected concept from select_concepts.
                transcript_excerpt: Optional SRT text for creative alignment.
            """
            import json as _json
            from meta_ads_mcp.core.vault_reader import enforce_vault_gate
            from meta_ads_mcp.core.utils import ensure_account_id_format

            account_id = ensure_account_id_format(account_id)
            vault_error, vault_ctx = enforce_vault_gate(account_id, "create_ad")
            if vault_error:
                return vault_error

            try:
                concept = _json.loads(concept_json)
            except:
                return {"error": "Malformed concept_json"}

            return generate_copy_package(vault_ctx, concept, transcript_excerpt)

        mcp.tool()(generate_ad_copy_chain)

        # Auto Copy Generation
        from meta_ads_mcp.engine.copy_generator import auto_generate_for_write

        def generate_auto_copy(
            account_id: str,
            angle_name: str,
            icp_name: str = "",
            funnel_stage: str = "tofu",
            copy_mode: str = "auto",
            existing_primary_text: str = None,
            existing_headline: str = None,
            existing_description: str = None,
            transcript_excerpt: str = None,
        ) -> dict:
            """
            Generate vault-grounded ad copy automatically.

            Assembles primary_text, headline, description from vault intelligence.
            Validates for language integrity, forbidden words, generic content.

            Args:
                account_id: Ad account ID.
                angle_name: Marketing angle.
                icp_name: Target ICP.
                funnel_stage: 'tofu', 'mofu', 'bofu'.
                copy_mode: 'auto', 'manual', 'hybrid'.
                existing_primary_text: For manual/hybrid modes.
                existing_headline: For manual/hybrid modes.
                existing_description: For manual/hybrid modes.
                transcript_excerpt: Optional SRT text for creative alignment.
            """
            return auto_generate_for_write(
                account_id=account_id,
                angle_name=angle_name,
                icp_name=icp_name,
                funnel_stage=funnel_stage,
                existing_primary_text=existing_primary_text,
                existing_headline=existing_headline,
                existing_description=existing_description,
                copy_mode=copy_mode,
                transcript_excerpt=transcript_excerpt,
            )

        mcp.tool()(generate_auto_copy)

    _register_engine_tools()
else:
    logger.info("Open-core mode - %s public tools loaded. Premium tools not available.", "55")


def main():
    """Run the MCP server. Defaults to stdio; set MCP_TRANSPORT=sse for HTTP/SSE mode."""
    import os
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mode = "premium (98 tools)" if PREMIUM_AVAILABLE else "open-core (55 tools)"
    logger.info("Starting KonQuest Meta Ads MCP server v%s [%s] transport=%s", "2.0.0", mode, transport)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
