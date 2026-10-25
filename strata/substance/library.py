"""Find Substance 3D Painter smart materials and smart masks on disk, for Strata's Assets panel.

Looks where Painter keeps them (starter assets of the installed Painter, and the user's own shelf),
plus any extra folders listed in Strata's settings ("substance_folders"). Thumbnails come from the
preview Painter embeds in each file; they are decoded on a worker thread and cached as small PNGs
in ~/.strata/thumbs so the panel opens instantly next time. Conversions are cached per file.
"""
from __future__ import annotations

import glob
import hashlib
import os
import queue
import sys
import threading
from dataclasses import dataclass

import numpy as np

THUMB_PX = 128
KIND_EXT = {".spsm": "smart_material", ".spmsk": "smart_mask"}


@dataclass
class LibraryItem:
    name: str
    path: str
    kind: str          # smart_material | smart_mask
    category: str      # sub-folder, e.g. "Metal"
    source: str        # "Starter assets", "Your assets", or the folder name


def default_roots():
    """(label, folder) pairs where Painter keeps shelf content on this machine."""
    home = os.path.expanduser("~")
    docs = [os.path.join(home, "Documents")]
    if sys.platform == "win32":
        try:
            import ctypes.wintypes
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # CSIDL_PERSONAL
            if buf.value and buf.value not in docs:
                docs.insert(0, buf.value)
        except Exception:
            pass
    roots = []
    for d in docs:
        roots += [("Your assets", os.path.join(d, "Adobe", "Adobe Substance 3D Painter", "assets")),
                  ("Your assets", os.path.join(d, "Allegorithmic", "Substance Painter", "shelf"))]
    installs = []
    if sys.platform == "win32":
        for pf in {os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")}:
            if pf:
                installs += [os.path.join(pf, "Adobe", "Adobe Substance 3D Painter", "resources"),
                             os.path.join(pf, "Allegorithmic", "Substance Painter", "resources")]
        installs += glob.glob(r"C:\Program Files (x86)\Steam\steamapps\common\Substance 3D Painter*\resources")
    elif sys.platform == "darwin":
        installs += ["/Applications/Adobe Substance 3D Painter/Adobe Substance 3D Painter.app/Contents/Resources",
                     "/Applications/Adobe Substance 3D Painter.app/Contents/Resources"]
    else:
        installs += ["/opt/Adobe/Adobe_Substance_3D_Painter/resources", "/opt/Allegorithmic/Substance_Painter/resources"]
    for inst in installs:
        roots.append(("Starter assets", os.path.join(inst, "starter_assets")))
        roots.append(("Starter assets", os.path.join(inst, "shelf", "allegorithmic")))
    return roots


def scan(extra_folders=(), include_defaults=True):
    """List smart materials / masks. Returns (items, folders_found)."""
    roots = (default_roots() if include_defaults else []) + [(os.path.basename(f.rstrip("/\\")) or f, f)
                                                             for f in extra_folders]
    items, seen, found = [], set(), []
    for label, root in roots:
        if not root or not os.path.isdir(root):
            continue
        found.append(root)
        for sub, kind in (("smart-materials", "smart_material"), ("smart-masks", "smart_mask"), ("", None)):
            base = os.path.join(root, sub) if sub else root
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, files in os.walk(base):
                for fn in files:
                    ext = os.path.splitext(fn)[1].lower()
                    k = KIND_EXT.get(ext)
                    if k is None or (kind is not None and k != kind):
                        continue
                    path = os.path.join(dirpath, fn)
                    key = os.path.normcase(os.path.abspath(path))
                    if key in seen:
                        continue
                    seen.add(key)
                    rel = os.path.relpath(dirpath, base)
                    cat = "" if rel in (".", "") else rel.replace("\\", "/").split("/")[0]
                    items.append(LibraryItem(os.path.splitext(fn)[0], path, k, cat, label))
    items.sort(key=lambda i: (i.kind, i.source != "Your assets", i.category.lower(), i.name.lower()))
    return items, found


# ----------------------------------------------------------------------------- thumbnails
def _cache_dir():
    d = os.path.join(os.path.expanduser("~"), ".strata", "thumbs")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return d


def _cache_key(path):
    try:
        st = os.stat(path)
        sig = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = path
    return hashlib.sha1(sig.encode("utf-8", "replace")).hexdigest()[:20]


def load_thumbnail(path, size=THUMB_PX):
    """RGBA uint8 (size, size, 4) or None. Uses / fills the disk cache."""
    from PIL import Image
    cdir = _cache_dir()
    cfile = os.path.join(cdir, _cache_key(path) + ".png") if cdir else None
    if cfile and os.path.exists(cfile):
        try:
            return np.asarray(Image.open(cfile).convert("RGBA"), np.uint8)
        except Exception:
            pass
    from .importer import read_thumbnail
    a = read_thumbnail(path)
    if a is None:
        return None
    im = Image.fromarray(a).convert("RGBA").resize((size, size), Image.LANCZOS)
    if cfile:
        try:
            im.save(cfile)
        except OSError:
            pass
    return np.asarray(im, np.uint8)


class ThumbLoader:
    """Decodes thumbnails on a worker thread; call poll() on the GL thread to receive them."""

    def __init__(self):
        self._q_in = queue.Queue()
        self._q_out = queue.Queue()
        self._requested = set()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def request(self, path):
        if path not in self._requested:
            self._requested.add(path)
            self._q_in.put(path)

    def _run(self):
        while True:
            path = self._q_in.get()
            try:
                img = load_thumbnail(path)
            except Exception:
                img = None
            self._q_out.put((path, img))

    def poll(self, limit=16):
        out = []
        for _ in range(limit):
            try:
                out.append(self._q_out.get_nowait())
            except queue.Empty:
                break
        return out
