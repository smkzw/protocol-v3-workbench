# 实际组件浏览器验证（2026-09-13）

范围：实际ProtocolIntakeWorkspace/ProtocolSourceIntake、真实源API和SQLite/Graph/Harness，只有provider HTTP回复为明确标注的合成数据。CUA iab tab2，地址http://127.0.0.1:5173/tests/protocol-intake-functional.html，独立API52456；不是全App导航或医学/模型/Word验收。

已直接操作并观察：
- 可选说明提交，真实202/GET结果显示缺失八字段；刷新保留原说明与结果。第一次提交前无源文件，synthetic_generation_calls=1，刷新未增加。
- 可见“添加DOCX文件”标签可打开多选，两个新合成DOCX同时选入。隐藏input的语义点击未打开chooser，首次chooser超时；换可见标签成功，不是上传权限绕过。
- 待选文件未保存时“准备写作材料”禁用并解释先保存或取消；同组明确选一次类别、一次保存，实际两次source POST200。
- 两份资料默认勾选；将第二份误选类别更正为同行评审文献，PATCH200、更正后的source ID/下载链接改变，两个勾选均保留。
- 带两份资料提交，刷新显示相同来源、说明与整理结果；第二个不同原始请求仅增加一次合成generation，总数2，真实模型0；日志没有刷新额外POST。
- 浏览器console error/warn为空。截图直接观察1248×720下无水平溢出，版面偏表单化；还没做窄屏/computed style完整检查。

未完成/用户视角发现：
- 缺失八字段被压成一长串并指引再写自由文本。下一步骤必须由AI给推荐问题/预选候选与最少补充，而非八个必填字段。没有确认建议、整稿、编辑或Word出口，不能称完整可用。
- 新任务202短暂显示“继续本次整理”，与自动后台执行同时出现可能使用户误以为需要再点击；功能去重不代表交互理想。需在冻结解除后区分刚提交的自动运行与恢复入口展示。
- 资料排除选择跨刷新是否保留尚待实际验证，不能从brief/run恢复推断所有编辑状态都恢复。
- 只进行了可见文件chooser操作，未记录macOS原生picker全部点击，不能据此宣称≤20全路径达标。

来源均为本目录新建synthetic-protocol.docx与synthetic-reference.docx，无用户医学资料、真实凭证或供应商调用。
