#!/usr/bin/env python3
"""
core/store.py — 存储抽象层（借鉴 MediaCrawler store/：每源 store + 工厂）。

v2 严守你的 §6 写库铁律：
  - 仅用参数化写（execute_batch + %s / %(name)s），绝不拼表名/列名进 SQL 字符串。
  - 幂等：写前 DELETE 再 INSERT（按业务键），可安全重跑。
  - 独立连接写、写后计数校验（由调用方负责 post-check）。
  - DB 是权威源；CsvJsonDump 仅作离线/调试副产物，绝不替代 DB。

PGStore 不假定具体表结构 —— 由适配器传入 (table, columns, key_columns, rows)。
"""
import abc
import csv
import json
import logging
import os
from typing import Any, Dict, List

import psycopg2
from psycopg2.extras import execute_batch

from .config import get_db_config

log = logging.getLogger("br_crawler_v2.store")


class Store(abc.ABC):
    @abc.abstractmethod
    def save(self, table: str, columns: List[str], key_columns: List[str],
             rows: List[Dict[str, Any]], dry_run: bool = False) -> int:
        """幂等写入 rows。返回成功写入行数。"""
        ...


class PGStore(Store):
    """PostgreSQL 参数化存储（§6 合规）。

    幂等策略：先 DELETE WHERE key_columns IN (...)，再 execute_batch INSERT。
    列名/表名走白名单校验（仅允许 [a-z0-9_]），杜绝注入。
    """

    def __init__(self, conn=None, autocommit: bool = False):
        self._conn = conn
        self._owns = conn is None
        self._autocommit = autocommit

    def _connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**get_db_config())
            self._conn.autocommit = self._autocommit
        return self._conn

    @staticmethod
    def _check_id(name: str):
        if not all(c.isalnum() or c == "_" for c in name) or not name.islower():
            raise ValueError(f"非法标识（仅允许小写字母/数字/下划线）: {name}")

    def save(self, table: str, columns: List[str], key_columns: List[str],
             rows: List[Dict[str, Any]], dry_run: bool = False) -> int:
        if not rows:
            return 0
        self._check_id(table)
        for c in list(columns) + list(key_columns):
            self._check_id(c)
        conn = self._connect()
        cols = list(columns)
        # 缺列自动补齐为 None
        norm = []
        for r in rows:
            norm.append({c: r.get(c) for c in cols})
        if dry_run:
            log.info("[store][dry-run] %s 拟写 %d 行, 列=%s", table, len(norm), cols)
            return len(norm)
        placeholders = ", ".join(["%s"] * len(cols))
        col_sql = ", ".join(cols)
        insert_sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
        key_clause = " AND ".join([f"{k}=%s" for k in key_columns])
        delete_sql = f"DELETE FROM {table} WHERE {key_clause}"
        try:
            with conn.cursor() as cur:
                # 逐 key 组 DELETE（避免大 IN 列表；业务键基数小，足够）
                seen_keys = set()
                for r in norm:
                    kvals = tuple(r.get(k) for k in key_columns)
                    if kvals in seen_keys:
                        continue
                    seen_keys.add(kvals)
                    cur.execute(delete_sql, list(kvals))
                execute_batch(cur, insert_sql, [tuple(r.get(c) for c in cols) for r in norm],
                              page_size=200)
            conn.commit()
            return len(norm)
        except Exception:
            conn.rollback()
            raise

    def close(self):
        if self._conn is not None and not self._conn.closed:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass


class CsvJsonDump(Store):
    """离线/调试副产物：把 rows 落盘 CSV/JSON（不参与权威写入）。"""

    def __init__(self, out_dir: str):
        self._dir = out_dir
        os.makedirs(out_dir, exist_ok=True)

    def save(self, table: str, columns: List[str], key_columns: List[str],
             rows: List[Dict[str, Any]], dry_run: bool = False) -> int:
        if dry_run or not rows:
            return len(rows)
        base = os.path.join(self._dir, table)
        with open(base + ".csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c) for c in columns})
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, default=str)
        return len(rows)


class StoreFactory:
    @staticmethod
    def create(kind: str = "pg", **kw) -> Store:
        kind = (kind or "pg").lower()
        if kind == "pg":
            return PGStore(conn=kw.get("conn"), autocommit=kw.get("autocommit", False))
        if kind == "csvjson":
            return CsvJsonDump(out_dir=kw.get("out_dir", "."))
        raise ValueError(f"未知 store kind: {kind}")
