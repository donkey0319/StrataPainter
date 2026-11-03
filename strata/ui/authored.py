"""Persistent surface-object authoring and control-point placement in native views."""
import copy
import numpy as np
from imgui_bundle import imgui,portable_file_dialogs as pfd
from .theme import V2,col32
from .. import authored


class AuthoredUI:
    def __init__(self,app):
        self.app=app;self.open=False;self.capturing=None;self.points=[];self.set_pid=None;self.moving=None
        self.font="";self.label="Label";self.capture_key=None
    def draw(self):
        if not self.open:return
        imgui.set_next_window_size(V2(490,660),imgui.Cond_.first_use_ever)
        visible,self.open=imgui.begin("Paths, ribbons and text",self.open)
        try:
            if not visible:return
            e=self.app.engine
            if e.mesh is None or e.ts is None:
                imgui.text("Open a project to author surface objects.");return
            if self.capturing and (self.set_pid!=e.ts.pid or self.capture_key!=authored.topology_key(e.mesh)):
                self.capturing=None;self.points=[];self.app.msg("Surface changed; restart path capture")
            if self.moving and not any(layer.pid==self.moving[0] for layer in e._walk(e.ts.layers)):self.moving=None
            for kind in ("path","ribbon","region"):
                if imgui.button("New "+kind):self.capturing=kind;self.points=[];self.set_pid=e.ts.pid;self.moving=None;self.capture_key=authored.topology_key(e.mesh)
                imgui.same_line()
            imgui.new_line()
            if self.capturing:
                imgui.text_wrapped(f"{self.capturing}: {len(self.points)} points. Click a UV surface or the 3D model; then Create object. UV seams/disconnected indexed charts require separate paths.")
                if imgui.button("Create object"):
                    try:
                        e.add_authored_path(self.points,self.capturing)
                        self.capturing=None;self.points=[]
                    except ValueError as error:self.app.msg(str(error))
                imgui.same_line()
                if imgui.button("Cancel path capture"):self.capturing=None;self.points=[]
            if imgui.button("Choose font..."):
                files=pfd.open_file("Choose text font","",["Font files","*.ttf *.otf *.ttc"]).result()
                if files:self.font=files[0]
            imgui.same_line();imgui.text_wrapped(self.font or "Choose a TrueType/OpenType font")
            _,self.label=imgui.input_text("New label text",self.label)
            if imgui.button("New text label"):
                try:e.add_text(self.label,self.font)
                except (ValueError,OSError,MemoryError) as error:self.app.msg(str(error))
            layer=e.layer
            if layer is None or layer.authored is None:return
            value=layer.authored
            imgui.separator();imgui.text(layer.name+": "+value["kind"])
            imgui.text_wrapped("Material colors, seven channel maps, blending and projection stay editable in the layer properties.")
            if value["kind"]=="text":
                imgui.text("Label text")
                changed,text=imgui.input_text_multiline("##Label text",value["text"],V2(-1,75))
                if changed:self.edit(layer,"Label text",text=text)
                changed,origin=imgui.drag_float2("Label origin",value["origin"],.002,-32,32)
                if changed:self.edit(layer,"Label origin",origin=list(origin))
                for key,lo,hi in (("size",.005,1.),("tracking",-.5,2.),("leading",.5,4.)):
                    changed,x=imgui.slider_float("Text "+key,float(value[key]),lo,hi)
                    if changed:self.edit(layer,"Text "+key,**{key:x})
                changed,index=imgui.combo("Text alignment",["left","center","right"].index(value["align"]),["left","center","right"])
                if changed:e.set_authored(layer,align=["left","center","right"][index])
                if self.font and imgui.button("Use chosen font for label"):
                    try:e.set_authored(layer,font=self.font)
                    except (ValueError,OSError) as error:self.app.msg(str(error))
            else:
                fields=[] if value["kind"]=="region" else [("width",.001,.5)]
                fields+= [("spacing",.05,2.)] if value["kind"]=="path" else [("repeat",.01,4.)] if value["kind"]=="ribbon" else []
                for key,lo,hi in fields:
                    changed,x=imgui.slider_float("Path "+key,float(value[key]),lo,hi)
                    if changed:self.edit(layer,"Path "+key,**{key:x})
                for index,point in enumerate(value["points"]):
                    imgui.push_id(index)
                    if imgui.button("Move point "+str(index+1)):self.moving=(layer.pid,index);self.capturing=None
                    for key,lo,hi in (() if value["kind"]=="region" else (("width",.01,4.),("pressure",0.,1.))):
                        changed,x=imgui.slider_float("Point "+key,float(point[key]),lo,hi)
                        if changed:
                            points=copy.deepcopy(value["points"]);points[index][key]=x
                            self.edit(layer,"Point "+key,points=points)
                    imgui.pop_id()
                if self.moving:imgui.text_wrapped("Click a new surface location for the selected control point. Esc cancels.")
            if value["kind"]=="path" and imgui.button("Choose path tip..."):
                files=pfd.open_file("Path brush tip","",["Images","*.png *.tif *.jpg"]).result()
                if files:
                    try:e.set_authored(layer,alpha=files[0])
                    except (ValueError,OSError) as error:self.app.msg(str(error))
            diagnostic=getattr(self.app,"_authored_error",None)
            if diagnostic:imgui.text_wrapped(diagnostic)
        finally:
            imgui.end()
            self.overlay()
    def edit(self,layer,label,**changes):
        try:
            value=dict(copy.deepcopy(layer.authored),**changes)
            self.app._edit_value(label,layer,"authored",value,True,continuous=True)
        except (ValueError,OSError,MemoryError) as error:self.app.msg(str(error))
    def input(self,over3,over2):
        if not self.open or not (self.capturing or self.moving):return False
        io=imgui.get_io();e=self.app.engine
        if imgui.is_key_pressed(imgui.Key.escape):self.capturing=None;self.moving=None;self.points=[];return True
        if io.key_alt or io.key_ctrl:return False
        if not (over3 or over2):return False
        if not imgui.is_mouse_clicked(0):return True
        try:
            if self.capturing and e.ts.pid!=self.set_pid:raise ValueError("Material changed; restart path capture")
            if over2:
                anchor=authored.anchor_uv(e.mesh,self.app._mouse_uv(),e.ts.tri_ids)
            else:
                info=e.pick_info(*self.app._mouse_vp())
                if info is None or info["set"]!=e.active:raise ValueError("Choose a surface in the active material")
                tri=info["tri"];uv=np.asarray(info["uv"]);vertices=e.mesh.uvs[e.mesh.indices[tri]]
                weights=np.linalg.solve(np.column_stack([vertices[1]-vertices[0],vertices[2]-vertices[0]]),uv-vertices[0])
                anchor={"tri":int(tri),"bary":[float(1-weights.sum()),*weights.tolist()],"width":1.,"pressure":1.}
            if self.capturing:self.points.append(anchor)
            else:
                pid,index=self.moving;layer=next(item for item in e._walk(e.ts.layers) if item.pid==pid)
                points=copy.deepcopy(layer.authored["points"]);anchor.update({key:points[index][key] for key in ("width","pressure")});points[index]=anchor
                e.set_authored(layer,points=points);self.moving=None
        except (ValueError,np.linalg.LinAlgError,StopIteration) as error:self.app.msg(str(error))
        return True
    def overlay(self):
        if not self.open:return
        e=self.app.engine;layer=e.layer
        points=self.points if self.capturing else (layer.authored or {}).get("points",[]) if layer else []
        if not points or not self.app.uv_rect or min(self.app.uv_rect[2:])<=0:return
        view,mapping=self.app._uv_input();x,y,w,h=view.rect;sx,sy=view.framebuffer_scale
        draw=imgui.get_foreground_draw_list();draw.push_clip_rect(V2(x,y),V2(x+w,y+h),True)
        positions=[]
        for point in points:
            uv=np.asarray(point["bary"])@e.mesh.uvs[e.mesh.indices[point["tri"]]];px,py=mapping.pixel(uv)
            position=V2(x+px/sx,y+h-py/sy);positions.append(position)
            draw.add_circle_filled(position,5,col32(1.,.65,.1,1.))
        for a,b in zip(positions,positions[1:]):draw.add_line(a,b,col32(1.,.65,.1,1.),1.5)
        draw.pop_clip_rect()
