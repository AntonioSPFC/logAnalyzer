"""Unit tests for CurationStore."""

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from dashboard.store import CurationReport, CurationStore


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_curation.db")


@pytest.fixture
def store(db_path):
    """Create a CurationStore with a temporary database."""
    return CurationStore(db_path)


class TestCurationStoreInit:
    """Tests for store initialization and schema creation."""

    def test_creates_database_file(self, db_path):
        """Store creates the database file on initialization."""
        CurationStore(db_path)
        assert os.path.exists(db_path)

    def test_creates_table(self, store, db_path):
        """Store creates the curation_reports table."""
        import sqlite3

        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='curation_reports'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent_schema_creation(self, db_path):
        """Creating store twice on same DB does not raise errors."""
        CurationStore(db_path)
        CurationStore(db_path)  # Should not raise


class TestSaveReport:
    """Tests for save_report method."""

    def test_save_new_report(self, store):
        """Saving a new report returns a CurationReport with correct fields."""
        report = store.save_report("abc123", "Test report text")

        assert isinstance(report, CurationReport)
        assert report.call_id == "abc123"
        assert report.report_text == "Test report text"
        assert report.created_at is not None
        assert report.modified_at is not None
        assert report.created_at == report.modified_at

    def test_save_report_timestamps_are_utc(self, store):
        """Saved report timestamps are in UTC."""
        report = store.save_report("abc123", "Text")

        assert report.created_at.tzinfo == timezone.utc
        assert report.modified_at.tzinfo == timezone.utc

    def test_update_existing_report(self, store):
        """Updating an existing report preserves created_at and updates modified_at."""
        original = store.save_report("abc123", "Original text")

        import time
        time.sleep(0.01)  # Ensure time difference

        updated = store.save_report("abc123", "Updated text")

        assert updated.call_id == "abc123"
        assert updated.report_text == "Updated text"
        assert updated.created_at == original.created_at
        assert updated.modified_at >= original.modified_at

    def test_save_report_persists_to_db(self, store):
        """Saved report can be retrieved from the database."""
        store.save_report("abc123", "Persisted text")

        retrieved = store.get_report("abc123")
        assert retrieved is not None
        assert retrieved.report_text == "Persisted text"


class TestGetReport:
    """Tests for get_report method."""

    def test_get_existing_report(self, store):
        """Retrieving an existing report returns it correctly."""
        store.save_report("call001", "Report content")

        report = store.get_report("call001")
        assert report is not None
        assert report.call_id == "call001"
        assert report.report_text == "Report content"

    def test_get_nonexistent_report(self, store):
        """Retrieving a nonexistent report returns None."""
        report = store.get_report("nonexistent_id")
        assert report is None

    def test_get_report_empty_db(self, store):
        """Getting a report from an empty DB returns None."""
        report = store.get_report("anything")
        assert report is None


class TestListReports:
    """Tests for list_reports method."""

    def test_list_empty_db(self, store):
        """Listing reports from an empty DB returns empty list."""
        reports = store.list_reports()
        assert reports == []

    def test_list_single_report(self, store):
        """Listing reports with one report returns a list of one."""
        store.save_report("call001", "Report 1")

        reports = store.list_reports()
        assert len(reports) == 1
        assert reports[0].call_id == "call001"

    def test_list_multiple_reports(self, store):
        """Listing reports returns all saved reports."""
        store.save_report("call001", "Report 1")
        store.save_report("call002", "Report 2")
        store.save_report("call003", "Report 3")

        reports = store.list_reports()
        assert len(reports) == 3

    def test_list_ordered_by_modified_at_desc(self, store):
        """Reports are ordered by modified_at descending (newest first)."""
        import time

        store.save_report("call001", "First")
        time.sleep(0.01)
        store.save_report("call002", "Second")
        time.sleep(0.01)
        store.save_report("call003", "Third")

        reports = store.list_reports()
        assert reports[0].call_id == "call003"
        assert reports[1].call_id == "call002"
        assert reports[2].call_id == "call001"

    def test_list_reflects_updates(self, store):
        """After updating a report, list order reflects the new modified_at."""
        import time

        store.save_report("call001", "First")
        time.sleep(0.01)
        store.save_report("call002", "Second")
        time.sleep(0.01)
        # Update call001 — it should now be "newest"
        store.save_report("call001", "Updated first")

        reports = store.list_reports()
        assert reports[0].call_id == "call001"
        assert reports[0].report_text == "Updated first"


class TestExportReports:
    """Tests for export_reports method."""

    def test_export_empty_db(self, store):
        """Exporting from empty DB returns empty list."""
        exported = store.export_reports()
        assert exported == []

    def test_export_without_loader(self, store):
        """Exporting without call_data_loader returns basic fields."""
        store.save_report("call001", "Report text")

        exported = store.export_reports()
        assert len(exported) == 1
        entry = exported[0]
        assert entry['call_id'] == "call001"
        assert entry['report_text'] == "Report text"
        assert 'created_at' in entry
        assert 'modified_at' in entry

    def test_export_with_loader(self, store):
        """Exporting with call_data_loader enriches entries with call data."""

        @dataclass
        class FakeCallData:
            customer_name: str = "João"
            company: str = "Empresa X"
            product: str = "Produto A"
            hangup_reason: str = "customer"

        def loader(call_id):
            return FakeCallData()

        store.save_report("call001", "Report text")

        exported = store.export_reports(call_data_loader=loader)
        assert len(exported) == 1
        entry = exported[0]
        assert entry['customer_name'] == "João"
        assert entry['company'] == "Empresa X"
        assert entry['product'] == "Produto A"
        assert entry['hangup_reason'] == "customer"

    def test_export_with_loader_returning_none(self, store):
        """Exporting with loader that returns None still includes basic fields."""

        def loader(call_id):
            return None

        store.save_report("call001", "Report text")

        exported = store.export_reports(call_data_loader=loader)
        assert len(exported) == 1
        entry = exported[0]
        assert entry['call_id'] == "call001"
        assert 'customer_name' not in entry

    def test_export_with_loader_raising_exception(self, store):
        """Exporting with a failing loader still includes the report entry."""

        def loader(call_id):
            raise RuntimeError("Parser error")

        store.save_report("call001", "Report text")

        exported = store.export_reports(call_data_loader=loader)
        assert len(exported) == 1
        assert exported[0]['call_id'] == "call001"
        assert 'customer_name' not in exported[0]

    def test_export_multiple_reports(self, store):
        """Exporting returns all reports."""
        store.save_report("call001", "Report 1")
        store.save_report("call002", "Report 2")

        exported = store.export_reports()
        assert len(exported) == 2
        call_ids = {e['call_id'] for e in exported}
        assert call_ids == {"call001", "call002"}

    def test_export_timestamps_are_iso_strings(self, store):
        """Exported timestamps are ISO 8601 strings."""
        store.save_report("call001", "Report text")

        exported = store.export_reports()
        entry = exported[0]
        # Should be parseable ISO strings
        datetime.fromisoformat(entry['created_at'])
        datetime.fromisoformat(entry['modified_at'])
