# Local Model Harness

本機 Ollama 多模型協調器：按任務類型路由到不同小模型，可選 critique/修訂流程，附小型評測集。

建議位置：`~/.local_model_harness`（Windows 即 `$env:USERPROFILE\.local_model_harness`）。無外部依賴，只需 Python 3.9+ 與 Ollama。

## 新機器安裝（遷移）

1. `git clone https://github.com/Stanley-1013/local-model-harness` 到上述位置
2. 照 `profiles.json` 逐一 `ollama pull <模型名>`（或先把角色換成新機器要用的模型）
3. 讓 `lmh` 短指令可用：
   - Windows：把安裝目錄加入使用者 PATH（repo 已含 `lmh.cmd` / `lmh.ps1`），新開的終端機才生效
   - Linux / macOS：`alias lmh='python ~/.local_model_harness/harness.py'`
4. `lmh doctor` 確認齊全 → `lmh eval` 建立這台機器的基準分數
5. 硬體不同時，照 `docs/MODEL_SELECTION.md` 的 VRAM 級距換角色模型，並更新 `profiles.json` 的 `hardware_note`

## 常用指令

（`lmh` 未設定時，用完整寫法 `python ~/.local_model_harness/harness.py ...` 代替）

```powershell
lmh doctor                # 健康檢查：Ollama 連線 + 模型齊全度 + 角色分工
lmh 你的問題               # 直接問（等同 lmh ask ...，預設 fast = 單次呼叫）
lmh chat                  # 互動模式；/exit 離開，/mode、/strength 可切換
lmh ask --strength strong --mode code "寫一個..."   # 高價值任務才用 review/strong
lmh eval --out "$env:USERPROFILE\.local_model_harness\results.json"   # 換模型後必跑
```

注意：`chat` 每輪獨立、**沒有多輪記憶**（要接續請把上下文貼進同一則問題）。
若 `lmh` 找不到指令：重開終端機（PATH 是使用者層級，新視窗才生效）。

## 路由規則（auto 模式）

| 任務 | mode | 用的角色 |
|---|---|---|
| 程式碼相關關鍵字 | code | coder |
| 推導/證明/為什麼 | reasoning | reasoner |
| 摘要/改寫/翻譯或短 prompt | quick | fast（中文則 general） |
| 其他 | general | general |

路由是關鍵字比對，會誤判；不對就手動 `--mode code|reasoning|quick|general`。
選模型的細節規則見 `docs/MODEL_SELECTION.md`。

## 接到其他工具

- **Claude Code**：已有 skill（`~\.claude\skills\lmh\SKILL.md`），對 Claude 說「用本地模型…」即可。
- **Continue / Codex**：直接把它們指到 Ollama（`http://127.0.0.1:11434`），模型名照 `profiles.json` 抄；細節見 `docs/HARNESS_NOTES.md`。

## 看目前分工 / 換模型

分工設定全在 `profiles.json`：每個角色（fast / general / coder / reasoner / embed）一個 `name`（Ollama 模型名）+ `options`。

換模型三步：
1. `ollama pull 新模型`
2. 改 `profiles.json` 該角色的 `name`
3. `doctor` 確認 → `eval` 比分數（流程細節見 `docs/HARNESS_NOTES.md` 末段）

## 出錯先看哪裡

1. 先跑 `doctor`。連不上 → 開 Ollama（`ollama serve` 或桌面版）；缺模型 → 照提示 `ollama pull`。
2. 答案品質差 → 看 `ask --json` 輸出的 `calls`，確認路由到哪個模型、各花幾秒。
3. critic 空白或很慢 → 見 `docs/HARNESS_NOTES.md`（R1 thinking 燒 token 問題）。
4. profiles.json 改壞 → 錯誤訊息會指出問題；還原用 `profiles.json.bak.*`。

## 8GB VRAM 級距建議（原調校機：RTX 3070 Laptop）

- 一次只常駐一個 4B–8B 模型；harness 已是循序呼叫，不要自己並行跑多個。
- 預設用 `--strength fast`；`review`/`strong` 只給高價值任務（實測 strong 約 3–5 倍時間）。
- reasoner（DeepSeek-R1 8B）最重最慢，且 thinking 會吃掉輸出預算——非必要不用。
- 換更大 VRAM 的升級順序見 `docs/MODEL_SELECTION.md` 末段。

## 檔案

- `harness.py` — 主程式（doctor / warm / ask / chat / eval）
- `lmh.cmd` / `lmh.ps1` — `lmh` 短指令包裝（Windows；把本目錄加入 PATH 後生效）
- `integrations/claude-code-SKILL.md` — Claude Code 整合用的 skill 範本（安裝方式見檔頭）
- `profiles.json` — 角色→模型設定與路由關鍵字
- `eval_set.json` — 小型評測集（7 題，涵蓋中文遵循、code、JSON、找錯、不亂猜）
- `docs/MODEL_SELECTION.md` — 模型選擇與升級規則
- `docs/HARNESS_NOTES.md` — 診斷、已知問題、TODO、換模型流程
- `results*.json` — 評測結果（會被覆寫；要留歷史請換檔名）
