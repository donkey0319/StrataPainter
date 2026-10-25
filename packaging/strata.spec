# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for Strata. Build from the repo root with:
#     pyinstaller packaging/strata.spec --noconfirm
# Output: dist/Strata/ (Windows, Linux) or dist/Strata.app (macOS).
import os
import sys
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hiddenimports = [], [], []
# imgui_bundle carries its fonts as data; glfw ships its native library inside the
# package; moderngl picks its GL backend (glcontext) at runtime, so PyInstaller can't see it.
for pkg in ("imgui_bundle", "glfw", "moderngl", "glcontext", "OpenGL"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Optional extras: bundled when installed, skipped otherwise.
for opt in ("assimp_py", "h5py"):
    try:
        __import__(opt)
    except ImportError:
        continue
    d, b, h = collect_all(opt)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Strata",
    console=False,          # set True to see a terminal with tracebacks while debugging a build
    argv_emulation=sys.platform == "darwin",  # lets macOS pass dropped/opened files as argv
)
coll = COLLECT(exe, a.binaries, a.datas, name="Strata")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Strata.app",
        bundle_identifier="com.strata.painter",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": os.environ.get("STRATA_VERSION", "0.0.0"),
        },
    )
