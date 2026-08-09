# 医学写作系统本地/私有化发布

该发布面用于当前单机私有运行和后续公司内网部署前的同构验收。真实方案、SQLite、DOCX/PDF/OCR 与独立 AI 不上传到公网 Sites。

## 常态入口

- 用户入口：`http://127.0.0.1:5174/`
- 后端：`http://127.0.0.1:8911/`
- 运行合同：`http://127.0.0.1:5174/runtime-build.json`
- 准备状态：`http://127.0.0.1:5174/api/runtime-readiness`
- 遗留 8910 不属于本发布，不得由发布脚本停止。

## 发布命令

```bash
deploy/medical_writing_local/manage.zsh status
deploy/medical_writing_local/manage.zsh verify
deploy/medical_writing_local/manage.zsh restart
deploy/medical_writing_local/manage.zsh stop
deploy/medical_writing_local/manage.zsh start
```

`restart` 只会终止工作目录属于本项目的 5174/8911 监听进程。若端口被其他程序占用，脚本失败关闭。后端密钥继续从仓库外 `~/.config/cms-medical-workbench/ai-runtime.env` 读取，不写入发布目录或日志。

## 上线门

- 前端 runtime contract、API contract 和期望后端 build 与当前后端一致。
- 31 项医学写作必需 API 能力全部注册。
- SQLite schema 16、完整性、外键和审计链通过。
- 独立 DeepSeek `deepseek-v4-pro` 可用且不依赖 Codex/Hermes。
- 无合同或旧合同客户端在写作 API 前失败关闭；当前合同可读取真实 RUX 文档会话。
- 浏览器可进入真实工作副本，阻断页不常驻，无 console error。
- Open XML SDK 3.5.1（MIT）发布门通过：绿地 DOCX 零错误，至少两个真实
  导入项目未修改透传 SHA-256 不变，修改导出相对来源零新增错误签名。
- LibreOffice 仅用于 PDF/PNG 辅助回归，不得回写交付 DOCX；Microsoft
  Word 原生打开、更新域、保存、目录/图目录/表目录及版式复核为最终门。

发布包构建必须显式传入 OpenXML 门禁报告：

```bash
python deploy/medical_writing_local/build_release_bundle.py \
  --full-pytest "<full pytest result>" \
  --medical-writing-pytest "<medical-writing pytest result>" \
  --browser-report records/.../browser_report.json \
  --word-validation-report records/.../openxml_release_gate.json
```

发布和运行代码不包含 Aspose、Syncfusion 等付费 Word 引擎，也不把
OpenXML 校验器放入 FastAPI 文档下载链路。

## 回滚

每次发布后在 `releases/medical_writing/` 保存不含 runtime、密钥、真实源文件和 `node_modules` 的源码快照、发布清单与 SHA-256。回滚时先 `stop`，校验目标快照哈希，再恢复代码并执行目标版本的 `restart` 与 `verify`。SQLite 与文档运行库不随代码快照覆盖；涉及 schema 迁移时必须使用单独的数据迁移/回滚程序。

## Sites 边界

既有可行性审计已确认：当前 FastAPI、SQLite、本地文件和私有 AI 链不能原样部署到 Sites。Sites 只保留为无真实临床数据的演示适配层候选，不发展第二套业务规则。
