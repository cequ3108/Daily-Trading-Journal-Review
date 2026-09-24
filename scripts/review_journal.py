#!/usr/bin/env python3
"""將交易紀錄與 FinMind 市場資料交叉比對，產生檢討摘要。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {"date", "stock_id", "side", "price", "shares"}


def load_journal(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"交易紀錄缺少欄位: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["stock_id"] = df["stock_id"].astype(str)
    return df


def load_market_data(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "watchlist_daily.csv"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，請先執行 fetch_market_context.py")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["stock_id"] = df["stock_id"].astype(str)
    return df


def review_journal(journal: pd.DataFrame, market: pd.DataFrame) -> dict:
    merged = journal.merge(
        market[["date", "stock_id", "open", "max", "min", "close"]],
        on=["date", "stock_id"],
        how="left",
    )

    trades = []
    for _, row in merged.iterrows():
        side = str(row["side"]).lower()
        entry_price = float(row["price"])
        day_close = float(row["close"]) if pd.notna(row["close"]) else None
        day_high = float(row["max"]) if pd.notna(row["max"]) else None
        day_low = float(row["min"]) if pd.notna(row["min"]) else None

        same_day_pnl_pct = None
        if day_close is not None:
            if side in ("buy", "long", "買"):
                same_day_pnl_pct = (day_close / entry_price - 1) * 100
            elif side in ("sell", "short", "賣"):
                same_day_pnl_pct = (entry_price / day_close - 1) * 100

        trades.append(
            {
                "date": row["date"],
                "stock_id": row["stock_id"],
                "side": row["side"],
                "entry_price": entry_price,
                "shares": int(row["shares"]),
                "day_high": day_high,
                "day_low": day_low,
                "day_close": day_close,
                "same_day_close_pnl_pct": round(same_day_pnl_pct, 2)
                if same_day_pnl_pct is not None
                else None,
                "note": row.get("note", ""),
            }
        )

    stock_ids = sorted(journal["stock_id"].unique())
    return {
        "trade_count": len(trades),
        "unique_stocks": stock_ids,
        "trades": trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="交易紀錄檢討")
    parser.add_argument("--journal", required=True, help="交易紀錄 CSV 路徑")
    parser.add_argument(
        "--data-dir",
        default="data/2026-08",
        help="FinMind 市場資料目錄",
    )
    parser.add_argument("--output", help="檢討結果 JSON 輸出路徑")
    args = parser.parse_args()

    journal = load_journal(Path(args.journal))
    market = load_market_data(Path(args.data_dir))
    result = review_journal(journal, market)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
