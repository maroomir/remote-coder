from __future__ import annotations

import csv
import io
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final


@dataclass(frozen=True)
class _TableSpec:
    name: str
    label: str
    columns: tuple[str, ...]
    sortable: frozenset[str]
    default_sort: str


_TABLES: Final[dict[str, _TableSpec]] = {
    "conversation_entries": _TableSpec(
        name="conversation_entries",
        label="대화·작업 기록",
        columns=(
            "id",
            "project",
            "chat_id",
            "role",
            "text",
            "job_id",
            "message_id",
            "reply_to_message_id",
            "created_at",
        ),
        sortable=frozenset({"id", "project", "chat_id", "role", "created_at", "job_id", "message_id"}),
        default_sort="id",
    ),
    "message_branch_links": _TableSpec(
        name="message_branch_links",
        label="메시지–브랜치 연결",
        columns=(
            "project",
            "chat_id",
            "message_id",
            "branch",
            "job_id",
            "created_at",
            "updated_at",
        ),
        sortable=frozenset(
            {"project", "chat_id", "message_id", "created_at", "updated_at", "branch", "job_id"}
        ),
        default_sort="updated_at",
    ),
}

_DEFAULT_EXPORT_MAX_ROWS: Final[int] = 50_000
_EXPORT_CHUNK: Final[int] = 2_000


def _open_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path.resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _build_where(
    spec: _TableSpec,
    *,
    project: str | None,
    chat_id: int | None,
    role: str | None,
    job_id: str | None,
    q: str | None,
) -> tuple[str, list[Any]]:
    where_parts: list[str] = []
    params: list[Any] = []

    if project and project.strip():
        where_parts.append("project = ?")
        params.append(project.strip())
    if chat_id is not None:
        where_parts.append("chat_id = ?")
        params.append(chat_id)
    if role and role.strip() and spec.name == "conversation_entries":
        where_parts.append("role = ?")
        params.append(role.strip())
    if job_id and job_id.strip():
        where_parts.append("job_id = ?")
        params.append(job_id.strip())

    if q and q.strip():
        qq = q.strip()
        if spec.name == "conversation_entries":
            where_parts.append(
                "(instr(lower(COALESCE(text,'')), lower(?)) > 0 "
                "OR instr(lower(COALESCE(job_id,'')), lower(?)) > 0 "
                "OR instr(lower(COALESCE(project,'')), lower(?)) > 0)"
            )
            params.extend([qq, qq, qq])
        else:
            where_parts.append(
                "(instr(lower(COALESCE(branch,'')), lower(?)) > 0 "
                "OR instr(lower(COALESCE(job_id,'')), lower(?)) > 0 "
                "OR instr(lower(COALESCE(project,'')), lower(?)) > 0)"
            )
            params.extend([qq, qq, qq])

    where_sql = " AND ".join(where_parts) if where_parts else "1=1"
    return where_sql, params


class ConversationDatabaseBrowser:
    # SECURITY: `_TABLES` 화이트리스트 외 테이블은 노출하지 않으며, sqlite는 read-only URI로만 엽니다.
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path.resolve()

    def tables_payload(self) -> dict[str, Any]:
        exists = self._db_path.is_file()
        tables = []
        for spec in _TABLES.values():
            tables.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "columns": list(spec.columns),
                    "default_sort": spec.default_sort,
                    "sortable": sorted(spec.sortable),
                }
            )
        return {
            "db_path": str(self._db_path),
            "db_exists": exists,
            "tables": tables,
        }

    def distinct_filter_options(self, table: str) -> dict[str, list[str]]:
        spec = _TABLES.get(table)
        if spec is None:
            raise ValueError(f"unknown table: {table}")
        if not self._db_path.is_file():
            return {"projects": [], "roles": []}

        conn = _open_readonly(self._db_path)
        try:
            cur = conn.execute(
                f"SELECT DISTINCT project FROM {spec.name} ORDER BY project COLLATE NOCASE"
            )
            projects = [str(r[0]) for r in cur.fetchall() if r[0] is not None and str(r[0]).strip() != ""]
            roles: list[str] = []
            if spec.name == "conversation_entries":
                cur2 = conn.execute(
                    "SELECT DISTINCT role FROM conversation_entries ORDER BY role COLLATE NOCASE"
                )
                roles = [str(r[0]) for r in cur2.fetchall() if r[0] is not None and str(r[0]).strip() != ""]
        finally:
            conn.close()
        return {"projects": projects, "roles": roles}

    def query_rows(
        self,
        table: str,
        *,
        project: str | None,
        chat_id: int | None,
        role: str | None,
        job_id: str | None,
        q: str | None,
        sort: str | None,
        order: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        spec = _TABLES.get(table)
        if spec is None:
            raise ValueError(f"unknown table: {table}")
        if order not in ("asc", "desc"):
            raise ValueError("order must be asc or desc")

        sort_col = (sort or "").strip() or spec.default_sort
        if sort_col not in spec.sortable:
            raise ValueError(f"invalid sort column: {sort_col}")

        if not self._db_path.is_file():
            return {
                "table": spec.name,
                "label": spec.label,
                "columns": list(spec.columns),
                "rows": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "sort": sort_col,
                "order": order,
            }

        where_sql, params = _build_where(
            spec, project=project, chat_id=chat_id, role=role, job_id=job_id, q=q
        )
        cols_sql = ", ".join(spec.columns)
        order_sql = "ASC" if order == "asc" else "DESC"

        count_sql = f"SELECT COUNT(*) FROM {spec.name} WHERE {where_sql}"
        data_sql = (
            f"SELECT {cols_sql} FROM {spec.name} WHERE {where_sql} "
            f"ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?"
        )

        conn = _open_readonly(self._db_path)
        try:
            total = int(conn.execute(count_sql, params).fetchone()[0])
            cur = conn.execute(data_sql, params + [limit, offset])
            col_names = [d[0] for d in cur.description]
            rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
        finally:
            conn.close()

        return {
            "table": spec.name,
            "label": spec.label,
            "columns": list(spec.columns),
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort": sort_col,
            "order": order,
        }

    def iter_csv_rows(
        self,
        table: str,
        *,
        project: str | None,
        chat_id: int | None,
        role: str | None,
        job_id: str | None,
        q: str | None,
        sort: str | None,
        order: str,
        max_rows: int = _DEFAULT_EXPORT_MAX_ROWS,
        chunk_size: int = _EXPORT_CHUNK,
    ) -> Iterator[bytes]:
        # Excel·한글 환경에서 CSV가 UTF-8로 인식되도록 BOM을 먼저 보냅니다.
        spec = _TABLES.get(table)
        if spec is None:
            raise ValueError(f"unknown table: {table}")
        if order not in ("asc", "desc"):
            raise ValueError("order must be asc or desc")
        sort_col = (sort or "").strip() or spec.default_sort
        if sort_col not in spec.sortable:
            raise ValueError(f"invalid sort column: {sort_col}")
        if max_rows < 1:
            raise ValueError("max_rows must be >= 1")
        if chunk_size < 1:
            raise ValueError("chunk_size must be >= 1")

        enc = "utf-8"
        yield "\ufeff".encode(enc)

        if not self._db_path.is_file():
            buf = io.StringIO()
            csv.writer(buf, lineterminator="\n").writerow(list(spec.columns))
            yield buf.getvalue().encode(enc)
            return

        where_sql, params = _build_where(
            spec, project=project, chat_id=chat_id, role=role, job_id=job_id, q=q
        )
        cols_sql = ", ".join(spec.columns)
        order_sql = "ASC" if order == "asc" else "DESC"
        header_buf = io.StringIO()
        csv.writer(header_buf, lineterminator="\n").writerow(list(spec.columns))
        yield header_buf.getvalue().encode(enc)

        conn = _open_readonly(self._db_path)
        try:
            emitted = 0
            offset = 0
            while emitted < max_rows:
                take = min(chunk_size, max_rows - emitted)
                data_sql = (
                    f"SELECT {cols_sql} FROM {spec.name} WHERE {where_sql} "
                    f"ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?"
                )
                cur = conn.execute(data_sql, params + [take, offset])
                batch = cur.fetchall()
                if not batch:
                    break
                for row in batch:
                    line_buf = io.StringIO()
                    csv.writer(line_buf, lineterminator="\n").writerow(
                        ["" if v is None else v for v in row]
                    )
                    yield line_buf.getvalue().encode(enc)
                emitted += len(batch)
                offset += len(batch)
                if len(batch) < take:
                    break
        finally:
            conn.close()
