"""Trading council: runs each selected trader through the full 4-stage ministry pipeline.

Yields SSE events so the frontend can render results progressively.
Reuses stage functions from council.py.
"""

import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from .council import (
    calculate_aggregate_rankings,
    stage0_research,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
)
from .trading_storage import (
    create_trading_session,
    save_master_synthesis,
    save_trading_analysis,
    update_trading_session_status,
)
from .trading_templates import (
    TRADER_REGISTRY,
    build_master_synthesis_prompt,
    build_research_query,
    load_and_fill_template,
)


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


async def run_trading_session(
    user_id: str,
    selected_traders: List[str],
    trader_fields: Dict[str, Dict[str, str]],
    global_settings: Dict[str, Any],
    ministry_models: Optional[List[str]] = None,
    model_personas: Optional[Dict[str, str]] = None,
    prime_minister: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Run a full trading advisory session and yield SSE events.

    Pipeline:
    1. Create session in DB
    2. Stage 0 research (shared)
    3. For each selected trader (excluding mastertrader if auto-synthesizing):
       - Fill template -> run Stage 1->2->3 -> save -> yield events
    4. If 2+ traders ran or mastertrader explicitly selected:
       - Build augmented mastertrader prompt -> run Stage 1->2->3 -> save
    5. Mark session complete
    """
    session_id = str(uuid.uuid4())

    try:
        # Create session
        create_trading_session(session_id, user_id, global_settings, selected_traders)
        yield _sse({"type": "session_created", "session_id": session_id})

        # Determine which traders to run individually vs. auto-master
        individual_traders = [t for t in selected_traders if t != "mastertrader"]
        master_explicitly_selected = "mastertrader" in selected_traders
        should_run_master = master_explicitly_selected or len(individual_traders) >= 2

        # ---- Stage 0: Shared Research ----
        yield _sse({"type": "stage0_start"})
        research_query = build_research_query(global_settings, selected_traders)
        research_briefing = await stage0_research(research_query)
        yield _sse({"type": "stage0_complete", "data": research_briefing})

        # ---- Run each individual trader through the pipeline ----
        completed_trader_results: List[Dict[str, Any]] = []

        for trader_id in individual_traders:
            meta = TRADER_REGISTRY.get(trader_id)
            if not meta:
                continue

            trader_name = meta["name"]
            fields = trader_fields.get(trader_id, {})

            yield _sse({
                "type": "trader_start",
                "trader_id": trader_id,
                "trader_name": trader_name,
            })

            # Fill the template
            filled_prompt = load_and_fill_template(trader_id, fields, global_settings)

            # Stage 1
            yield _sse({"type": "trader_stage1_start", "trader_id": trader_id})
            stage1 = await stage1_collect_responses(
                filled_prompt,
                ministry_models=ministry_models,
                model_personas=model_personas,
                research_briefing=research_briefing,
            )
            yield _sse({
                "type": "trader_stage1_complete",
                "trader_id": trader_id,
                "data": stage1,
            })

            # Stage 2
            yield _sse({"type": "trader_stage2_start", "trader_id": trader_id})
            stage2, label_to_model = await stage2_collect_rankings(
                filled_prompt,
                stage1,
                ministry_models=ministry_models,
                research_briefing=research_briefing,
            )
            aggregate = calculate_aggregate_rankings(stage2, label_to_model)
            yield _sse({
                "type": "trader_stage2_complete",
                "trader_id": trader_id,
                "data": stage2,
                "metadata": {
                    "label_to_model": label_to_model,
                    "aggregate_rankings": aggregate,
                },
            })

            # Stage 3
            yield _sse({"type": "trader_stage3_start", "trader_id": trader_id})
            stage3 = await stage3_synthesize_final(
                filled_prompt,
                stage1,
                stage2,
                prime_minister=prime_minister,
                research_briefing=research_briefing,
            )
            yield _sse({
                "type": "trader_stage3_complete",
                "trader_id": trader_id,
                "data": stage3,
            })

            # Save to DB
            save_trading_analysis(
                session_id=session_id,
                trader_id=trader_id,
                trader_name=trader_name,
                prompt_text=filled_prompt,
                stage0=research_briefing,
                stage1=stage1,
                stage2=stage2,
                stage3=stage3,
                metadata={"label_to_model": label_to_model, "aggregate_rankings": aggregate},
            )

            completed_trader_results.append({
                "trader_id": trader_id,
                "trader_name": trader_name,
                "stage3": stage3,
            })

        # ---- Master Trader Synthesis ----
        if should_run_master:
            yield _sse({"type": "master_start"})

            # Build the augmented mastertrader prompt
            master_fields = trader_fields.get("mastertrader", {})
            base_prompt = load_and_fill_template("mastertrader", master_fields, global_settings)
            augmented_prompt = build_master_synthesis_prompt(
                base_prompt, completed_trader_results, research_briefing
            )

            # Stage 1
            yield _sse({"type": "master_stage1_start"})
            master_s1 = await stage1_collect_responses(
                augmented_prompt,
                ministry_models=ministry_models,
                model_personas=model_personas,
                research_briefing=research_briefing,
            )
            yield _sse({"type": "master_stage1_complete", "data": master_s1})

            # Stage 2
            yield _sse({"type": "master_stage2_start"})
            master_s2, master_l2m = await stage2_collect_rankings(
                augmented_prompt,
                master_s1,
                ministry_models=ministry_models,
                research_briefing=research_briefing,
            )
            master_agg = calculate_aggregate_rankings(master_s2, master_l2m)
            yield _sse({
                "type": "master_stage2_complete",
                "data": master_s2,
                "metadata": {
                    "label_to_model": master_l2m,
                    "aggregate_rankings": master_agg,
                },
            })

            # Stage 3
            yield _sse({"type": "master_stage3_start"})
            master_s3 = await stage3_synthesize_final(
                augmented_prompt,
                master_s1,
                master_s2,
                prime_minister=prime_minister,
                research_briefing=research_briefing,
            )
            yield _sse({"type": "master_stage3_complete", "data": master_s3})

            # Save master synthesis
            save_master_synthesis(
                session_id=session_id,
                prompt_text=augmented_prompt,
                stage1=master_s1,
                stage2=master_s2,
                stage3=master_s3,
                metadata={"label_to_model": master_l2m, "aggregate_rankings": master_agg},
            )

        # ---- Complete ----
        update_trading_session_status(session_id, "complete")
        yield _sse({"type": "complete", "session_id": session_id})

    except Exception as e:
        # Mark session as errored
        try:
            update_trading_session_status(session_id, "error")
        except Exception:
            pass
        yield _sse({"type": "error", "message": str(e)})
