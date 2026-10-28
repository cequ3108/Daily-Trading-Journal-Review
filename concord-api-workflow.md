# 康和（Concord）證券 API 自動化工作流程

> 文件來源：Cloud Agent 通話討論整理（2026-10-28，Asia/Taipei）  
> 目標帳號：`證-台中-0230867-林冠穎`（口語：證-台中-零二三零八六七）  
> API 套件：`conrich`（康和程式下單／帳務 API）

---

## 1. 概述（Overview）

目標是**收盤後自動拉取**台中帳號當日四份報表，用來取代目前手動從 XQ／桌面端匯出 CSV 的流程，並餵給既有的每日交易日誌複盤腳本。

| 檔案 | 桌面匯出檔名（參考） | 用途 |
|------|----------------------|------|
| 委託 | `證券委託.csv` | 當日所有委託明細 |
| 成交 | `證券成交回報.csv` | 當日成交明細（含成交時間） |
| 對帳單 | `證券對帳單.csv` | 當日交割／應收付 |
| 已實現損益 | `證券已實現損益.csv` | 當日已實現損益彙總 |

成功後的期望狀態：

1. 每個交易日收盤後，由本機 Windows Agent 呼叫康和 API。
2. 輸出四份 CSV，欄位與編碼盡量對齊桌面匯出參考檔。
3. 寫入日誌資料目錄（例如 `data/YYYY-MM-DD/`），再跑既有 review 流程。

---

## 2. API 申請與執行環境（API Access）

### 2.1 申請流程

- **必須透過營業員申請**程式交易／API 權限（不可只靠自行線上開通就視為完成）。
- 需簽署**風險預告書**等相關文件。
- 審核與開通大約需要 **5–10 個營業日**（實際以營業員回覆為準）。
- 需安裝／啟用康和相關下單環境（文件要求含 **康和金好康** 等前置）。

### 2.2 執行環境限制（硬條件）

`conrich` 官方需求：

- **Windows 7+**
- **.NET Framework 4.5+**
- **Python 3.6+**
- 套件本質是 .NET 交易介面的 Python 包裝，**無法在純 Linux Cloud Agent 上直接執行**

官方文件：<https://concords6016.github.io/conrich_docs/>

### 2.3 對本專案的意義

目前 Cursor Cloud Agent 跑在 **Linux** 容器內，因此：

- 不能在此環境完成真實 `login` / `order_recover` / 帳務查詢。
- 正式拉取必須改到**本機 Windows**（或同等 Windows Runner）上的 Local Agent。

---

## 3. 認證（Authentication）

### 3.1 登入方式

- 屬於類似 **OAuth／會話式登入** 的 API 登入流程（`agent.login`）。
- 股票端登入參數核心為：
  - `in_no`：身分證字號（康和登入 ID）
  - `pwd`：密碼
- 後續查詢還需要：
  - `branch_no`：分公司代號（台中分公司，須向營業員確認正確代碼）
  - `account_no`：帳號七碼（含檢查碼），本帳為 **`0230867`**

### 3.2 憑證存放原則

- 呼叫端的康和 **ID／密碼必須安全存放**（環境變數、OS 密鑰庫、或 Cursor secrets），**禁止寫進 Git repo**。
- 建議本機 secrets 名稱範例：
  - `CONCORD_IN_NO`
  - `CONCORD_PWD`
  - `CONCORD_BRANCH_NO`
  - `CONCORD_ACCOUNT_NO=0230867`
- Cloud 環境目前**沒有**任何 Concord／conrich 相關 secret（既有 secrets 僅含 UANALYZE、Gmail、Travelpayouts、FinMind 等）。

---

## 4. 四類查詢對應（The Four Queries）

### 4.1 對帳單 — 現成帳務查詢

- API：`history_delivery`
- 參數：`branch_no`, `account_no`, `strSDate`, `strEDate`（`yyyyMMdd`）
- 收盤後拉「當日」即可對應桌面 `證券對帳單.csv`
- 後處理重點：欄位中文表頭、數字格式、小計列（若桌面有）、編碼 **CP950**、換行 **CRLF**

### 4.2 已實現損益 — 現成帳務查詢

- API：`realized_profit`
- 參數：`branch_no`, `account_no`, `strSDate`, `strEDate`
- 對應桌面 `證券已實現損益.csv`
- 後處理重點：報酬率百分比字串、手續費／交易稅等費用欄、明細欄

### 4.3 委託 — 回補 + 回報事件

- 註冊：`agent.OrderReportEvent += handler`
- 回補：`agent.order_recover(branch_no=..., account_no=...)`
- 從回報物件組出「當日所有委託」扁平列，對應 `證券委託.csv`
- 需自行映射：狀態中文、交易類別、盤別、來源別（例如桌面常見 `XQTrade`）、取消／成交／剩餘張數等

### 4.4 成交 — 同樣走回補 + 回報（明細層）

- 同樣依賴 `OrderReportEvent` 與 `order_recover`
- 成交明細取自 `result.ExcReport`，關鍵欄位包含：

| API 欄位 | 意義 | 對桌面成交檔 |
|----------|------|--------------|
| `Account` | 帳號 | `帳號` |
| `TransactTime` | 成交時間 | **`成交時間`（第 2 欄）** |
| `Symbol` | 商品 | `股票名稱`（需補中文名／代號格式） |
| `Side` / 委託類別相關 | 買賣／交易類別 | `交易類別` |
| `LastQty` | 本次成交量 | `成交數量` |
| `LastPx` | 本次成交價 | `成交單價` |
| （推導）`LastQty * LastPx` | 價金 | `成交價金` |

> **重要：** 桌面「成交回報」主畫面摘要不一定顯示成交時間；**成交時間只在明細（明細）層可見**。呼叫端上傳的 `證券成交回報.csv` **已經是明細扁平格式**，第 1 欄帳號、**第 2 欄就是成交時間**。API 對應時必須用明細列 + `TransactTime`，不可做成摘要列。

---

## 5. 格式對齊（Format Matching）

### 5.1 參考檔來源

格式黃金標準＝呼叫端上傳至聊天室的四份**桌面匯出 CSV**（範例日：2026-10-28，台中帳）：

- `證券委託.csv`
- `證券成交回報.csv`
- `證券對帳單.csv`
- `證券已實現損益.csv`

共通檔案特徵（實測）：

- 編碼：**CP950**（Big5 系），無 BOM
- 分隔：逗號
- 換行：**CRLF**
- 帳號字串形如：`證-台中-0230867-林冠穎`

### 5.2 成交回報欄位（明細布局）

```
帳號,成交時間,交易類別,委託條件,股票名稱,成交數量,成交單價,成交價金,盤別
```

關鍵發現：

1. 匯出檔**已是明細布局**（非摘要）。
2. **成交時間在帳號後面的第二欄**。
3. API 成交時間對應 **`ExcReport.TransactTime`**。

### 5.3 委託欄位（較難完全一致）

桌面參考表頭（17 欄）：

```
筆數,帳號,狀態,委託書號,盤別,交易類別,委託條件,股票名稱,原委託,價格,取消,成交,剩餘,來源別,委託時間,有效日期,詳細
```

難點：

- **狀態中文**（例如「完全成交」「委託取消」）需自 API 狀態碼／`ExecType` 做對照表。
- **費用相關欄**與桌面字串格式（手續費、交易稅、百分比）在對帳單／已實現損益也需中文化與格式化。
- **來源別**桌面常見 `XQTrade`；API 未必直接給相同字串。
- **結論（已核准）：** 狀態文字與費用欄的**中文轉換／對照映射可以做**；即使如此，**委託狀態文字與費用欄仍是最難做到與桌面匯出 byte-for-byte 完全一致**的部分。目標改為「欄位齊全、語意正確、盡量贴近參考檔」，而非保證與手動匯出逐位元相同。

### 5.4 已核准事項

- ✅ 狀態文字中文化轉換
- ✅ 費用欄中文化／格式對照
- ✅ 成交檔必須使用明細布局（含 `成交時間` ← `TransactTime`）

---

## 6. 試拉結果（Trial Pull Result）

時間：2026-10-28 約 13:44（Asia/Taipei）  
模式：**僅預覽，不寫檔、不覆蓋任何資料**  
目標：拉取台中帳 `0230867` 當日委託／成交明細

| 步驟 | 動作 | 結果 |
|------|------|------|
| 1 | OS 相容性 | ❌ 主機為 Linux，非 Windows |
| 2 | `pip install conrich` | ❌ `No matching distribution found for conrich` |
| 3 | `import conrich` | ❌ `ModuleNotFoundError` |
| 4 | 檢查登入 secrets | ❌ 環境無 Concord ID／密碼 |
| 5 | `login` + `OrderReportEvent` + `order_recover` | ⏭ 未執行（被上述錯誤擋住） |

- **取回列數：** `0`
- **是否存檔：** 否（依指示 preview only）
- **根因摘要：**
  1. Cloud Agent 為 Linux，conrich 需要 Windows + .NET  
  2. 本環境沒有康和登入憑證  
  3. 因此無法取得任何原始回報列供核對

---

## 7. 下一步（Next Step）

1. **改在本機 Windows** 建立／啟動新的 **Local Cursor Agent**（含 .NET 4.5+、Python、康和金好康／conrich）。
2. 由呼叫端提供康和登入憑證，以 **本機安全方式** 注入（勿提交到 GitHub）。
3. 向營業員確認台中帳的正確 `branch_no`，帳號使用 `0230867`。
4. 實作收盤批次腳本順序建議：
   1. `login`
   2. 註冊 `OrderReportEvent` → `order_recover` → 組出委託／成交（明細含 `TransactTime`）
   3. `history_delivery` → 對帳單
   4. `realized_profit` → 已實現損益
   5. 依參考 CSV 做中文狀態／費用映射與 CP950/CRLF 輸出
   6. **先 preview 印出欄位與樣本列**，經人工確認後再寫入 `data/YYYY-MM-DD/`
5. API 申請若尚未完成：先走營業員申請＋風險預告，預留約 5–10 營業日。

---

## 附錄 A — 建議最小預覽腳本流程（Windows）

```text
1. 讀取 CONCORD_IN_NO / CONCORD_PWD / CONCORD_BRANCH_NO / CONCORD_ACCOUNT_NO
2. agent.login(in_no, pwd)
3. 註冊 OrderReportHandler（收集 ExcReport / 委託狀態）
4. agent.order_recover(branch_no, account_no)
5. 等待回補完成 → 印出 raw fields + sample rows（不寫檔）
6. agent.history_delivery(...今日...)
7. agent.realized_profit(...今日...)
8. 人工確認後，再開啟「寫出四份 CSV」開關
```

## 附錄 B — 成交明細映射速查

| 桌面欄（證券成交回報.csv） | API 來源 |
|---------------------------|----------|
| 帳號 | `ExcReport.Account`（再格式化成 `證-台中-0230867-林冠穎`） |
| 成交時間 | `ExcReport.TransactTime` |
| 交易類別 | Side／委託類別／現沖註記 → 中文（現股買進、現沖賣出…） |
| 委託條件 | TimeInForce → `ROD` / `IOC` / `FOK` |
| 股票名稱 | Symbol + 中文名 → `聯電(2303)` 形式 |
| 成交數量 | `LastQty`（注意股／張單位） |
| 成交單價 | `LastPx` |
| 成交價金 | 數量 × 單價（或 API 若另有價金欄） |
| 盤別 | LotType → `整股` 等 |

## 附錄 C — 相關連結

- conrich 總覽：<https://concords6016.github.io/conrich_docs/>
- 註冊回報：<https://concords6016.github.io/conrich_docs/tutorial/register_report/>
- 功能總表：<https://concords6016.github.io/conrich_docs/sum_chart/summarized_table/>

---

*本文件僅描述工作流程與試拉結論；不含帳密，亦不保證與桌面匯出逐位元完全相同。*
