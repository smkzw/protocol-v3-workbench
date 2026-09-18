# 3R.4B owner验收 — 2026-09-13

结论：B的可执行适用性/结构与输入输出绑定范围通过，继续C；整个3R.4与产品未完成。70现行规则、0 pending、743绑定；不将本结论扩大为医学充分性、真实项目、浏览器或Word。

## 实际证据与独立性

- 原冻结315文件（311开跑前+4运行中补捕）见fresh_review_20260913/artifact_manifest.json；原2177回归与快照保留。
- 独立C03 ZCode/GLM-5.3/max，新会话sess_e3599511-8964-4589-b7bf-c2c90ac2e0d2，1159.971秒，终态returncode0，无fallback。reviewer_stdout.log实际为JSON运行回执；请求/响应模型和observed effort一致。tool_result_count遥测0不作工具成功计数，实际读取/实验产物另存reviewer_scratch。
- review_receipt.json实际为Markdown报告。审阅者报告核心317项与独立实验通过；覆盖70规则源码/当前合同对照，但仅精读28个DOCX窗口，未逐字读全部skill prompt、未做医学充分性/Word，不冒称完全医学审阅。
- global guard因无关C01.peak字符串导致导入失败，原global文件未改。沿同一live manifest完整C03链使用既有runner；没有guard生成包或audit-execution通过证明。如实保留该过程限制，不虚构审批。

## 审阅意见处置

P2-1接受：原49行source_inventory保持历史字节不回写；新增runs/mw_protocol_v3_3r4b_20260912/applicability_obligation_matrix_adjudicated_20260913.json逐项记录49源行、14重叠行与70现行声明。真实谱系计数40保留ID/9退役/30新增，净增21；纠正报告把净增21说成新增21。源节点锚点与逐规则继承区分，当前rationale/谓词/受控义务完整保存。

P3-1移交D/V1.2：master=false不自动产生features对象；已有原始/历史值保留，新的规范事实采用时处理，用户不应被要求编辑JSON。保留actual临床参数残留冲突。该投影/一次修订仍需真实SQLite用例，未声称已实现。
P3-2保留当前8.1永久停药基础义务；空转规则可在触达该章时简化，不能误删永久停药。
P3-3移交V1内容核对：ECG集中判读与中心实验室独立，当前通用事实粒度并非医学内容完备证明。
P3-4移交3R.5A词汇闭合：目前相关词汇未发现越域，后续把声明目录新增claim/evidence纳入同一闭合，非新增平台。
P3-5“死代码”判断拒绝：owner_presence_branch_check.json证明presence=true而内部条件未知时，第二次判断必须把章节置conditional。不能删除。粗粒度rule_id不作为用户前端解释或医学批准。

## owner补充修复与复验

独立审阅不包含owner发现的不存在cell目标加载反例。候选在审阅期间仅存patch，终态后才修改源。新增定向测试先因漏import失败（cell_target_red.log，非产品证据），补import后DID NOT RAISE才是真实红测（cell_target_behavior_red.log）；loader增加当前合同cell目标存在性检查，未改变实际70规则或负向fixtures/expected。

修复后318相关测试通过；共享模块全量Protocol v3回归2178通过、1既有warning、52.75秒，post_review_regression.log/xml。post_review_source_hashes.json全部文件至回归终态不变；此小型确定性目标检查由owner按实际反例与完整回归复验，不冒充修订后又有新的独立模型意见。

## 下一步

当前Trellis转3R.4C，复用owner_c_reconnaissance.json桥接反例，事实标签传播、候选与实际确认分离；随后D复用既有SQLite/UoW/ledger。原review冻结快照与所有失败保留。不重新初始化Trellis、不重派已终态C03、不重跑产品首次探针/OCR/翻译。无服务或产品模型已启动。
