# PyInstaller spec — Milestone-1 packaging spike (hello-world Streamlit exe).
# one-dir mode deliberately: one-file re-extracts to %TEMP% on every launch,
# which is slow and routinely quarantined by corporate antivirus.
import os

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

here = os.path.dirname(os.path.abspath(SPEC))

datas = [(os.path.join(here, "hello_app.py"), ".")]
# Streamlit's static/ and runtime/ assets are not auto-detected.
datas += collect_data_files("streamlit", includes=["static/**/*", "runtime/**/*"])
datas += copy_metadata("streamlit")

a = Analysis(
    [os.path.join(here, "hello_entry.py")],
    pathex=[here],
    datas=datas,
    hiddenimports=[
        "streamlit",
        "streamlit.web.bootstrap",
        "streamlit.runtime.scriptrunner.magic_funcs",
    ],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="forecastlens-hello",
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="forecastlens-hello",
)
