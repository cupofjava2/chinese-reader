# 中文文字閱讀器

貼上一段中文，程式會依中文標點**自動分句**。點擊任何一句，就用普通話讀出來。
速度可調，亦有**跟讀模式**——讀完一句停一停，讓你跟著練習發音。

為練習普通話而做：寫好稿之後，先聽一句、跟讀一次，再逐句練下去。

<!-- 建議放一張截圖：把圖片存成 docs/screenshot.png，再把下面這行取消註解 -->
![介面截圖](docs/screenshot.png)

---

## 特色

- **自動分句** — 依中文標點（`。！？；…`）切分，正確處理引號黏合、小數點、單雙省略號
- **點句即讀** — 點擊句子用普通話朗讀，支援簡體與繁體
- **速度可調** — 0.5× 至 2.0×
- **跟讀模式** — 每句之間停頓指定秒數，附倒數提示
- **連續朗讀** — 由第一句未讀的接續朗讀，可隨時暫停／停止
- **繁簡轉換** — 一鍵在簡體／繁體之間切換（只影響顯示，不影響發音）
- **複製** — 複製全文，或右鍵單句複製
- **字級可調** — 14–28pt
- **兩種語音引擎** — 離線系統語音，或音色較自然但需網絡的 neural 語音

## 安裝

需要 [Python 3.9+](https://www.python.org/downloads/)。
依賴管理用 [uv](https://docs.astral.sh/uv/)——佢會自動開好虛擬環境、鎖定版本，唔使手動 pip。

### 1. 安裝 uv

```sh
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或者用 Homebrew
brew install uv
```

Windows（PowerShell）：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

> 冇裝 Python 都得——uv 會自動下載合適嘅版本。

### 2. 下載程式

```sh
git clone https://github.com/cupofjava2/chinese-reader.git
cd chinese-reader
```

### 3. 裝依賴 + 啟動

```sh
./run.sh
```

`run.sh` 會自動做齊兩件事：`uv sync --extra edge` 建立 `.venv` 裝齊依賴，
然後啟動 server（預設 port 5000）。開瀏覽器去 <http://127.0.0.1:5000> 就得。

會裝三個依賴：

| 依賴 | 用途 | 必需？ |
|---|---|---|
| `flask` | web 後端 | ✅ 必需 |
| `opencc-python-reimplemented` | 繁簡轉換 | ✅（缺咗自動降級為唔轉換） |
| `edge-tts` | edge 引擎（音色較自然） | 選用（`--extra edge` 裝） |

> 程式只綁定 `127.0.0.1`，僅限本機存取，不會暴露到網絡。

### 其他用法

```sh
./run.sh 5050                          # 換 port（macOS AirPlay 接收器霸咗 5000 時用）
uv sync --extra edge                   # 只裝依賴唔啟動
uv run python app.py 5000              # 手動啟動
```

### Windows

先裝 [Git](https://git-scm.com/downloads/)（要 `git clone` 就得）。
PowerShell 或 Git Bash 執行同樣的 `./run.sh`；若 shell 唔支援 `./run.sh`，用：

```sh
uv sync --extra edge
uv run python app.py 5000
```

### 更新

```sh
git pull
uv sync --extra edge
```

`uv sync` 會照 `uv.lock` 對齊版本。**更新後記得重新 `uv sync`**，
唔係啱 `git pull` 就會用到新嘅依賴（例如下面嘅 edge-tts 403 問題）。

## 語音引擎

| 引擎 | 平台 | 離線 | 音色 |
|---|---|---|---|
| `say` — macOS 系統語音 | macOS | ✅ | 中等 |
| `edge` — edge-tts | 全平台 | ❌ 需網絡 | **自然**（14 個中文音色） |

`run.sh` 會一併安裝 edge 引擎。**沒網絡時不會出錯**——edge 引擎會顯示為不可用，
程式自動只用系統語音。

edge-tts 會把文字送到微軟的線上服務，**請勿用於敏感內容**。

### edge 引擎的 403 錯誤

`edge` 引擎會突然完全唔出聲，log 見到
`aiohttp.client_exceptions.WSServerHandshakeError: 403`——
呢個**唔係網絡問題**，係微軟改咗驗證方法。

**原因**：Edge 線上語音服務每次連線都要驗證一個 token（`Sec-MS-GEC`）。
2026 年 10 月，微軟改用 **Sec-MS-GEC v2** 格式並強制執行；
但 `edge-tts` 要到 **7.3.0**（2026-10-13）先支援 v2。
用 7.2.x 或更舊嘅版本，握手會因為送錯 token 而被拒絕（403）。

點樣分辨邊個問題：

| 症狀 | 原因 |
|---|---|
| 語音清單正常，一朗讀就 403 | token 驗證失敗 → **edge-tts 版本過舊** |
| 語音清單都攞唔到 | 網絡／DNS 問題 |
| 引擎選單顯示「不可用：版本過舊」 | 程式預檢到，直接照提示更新 |

**解決**：升級 edge-tts（本專案已要求 `>= 7.3.1`）

```sh
uv sync --extra edge --upgrade-package edge-tts
```

程式會喺啟動時預檢 token 版本，過舊就把 edge 引擎喺選單標示為不可用並附上更新指令，
唔會等到朗讀先爆 403。將來微軟再改 token 格式亦一樣處理。

### 關於 macOS 語音清單

macOS 的 `say -v ?` 會列出「支援」中文的語音，但新型語音（Eddy／Flo／Rocko…）
未必已下載中文語音資料，揀了會讀不出中文。本程式會掃描系統實際的語音資料，
只列出真係讀得到中文的語音。

## 測試

```sh
uv run python test_splitter.py   # 分句邏輯 17 項
uv run python test_server.py     # 後端整合 34 項（需要先啟動 server）
node test_ui.js                  # 前端邏輯 26 項（建議先啟動 server）
```

`test_server.py` 與 `test_ui.js` 會實際發出語音，運行時有聲音屬正常。

## 設計說明

**為什麼不需要 WebSocket？** `/api/speak` 會「阻塞到語音讀完」才回應，
所以「收到回應」就等於「這句讀完了」。前端據此推進度與高亮，
無需事件流，也不會有同步錯位。

**停止為什麼要世代計數？** 使用者連點句子時，「停止舊句」和「開始新句」會同時發生。
單靠鎖會出現「停止指令剛好殺掉新句」的競態，因此每次停止會遞增世代號，
朗讀中的句子若發現世代已變，就知道自己被取代並立即退出。

**為什麼要預檢 edge-tts 版本？** 微軟的線上語音服務會定期更換驗證 token，
舊版 edge-tts 會被拒絕。預檢可以喺介面直接話你知要更新，
好過等朗讀失敗先一堆不明所以嘅 `403`。

## License

MIT — 見 [LICENSE](LICENSE)。
