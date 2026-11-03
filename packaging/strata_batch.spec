# Console-only batch build: pyinstaller packaging/strata_batch.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_all
ROOT=os.path.abspath(os.path.join(SPECPATH,".."))
datas=[(os.path.join(ROOT,"strata",name),"strata") for name in ("blender_delivery.py","bundleio.py","unwrap_worker.py")]
binaries=[];hiddenimports=[]
for package in ("moderngl","glcontext","OpenGL"):
    data,binary,hidden=collect_all(package);datas+=data;binaries+=binary;hiddenimports+=hidden
for optional in ("assimp_py","h5py","PyOpenColorIO"):
    try:__import__(optional)
    except ImportError:continue
    data,binary,hidden=collect_all(optional);datas+=data;binaries+=binary;hiddenimports+=hidden
a=Analysis([os.path.join(ROOT,"run_batch.py")],pathex=[ROOT],binaries=binaries,datas=datas,hiddenimports=hiddenimports,excludes=["tkinter","matplotlib","imgui_bundle","glfw"],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name="StrataBatch",console=True)
coll=COLLECT(exe,a.binaries,a.datas,name="StrataBatch")
