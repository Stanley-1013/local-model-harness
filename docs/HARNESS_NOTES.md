# HARNESS_NOTES — 診斷與 TODO

診斷日期：2026-07-05。依據：實際程式碼 + `results.json` / `results_review_sample.json` 實測。

## 最浪費 token 的 3 件事

1. **DeepSeek-R1 當 critic 時整個 token 預算燒在 thinking**。實測：120 秒、正文回空字串，harness 默默接受，答案尾端出現空的 "Review notes:"。
   - 最小修法：critic 回空文時，改從 thinking 尾段撈出可用內容並標註；仍為空就明說 critic 失敗。→ **已修（harness.py）**
2. **`ask` 預設 `--strength strong`（3 次模型呼叫），但多數任務 fast（1 次）就夠**。README 自己也說 fast 才是實務預設。
   - 最小修法：`ask` 預設改為 `fast`，要 critique 再手動加 `--strength review/strong`。→ **已修**
3. **coder 模型每次都輸出長篇 Explanation 章節**，rubric 反而扣分（review 樣本就因不夠 concise 被扣到 4.0）。
   - 最小修法：code 模式 system prompt 加一句「不要附長篇解說章節」。→ **已修（system_for）**

## 最容易讓模型失焦的 3 件事

1. **關鍵字路由太寬**：英文含 "why" 一律進 reasoning（R1），"test" 一律進 code。
   - 修法：只記錄不改。關鍵字路由本來就粗糙，改複雜不划算；用 `--mode` 手動指定即可。文件已寫明。
2. **短 prompt（<240 字元）一律進 quick**，難的短問題會被最弱模型接走。
   - 修法：只記錄不改。同上，手動 `--mode reasoning` 即可。
3. **critic 拿到完整原 prompt + 完整草稿卻沒有輸出格式要求**，容易寫成第二份答案而不是找錯清單。
   - 最小修法：critic prompt 要求「條列最多 5 個具體缺陷，沒有就說 no major issues」。→ **已修**

## 最容易出錯的 3 件事

1. **worker 和 judge 是同一個模型**：zh/quick 任務由 qwen3.5 作答、又由 qwen3.5 打分（自評 5/5 不可信）。
   - 最小修法：judge 自動挑一個與 worker 不同的模型（general → coder → fast 順位）。→ **已修**
2. **Ollama 沒開或 profiles.json 壞掉時直接噴 traceback**，看不出下一步。
   - 最小修法：main 捕捉並印出「下一步指令」（如 `ollama serve`、檢查 JSON）。→ **已修**
3. **heuristic 備援評分是寫死給舊 3 題的**，新題目落到 fallback 時分數無意義。
   - 最小修法：eval 項目可帶 `must_include` / `must_exclude`，fallback 改用它們。→ **已修**

## 接到現有工具（降低「又多一個東西」）

- **Claude Code**：把 `integrations/claude-code-SKILL.md` 複製成 `~/.claude/skills/lmh/SKILL.md`（每台機器裝一次）。之後在任何 session 說「用本地模型…」或提到 lmh，Claude 就會透過 `lmh` CLI 呼叫本地模型並自行驗證輸出。
- **Continue（VS Code）**：不經 harness，直接在 Continue 設定加 Ollama provider——chat 用 `qwen3.5:4b`，tab 自動補全用 `qwen2.5-coder:7b-instruct-q6_K`（模型名照 `profiles.json` 抄）。harness 的路由/critique 只在 CLI 路徑生效。
- **Codex CLI**：同理，設 OpenAI 相容端點 `http://127.0.0.1:11434/v1` + 模型名即可直連 Ollama。
- 若要讓編輯器也吃到 harness 路由，需做 OpenAI 相容 proxy（見 TODO），這次判定過度複雜、不做。

## TODO（值得做但這次不做）

- [ ] `harness.py serve`：用 stdlib 起一個 OpenAI 相容 `/v1/chat/completions`，內部走 route()，讓 Continue/Codex 指到 harness 而不是裸 Ollama。約 100–150 行，中風險，等真的需要再做。

- [ ] R1 的 `think: false` 在目前 Ollama 版本沒生效（thinking 欄位仍有內容）。升級 Ollama 後重測；若仍無效，考慮 reasoner 換成非 think 型號或加大 `num_predict`。
- [ ] 路由改為「用 fast 模型做一次分類呼叫」取代關鍵字——收益不確定、多一次呼叫，先不做。
- [ ] eval 加自動迴歸比較（跟上次 results 比 diff）——手動看即可，暫不值得。
- [ ] `results_*.json` 會被整包覆寫，無歷史版本。要留歷史就 `--out results_YYYYMMDD.json`。

## 換模型 / 換機器時的重新配置流程

1. `ollama pull` 新模型。
2. 改 `profiles.json` 對應角色的 `name`（其他欄位先不動）。
3. `python harness.py doctor` 確認齊全。
4. `python harness.py eval --out results_new.json` 跑一次，和舊 results 比分數與秒數。
5. 分數掉了就把角色換回去；只調 `num_predict` / `num_ctx` 再試一次。
6. VRAM 變大時參考 `docs/MODEL_SELECTION.md` 的升級表。
