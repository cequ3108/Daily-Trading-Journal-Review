# Daily Trading Journal Review

用 FinMind 歷史資料輔助台股交易紀錄的月度檢討。

## 你可以怎麼用

1. **上傳上個月的交易分析**（CSV、Excel、截圖或文字筆記皆可）
2. 我會把每筆交易對照當日/當週的市場走勢、大盤環境做檢討
3. 必要時可補抓你交易標的的籌碼面、法人買賣等 FinMind 資料

## 建議的交易紀錄格式

請盡量包含以下欄位（可直接用 `templates/journal_template.csv`）：

| 欄位 | 說明 |
|------|------|
| `date` | 交易日期 YYYY-MM-DD |
| `stock_id` | 股票代號 |
| `side` | buy / sell（或 買 / 賣） |
| `price` | 成交價 |
| `shares` | 股數 |
| `note` | 進出場理由（選填） |

## 已準備的市場背景（2026 年 8 月）

FinMind 已連線，並預先抓取上個月資料，摘要如下：

- **加權指數**：42,780 → 46,128（月漲 **+7.83%**）
- **區間高點 / 低點**：46,575 / 42,780
- **交易日**：21 天
- **預設觀察標的**：2330、2317、2454、2303、2881、0050、0056

詳細資料在 `data/2026-08/`。

## 環境設定

```bash
pip install -r requirements.txt
export FINMIND_TOKEN=你的_token   # Cloud Agent 環境已設定
```

## 指令

```bash
# 抓取指定期間市場資料（watchlist 可改成你的持股）
python scripts/fetch_market_context.py \
  --start 2026-08-01 --end 2026-08-31 \
  --watchlist 2330,2454,你的代號

# 對照交易紀錄做初步檢討
python scripts/review_journal.py \
  --journal templates/journal_template.csv \
  --data-dir data/2026-08 \
  --output review_result.json
```

## 檢討維度（你上傳資料後我會做）

- **進出場時機**：相對當日高低點、收盤價的位置
- **大盤環境**：強勢月 (+7.83%) 下，個股選擇與部位是否合理
- **策略一致性**：note 中的理由 vs 實際走勢是否吻合
- **風險管理**：停損/停利、部位大小、交易頻率
- **可選回測**：若你有固定規則，可用 FinMind BackTest 框架驗證
