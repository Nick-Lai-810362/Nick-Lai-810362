# TSGEX Bitfinex USD 保證金放貸自動化機器人 — 完整使用說明書

版本對應：`tsgex_bfx_bot` v5.6.0（對應 CHANGELOG.md v5.6）
適用對象：TSGEX 資產管理部與其他實際操作 / 維護此工具的人員

---

## 目錄

1. [這個工具是什麼](#1-這個工具是什麼)
2. [三個組成部分](#2-三個組成部分)
3. [安裝與需求](#3-安裝與需求)
4. [快速開始](#4-快速開始)
5. [核心概念](#5-核心概念)
6. [五種放貸模式](#6-五種放貸模式)
7. [完整 CLI 參數對照表](#7-完整-cli-參數對照表)
8. [安全機制](#8-安全機制)
9. [本地端網頁儀表板](#9-本地端網頁儀表板)
10. [離線 Artifact 儀表板](#10-離線-artifact-儀表板)
11. [匯出歷史紀錄 CSV](#11-匯出歷史紀錄-csv)
12. [實際上線部署流程](#12-實際上線部署流程)
13. [模組架構（給維護者）](#13-模組架構給維護者)
14. [已知限制與研究結論摘要](#14-已知限制與研究結論摘要)
15. [疑難排解](#15-疑難排解)

---

## 1. 這個工具是什麼

一個獨立開發的 Bitfinex `fUSD`（USD 保證金放貸）自動化出借機器人，行為設計參考 Fuly.ai **公開文件揭露**的策略手法（IBRR/FBRR 概念、階梯式掛單、多天期配置），但所有實際數字與門檻都是用**真實 Bitfinex 資料**（5 年逐小時利率歷史、近萬筆真實成交紀錄）重新推導、回測、驗證過的，不是照抄假設。凡是無法用真實資料驗證的地方（例如掛單簿深度、真實成交延遲），文件與程式碼註解都會明講「這是揭露的推測，不是量測值」。

**這不是一個「保證獲利」的黑盒子。** 它是一個把「該掛多少錢、掛在哪個天期、多久該撤單重掛」這幾件事自動化、且全程可稽核（JSON-lines 稽核日誌）的工具。是否要接上真實金流、投入多少資金，仍然是人的決策。

---

## 2. 三個組成部分

| 部分 | 檔案 | 用途 | 是否需要網路/API金鑰 |
|---|---|---|---|
| **放貸機器人本體** | `tsgex_bitfinex_lending_bot.py` | 實際讀取利率、決定配置、下單、記帳的核心程式 | `--mock` 不需要；`--live` 需要 |
| **本地端儀表板** | `tsgex_bitfinex_dashboard.py` | 資產總覽／掛單詳情／出借歷史／收益年化，可即時對接 Bitfinex API，支援多子帳號切換 | `--mock` 不需要；接真實帳戶需要 API 金鑰 |
| **離線 Artifact 儀表板** | `reports/TSGEX_Bitfinex_Bot_Dashboard.html`（獨立於本套件） | 上傳 `bfx_bot_state.json` 或匯出的 CSV，離線瀏覽同樣四個分頁，不需要跑任何本地程式 | 完全不需要，純瀏覽器 |

三者共用同一套帳本格式（`bfx_bot_state.json`）與同一套分析邏輯（機器人本體用 Python 的 `analytics.py`，離線 Artifact 用對應的 JavaScript 版本），數字算法是一致的。

---

## 3. 安裝與需求

```bash
# Python 3.8+，無需安裝任何第三方套件即可執行機器人本體、儀表板伺服器
cd tsgex_bitfinex_bot
python tsgex_bitfinex_lending_bot.py --help

# 若要跑 research/ 底下的回測腳本，需要：
pip install pandas numpy

# 若要跑測試（開發/維護用）：
pip install pytest
pytest   # 或直接在此目錄下執行，pyproject.toml 已設定 pythonpath
```

不需要 Docker、不需要資料庫、不需要任何雲端服務。狀態全部存在本機的 JSON 檔案裡。

---

## 4. 快速開始

```bash
# 1. 完全不需要 API 金鑰或網路，用模擬資料看整個流程如何運作
#    時鐘會用 --mock-days-per-cycle 快轉，讓部位在短時間內真的成交、到期
python tsgex_bitfinex_lending_bot.py --mock --contribute 158730 --mode dave_high \
    --cycles 10 --mock-days-per-cycle 3

# 2. 同時打開儀表板看剛剛跑出來的帳本（另開一個終端機視窗）
python tsgex_bitfinex_dashboard.py --mock
# 瀏覽器打開 http://127.0.0.1:8765/

# 3. 只想單純看即時市場利率、不下真實單（dry-run，需要網路，不需要金鑰）
python tsgex_bitfinex_lending_bot.py --contribute 158730 --mode barbell

# 4. 匯出完整部位歷史成 CSV
python tsgex_bitfinex_lending_bot.py --export-csv history.csv

# 5. 真正上線下真實單（詳見第 12 節，務必先完成前置設定）
python tsgex_bitfinex_lending_bot.py --live --mode dave_high
```

---

## 5. 核心概念

### 5.1 天期（Tenor）與利率單位
- Bitfinex 放貸天期可以是 2～120 天中的任意整數天，但真實成交量高度集中：**2 天期佔約 89.6% 成交筆數、96% 以上成交量**；30 天期約 1%；120 天期僅 0.11%（來自近萬筆真實成交紀錄的統計）。
- 送到 Bitfinex API 的 `rate` 欄位是**日利率**（不是年化、也不是每小時利率——這點在研究階段特別重新查證過三個獨立來源確認）。程式內部一律先換算成年化（`daily_rate × 365`）再做決策與顯示。
- **毛年化 vs 淨年化**：Bitfinex 對放貸「利息收入」（不是本金）抽成——標準掛單 15%、隱藏掛單 18%。所有決策（是否要放貸、要不要換天期）都是用淨年化（扣完手續費後）在判斷，不是用掛牌的毛利率。

### 5.2 本金／利潤帳本
機器人會分開追蹤「本來投入的本金」跟「已實現的利潤」，利潤拿去複投時仍然標記成利潤（不會因為滾入下一輪而被誤記成本金），這樣才能隨時回答「我到底賺了多少、本金還剩多少」。

### 5.3 部位生命週期
```
pending（已送出掛單，本金已從閒置資金扣除，但尚未開始計息）
   ├─→ active（已成交，天期與利息從「成交當下」開始算，不是從送出掛單那一刻）
   │      └─→ matured（到期，本金歸還閒置資金池，利息計入已實現利潤）
   └─→ cancelled（撤單重掛：等太久沒成交，或市場利率偏離太多，撤單後立刻用新利率重新送出）
```
這個生命週期是刻意設計的：真實 Bitfinex 掛單不是送出去就馬上生息，必須先等有人來借才會成交。

### 5.4 動態天期配置
`custom` / `dave_high` 模式不是固定「30% 放 2 天、70% 放 30 天」這種寫死的表格，而是**每個週期重新讀取當下真實利率**，只有在「當下」觀察到的長天期溢價（gap）超過門檻（`--term-premium-min-pp`）時才會把部分資金移過去，並且：
- 有上限（`--max-total-shift-from-short`，預設 0.7）：最短、流動性最好的天期永遠留住至少 30% 的資金，不會被完全掏空。
- 有深度過濾（`--min-period-depth-usd`）：某個天期當下的掛牌簿深度太薄（可能只有一兩張單），不管利率多誘人都不會把資金押過去，因為真的填不進去。

---

## 6. 五種放貸模式

透過 `--mode` 指定：

| 模式 | 中文名稱 | 行為 |
|---|---|---|
| `dave_high`（預設） | 戴夫高利模式 | 全自動多天期配置（見 5.4），外加一個「動量訊號」保留機制——**預設關閉**，因為用 5 年真實資料回測後發現這個訊號的方向剛好是反的（見第 14 節）。 |
| `dave_fast` | 戴夫極速模式 | 只掛一張單、掛在當下最容易成交的最短天期、用最有競爭力（最低）的利率，犧牲一點利率換取幾乎立即成交。 |
| `custom` | 自訂 | 跟 `dave_high` 幾乎一樣的多天期配置邏輯，但不含動量保留機制，是最單純、最可預期的自動模式。 |
| `frr` | FRR 浮動模式 | 掛單釘住 Bitfinex 自己的 Flash Return Rate（FRR，每小時浮動更新），不用自己猜利率。 |
| `barbell` | 槓鈴模式 | 資金一半放最短天期（流動性）、一半放較長天期（追求溢價），透過 `--barbell-short-fraction` 調整比例。 |

**倒金字塔階梯掛單**（所有模式共用，除了 `dave_fast` 的單一張掛單）：把要放的資金拆成好幾張、金額遞增、利率也遞增的掛單，模仿 Fuly 公開文件的範例（利率越沒競爭力的檔位掛越大量），而不是全部資金賭在一個利率猜測上。拆法有兩種（`--tranche-sizing-mode`）：
- `calibrated`（預設）：張數由「該天期真實成交量校準出的典型單量」反推，資金越多、張數自然越多。
- `fixed_count`：直接指定要同時掛幾張（`--max-concurrent-orders`），資金平均分配，會自動避免單張低於 Bitfinex 最低下單金額（$150 美元）。

---

## 7. 完整 CLI 參數對照表

執行 `python tsgex_bitfinex_lending_bot.py --help` 可看到即時版本；以下是各參數的意義與預設值。

### 基本設定
| 參數 | 預設 | 說明 |
|---|---|---|
| `--symbol` | `fUSD` | 放貸幣別 |
| `--mode` | `dave_high` | 見第 6 節 |
| `--floor-rate` | `0.05` | 淨年化低於此門檻就不放貸（持有現金） |
| `--reserved-amount` | `0.0` | 永遠保留不出借的金額 |
| `--contribute` | `0.0` | 本次執行前，先把這筆金額計入累計投入本金 |

### 天期配置（`custom`/`dave_high`/`barbell`）
| 參數 | 預設 | 說明 |
|---|---|---|
| `--term-premium-min-pp` | `0.02` | 長天期溢價要超過幾個百分點才會分配資金過去（0.02 = 2pp） |
| `--max-total-shift-from-short` | `0.7` | 最多可以把短天期配置的幾成移到長天期（合計） |
| `--min-period-depth-usd` | `1000.0` | 該天期掛牌簿深度低於此值就不考慮 |
| `--authorize-extreme-tenor` | 關閉 | 允許考慮 30 天以上的極端天期（實測 120 天沒有比 30 天多賺，預設關閉） |
| `--barbell-short-fraction` | `0.5` | `barbell` 模式短天期佔比 |

### 掛單張數與大小
| 參數 | 預設 | 說明 |
|---|---|---|
| `--tranche-sizing-mode` | `calibrated` | `calibrated`（依真實成交量校準）或 `fixed_count`（固定張數平分） |
| `--max-concurrent-orders` | `20` | 僅 `fixed_count` 模式使用：同時掛幾張 |
| `--max-orders-per-cycle` | `400` | 僅 `calibrated` 模式使用：張數上限（非 Bitfinex 限制，只是保護機制） |

### 撤單重掛
| 參數 | 預設 | 說明 |
|---|---|---|
| `--max-wait-multiplier` | `1.0` | 縮放各天期預設的「等待多久算太久」門檻（2d:6h／7d:24h／30d:72h／120d:120h），大於1更有耐心、小於1更早撤單重掛 |
| `--rate-drift-threshold-pp` | `0.01` | 掛單利率跟當下市場利率偏離超過此值（不論漲跌）就撤單重掛，1pp = 0.01。**不要設低於 0.01**，實測太緊會頻繁觸發撤單重掛、反而拉低資金真正在生息的比例（詳見第 14 節） |

### 進階/風險相關
| 參數 | 預設 | 說明 |
|---|---|---|
| `--enable-spike-reserve` | 關閉 | `dave_high` 專用的動量保留訊號，**已用真實資料證實方向是反的，不建議開啟**，除非你自己另外驗證過信得過的訊號 |
| `--order-visibility` | `standard` | `standard`（手續費15%）或 `hidden`（隱藏掛單，手續費18%） |

### 執行控制
| 參數 | 預設 | 說明 |
|---|---|---|
| `--live` | 關閉 | 真的下真實單（需要環境變數 `BFX_API_KEY`/`BFX_API_SECRET`） |
| `--mock` | 關閉 | 使用模擬市場資料，不連真實 Bitfinex |
| `--cycles` | `1` | 執行幾個週期 |
| `--poll-interval` | `5`（秒） | 週期之間的真實等待秒數（`--live`/dry-run 用；`--mock-days-per-cycle` 設定時不會用到這個） |
| `--mock-days-per-cycle` | `0` | 模擬模式下，每個週期讓時鐘快轉幾天，方便短時間內看到部位成交/到期 |

### 狀態與稽核檔案
| 參數 | 預設 | 說明 |
|---|---|---|
| `--state-file` | `bfx_bot_state.json` | 帳本檔案位置 |
| `--audit-log` | `bfx_bot_audit_log.jsonl` | 每個週期的決策紀錄（JSON-lines，可稽核） |

### 匯出
| 參數 | 預設 | 說明 |
|---|---|---|
| `--export-csv` | 無 | 指定路徑即匯出部位歷史 |
| `--export-tenor` | 無 | 只匯出某個天期 |
| `--export-start` / `--export-end` | 無 | 依下單時間篩選日期區間（ISO 格式，如 `2026-01-01`） |

---

## 8. 安全機制

- **預設是 dry-run**：不加 `--live` 就不會真的下單，只會印出「如果是真的會怎麼做」的紀錄。
- **`--live` 強制要求環境變數**：API 金鑰/密鑰絕對不能用命令列參數傳（會留在 shell 歷史紀錄跟行程列表裡），只能用 `BFX_API_KEY`/`BFX_API_SECRET` 環境變數。
- **最小權限強制檢查**（`governance.assert_minimal_permissions`）：`--live` 啟動時會先去問 Bitfinex 這把金鑰有沒有提領/轉帳權限，**只要有，直接拒絕執行**，不管你以為自己有沒有開那個權限。金鑰申請時只勾選「Margin Funding」讀寫，絕對不要勾 Withdraw。
- **資金位置提醒**：資金必須放在 Bitfinex 的「Funding 錢包」（不是 Exchange 錢包），機器人只看得到、也只動得到 Funding 錢包餘額。
- **關閉 Bitfinex 自己的 Lending Pro**：如果 Bitfinex 內建的自動放貸沒關，會跟這個機器人搶同一筆餘額、互相打架下單。
- **本地儀表板預設只綁 127.0.0.1**：`tsgex_bitfinex_dashboard.py` 預設拒絕綁定到 localhost 以外的位置（因為會顯示真實帳戶餘額與掛單），要對外開放必須明確加 `--allow-remote` 並自行承擔風險（例如自己包一層驗證或 VPN）。

---

## 9. 本地端網頁儀表板

```bash
# 零金鑰、零網路先試用
python tsgex_bitfinex_dashboard.py --mock
# 打開 http://127.0.0.1:8765/

# 接單一真實帳戶（跟機器人本體共用同一組環境變數）
export BFX_API_KEY=...
export BFX_API_SECRET=...
python tsgex_bitfinex_dashboard.py
```

四個分頁：**資產總覽**（累計本金、閒置資金、使用中/等待成交中金額、已實現利潤、淨值估計）、**掛單詳情**（目前 pending/active 的每一張單，若有金鑰會跟交易所目前掛單數對帳）、**出借歷史紀錄**（完整可篩選明細表，可下載 CSV）、**收益與年化報酬**（累積獲利折線圖、各天期獲利長條圖、目前使用中資金加權年化、歷史實際年化報酬）。

### 多子帳號切換
建立一個 `profiles.json`：
```json
{
  "profiles": [
    {"name": "主帳戶", "state_path": "bfx_bot_state_main.json",
     "api_key_env": "BFX_API_KEY_MAIN", "api_secret_env": "BFX_API_SECRET_MAIN"},
    {"name": "子帳戶A", "state_path": "bfx_bot_state_a.json",
     "api_key_env": "BFX_API_KEY_A", "api_secret_env": "BFX_API_SECRET_A",
     "order_visibility": "hidden"}
  ]
}
```
```bash
export BFX_API_KEY_MAIN=... BFX_API_SECRET_MAIN=...
export BFX_API_KEY_A=...    BFX_API_SECRET_A=...
python tsgex_bitfinex_dashboard.py --profiles-file profiles.json
```
**金鑰本身永遠不寫進 `profiles.json`**，檔案裡只有「環境變數的名字」，就算這個檔案外流或被 commit 進版本控制，也不會洩漏任何密鑰。切換帳戶在網頁右上角下拉選單直接選，不用重啟伺服器。

### 為什麼這是本地伺服器，不是網頁連結
claude.ai 的 Artifact 頁面（見第 10 節）的瀏覽器安全政策完全擋掉對 `api.bitfinex.com` 的請求，這是平台層級的硬限制，不是設計選擇。真正要接上即時 Bitfinex API，一定要有伺服器端（不受瀏覽器 CSP 限制）去發送簽章過的請求——這就是為什麼這個功能必須做成一個在你自己電腦上跑的本地程式。

---

## 10. 離線 Artifact 儀表板

`reports/TSGEX_Bitfinex_Bot_Dashboard.html` 是給不想安裝/執行任何本地程式的人用的輕量選項：打開就會看到一組清楚標示「範例資料」的示範帳本，上傳您自己的 `bfx_bot_state.json`（建議，資訊最完整）或舊版 `--export-csv` 匯出的 CSV，畫面會換成真實資料。同樣四個分頁、同樣的分析邏輯，但**沒有**即時 API 連線、也沒有多帳號切換——原因跟第 9 節最後一段一樣：瀏覽器層級的安全限制。

---

## 11. 匯出歷史紀錄 CSV

```bash
python tsgex_bitfinex_lending_bot.py --export-csv history.csv
python tsgex_bitfinex_lending_bot.py --export-csv q1_30d.csv --export-tenor 30 \
    --export-start 2026-01-01 --export-end 2026-03-31
```
欄位：`id, status, label, tenor_days, amount, principal_component, profit_component, daily_rate, gross_apr, net_apr, placed_ts, filled_ts, maturity_ts, matured_ts, interest_earned`。可以直接丟進離線 Artifact 儀表板，或自己拉進 Excel 做進一步分析。

---

## 12. 實際上線部署流程

1. Bitfinex 後台 → API Keys → 建立新金鑰，**只勾選 Margin Funding 讀寫**，絕對不要勾 Withdraw。
2. 把要出借的資金從 Exchange 錢包轉到 **Funding 錢包**。
3. 如果 Bitfinex 內建的 Lending Pro 自動放貸是開的，**先關掉**。
4. （建議）幫這把金鑰加上 IP 白名單限制。
5. 匯出環境變數（絕對不要寫在指令列參數裡）：
   ```bash
   export BFX_API_KEY=你的金鑰
   export BFX_API_SECRET=你的密鑰
   ```
6. 先跑一次 dry-run 確認邏輯合理（不加 `--live`，會真的連線讀真實市場資料，但不會下真實單）：
   ```bash
   python tsgex_bitfinex_lending_bot.py --contribute 158730 --mode dave_high --cycles 1
   ```
7. 檢查印出來的 `[DRY-RUN] would place:` 內容合理之後，才加上 `--live`：
   ```bash
   python tsgex_bitfinex_lending_bot.py --live --mode dave_high --cycles 1
   ```
8. 要長時間持續運作，用 `--cycles` 設一個很大的數字（或包一層 cron/systemd 定時重跑），搭配本地儀表板即時監看。

---

## 13. 模組架構（給維護者）

```
tsgex_bitfinex_lending_bot.py   機器人本體的進入點（設定 logging，呼叫 cli.main()）
tsgex_bitfinex_dashboard.py     本地儀表板的進入點（呼叫 webapp.main()）

tsgex_bfx_bot/
  constants.py     真實資料推導出的數字：典型單量、撤單等待門檻、平台手續費，每個數字都寫明來源
  config.py        StrategyConfig 設定物件 + platform_fee()/net_apr()
  ledger.py        Position/BotState，本金／利潤帳本：讀存、入金、結算、開倉/撤單、CSV 匯出
  client.py        BitfinexClient（真實 REST API 呼叫）+ extract_offer_id()
  mock_client.py   MockBitfinexClient：模擬掛牌簿與成交機率，供 --mock 使用
  governance.py    assert_minimal_permissions()：--live 前的最小權限強制檢查
  audit.py         write_audit_log()：JSON-lines 決策稽核紀錄
  strategy.py      best_rate_by_tenor()、depth_by_tenor()、decide_tenor_allocation()、
                    compute_spike_signal()、build_tranches_for_tenor()
  execution.py      place_tranche()、place_frr_tranche()、reconcile_pending_offers()（成交偵測+撤單重掛）
  runner.py        run_cycle()：把上面全部串成一個完整週期
  cli.py           argparse + main()
  analytics.py     overview()、open_offers()、history()、earnings()、apr()：儀表板背後的純函式
  profiles.py      Profile/load_profiles()/find_profile()：多子帳號設定
  webapp.py        本地端 HTTP 伺服器：同源 JSON API + 靜態頁面
  webapp_static/dashboard.html   本地儀表板的前端頁面

tests/             pytest 測試套件，每個模組一份 + test_integration.py 端對端測試（105 個測試）
research/          回測與參數掃描腳本，附完整真實資料，任何人都能重新跑一次驗證
```

---

## 14. 已知限制與研究結論摘要

這個機器人的每一個數字門檻都經過真實資料檢驗，**下面條列每一個「已經驗證過、有明確結論」的重點**（完整推導過程見 `CHANGELOG.md`）：

- ✅ **2 天期是流動性核心**：真實成交量 89.6% 集中在 2 天期，這是為什麼所有模式預設都以 2 天期為錨點。
- ✅ **120 天期沒有額外報酬**：5 年真實資料顯示 120 天期利率中位數只比 30 天期高 0.04pp（幾乎等於沒有），但流動性差 8 倍，預設排除，除非明確加 `--authorize-extreme-tenor`。
- ✅ **30 天期溢價是真實存在的，且相當大**：兩種完全獨立的方法都測出約 +3.65～3.7pp/年的差距（一次是即時利差中位數、一次是真實複利終值回測），不是雜訊。
- ❌ **「動量訊號預測利率會漲」是反的**：實測發現訊號出現時，利率接下來反而平均下跌，`--enable-spike-reserve` 因此預設關閉。
- ❌ **「用 2 天期高頻複利取代 30 天期溢價」不成立**：真實複利回測顯示 2 天期年化只有 5.60%，30 天期是 9.31%，複利頻率的優勢在放貸這種個位數利率規模下完全補不回真實利差。
- ⚠️ **撤單重掛的門檻不要設太緊**：`--rate-drift-threshold-pp` 設到 0.005 時，模擬顯示資金真正「在生息」的比例明顯變差（頻繁撤單重掛反而讓資金一直卡在等待成交狀態）。
- ⚠️ **降低 `--term-premium-min-pp` 追逐帳面高報酬是一個未驗證的賭注**：理論上門檻越低、回測出來的混合報酬越高，但那是假設每個天期都能立即成交；30 天期市場只有約 1% 的真實成交量，Bitfinex 又沒有歷史掛單簿深度 API 可以驗證真的填不填得進去，所以預設值沒有往下調。
- ⚠️ **Bitfinex 沒有歷史掛單簿/成交延遲 API**：所有跟「多久會成交」「掛單簿深度」有關的門檻（`--max-wait-multiplier`、`--min-period-depth-usd`）都是揭露清楚的合理推測，不是量測出來的真實數字，建議上線後持續用儀表板觀察實際撤單重掛頻率，必要時自行調整。

---

## 15. 疑難排解

| 現象 | 可能原因 / 處理方式 |
|---|---|
| `--live requires BFX_API_KEY and BFX_API_SECRET environment variables` | 忘記 `export` 環境變數，或是打錯變數名稱 |
| `REFUSING TO RUN: this API key has withdrawal/transfer permission` | 金鑰勾選了提領/轉帳權限，回 Bitfinex 後台建立一把只有 Margin Funding 權限的新金鑰 |
| `REFUSING TO BIND to 0.0.0.0` | 儀表板預設只給本機用，若確定要對外開放要自己加 `--allow-remote` 並理解風險 |
| 儀表板顯示「即時對帳目前無法使用」 | 該帳戶沒設對應的 API 金鑰環境變數，或網路連不到 Bitfinex——本地帳本紀錄仍然正常顯示 |
| 掛單一直被撤單重掛、遲遲不成交 | 檢查 `--rate-drift-threshold-pp` 是不是設太緊（低於 0.01 不建議），或該天期真實流動性本來就薄 |
| 想確認邏輯正確但不想連真實網路 | 一律先用 `--mock`，可以完整跑完整個成交/到期週期，不需要任何金鑰 |

---

如需更完整的研究方法與每個數字的推導過程，請見同目錄下的 `README.md`（模組地圖）與 `CHANGELOG.md`（完整版本歷史與每一次真實資料驗證的詳細記錄）。
