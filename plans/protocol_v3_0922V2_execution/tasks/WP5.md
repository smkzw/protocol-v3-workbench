# WP5 当前Word、编辑保真与宽屏体验收口
**依赖WP1–4；完成本包后进入一次集中验收，不逐项跑测试。**

文件范围：GenOfficeFrame、ManuscriptWorkspace、ProtocolWritingDesk/IntakeWorkspace与CSS；frontend/public/genoffice/bridge-shim.js；manuscript_documents/API；full_draft locator/body范围；同级genoffice-upstream的App.tsx/protocol-office.ts/docx-engine必要源码及构建脚本。不得只补minified bundle。

步骤：
1. bridge与服务端真实receipt逐字段对齐：persisted、operation_id、content_sha256、artifact_revision、base/document revision及请求上下文。正常新保存与同操作重放都正确；坏JSON/假成功/错误身份保持dirty和pending bytes；n结果不能清n+1输入。
2. locator首次/复用/恢复同一紧凑摘要；descriptor/adopt同一有序目标范围hash；不增大2000上限掩盖无界数组，不取消CAS。
3. 当前Office保持唯一用户稿；新候选显式采用，历史只下载/查看，专注不重建iframe。保存分析解耦，故障可下载未保存备份，切项目/刷新准确保护IME和待提交单元格。
4. 选区保存结构slice/签名及标记，替换与撤销保留原结构；不支持的结构明确限制且不破坏。最低“一段/一格”可用，继承摘要显式重生成与SOA局部更新要求，不以纯文本实验覆盖全部范围。
5. 文献表原位更新受管条目，保留用户位置/容器样式；正文引用重排/删除，编号与书目同步。复核现有sources XML正规化/作者数组改进，不重复旧P0结论。已有第三方域保留与动态插件互操作分开。
6. 模板映射、文控、真实签字空白、目录/页码、章节分节、横向SOA、跨页表头、字体、题注交叉引用、附录及无工程词全部收口；导出下载实际当前快照，不重新投影覆盖人工稿。
7. 按PRD做1440/1920/2560信息密度与真实状态审阅：主文档＋目录/待办/证据；压缩多余padding和长AI话术为bullet；保留已实现双栏，不重做一套UI。最小字/点击口径与原V指标不删。
8. 固定renderer上游base+必要dirty patch+未跟踪源、锁文件/构建命令/资源hash。一次交付记录足够，无需新发布系统。生产服务不切换。

WP6验收：B09–B12、W04–W06、A09–A24、V01–V08。须真实宿主＋iframe选择、保存、重开、下载；原生Word检查包含实际改后保存而非只打开或hash不变。文献表位置/格式和富文本撤销不能只用文本字符串比较。
