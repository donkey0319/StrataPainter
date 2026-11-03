"""Version 1 explicit Python extension and batch command API; no project autoloading."""
import copy
import importlib
import inspect
import json
from pathlib import Path
import re

API_VERSION=1
_RESERVED={"project","material","layer","channel","shader","brush","textures","delivery"}


class Registry:
    def __init__(self):self._commands={}

    def register(self,name,handler,description="",*,_builtin=False):
        if not isinstance(name,str) or not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*",name):raise ValueError("Use namespace.command identifiers")
        if name in self._commands or (not _builtin and name.partition(".")[0] in _RESERVED):raise ValueError("Duplicate or reserved extension command")
        if not callable(handler):raise TypeError("Command handler must be callable")
        signature=inspect.signature(handler)
        if not signature.parameters or next(iter(signature.parameters))!="engine":raise TypeError("Command handler's first parameter must be engine")
        self._commands[name]=(handler,signature,description)

    def validate(self,name,params):
        if name not in self._commands:raise ValueError("Unknown command: "+str(name))
        if not isinstance(params,dict):raise ValueError("Command params must be an object")
        self._commands[name][1].bind(None,**params)

    def execute(self,engine,name,params=None):
        params=copy.deepcopy({} if params is None else params);self.validate(name,params)
        result=self._commands[name][0](engine,**params)
        json.dumps(result,allow_nan=False)  # Results have the same contract in Python and CLI.
        return result

    def describe(self):
        return {name:{"signature":str(value[1]),"description":value[2]} for name,value in self._commands.items()}


def load_extension(registry,module_name):
    if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*",module_name):raise ValueError("Extension must be an explicitly named Python module")
    module=importlib.import_module(module_name)
    if getattr(module,"STRATA_EXTENSION_API",None)!=API_VERSION:raise ValueError("Extension API version mismatch")
    module.register(registry)


def _layer(engine,pid=None):
    if pid is None:
        if engine.layer is None:raise ValueError("Select a layer")
        return engine.layer
    layer=next((l for l in engine.all_layers_all_sets() if l.pid==pid),None)
    if layer is None:raise ValueError("Unknown layer identity")
    return layer


def builtins():
    registry=Registry()
    def add(name,handler,description):registry.register(name,handler,description,_builtin=True)
    def new(engine,mesh="Canister",resolution=256,source_unit=None,tangent_basis="legacy",ao_samples=16):
        from .mesh import BUILTIN_MESHES,load_mesh
        source=mesh if mesh in BUILTIN_MESHES else load_mesh(mesh)
        engine.new_project(source,res=resolution,source_unit=source_unit,tangent_basis=tangent_basis,ao_samples=ao_samples)
        return {"sets":[{"index":i,"name":ts.name,"pid":ts.pid} for i,ts in enumerate(engine.sets)]}
    def load(engine,path):engine.load(path);return {"sets":len(engine.sets)}
    def save(engine,path,portable=False):engine.save(path,portable=portable);return str(Path(path).resolve())
    def select(engine,index):engine.set_active(index);return engine.ts.pid
    def resize(engine,resolution,index=None):return engine.set_resolution(resolution,ts_index=index)
    def layer_add(engine,kind="paint",name=None):return engine.add_layer(kind=kind,name=name).pid
    def layer_edit(engine,values,pid=None):return engine.set_properties(_layer(engine,pid),**values)
    def layer_select(engine,pid):
        layer=_layer(engine,pid)
        index=next(i for i,ts in enumerate(engine.sets) if any(l is layer for l in engine._walk(ts.layers)))
        engine.set_active(index);engine.select(layer);return layer.pid
    def declare(engine,name,default=0.,label=None):return engine.add_user_channel(name,default,label)
    def fill(engine,key,value,enabled=True,pid=None):return engine.set_user_channel(key,_layer(engine,pid),value=value,enabled=enabled)
    def shader(engine,settings):return engine.set_shader_workflow(**settings)
    def uv_path(engine,points,brush=None,viewport=(512,512),seed=17):
        from .layers import Brush
        from .viewinput import UVMapping
        if not isinstance(points,list) or not 1<=len(points)<=100000:raise ValueError("UV path requires 1..100000 samples")
        if brush:
            if not isinstance(brush,dict) or set(brush)-Brush.__dataclass_fields__.keys():raise ValueError("Unknown brush field")
            engine.end_stroke();engine.brush.load_dict(brush)
        mapping=UVMapping(tuple(viewport))
        if not engine.begin_uv_stroke(points[0],mapping,seed=seed):raise ValueError("UV stroke cannot start on this target")
        try:
            for point in points[1:]:engine.stroke_uv_to(point)
            engine.end_stroke()
        except Exception:engine.cancel_stroke();raise
        return {"samples":len(points)}
    def textures(engine,folder,template="$workflow",size=None):
        from . import exporter
        return exporter.export_textures(engine,folder,exporter.workflow_template(engine) if template=="$workflow" else template,size=size)
    def blender(engine,path,size=None):
        from .delivery import export_blender
        return export_blender(engine,path,size)
    def glb(engine,path,size=None):
        from .delivery import export_glb
        return export_glb(engine,path,size)
    for name,handler,description in (("project.new",new,"Create/import a mesh using native project operations"),("project.load",load,"Open a native project transactionally"),("project.save",save,"Atomic native/portable save"),("material.select",select,"Select a material set by index"),("material.resize",resize,"Native replay/evaluation resize"),("layer.add",layer_add,"Add an undoable native layer; return its persistent ID"),("layer.configure",layer_edit,"Edit native properties, current layer or persistent ID"),("layer.select",layer_select,"Select a persistent layer and its material set"),("channel.declare",declare,"Declare a project-local scalar channel"),("channel.fill",fill,"Edit a scalar channel on a native layer"),("shader.configure",shader,"Change the native shader workflow"),("brush.uv_path",uv_path,"Paint a deterministic native UV path"),("textures.export",textures,"Use the native texture export manifest/writer"),("delivery.blender",blender,"Build the portable mesh/material Blender ZIP"),("delivery.glb",glb,"Build genuine mesh/material glTF 2.0 GLB")):
        add(name,handler,description)
    return registry


def install_ui_command(registry,app,command,params,label,menu="Extensions"):
    """Explicit host hook; installing a command never executes it."""
    if menu in {"File","Edit","Layer","Viewport","Window","Help"} or not isinstance(menu,str) or not menu.strip():raise ValueError("Use a separate extension menu name")
    registry.validate(command,params)
    app.reg.add("extension."+command,label,menu,lambda:registry.execute(app.engine,command,params))
