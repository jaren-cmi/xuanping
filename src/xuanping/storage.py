import json
import sqlite3
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, path: str | Path = "xuanping.db") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return self._connection

    def _initialize(self) -> None:
        connection = self._connect()
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, category TEXT NOT NULL, status TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS products (
                task_id TEXT NOT NULL, asin TEXT NOT NULL, data_json TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'collected',
                PRIMARY KEY (task_id, asin)
            );
            CREATE TABLE IF NOT EXISTS calibration (
                category TEXT PRIMARY KEY, a REAL NOT NULL, b REAL NOT NULL,
                sample_count INTEGER NOT NULL
            );
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(products)")}
        if "stage" not in columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN stage TEXT NOT NULL DEFAULT 'collected'"
            )
        connection.commit()

    def save_task(self, task_id: str, category: str, status: str, result: dict[str, Any]) -> None:
        connection = self._connect()
        connection.execute(
                """INSERT INTO tasks(id, category, status, result_json) VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET category=excluded.category,
                status=excluded.status, result_json=excluded.result_json""",
                (task_id, category, status, json.dumps(result, ensure_ascii=False)),
        )
        connection.commit()

    def save_product(
        self, task_id: str, asin: str, data: dict[str, Any], stage: str = "collected"
    ) -> None:
        connection = self._connect()
        connection.execute(
            """INSERT INTO products(task_id, asin, data_json, stage) VALUES (?, ?, ?, ?)
            ON CONFLICT(task_id, asin) DO UPDATE SET
            data_json=excluded.data_json, stage=excluded.stage""",
            (task_id, asin, json.dumps(data, ensure_ascii=False), stage),
        )
        connection.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._connect().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "category": row["category"],
            "status": row["status"],
            "result": json.loads(row["result_json"]),
        }

    def get_calibration(self, category: str) -> tuple[float, float, int] | None:
        row = self._connect().execute(
            "SELECT a, b, sample_count FROM calibration WHERE category = ?", (category,)
        ).fetchone()
        return (row["a"], row["b"], row["sample_count"]) if row else None

    def save_calibration(self, category: str, a: float, b: float, sample_count: int) -> None:
        connection = self._connect()
        connection.execute(
                """INSERT INTO calibration(category, a, b, sample_count) VALUES (?, ?, ?, ?)
                ON CONFLICT(category) DO UPDATE SET a=excluded.a, b=excluded.b,
                sample_count=excluded.sample_count""",
                (category, a, b, sample_count),
        )
        connection.commit()

    def list_products(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT data_json FROM products WHERE task_id = ? ORDER BY asin", (task_id,)
        ).fetchall()
        return [json.loads(row["data_json"]) for row in rows]

    def list_product_records(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._connect().execute(
            "SELECT data_json, stage FROM products WHERE task_id = ? ORDER BY asin", (task_id,)
        ).fetchall()
        return [{"product": json.loads(row["data_json"]), "stage": row["stage"]} for row in rows]

    def close(self) -> None:
        self._connection.close()
