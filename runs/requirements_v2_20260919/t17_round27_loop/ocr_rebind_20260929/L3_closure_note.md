# L3 缺陷（OCR key 环境复现缺口）环境侧清偿记录 · 2026-09-29

## 账本口径（必须如实写入本轮 retest 报告与 L3 closed 证据）

**本轮 L3 的清偿路径 = 本地 oMLX OCR 通道（GLM-OCR-bf16 @ 8001），与 R26 缺陷发生时的 PaddleOCR 云端路径不同径。**
本轮语料准入相关用例通过，应表述为"**经本地 oMLX OCR 通道闭合**"，不得表述为 Paddle 云端链路已修复——PADDLE_OCR_API_KEY 在本机不存在（主会话已确认本地与云端均未配置过该密钥），Paddle 云端 profile（ocr_paddle_official）保持绑定配置不变、仍因缺 key 不可用，未删除未改动。

## 处置事实链
1. 密钥来源核查（本机穷尽）：`~/.config/cms-medical-workbench/ai-runtime.env`（含 DEEPSEEK_API_KEY + WORKBENCH_AI_* 网关配置，source ~/.omp/agent/.env 含 DEEPSEEK/OPENCODE/CMS_ROUTER/MTPLX 四 key）——均无 PADDLE_OCR_API_KEY；测试与 live 两套加密凭证存储（ai_provider_secrets.json）均无 ocr_paddle_official 条目；shell 配置/keychain/launchd/zsh 历史无痕迹。主会话确认：A 方案（补 key）不可能。
2. 主会话授权 B 方案（2026-09-29）：OCR 角色改绑本机 oMLX OCR profile。
3. 改绑：`isolated_runtime/ai_role_bindings.json` ocr 角色 `ocr_paddle_official/PaddleOCR-VL-1.6` → `ocr_local_omlx/GLM-OCR-bf16`，revision 7→8；改前备份 `ai_role_bindings.json.pre-ocr-rebind-20260928`（只增不删）。
4. 重启：经 `start_5301_round27.sh` 重启 5301（新 PID 49963），预检如实告警 5 个云端 key 未导出（与改绑前一致），启动后健康。
5. 验证：OCR 视觉探针两次通过（读图校验码 "CMS VISION 7429"，首次 11.06 s 含冷加载，翻译模型调用后复测 0.40 s）；翻译探针（dawncr0w）通过。证据见本目录 JSON 文件与 mem_probe.md。
6. 产品代码零改动：本次仅改 isolated_runtime 运行时配置文件；前后端构建指纹不变（api-a8a3f1a2bf2430a1）。

## 对测试者的含义
- 语料准入→翻译→例外放行→生成→导出链路本轮**具备复测条件**（OCR 走本地通道，无需云端 key）。
- R26-QA P0-1（OCR key 缺失阻断）在本地通道口径下不再复现；若需回归 Paddle 云端行为，仍属环境缺口（key 未配置），不构成本轮产品缺陷。
