"""Trading template registry and prompt builder.

Manages the 8 trader prompt templates (traders/*.md), provides
metadata for the frontend, and fills placeholder fields at runtime.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Path to trader markdown files
TRADERS_DIR = Path(__file__).parent.parent / "traders"

# ============================================================================
# Trader Registry
# ============================================================================

TRADER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "trader1": {
        "id": "trader1",
        "name": "Equity Trader",
        "description": "5 high-probability trade ideas from live market conditions",
        "file": "trader1.md",
        "fields": [
            {
                "key": "trading_style",
                "label": "Trading Style",
                "type": "select",
                "options": ["DAY TRADER", "SWING TRADER", "POSITION TRADER"],
                "placeholder": "[DAY TRADER / SWING TRADER / POSITION TRADER]",
            },
            {
                "key": "markets",
                "label": "Markets",
                "type": "select",
                "options": ["US EQUITIES", "OPTIONS", "CRYPTO", "FOREX", "FUTURES"],
                "placeholder": "[US EQUITIES / OPTIONS / CRYPTO / FOREX / FUTURES]",
            },
            {
                "key": "risk_per_trade",
                "label": "Risk Per Trade",
                "type": "text",
                "placeholder": "[DOLLAR AMOUNT OR PERCENTAGE OF PORTFOLIO]",
            },
        ],
        "global_field_map": {
            "trading_style": "trading_style",
            "markets": "markets",
            "risk_per_trade": "risk_per_trade",
        },
    },
    "trader2": {
        "id": "trader2",
        "name": "Sentiment Analyst",
        "description": "Real-time X sentiment scoring and crowd positioning analysis",
        "file": "trader2.md",
        "fields": [
            {
                "key": "watchlist",
                "label": "Tickers to Scan",
                "type": "textarea",
                "placeholder": "[LIST YOUR WATCHLIST]",
            },
            {
                "key": "scan_window",
                "label": "Scan Window",
                "type": "select",
                "options": ["LAST 2 HOURS", "6 HOURS", "24 HOURS"],
                "placeholder": "[LAST 2 HOURS / 6 HOURS / 24 HOURS]",
            },
        ],
        "global_field_map": {
            "watchlist": "watchlist",
        },
    },
    "trader3": {
        "id": "trader3",
        "name": "Pine Script Developer",
        "description": "Converts trading ideas into TradingView Pine Script strategies",
        "file": "trader3.md",
        "fields": [
            {
                "key": "strategy_rules",
                "label": "Strategy Rules",
                "type": "textarea",
                "placeholder": "[DESCRIBE YOUR ENTRY, EXIT, STOP LOSS, AND TAKE PROFIT RULES]",
            },
            {
                "key": "timeframe",
                "label": "Timeframe",
                "type": "select",
                "options": ["1 MIN", "5 MIN", "15 MIN", "1 HOUR", "4 HOUR", "DAILY"],
                "placeholder": "[1 MIN / 5 MIN / 15 MIN / 1 HOUR / 4 HOUR / DAILY]",
            },
            {
                "key": "asset_class",
                "label": "Asset Class",
                "type": "select",
                "options": ["STOCKS", "CRYPTO", "FOREX", "FUTURES"],
                "placeholder": "[STOCKS / CRYPTO / FOREX / FUTURES]",
            },
        ],
        "global_field_map": {},
    },
    "trader4": {
        "id": "trader4",
        "name": "Earnings Strategist",
        "description": "Pre-earnings positioning and options strategy recommendations",
        "file": "trader4.md",
        "fields": [
            {
                "key": "ticker",
                "label": "Stock Ticker",
                "type": "text",
                "placeholder": "[TICKER]",
            },
            {
                "key": "account_type",
                "label": "Account Type",
                "type": "select",
                "options": ["OPTIONS APPROVED", "EQUITIES ONLY"],
                "placeholder": "[OPTIONS APPROVED / EQUITIES ONLY]",
            },
            {
                "key": "directional_bias",
                "label": "Directional Bias",
                "type": "select",
                "options": ["BULLISH", "BEARISH", "NEUTRAL"],
                "placeholder": "[BULLISH / BEARISH / NEUTRAL]",
            },
        ],
        "global_field_map": {},
    },
    "trader5": {
        "id": "trader5",
        "name": "Technical Analyst",
        "description": "Chart pattern identification and technical trade plans",
        "file": "trader5.md",
        "fields": [
            {
                "key": "ticker",
                "label": "Ticker",
                "type": "text",
                "placeholder": "[STOCK / CRYPTO / FOREX PAIR]",
            },
            {
                "key": "primary_timeframe",
                "label": "Primary Timeframe",
                "type": "select",
                "options": ["15 MIN", "1 HOUR", "4 HOUR", "DAILY"],
                "placeholder": "[15 MIN / 1 HOUR / 4 HOUR / DAILY]",
            },
            {
                "key": "bias",
                "label": "Bias",
                "type": "select",
                "options": ["LOOKING FOR LONGS", "SHORTS", "BOTH"],
                "placeholder": "[LOOKING FOR LONGS / SHORTS / BOTH]",
            },
        ],
        "global_field_map": {},
    },
    "trader6": {
        "id": "trader6",
        "name": "Risk Manager",
        "description": "Portfolio stress testing and risk exposure analysis",
        "file": "trader6.md",
        "fields": [
            {
                "key": "positions",
                "label": "Current Positions",
                "type": "textarea",
                "placeholder": "[LIST TICKERS AND POSITION SIZES]",
            },
            {
                "key": "account_size",
                "label": "Account Size",
                "type": "text",
                "placeholder": "[TOTAL PORTFOLIO VALUE]",
            },
            {
                "key": "risk_tolerance",
                "label": "Risk Tolerance",
                "type": "select",
                "options": ["CONSERVATIVE", "MODERATE", "AGGRESSIVE"],
                "placeholder": "[CONSERVATIVE / MODERATE / AGGRESSIVE]",
            },
        ],
        "global_field_map": {
            "positions": "open_positions",
            "account_size": "account_size",
            "risk_tolerance": "risk_tolerance",
        },
    },
    "trader7": {
        "id": "trader7",
        "name": "Macro Strategist",
        "description": "Global macro-to-stock translation with sector and ETF picks",
        "file": "trader7.md",
        "fields": [
            {
                "key": "macro_view",
                "label": "Macro View",
                "type": "textarea",
                "placeholder": "[DESCRIBE WHAT YOU BELIEVE IS HAPPENING MACRO]",
            },
            {
                "key": "tradeable_universe",
                "label": "Tradeable Universe",
                "type": "select",
                "options": ["US STOCKS", "ETFS", "OPTIONS", "GLOBAL EQUITIES"],
                "placeholder": "[US STOCKS / ETFS / OPTIONS / GLOBAL EQUITIES]",
            },
        ],
        "global_field_map": {},
    },
    "mastertrader": {
        "id": "mastertrader",
        "name": "Master Trader",
        "description": "Daily trading brief synthesizing sentiment, technicals, macro, and risk",
        "file": "mastertrader.md",
        "fields": [
            {
                "key": "watchlist",
                "label": "Watchlist",
                "type": "textarea",
                "placeholder": "[LIST YOUR TICKERS]",
            },
            {
                "key": "account_size",
                "label": "Account Size",
                "type": "text",
                "placeholder": "[PORTFOLIO VALUE]",
            },
            {
                "key": "open_positions",
                "label": "Open Positions",
                "type": "textarea",
                "placeholder": "[WHAT YOU CURRENTLY HOLD]",
            },
            {
                "key": "todays_focus",
                "label": "Today's Focus",
                "type": "select",
                "options": ["DAY TRADE", "SWING", "BOTH"],
                "placeholder": "[DAY TRADE / SWING / BOTH]",
            },
        ],
        "global_field_map": {
            "watchlist": "watchlist",
            "account_size": "account_size",
            "open_positions": "open_positions",
        },
    },
}


def _load_template(trader_id: str) -> str:
    """Load a trader markdown template from disk."""
    meta = TRADER_REGISTRY.get(trader_id)
    if not meta:
        raise ValueError(f"Unknown trader: {trader_id}")
    path = TRADERS_DIR / meta["file"]
    return path.read_text()


def load_and_fill_template(
    trader_id: str,
    field_values: Dict[str, str],
    global_settings: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Load a trader template and substitute placeholder brackets with values.

    Priority: per-trader field_values > global_settings mapping > leave placeholder.
    """
    template = _load_template(trader_id)
    meta = TRADER_REGISTRY[trader_id]
    global_settings = global_settings or {}
    global_map = meta.get("global_field_map", {})

    for field_def in meta["fields"]:
        key = field_def["key"]
        placeholder = field_def["placeholder"]

        # Priority: explicit field value > global setting > leave as-is
        value = field_values.get(key)
        if not value and key in global_map:
            value = global_settings.get(global_map[key])
        if value:
            template = template.replace(placeholder, value)

    return template


def build_master_synthesis_prompt(
    base_prompt: str,
    trader_results: List[Dict[str, Any]],
    research_briefing: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build the master trader prompt augmented with all previous trader syntheses.

    Appends each trader's Stage 3 synthesis to the base mastertrader template
    so the master trader can produce a unified daily brief.
    """
    parts = [base_prompt, "", "---", ""]
    parts.append("PREVIOUS TRADER ANALYSES (Stage 3 Syntheses):")
    parts.append("")

    for result in trader_results:
        trader_name = result.get("trader_name", "Unknown Trader")
        stage3 = result.get("stage3", {})
        synthesis = stage3.get("response", "") if isinstance(stage3, dict) else ""
        if synthesis:
            parts.append(f"### {trader_name}")
            parts.append(synthesis)
            parts.append("")

    if research_briefing:
        parts.append("---")
        parts.append("RESEARCH BRIEFING:")
        if research_briefing.get("key_facts"):
            parts.append(research_briefing["key_facts"])
        if research_briefing.get("summary"):
            parts.append(research_briefing["summary"])
        parts.append("")

    parts.append("---")
    parts.append(
        "Synthesize ALL of the above trader analyses into your unified daily trading brief. "
        "Resolve any conflicts, highlight consensus, and provide your top actionable recommendations."
    )

    return "\n".join(parts)


def build_research_query(
    global_settings: Dict[str, Any],
    selected_traders: List[str],
) -> str:
    """Construct a market-focused research query from global settings for Stage 0."""
    parts = ["Current market conditions and trading opportunities"]

    watchlist = global_settings.get("watchlist", "").strip()
    if watchlist:
        parts.append(f"for: {watchlist}")

    markets = global_settings.get("markets", "").strip()
    if markets:
        parts.append(f"in {markets}")

    trader_names = []
    for tid in selected_traders:
        meta = TRADER_REGISTRY.get(tid)
        if meta and tid != "mastertrader":
            trader_names.append(meta["name"].lower())
    if trader_names:
        parts.append(f"covering {', '.join(trader_names)} perspectives")

    return " ".join(parts)


def get_templates_metadata() -> List[Dict[str, Any]]:
    """Return field metadata for the frontend (no prompt text exposed)."""
    result = []
    for trader_id, meta in TRADER_REGISTRY.items():
        result.append({
            "id": meta["id"],
            "name": meta["name"],
            "description": meta["description"],
            "fields": meta["fields"],
            "global_field_map": meta.get("global_field_map", {}),
        })
    return result
