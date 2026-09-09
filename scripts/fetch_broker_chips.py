#!/usr/bin/env python3
"""抓取券商分點籌碼。

優先順序：
1. 本機／clone 的 tw-broker-chip-data（BROKER_CHIP_REPO 或 --repo-dir）
   - 預設分支：main（已合併；勿再用舊 feature branch）
   - 路徑：data/daily/YYYY-MM-DD.parquet（Git LFS，需 git lfs pull）
2. FinMind TaiwanStockTradingDailyReport（需 FINMIND_TOKEN；僅指定股票／後備）
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
DEFAULT_BRANCH = "main"


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )


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
        "buy_amount": "buy_amt",
        "sell_amount": "sell_amt",
    }
    out = df.rename(columns={k: v for k, v in rename.items() if k in df.columns}).copy()

    for c in ("buy", "sell"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    for c in ("buy_amt", "sell_amt"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

    # tw-broker-chip-data：無 price，改由金額／股數推估均價
    if "price" not in out.columns:
        buy = pd.to_numeric(out.get("buy", 0), errors="coerce").fillna(0)
        sell = pd.to_numeric(out.get("sell", 0), errors="coerce").fillna(0)
        buy_amt = pd.to_numeric(out.get("buy_amt", 0), errors="coerce").fillna(0)
        sell_amt = pd.to_numeric(out.get("sell_amt", 0), errors="coerce").fillna(0)
        tot = buy + sell
        blended = (buy_amt + sell_amt) / tot.replace(0, pd.NA)
        buy_only = buy_amt / buy.replace(0, pd.NA)
        sell_only = sell_amt / sell.replace(0, pd.NA)
        price = blended.fillna(buy_only).fillna(sell_only).fillna(0)
        out["price"] = pd.to_numeric(price, errors="coerce").fillna(0)

    missing = REQUIRED_COLS - set(out.columns)
    if missing:
        raise ValueError(f"籌碼資料缺少欄位: {sorted(missing)}")

    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out["stock_id"] = out["stock_id"].astype(str)
    out["securities_trader"] = out["securities_trader"].astype(str)
    out["securities_trader_id"] = out["securities_trader_id"].astype(str)
    for c in ("price", "buy", "sell"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

    cols = list(REQUIRED_COLS)
    for extra in ("buy_amt", "sell_amt"):
        if extra in out.columns:
            cols.append(extra)
    return out[cols]


def _ensure_lfs(repo_dir: Path) -> None:
    try:
        _run(["git", "lfs", "install"], cwd=repo_dir)
        _run(["git", "lfs", "pull"], cwd=repo_dir)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"[warn] git lfs pull 失敗（parquet 可能仍是指標檔）: {e}")


def try_sync_repo(repo_url: str, dest: Path, branch: str) -> Path | None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dest.exists() and (dest / ".git").exists():
            _run(["git", "remote", "set-url", "origin", repo_url], cwd=dest)
            _run(["git", "fetch", "origin", branch], cwd=dest)
            _run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=dest)
            try:
                _run(["git", "pull", "origin", branch], cwd=dest)
            except subprocess.CalledProcessError as e:
                print(f"[warn] git pull origin {branch}: {(e.stderr or e.stdout or '').strip()}")
            _ensure_lfs(dest)
            return dest

        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)

        _run(
            [
                "git",
                "clone",
                "--branch",
                branch,
                "--single-branch",
                repo_url,
                str(dest),
            ]
        )
        _ensure_lfs(dest)
        return dest
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or "").strip()
        print(f"[warn] 無法同步 {repo_url}@{branch}: {err}")
        return None


def load_from_repo_dir(repo_dir: Path, date: str, stock_ids: list[str]) -> pd.DataFrame | None:
    if not repo_dir.exists():
        return None

    preferred = repo_dir / "data" / "daily" / f"{date}.parquet"
    files: list[Path] = []
    if preferred.is_file():
        files = [preferred]
    else:
        candidates: list[Path] = []
        for pattern in (
            f"data/daily/{date}.parquet",
            f"**/{date}*.parquet",
            f"**/{date}*.csv",
            f"**/{date}/**/*.parquet",
            f"**/{date}/**/*.csv",
        ):
            candidates.extend(repo_dir.glob(pattern))
        files = sorted(
            {
                p
                for p in candidates
                if p.is_file() and p.suffix.lower() in {".csv", ".parquet", ".pq"}
            }
        )

    if not files:
        print(f"[warn] repo 內找不到 {date} 籌碼檔：{repo_dir}（預期 data/daily/{date}.parquet）")
        return None

    frames = []
    for path in files:
        try:
            raw = (
                pd.read_parquet(path)
                if path.suffix.lower() in {".parquet", ".pq"}
                else pd.read_csv(path)
            )
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
        raise RuntimeError("FinMind 單檔查詢需要 --stocks（全市場請用 tw-broker-chip-data）")

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
    try:
        api = DataLoader()
        api.login_by_token(api_token=token)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] FinMind login 失敗，略過收盤價: {e}")
        return {}
    closes: dict[str, float] = {}
    for sid in stock_ids:
        try:
            df = api.taiwan_stock_daily(stock_id=sid, start_date=date, end_date=date)
            if df is not None and not df.empty:
                closes[sid] = float(df.iloc[-1]["close"])
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 收盤價略過 {sid}: {e}")
            break  # 多半是 rate limit，後面也會失敗
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
    parser.add_argument(
        "--branch",
        default=os.environ.get("BROKER_CHIP_BRANCH", DEFAULT_BRANCH),
        help="籌碼資料所在分支（預設 main）",
    )
    parser.add_argument("--skip-clone", action="store_true", help="不要嘗試 git sync/LFS")
    parser.add_argument("--output-dir", default="data", help="輸出根目錄")
    args = parser.parse_args()

    stock_ids = [s.strip() for s in args.stocks.split(",") if s.strip()]
    out_dir = Path(args.output_dir) / args.date
    out_dir.mkdir(parents=True, exist_ok=True)

    repo_dir = Path(args.repo_dir)
    source = None
    df = None

    if not args.skip_clone:
        synced = try_sync_repo(args.repo_url, repo_dir, args.branch)
        if synced:
            repo_dir = synced

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

    # 全市場檔很大時，預設不逐檔打收盤價 API；有指定股票才抓
    closes = fetch_closes(args.date, stock_ids) if stock_ids else {}
    raw_path = out_dir / "broker_chips_raw.csv"
    # 全市場列數過多：只寫 meta 指向 parquet；有 --stocks 才落地 CSV 供個股功課
    if stock_ids:
        df.to_csv(raw_path, index=False)
        raw_note = str(raw_path)
    else:
        raw_note = None
        print(f"[info] 未指定 --stocks，略過寫入全市場 CSV（rows={len(df)}）；請用 --market-scan 讀 parquet")

    meta = {
        "date": args.date,
        "source": source,
        "repo_dir": str(repo_dir),
        "branch": args.branch,
        "daily_parquet": str(repo_dir / "data" / "daily" / f"{args.date}.parquet"),
        "stock_ids": used_ids if stock_ids else [],
        "stock_count": len(used_ids),
        "rows": int(len(df)),
        "closes": closes,
        "raw_csv": raw_note,
    }
    meta_path = out_dir / "broker_chips_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    printable = {k: v for k, v in meta.items() if k != "stock_ids"}
    print(json.dumps(printable, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
