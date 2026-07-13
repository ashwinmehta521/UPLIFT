"""
fetch_history.py
-----------------
Fetch the last N years of historical OHLCV data for a stock (symbol given
interactively or via CLI) using the Kite Connect API, then render it as an
interactive candlestick chart with critical points highlighted:
    - 50-day and 200-day moving averages
    - Golden Cross / Death Cross events (50 crossing 200)
    - Swing highs / swing lows (local price extremes)
    - Period high and period low
    - Volume panel

Usage:
    python fetch_history.py
    python fetch_history.py --symbol TVSMOTOR --exchange NSE --years 5

Requires:
    - .env with KITE_API_KEY
    - .kite_session file containing a valid access_token
      (run refresh_token.py first if this is missing or expired)
    - pip install plotly pandas kiteconnect python-dotenv --break-system-packages

Output:
    - <SYMBOL>_<interval>_history.csv   (raw data)
    - <SYMBOL>_dashboard.html           (interactive chart, open in browser)
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteConnect

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    print("[fetch_history] plotly not installed. Run: "
          "pip install plotly --break-system-packages", file=sys.stderr)
    sys.exit(1)

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
SESSION_FILE = ".kite_session"

# Max days per request, by interval (kept slightly under Kite's actual caps).
CHUNK_DAYS = {
    "day": 1900,
    "60minute": 380,
    "30minute": 190,
    "15minute": 190,
    "10minute": 90,
    "5minute": 90,
    "3minute": 90,
    "minute": 55,
}


def fail(msg):
    print(f"[fetch_history] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def load_session():
    if not API_KEY:
        fail("KITE_API_KEY missing from .env")
    if not os.path.exists(SESSION_FILE):
        fail(f"{SESSION_FILE} not found. Run refresh_token.py first to log in.")

    access_token = open(SESSION_FILE).read().strip()
    if not access_token:
        fail(f"{SESSION_FILE} is empty. Run refresh_token.py again.")

    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(access_token)

    try:
        kite.profile()  # cheap call to confirm token is actually valid
    except Exception as e:
        fail(f"Session invalid or expired ({e}). Run refresh_token.py again.")

    return kite


def resolve_instrument_token(kite, symbol, exchange):
    """Look up the numeric instrument token for a tradingsymbol on an exchange."""
    print(f"[fetch_history] Looking up instrument token for {exchange}:{symbol} ...")
    try:
        instruments = kite.instruments(exchange)
    except Exception as e:
        fail(f"Could not fetch instrument list for {exchange}: {e}")

    symbol_upper = symbol.strip().upper()
    matches = [i for i in instruments if i["tradingsymbol"] == symbol_upper]

    if not matches:
        loose = [i for i in instruments if symbol_upper in i["tradingsymbol"]]
        if loose:
            print("[fetch_history] Exact match not found. Closest matches:")
            for m in loose[:10]:
                print(f"    {m['tradingsymbol']}  (token: {m['instrument_token']})")
        fail(f"No exact instrument match for '{symbol_upper}' on {exchange}.")

    if len(matches) > 1:
        print(f"[fetch_history] Multiple matches found, using first: {matches[0]}")

    instrument = matches[0]
    print(f"[fetch_history] Found: {instrument['tradingsymbol']} "
          f"(token: {instrument['instrument_token']}, "
          f"name: {instrument.get('name', 'n/a')})")
    return instrument["instrument_token"]


def fetch_years_history(kite, instrument_token, interval, years):
    """
    Fetch `years` worth of candles, working backward from today in chunks
    sized to the interval's API limit, and stopping once the requested
    date range is covered or the API returns no more data.
    """
    chunk_days = CHUNK_DAYS.get(interval)
    if chunk_days is None:
        fail(f"Unsupported interval '{interval}'. Choose from: {list(CHUNK_DAYS)}")

    start_bound = datetime.now() - timedelta(days=int(years * 365.25))
    all_candles = []
    cursor_to = datetime.now()

    chunk_num = 0
    while cursor_to > start_bound:
        chunk_num += 1
        cursor_from = max(cursor_to - timedelta(days=chunk_days), start_bound)

        print(f"[fetch_history] Chunk {chunk_num}: "
              f"{cursor_from.date()} to {cursor_to.date()} ...")

        try:
            candles = kite.historical_data(
                instrument_token=instrument_token,
                from_date=cursor_from.strftime("%Y-%m-%d %H:%M:%S"),
                to_date=cursor_to.strftime("%Y-%m-%d %H:%M:%S"),
                interval=interval,
                continuous=False,
                oi=False,
            )
        except Exception as e:
            print(f"[fetch_history] Chunk {chunk_num} failed ({e}). Stopping here.")
            break

        if not candles:
            print(f"[fetch_history] No more data before {cursor_to.date()}. "
                  f"Reached start of available history.")
            break

        all_candles.extend(candles)
        cursor_to = cursor_from - timedelta(days=1)

    if not all_candles:
        fail("No historical data returned at all. Check the symbol/exchange/interval.")

    df = pd.DataFrame(all_candles)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return df


def add_technical_markers(df):
    """
    Compute moving averages, crossover events, and swing highs/lows.
    Returns the enriched dataframe plus lists of marker points.
    """
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()

    # Golden Cross (50 crosses above 200) / Death Cross (50 crosses below 200)
    df["above"] = df["sma50"] > df["sma200"]
    df["cross"] = df["above"].astype(int).diff()
    golden_crosses = df[df["cross"] == 1]
    death_crosses = df[df["cross"] == -1]

    # Swing highs / lows: local extremes over a rolling window.
    window = 15
    df["swing_high"] = (
        df["high"] == df["high"].rolling(window * 2 + 1, center=True).max()
    )
    df["swing_low"] = (
        df["low"] == df["low"].rolling(window * 2 + 1, center=True).min()
    )
    swing_highs = df[df["swing_high"] == True]
    swing_lows = df[df["swing_low"] == True]

    # Period high / low.
    period_high_row = df.loc[df["high"].idxmax()]
    period_low_row = df.loc[df["low"].idxmin()]

    return df, {
        "golden_crosses": golden_crosses,
        "death_crosses": death_crosses,
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
        "period_high": period_high_row,
        "period_low": period_low_row,
    }


def build_dashboard(df, markers, symbol, exchange, interval, out_html):
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.75, 0.25], vertical_spacing=0.03,
        subplot_titles=(f"{exchange}:{symbol} — Price", "Volume"),
    )

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="Price",
    ), row=1, col=1)

    # Moving averages
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["sma50"], name="SMA 50",
        line=dict(color="#1f77b4", width=1.3),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["sma200"], name="SMA 200",
        line=dict(color="#ff7f0e", width=1.3),
    ), row=1, col=1)

    # Golden / death crosses
    gc = markers["golden_crosses"]
    if not gc.empty:
        fig.add_trace(go.Scatter(
            x=gc["date"], y=gc["close"], mode="markers", name="Golden Cross",
            marker=dict(symbol="star", size=13, color="gold",
                        line=dict(color="black", width=1)),
        ), row=1, col=1)

    dc = markers["death_crosses"]
    if not dc.empty:
        fig.add_trace(go.Scatter(
            x=dc["date"], y=dc["close"], mode="markers", name="Death Cross",
            marker=dict(symbol="star", size=13, color="black",
                        line=dict(color="white", width=1)),
        ), row=1, col=1)

    # Swing highs / lows
    sh = markers["swing_highs"]
    fig.add_trace(go.Scatter(
        x=sh["date"], y=sh["high"], mode="markers", name="Swing High",
        marker=dict(symbol="triangle-down", size=9, color="red"),
    ), row=1, col=1)

    sl = markers["swing_lows"]
    fig.add_trace(go.Scatter(
        x=sl["date"], y=sl["low"], mode="markers", name="Swing Low",
        marker=dict(symbol="triangle-up", size=9, color="green"),
    ), row=1, col=1)

    # Period high / low
    ph, pl = markers["period_high"], markers["period_low"]
    fig.add_trace(go.Scatter(
        x=[ph["date"]], y=[ph["high"]], mode="markers+text", name="Period High",
        text=[f"High: {ph['high']:.1f}"], textposition="top center",
        marker=dict(symbol="diamond", size=12, color="purple"),
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=[pl["date"]], y=[pl["low"]], mode="markers+text", name="Period Low",
        text=[f"Low: {pl['low']:.1f}"], textposition="bottom center",
        marker=dict(symbol="diamond", size=12, color="brown"),
    ), row=1, col=1)

    # Volume
    colors = ["green" if c >= o else "red" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["volume"], name="Volume",
        marker_color=colors, opacity=0.6,
    ), row=2, col=1)

    fig.update_layout(
        title=f"{exchange}:{symbol} — {interval} candles, critical points highlighted",
        xaxis_rangeslider_visible=False,
        height=850,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        template="plotly_white",
    )

    fig.write_html(out_html, include_plotlyjs="cdn")
    print(f"[fetch_history] Interactive dashboard saved to: {out_html}")


def main():
    parser = argparse.ArgumentParser(description="Fetch N years of history and render an interactive dashboard.")
    parser.add_argument("--symbol", help="Trading symbol, e.g. TVSMOTOR, INFY, SBIN")
    parser.add_argument("--exchange", default="NSE", help="Exchange (default: NSE)")
    parser.add_argument("--interval", default="day",
                         choices=list(CHUNK_DAYS.keys()),
                         help="Candle interval (default: day)")
    parser.add_argument("--years", type=float, default=5.0,
                         help="Years of history to fetch (default: 5)")
    args = parser.parse_args()

    symbol = args.symbol or input("Enter stock symbol (e.g. TVSMOTOR): ").strip()
    exchange = args.exchange.strip().upper()
    interval = args.interval
    years = args.years

    if not symbol:
        fail("No symbol provided.")

    kite = load_session()
    instrument_token = resolve_instrument_token(kite, symbol, exchange)
    df = fetch_years_history(kite, instrument_token, interval, years)

    csv_filename = f"{symbol.upper()}_{interval}_history.csv"
    df.to_csv(csv_filename, index=False)

    df, markers = add_technical_markers(df)

    html_filename = f"{symbol.upper()}_dashboard.html"
    build_dashboard(df, markers, symbol.upper(), exchange, interval, html_filename)

    print("\n" + "=" * 50)
    print(f"Done: {len(df)} candles fetched for {exchange}:{symbol.upper()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"CSV saved to: {csv_filename}")
    print(f"Dashboard saved to: {html_filename}  (open in a browser)")
    print("=" * 50)


if __name__ == "__main__":
    main()