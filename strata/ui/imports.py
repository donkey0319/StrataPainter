"""Visible replay budgets, cancellation and saved continuation controls."""
import json
import time
from pathlib import Path
from imgui_bundle import imgui
from .theme import V2


class ImportUI:
    def __init__(self,app):
        self.app=app;self.max_dabs=150000;self.per_layer=40000;self.cancelled=False;self.last_frame=0.;self.open=False
    def budgets(self):
        _,self.max_dabs=imgui.input_int("Replay dab budget",self.max_dabs,1000,10000)
        _,self.per_layer=imgui.input_int("Per-layer dab budget",self.per_layer,1000,10000)
        self.max_dabs=max(1,self.max_dabs);self.per_layer=max(1,self.per_layer)
        imgui.text_wrapped("Budgets pause at whole-stroke checkpoints. No points are decimated. Increase both limits if one stroke cannot fit; save/reopen retains continuation.")
    def run(self,action):
        self.cancelled=False;self.last_frame=0.
        return self.app._run_busy("Importing Painter content...",action)
    def progress(self,value):
        import glfw
        now=time.monotonic()
        if now-self.last_frame<.08:return not self.cancelled
        self.last_frame=now
        app=self.app;glfw.poll_events();app.impl.process_inputs();imgui.new_frame()
        imgui.begin("Import replay progress",flags=imgui.WindowFlags_.always_auto_resize)
        imgui.progress_bar(float(value),V2(360,0))
        if imgui.button("Cancel replay") or imgui.is_key_pressed(imgui.Key.escape):self.cancelled=True
        imgui.text_wrapped("Cancel keeps completed strokes and a resumable checkpoint.")
        imgui.end();app.ctx.screen.use()
        fw,fh=glfw.get_framebuffer_size(app.window);app.ctx.viewport=(0,0,fw,fh);app.ctx.clear(.08,.085,.09)
        imgui.render();app._drain_gl_errors();app.impl.render(imgui.get_draw_data());app.tiles_ui.finish_frame();glfw.swap_buffers(app.window)
        return not self.cancelled
    def draw(self):
        self.coverage()
        e=self.app.engine;state=e.import_state
        if not state or state["status"]=="complete":return
        imgui.set_next_window_size(V2(470,0),imgui.Cond_.appearing)
        imgui.begin("Incomplete Painter import",flags=imgui.WindowFlags_.always_auto_resize)
        imgui.text_wrapped(f"{state['status']}: {state['next']} / {len(state['tasks'])} source strokes, {state['dabs']} dabs committed.")
        self.budgets()
        if imgui.button("Continue import replay"):
            self.run(lambda:e.continue_import(self.max_dabs,self.per_layer,self.progress))
        imgui.same_line()
        if imgui.button("Discard remaining replay"):
            for report in e.import_reports[-1:]:report["replay"]["status"]="discarded_incomplete"
            e.discard_import_continuation()
        imgui.text_wrapped("Editing replay targets or resizing invalidates continuation. Save a checkpoint before editing; a mismatch prevents duplicate or overwritten paint.")
        imgui.end()

    def coverage(self):
        if not self.open:return
        imgui.set_next_window_size(V2(700,650),imgui.Cond_.first_use_ever)
        visible,self.open=imgui.begin("Painter import coverage",self.open)
        if visible:
            reports=self.app.engine.import_reports
            imgui.text_wrapped("Read success and native editability do not establish appearance identity. Unsupported source metadata is retained in the project.")
            self.budgets()
            if not reports:imgui.text("No source compatibility report in this project.")
            for index,report in enumerate(reports):
                imgui.push_id(index)
                source=report.get("source",{})
                if imgui.collapsing_header(Path(source.get("path","Import")).name):
                    imgui.text_wrapped("Source SHA256: "+source.get("sha256","unknown"))
                    imgui.text("Painter version: "+source.get("painter_version","unknown"))
                    imgui.text("Appearance: "+report.get("appearance",{}).get("status","unvalidated"))
                    for dataset in source.get("datasets",[]):imgui.text_wrapped(f"{dataset['path']}: {dataset['encoding']}, data version {dataset['data_version']}")
                    for row in report.get("coverage",[]):imgui.text_wrapped(f"{row['feature']} x{row['count']}: {row['retention']}")
                    for note in report.get("conversion_notes",[]):imgui.text_wrapped(note)
                    imgui.text_wrapped("Replay: "+str(report.get("replay",{})))
                imgui.pop_id()
            if reports and imgui.button("Save import coverage JSON..."):
                from imgui_bundle import portable_file_dialogs as pfd
                target=pfd.save_file("Save import coverage JSON","import-coverage.json",["JSON","*.json"]).result()
                if target:
                    path=Path(target)
                    if path.suffix.lower()!=".json":path=Path(str(path)+".json")
                    try:path.write_text(json.dumps(reports,indent=2),encoding="utf-8")
                    except OSError as error:self.app.msg(f"Could not save import coverage: {error}")
        imgui.end()
