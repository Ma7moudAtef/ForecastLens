"""Server-side file browser: lets the user navigate folders and pick a
workbook path instead of typing it. Meant for local/desktop use — on a
hosted deployment it browses the server's filesystem, where uploading is
usually the better route."""
from __future__ import annotations

from pathlib import Path

import streamlit as st


def _listdir(folder: Path, suffixes: tuple[str, ...]):
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except (PermissionError, OSError):
        return [], []
    dirs = [p for p in entries if p.is_dir() and not p.name.startswith(".")]
    files = [p for p in entries
             if p.is_file() and p.suffix.lower() in suffixes]
    return dirs, files


def path_picker(key: str, suffixes: tuple[str, ...] = (".xlsx",),
                start: Path | None = None) -> str | None:
    """Render a 📂 Browse popover. Returns the chosen file path (str) the
    moment the user confirms one, else None."""
    cwd_key, chosen_key = f"{key}_cwd", f"{key}_chosen"
    if cwd_key not in st.session_state:
        st.session_state[cwd_key] = str((start or Path.home()).resolve())

    with st.popover("📂 Browse…",
                    help="Navigate the computer's folders and pick a "
                         "workbook file instead of typing its path."):
        cwd = Path(st.session_state[cwd_key])
        st.caption(f"📁 {cwd}")
        dirs, files = _listdir(cwd, suffixes)

        nav_options = ["(stay here)", "⬆️ .. (up one level)"] + \
            [f"📁 {d.name}" for d in dirs]
        move = st.selectbox("Go to folder", nav_options, key=f"{key}_nav",
                            help="Choose a subfolder to enter, or go up one "
                                 "level.")
        if st.button("Open folder", key=f"{key}_open",
                     help="Enter the folder selected above."):
            if move == "⬆️ .. (up one level)":
                st.session_state[cwd_key] = str(cwd.parent)
            elif move.startswith("📁 "):
                st.session_state[cwd_key] = str(cwd / move[2:].strip())
            st.rerun()

        if files:
            pick = st.selectbox(
                "Workbook files in this folder",
                [f.name for f in files], key=f"{key}_file",
                help="Excel workbooks found in the current folder.")
            if st.button("✅ Use this file", key=f"{key}_use",
                         help="Set the selected file as the workbook path."):
                st.session_state[chosen_key] = str(cwd / pick)
                st.rerun()
        else:
            st.caption("No workbook files in this folder.")

    return st.session_state.pop(chosen_key, None)
