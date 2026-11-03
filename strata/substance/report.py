"""Lossless HBO metadata retention and structured, conservative import coverage."""
import hashlib
from collections import Counter
from pathlib import Path
from .hbo import HObj, Prim


def encode(value):
    if isinstance(value,HObj):return {"$object":value.type,"fields":{k:encode(v) for k,v in value.fields.items()}}
    if isinstance(value,Prim):return {"$primitive":value.code,"hex":value.raw.hex()}
    if isinstance(value,bytes):return {"$bytes":value.hex()}
    if isinstance(value,(list,tuple)):return [encode(v) for v in value]
    if isinstance(value,dict):return {k:encode(v) for k,v in value.items()}
    return value


def decode(value):
    if isinstance(value,list):return [decode(v) for v in value]
    if isinstance(value,dict):
        if "$object" in value:return HObj(value["$object"],{k:decode(v) for k,v in value["fields"].items()})
        if "$primitive" in value:return Prim(value["$primitive"],bytes.fromhex(value["hex"]))
        if "$bytes" in value:return bytes.fromhex(value["$bytes"])
        return {k:decode(v) for k,v in value.items()}
    return value


def job_dict(job):
    return {key:encode(value) for key,value in job.__dict__.items()}


def job_load(value):
    from .convert import PaintJob
    return PaintJob(**{key:decode(v) for key,v in value.items()})


def compatibility(spf,root,notes,layers=()):
    from .hbo import walk
    counts=Counter()
    walk(root,lambda obj,path:counts.update([obj.type]))
    translated={"DataLayerColor","DataLayerGroup","DataActionFill","DataActionPaint","DataActionEraser","DataActionLevels","DataActionInvert","DataSourceUniform","DataSourceBitmap"}
    coverage=[{"feature":name,"count":count,"retention":"editable_translation" if name in translated else "reported_approximation" if name in ("DataSourceProcedural","DataActionFilterProcedural","DataLayerInstance") else "metadata_only","appearance":"unvalidated"} for name,count in sorted(counts.items()) if name.startswith(("DataAction","DataSource","DataLayer"))]
    native=sum(1 for layer in layers for item in layer.walk() for effect in item.layer.effects+item.layer.mask_effects if effect.kind=="graph")
    return {"schema":1,"source":{"path":spf.path,"sha256":hashlib.sha256(Path(spf.path).read_bytes()).hexdigest(),
            "kind":spf.kind,"painter_version":spf.painter_version() or "unknown",
            "datasets":[{"path":name,"encoding":encoding,"data_version":version} for name,(_,encoding,version) in spf._decoded.items()]},
            "read_success":True,"features":dict(sorted(counts.items())),"coverage":coverage,"unexecuted_features":[row for row in coverage if row["retention"]=="metadata_only"],
            "variant_errors":getattr(spf,"_variant_errors",[]),"stroke_fidelity":{"embedded_bitmap_alpha":"mapped_when_available","explicit_emitter_jitter":"mapped","symmetry":"metadata_only","proprietary_tips":"not_executed"},"retained_editability":{"native_graphs":native,"layers":sum(1 for layer in layers for _ in layer.walk())},
            "appearance":{"status":"unvalidated","reference":None,"deviation":None},
            "conversion_notes":list(notes),"skipped_operations":[n for n in notes if any(word in n.lower() for word in ("skip","left out","ignored","only the first","merged"))],
            "replay":{"status":"not_started","truncated":False},"source_metadata":encode(root)}
