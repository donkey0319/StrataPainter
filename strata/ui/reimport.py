"""Artist-visible mesh mapping, staged comparison, commit/cancel and checkpoint recovery."""
from imgui_bundle import imgui
from .theme import V2


class MeshRevisionUI:
    def __init__(self, app):
        self.app = app
        self.open = False
        self.mesh = self.report = self.prepared = self.thumbnail = None
        self.mapping, self.path, self.error = {}, "", ""
        self.distance = .1
        self.auto_uv = False
        self.uv_tiles = 1

    def register_commands(self, registry):
        registry.add("file.reimport_mesh", "Reimport Mesh...", "File",
                     lambda: setattr(self, "open", True), [], self.app._has)
        registry.add("file.restore_mesh_checkpoint", "Restore Pre-reimport Project", "File",
                     self.restore_checkpoint, [], lambda: bool(getattr(self.app.engine, "reimport_checkpoint", None)))

    def restore_checkpoint(self):
        e = self.app.engine
        path = getattr(e, "reimport_checkpoint", None)
        if path:
            self.app._run_busy("Restoring pre-reimport project...", lambda: self._restore(path))

    def _restore(self, path):
        e = self.app.engine
        destination = e.project_path
        e.load(path)
        e.project_path = destination
        e.mark_modified()
        self.app.msg("Restored the portable pre-reimport checkpoint")

    def _cancel_stage(self):
        if self.thumbnail is not None:
            self.thumbnail.release()
            self.thumbnail = None
        if self.prepared is not None:
            self.prepared.cancel()
            self.prepared = None

    def inspect(self, path):
        from ..reimport import preview
        self._cancel_stage()
        self.path, self.mapping, self.error = path, {}, ""
        try:
            source = path
            if self.auto_uv:
                from ..mesh import load_mesh
                from ..uvprep import prepare_mesh
                source = prepare_mesh(load_mesh(path, xform=self.app.engine.mesh.extra.get("xform"), require_uvs=False),
                                      {"resolution": self.app.engine.res, "tile_count": self.uv_tiles})
            self.mesh, self.report = preview(self.app.engine, source)
            self.distance = self.report["max_distance"]
        except Exception as error:
            self.mesh, self.report, self.error = None, None, str(error)

    def _mapping(self):
        return {pid: ([] if selected == 1 else [selected - 2])
                for pid, selected in self.mapping.items() if selected}

    def stage(self):
        from ..reimport import prepare
        self._cancel_stage()
        try:
            self.app._finish_fill_projection(cancel=True)
            self.app._finish_property_edit()
            self.prepared = prepare(self.app.engine, self.mesh, self._mapping(), self.distance)
            self.report, self.error = self.prepared.report, ""
            self._comparison()
        except Exception as error:
            self._cancel_stage()
            self.error = str(error)

    def commit(self):
        try:
            self.prepared.commit()
            self.prepared = None
            self._cancel_stage()
            self.app.uv.reset()
            self.app.material_ui.transform_tool = self.app.material_ui.transform_layer_pid = None
            self.app.msg("Mesh revision committed; portable pre-reimport checkpoint retained")
        except Exception as error:
            self.error, self.open = str(error), True

    def _comparison(self):
        e, candidate = self.app.engine, self.prepared.stage
        e.update()
        ctx = e.ctx
        texture = e.gpu.texture((640, 240), 4, dtype="f1", purpose="mesh revision comparison")
        depth = ctx.depth_renderbuffer((640, 240))
        fbo = ctx.framebuffer([texture], depth)
        previous, mode, scene = ctx.fbo, e.renderer.mode, e.renderer.scene
        try:
            fbo.use()
            e.renderer.mode = 1
            for project, rect in ((e, (0, 0, 320, 240)), (candidate, (320, 0, 320, 240))):
                e.renderer.scene = scene if project is e else self.prepared.scene
                vp = project.camera.proj(320 / 240) @ project.camera.view()
                if any(ts.tiles is not None for ts in project.sets):
                    original = project._vp
                    project._vp = vp
                    try:
                        diagnostics = project.render_materials(rect, tile_resolution=256)
                        if diagnostics:
                            raise ValueError(diagnostics[0]["message"])
                    finally:
                        project._vp = original
                else:
                    sets = [(ts.key, ts.comp, ts.bakes) for ts in project.sets]
                    e.renderer.render_sets(project.gm, project.camera, vp, sets, rect)
            self.thumbnail = texture
        except Exception:
            texture.release()
            raise
        finally:
            e.renderer.mode, e.renderer.scene = mode, scene
            if e.renderer.pick_pos is not None:
                e.renderer.render_pick(e.gm, e._vp, *e.view_size)
            if previous is not None:
                previous.use()
            fbo.release()
            depth.release()

    def draw(self):
        if self.open:
            imgui.open_popup("Mesh Revision")
            self.open = False
        s = self.app.ui_scale
        imgui.set_next_window_size(V2(780 * s, 750 * s), imgui.Cond_.appearing)
        if not imgui.begin_popup_modal("Mesh Revision", None)[0]:
            return
        if self.prepared is None:
            _, self.auto_uv = imgui.checkbox("Prepare missing revision UVs (Blender)", self.auto_uv)
            if self.auto_uv:
                _, self.uv_tiles = imgui.slider_int("Revision UV tile budget", self.uv_tiles, 1, 64)
                imgui.text_wrapped("Multi-tile revisions require an already tiled project and matching UVs/topology. Changed layouts are rejected before staging. Choose options before loading the revision.")
            if imgui.button("Choose revised mesh"):
                path = self.app._ask_mesh()
                if path:
                    self.app._run_busy("Inspecting mesh revision...", lambda: self.inspect(path))
            imgui.text_wrapped(self.path)
            if self.mesh is not None:
                imgui.text_wrapped("Material names match automatically. Unmapped sets retain their authored content.")
                options = ["Automatic by name", "Keep unassigned"] + self.mesh.material_names
                for ts in self.app.engine.sets:
                    _, self.mapping[ts.pid] = imgui.combo(ts.name + "##revision_" + ts.pid,
                                                        self.mapping.get(ts.pid, 0), options)
                _, self.distance = imgui.slider_float("Projection distance (project units)", self.distance,
                                                       .001, max(self.app.engine.mesh.radius, .002), "%.4f")
                imgui.text_wrapped("Source normalization is preserved. Native UV paint requires unchanged UV correspondence. Raster bases and clone/smudge checkpoints keep their original UV coordinates.")
                if imgui.button("Stage mesh revision"):
                    self.app._run_busy("Staging mesh revision...", self.stage, "Rebuilding mesh maps and projecting native surface paint")
        else:
            imgui.text_wrapped("Staged comparison: current project (left), proposed revision (right), unlit base color.")
            if self.thumbnail is not None:
                imgui.image(imgui.ImTextureRef(self.thumbnail.glo), V2(640 * s, 240 * s), V2(0, 1), V2(1, 0))
            report = self.report
            imgui.text_wrapped(f"Projected {report['reprojected_dabs']} dabs; missed {report['missed_samples']} samples/dabs.")
            imgui.text_wrapped("Bounds: " + str(report["old_bounds"]) + " → " + str(report["new_bounds"]))
            imgui.begin_child("##revision_report", V2(0, 150 * s))
            for assignment in report["sets"]:
                labels = [self.mesh.material_names[index] for index in assignment["materials"]]
                imgui.text_wrapped(f"{assignment['name']}: {', '.join(labels) or 'unassigned'}; {assignment['triangles']} triangles; UV {'unchanged' if assignment['uv_unchanged'] else 'changed'}")
            for message in report["warnings"]:
                imgui.text_wrapped(message)
            imgui.end_child()
            imgui.text_wrapped("Commit clears GPU undo history and writes a portable pre-reimport checkpoint. Restore it with File > Restore Pre-reimport Project.")
            if imgui.button("Commit mesh revision"):
                self.app._run_busy("Committing mesh revision...", self.commit)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Revise mapping"):
                self.app._run_busy("Updating revision preview...", self._cancel_stage)
        if self.error:
            imgui.text_wrapped(self.error)
        if imgui.button("Cancel mesh revision"):
            self.app._run_busy("Cancelling mesh revision...", self._cancel_stage)
            imgui.close_current_popup()
        imgui.end_popup()
