# -*- coding: utf-8 -*-
"""
Eva Paper Trading Engine
Uses real live prices from public Binance API (no auth needed).
Simulates trades with full PnL tracking, SL/TP auto-close, portfolio stats.
No testnet, no KYC, no geo-restrictions — 100% simulated with real prices.
"""

import os, json, logging, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

PHT               = timezone(timedelta(hours=8))
PAPER_FILE        = Path(__file__).parent / "paper_trades.json"
STARTING_BALANCE  = float(os.environ.get("PAPER_BALANCE", "1000"))   # fake USDT
TRADE_BUDGET_USDT = float(os.environ.get("TRADE_BUDGET_USDT", "50"))


# ── PERSISTENCE ──────────────────────────────────────────────────────────────
def _load() -> dict:
    if PAPER_FILE.exists():
        try:
            return json.loads(PAPER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "balance":       STARTING_BALANCE,
        "starting":      STARTING_BALANCE,
        "positions":     {},   # symbol → position dict
        "closed_trades": [],   # list of completed trades
        "total_trades":  0,
        "wins":          0,
        "losses":        0,
    }


def _save(data: dict):
    try:
        PAPER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logging.warning(f"[paper] save: {e}")


# ── LIVE PRICE ────────────────────────────────────────────────────────────────
def get_live_price(symbol: str) -> float:
    """Fetch real-time price from Binance public API (no auth needed)."""
    try:
        coin = symbol.replace("/USDT", "").replace(":USDT", "").upper() + "USDT"
        url  = f"https://api.binance.com/api/v3/ticker/price?symbol={coin}"
        resp = requests.get(url, timeout=5)
        return float(resp.json()["price"])
    except Exception as e:
        logging.warning(f"[paper] get_live_price {symbol}: {e}")
        return 0.0


def get_live_prices(symbols: list) -> dict:
    """Batch fetch prices for multiple symbols."""
    try:
        url  = "https://api.binance.com/api/v3/ticker/price"
        resp = requests.get(url, timeout=8)
        all_prices = {item["symbol"]: float(item["price"]) for item in resp.json()}
        result = {}
        for sym in symbols:
            coin = sym.replace("/USDT", "").replace(":USDT", "").upper() + "USDT"
            if coin in all_prices:
                result[sym] = all_prices[coin]
        return result
    except Exception as e:
        logging.warning(f"[paper] get_live_prices batch: {e}")
        return {}


# ── TRADE EXECUTION ───────────────────────────────────────────────────────────
def open_position(symbol: str, side: str, usdt_amount: float = TRADE_BUDGET_USDT,
                  sl: float = None, tp1: float = None, tp2: float = None) -> dict:
    """
    Open a paper trade position.
    side: 'buy' (long) or 'sell' (short)
    Returns result dict.
    """
    data  = _load()
    price = get_live_price(symbol)
    if not price:
        return {"error": f"Could not fetch price for {symbol}"}

    if usdt_amount > data["balance"]:
        return {"error": f"Insufficient balance. Available: ${data['balance']:.2f} USDT"}

    if symbol in data["positions"]:
        return {"error": f"Already have an open position in {symbol}. Close it first."}

    quantity = usdt_amount / price
    now      = datetime.now(PHT).isoformat()

    position = {
        "symbol":      symbol,
        "side":        side,
        "entry_price": price,
        "quantity":    quantity,
        "usdt_amount": usdt_amount,
        "sl":          sl,
        "tp1":         tp1,
        "tp1_hit":     False,
        "tp2":         tp2,
        "opened_at":   now,
        "pnl":         0.0,
    }

    data["balance"]              -= usdt_amount
    data["positions"][symbol]     = position
    data["total_trades"]         += 1
    _save(data)

    coin = symbol.replace("/USDT", "")
    return {
        "ok":          True,
        "symbol":      symbol,
        "side":        side,
        "entry_price": price,
        "quantity":    round(quantity, 6),
        "usdt_amount": usdt_amount,
        "sl":          sl,
        "tp1":         tp1,
        "tp2":         tp2,
        "balance_left": round(data["balance"], 2),
    }


def close_position(symbol: str, reason: str = "manual") -> dict:
    """Close an open paper position at current market price."""
    data = _load()
    if symbol not in data["positions"]:
        return {"error": f"No open position for {symbol}"}

    pos   = data["positions"][symbol]
    price = get_live_price(symbol)
    if not price:
        return {"error": f"Could not fetch exit price for {symbol}"}

    entry = pos["entry_price"]
    qty   = pos["quantity"]
    side  = pos["side"]

    if side == "buy":
        pnl = (price - entry) * qty
    else:
        pnl = (entry - price) * qty

    pnl_pct   = (pnl / pos["usdt_amount"]) * 100
    returned  = pos["usdt_amount"] + pnl
    data["balance"] += returned

    if pnl >= 0:
        data["wins"] += 1
    else:
        data["losses"] += 1

    closed = {
        **pos,
        "exit_price": price,
        "pnl":        round(pnl, 4),
        "pnl_pct":    round(pnl_pct, 2),
        "closed_at":  datetime.now(PHT).isoformat(),
        "reason":     reason,
    }
    data["closed_trades"].append(closed)
    del data["positions"][symbol]
    _save(data)

    return {
        "ok":        True,
        "symbol":    symbol,
        "side":      side,
        "entry":     entry,
        "exit":      price,
        "pnl":       round(pnl, 4),
        "pnl_pct":   round(pnl_pct, 2),
        "reason":    reason,
        "balance":   round(data["balance"], 2),
    }


def check_sl_tp() -> list:
    """
    Check all open positions against current prices.
    Auto-close if SL or TP hit. Returns list of closed position results.
    """
    data    = _load()
    if not data["positions"]:
        return []

    symbols = list(data["positions"].keys())
    prices  = get_live_prices(symbols)
    closed  = []

    for symbol, pos in list(data["positions"].items()):
        price = prices.get(symbol)
        if not price:
            continue

        side  = pos["side"]
        entry = pos["entry_price"]
        sl    = pos.get("sl")
        tp1   = pos.get("tp1")
        tp2   = pos.get("tp2")

        # Check Stop Loss
        if sl:
            if (side == "buy" and price <= sl) or (side == "sell" and price >= sl):
                result = close_position(symbol, reason="stop_loss")
                result["trigger"] = "SL"
                closed.append(result)
                continue

        # Check TP2 (full close)
        if tp2:
            if (side == "buy" and price >= tp2) or (side == "sell" and price <= tp2):
                result = close_position(symbol, reason="take_profit_2")
                result["trigger"] = "TP2"
                closed.append(result)
                continue

        # Check TP1 (partial — just notify, don't close yet)
        if tp1 and not pos.get("tp1_hit"):
            if (side == "buy" and price >= tp1) or (side == "sell" and price <= tp1):
                data["positions"][symbol]["tp1_hit"] = True
                _save(data)
                closed.append({
                    "symbol":  symbol,
                    "trigger": "TP1",
                    "price":   price,
                    "pnl":     round((price - entry) * pos["quantity"] if side == "buy"
                                     else (entry - price) * pos["quantity"], 4),
                    "partial": True,
                })

    return closed


# ── PORTFOLIO ─────────────────────────────────────────────────────────────────
def get_portfolio() -> dict:
    """Get full portfolio state with live PnL for open positions."""
    data   = _load()
    prices = get_live_prices(list(data["positions"].keys())) if data["positions"] else {}

    open_pos = []
    total_unrealized = 0.0
    for symbol, pos in data["positions"].items():
        price = prices.get(symbol, pos["entry_price"])
        entry = pos["entry_price"]
        qty   = pos["quantity"]
        side  = pos["side"]
        pnl   = (price - entry) * qty if side == "buy" else (entry - price) * qty
        pnl_pct = (pnl / pos["usdt_amount"]) * 100
        total_unrealized += pnl
        open_pos.append({
            **pos,
            "current_price": price,
            "pnl":           round(pnl, 4),
            "pnl_pct":       round(pnl_pct, 2),
        })

    total_trades  = data["total_trades"]
    wins          = data["wins"]
    losses        = data["losses"]
    win_rate      = round((wins / total_trades * 100) if total_trades else 0, 1)
    total_realized = sum(t["pnl"] for t in data["closed_trades"])
    net_pnl       = total_realized + total_unrealized

    return {
        "balance":          round(data["balance"], 2),
        "starting":         data["starting"],
        "open_positions":   open_pos,
        "closed_trades":    data["closed_trades"][-10:],  # last 10
        "total_trades":     total_trades,
        "wins":             wins,
        "losses":           losses,
        "win_rate":         win_rate,
        "total_realized":   round(total_realized, 4),
        "total_unrealized": round(total_unrealized, 4),
        "net_pnl":          round(net_pnl, 4),
    }


def reset_portfolio():
    """Reset paper trading account to starting balance."""
    data = {
        "balance":       STARTING_BALANCE,
        "starting":      STARTING_BALANCE,
        "positions":     {},
        "closed_trades": [],
        "total_trades":  0,
        "wins":          0,
        "losses":        0,
    }
    _save(data)
    return data


# ── FORMATTERS ────────────────────────────────────────────────────────────────
def format_portfolio_message(p: dict) -> str:
    net_emoji = "🟢" if p["net_pnl"] >= 0 else "🔴"
    lines = [
        "📋 <b>Paper Trading Portfolio</b> 🧪\n",
        f"💰 Cash Balance:  <b>${p['balance']:,.2f} USDT</b>",
        f"📊 Starting:      ${p['starting']:,.2f} USDT",
        f"{net_emoji} Net PnL:       <b>${p['net_pnl']:+.2f} USDT</b>",
        f"   Realized:     ${p['total_realized']:+.4f}",
        f"   Unrealized:   ${p['total_unrealized']:+.4f}",
        f"\n🏆 Record: {p['wins']}W / {p['losses']}L — Win Rate: <b>{p['win_rate']}%</b>",
        f"   Total Trades: {p['total_trades']}",
    ]

    if p["open_positions"]:
        lines.append("\n📂 <b>Open Positions:</b>")
        for pos in p["open_positions"]:
            coin    = pos["symbol"].replace("/USDT", "")
            side_e  = "🟢 LONG" if pos["side"] == "buy" else "🔴 SHORT"
            pnl_e   = "+" if pos["pnl"] >= 0 else ""
            tp1_tag = " ✅TP1" if pos.get("tp1_hit") else ""
            sl_str  = f"${pos['sl']:,.4f}"  if pos.get("sl")  else "—"
            tp2_str = f"${pos['tp2']:,.4f}" if pos.get("tp2") else "—"
            lines.append(
                f"  {side_e} <b>{coin}</b>{tp1_tag}\n"
                f"    Entry: ${pos['entry_price']:,.4f} → Now: ${pos['current_price']:,.4f}\n"
                f"    PnL: <b>{pnl_e}${pos['pnl']:.4f}</b> ({pnl_e}{pos['pnl_pct']:.2f}%)\n"
                f"    SL: {sl_str} | TP2: {tp2_str}"
            )
    else:
        lines.append("\n📂 No open positions.")

    if p["closed_trades"]:
        lines.append("\n📜 <b>Recent Closed Trades:</b>")
        for t in reversed(p["closed_trades"][-5:]):
            coin   = t["symbol"].replace("/USDT", "")
            pnl_e  = "🟢" if t["pnl"] >= 0 else "🔴"
            lines.append(
                f"  {pnl_e} {coin} {t['side'].upper()} → "
                f"<b>{'+' if t['pnl']>=0 else ''}{t['pnl']:.4f}</b> USDT "
                f"({t.get('reason','closed')})"
            )

    lines.append("\n<i>📌 Paper trading — fake USDT, real prices</i>")
    return "\n".join(lines)


def format_close_message(result: dict) -> str:
    if "error" in result:
        return f"❌ {result['error']}"
    coin    = result["symbol"].replace("/USDT", "")
    pnl_e   = "🟢" if result["pnl"] >= 0 else "🔴"
    trigger = result.get("reason", "manual").replace("_", " ").title()
    return (
        f"{pnl_e} <b>Position Closed — {coin}</b>\n\n"
        f"Side:   {'🟢 LONG' if result['side']=='buy' else '🔴 SHORT'}\n"
        f"Entry:  ${result['entry']:,.4f}\n"
        f"Exit:   ${result['exit']:,.4f}\n"
        f"PnL:    <b>{'+' if result['pnl']>=0 else ''}{result['pnl']:.4f} USDT "
        f"({'+' if result['pnl']>=0 else ''}{result['pnl_pct']:.2f}%)</b>\n"
        f"Reason: {trigger}\n\n"
        f"💰 Balance: ${result['balance']:,.2f} USDT"
    )
