"""Plotly figure builders. History + forecast + intervals + driver overlay."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

HISTORY = "#1f77b4"
FORECAST = "#d62728"
BAND80 = "rgba(214, 39, 40, 0.25)"
BAND95 = "rgba(214, 39, 40, 0.12)"
DRIVER = "#7f7f7f"
STANDARD = "#2ca02c"

#: order matters — it is the order of `customdata` in the hover template
BAND_COLUMNS = ("lower_80", "upper_80", "lower_95", "upper_95")

#: 4 significant digits with the trailing zeros trimmed: the same template has
#: to read well for a rate of 0.0047 and a demand of 12,400
_NUM = ",.4~g"
_FORECAST_HOVER = f"forecast <b>%{{y:{_NUM}}}</b><extra></extra>"
_FORECAST_HOVER_WITH_BANDS = (
    f"forecast <b>%{{y:{_NUM}}}</b><br>"
    f"80% range %{{customdata[0]:{_NUM}}} – %{{customdata[1]:{_NUM}}}<br>"
    f"95% range %{{customdata[2]:{_NUM}}} – %{{customdata[3]:{_NUM}}}"
    "<extra></extra>")
_HISTORY_HOVER = f"history <b>%{{y:{_NUM}}}</b><extra></extra>"
_DRIVER_HOVER = f"production %{{y:{_NUM}}}<extra></extra>"


def series_chart(history: pd.DataFrame, forecast: pd.DataFrame,
                 value_col: str, forecast_col: str,
                 driver: pd.DataFrame | None = None,
                 std_rate: float | None = None,
                 title: str = "") -> go.Figure:
    """history: period, <value_col>, [driver_qty]; forecast: period,
    <forecast_col>, lower/upper bands (matching scale)."""
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=history["period"], y=history[value_col], name="history",
        mode="lines+markers", line={"color": HISTORY, "width": 2},
        marker={"size": 5}, hovertemplate=_HISTORY_HOVER))

    if not forecast.empty:
        has_bands = all(forecast.get(c) is not None for c in BAND_COLUMNS)
        if has_bands:
            fig.add_trace(go.Scatter(
                x=forecast["period"], y=forecast["upper_95"], name="95% band",
                line={"width": 0}, showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(
                x=forecast["period"], y=forecast["lower_95"], name="95% band",
                fill="tonexty", fillcolor=BAND95, line={"width": 0},
                hoverinfo="skip"))
            fig.add_trace(go.Scatter(
                x=forecast["period"], y=forecast["upper_80"], name="80% band",
                line={"width": 0}, showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(
                x=forecast["period"], y=forecast["lower_80"], name="80% band",
                fill="tonexty", fillcolor=BAND80, line={"width": 0},
                hoverinfo="skip"))
        # The four band traces are invisible fills, so they are skipped on
        # hover — otherwise the tooltip lists four unnamed numbers. Their
        # values ride along on the forecast point instead, which is where a
        # reader looks for them.
        fig.add_trace(go.Scatter(
            x=forecast["period"], y=forecast[forecast_col], name="forecast",
            mode="lines+markers", line={"color": FORECAST, "width": 2,
                                        "dash": "dash"}, marker={"size": 5},
            customdata=(forecast[list(BAND_COLUMNS)].to_numpy()
                        if has_bands else None),
            hovertemplate=(_FORECAST_HOVER_WITH_BANDS if has_bands
                           else _FORECAST_HOVER)))

    if driver is not None and not driver.empty:
        fig.add_trace(go.Scatter(
            x=driver["period"], y=driver["driver_qty"], name="driver",
            mode="lines", line={"color": DRIVER, "width": 1, "dash": "dot"},
            yaxis="y2", opacity=0.7, hovertemplate=_DRIVER_HOVER))
        fig.update_layout(yaxis2={"overlaying": "y", "side": "right",
                                  "title": "driver", "showgrid": False})

    if std_rate is not None:
        fig.add_hline(y=std_rate, line_color=STANDARD, line_dash="dashdot",
                      annotation_text="standard rate",
                      annotation_position="top left")

    fig.update_layout(
        title=title, hovermode="x unified", height=430,
        margin={"l": 40, "r": 40, "t": 50, "b": 40},
        legend={"orientation": "h", "y": -0.18},
        xaxis={"type": "category", "tickangle": -45})
    return fig
