#!/usr/bin/env python3
"""抓取券商分點籌碼。

優先順序：
1. 本機／clone 的 tw-broker-chip-data（BROKER_CHIP_REPO 或 --repo-dir）
2. FinMind TaiwanStockTradingDailyReport（需 FINMIND_TOKEN）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import pandas as pd
from FinMind.data import DataLoader

REQUIRED_COLS = {
    "date",
    "stock_id",
    "securities_trader",
    "securities_trader_id",
    "price",
    "buy",
    "sell",
}

DEFAULT_REPO = "https://github.com/cequ3108/tw-broker-chip-data.git"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    rename = {
        "Date": "date",
        "StockId": "stock_id",
        "stock": "stock_id",
        "broker": "securities_trader",
        "broker_name": "securities_trader",
        "broker_id": "securities_trader_id",
        "Buy": "buy",
        "Sell": "sell",
        "Price": "price",
    }
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns}).copy()
    missing = REQUIRED_COLS - set(out.columns)
    if missing:
        raise ValueError(f"籌碼資料缺少欄位: {sorted(missing)}")
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["stock_id"] = out["stock_id"].astype(str)
    out["securities_trader"] = out["securities_trader"].astype(str)
    out["securities_trader_id"] = out["securities_trader_id"].astype(str)
    for c in ("price", "buy", "sell"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    return out[list(REQUIRED_COLS)]


def try_clone_repo(repo_url: str, dest: Path) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            subprocess.run(
                ["git", "-C", str(dest), "pull", "--ff-only"],
                check=True,
                capture_output=True,
                text=True,
            )
            return dest
        except subprocess.CalledProcessError:
            shutil.rmtree(dest, ignore_errors=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
        return dest
    except subprocess.CalledProcessError as e:
        print(f"[warn] 無法 clone {repo_url}: {e.stderr or e.stdout}")
        return None


def load_from_repo_dir(repo_dir: Path, date: str, stock_ids: list[str]) -> pd.DataFrame | None:
    if not repo_dir.exists():
        return None

    candidates: list[Path] = []
    for pattern in (
        f"**/{date}*.parquet",
        f"**/{date}*.csv",
        f"**/{date}/**/*.parquet",
        f"**/{date}/**/*.csv",
        f"**/data/{date}*",
    ):
        candidates.extend(repo_dir.glob(pattern))

    # also accept nested YYYY/MM/DD
    y, m, d = date.split("-")
    for pattern in (f"**/{y}/{m}/{d}/**/*", f"**/{y}{m}{d}*", f"**/{y}-{m}-{d}*"):
        candidates.extend(repo_dir.glob(pattern))

    files = sorted(
        {
            p
            for p in candidates
            if p.is_file() and p.suffix.lower() in {".csv", ".parquet", ".pq"}
        }
    )
    if not files:
        # last resort: any parquet/csv mentioning date in name under data/
        data_root = repo_dir / "data"
        if data_root.exists():
            files = sorted(
                p
                for p in data_root.rglob("*")
                if p.is_file()
                and p.suffix.lower() in {".csv", ".parquet", ".pq"}
                and date.replace("-", "") in p.name.replace("-", "")
            )
    if not files:
        print(f"[warn] repo 內找不到 {date} 籌碼檔：{repo_dir}")
        return None

    frames = []
    for path in files:
        try:
            raw = pd.read_parquet(path) if path.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(path)
            part = _normalize(raw)
            frames.append(part)
            print(f"[ok] 讀取 {path.relative_to(repo_dir)} rows={len(part)}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 略過 {path}: {e}")

    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df = df[df["date"] == date]
    if stock_ids:
        df = df[df["stock_id"].isin(stock_ids)]
    return df.reset_index(drop=True)


def fetch_from_finmind(date: str, stock_ids: list[str]) -> pd.DataFrame:
    token = os.environ.get("FINMIND_TOKEN")
    if not token:
        raise RuntimeError("請設定環境變數 FINMIND_TOKEN")
    if not stock_ids:
        raise RuntimeError("FinMind 單檔查詢需要 --stocks")

    api = DataLoader()
    api.login_by_token(api_token=token)
    frames = []
    for sid in stock_ids:
        df = api.taiwan_stock_trading_daily_report(stock_id=sid, date=date)
        if df is None or df.empty:
            print(f"[warn] FinMind 無資料 {sid} {date}")
            continue
        frames.append(_normalize(df))
        print(f"[ok] FinMind {sid} rows={len(df)}")
    if not frames:
        return pd.DataFrame(columns=list(REQUIRED_COLS))
    return pd.concat(frames, ignore_index=True)


def fetch_closes(date: str, stock_ids: list[str]) -> dict[str, float]:
    token = os.environ.get("FINMIND_TOKEN")
    if not token or not stock_ids:
        return {}
    api = DataLoader()
    api.login_by_token(api_token=token)
    closes: dict[str, float] = {}
    for sid in stock_ids:
        df = api.taiwan_stock_daily(stock_id=sid, start_date=date, end_date=date)
        if df is not None and not df.empty:
            closes[sid] = float(df.iloc[-1]["close"])
    return closes


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取券商分點籌碼")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--stocks", default="", help="逗號分隔股票代號；空=全檔（僅 repo）")
    parser.add_argument(
        "--repo-dir",
        default=os.environ.get("BROKER_CHIP_REPO_DIR", "vendor/tw-broker-chip-data"),
        help="本機籌碼 repo 路徑",
    )
    parser.add_argument(
        "--repo-url",
        default=os.environ.get("BROKER_CHIP_REPO_URL", DEFAULT_REPO),
        help="籌碼 repo git URL",
    )
    parser.add_argument("--skip-clone", action="store_true", help="不要嘗試 git clone/pull")
    parser.add_argument("--output-dir", default="data", help="輸出根目錄")
    args = parser.parse_args()

    stock_ids = [s.strip() for s in args.stocks.split(",") if s.strip()]
    out_dir = Path(args.output_dir) / args.date
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_dir = Path(args.repo_dir)
    source = None
    df = None

    if not args.skip_clone:
        cloned = try_clone_repo(args.repo_url, repo_dir)
        if cloned:
            repo_dir = cloned

    df = load_from_repo_dir(repo_dir, args.date, stock_ids)
    if df is not None and not df.empty:
        source = "tw-broker-chip-data"
    else:
        df = fetch_from_finmind(args.date, stock_ids)
        source = "finmind"

    if stock_ids:
        used_ids = stock_ids
    else:
        used_ids = sorted(df["stock_id"].unique().tolist()) if not df.empty else []

    closes = fetch_closes(args.date, used_ids)
    raw_path = out_dir / "broker_chips_raw.csv"
    df.to_csv(raw_path, index=False)

    meta = {
        "date": args.date,
        "source": source,
        "repo_dir": str(repo_dir),
        "stock_ids": used_ids,
        "rows": int(len(df)),
        "closes": closes,
        "raw_csv": str(raw_path),
    }
    meta_path = out_dir / "broker_chips_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
