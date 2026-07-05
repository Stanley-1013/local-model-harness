# MODEL_SELECTION — 模型選擇規則

規則寫給小模型和未來使用者直接照做。角色名對應 `profiles.json` 的 key，模型可換，規則不變。

## 各角色適合做什麼

- **fast**（現為 Gemma 3n E2B）：英文短改寫、分類、格式轉換、一句話回答。不要給它中文長句或任何需要推理的事。
- **general**（現為 Qwen3.5 4B）：中文任務、摘要、日常問答、當 final editor。是「不知道給誰就給它」的預設。
- **coder**（現為 Qwen2.5-Coder 7B）：寫程式、改 bug、產生測試。只給它程式任務；它會過度解說，prompt 裡要求「只給 code + 一句說明」。
- **reasoner**（現為 DeepSeek-R1 8B）：多步推理、數學、當 critic 找錯。最慢、thinking 會吃輸出預算，非必要不用；期待長答案時把 `num_predict` 開大。
- **embed**（現為 Nomic Embed）：只能做向量/相似度搜尋。**不能**生成文字、不能回答問題、不能打分。任何「請 embed 模型回答」都是配置錯誤。

## 升級 / 重試 / 換策略判斷

照順序判斷，符合就停：

1. **答案含具體可驗證錯誤（code 跑不動、算錯）**→ 不要同模型重試，升一級：fast→general→coder/reasoner。同模型重試多半得到同樣的錯。
2. **答案空白或明顯沒讀懂指令** → 換策略：把 prompt 拆短、給範例輸出格式，再用同級模型試一次；還是不行才升級。
3. **答案看起來對但屬於高風險（會執行的 code、對外文件、數字結論）** → 一律加 `--strength review` 讓第二個模型找錯，不要相信單模型輸出。
4. **模糊方向、高品味寫作、開放式研究、缺上下文的任務** → 本地小模型不可靠。明說不確定，升級到雲端強模型或請使用者補充目標。不要讓小模型假裝能解。
5. **同一任務失敗兩次** → 停。記下失敗樣態，不要第三次。

## 驗證規則

- **worker 和 verifier/judge 不要用同一個模型**。自己打自己的分不可信（harness 的 eval judge 已自動避開）。
- critic 的產出要是「條列缺陷」，不是重寫一份答案；critic 回空白視同 critic 失敗，不算通過審查。

## VRAM 規則

- **8GB（現況）**：同時只常駐 1 個 4B–8B 模型。頂配大約就是 7B Q6 / 8B Q4；不要嘗試常駐兩個 7B+。
- **12GB**：coder 可升 14B 級（如 Qwen-Coder 14B Q4）；其餘不動。coder 是投報率最高的升級位。
- **16GB**：coder 14B Q6 或 general 升 14B 級；可以讓 fast+general 同時常駐。
- **24GB**：general/reasoner 可上 32B Q4，此時 reasoner 才真正值得常用；fast 角色可考慮直接併入 general。
- 換任何模型後：`doctor` → `eval` → 跟舊 results 比分數和秒數，掉分就回退（流程見 HARNESS_NOTES）。
