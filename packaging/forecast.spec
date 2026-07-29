# PyInstaller spec — the ForecastLens desktop build.
#
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
# statsmodels and scipy load data files at runtime (datasets, templates,
# distribution tables); plotly ships validators and chart templates.
datas += collect_data_files("statsmodels")
datas += collect_data_files("scipy")
datas += collect_data_files("plotly")
datas += copy_metadata("plotly")

# The app scripts are executed from disk by Streamlit, so they ship as data
# alongside the frozen modules. Everything read at runtime goes through
# core.paths.resource_path(), which resolves against sys._MEIPASS here.
datas += [
    (os.path.join(root, "app"), "app"),
    (os.path.join(root, "core", "store", "schema.sql"), os.path.join("core", "store")),
    # the default workbook the app preloads for every user
    (os.path.join(root, "tests", "fixtures", "sample_public.xlsx"), "data"),
]

# Imports PyInstaller's static analysis cannot see: statsmodels reaches for
# submodules lazily, scipy's special functions are loaded on demand, and
# Streamlit resolves its runtime pieces dynamically.
hiddenimports = (
    collect_submodules("core")
    + collect_submodules("app")
    + collect_submodules("statsmodels")
    + collect_submodules("scipy.special")
    + collect_submodules("scipy.optimize")
    + [
        "streamlit",
        "streamlit.web.bootstrap",
        "streamlit.runtime.scriptrunner.magic_funcs",
        "streamlit.testing.v1",
        # joblib spawns workers; the frozen build uses the threading backend
        # (core.pipeline) but loky is imported either way
        "joblib",
        "joblib.externals.loky.backend.context",
        "openpyxl",
        "openpyxl.cell._writer",
        "plotly",
        "plotly.graph_objects",
        "plotly.io._templates",
        "pydantic",
        "pydantic.deprecated.decorator",
        "sqlite3",
        "scipy.special._cdflib",
        "scipy._lib.array_api_compat.numpy.fft",
    ]
)

a = Analysis(
    [os.path.join(here, "entry.py")],
    pathex=[root],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ForecastLens",
    console=True,                 # keep the console: the startup self-check
                                  # prints here, and a silent exe is
                                  # undiagnosable for a non-technical user
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="ForecastLens",
)
