# Protocol v3 模型路由阶段复盘（2026-09-23）

## 本阶段范围

本阶段只处理“综合 AI 的模型选择与故障切换”这一条横切能力，并把它接到已经存在的三类真实入口：竞品分诊、企业语料分析，以及本批完成的事实提取/写作预填。没有启动新的全文生成、检索、下载、OCR、翻译、浏览器或 Word 验收。

## 完成结果

- 模型顺序由设置中的主模型和 fallback 链决定；源码不再把单一 provider 写死在上述入口。
- 每条路由保留自己的 provider、model、thinking 和 reasoning effort。实际成功后记录真正使用的 provider/model；事实提取还记录链 ID、层级和切换原因。
- 只有 408、429、500、502、503、504、传输失败和空响应会切换到下一条路由。400、鉴权/配置错误、无效内容和模型身份不符会直接显式失败。
- 每条路由只做一次底层请求，避免“一个 provider 内重试数次后又整链重试”造成不可控等待。
- 没有可用模型时，写作预填仍可回到确定性预填，不把整个页面打成 500。
- 原有无 fallback 的冻结任务保持旧身份和去重规则，历史记录未被改写。

## 会商带来的实质修正

独立 reviewer 首轮找到了五个真实问题，说明仅靠主线程阅读还不足以关闭这一批：

1. HTTP 200 但正文为空时，模型身份检查可能先报错，导致本应切换却没有切换。
2. 写作预填设置的长超时只写到了 wrapper，没有传给链内 provider。
3. 没有可用链时，写作预填可能从原来的温和降级退化为 500。
4. wrapper 类型可能让任意 provider 获得“身份已验证”的信任。
5. 同一 wrapper 再次运行时可能保留上次 fallback 状态。

这些问题均已修复。同一 ZCode/GLM-5.3-Flash:max session 连续复核三轮，最终没有剩余发布阻断项。会商总计 3 次模型调用，未 fallback。

## 测试与证据

- 交互路径集中矩阵：297 passed。
- `tests/protocol_v3`：2608 passed，只有 1 条 Python tar 未来版本 deprecation warning。
- Python 编译和 `git diff --check` 通过。
- conference review gate 与 validate-conference 通过。
- MTPLX 11234 未监听，因此没有把本地模型的真实响应质量写成已验证。

## 踩到的坑

- 测试环境差异会制造假象。reviewer 用系统 Python 时一批 API 测试因导入路径和 Python 版本不能运行；回到项目锁定 venv 与完整 PYTHONPATH 后，相关矩阵 297 项全部通过。
- 三条失败测试不是新实现造成的：一个仍期待旧 32768 token 上限，两个仍固定旧 full-draft v0.9。升级到当前 65536/v0.11 后，还必须同步补上 v0.11 的 `gap_items` 合同，不能只改版本字符串。
- fallback 的“能切换”不等于“切换原因正确”。空响应分类顺序和 wrapper 超时传播必须单独验证，否则表面上链路工作，实际可能因错误原因迁移。
- 当前运行目录存在大量历史制品、备份和未提交运行时状态。收尾时采用精确文件清单提交，未使用 `git add .`、reset 或 clean。

## 尚未完成

- MTPLX `Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed / medium` 的 endpoint identity、真实生成质量和长文本稳定性。
- WP6 中剩余真实模型完整旅程、宽屏浏览器、原生 Word 保存重开、逐章医学/统计/安全接受，以及 A/V/B 验收矩阵尚未全部关闭。
- authoring prefill 只记录实际 provider/model，尚未与 fact intake 一样保存完整 fallback depth/reason/profile/chain 四字段；全链失败也只暴露最后一个明确错误。两项均是可审计性增强，不影响本批正确输出。
- 顶层准备阶段仍有一条旧测试期待“每批暂停”，与当前自动连续排空设计冲突；另有全仓环境债包括可选 `jsonschema` 和已删除历史翻译脚本，不在本批恢复。

## 下一阶段建议

恢复时先核对 HEAD、Trellis、dirty 与 11234 是否监听。若 MTPLX 可用，先做一次 exact model identity、空响应和结构化长输出探针；若不可用，不阻断其余 WP6。随后继续 V01/V04/V06/V07 和三研究完整“资料→推荐→确认→初稿→当前 Word→下载”旅程，集中按失败族修复，再完成浏览器、原生 Word 和逐章医学接受。不要重放旧 v0.9、9 月 21 日 source overlay、检索/分诊/下载/OCR/翻译或五个历史失败项。
