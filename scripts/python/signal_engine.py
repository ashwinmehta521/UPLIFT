"""
signal_engine.py
-----------------
Fetches live market data from Kite Connect, hands it to Claude (with web
search enabled for current news) for a structured five-factor analysis, and
returns a BUY / SELL / HOLD verdict + confidence + reasoning.

This module ONLY produces a recommendation. It never calls kite.place_order().
Wire its output into your existing Telegram approval bot so a human still
taps Approve/Reject before anything reaches the market — same
human-in-the-loop pattern as the rest of equity-agent.

Requires (add to requirements.txt):
    kiteconnect
    python-dotenv
    requests

.env should contain:
    KITE_API_KEY=...
    KITE_ACCESS_TOKEN=...      # refreshed daily by refresh_token.py
    ANTHROPIC_API_KEY=...
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("signal_engine")

KITE_API_KEY = os.environ["KITE_API_KEY"]
KITE_ACCESS_TOKEN = os.environ["KITE_ACCESS_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Pin a dated/known-good model string. Check
# https://docs.claude.com/en/docs/about-claude/models/overview before bumping.
CLAUDE_MODEL = "claude-sonnet-5"

# Client-side tool that forces Claude's final answer through the Anthropic
# API's own JSON-schema validation, instead of asking it to hand-write JSON
# as text (which occasionally breaks on stray quotes/commas inside notes).
_FACTOR_NAMES = ("fundamentals", "macro", "sentiment", "industry_trends", "institutional_flows")

SUBMIT_ANALYSIS_TOOL = {
    "name": "submit_analysis",
    "description": "Submit the completed five-factor stock analysis and verdict.",
    "input_schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "verdict": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "factors": {
                "type": "object",
                "properties": {
                    name: {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": -100, "maximum": 100},
                            "note": {"type": "string"},
                        },
                        "required": ["score", "note"],
                    }
                    for name in _FACTOR_NAMES
                },
                "required": list(_FACTOR_NAMES),
            },
            "technical_summary": {"type": "string"},
            "news_summary": {"type": "string"},
            "suggested_entry": {"type": ["number", "null"]},
            "suggested_stop": {"type": ["number", "null"]},
            "suggested_target": {"type": ["number", "null"]},
            "reasoning": {"type": "string"},
        },
        "required": [
            "symbol", "verdict", "confidence", "factors",
            "technical_summary", "news_summary", "reasoning",
        ],
    },
}

kite = KiteConnect(api_key=KITE_API_KEY)
kite.set_access_token(KITE_ACCESS_TOKEN)


# ---------------------------------------------------------------------------
# 1. Market data (Kite Connect)
# ---------------------------------------------------------------------------

def fetch_market_data(symbol: str, exchange: str = "NSE", history_days: int = 400) -> dict:
    """Pull quote, OHLC, depth, and recent daily candles for a symbol."""
    instrument = f"{exchange}:{symbol}"

    quote = kite.quote([instrument])[instrument]
    ohlc = kite.ohlc([instrument])[instrument]
    instrument_token = quote["instrument_token"]

    to_date = datetime.now()
    from_date = to_date - timedelta(days=history_days)
    historical = kite.historical_data(instrument_token, from_date, to_date, "day")

    return {
        "symbol": symbol,
        "exchange": exchange,
        "ltp": quote.get("last_price"),
        "net_change": quote.get("net_change"),
        "volume": quote.get("volume"),
        "oi": quote.get("oi"),
        "ohlc": ohlc,
        "depth": quote.get("depth"),
        # last 60 sessions is enough context for trend/momentum without
        # bloating the prompt — Claude doesn't need 400 days of candles
        "historical": historical[-60:],
    }


# ---------------------------------------------------------------------------
# 2. Prompt construction
# ---------------------------------------------------------------------------

def build_prompt(market_data: dict) -> str:
    candles = [
        {
            "d": str(c["date"])[:10],
            "o": c["open"], "h": c["high"], "l": c["low"],
            "c": c["close"], "v": c["volume"],
        }
        for c in market_data["historical"]
    ]

    return f"""You are a disciplined equity analyst covering Indian markets (NSE/BSE).
Analyze {market_data['symbol']} ({market_data['exchange']}) using the live data below,
plus current news you find via web search.

LIVE SNAPSHOT
LTP: {market_data['ltp']}
Net change: {market_data.get('net_change')}
Day OHLC: {market_data['ohlc']}
Volume: {market_data.get('volume')}
Open Interest (if derivative): {market_data.get('oi')}
Top of book depth: {json.dumps(market_data.get('depth'))}

RECENT DAILY CANDLES (oldest -> newest, last 60 sessions)
{json.dumps(candles)}

TASK
1. Search the web for news on this company from the last 30 days: earnings/results,
   management commentary, credit rating actions, regulatory or legal developments,
   sector-specific news, and any relevant macro developments (RBI policy, budget,
   global cues, crude/currency moves if relevant to the sector).
2. Score five factors on a -100 (very bearish) to +100 (very bullish) scale:
   - fundamentals: valuation, earnings trend, balance sheet health
   - macro: rates, RBI policy, fiscal/budget factors relevant to this sector
   - sentiment: news tone, analyst commentary, retail/FII mood
   - industry_trends: sector tailwinds/headwinds, competitive position
   - institutional_flows: FII/DII activity, bulk/block deals if you find them
3. Weigh those factors against the price/volume data to reach one verdict.
4. Once your research is complete, call the submit_analysis tool exactly once
   with your full analysis. Do not write any JSON as plain text — use the tool.
"""


# ---------------------------------------------------------------------------
# 3. Claude call
# ---------------------------------------------------------------------------

def _extract_tool_input(content_blocks: list, tool_name: str) -> dict:
    """Pull the parsed input dict straight from the tool_use block.

    This is the whole point of using a tool instead of free-text JSON: the
    Anthropic API validates/parses the structure server-side, so `input` is
    already a Python dict here — no string parsing, no delimiter errors.
    """
    for block in content_blocks:
        if block.get("type") == "tool_use" and block.get("name") == tool_name:
            return block["input"]
    raise ValueError(f"No '{tool_name}' tool call found in Claude's response.")


def get_claude_analysis(market_data: dict, max_retries: int = 2) -> dict:
    prompt = build_prompt(market_data)

    last_err: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": 4000,
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": [
                        {"type": "web_search_20250305", "name": "web_search"},
                        SUBMIT_ANALYSIS_TOOL,
                    ],
                },
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            return _extract_tool_input(data.get("content", []), "submit_analysis")

        except (requests.RequestException, ValueError, KeyError) as e:
            last_err = e
            log.warning("Claude analysis attempt %d failed: %s", attempt + 1, e)

    raise RuntimeError(f"Claude analysis failed after {max_retries + 1} attempts: {last_err}")


# ---------------------------------------------------------------------------
# 4. Orchestrator — this is what the rest of equity-agent should import
# ---------------------------------------------------------------------------

def analyze(symbol: str, exchange: str = "NSE") -> dict:
    """
    Returns a structured verdict dict. Does NOT place any order.
    Hand the result to your Telegram approval bot, e.g.:

        from signal_engine import analyze
        from telegram_approval_bot import send_approval_request

        verdict = analyze("SBIN")
        if verdict["verdict"] != "HOLD" and verdict["confidence"] >= 65:
            send_approval_request(verdict)   # human taps Approve/Reject
    """
    log.info("Fetching market data for %s:%s", exchange, symbol)
    market_data = fetch_market_data(symbol, exchange)

    log.info("Sending to Claude for 5-factor analysis + news search")
    verdict = get_claude_analysis(market_data)

    verdict["_ltp_at_analysis"] = market_data["ltp"]
    verdict["_analyzed_at"] = datetime.now().isoformat()
    return verdict


if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "SBIN"
    exch = sys.argv[2] if len(sys.argv) > 2 else "NSE"

    result = analyze(sym, exch)
    print(json.dumps(result, indent=2))

    print(f"\n--- {result['symbol']}: {result['verdict']} (confidence {result['confidence']}) ---")
    print(result["reasoning"])
    print("\nNote: no order has been placed. Route this verdict through your")
    print("Telegram approval flow before any execution.")