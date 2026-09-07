#!/usr/bin/env python3
"""券商分點籌碼功課：誰在買/賣、誰賺最多/賠最多、操作邏輯摘要。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _broker_stats(df: pd.DataFrame, close: float | None) -> pd.DataFrame:
    tmp = df.copy()
    tmp["buy_amt"] = tmp["price"] * tmp["buy"]
    tmp["sell_amt"] = tmp["price"] * tmp["sell"]
    g = tmp.groupby(["securities_trader_id", "securities_trader"], as_index=False).agg(
        buy_shares=("buy", "sum"),
        sell_shares=("sell", "sum"),
        buy_notional=("buy_amt", "sum"),
        sell_notional=("sell_amt", "sum"),
    )
    g["net_shares"] = g["buy_shares"] - g["sell_shares"]
    g["avg_buy"] = g.apply(
        lambda r: (r["buy_notional"] / r["buy_shares"]) if r["buy_shares"] else None, axis=1
    )
    g["avg_sell"] = g.apply(
        lambda r: (r["sell_notional"] / r["sell_shares"]) if r["sell_shares"] else None, axis=1
    )
    if close is not None:
        # 當日估計損益：賣出收入 - 買進成本 + 淨庫存 × 收盤
        g["est_pnl"] = g["sell_notional"] - g["buy_notional"] + g["net_shares"] * close
    else:
        g["est_pnl"] = g["sell_notional"] - g["buy_notional"]
    g["turnover_shares"] = g["buy_shares"] + g["sell_shares"]
    return g.sort_values("turnover_shares", ascending=False)


def _logic_for_broker(row: pd.Series, close: float | None) -> str:
    buy, sell = float(row["buy_shares"]), float(row["sell_shares"])
    net = float(row["net_shares"])
    avg_b, avg_s = row["avg_buy"], row["avg_sell"]
    tags: list[str] = []

    if buy > 0 and sell > 0:
        tags.append("當沖對敲")
        if avg_b and avg_s and avg_s > avg_b:
            tags.append("高賣低買偏賺")
        elif avg_b and avg_s and avg_s < avg_b:
            tags.append("低賣高買偏賠")
    elif buy > 0 and sell == 0:
        tags.append("純買進鎖碼")
    elif sell > 0 and buy == 0:
        tags.append("純賣出出貨")

    if close and avg_b:
        if net > 0 and avg_b < close * 0.99:
            tags.append("偏低價吃貨")
        if net > 0 and avg_b > close * 1.01:
            tags.append("追高吃貨")
    if close and avg_s:
        if net < 0 and avg_s > close * 1.01:
            tags.append("偏高價倒貨")
        if net < 0 and avg_s < close * 0.99:
            tags.append("壓低出貨")

    if abs(net) > max(buy, sell) * 0.6 and buy > 0 and sell > 0:
        tags.append("偏向單邊")
    return "／".join(tags) if tags else "中性"


def analyze_stock(df: pd.DataFrame, stock_id: str, close: float | None, top_n: int = 8) -> dict:
    part = df[df["stock_id"] == stock_id].copy()
    stats = _broker_stats(part, close)
    if stats.empty:
        return {"stock_id": stock_id, "close": close, "brokers": [], "summary": "無分點資料"}

    total_buy = float(stats["buy_shares"].sum())
    total_sell = float(stats["sell_shares"].sum())
    stats["logic"] = stats.apply(lambda r: _logic_for_broker(r, close), axis=1)

    top_buy = stats.nlargest(top_n, "net_shares")
    top_sell = stats.nsmallest(top_n, "net_shares")
    winners = stats.nlargest(top_n, "est_pnl")
    losers = stats.nsmallest(top_n, "est_pnl")

    # concentration
    top5_turnover = float(stats.nlargest(5, "turnover_shares")["turnover_shares"].sum())
    all_turnover = float(stats["turnover_shares"].sum()) or 1.0
    concentration = top5_turnover / all_turnover

    def pack(frame: pd.DataFrame) -> list[dict]:
        rows = []
        for _, r in frame.iterrows():
            rows.append(
                {
                    "broker": r["securities_trader"],
                    "broker_id": r["securities_trader_id"],
                    "buy_lots": round(float(r["buy_shares"]) / 1000, 1),
                    "sell_lots": round(float(r["sell_shares"]) / 1000, 1),
                    "net_lots": round(float(r["net_shares"]) / 1000, 1),
                    "avg_buy": None if pd.isna(r["avg_buy"]) else round(float(r["avg_buy"]), 2),
                    "avg_sell": None if pd.isna(r["avg_sell"]) else round(float(r["avg_sell"]), 2),
                    "est_pnl": round(float(r["est_pnl"]), 0),
                    "logic": r["logic"],
                }
            )
        return rows

    # overall market maker style
    styles = stats["logic"].value_counts().head(5).to_dict()

    return {
        "stock_id": stock_id,
        "close": close,
        "total_buy_lots": round(total_buy / 1000, 1),
        "total_sell_lots": round(total_sell / 1000, 1),
        "broker_count": int(len(stats)),
        "top5_turnover_share": round(concentration, 3),
        "top_net_buy": pack(top_buy),
        "top_net_sell": pack(top_sell),
        "top_winners": pack(winners),
        "top_losers": pack(losers),
        "logic_styles": {str(k): int(v) for k, v in styles.items()},
        "read": _stock_read(stock_id, close, top_buy, top_sell, winners, losers, concentration),
    }


def _stock_read(
    stock_id: str,
    close: float | None,
    top_buy: pd.DataFrame,
    top_sell: pd.DataFrame,
    winners: pd.DataFrame,
    losers: pd.DataFrame,
    concentration: float,
) -> str:
    buy_names = "、".join(top_buy.head(3)["securities_trader"].tolist())
    sell_names = "、".join(top_sell.head(3)["securities_trader"].tolist())
    win_names = "、".join(winners.head(2)["securities_trader"].tolist())
    lose_names = "、".join(losers.head(2)["securities_trader"].tolist())
    conc = "分點集中" if concentration >= 0.25 else "分點分散"
    return (
        f"{stock_id} 收{close}；主力偏買：{buy_names}；主力偏賣：{sell_names}；"
        f"估計當日賺最多：{win_names}；賠最多：{lose_names}；{conc}（前5分點成交占比 {concentration:.0%}）。"
    )


def build_homework(meta: dict, df: pd.DataFrame, top_n: int = 8) -> dict:
    closes = meta.get("closes") or {}
    stock_ids = meta.get("stock_ids") or sorted(df["stock_id"].unique().tolist())
    per_stock = []
    for sid in stock_ids:
        close = closes.get(sid)
        if close is None and sid in closes:
            close = closes[sid]
        per_stock.append(analyze_stock(df, sid, float(close) if close is not None else None, top_n=top_n))

    # cross-stock broker scoreboard
    all_stats = []
    for sid in stock_ids:
        close = closes.get(sid)
        part = df[df["stock_id"] == sid]
        if part.empty:
            continue
        st = _broker_stats(part, float(close) if close is not None else None)
        st["stock_id"] = sid
        all_stats.append(st)
    board = []
    if all_stats:
        big = pd.concat(all_stats, ignore_index=True)
        board_g = big.groupby(["securities_trader_id", "securities_trader"], as_index=False).agg(
            est_pnl=("est_pnl", "sum"),
            net_shares=("net_shares", "sum"),
            turnover_shares=("turnover_shares", "sum"),
            names=("stock_id", lambda s: ",".join(sorted(set(s)))),
        )
        board_g = board_g.sort_values("est_pnl", ascending=False)
        for _, r in pd.concat([board_g.head(10), board_g.tail(10)]).drop_duplicates().iterrows():
            board.append(
                {
                    "broker": r["securities_trader"],
                    "broker_id": r["securities_trader_id"],
                    "est_pnl": round(float(r["est_pnl"]), 0),
                    "net_lots": round(float(r["net_shares"]) / 1000, 1),
                    "stocks": r["names"],
                }
            )

    return {
        "date": meta.get("date"),
        "source": meta.get("source"),
        "stock_ids": stock_ids,
        "per_stock": per_stock,
        "cross_broker_board": board,
        "notes": [
            "est_pnl 為「賣出收入−買進成本+淨庫存×收盤」之當日估計，非真實帳戶損益。",
            "同公司多分點（如元大各分公司）未合併；解讀時可再按券商品牌加總。",
            "優先資料源：tw-broker-chip-data；失敗時改用 FinMind 分點。",
        ],
    }


def render_markdown(hw: dict) -> str:
    lines = [
        f"# 券商分點籌碼功課 {hw['date']}",
        "",
        f"資料來源：`{hw.get('source')}`",
        "",
        "## 跨標的券商估計損益榜（前賺／後賠）",
    ]
    board = hw.get("cross_broker_board") or []
    if not board:
        lines.append("- （無）")
    else:
        for b in board[:10]:
            lines.append(
                f"- 賺 {b['broker']} {b['est_pnl']:,.0f}（淨 {b['net_lots']} 張｜{b['stocks']}）"
            )
        lines.append("")
        lines.append("賠最多：")
        for b in board[-5:]:
            lines.append(
                f"- 賠 {b['broker']} {b['est_pnl']:,.0f}（淨 {b['net_lots']} 張｜{b['stocks']}）"
            )

    for s in hw.get("per_stock") or []:
        lines.extend(
            [
                "",
                f"## {s['stock_id']}（收 {s.get('close')}｜分點 {s.get('broker_count')}）",
                s.get("read", ""),
                "",
                "### 淨買超前幾名",
            ]
        )
        for r in s.get("top_net_buy", [])[:5]:
            lines.append(
                f"- {r['broker']} 淨+{r['net_lots']}張｜買均 {r['avg_buy']} 賣均 {r['avg_sell']}｜"
                f"估PnL {r['est_pnl']:,.0f}｜{r['logic']}"
            )
        lines.append("")
        lines.append("### 淨賣超前幾名")
        for r in s.get("top_net_sell", [])[:5]:
            lines.append(
                f"- {r['broker']} 淨{r['net_lots']}張｜買均 {r['avg_buy']} 賣均 {r['avg_sell']}｜"
                f"估PnL {r['est_pnl']:,.0f}｜{r['logic']}"
            )
        lines.append("")
        lines.append("### 估計賺最多／賠最多")
        for r in s.get("top_winners", [])[:3]:
            lines.append(f"- 賺：{r['broker']} {r['est_pnl']:,.0f}｜{r['logic']}")
        for r in s.get("top_losers", [])[:3]:
            lines.append(f"- 賠：{r['broker']} {r['est_pnl']:,.0f}｜{r['logic']}")

    lines.extend(["", "## 備註"])
    for n in hw.get("notes") or []:
        lines.append(f"- {n}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="券商分點籌碼功課")
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-dir", default="data", help="含 YYYY-MM-DD 子目錄的根目錄")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--output", help="JSON 輸出路徑")
    parser.add_argument("--markdown", help="Markdown 輸出路徑")
    args = parser.parse_args()

    day_dir = Path(args.data_dir) / args.date
    meta = json.loads((day_dir / "broker_chips_meta.json").read_text(encoding="utf-8"))
    df = pd.read_csv(day_dir / "broker_chips_raw.csv")
    df["stock_id"] = df["stock_id"].astype(str)

    hw = build_homework(meta, df, top_n=args.top)
    out_json = Path(args.output) if args.output else day_dir / "broker_chips_homework.json"
    out_md = Path(args.markdown) if args.markdown else day_dir / "broker_chips_homework.md"
    out_json.write_text(json.dumps(hw, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_markdown(hw), encoding="utf-8")
    print(f"wrote {out_json}")
    print(f"wrote {out_md}")


if __name__ == "__main__":
    main()
