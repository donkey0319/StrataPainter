"""Portable Blender material delivery and genuine, bounded glTF 2.0 GLB export."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import zipfile
import numpy as np
from . import exporter, imageio
from .bundleio import MAX_BYTES, validate_archive


def _prepare(engine, size=None):
    if engine.mesh is None or not engine.sets:raise ValueError("Open a project before delivery")
    if any(ts.tiles is not None for ts in engine.sets):raise ValueError("Delivery currently supports single-tile material sets; export UDIM textures separately")
    if np.any(engine.mesh.uvs < -1e-6) or np.any(engine.mesh.uvs > 1.+1e-6):raise ValueError("Delivery requires single-tile UVs in [0,1]")
    if size is not None and (type(size) is not int or not 1<=size<=8192):raise ValueError("Delivery resolution must be 1..8192")
    engine.commit_edit();engine.end_stroke();engine.dirty=True;engine.update()
    material_indices=np.full(len(engine.mesh.indices),-1,np.int32)
    for i,ts in enumerate(engine.sets):
        if np.any(material_indices[ts.tri_ids]!=-1):raise ValueError("Texture sets overlap mesh ownership")
        material_indices[ts.tri_ids]=i
    if np.any(material_indices<0):raise ValueError("Texture sets do not cover the full mesh")
    return material_indices


def _positions(engine, require_meters=False):
    mesh=engine.mesh
    if mesh.extra.get("physical",{}).get("unit","unspecified")=="unspecified":
        if require_meters:raise ValueError("Declare source units before GLB delivery")
        return mesh.positions.copy(),"project"
    from .uvprep import meters_per_project_unit
    center,scale=mesh.extra.get("xform",([0,0,0],1.))
    center=np.asarray(center,dtype=np.float64)
    if center.shape!=(3,) or not np.isfinite(center).all():raise ValueError("Invalid source coordinate center")
    return ((mesh.positions+center*float(scale))*meters_per_project_unit(mesh)).astype(np.float32),"m"


def _values(engine, ts):
    data=exporter._SetData(engine,ts,"dilation_background",16)
    names=["basecolor","roughness","metallic","height","normal_opengl","emissive","opacity","ao"]
    if engine.shader_workflow["model"]=="spec_gloss":names += ["specular","glossiness"]
    if "coat" in engine.shader_workflow["bindings"]:names += ["coat","coat_roughness"]
    if engine.shader_workflow["displacement_meters"]:names += ["displacement_meters"]
    names += list(engine.user_channels)
    result={name:data.source(name).astype(np.float32) for name in names}
    if not engine.color.managed:
        for name in ("basecolor","emissive"):
            result[name]=np.maximum(result[name],0.)**2.2
    if any(not np.isfinite(v).all() for v in result.values()):raise ValueError("Delivery source contains non-finite values")
    return result


def _evaluations(engine, size):
    from contextlib import ExitStack
    from .evaluation import evaluate_set
    for ts in engine.sets:
        with ExitStack() as scope:
            source=ts if size is None or size==ts.res else scope.enter_context(evaluate_set(engine,ts,size))[0]
            yield ts,_values(engine,source)


def _publish(path, writer):
    path=Path(path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix=".strata-delivery-",suffix=path.suffix,dir=path.parent)
    os.close(fd)
    try:
        writer(Path(temporary));os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(path)


def export_blender(engine, path, size=None):
    """Atomically publish one verified ZIP containing mesh, material maps and setup code."""
    if Path(path).suffix.lower()!=".zip":raise ValueError("Blender delivery uses a .zip destination")
    assignments=_prepare(engine,size);positions,units=_positions(engine)
    with tempfile.TemporaryDirectory(prefix="strata-delivery-") as temporary:
        root=Path(temporary)
        np.savez_compressed(root/"geometry.npz",positions=positions,normals=engine.mesh.normals,uvs=engine.mesh.uvs,indices=engine.mesh.indices,material_indices=assignments)
        for name in ("blender_delivery.py","bundleio.py"):
            (root/name).write_bytes(Path(__file__).with_name(name).read_bytes())
        materials=[]
        for i,(ts,values) in enumerate(_evaluations(engine,size)):
            textures={};folder=root/"textures"/f"set_{i:03}";folder.mkdir(parents=True)
            for j,(semantic,array) in enumerate(values.items()):
                image=folder/f"channel_{j:02}.exr";imageio.write_image(str(image),array,"32f")
                textures[semantic]={"file":image.relative_to(root).as_posix(),"components":array.shape[2],"color_space":"linear_rec709" if semantic in ("basecolor","emissive") else "data"}
                if semantic=="normal_opengl":textures[semantic]["normal_convention"]="opengl_y_plus"
            materials.append({"name":ts.name,"pid":ts.pid,"model":engine.shader_workflow["model"],"textures":textures,"resolution":size or ts.res})
        meta={"version":1,"target":"blender","generator":"StrataPainter T19","geometry":{"file":"geometry.npz","name":engine.mesh.name,"units":units,"up_axis":"Y"},"materials":materials,"workflow":copy.deepcopy(engine.shader_workflow),"color":{"working":"linear_rec709","source":engine.color.metadata(),"legacy_conversion":"preview_gamma_2.2" if not engine.color.managed else None},"normal":"finished_tangent_opengl_y_plus","limits":["single-tile material sets","target BRDF approximation; lighting pixel parity unclaimed"],"files":{}}
        for file in sorted(root.rglob("*")):
            if file.is_file():
                content=file.read_bytes();meta["files"][file.relative_to(root).as_posix()]={"bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()}
        if sum(v["bytes"] for v in meta["files"].values())>MAX_BYTES:raise MemoryError("Delivery bundle exceeds the 512 MiB budget")
        (root/"manifest.json").write_text(json.dumps(meta,indent=2,allow_nan=False),encoding="utf-8")
        def write(destination):
            with zipfile.ZipFile(destination,"w",zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(root.rglob("*")):
                    if file.is_file():archive.write(file,file.relative_to(root).as_posix())
            validate_archive(destination)
        return _publish(path,write)


def export_glb(engine,path,size=None):
    """glTF 2.0 mesh/material interchange with embedded PNGs, MR and clearcoat."""
    if Path(path).suffix.lower()!=".glb":raise ValueError("glTF binary delivery requires .glb")
    workflow=engine.shader_workflow
    if workflow["model"]!="metal_rough" or workflow["displacement_meters"]:
        raise ValueError("GLB supports metallic/roughness and clearcoat; use Blender delivery for specular/glossiness or displacement")
    if set(engine.user_channels)-set(workflow["bindings"].values()):raise ValueError("GLB cannot preserve arbitrary user channels; use Blender delivery")
    assignments=_prepare(engine,size);positions,_=_positions(engine,True)
    document={"asset":{"version":"2.0","generator":"StrataPainter"},"scene":0,"scenes":[{"nodes":[0]}],"nodes":[{"mesh":0,"name":engine.mesh.name}],"meshes":[{"primitives":[]}],"buffers":[{}],"bufferViews":[],"accessors":[],"materials":[],"images":[],"textures":[],"samplers":[{"magFilter":9729,"minFilter":9729,"wrapS":33071,"wrapT":33071}]}
    binary=bytearray()
    def view(content,target=None):
        binary.extend(b"\0"*((-len(binary))%4));offset=len(binary);binary.extend(content)
        record={"buffer":0,"byteOffset":offset,"byteLength":len(content)}
        if target:record["target"]=target
        document["bufferViews"].append(record);return len(document["bufferViews"])-1
    def accessor(array,kind,component,target):
        array=np.ascontiguousarray(array,dtype="<u4" if component==5125 else "<f4")
        record={"bufferView":view(array.tobytes(),target),"componentType":component,"count":len(array),"type":kind}
        if kind=="VEC3":record.update(min=array.min(0).tolist(),max=array.max(0).tolist())
        document["accessors"].append(record);return len(document["accessors"])-1
    uv=engine.mesh.uvs.copy();uv[:,1]=1.-uv[:,1]
    attributes={"POSITION":accessor(positions,"VEC3",5126,34962),"NORMAL":accessor(engine.mesh.normals,"VEC3",5126,34962),"TEXCOORD_0":accessor(uv,"VEC2",5126,34962)}
    from PIL import Image
    def texture(array,color=False):
        if color:array=exporter._lin2srgb(array)
        array=np.uint8(np.clip(array,0,1)*255+.5)
        if array.shape[2]==1:array=array[:,:,0]
        stream=io.BytesIO();Image.fromarray(array).save(stream,format="PNG")
        document["images"].append({"bufferView":view(stream.getvalue()),"mimeType":"image/png"})
        document["textures"].append({"sampler":0,"source":len(document["images"])-1});return {"index":len(document["textures"])-1}
    for i,(ts,values) in enumerate(_evaluations(engine,size)):
        c=values["basecolor"]
        if np.any(c<0) or np.any(c>1):raise ValueError("GLB base color must be in [0,1]; use the HDR Blender bundle")
        rgba=np.concatenate([exporter._lin2srgb(c),values["opacity"]],2)
        orm=np.concatenate([values["ao"],values["roughness"],values["metallic"]],2)
        material={"name":ts.name,"pbrMetallicRoughness":{"baseColorFactor":[1,1,1,1],"baseColorTexture":texture(rgba),"metallicFactor":1.,"roughnessFactor":1.,"metallicRoughnessTexture":texture(orm)},"normalTexture":texture(values["normal_opengl"]),"occlusionTexture":{"index":len(document["textures"])-2},"emissiveFactor":[1,1,1],"doubleSided":True,"extras":{"strata_set_pid":ts.pid}}
        if float(values["opacity"].min())<.999:material["alphaMode"]="BLEND"
        if np.any(values["emissive"]<0):raise ValueError("GLB emissive values must be nonnegative")
        strength=max(1.,float(values["emissive"].max()));material["emissiveTexture"]=texture(values["emissive"]/strength,True)
        if strength>1:
            document.setdefault("extensionsUsed",[]).append("KHR_materials_emissive_strength")
            material.setdefault("extensions",{})["KHR_materials_emissive_strength"]={"emissiveStrength":strength}
        if "coat" in values:
            coat=np.concatenate([values["coat"],values["coat_roughness"],np.zeros_like(values["coat"])],2);info=texture(coat)
            document.setdefault("extensionsUsed",[]).append("KHR_materials_clearcoat")
            material.setdefault("extensions",{})["KHR_materials_clearcoat"]={"clearcoatFactor":1.,"clearcoatTexture":info,"clearcoatRoughnessFactor":1.,"clearcoatRoughnessTexture":info}
        document["materials"].append(material)
        indices=engine.mesh.indices[assignments==i].reshape(-1)
        if len(indices):document["meshes"][0]["primitives"].append({"attributes":attributes,"indices":accessor(indices,"SCALAR",5125,34963),"material":i,"mode":4})
    if "extensionsUsed" in document:document["extensionsUsed"]=sorted(set(document["extensionsUsed"]))
    document["buffers"][0]["byteLength"]=len(binary)
    encoded=json.dumps(document,separators=(",",":"),allow_nan=False).encode();encoded+=b" "*((-len(encoded))%4);binary.extend(b"\0"*((-len(binary))%4))
    payload=struct.pack("<III",0x46546c67,2,12+8+len(encoded)+8+len(binary))+struct.pack("<II",len(encoded),0x4e4f534a)+encoded+struct.pack("<II",len(binary),0x004e4942)+binary
    if len(payload)>MAX_BYTES:raise MemoryError("GLB exceeds the 512 MiB budget")
    return _publish(path,lambda destination:destination.write_bytes(payload))
