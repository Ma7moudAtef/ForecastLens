"""Item identity helpers for the UI.

The logic lives in `core.identity` so the engine, the CLI and the frozen exe
share it — this module is only a re-export for the views.
"""
from core.identity import (  # noqa: F401
    ID_COLS,
    MISSING_DESCRIPTION,
    NO_ITEM,
    add_identity,
    build_labels,
    describe,
    description_lookup,
    expand_series_id,
    label_of,
)
