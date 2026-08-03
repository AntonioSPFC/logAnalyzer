"""SQLite-backed persistence for curation reports."""

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass
class CurationReport:
    """A curation report associated with a call."""

    call_id: str
    report_text: str
    created_at: datetime
    modified_at: datetime


class CurationStore:
    """SQLite-backed persistence for curation reports."""

    def __init__(self, db_path: str):
        """Initialize store, creating DB and table if they don't exist."""
        self._db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the curation_reports table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS curation_reports (
                    call_id TEXT PRIMARY KEY,
                    report_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL
                )
            ''')

    def _connect(self) -> sqlite3.Connection:
        """Create a new database connection."""
        return sqlite3.connect(self._db_path, timeout=5.0)

    def save_report(self, call_id: str, report_text: str) -> CurationReport:
        """Save or update a report. Preserves created_at on updates."""
        now = datetime.now(timezone.utc)

        existing = self.get_report(call_id)

        try:
            with self._connect() as conn:
                if existing:
                    conn.execute(
                        'UPDATE curation_reports SET report_text = ?, modified_at = ? WHERE call_id = ?',
                        (report_text, now.isoformat(), call_id),
                    )
                    return CurationReport(
                        call_id=call_id,
                        report_text=report_text,
                        created_at=existing.created_at,
                        modified_at=now,
                    )
                else:
                    conn.execute(
                        'INSERT INTO curation_reports (call_id, report_text, created_at, modified_at) VALUES (?, ?, ?, ?)',
                        (call_id, report_text, now.isoformat(), now.isoformat()),
                    )
                    return CurationReport(
                        call_id=call_id,
                        report_text=report_text,
                        created_at=now,
                        modified_at=now,
                    )
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                # Retry once on BUSY
                time.sleep(0.1)
                return self.save_report(call_id, report_text)
            raise

    def get_report(self, call_id: str) -> CurationReport | None:
        """Retrieve report by CallId."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    'SELECT call_id, report_text, created_at, modified_at FROM curation_reports WHERE call_id = ?',
                    (call_id,),
                ).fetchone()
        except sqlite3.DatabaseError:
            return None

        if row is None:
            return None

        return CurationReport(
            call_id=row[0],
            report_text=row[1],
            created_at=datetime.fromisoformat(row[2]),
            modified_at=datetime.fromisoformat(row[3]),
        )

    def list_reports(self) -> list[CurationReport]:
        """List all reports ordered by modification date (newest first)."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    'SELECT call_id, report_text, created_at, modified_at FROM curation_reports ORDER BY modified_at DESC'
                ).fetchall()
        except sqlite3.DatabaseError:
            return []

        return [
            CurationReport(
                call_id=row[0],
                report_text=row[1],
                created_at=datetime.fromisoformat(row[2]),
                modified_at=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]

    def export_reports(self, call_data_loader: Callable | None = None) -> list[dict]:
        """Export all reports with optional enriched call data."""
        reports = self.list_reports()
        exported = []

        for report in reports:
            entry = {
                'call_id': report.call_id,
                'report_text': report.report_text,
                'created_at': report.created_at.isoformat(),
                'modified_at': report.modified_at.isoformat(),
            }

            if call_data_loader:
                try:
                    call_data = call_data_loader(report.call_id)
                    if call_data:
                        entry['customer_name'] = call_data.customer_name
                        entry['company'] = call_data.company
                        entry['product'] = call_data.product
                        entry['hangup_reason'] = call_data.hangup_reason
                except Exception:
                    pass

            exported.append(entry)

        return exported
