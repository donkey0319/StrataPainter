"""User-channel authoring and shared shader/export workflow controls."""
import copy
import json
from imgui_bundle import imgui
from .theme import V2
from ..layers import BLEND_MODES
from .. import exporter


class ChannelsUI:
    def __init__(self, app):
        self.app = app
        self.open = False
        self.name = "wetness"
        self.selected = None
        self.component = 0
        self.effect = 0

    def action(self, callback):
        try:
            callback()
        except (ValueError, OSError, MemoryError) as error:
            self.app.msg(str(error))

    def draw(self):
        if not self.open:
            return
        imgui.set_next_window_size(V2(510, 720), imgui.Cond_.first_use_ever)
        visible, self.open = imgui.begin("Channels and shaders", self.open)
        try:
            e = self.app.engine
            if not visible or e.ts is None:
                return
            _, self.name = imgui.input_text("New channel name", self.name)
            if imgui.button("Create scalar channel"):
                self.action(lambda: setattr(self, "selected", e.add_user_channel(self.name)))
            keys = list(e.user_channels)
            if keys:
                if self.selected not in keys:
                    self.selected = keys[0]
                changed, index = imgui.combo("User channel", keys.index(self.selected), [e.user_channels[k]["label"] for k in keys])
                if changed:
                    self.selected = keys[index]
                key = self.selected
                imgui.text_disabled(key + " | linear scalar, 16-bit float")
                layer = e.layer
                if layer is not None:
                    values = layer.user_channels.get(key, {"value":e.user_channels[key]["default"], "enabled":layer.is_group, "blend":-1, "opacity":1.})
                    changed, enabled = imgui.checkbox("Layer channel enabled", values["enabled"])
                    if changed:self.action(lambda:e.set_user_channel(key,enabled=enabled))
                    changed, value = imgui.slider_float("Channel fill value", values["value"], 0., 1.)
                    setting = dict(values, value=value)
                    self.app._edit_value("Channel fill value",layer,"user_channels",dict(layer.user_channels,**{key:setting}),changed,continuous=True)
                    changed, opacity = imgui.slider_float("Channel opacity",values["opacity"],0.,1.)
                    self.app._edit_value("Channel opacity",layer,"user_channels",dict(layer.user_channels,**{key:dict(values,opacity=opacity)}),changed,continuous=True)
                    changed, mode = imgui.combo("Channel blend",values["blend"]+1,["Normal default"]+BLEND_MODES[:29])
                    if changed:self.action(lambda:e.set_user_channel(key,blend=mode-1))
                    changed, value = imgui.slider_float("Channel brush value",e.brush.user_value,0.,1.)
                    if changed:e.brush.user_value=value
                    if imgui.button("Paint selected channel"):
                        self.action(lambda:e.paint_user_channel(key,e.brush.user_value))
                    imgui.same_line()
                    if imgui.button("Paint document channels"):
                        e.paint_user_channel(None)
                    imgui.text_wrapped("Brush target: "+(e.brush.user_channel or "document channels"))
                    kinds=["invert","levels","blur","brightness_contrast","graph"]
                    _,self.effect=imgui.combo("User channel effect",self.effect,kinds)
                    if imgui.button("Add channel effect"):
                        self.action(lambda:e.add_effect(kinds[self.effect],mask=False,channel=3,user_channel=key))
                    imgui.text_wrapped("Edit effect parameters in the layer's content effect stack.")
                if imgui.button("Preview selected channel"):
                    e.renderer.user_preview=key;e.renderer.mode=19
                _,self.component=imgui.combo("Pack into component",self.component,["R","G","B","A"])
                if imgui.button("Prepare packed export"):
                    mapping={"name":"$mesh_$textureSet_User","r":"0","g":"0","b":"0","a":"1"}
                    mapping["rgba"[self.component]]=key
                    self.app.export_custom_template={"name":"User channel packing","maps":[mapping],"format":"png","depth":"16"}
                    self.app.export_overrides={}
                    self.app.export_template_json=json.dumps(self.app.export_custom_template,indent=2)
                    self.app.msg("User channel template prepared in Export textures")
            imgui.separator()
            workflow=e.shader_workflow
            changed,model=imgui.combo("Shading model",int(workflow["model"]=="spec_gloss"),["Metallic / roughness","Specular / glossiness"])
            if changed:
                self.action(lambda:e.set_shader_workflow(model=["metal_rough","spec_gloss"][model]))
            imgui.text_wrapped("Bind independent linear F0 RGB and glossiness before selecting Specular / glossiness.")
            names=["specular_r","specular_g","specular_b","glossiness","coat","coat_roughness"]
            for semantic in names:
                choices=["Unbound"]+keys
                current=workflow["bindings"].get(semantic)
                changed,index=imgui.combo(semantic,choices.index(current) if current in choices else 0,choices)
                if changed:
                    bindings=dict(workflow["bindings"])
                    if index:bindings[semantic]=choices[index]
                    else:bindings.pop(semantic,None)
                    self.action(lambda:e.set_shader_workflow(bindings=bindings))
            imgui.text("Vertex displacement")
            changed,value=imgui.input_float("Range (meters)",workflow["displacement_meters"],.001,.01,"%.4f")
            if changed:self.action(lambda:e.set_shader_workflow(displacement_meters=value))
            changed,value=imgui.slider_float("Height midlevel",workflow["height_midlevel"],0.,1.)
            self.app._edit_value("Height midlevel",e,"shader_workflow",dict(workflow,height_midlevel=value),changed,continuous=True)
            imgui.text_wrapped("Vertex displacement uses existing mesh density and declared source units. Edit in 2D while displaced. Tiled displacement is unavailable.")
            if imgui.button("Prepare shader export"):
                self.app.export_custom_template=exporter.workflow_template(e)
                self.app.export_template_json=json.dumps(self.app.export_custom_template,indent=2)
                self.app.export_overrides={}
                self.app.msg("Shader template prepared in Export textures")
        finally:
            imgui.end()
