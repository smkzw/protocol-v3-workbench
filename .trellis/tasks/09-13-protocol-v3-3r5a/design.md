# 设计与边界

复用标准库zip/XML、现有Pydantic、当前semantic_node IDs和CheckerFinding语义，不加数据库或通用QC平台。原始source rows与normalized atomic obligations分开；criterion ID不用可能为空/重复的E6 label，使用源版本+XML位置+稳定子项。公司6.x标签不伪称当前ICH新编号。

每atom最少保存source locator/raw fragment、normalized check、category、semantic nodes、applicability说明/已接规则引用、evidence requirement、implementation/status。不以空字段/关键词验证医学充分性。注册中的来源不确定性保留，不猜“排斥反应”替代含义；末参考提示不硬造正文要求。

六项L1分别登记当前状态：版本一致、缩略语闭环、参考文献双向、文字性交叉引用、数字单位、登记一致性。时效性/全称医学正确/登记真实适用不能冒称纯字符串检查完成。当前版本标识与修订历史以前记录分开，不要求历史日期都一致。签署控件不假填。

Word当前源required样式/书签都存在，无缺失不造修复；自动_Toc与稳定语义对象分开，现阶段仅源映射，实际生成对象全量核对在V1.5。
