"""Native mesh/material delivery, using the same backend as the batch API."""
from pathlib import Path
from imgui_bundle import imgui,portable_file_dialogs as pfd
from .theme import V2
from .. import delivery


class DeliveryUI:
    def __init__(self,app):
        self.app=app;self.open=False;self.format=0;self.path="";self.size=0;self.last_path=None

    def export(self):
        app=self.app;path=self.path;format=self.format;size=None if self.size==0 else (128,256,512,1024,2048)[self.size-1]
        app._finish_property_edit()
        def job():
            try:
                self.last_path=(delivery.export_blender if format==0 else delivery.export_glb)(app.engine,path,size)
                app.msg("Delivered mesh and materials: "+self.last_path)
            except (ValueError,OSError,MemoryError,RuntimeError) as error:
                app.msg("Delivery failed: "+str(error))
        app._run_busy("Delivering mesh and materials...",job,"Evaluating native material maps and staging an atomic delivery file")

    def draw(self):
        if not self.open:return
        imgui.set_next_window_size(V2(600,440),imgui.Cond_.first_use_ever)
        visible,self.open=imgui.begin("Mesh and material delivery",self.open)
        try:
            if not visible:return
            e=self.app.engine
            if e.mesh is None:imgui.text("Open a project to deliver materials.");return
            _,self.format=imgui.combo("Delivery format",self.format,["Blender mesh/material ZIP","glTF 2.0 GLB"])
            _,self.path=imgui.input_text("Destination",self.path)
            if imgui.button("Choose destination"):
                suffix="zip" if self.format==0 else "glb"
                path=pfd.save_file("Deliver mesh and materials",str(Path(self.path or "material_delivery").with_suffix("."+suffix)),["Delivery file","*."+suffix]).result()
                if path:self.path=path
            _,self.size=imgui.combo("Material resolution",self.size,["Native material resolution","128","256","512","1024","2048"])
            if self.format==0:
                imgui.text_wrapped("Portable geometry, material identities, linear texture maps and a Blender setup script. Import creates a new collection and packs its images.")
                imgui.text_wrapped("Supports metallic/roughness, independent specular/glossiness, clearcoat and vertex displacement. Single-tile material sets only.")
            else:
                imgui.text_wrapped("Real indexed mesh, material assignments and embedded PNG textures. Requires declared source units. Supports metallic/roughness and clearcoat; Blender bundles preserve other workflows.")
            imgui.text_wrapped("Blender is the qualified target. Unreal and Unity setup integrations are not claimed.")
            imgui.begin_disabled(not self.path or self.app.pending is not None)
            if imgui.button("Export delivery"):self.export()
            imgui.end_disabled()
            if self.last_path:imgui.text_wrapped("Saved: "+self.last_path)
            imgui.separator();imgui.text_wrapped("Optional offline Cycles rendering is available through: python -m strata render bundle.zip render.png")
        finally:imgui.end()
