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
        marker={"size": 5}))

    if not forecast.empty:
        lo95 = forecast.get("lower_95")
        if lo95 is not None:
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
        fig.add_trace(go.Scatter(
            x=forecast["period"], y=forecast[forecast_col], name="forecast",
            mode="lines+markers", line={"color": FORECAST, "width": 2,
                                        "dash": "dash"}, marker={"size": 5}))

    if driver is not None and not driver.empty:
        fig.add_trace(go.Scatter(
            x=driver["period"], y=driver["driver_qty"], name="driver",
            mode="lines", line={"color": DRIVER, "width": 1, "dash": "dot"},
            yaxis="y2", opacity=0.7))
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
