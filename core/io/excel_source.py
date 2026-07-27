"""Excel implementation of DataSource with upload hardening.

- extension allowlist (.xlsx only — .xlsm and friends are rejected)
- file size cap
- openpyxl read-only mode; macros are never executed (xlsx cannot carry them)
- schema validated before any processing
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.config import AppConfig
from core.io.datasource import DataSource
from core.io.schema import (
    OPTIONAL_SHEETS,
    REQUIRED_SHEETS,
    RawTables,
    SchemaError,
    build_raw_tables,
)
from core.log import get_logger

log = get_logger("io.excel")


class ExcelSource(DataSource):
    def __init__(self, path: str | Path, app_config: AppConfig | None = None):
        self.path = Path(path)
        self.app_config = app_config or AppConfig()

    def _harden(self) -> None:
        if not self.path.exists():
            raise SchemaError(f"file not found: {self.path}")
        ext = self.path.suffix.lower()
        if ext not in self.app_config.allowed_upload_extensions:
            raise SchemaError(
                f"extension '{ext}' is not allowed; "
                f"allowed: {self.app_config.allowed_upload_extensions}")
        size_mb = self.path.stat().st_size / (1024 * 1024)
        if size_mb > self.app_config.max_upload_mb:
            raise SchemaError(
                f"file is {size_mb:.0f} MB, above the "
                f"{self.app_config.max_upload_mb} MB cap")

    def load(self) -> RawTables:
        self._harden()
        log.info("loading workbook %s", self.path.name)
        with pd.ExcelFile(self.path, engine="openpyxl") as xl:
            present = set(xl.sheet_names)
            sheets = {
                name: xl.parse(name)
                for name in (*REQUIRED_SHEETS, *OPTIONAL_SHEETS)
                if name in present
            }
        return build_raw_tables(sheets, source_name=self.path.name)
