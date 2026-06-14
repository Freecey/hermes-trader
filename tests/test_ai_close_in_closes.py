"""Regression: AI CLOSE verdicts must surface in the dashboard recent-closes
panel. Before the fix, _closed_trades_payload only walked dsl_exit and
close_position, so AI-driven closes were invisible — and the ai_close event
didn't even carry the realized PnL needed to render one."""

from hermes_trader import dashboard, session_log


def test_ai_close_with_pnl_surfaces_in_closed_trades():
    session_log.append({"event": "execute", "coin": "FARTCOIN", "side": "short"})
    session_log.append({
        "event": "ai_close", "coin": "FARTCOIN", "executed": True,
        "detail": "7", "reasoning": "momentum faded",
        "side": "short", "leverage": 3, "entry_px": 0.124745,
        "fill_px": 0.125575, "realized_pnl_pct": -2.1462,
        "realized_spot_pct": -0.6654, "fees_pct": 0.15,
        "reason": "AI CLOSE verdict",
    })
    rows = dashboard._closed_trades_payload(limit=50)
    fart = [r for r in rows if r["coin"] == "FARTCOIN"]
    assert fart, "AI close not surfaced in closed-trades payload"
    r = fart[0]
    assert r["source"] == "ai"
    assert r["side"] == "short"
    assert r["leverage"] == 3
    assert r["pnl_source"] == "fill"
    assert abs(r["pnl_pct"] - (-2.1462)) < 1e-6
    assert abs(r["pnl_pct_gross"] - (-0.6654 * 3)) < 1e-6
    assert r["executed"] is True


def test_ai_close_without_pnl_degrades_gracefully():
    # An old/noop ai_close with no PnL fields must still render (0%, estimated)
    # and expose the keys the frontend tooltip reads unconditionally.
    session_log.append({"event": "ai_close", "coin": "DOGE",
                        "executed": True, "detail": "noop"})
    rows = dashboard._closed_trades_payload(limit=50)
    doge = [r for r in rows if r["coin"] == "DOGE"]
    assert doge
    r = doge[0]
    assert r["source"] == "ai"
    assert r["pnl_pct"] == 0.0
    assert r["pnl_source"] == "estimated"
    assert "pnl_pct_gross" in r and "fees_pct" in r and "spot_pct" in r
