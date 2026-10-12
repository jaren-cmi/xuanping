import json
import sqlite3
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, path: str | Path = "xuanping.db") -> None:
        self.path = str(path)
        self._memory_connection = sqlite3.connect(":memory:") if self.path == ":memory:" else None
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            self._memory_connection.row_factory = sqlite3.Row
            return self._memory_connection
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, category TEXT NOT NULL, status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS products (
                    task_id TEXT NOT NULL, asin TEXT NOT NULL, data_json TEXT NOT NULL,
                    PRIMARY KEY (task_id, asin)
                );
                CREATE TABLE IF NOT EXISTS calibration (
                    category TEXT PRIMARY KEY, a REAL NOT NULL, b REAL NOT NULL,
                    sample_count INTEGER NOT NULL
                );
                """
            )

    def save_task(self, task_id: str, category: str, status: str, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO tasks(id, category, status, result_json) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET category=excluded.category,
                status=excluded.status, result_json=excluded.result_json""",
                (task_id, category, status, json.dumps(result, ensure_ascii=False)),
            )

    def save_product(self, task_id: str, asin: str, data: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO products(task_id, asin, data_json) VALUES (?, ?, ?)
                ON CONFLICT(task_id, asin) DO UPDATE SET data_json=excluded.data_json""",
                (task_id, asin, json.dumps(data, ensure_ascii=False)),
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "category": row["category"],
            "status": row["status"],
            "result": json.loads(row["result_json"]),
        }

    def get_calibration(self, category: str) -> tuple[float, float, int] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT a, b, sample_count FROM calibration WHERE category = ?", (category,)
            ).fetchone()
        return (row["a"], row["b"], row["sample_count"]) if row else None

    def save_calibration(self, category: str, a: float, b: float, sample_count: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO calibration(category, a, b, sample_count) VALUES (?, ?, ?, ?)
                ON CONFLICT(category) DO UPDATE SET a=excluded.a, b=excluded.b,
                sample_count=excluded.sample_count""",
                (category, a, b, sample_count),
            )

    def list_products(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT data_json FROM products WHERE task_id = ? ORDER BY asin", (task_id,)
            ).fetchall()
        return [json.loads(row["data_json"]) for row in rows]
