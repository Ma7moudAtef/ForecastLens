"""Abstract data source. ERP connectors become drop-in implementations in v2."""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.io.schema import RawTables


class DataSource(ABC):
    """Anything that can produce the four internal tables."""

    @abstractmethod
    def load(self) -> RawTables:
        """Read, map external→internal columns, coerce dtypes."""
        raise NotImplementedError
