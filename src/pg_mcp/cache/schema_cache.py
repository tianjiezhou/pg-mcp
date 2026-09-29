"""Schema caching layer.

This module provides caching functionality for database schemas to avoid
repeated introspection queries and improve performance.
"""

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asyncpg import Pool

from pg_mcp.config.settings import CacheConfig
from pg_mcp.db.introspection import SchemaIntrospector
from pg_mcp.models.schema import DatabaseSchema

logger = logging.getLogger(__name__)


class SchemaCache:
    """Schema cache manager with TTL and auto-refresh capabilities.

    This class manages cached database schemas with configurable TTL and
    supports automatic background refresh.

    Attributes:
        config: Cache configuration.

    Example:
        >>> cache = SchemaCache(CacheConfig(schema_ttl=3600))
        >>> schema = await cache.load("mydb", pool)
        >>> cached = cache.get("mydb")  # Returns cached schema
        >>> await cache.start_auto_refresh(60, pools)  # Refresh every 60 minutes
    """

    def __init__(self, config: CacheConfig):
        """Initialize schema cache.

        Args:
            config: Cache configuration with TTL and size limits.
        """
        self.config = config
        self._cache: dict[str, DatabaseSchema] = {}
        self._cache_timestamps: dict[str, datetime] = {}
        self._refresh_task: asyncio.Task[None] | None = None
        self._stop_refresh = False

    def get(self, database_name: str) -> DatabaseSchema | None:
        """Get cached schema if available and not expired.

        Args:
            database_name: Name of the database.

        Returns:
            DatabaseSchema | None: Cached schema if available and valid,
                None otherwise.

        Example:
            >>> schema = cache.get("mydb")
            >>> if schema is None:
            ...     schema = await cache.load("mydb", pool)
        """
        if not self.config.enabled:
            return None

        if database_name not in self._cache:
            return None

        # Check if cache is expired
        cache_age = self.get_cache_age(database_name)
        if cache_age is None or cache_age > self.config.schema_ttl:
            # Cache expired, remove it
            self._cache.pop(database_name, None)
            self._cache_timestamps.pop(database_name, None)
            return None

        return self._cache[database_name]

    async def load(
        self,
        database_name: str,
        pool: Pool,
        use_cache: bool = True,
    ) -> DatabaseSchema:
        """Load and cache database schema.

        This method performs schema introspection and stores the result
        in cache with current timestamp. When ``use_cache`` is true and
        caching is enabled, a valid disk-persisted schema is returned
        without contacting the database, which keeps server cold starts
        fast for large schemas.

        Args:
            database_name: Name of the database to introspect.
            pool: Connection pool for the database.
            use_cache: Allow returning a cached schema (memory or disk).

        Returns:
            DatabaseSchema: Loaded database schema.

        Raises:
            asyncpg.PostgresError: If database connection or introspection fails.

        Example:
            >>> schema = await cache.load("mydb", pool)
            >>> print(f"Loaded {len(schema.tables)} tables")
        """
        if use_cache and self.config.enabled:
            cached = self.get(database_name)
            if cached is not None:
                return cached
            from_disk = self._load_from_disk(database_name)
            if from_disk is not None:
                return from_disk

        introspector = SchemaIntrospector(pool, database_name)
        schema = await introspector.introspect()

        if self.config.enabled:
            self._cache[database_name] = schema
            self._cache_timestamps[database_name] = datetime.now(UTC)
            self._save_to_disk(database_name, schema)

        return schema

    async def refresh(
        self,
        database_name: str,
        pool: Pool,
    ) -> None:
        """Refresh schema cache for a specific database.

        This method force-reloads the schema from the database, bypassing
        any cached copy, and updates the cache.

        Args:
            database_name: Name of the database to refresh.
            pool: Connection pool for the database.

        Example:
            >>> await cache.refresh("mydb", pool)
        """
        await self.load(database_name, pool, use_cache=False)

    def _disk_path(self, database_name: str) -> Path | None:
        """Return the disk cache file path for a database, or None if disabled."""
        if not self.config.persist_dir:
            return None
        safe_name = database_name.replace("/", "_").replace("\\", "_")
        return Path(self.config.persist_dir) / f"{safe_name}.json"

    def _load_from_disk(self, database_name: str) -> DatabaseSchema | None:
        """Load a schema from the disk cache if present and fresh."""
        path = self._disk_path(database_name)
        if path is None or not path.exists():
            return None
        try:
            payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            cached_at = datetime.fromisoformat(payload["cached_at"])
            age = (datetime.now(UTC) - cached_at).total_seconds()
            if age > self.config.disk_ttl:
                logger.debug("Disk schema cache for '%s' expired (%.0fs old)", database_name, age)
                return None
            schema = DatabaseSchema.model_validate(payload["schema"])
            self._cache[database_name] = schema
            self._cache_timestamps[database_name] = cached_at
            logger.info(
                "Loaded schema for '%s' from disk cache (%d tables, %.0fs old)",
                database_name,
                len(schema.tables),
                age,
            )
            return schema
        except Exception as e:
            logger.warning("Ignoring unreadable disk schema cache for '%s': %s", database_name, e)
            return None

    def _save_to_disk(self, database_name: str, schema: DatabaseSchema) -> None:
        """Persist a schema to the disk cache atomically (best effort)."""
        path = self._disk_path(database_name)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "cached_at": datetime.now(UTC).isoformat(),
                "schema": schema.model_dump(mode="json"),
            }
            tmp_path = path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(path)
        except Exception as e:
            logger.warning("Failed to persist schema cache for '%s': %s", database_name, e)

    async def start_auto_refresh(
        self,
        interval_minutes: int,
        pools: dict[str, Pool],
    ) -> None:
        """Start automatic background schema refresh.

        This method starts a background task that periodically refreshes
        all cached schemas.

        Args:
            interval_minutes: Refresh interval in minutes.
            pools: Dictionary mapping database names to connection pools.

        Example:
            >>> pools = {"db1": pool1, "db2": pool2}
            >>> await cache.start_auto_refresh(60, pools)
        """
        if not self.config.enabled:
            return

        if self._refresh_task is not None and not self._refresh_task.done():
            # Task already running
            return

        self._stop_refresh = False
        self._refresh_task = asyncio.create_task(self._auto_refresh_loop(interval_minutes, pools))

    async def stop_auto_refresh(self) -> None:
        """Stop automatic refresh task.

        This method immediately cancels the background refresh task if running.

        Example:
            >>> await cache.stop_auto_refresh()
        """
        self._stop_refresh = True

        if self._refresh_task is not None and not self._refresh_task.done():
            # Immediately cancel the task
            self._refresh_task.cancel()
            # Wait for cancellation to complete
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            logger.debug("Auto-refresh task cancelled")

    async def _auto_refresh_loop(
        self,
        interval_minutes: int,
        pools: dict[str, Pool],
    ) -> None:
        """Background loop for automatic schema refresh.

        Args:
            interval_minutes: Refresh interval in minutes.
            pools: Dictionary mapping database names to connection pools.
        """
        interval_seconds = interval_minutes * 60

        while not self._stop_refresh:
            try:
                # Wait for the interval
                await asyncio.sleep(interval_seconds)

                if self._stop_refresh:
                    break

                # Refresh all cached schemas
                for database_name, pool in pools.items():
                    if database_name in self._cache:
                        with contextlib.suppress(Exception):
                            await self.refresh(database_name, pool)

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but continue
                logger.exception("Error during schema refresh: %s", e)

    def get_cache_age(self, database_name: str) -> float | None:
        """Get cache age in seconds.

        Args:
            database_name: Name of the database.

        Returns:
            float | None: Age in seconds if cached, None otherwise.

        Example:
            >>> age = cache.get_cache_age("mydb")
            >>> if age and age > 3600:
            ...     print("Cache is stale")
        """
        if database_name not in self._cache_timestamps:
            return None

        timestamp = self._cache_timestamps[database_name]
        age = datetime.now(UTC) - timestamp
        return age.total_seconds()

    def clear(self, database_name: str | None = None) -> None:
        """Clear cache for a specific database or all databases.

        Args:
            database_name: Name of the database to clear. If None, clears all.

        Example:
            >>> cache.clear("mydb")  # Clear specific database
            >>> cache.clear()  # Clear all
        """
        if database_name is None:
            self._cache.clear()
            self._cache_timestamps.clear()
        else:
            self._cache.pop(database_name, None)
            self._cache_timestamps.pop(database_name, None)

    def get_cached_databases(self) -> list[str]:
        """Get list of currently cached database names.

        Returns:
            list[str]: List of database names with valid cache entries.

        Example:
            >>> databases = cache.get_cached_databases()
            >>> print(f"Cached: {', '.join(databases)}")
        """
        return list(self._cache.keys())
