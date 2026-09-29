# Codex Review 问题修复方案

对应第 5 章第 4 节 codex review 指出的 4 类缺陷。目标：设计承诺与实际行为对齐，不扩大改动面。

## 问题 1：重复 to_dict + 测试回归

**改动：**
- `models/query.py`：删除 `QueryResponse` 的第二个 `to_dict`（214-220 行，exclude_none=True 版本），保留第一个（tokens_used 补 0 逻辑生效）；删除无人调用的 `QueryResult.to_dict`（130-136 行）
- `server.py`：删除 359-362 行的手工补 `tokens_used`（保留的 to_dict 已处理）
- `tests/unit/test_config.py`：修复 4 个回归
  - 3 个 `test_default_values`：构造时传 `_env_file=None` 隔离本地 .env（pydantic-settings 标准做法）
  - `test_invalid_api_key_format`：改为「空 key 报错、非 sk- 前缀 key 合法」（配合 MiMo 支持）

## 问题 2：安全控制（表/列黑名单、EXPLAIN）接入配置

**改动：**
- `config/settings.py` `SecurityConfig` 新增：
  - `blocked_tables: list[str] = []`（env: `SECURITY_BLOCKED_TABLES`，JSON 数组）
  - `blocked_columns: list[str] = []`（env: `SECURITY_BLOCKED_COLUMNS`，JSON 数组）
  - `allow_explain: bool = False`（env: `SECURITY_ALLOW_EXPLAIN`）
- `server.py`：`SQLValidator(...)` 由硬编码 None/False 改为从 `_settings.security` 传入
- validator 引擎已实现（sql_validator.py:80-95、187-190、236-252），无需改动

**示例**：`.env` 中 `SECURITY_BLOCKED_TABLES='["ts_secret_config","user_credentials"]'`

## 问题 3：弹性与可观测接入请求流程

**3a 限流接入：**
- `server.py`：`_rate_limiter` 传入 orchestrator（替换现在创建后无人用的死对象；同时删除同样无人用的 server 级 `_circuit_breaker` 全局变量，orchestrator 自建的为准）
- `services/orchestrator.py`：构造函数新增 `rate_limiter` 参数；SQL 生成包裹 `async with rate_limiter.for_llm()`，SQL 执行包裹 `async with rate_limiter.for_queries()`
- `config/settings.py` `ResilienceConfig` 新增 `query_rate_limit: int = 10`、`llm_rate_limit: int = 5`（替换 server.py 中硬编码的 10/5）

**3b 重试退避（启用闲置字段 retry_delay/backoff_factor）：**
- `orchestrator.py` `_generate_sql_with_retry`：重试前 `await asyncio.sleep(retry_delay * backoff_factor ** attempt)`，指数退避

**3c 指标埋点（MetricsCollector 已有完整 API，只缺调用）：**
- `orchestrator.py`：请求开始/结束 `increment_query_request(status, database)`；总时长 observe query_duration；SQL 执行段 observe_db_query_duration；校验失败 `increment_sql_rejected(reason)`（在 PgMcpError 分支按 error.code）
- `services/sql_generator.py`、`result_validator.py`：LLM 调用前后 `increment_llm_call` + `observe_llm_latency`（不改方法签名，token 计数留待后续）
- 直接 `from pg_mcp.observability.metrics import metrics`（模块级单例，避免构造函数层层传参）

**3d tracing.py：** 本次不接（99 语句的完整 tracing 体系超出本次范围，request_id 日志链路已可用）。在文档中注明遗留。

## 问题 4：多数据库启用

**配置格式**（向后兼容）：
- 新增 env `DATABASES`：JSON 数组，每项 `{"name": "...", "host": ..., "port": ..., "name"→用 "database" 字段名 ..., "user": ..., "password": ...}`
  - 示例：`DATABASES='[{"name":"ucenter","host":"<your-db-host>","database":"ucenter","user":"<readonly-user>","password":"..."},{"name":"dpi_policy3",...}]'`
- 未设置 `DATABASES` 时回退现有单库 `DATABASE_*`（现有部署不受影响）
- 实现：`Settings` 新增 `databases: list[DatabaseConfig]` 解析逻辑（first 为主库）

**接线：**
- `server.py` lifespan：为每个库建 pool、建 executor、加载 schema；传 `executors` 字典给 orchestrator
- `orchestrator.py`：`sql_executor`（单个）→ `sql_executors: dict[str, SQLExecutor]`；execute_query 按 `_resolve_database` 结果取执行器（多库校验逻辑 `_resolve_database` 已实现，无需改）
- MCP `query` 工具 docstring 更新 database 参数说明

**注意**：schema 加载串行，多库启动时间 = 各库之和（ucenter 35s + dpi_policy3 预计类似）；池参数每库独立。

## 测试计划

- 更新 `test_orchestrator.py`（构造签名变化：executors 字典 + rate_limiter）
- 新增：
  - 退避：mock `asyncio.sleep` 断言按指数退避调用
  - 限流：构造 limit=1 的 limiter，并发两请求断言排队/超时行为
  - 安全：`SECURITY_BLOCKED_TABLES` 生效 → 查询命中黑名单表被拒（sql_rejected 指标 +1）
  - 多库：两库配置下 `_resolve_database` 正确路由、未知名报错、单库自动选择
  - 模型：to_dict 删除后 tokens_used 行为（None → 0）
- 全量：`pytest tests/unit`（预期 248+ 全绿）、`mypy src`、`ruff check .`

## 验证（按全局规则用 MCP 实测）

1. `claude -p` 调 `mcp__pg-mcp__query`：默认库 ucenter 正常查询
2. 指定 `database="dpi_policy3"` 查询（同主机第二库，凭据同主库只读账号）
3. `.env` 临时加 `SECURITY_BLOCKED_TABLES='["xxl_job_log"]'` 重启，查询该表应被拒（MCP 返回 SECURITY_VIOLATION），去掉后恢复
4. `OBSERVABILITY_METRICS_ENABLED=true` 启动，curl metrics 端口看 `pg_mcp_query_requests_total` 等有值

## 文件改动清单

| 文件 | 操作 |
|---|---|
| `src/pg_mcp/models/query.py` | 删重复 to_dict ×2 |
| `src/pg_mcp/config/settings.py` | SecurityConfig +3 字段、ResilienceConfig +2 字段、Settings 多库解析 |
| `src/pg_mcp/services/orchestrator.py` | executors 字典、rate_limiter、退避、指标埋点 |
| `src/pg_mcp/services/sql_generator.py` | LLM 指标埋点 |
| `src/pg_mcp/services/result_validator.py` | LLM 指标埋点 |
| `src/pg_mcp/server.py` | 多库 lifespan、传参清理、删死对象、删手工补丁 |
| `tests/unit/test_config.py` | 修 4 个回归 |
| `tests/unit/test_orchestrator.py` | 适配新构造签名 |
| `tests/unit/` 新增/扩展 | 退避/限流/黑名单/多库/模型 用例 |
| `.env` | 加 DATABASES（ucenter + dpi_policy3）演示多库 |
| `ISMI-CHANGELOG.md` | 追加 id=2 变更记录 |

## 遗留（不在本次范围）

- LLM token 用量提取（需改 generate() 签名）
- tracing.py 全量接入
- schema 多库并行加载优化
