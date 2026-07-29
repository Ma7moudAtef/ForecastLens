"""Shared UI helpers.

Every control, section and chart in the app carries an explanation the user
can read by hovering. Streamlit widgets take a `help=` argument (the ❓ icon);
elements that do not accept one — charts above all — get `help_icon()`, a
small ❓ with a native browser tooltip.
"""
from __future__ import annotations

import html

import streamlit as st


def help_icon(text: str, inline: bool = True) -> None:
    """Render a ❓ whose tooltip appears on hover. For elements without a
    `help=` parameter (st.plotly_chart, st.dataframe captions, headings)."""
    safe = html.escape(text, quote=True)
    style = ("cursor:help;opacity:.65;font-size:0.9em;"
             "border-bottom:1px dotted currentColor;")
    st.markdown(
        f'<span title="{safe}" style="{style}">❓</span>',
        unsafe_allow_html=True)


def section(title: str, help_text: str, level: str = "subheader") -> None:
    """A heading that carries its own explanation icon."""
    fn = getattr(st, level)
    fn(title, help=help_text)


def chart(fig, help_text: str, key: str | None = None) -> None:
    """A Plotly chart with a hover explanation above it."""
    left, right = st.columns([0.97, 0.03])
    with right:
        help_icon(help_text)
    st.plotly_chart(fig, width="stretch", key=key)


def table(df, help_text: str, column_help: dict[str, str] | None = None,
          **kwargs) -> None:
    """A dataframe with a hover explanation.

    `column_help` puts a ❓ on individual column headers as well, so a reader
    can ask what a single column means without hunting for a legend.
    """
    left, right = st.columns([0.97, 0.03])
    with right:
        help_icon(help_text)
    if column_help:
        kwargs.setdefault("column_config", column_config(df, column_help))
    st.dataframe(df, width="stretch", **kwargs)


def column_config(df, column_help: dict[str, str]) -> dict:
    """Per-column ❓ tooltips for st.dataframe, for the columns that have
    an explanation and are actually present."""
    return {name: st.column_config.Column(name, help=text)
            for name, text in column_help.items()
            if text and name in getattr(df, "columns", [])}
