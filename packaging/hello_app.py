"""Milestone-1 packaging spike: the smallest possible Streamlit app.

If this launches from a PyInstaller bundle on a clean Windows machine, the
packaging approach is proven; everything else is additive.
"""
import streamlit as st

st.set_page_config(page_title="ForecastLens packaging spike")
st.title("ForecastLens packaging spike")
st.write("If you can read this from the packaged exe, Streamlit bundling works.")
