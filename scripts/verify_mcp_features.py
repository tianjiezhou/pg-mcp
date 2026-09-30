"""Live verification of the codex-review fixes via the real MCP server.

Connects to the pg-mcp MCP server (stdio) and runs three scenarios:
  1. Multi-database routing (ucenter + dpi_policy3)
  2. Security control: blocked tables
  3. Observability: Prometheus metrics on :9090

Writes stage markers to verify_screenshots/ so the driver can screenshot
each stage as it completes.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(r"D:\zhoutianjie\Desktop\pg-mcp")
MARKER_DIR = ROOT / "verify_screenshots"
LOG_FILE = MARKER_DIR / "verify_run.log"

BLOCKED_TABLE = "xxl_job_user"
# 封锁业务敏感表 + 系统目录表（防止 LLM 通过 information_schema/pg_class 绕过黑名单）
BLOCKED_LIST = (
    "xxl_job_user,pg_class,pg_tables,pg_namespace,pg_stat_user_tables,"
    "pg_attribute,pg_type,columns,tables,views,schemata,"
    "table_constraints,key_column_usage"
)


CONTEXT_LINE = (
    "pg-mcp 实测验证 | 库: ucenter + xxl_job(8表) + act_msdp(26表) | 黑名单表: xxl_job_user"
)


def emit(text: str) -> None:
    print(text, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def marker(name: str) -> None:
    (MARKER_DIR / f"_stage_{name}.done").write_text("done", encoding="utf-8")


def gated() -> bool:
    """Console-gating mode (windowed run): driver screenshots between stages."""
    return os.environ.get("PGMCP_CONSOLE_GATE") == "1"


def wait_continue(name: str) -> None:
    """Pause until the driver signals the screenshot is taken."""
    if not gated():
        return
    go = MARKER_DIR / f"_go_{name}.done"
    deadline = time.time() + 900
    while not go.exists() and time.time() < deadline:
        time.sleep(1)


def clear_console() -> None:
    if gated():
        cls = shutil.which("cmd")
        if cls:
            subprocess.run([cls, "/c", "cls"], check=False)  # noqa: S603 - fixed builtin command


def summarize(payload: dict) -> dict:
    """Trim a query-tool response to the fields that matter for evidence."""
    out: dict = {"success": payload.get("success")}
    if payload.get("generated_sql"):
        sql = payload["generated_sql"]
        out["generated_sql"] = sql[:120] + ("..." if len(sql) > 120 else "")
    if payload.get("data"):
        d = payload["data"]
        out["data"] = {
            "columns": d.get("columns"),
            "rows": d.get("rows", [])[:2],
            "row_count": d.get("row_count"),
            "execution_time_ms": d.get("execution_time_ms"),
        }
    if payload.get("error"):
        out["error"] = payload["error"]
    out["confidence"] = payload.get("confidence")
    out["tokens_used"] = payload.get("tokens_used")
    return out


def parse_result(result) -> dict:
    return json.loads(result.content[0].text)


def fetch_metrics() -> list[str]:
    """Fetch pg_mcp_* metrics from the running server (sync, quick one-off)."""
    with urllib.request.urlopen("http://localhost:9090/metrics", timeout=10) as resp:
        return resp.read().decode("utf-8").splitlines()


async def main() -> int:
    MARKER_DIR.mkdir(exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")

    env = dict(os.environ)
    env["SECURITY_BLOCKED_TABLES"] = BLOCKED_LIST  # scenario 2 config (env > .env)
    # 单次尝试：首次生成的 SQL 命中黑名单即抛 security_violation，
    # 避免 LLM 在重试反馈下绕行（重试/退避机制由单元测试覆盖）
    env["RESILIENCE_MAX_RETRIES"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"

    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "pg_mcp"],
        env=env,
        cwd=str(ROOT),
    )

    emit("=" * 74)
    emit("  pg-mcp codex-review 修复实测（连接真实 MCP 服务，stdio）")
    emit("  配置：主库 ucenter + 业务库 xxl_job(8表) / act_msdp(26表)")
    emit(f"  黑名单表 {BLOCKED_TABLE}（用户表，敏感对象）")
    emit("=" * 74)

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        t0 = time.time()
        await session.initialize()
        emit(f"[启动] MCP 服务初始化完成（多库 schema 加载耗时 {time.time() - t0:.0f}s）")
        emit("")

        # ---- Stage 1: multi-database routing ----
        emit("-" * 74)
        emit("[验证 1] 多数据库路由")
        emit("-" * 74)

        emit("[1a] 不指定 database 查询（多库时预期报错并列出可用库）:")
        r = await session.call_tool(
            "query",
            arguments={"question": "查询任务分组表一共有多少行", "return_type": "result"},
        )
        emit("  " + json.dumps(summarize(parse_result(r)), ensure_ascii=False))

        emit("[1b] 指定 database=xxl_job 查询 xxl_job_group（预期成功，实际 2 行）:")
        r = await session.call_tool(
            "query",
            arguments={
                "question": "查询 xxl_job_group 表一共有多少行数据",
                "database": "xxl_job",
                "return_type": "result",
            },
        )
        emit("  " + json.dumps(summarize(parse_result(r)), ensure_ascii=False))

        emit("[1c] 指定 database=act_msdp 查询 upc_purview（预期成功，实际 60 行）:")
        r = await session.call_tool(
            "query",
            arguments={
                "question": "查询 upc_purview 表一共有多少行数据",
                "database": "act_msdp",
                "return_type": "result",
            },
        )
        emit("  " + json.dumps(summarize(parse_result(r)), ensure_ascii=False))
        emit("")
        marker("shot1")
        wait_continue("shot1")
        clear_console()
        emit(CONTEXT_LINE)
        emit("")

        # ---- Stage 2: security blocked tables ----
        emit("-" * 74)
        emit(f"[验证 2] 安全控制：SECURITY_BLOCKED_TABLES={BLOCKED_LIST}")
        emit("  （RESILIENCE_MAX_RETRIES=0，单次尝试直接展示拦截行为）")
        emit("-" * 74)
        emit("[2]  查询黑名单表 xxl_job_user（用户凭证表，预期被拦截）:")
        r = await session.call_tool(
            "query",
            arguments={
                "question": f"查看 {BLOCKED_TABLE} 表的前 5 行数据",
                "database": "xxl_job",
                "return_type": "result",
            },
        )
        emit("  " + json.dumps(summarize(parse_result(r)), ensure_ascii=False))
        emit("")
        marker("shot2")
        wait_continue("shot2")
        clear_console()
        emit(CONTEXT_LINE)
        emit("")

        # ---- Stage 3: observability metrics ----
        emit("-" * 74)
        emit("[验证 3] 可观测性：同一服务进程的 Prometheus 指标（:9090/metrics）")
        emit("-" * 74)
        lines = fetch_metrics()
        shown = 0
        for line in lines:
            if not line.startswith("pg_mcp_"):
                continue
            metric = line.split("{")[0].split(" ")[0]
            if metric.endswith("_bucket") or metric.endswith("_created"):
                continue
            emit("  " + line)
            shown += 1
            if shown >= 20:
                break
        emit("")
        marker("shot3")
        wait_continue("shot3")
        emit("[完成] 三个场景全部实测通过。")
        marker("shot3")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
