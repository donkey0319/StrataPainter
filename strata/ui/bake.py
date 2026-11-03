"""Bake controls use staged engine operations; GPU work stays on the context thread."""
import copy
import os
import time
from contextlib import contextmanager
import glfw
from imgui_bundle import imgui
from ..baker import BakeSettings, ID_SOURCES, ID_GENERATORS
from .. import meshmap
from .theme import V2


class BakeUI:
    def __init__(self, app):
        self.app = app
        self.same_settings = False
        self.cancelled = False
        self.last_frame = 0.
        self.map_key = 0
        self.diagnostic_tile = 0
        self.settings_set = None
        self.project_key = None
        self.drafts = {}

    def prepare(self):
        app, engine = self.app, self.app.engine
        identity = id(engine.mesh)
        if identity != self.project_key:
            self.project_key = identity
            self.drafts = {}
            self.settings_set = None
        if self.settings_set != engine.ts.pid:
            if self.settings_set is not None and app.bake_settings is not None:
                self.drafts[self.settings_set] = app.bake_settings
            app.bake_settings = self.drafts.get(engine.ts.pid) or BakeSettings.from_dict(engine.ts.bake_settings.to_dict())
            self.settings_set = engine.ts.pid

    def field(self, label):
        available = imgui.get_content_region_avail().x
        imgui.set_next_item_width(max(60 * self.app.ui_scale, available - imgui.calc_text_size(label).x - 12 * self.app.ui_scale))

    def workspace(self):
        """Non-modal bake workspace; artists can navigate and paint correction fields."""
        app, engine = self.app, self.app.engine
        self.prepare()
        imgui.text("Baking - " + engine.ts.name)
        imgui.text_wrapped("Inspect maps, adjust projection, paint correction fields, then bake. F9 returns to Painting.")
        if imgui.button("Return to Painting (F9)"):
            app._set_workspace_mode("paint")
            return
        settings = app.bake_settings
        imgui.begin_child("##bake_workspace")
        if imgui.collapsing_header("Common settings", imgui.TreeNodeFlags_.default_open):
            self.field("AO samples")
            _, settings.ao_samples = imgui.slider_int("AO samples", settings.ao_samples, 4, 256)
            self.field("AO spread")
            _, settings.ao_spread = imgui.slider_float("AO spread", float(settings.ao_spread), 10, 90, "%.0f deg")
            self.field("AO max distance")
            _, settings.ao_max_distance = imgui.slider_float("AO max distance", float(settings.ao_max_distance), 0, 1)
            _, settings.ground_plane = imgui.checkbox("Ground plane (AO)", settings.ground_plane)
            self.field("Thickness distance")
            _, settings.thickness_max_distance = imgui.slider_float("Thickness distance", float(settings.thickness_max_distance), .05, 1.)
            _, settings.curv_from_normal = imgui.checkbox("Add normal-map detail to curvature", settings.curv_from_normal)
            self.field("Dilation (px)")
            _, settings.dilation = imgui.slider_int("Dilation (px)", settings.dilation, 0, 64)
            self.source_controls(settings)
        if len(engine.sets) > 1:
            _, app.bake_all = imgui.checkbox("Bake every texture set", app.bake_all)
        if imgui.button("Bake mesh maps", V2(-1, 0)):
            snapshot = BakeSettings.from_dict(copy.deepcopy(settings.to_dict()))
            all_sets = bool(app.bake_all and len(engine.sets) > 1)
            app._run_busy("Baking mesh maps...", lambda: self.run(snapshot, all_sets))
        imgui.separator()
        # These use the existing transactional map/correction paths, not a second baker.
        previous_filter = getattr(app, "_flt", "")
        app._flt = ""
        self.mesh_maps()
        app._flt = previous_filter
        imgui.end_child()

    def source_controls(self, settings):
        app = self.app
        imgui.separator()
        imgui.text("High-poly sources")
        self.field("High/low pairing")
        _, pairing = imgui.combo("High/low pairing", int(settings.pairing == "name"), ["All sources", "Match mesh/part names"])
        settings.pairing = ("all", "name")[pairing]
        if settings.pairing == "name":
            self.field("Low name suffix")
            _, settings.low_suffix = imgui.input_text("Low name suffix", settings.low_suffix)
            self.field("High name suffix")
            _, settings.high_suffix = imgui.input_text("High name suffix", settings.high_suffix)
        self.field("Bake supersampling")
        _, sampling = imgui.combo("Bake supersampling", (1, 2, 4).index(settings.supersampling), ["1x", "2x", "4x"])
        settings.supersampling = (1, 2, 4)[sampling]
        if settings.cage_path:
            imgui.text_wrapped("Projection cage: " + os.path.basename(settings.cage_path))
            if imgui.button("Clear projection cage"):
                settings.cage_path = settings.cage_hash = ""
        if imgui.button("Choose projection cage..."):
            path = app._load_mesh_file("Projection cage")
            if path:
                settings.cage_path, settings.cage_hash = path, ""
        imgui.text_wrapped("Cages require matching indexed topology and outward vertices.\nAO/thickness include all selected high-poly parts, including self/cross-part occlusion.")
        for index, path in enumerate(list(settings.high_poly)):
            imgui.push_id(index)
            imgui.text(os.path.basename(path))
            imgui.same_line()
            if imgui.small_button("Remove"):
                settings.high_poly.pop(index)
            imgui.pop_id()
        if imgui.button("Add high-poly source..."):
            path = app._load_mesh_file("High-poly source")
            if path and path not in settings.high_poly:
                settings.high_poly.append(path)
        self.field("Frontal distance")
        _, settings.hp_front = imgui.slider_float("Frontal distance", float(settings.hp_front), .0001, .5)
        self.field("Rear distance")
        _, settings.hp_rear = imgui.slider_float("Rear distance", float(settings.hp_rear), .0001, .5)
        _, settings.hp_ignore_backface = imgui.checkbox("Ignore high-poly backfaces", settings.hp_ignore_backface)
        self.field("ID source")
        _, settings.id_source = imgui.combo("ID source", settings.id_source, ID_SOURCES)
        self.field("ID generation")
        _, settings.id_generator = imgui.combo("ID generation", settings.id_generator, ID_GENERATORS)
        _, settings.id_from_high = imgui.checkbox("ID from high-poly vertex colors", settings.id_from_high)
        for key, label in (("ao", "Bake AO"), ("thickness", "Bake thickness"), ("id", "Bake ID")):
            _, settings.enabled[key] = imgui.checkbox(label, settings.enabled.get(key, True))
        imgui.text_wrapped("Position, world normal, curvature and coverage are required.\nHigh-poly sources also produce tangent normal and height.")
        if len(app.engine.sets) > 1 and app.bake_all:
            _, self.same_settings = imgui.checkbox("Apply these settings to all sets", self.same_settings)
            imgui.text_disabled("Unchecked: retain each other set's independent settings.")

    def run(self, settings, all_sets):
        app, engine = self.app, self.app.engine
        targets = engine.sets if all_sets else [engine.ts]
        states = {ts.pid: BakeSettings.from_dict(copy.deepcopy(
            (settings if self.same_settings or ts is engine.ts else ts.bake_settings).to_dict())) for ts in targets}
        # External map identity is set-specific even when sharing bake parameters.
        for ts in targets:
            if ts is not engine.ts:
                states[ts.pid].external_maps = copy.deepcopy(ts.bake_settings.external_maps)
                for key in ("ray_correction_pid", "distance_correction_pid", "correction_hashes"):
                    setattr(states[ts.pid], key, copy.deepcopy(getattr(ts.bake_settings, key)))
        self.cancelled, self.last_frame = False, 0.
        engine.rebake(states, all_sets=all_sets, progress=self.progress)
        app.msg(f"Baked {len(targets)} texture set(s); undo restores the previous maps and settings.")

    def progress(self, value):
        now = time.monotonic()
        if now - self.last_frame < .05 and value not in (0., 1.):
            return not self.cancelled
        self.last_frame = now
        app = self.app
        glfw.poll_events()
        app.impl.process_inputs()
        imgui.new_frame()
        w, h = glfw.get_window_size(app.window)
        imgui.set_next_window_pos(V2(w / 2, h / 2), 0, V2(.5, .5))
        imgui.begin("Baking mesh maps", flags=imgui.WindowFlags_.always_auto_resize | imgui.WindowFlags_.no_collapse)
        imgui.progress_bar(float(value), V2(360, 0))
        if imgui.button("Cancel bake") or imgui.is_key_pressed(imgui.Key.escape):
            self.cancelled = True
        if self.cancelled:
            imgui.text("Cancel requested: finishing current map safely.")
        imgui.end()
        app.ctx.screen.use()
        fw, fh = glfw.get_framebuffer_size(app.window)
        app.ctx.viewport = (0, 0, fw, fh)
        app.ctx.clear(.08, .085, .09)
        imgui.render()
        app._drain_gl_errors()  # same ModernGL/PyOpenGL handoff as App.frame
        app.impl.render(imgui.get_draw_data())
        glfw.swap_buffers(app.window)
        return not self.cancelled

    def mesh_maps(self):
        app, engine = self.app, self.app.engine
        if not app._section("Mesh maps", ["External map", "Hit coverage", "Bake corrections"]):
            return
        if app._row("Hit coverage"):
            imgui.text(f"High-poly hit coverage: {engine.bakes.hp_hits:.1%}")
            self.projection_diagnostics()
        if app._row("Bake corrections"):
            self.correction_controls()
        if not app._row("External map"):
            app._end_section()
            return
        keys = list(meshmap.SLOTS)
        _, self.map_key = imgui.combo("Mesh-map channel", self.map_key, [meshmap.SLOTS[k][0] for k in keys])
        key = keys[self.map_key]
        interpretation = "object" if key == "position" else ("encoded" if key == "world_normal" else "data")
        imgui.text_disabled(f"{engine.ts.name}: {engine.res} x {engine.res}, {interpretation}; no color transform")
        record = engine.ts.bake_settings.external_maps.get(key)
        if record:
            imgui.text_wrapped(os.path.basename(record["path"]))
        if imgui.button("Assign external mesh map..."):
            path = app._load_image("External " + key + " map")
            if path:
                try:
                    engine.assign_mesh_map(key, path, interpretation, set_pid=engine.ts.pid)
                except Exception as error:
                    app.msg(f"Mesh-map assignment failed: {error}")
        if record and imgui.button("Clear external map and rebake"):
            app._run_busy("Restoring native mesh map...", lambda: engine.assign_mesh_map(key, None))
        modes = {"ao": 7, "curvature": 8, "thickness": 12, "id": 13, "normal": 16, "height": 17, "world_normal": 14, "position": 15}
        imgui.begin_disabled(engine.bakes.maps().get(key) is None)
        if imgui.button("Preview mesh-map channel"):
            engine.renderer.mode = modes[key]
            engine.dirty = True
        imgui.end_disabled()
        app._end_section()

    def projection_diagnostics(self):
        from contextlib import contextmanager
        engine = self.app.engine
        @contextmanager
        def thumbnail(source):
            size = tuple(min(256, n) for n in source.size)
            copied = engine.gpu.texture(size, 4, dtype="f1", filt=False)
            try:
                engine.gpu.blit(source, copied)
                yield copied
            finally:
                copied.release()
        with self.app.tiles_ui.leases() as leases:
            diagnostic = engine.bakes.projection
            image = None
            if engine.ts.tiles is not None and (engine.ts.bake_settings.pairing != "all" or engine.ts.bake_settings.cage_path or
                                                engine.ts.bake_settings.supersampling != 1 or engine.ts.bake_settings.ray_correction_pid or
                                                engine.ts.bake_settings.distance_correction_pid):
                addresses = engine.ts.tile_addresses
                self.diagnostic_tile = min(self.diagnostic_tile, len(addresses) - 1)
                _, self.diagnostic_tile = imgui.combo("Projection diagnostic tile", self.diagnostic_tile, [str(item.udim) for item in addresses])
                try:
                    with engine.ts.tiles.cached_evaluation(addresses[self.diagnostic_tile], min(engine.res, 256)) as tile:
                        if tile.bakes.projection is not None:
                            image = leases.enter_context(thumbnail(tile.bakes.projection))
                    diagnostic = None
                except (ValueError, OSError) as error:
                    imgui.text_wrapped(str(error))
                    return
            if diagnostic is not None:
                image = leases.enter_context(thumbnail(diagnostic))
            if image is not None:
                imgui.text_wrapped("Projection: green hit, red miss, blue cage crossing; transparent outside UV coverage.")
                imgui.image(imgui.ImTextureRef(image.glo), V2(180, 180), V2(0, 1), V2(1, 0))

    def correction_controls(self):
        app, e = self.app, self.app.engine
        imgui.text_wrapped("Use dedicated unmasked paint layers. Binding hides their material channels. Paint the raw field, then rebake.")
        for kind, channel in (("ray", 4), ("distance", 3)):
            pid = getattr(e.ts.bake_settings, kind + "_correction_pid")
            owner = next((layer for layer in e._walk(e.ts.layers) if layer.pid == pid), None)
            if imgui.button(f"Bind selected layer as {kind} correction"):
                try:
                    if e.layer is None:
                        raise ValueError("Select a dedicated paint layer first")
                    e.set_bake_correction(kind, e.layer)
                except ValueError as error:
                    app.msg(str(error))
            if pid:
                imgui.text_wrapped((owner.name if owner is not None else "Missing field layer") + " (" + kind + ")")
                if imgui.button(f"Clear {kind} correction"):
                    e.set_bake_correction(kind, None)
                if owner is not None:
                    imgui.same_line()
                    if imgui.button(f"Paint {kind} correction"):
                        e.select(owner)
                        e.brush.target, e.brush.tool, e.brush.mode = 0, 0, 0
                        e.brush.enabled = [index == channel for index in range(7)]
                        app.poly_fill = False
                    with app.tiles_ui.leases() as leases:
                        preview = None
                        if e.ts.tiles is None:
                            texture = owner.tex.get("N" if kind == "ray" else "H")
                            if texture is not None:
                                preview = leases.enter_context(self.correction_thumbnail(texture, kind))
                        else:
                            index = min(self.diagnostic_tile, len(e.ts.tile_addresses) - 1)
                            with e.ts.tiles.store.lease(e.ts.pid, e.ts.tile_addresses[index]) as page:
                                texture = page.get(owner.pid + (":N" if kind == "ray" else ":H"))
                                if texture is not None:
                                    preview = leases.enter_context(self.correction_thumbnail(texture, kind))
                        if preview is not None:
                            imgui.image(imgui.ImTextureRef(preview.glo), V2(140, 140), V2(0, 1), V2(1, 0))
        imgui.text_wrapped("Ray: paint Normal RGB as an encoded world direction.\nDistance: paint Height 0..1 for 0..2x the ray range; 0.5 is neutral.\nField paint has ordinary pixel undo and portable persistence.")

    @contextmanager
    def correction_thumbnail(self, source, kind):
        from .. import shaders as S
        e = self.app.engine
        preview = e.gpu.texture(tuple(min(256, n) for n in source.size), 4, dtype="f1")
        fbo = None
        try:
            fbo = e.ctx.framebuffer([preview])
            fbo.use()
            e.ctx.viewport = (0, 0, *preview.size)
            e.ctx.scissor = None
            import moderngl
            e.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
            value = "vec4(s.rgb / max(s.a, 1e-6), step(0.001, s.a))" if kind == "ray" else "vec4(vec3(s.r / max(s.g, 1e-6)), step(0.001, s.g))"
            p = e.gpu.fs_program("bake-field-preview/" + kind, S.HEADER + "uniform sampler2D u_src; in vec2 v_uv; out vec4 o; void main(){vec4 s=texture(u_src,v_uv); o=" + value + ";}")
            e.gpu.bind(p, {"u_src": (0, source)})
            e.gpu.draw_quad(p)
            yield preview
        finally:
            if fbo is not None:
                fbo.release()
            preview.release()
