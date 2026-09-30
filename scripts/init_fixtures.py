r"""Initialize fixture test databases (blog_small / saas_crm_large) on the
configured PostgreSQL server.

The fixture SQL files start with DROP/CREATE DATABASE followed by a psql
`\c <db>` meta-command, then pure schema+data SQL. We split at the `\c` line:
part 1 runs on the 'postgres' database (autocommit, one statement at a time),
part 2 runs as a single multi-statement batch on the new database.
"""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

ROOT = Path(r"D:\zhoutianjie\Desktop\pg-mcp")
FIXTURES = [
    (ROOT / "fixtures" / "01_small_db.sql", "blog_small"),
    (ROOT / "fixtures" / "03_large_db.sql", "saas_crm_large"),
]


def split_sql(path: Path) -> tuple[list[str], str, list[str]]:
    """Return (pre-connect statements, post-connect SQL batch, post-batch statements).

    VACUUM cannot run inside a transaction block, so it is pulled out of the
    main batch and executed separately afterwards.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    split_idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith("\\c"))
    pre = [ln for ln in lines[:split_idx] if ln.strip() and not ln.strip().startswith("--")]
    post_lines = lines[split_idx + 1 :]
    standalone = [
        ln.strip().rstrip(";")
        for ln in post_lines
        if ln.strip().upper().startswith("VACUUM")
    ]
    post_lines = [
        ln for ln in post_lines if not ln.strip().upper().startswith("VACUUM")
    ]
    stmts = [s.strip() for s in "\n".join(pre).split(";") if s.strip()]
    return stmts, "\n".join(post_lines), standalone


async def load_one(admin_conn_spec: dict, sql_path: Path, dbname: str) -> None:
    stmts, batch, standalone = split_sql(sql_path)

    admin = await asyncpg.connect(**admin_conn_spec, database="postgres")
    try:
        for stmt in stmts:
            await admin.execute(stmt)
        print(f"[ok] database '{dbname}' created", flush=True)
    finally:
        await admin.close()

    conn = await asyncpg.connect(**admin_conn_spec, database=dbname)
    try:
        await conn.execute(batch)
        for stmt in standalone:
            await conn.execute(stmt)
        tables = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE'"
        )
        views = await conn.fetchval(
            "SELECT COUNT(*) FROM information_schema.views WHERE table_schema='public'"
        )
        print(
            f"[ok] '{dbname}' loaded: {tables} tables, {views} views",
            flush=True,
        )
    finally:
        await conn.close()


async def main() -> int:
    load_dotenv(ROOT / ".env")
    spec = {
        "host": os.environ["DATABASE_HOST"],
        "port": int(os.environ["DATABASE_PORT"]),
        "user": os.environ["DATABASE_USER"],
        "password": os.environ["DATABASE_PASSWORD"],
        "timeout": 30,
    }
    for sql_path, dbname in FIXTURES:
        await load_one(spec, sql_path, dbname)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
