# PyInstaller spec — the full ForecastLens app.
# one-dir mode deliberately: one-file re-extracts to %TEMP% on every launch,
# which is slow and routinely quarantined by corporate antivirus.
#
# Build (Windows):  pyinstaller packaging/forecast.spec --noconfirm
import os

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

here = os.path.dirname(os.path.abspath(SPEC))
root = os.path.dirname(here)

datas = []
# Streamlit's static/ and runtime/ assets are not auto-detected.
datas += collect_data_files("streamlit", includes=["static/**/*", "runtime/**/*"])
datas += copy_metadata("streamlit")
# statsmodels ships datasets/templates the hooks miss.
datas += collect_data_files("statsmodels")
# plotly's package data (validators, templates)
datas += collect_data_files("plotly")
# The app's script files: streamlit executes them from disk, so they ship as
# data alongside the frozen modules. core/store/schema.sql rides with core.
datas += [
    (os.path.join(root, "app"), "app"),
    (os.path.join(root, "core", "store", "schema.sql"), os.path.join("core", "store")),
    # the default workbook the app preloads for every user
    (os.path.join(root, "tests", "fixtures", "sample_public.xlsx"), "data"),
]

hiddenimports = (
    collect_submodules("core")
    + collect_submodules("app")
    + collect_submodules("statsmodels")
    + [
        "streamlit",
        "streamlit.web.bootstrap",
        "streamlit.runtime.scriptrunner.magic_funcs",
        "joblib",
        "openpyxl",
        "plotly",
        "pydantic",
        "scipy.special._cdflib",
    ]
)

a = Analysis(
    [os.path.join(here, "entry.py")],
    pathex=[root],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "jupyter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ForecastLens",
    console=True,                 # keep the console: visible logs, no admin
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="ForecastLens",
)
