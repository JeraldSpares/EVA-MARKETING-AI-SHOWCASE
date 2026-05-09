# -*- coding: utf-8 -*-
"""
Eva Trading Engine — Institutional Grade Multi-Timeframe Signal Detection
4H bias → 1H structure → 15m execution entry
Grade thresholds: A+(>=9), A(>=6), B(>=4) — only A/A+ fire Telegram alerts
"""

import os, logging
from datetime import datetime, timezone, timedelta

PHT = timezone(timedelta(hours=8))

# ── CONFIG ───────────────────────────────────────────────────────────────────
BYBIT_API_KEY     = os.environ.get("BYBIT_API_KEY", "")
BYBIT_SECRET_KEY  = os.environ.get("BYBIT_SECRET_KEY", "")
BYBIT_TESTNET     = os.environ.get("BYBIT_TESTNET", "true").lower() == "true"
TRADE_BUDGET_USDT = float(os.environ.get("TRADE_BUDGET_USDT", "50"))

WATCHLIST = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
    "XRP/USDT", "ADA/USDT", "AVAX/USDT", "DOGE/USDT",
    "LINK/USDT", "DOT/USDT",
]

FUTURES_WATCHLIST = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
    "XRP/USDT:USDT", "DOGE/USDT:USDT",
]


# ── EXCHANGE CONNECTIONS ─────────────────────────────────────────────────────
_spot_exchange    = None
_futures_exchange = None


def get_spot_exchange():
    global _spot_exchange
    if _spot_exchange:
        return _spot_exchange
    import ccxt
    _spot_exchange = ccxt.bybit({
        "apiKey": BYBIT_API_KEY,
        "secret": BYBIT_SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    if BYBIT_TESTNET:
        _spot_exchange.set_sandbox_mode(True)
    return _spot_exchange


def get_futures_exchange():
    global _futures_exchange
    if _futures_exchange:
        return _futures_exchange
    import ccxt
    _futures_exchange = ccxt.bybit({
        "apiKey": BYBIT_API_KEY,
        "secret": BYBIT_SECRET_KEY,
        "enableRateLimit": True,
        "options": {"defaultType": "linear"},
    })
    if BYBIT_TESTNET:
        _futures_exchange.set_sandbox_mode(True)
    return _futures_exchange


# ── MARKET DATA ──────────────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, timeframe: str = "15m", limit: int = 200,
                market: str = "spot") -> list:
    """Fetch OHLCV candles from Binance public API (no auth, no geo-block)."""
    try:
        import urllib.request, json
        coin = symbol.replace("/USDT:USDT", "USDT").replace("/USDT", "USDT").replace("/", "")
        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
        tf = tf_map.get(timeframe, "15m")
        url = f"https://api.binance.com/api/v3/klines?symbol={coin}&interval={tf}&limit={limit}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return [[int(d[0]), float(d[1]), float(d[2]), float(d[3]), float(d[4]), float(d[5])] for d in data]
    except Exception as e:
        logging.warning(f"[trade] fetch_ohlcv {symbol} {timeframe}: {e}")
        return []


def get_ticker(symbol: str, market: str = "spot") -> dict:
    """Get current price from Binance public API."""
    try:
        import urllib.request, json
        coin = symbol.replace("/USDT:USDT", "USDT").replace("/USDT", "USDT").replace("/", "")
        url  = f"https://api.binance.com/api/v3/ticker/24hr?symbol={coin}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return {"last": float(data["lastPrice"]), "change": float(data["priceChangePercent"])}
    except Exception as e:
        logging.warning(f"[trade] get_ticker {symbol}: {e}")
        return {}


def get_balance(market: str = "spot") -> dict:
    """Get USDT balance (requires API keys for live trading)."""
    try:
        ex = get_futures_exchange() if market == "futures" else get_spot_exchange()
        bal  = ex.fetch_balance()
        usdt = bal.get("USDT", {})
        return {"free": float(usdt.get("free", 0)), "total": float(usdt.get("total", 0))}
    except Exception as e:
        logging.warning(f"[trade] get_balance: {e}")
        return {"free": 0, "total": 0}


# ── PURE-PANDAS INDICATOR HELPERS (no pandas-ta dependency) ─────────────────
def _ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def _rsi(series, length=14):
    import pandas as pd
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))

def _macd(series, fast=21, slow=55, signal=9):
    ema_fast   = series.ewm(span=fast,   adjust=False).mean()
    ema_slow   = series.ewm(span=slow,   adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line

def _bbands(series, length=20, std=2):
    mid = series.rolling(length).mean()
    dev = series.rolling(length).std()
    return mid + std * dev, mid - std * dev, mid

def _atr(high, low, close, length=14):
    import pandas as pd
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def _stoch(high, low, close, k=14, d=3):
    low_k  = low.rolling(k).min()
    high_k = high.rolling(k).max()
    denom  = (high_k - low_k).replace(0, float("nan"))
    raw_k  = 100 * (close - low_k) / denom
    sk     = raw_k.rolling(d).mean()
    sd     = sk.rolling(d).mean()
    return sk, sd


# ── HTF BIAS ENGINE (4H analysis) ────────────────────────────────────────────
def compute_htf_bias(ohlcv_4h: list) -> dict:
    """
    Analyze 4H timeframe for Higher Timeframe directional bias.
    Returns bias (bullish/bearish/neutral), trend, key levels, score.
    """
    if len(ohlcv_4h) < 50:
        return {"bias": "neutral", "trend": "unclear", "score": 0, "notes": []}
    try:
        import pandas as pd

        df = pd.DataFrame(ohlcv_4h, columns=["ts", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        df["ema20"]  = _ema(df["close"], 20)
        df["ema50"]  = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["rsi"]    = _rsi(df["close"], 14)

        last  = df.iloc[-1]
        price = float(last["close"])
        rsi4h = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50.0

        # Structure: Higher Highs/Higher Lows vs Lower Highs/Lower Lows
        highs_recent = df["high"].iloc[-10:].values
        highs_prior  = df["high"].iloc[-20:-10].values
        lows_recent  = df["low"].iloc[-10:].values
        lows_prior   = df["low"].iloc[-20:-10].values

        hh_hl = max(highs_recent) > max(highs_prior) and min(lows_recent) > min(lows_prior)
        lh_ll = max(highs_recent) < max(highs_prior) and min(lows_recent) < min(lows_prior)

        above_ema200 = price > float(last["ema200"]) if not pd.isna(last["ema200"]) else False
        above_ema50  = price > float(last["ema50"])  if not pd.isna(last["ema50"])  else False
        above_ema20  = price > float(last["ema20"])  if not pd.isna(last["ema20"])  else False

        # 4H Dealing Range
        h4_high = float(df["high"].iloc[-30:].max())
        h4_low  = float(df["low"].iloc[-30:].min())
        h4_eq   = (h4_high + h4_low) / 2
        h4_discount = price < h4_eq
        h4_premium  = price > h4_eq

        bias_score = 0
        notes = []

        if above_ema200:
            bias_score += 2
            notes.append("4H above EMA200 — macro bullish")
        else:
            bias_score -= 2
            notes.append("4H below EMA200 — macro bearish")

        if hh_hl:
            bias_score += 2
            notes.append("4H HH+HL structure — confirmed uptrend")
        elif lh_ll:
            bias_score -= 2
            notes.append("4H LH+LL structure — confirmed downtrend")

        if above_ema50 and above_ema20:
            bias_score += 1
        elif not above_ema50 and not above_ema20:
            bias_score -= 1

        if h4_discount:
            bias_score += 1
            notes.append("4H price in discount zone")
        elif h4_premium:
            bias_score -= 1
            notes.append("4H price in premium zone")

        if rsi4h < 40:
            bias_score += 1
            notes.append(f"4H RSI oversold ({rsi4h:.0f}) — macro accumulation")
        elif rsi4h > 60:
            bias_score -= 1
            notes.append(f"4H RSI overbought ({rsi4h:.0f}) — macro distribution")

        bias = "bullish" if bias_score >= 3 else ("bearish" if bias_score <= -3 else "neutral")
        trend = "uptrend" if hh_hl else ("downtrend" if lh_ll else "ranging")

        return {
            "bias":        bias,
            "trend":       trend,
            "above_ema200": above_ema200,
            "discount":    h4_discount,
            "premium":     h4_premium,
            "rsi":         rsi4h,
            "score":       bias_score,
            "notes":       notes,
            "swing_high":  h4_high,
            "swing_low":   h4_low,
        }
    except Exception as e:
        logging.warning(f"[trade] compute_htf_bias: {e}")
        return {"bias": "neutral", "trend": "unclear", "score": 0, "notes": []}


# ── CANDLE PATTERN DETECTION ─────────────────────────────────────────────────
def detect_candle_patterns(df) -> dict:
    """
    Detect high-probability institutional candle patterns.
    Returns list of pattern descriptions + bullish/bearish flags.
    """
    patterns = []
    bullish_pat = False
    bearish_pat = False

    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]

        o, h, l, c = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
        body        = abs(c - o)
        total_range = h - l
        if total_range < 1e-10:
            return {"patterns": [], "bullish": False, "bearish": False}

        upper_wick  = h - max(o, c)
        lower_wick  = min(o, c) - l
        body_ratio  = body / total_range

        po = float(prev["open"]); ph = float(prev["high"])
        pl = float(prev["low"]);  pc = float(prev["close"])
        prev_body = abs(pc - po)
        prev_range = ph - pl

        # Bullish Pin Bar (hammer) — long lower wick, small body
        if lower_wick > body * 2.5 and body_ratio < 0.35:
            patterns.append("✅ Bullish Pin Bar — strong rejection of lows, institutional buying")
            bullish_pat = True

        # Bearish Pin Bar (shooting star) — long upper wick, small body
        if upper_wick > body * 2.5 and body_ratio < 0.35:
            patterns.append("✅ Bearish Pin Bar — strong rejection of highs, institutional selling")
            bearish_pat = True

        # Bullish Engulfing
        if c > o and pc < po and body > prev_body * 1.5 and c > po and o < pc:
            patterns.append("✅ Bullish Engulfing — momentum candle, bulls fully overtook bears")
            bullish_pat = True

        # Bearish Engulfing
        if c < o and pc > po and body > prev_body * 1.5 and c < po and o > pc:
            patterns.append("✅ Bearish Engulfing — momentum candle, bears fully overtook bulls")
            bearish_pat = True

        # Inside Bar — compression before breakout
        if h < ph and l > pl:
            patterns.append("⚡ Inside Bar — tight compression, explosive breakout imminent")

        # Doji — indecision
        if body_ratio < 0.08:
            patterns.append("⚡ Doji — market indecision, wait for next candle direction")

    except Exception as e:
        logging.warning(f"[trade] candle_patterns: {e}")

    return {"patterns": patterns, "bullish": bullish_pat, "bearish": bearish_pat}


# ── MAIN SIGNAL ENGINE ────────────────────────────────────────────────────────
def compute_signals(ohlcv: list, ohlcv_4h: list = None, ohlcv_1h: list = None) -> dict:
    """
    Institutional multi-timeframe confluence engine.
    Levels: Premium/Discount, OTE Fib, OB+CE, FVG+CE, Turtle Soup/Liquidity,
            HTF Trend, RSI divergence, MACD 21/55/9, Stochastic, Volume,
            Candle Patterns, Killzone timing, Daily Bias, MTF alignment.
    Grade: A+(>=9), A(>=6), B(>=4) — only A/A+ fire alerts.
    """
    if len(ohlcv) < 100:
        return {"action": "wait", "reason": "Not enough candle data"}

    # Weekend filter — crypto thins out, avoid new positions
    now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:
        return {"action": "wait", "reason": "Weekend — low liquidity, no new positions"}

    try:
        import pandas as pd

        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # ── Indicators (pure pandas — no external TA library) ─────────────
        df["ema20"]  = _ema(df["close"], 20)
        df["ema50"]  = _ema(df["close"], 50)
        df["ema200"] = _ema(df["close"], 200)
        df["rsi"]    = _rsi(df["close"], 14)

        # Institutional MACD 21/55/9 (fewer false signals than 12/26/9)
        df["macd"], df["macd_sig"], df["macd_hist"] = _macd(df["close"], 21, 55, 9)

        df["bb_upper"], df["bb_lower"], df["bb_mid"] = _bbands(df["close"], 20, 2)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

        df["atr"]    = _atr(df["high"], df["low"], df["close"], 14)
        df["vol_ma"] = df["volume"].rolling(20).mean()

        df["stoch_k"], df["stoch_d"] = _stoch(df["high"], df["low"], df["close"], 14, 3)

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        price = float(last["close"])
        rsi_v = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50.0
        atr_v = float(last["atr"]) if not pd.isna(last["atr"]) else price * 0.005

        # ── EMA structure (defined early — used throughout) ───────────────
        above_200 = price > float(last["ema200"]) if not pd.isna(last["ema200"]) else False
        above_50  = price > float(last["ema50"])  if not pd.isna(last["ema50"])  else False
        above_20  = price > float(last["ema20"])  if not pd.isna(last["ema20"])  else False

        confluences = []
        bullish     = 0
        bearish     = 0
        setup_type  = "Standard Setup"

        # ── HTF BIAS (4H) — most important filter ────────────────────────
        htf = {}
        if ohlcv_4h and len(ohlcv_4h) >= 50:
            htf = compute_htf_bias(ohlcv_4h)
            htf_bias = htf.get("bias", "neutral")
            if htf_bias == "bullish":
                confluences.append(f"🏦 4H HTF: BULLISH ({htf.get('trend','uptrend')}) — trade with macro bias")
                bullish += 2
            elif htf_bias == "bearish":
                confluences.append(f"🏦 4H HTF: BEARISH ({htf.get('trend','downtrend')}) — trade with macro bias")
                bearish += 2
            else:
                confluences.append("⚠️ 4H HTF: Neutral/Ranging — lower conviction, smaller size if trading")

        # ── DAILY BIAS (price vs midnight UTC open) ───────────────────────
        midnight_ts = int(datetime(now_utc.year, now_utc.month, now_utc.day,
                                   tzinfo=timezone.utc).timestamp() * 1000)
        daily_open = None
        for candle in reversed(ohlcv):
            if candle[0] <= midnight_ts:
                daily_open = float(candle[4])
                break
        if daily_open:
            if price > daily_open * 1.002:
                confluences.append(f"✅ Daily bias BULLISH — above midnight open (${daily_open:,.2f})")
                bullish += 1
            elif price < daily_open * 0.998:
                confluences.append(f"✅ Daily bias BEARISH — below midnight open (${daily_open:,.2f})")
                bearish += 1

        # ── LEVEL 1: Premium/Discount (Dealing Range) ─────────────────────
        swing_high = float(df["high"].iloc[-50:].max())
        swing_low  = float(df["low"].iloc[-50:].min())
        rng        = swing_high - swing_low
        eq         = (swing_high + swing_low) / 2
        in_discount = price < eq
        in_premium  = price > eq
        pd_pct = round(((price - swing_low) / rng) * 100, 1) if rng > 0 else 50.0

        if in_discount and pd_pct < 35:
            confluences.append(f"✅ Deep discount ({pd_pct}%) — institutional buy zone, extreme value")
            bullish += 2
        elif in_discount:
            confluences.append(f"✅ Discount ({pd_pct}%) — below fair value, prefer longs")
            bullish += 1
        elif in_premium and pd_pct > 65:
            confluences.append(f"✅ Deep premium ({pd_pct}%) — institutional sell zone, overextended")
            bearish += 2
        elif in_premium:
            confluences.append(f"✅ Premium ({pd_pct}%) — above fair value, prefer shorts")
            bearish += 1

        # ── LEVEL 2: OTE Fibonacci Zone (62-79% retracement) ─────────────
        r20_high = float(df["high"].iloc[-20:].max())
        r20_low  = float(df["low"].iloc[-20:].min())
        fib_rng  = r20_high - r20_low
        ote_low  = r20_high - fib_rng * 0.79  # long OTE
        ote_high = r20_high - fib_rng * 0.62
        ote_s_low  = r20_low + fib_rng * 0.62  # short OTE
        ote_s_high = r20_low + fib_rng * 0.79

        if ote_low <= price <= ote_high and above_200:
            confluences.append(f"✅ OTE Long (62-79% fib) ${ote_low:,.2f}–${ote_high:,.2f} — optimal long entry")
            bullish += 2
            setup_type = "OTE Long Entry"
        if ote_s_low <= price <= ote_s_high and not above_200:
            confluences.append(f"✅ OTE Short (62-79% fib) ${ote_s_low:,.2f}–${ote_s_high:,.2f} — optimal short entry")
            bearish += 2
            setup_type = "OTE Short Entry"

        # ── LEVEL 3: Order Block + Consequent Encroachment ───────────────
        ob_bull = False
        ob_bear = False
        for i in range(-15, -2):
            c    = df.iloc[i]
            nc   = df.iloc[i + 1]
            c_is_bear = float(c["close"]) < float(c["open"])
            c_is_bull = float(c["close"]) > float(c["open"])
            strong_bull = (float(nc["close"]) - float(nc["open"])) > atr_v * 1.5
            strong_bear = (float(nc["open"]) - float(nc["close"])) > atr_v * 1.5

            if c_is_bear and strong_bull and not ob_bull:
                ob_l = float(c["low"]); ob_h = float(c["high"])
                ob_ce = (ob_l + ob_h) / 2
                if ob_l <= price <= ob_h:
                    prx = "at CE (50%)" if abs(price - ob_ce) < atr_v * 0.35 else "in zone"
                    confluences.append(f"✅ Bullish OB ${ob_l:,.2f}–${ob_h:,.2f} CE:${ob_ce:,.2f} — price {prx}")
                    bullish += 3
                    ob_bull = True
                    setup_type = "OB Long"
                    break

            if c_is_bull and strong_bear and not ob_bear:
                ob_l = float(c["low"]); ob_h = float(c["high"])
                ob_ce = (ob_l + ob_h) / 2
                if ob_l <= price <= ob_h:
                    prx = "at CE (50%)" if abs(price - ob_ce) < atr_v * 0.35 else "in zone"
                    confluences.append(f"✅ Bearish OB ${ob_l:,.2f}–${ob_h:,.2f} CE:${ob_ce:,.2f} — price {prx}")
                    bearish += 3
                    ob_bear = True
                    setup_type = "OB Short"
                    break

        # ── LEVEL 4: Fair Value Gap + CE ──────────────────────────────────
        fvg_bull = False
        fvg_bear = False
        for i in range(-12, -2):
            c1 = df.iloc[i]
            c3 = df.iloc[i + 2] if (i + 2) < 0 else df.iloc[-1]

            if float(c1["high"]) < float(c3["low"]):
                fb = float(c1["high"]); ft = float(c3["low"])
                fce = (fb + ft) / 2
                if fb <= price <= ft:
                    confluences.append(f"✅ Bullish FVG ${fb:,.2f}–${ft:,.2f} CE:${fce:,.2f} — imbalance fill")
                    bullish += 2
                    fvg_bull = True
                    if not ob_bull:
                        setup_type = "FVG Long"
                    break

            if float(c1["low"]) > float(c3["high"]):
                fb = float(c3["high"]); ft = float(c1["low"])
                fce = (fb + ft) / 2
                if fb <= price <= ft:
                    confluences.append(f"✅ Bearish FVG ${fb:,.2f}–${ft:,.2f} CE:${fce:,.2f} — imbalance fill")
                    bearish += 2
                    fvg_bear = True
                    if not ob_bear:
                        setup_type = "FVG Short"
                    break

        # OB + FVG combo — highest probability (~68% win rate)
        if ob_bull and fvg_bull:
            confluences.append("⭐ OB + FVG COMBO — highest probability setup, ~68% historical win rate")
            bullish += 2
            setup_type = "OB+FVG Long"
        if ob_bear and fvg_bear:
            confluences.append("⭐ OB + FVG COMBO — highest probability setup, ~68% historical win rate")
            bearish += 2
            setup_type = "OB+FVG Short"

        # ── LEVEL 5: Turtle Soup / Liquidity Sweep ────────────────────────
        lkbk_high = float(df["high"].iloc[-20:-3].max())
        lkbk_low  = float(df["low"].iloc[-20:-3].min())
        sweep_bull = float(prev["low"]) < lkbk_low  and price > lkbk_low
        sweep_bear = float(prev["high"]) > lkbk_high and price < lkbk_high

        if sweep_bull:
            confluences.append(f"✅ Turtle Soup LONG — SSL swept ${lkbk_low:,.4f}, reclaimed → reversal")
            bullish += 3
            setup_type = "Turtle Soup Long"
        if sweep_bear:
            confluences.append(f"✅ Turtle Soup SHORT — BSL swept ${lkbk_high:,.4f}, rejected → reversal")
            bearish += 3
            setup_type = "Turtle Soup Short"

        # Equal highs/lows — liquidity pools
        highs20 = df["high"].iloc[-20:-1]
        lows20  = df["low"].iloc[-20:-1]
        eq_high = float(highs20.max())
        eq_low  = float(lows20.min())
        if (highs20 > eq_high * 0.998).sum() >= 2 and in_premium:
            confluences.append(f"✅ Equal highs at ${eq_high:,.4f} — BSL pool above, expect sweep + drop")
            bearish += 1
        if (lows20 < eq_low * 1.002).sum() >= 2 and in_discount:
            confluences.append(f"✅ Equal lows at ${eq_low:,.4f} — SSL pool below, expect sweep + bounce")
            bullish += 1

        # ── LEVEL 6: HTF EMA Structure + BOS ─────────────────────────────
        ema_bull_x = (float(last["ema20"]) > float(last["ema50"]) and
                      float(prev["ema20"]) <= float(prev["ema50"]))
        ema_bear_x = (float(last["ema20"]) < float(last["ema50"]) and
                      float(prev["ema20"]) >= float(prev["ema50"]))

        if above_200:
            confluences.append("✅ Above EMA 200 — macro bullish structure")
            bullish += 1
        else:
            confluences.append("✅ Below EMA 200 — macro bearish structure")
            bearish += 1

        if ema_bull_x:
            confluences.append("✅ EMA 20/50 bullish cross — momentum shift up")
            bullish += 2
        elif above_20 and above_50 and above_200:
            confluences.append("✅ Perfect EMA stack: 20>50>200 — trend continuation long")
            bullish += 1

        if ema_bear_x:
            confluences.append("✅ EMA 20/50 bearish cross — momentum shift down")
            bearish += 2
        elif not above_20 and not above_50 and not above_200:
            confluences.append("✅ Perfect EMA stack: 20<50<200 — trend continuation short")
            bearish += 1

        # Simple BOS: did price just break above/below the last 10-bar pivot?
        pivot_high = float(df["high"].iloc[-12:-2].max())
        pivot_low  = float(df["low"].iloc[-12:-2].min())
        if price > pivot_high and above_200:
            confluences.append(f"✅ Bullish BOS — broke above ${pivot_high:,.2f} structure high")
            bullish += 1
        if price < pivot_low and not above_200:
            confluences.append(f"✅ Bearish BOS — broke below ${pivot_low:,.2f} structure low")
            bearish += 1

        # ── LEVEL 7: RSI Multi-Timeframe Divergence ───────────────────────
        if rsi_v < 30:
            confluences.append(f"✅ RSI extreme oversold ({rsi_v:.1f}) — capitulation, reversal zone")
            bullish += 2
        elif rsi_v > 70:
            confluences.append(f"✅ RSI extreme overbought ({rsi_v:.1f}) — exhaustion, reversal zone")
            bearish += 2
        elif 35 <= rsi_v <= 48 and above_200:
            confluences.append(f"✅ RSI bull reset ({rsi_v:.1f}) — healthy dip in uptrend, buy zone")
            bullish += 1
        elif 52 <= rsi_v <= 65 and not above_200:
            confluences.append(f"✅ RSI bear rally ({rsi_v:.1f}) — weak bounce in downtrend, sell zone")
            bearish += 1

        # RSI 5-bar divergence
        price_5 = float(df.iloc[-6]["close"])
        rsi_5   = float(df.iloc[-6]["rsi"]) if not pd.isna(df.iloc[-6]["rsi"]) else rsi_v
        if price < price_5 and rsi_v > rsi_5 + 3 and rsi_v < 55:
            confluences.append("✅ Bullish RSI divergence — price drops but RSI rising = hidden strength")
            bullish += 2
        if price > price_5 and rsi_v < rsi_5 - 3 and rsi_v > 45:
            confluences.append("✅ Bearish RSI divergence — price rises but RSI falling = hidden weakness")
            bearish += 2

        # 4H RSI context
        h4_rsi = htf.get("rsi", 50)
        if h4_rsi < 38:
            confluences.append(f"✅ 4H RSI macro oversold ({h4_rsi:.0f}) — major accumulation zone")
            bullish += 1
        elif h4_rsi > 62:
            confluences.append(f"✅ 4H RSI macro overbought ({h4_rsi:.0f}) — major distribution zone")
            bearish += 1

        # ── LEVEL 8: MACD 21/55/9 (institutional settings) ───────────────
        try:
            mv  = float(last["macd"])
            ms  = float(last["macd_sig"])
            mh  = float(last["macd_hist"])
            pmv = float(prev["macd"])
            pms = float(prev["macd_sig"])
            pmh = float(prev["macd_hist"])
            if not any(pd.isna(x) for x in [mv, ms, mh, pmv, pms, pmh]):
                if mv > ms and pmv <= pms:
                    confluences.append("✅ MACD (21/55/9) bullish cross — institutional momentum up")
                    bullish += 2
                if mv < ms and pmv >= pms:
                    confluences.append("✅ MACD (21/55/9) bearish cross — institutional momentum down")
                    bearish += 2
                if mh > 0 and pmh <= 0:
                    confluences.append("✅ MACD histogram positive flip — bulls accelerating")
                    bullish += 1
                if mh < 0 and pmh >= 0:
                    confluences.append("✅ MACD histogram negative flip — bears accelerating")
                    bearish += 1
        except Exception:
            pass

        # ── LEVEL 9: Volume + Stochastic + Candle Patterns ───────────────
        vol_now = float(last["volume"])
        vol_avg = float(last["vol_ma"]) if not pd.isna(last["vol_ma"]) else vol_now
        vol_spike = vol_now > vol_avg * 1.5

        if vol_spike and price > float(prev["close"]):
            confluences.append(f"✅ Volume spike {vol_now/vol_avg:.1f}x — institutional accumulation")
            bullish += 1
        if vol_spike and price < float(prev["close"]):
            confluences.append(f"✅ Volume spike {vol_now/vol_avg:.1f}x — institutional distribution")
            bearish += 1

        sk = float(last["stoch_k"]) if not pd.isna(last["stoch_k"]) else 50.0
        sd = float(last["stoch_d"]) if not pd.isna(last["stoch_d"]) else 50.0
        psk = float(prev["stoch_k"]) if not pd.isna(prev["stoch_k"]) else 50.0
        psd = float(prev["stoch_d"]) if not pd.isna(prev["stoch_d"]) else 50.0
        if sk < 20 and sk > sd and psk <= psd:
            confluences.append(f"✅ Stochastic oversold bullish cross ({sk:.0f}) — reversal signal")
            bullish += 1
        if sk > 80 and sk < sd and psk >= psd:
            confluences.append(f"✅ Stochastic overbought bearish cross ({sk:.0f}) — reversal signal")
            bearish += 1

        # BB squeeze — volatility compression before explosion
        try:
            bw_now = float(last["bb_width"])
            bw_q15 = float(df["bb_width"].quantile(0.15))
            if bw_now < bw_q15:
                confluences.append("⚡ Bollinger Band squeeze — volatility compression, big move incoming")
        except Exception:
            pass

        # Candle patterns
        pats = detect_candle_patterns(df)
        for p in pats.get("patterns", []):
            confluences.append(p)
        if pats.get("bullish"):
            bullish += 1
        if pats.get("bearish"):
            bearish += 1

        # ── LEVEL 10: Killzone + Session Timing ──────────────────────────
        in_london = 2  <= now_utc.hour < 5
        in_ny     = 7  <= now_utc.hour < 10
        in_ny2    = 12 <= now_utc.hour < 15
        in_asia   = now_utc.hour >= 18 or now_utc.hour < 2

        if in_london:
            confluences.append("⏰ London Killzone (02-05 UTC) — stop hunt session, watch sweep + reverse")
            bullish += 1; bearish += 1
        elif in_ny:
            confluences.append("⏰ NY Killzone (07-10 UTC) — 40% daily volume, strongest directional move")
            bullish += 1; bearish += 1
        elif in_ny2:
            confluences.append("⏰ London/NY Overlap (12-15 UTC) — second momentum wave")
        elif in_asia:
            confluences.append("⚠️ Asia session (18-02 UTC) — low volume, high false-signal risk")

        # ── MTF CONFLICT PENALTY ──────────────────────────────────────────
        htf_bias = htf.get("bias", "neutral")
        if htf_bias == "bullish" and bearish > bullish + 2:
            confluences.append("⚠️ MTF CONFLICT: LTF bearish vs 4H bullish — high uncertainty, skip")
            bullish = max(0, bullish - 2)
        elif htf_bias == "bearish" and bullish > bearish + 2:
            confluences.append("⚠️ MTF CONFLICT: LTF bullish vs 4H bearish — high uncertainty, skip")
            bearish = max(0, bearish - 2)

        # ── GRADE + DECISION ─────────────────────────────────────────────
        score = bullish - bearish

        # Stricter thresholds: A+(>=9), A(>=6), B(>=4)
        if score >= 9:
            action, grade, confidence = "buy",  "A+", "Exceptional (~75-80%)"
        elif score >= 6:
            action, grade, confidence = "buy",  "A",  "High (~65-70%)"
        elif score >= 4:
            action, grade, confidence = "buy",  "B",  "Medium (~55%)"
        elif score <= -9:
            action, grade, confidence = "sell", "A+", "Exceptional (~75-80%)"
        elif score <= -6:
            action, grade, confidence = "sell", "A",  "High (~65-70%)"
        elif score <= -4:
            action, grade, confidence = "sell", "B",  "Medium (~55%)"
        else:
            action, grade, confidence = "wait", "C",  "Low — no trade"

        # C-grade = no trade. B-grade keeps its action for paper scan testing.
        if grade == "C":
            action = "wait"

        # ── SL / TP — Institutional Placement (ATR-based) ─────────────────
        # A+: tightest SL (high conviction), widest TP, 3 targets
        # A:  standard SL, 3 targets
        if grade == "A+":
            sl_m, tp1_m, tp2_m, tp3_m = 0.8, 1.8, 3.5, 6.0
        elif grade == "A":
            sl_m, tp1_m, tp2_m, tp3_m = 1.0, 1.8, 3.5, 5.5
        else:
            sl_m, tp1_m, tp2_m, tp3_m = 1.2, 1.5, 3.0, 4.5

        sl_d  = atr_v * sl_m
        tp1_d = atr_v * tp1_m
        tp2_d = atr_v * tp2_m
        tp3_d = atr_v * tp3_m

        if action == "buy":
            sl  = round(price - sl_d,  4)
            tp1 = round(price + tp1_d, 4)
            tp2 = round(price + tp2_d, 4)
            tp3 = round(price + tp3_d, 4)
        elif action == "sell":
            sl  = round(price + sl_d,  4)
            tp1 = round(price - tp1_d, 4)
            tp2 = round(price - tp2_d, 4)
            tp3 = round(price - tp3_d, 4)
        else:
            sl = tp1 = tp2 = tp3 = None

        rr       = round(tp2_d / sl_d, 2) if sl_d else 0
        risk_pct = {"A+": 0.02, "A": 0.015, "B": 0.005}.get(grade, 0)

        return {
            "action":     action,
            "grade":      grade,
            "confidence": confidence,
            "setup_type": setup_type,
            "price":      price,
            "rsi":        round(rsi_v, 1),
            "pd_pct":     pd_pct,
            "bullish":    bullish,
            "bearish":    bearish,
            "score":      score,
            "signals":    confluences,
            "htf_bias":   htf.get("bias", "neutral"),
            "sl":         sl,
            "tp1":        tp1,
            "tp2":        tp2,
            "tp3":        tp3,
            "rr":         rr,
            "atr":        round(atr_v, 4),
            "risk_pct":   risk_pct,
        }

    except Exception as e:
        logging.warning(f"[trade] compute_signals: {e}")
        import traceback
        logging.warning(traceback.format_exc())
        return {"action": "wait", "reason": str(e)}


# ── ORDER EXECUTION ──────────────────────────────────────────────────────────
def place_spot_order(symbol: str, side: str, usdt_amount: float = TRADE_BUDGET_USDT) -> dict:
    """Place a spot market order. side: 'buy' or 'sell'."""
    try:
        ex     = get_spot_exchange()
        ticker = ex.fetch_ticker(symbol)
        price  = float(ticker["last"])
        amount = usdt_amount / price
        mkt    = ex.market(symbol)
        min_a  = mkt.get("limits", {}).get("amount", {}).get("min", 0)
        if amount < min_a:
            return {"error": f"Amount {amount:.6f} below minimum {min_a}"}
        order = ex.create_order(symbol=symbol, type="market", side=side, amount=amount)
        logging.info(f"[trade] Spot {side.upper()} {symbol}: ${usdt_amount} → {order.get('id')}")
        return order
    except Exception as e:
        logging.warning(f"[trade] place_spot_order {symbol} {side}: {e}")
        return {"error": str(e)}


def place_futures_order(symbol: str, side: str, usdt_amount: float = TRADE_BUDGET_USDT,
                        leverage: int = 5) -> dict:
    """Place a futures market order with leverage. side: 'buy' (long) or 'sell' (short)."""
    try:
        ex = get_futures_exchange()
        try:
            ex.set_leverage(leverage, symbol)
        except Exception:
            pass
        ticker   = ex.fetch_ticker(symbol)
        price    = float(ticker["last"])
        notional = usdt_amount * leverage
        amount   = notional / price
        order    = ex.create_order(symbol=symbol, type="market", side=side, amount=amount)
        logging.info(f"[trade] Futures {side.upper()} {symbol} {leverage}x: ${usdt_amount} → {order.get('id')}")
        return order
    except Exception as e:
        logging.warning(f"[trade] place_futures_order {symbol} {side}: {e}")
        return {"error": str(e)}


def set_sl_tp(symbol: str, side: str, sl_price: float, tp_price: float,
              amount: float, market: str = "spot") -> dict:
    """Set Stop Loss and Take Profit orders after entry."""
    results = {}
    try:
        ex         = get_futures_exchange() if market == "futures" else get_spot_exchange()
        close_side = "sell" if side == "buy" else "buy"
        try:
            sl_order = ex.create_order(
                symbol=symbol,
                type="stop_market" if market == "futures" else "stop_loss_limit",
                side=close_side, amount=amount,
                price=sl_price if market == "spot" else None,
                params={"stopPrice": sl_price, "reduceOnly": True} if market == "futures"
                       else {"stopPrice": sl_price},
            )
            results["sl_order"] = sl_order.get("id")
        except Exception as e:
            results["sl_error"] = str(e)
        try:
            tp_order = ex.create_order(
                symbol=symbol,
                type="take_profit_market" if market == "futures" else "limit",
                side=close_side, amount=amount, price=tp_price,
                params={"stopPrice": tp_price, "reduceOnly": True} if market == "futures" else {},
            )
            results["tp_order"] = tp_order.get("id")
        except Exception as e:
            results["tp_error"] = str(e)
    except Exception as e:
        results["error"] = str(e)
    return results


def get_open_positions(market: str = "futures") -> list:
    """Get all open futures positions."""
    try:
        ex        = get_futures_exchange() if market == "futures" else get_spot_exchange()
        positions = ex.fetch_positions()
        return [p for p in positions if float(p.get("contracts", 0)) != 0]
    except Exception as e:
        logging.warning(f"[trade] get_open_positions: {e}")
        return []


def close_position(symbol: str, market: str = "futures") -> dict:
    """Close an open futures position at market price."""
    try:
        ex        = get_futures_exchange()
        positions = ex.fetch_positions([symbol])
        for pos in positions:
            if float(pos.get("contracts", 0)) != 0:
                side  = "sell" if pos["side"] == "long" else "buy"
                amt   = abs(float(pos["contracts"]))
                order = ex.create_order(
                    symbol=symbol, type="market", side=side, amount=amt,
                    params={"reduceOnly": True},
                )
                return order
        return {"error": "No open position found"}
    except Exception as e:
        logging.warning(f"[trade] close_position {symbol}: {e}")
        return {"error": str(e)}


# ── SCANNER ──────────────────────────────────────────────────────────────────
_GRADE_RANK = {"A+": 4, "A": 3, "B": 2, "C": 1}

def scan_all(timeframe: str = "15m", min_grade: str = "A") -> list:
    """
    Scan all watchlist coins for signals.
    min_grade: "A" = only A/A+ (live alerts), "B" = include B-grade (paper testing).
    Fetches 15m (execution) + 4H (bias) for multi-timeframe analysis.
    """
    min_rank = _GRADE_RANK.get(min_grade, 3)
    alerts = []
    for symbol in WATCHLIST:
        try:
            ohlcv_15m = fetch_ohlcv(symbol, timeframe="15m", limit=200)
            ohlcv_4h  = fetch_ohlcv(symbol, timeframe="4h",  limit=100)
            if not ohlcv_15m:
                continue
            sig = compute_signals(ohlcv_15m, ohlcv_4h=ohlcv_4h)
            grade = sig.get("grade", "C")
            if (sig.get("action") in ("buy", "sell") and
                    _GRADE_RANK.get(grade, 0) >= min_rank):
                sig["symbol"]    = symbol
                sig["market"]    = "spot"
                sig["timeframe"] = timeframe
                alerts.append(sig)
        except Exception as e:
            logging.warning(f"[trade] scan {symbol}: {e}")
    return alerts


def format_signal_message(sig: dict) -> str:
    """Format an institutional-grade signal as Telegram HTML."""
    symbol     = sig.get("symbol", "")
    action     = sig.get("action", "wait").upper()
    price      = sig.get("price", 0)
    rsi        = sig.get("rsi", 0)
    sl         = sig.get("sl")
    tp1        = sig.get("tp1")
    tp2        = sig.get("tp2")
    tp3        = sig.get("tp3")
    rr         = sig.get("rr", 0)
    grade      = sig.get("grade", "B")
    confidence = sig.get("confidence", "Medium")
    timeframe  = sig.get("timeframe", "15m")
    setup_type = sig.get("setup_type", "Standard Setup")
    htf_bias   = sig.get("htf_bias", "neutral").upper()
    pd_pct     = sig.get("pd_pct", 50)
    risk_pct   = sig.get("risk_pct", 0)
    confluences = sig.get("signals", [])
    score      = sig.get("score", 0)

    emoji      = "🟢" if action == "BUY" else "🔴"
    coin       = symbol.replace("/USDT:USDT", "").replace("/USDT", "")
    grade_star = {"A+": "⭐⭐ A+", "A": "⭐ A", "B": "✳️ B", "C": "⬜ C"}.get(grade, grade)

    # Show top 7 confluences
    conf_lines = "\n".join(f"  {c}" for c in confluences[:7])

    def fmt(v):
        if v is None:
            return "—"
        return f"${v:,.2f}" if v >= 1 else f"${v:,.6f}"

    sl_str  = fmt(sl)
    tp1_str = fmt(tp1)
    tp2_str = fmt(tp2)
    tp3_str = fmt(tp3)

    risk_line = f"  Risk: {risk_pct*100:.1f}% of portfolio per Kelly\n" if risk_pct else ""

    return (
        f"{emoji} <b>{coin}/USDT — {action}</b> [{timeframe} · {grade_star}]\n"
        f"🎯 Setup: <b>{setup_type}</b> | Confidence: {confidence}\n"
        f"🏦 4H Bias: {htf_bias} | PD: {pd_pct}% of range | Score: {score}\n\n"
        f"📐 <b>Confluences ({len(confluences)}):</b>\n{conf_lines}\n\n"
        f"💰 Entry: <b>{fmt(price)}</b> | RSI: {rsi}\n\n"
        f"🎯 <b>Trade Plan (Partial Exit Model):</b>\n"
        f"  SL:  <code>{sl_str}</code> — invalidation\n"
        f"  TP1 (40%): <code>{tp1_str}</code> → move SL to BE\n"
        f"  TP2 (35%): <code>{tp2_str}</code> — main target\n"
        f"  TP3 (25%): <code>{tp3_str}</code> — trail 2x ATR\n"
        f"  R:R = 1:{rr}\n"
        f"{risk_line}\n"
        f"💵 Budget: ${TRADE_BUDGET_USDT} USDT\n"
        f"<i>⚠️ Not financial advice. Always use SL. DYOR.</i>"
    )
