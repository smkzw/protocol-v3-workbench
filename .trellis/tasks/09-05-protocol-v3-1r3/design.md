# Design

复用产品SQLite factory、ApplicationService与现有事件replay/HTTP composition。
只使用临时数据库及合成事实，不复制真实项目。保留源连接持有WAL时用
sqlite3.Connection.backup创建新副本；不把裸主文件复制当作一致备份。
比较业务表内容/事件hash及canonical状态，不用文件字节hash判定SQLite等价。
API测试沿用隔离实际main方法；区分旧main自带sweeper与新增链副作用。
结果未知时按logical key查询，不自动调用执行器。错误映射改动必须由红测定位。
