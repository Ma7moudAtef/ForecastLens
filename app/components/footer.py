"""Build-identity footer.

Rendered identically by the web app and the frozen exe: when a user reports a
problem, the build stamp in the sidebar says exactly which build they ran.
"""
from __future__ import annotations

import streamlit as st

from core import paths
from core.version import VERSION, build_sha, build_time


def render(container=None) -> None:
    target = container if container is not None else st
    kind = "packaged app" if paths.is_frozen() else "web / source"
    target.divider()
    target.caption(
        f"**ForecastEngine {VERSION}** · {kind}  \n"
        f"build `{build_sha()}` · {build_time()}",
        help="Which build you are running. Quote the build id when "
             "reporting a problem — the exe and the web app show the same "
             "stamp, so it identifies the exact code that produced your "
             "results.")
    target.caption(f"Data folder: `{paths.data_dir()}`",
                   help="Where your database, working copy and exports are "
                        "stored. It is always a folder you can write to, "
                        "never inside the application itself.")
