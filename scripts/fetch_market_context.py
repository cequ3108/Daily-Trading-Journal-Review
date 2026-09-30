#!/usr/bin/env python3
"""從 FinMind 抓取指定期間的市場背景資料，供交易檢討使用。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd
from FinMind.data import DataLoader


def fetch_market_context(
    start_date: str,
    end_date: str,
    watchlist: list[str],
    output_dir: Path,
) -> dict:
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise RuntimeError("請設定環境變數 FINMIND_TOKEN")

    api = DataLoader()
    api.login_by_token(api_token=token)
    output_dir.mkdir(parents=True, exist_ok=True)

    for idx in ("TAIEX", "OTC"):
        df = api.taiwan_stock_daily(stock_id=idx, start_date=start_date, end_date=end_date)
        df.to_csv(output_dir / f"{idx}_daily.csv", index=False)

    trading_dates = api.taiwan_stock_trading_date(start_date=start_date, end_date=end_date)
    trading_dates.to_csv(output_dir / "trading_dates.csv", index=False)

    if watchlist:
        stock_data = api.taiwan_stock_daily(
            stock_id_list=watchlist,
            start_date=start_date,
            end_date=end_date,
            use_async=True,
        )
        stock_data.to_csv(output_dir / "watchlist_daily.csv", index=False)

    taiex = pd.read_csv(output_dir / "TAIEX_daily.csv")
    summary = {
        "period": f"{start_date} ~ {end_date}",
        "trading_days": len(taiex),
        "taiex_open": round(float(taiex.iloc[0]["open"]), 2),
        "taiex_close": round(float(taiex.iloc[-1]["close"]), 2),
        "taiex_high": round(float(taiex["max"].max()), 2),
        "taiex_low": round(float(taiex["min"].min()), 2),
        "taiex_return_pct": round(
            (float(taiex.iloc[-1]["close"]) / float(taiex.iloc[0]["open"]) - 1) * 100, 2
        ),
        "watchlist": watchlist,
    }
    with open(output_dir / "market_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取 FinMind 市場背景資料")
    parser.add_argument("--start", required=True, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="結束日期 YYYY-MM-DD")
    parser.add_argument(
        "--watchlist",
        default="2330,2317,2454,2303,2881,0050,0056",
        help="逗號分隔的股票代號",
    )
    parser.add_argument(
        "--output",
        default="data",
        help="輸出根目錄，實際路徑為 data/YYYY-MM",
    )
    args = parser.parse_args()

    period_key = args.start[:7]
    output_dir = Path(args.output) / period_key
    watchlist = [s.strip() for s in args.watchlist.split(",") if s.strip()]
    summary = fetch_market_context(args.start, args.end, watchlist, output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
