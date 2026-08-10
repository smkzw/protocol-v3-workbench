READY

P1 已关闭：

- [protocol_v3.py:385](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages/contracts/workbench_contracts/protocol_v3.py:385>)–[395](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages/contracts/workbench_contracts/protocol_v3.py:395>) 正确拒绝 ID/hash XOR、原始文件父身份、派生文件不完整父身份。
- [test_contract_models.py:217](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/test_contract_models.py:217>)–[235](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/test_contract_models.py:235>) 覆盖四种部分输入及完整派生身份。
- 独立矩阵复验：原始无父身份通过；原始单边/双边父身份拒绝；派生单边身份拒绝；完整派生身份通过。未见同因回归。
- 此前只读沙箱无法执行 pytest 仅是环境临时目录限制，不否定主验收者在可写隔离环境完成的 16+42 功能测试证据。