"""CPU-only delivery archive validation, shared by the standalone Blender importer."""
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import zipfile

VERSION = 1
MAX_BYTES = 512 * 1024**2


def safe_name(name):
    p = PurePosixPath(name)
    reserved={"CON","PRN","AUX","NUL"}|{"COM"+str(i) for i in range(1,10)}|{"LPT"+str(i) for i in range(1,10)}
    return isinstance(name,str) and bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name and ":" not in name and str(p)==name and all(re.fullmatch(r"[A-Za-z0-9_.-]+",part) and not part.endswith(".") and part.partition(".")[0].upper() not in reserved for part in p.parts)


def validate_archive(path):
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist()
        if len(infos)>256 or sum(i.file_size for i in infos)>MAX_BYTES:
            raise ValueError("Delivery archive exceeds the 512 MiB/256-file budget")
        names=[i.filename for i in infos]
        if any(not safe_name(n) for n in names) or len(set(n.casefold() for n in names))!=len(names):
            raise ValueError("Unsafe or duplicate delivery path")
        if "manifest.json" not in names or archive.getinfo("manifest.json").file_size>1024**2:
            raise ValueError("Missing or oversized delivery manifest")
        meta=json.loads(archive.read("manifest.json"))
        if meta.get("version")!=VERSION or meta.get("target")!="blender" or not isinstance(meta.get("materials"),list) or not meta["materials"]:
            raise ValueError("Unsupported delivery manifest")
        files=meta.get("files")
        if not isinstance(files,dict) or set(files)!=set(names)-{"manifest.json"}:
            raise ValueError("Delivery file inventory differs from manifest")
        for name,record in files.items():
            if record.get("bytes")!=archive.getinfo(name).file_size or hashlib.sha256(archive.read(name)).hexdigest()!=record.get("sha256"):
                raise ValueError("Delivery resource changed: "+name)
        geometry=meta.get("geometry",{})
        if geometry.get("file") not in files or geometry.get("units") not in ("m","project") or geometry.get("up_axis")!="Y":
            raise ValueError("Invalid delivery geometry description")
        pids=set()
        for material in meta["materials"]:
            if not isinstance(material.get("pid"),str) or material["pid"] in pids:
                raise ValueError("Invalid delivery material identity")
            pids.add(material["pid"])
            if material.get("model") not in ("metal_rough","spec_gloss") or not isinstance(material.get("textures"),dict):
                raise ValueError("Invalid delivery material")
            required={"basecolor","roughness","metallic","normal_opengl","emissive","opacity"}
            if material["model"]=="spec_gloss":required|={"specular","glossiness"}
            if not required<=material["textures"].keys():raise ValueError("Missing required material source")
            for semantic,texture in material["textures"].items():
                if texture.get("file") not in files or texture.get("color_space") not in ("linear_rec709","data") or texture.get("components") not in (1,3):
                    raise ValueError("Invalid delivery texture: "+semantic)
            if material["textures"]["normal_opengl"].get("normal_convention")!="opengl_y_plus":raise ValueError("Invalid normal convention")
        return meta


def unpack(path, destination):
    meta=validate_archive(path)
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            output=root.joinpath(*PurePosixPath(name).parts)
            if not output.resolve().is_relative_to(root):raise ValueError("Delivery path escapes destination")
            output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(archive.read(name))
    return meta


def geometry(path, material_count):
    import numpy as np
    with zipfile.ZipFile(path) as nested:
        if sum(i.file_size for i in nested.infolist())>MAX_BYTES:raise ValueError("Geometry exceeds decode budget")
    with np.load(path,allow_pickle=False) as archive:
        values={name:archive[name] for name in ("positions","normals","uvs","indices","material_indices")}
    p,n,uv,tri,mat=(values[k] for k in ("positions","normals","uvs","indices","material_indices"))
    if p.ndim!=2 or p.shape[1]!=3 or n.shape!=p.shape or uv.shape!=(len(p),2) or tri.ndim!=2 or tri.shape[1]!=3 or mat.shape!=(len(tri),):raise ValueError("Invalid delivery geometry dimensions")
    if any(not np.isfinite(v).all() for v in values.values()) or not np.issubdtype(tri.dtype,np.integer) or not np.issubdtype(mat.dtype,np.integer):raise ValueError("Invalid delivery geometry values")
    if not len(tri) or tri.min()<0 or tri.max()>=len(p) or mat.min()<0 or mat.max()>=material_count:raise ValueError("Invalid delivery geometry indices")
    if np.any(np.linalg.norm(n,axis=1)<1e-8):raise ValueError("Invalid zero geometry normal")
    return values
