"""Editors for ordered content/mask effects and stable reference selection."""
from __future__ import annotations

from imgui_bundle import imgui

from ..layers import (MASK_EFFECTS, CONTENT_EFFECTS, BLEND_MODES, GENERATORS,
                      MESH_MAPS, PROJECTIONS, Projection, bind_anchor_references)
from ..channels import CHANNEL_DESCRIPTORS


class EffectsUI:
    def __init__(self, app):
        self.app = app
        self.selected = {}
        self.add_kind = {False: 0, True: 0}
        self.pick_target = None
        self.color = [.5, .5, .5]

    def param(self, effect, key, label, kind="slider", lo=0., hi=1., choices=None):
        app = self.app
        if not app._row(label):
            return
        value = effect.params.get(key, lo)
        if choices is not None:
            changed, value = imgui.combo("##" + label, int(value), choices)
        elif kind == "text":
            changed, value = imgui.input_text("##" + label, str(value))
        else:
            changed, value = imgui.slider_float("##" + label, float(value), lo, hi, "%.3f",
                                               imgui.SliderFlags_.always_clamp)
        values = dict(effect.params)
        values[key] = value
        app._edit_value(label, effect, "params", values, changed, continuous=choices is None)

    def draw(self, layer):
        self.stack(layer, False)
        self.stack(layer, True)
        self.geometry(layer)

    def stack(self, layer, mask):
        app, engine = self.app, self.app.engine
        title = "Mask effects" if mask else "Content effects"
        kinds = MASK_EFFECTS if mask else CONTENT_EFFECTS
        labels = ["Effect", "Enable", "Blend", "Opacity", "Source", "Anchor", "Paint", "Geometry",
                  "Gamma", "Threshold", "Radius", "Color", "Generator", "Projection", "Channel"]
        labels += ["Graph", "Native procedural", "Grunge", "Gradient", "Transform", "Warp", "Sharpen"]
        labels += ["Add effect", "Effect name", "Effect blend", "Effect opacity", "Anchor source", "Source channel",
                   "Anchor name", "Independent paint", "Paint target", "Generator type", "Level", "Softness",
                   "Noise breakup", "Noise scale", "Azimuth", "Elevation", "Generator seed", "Generator axis",
                   "Invert generator", "Fill value", "Mask bitmap", "Mask mapping", "Mask projection", "Mask scale",
                   "Mask offset", "Mask rotation", "Mask axis", "Mask sharpness", "ID tolerance", "ID hardness",
                   "ID colors", "Effect channel", "Color target", "Input low", "Input high", "Output low", "Output high",
                   "Blur radius", "Threshold softness", "Hue", "Saturation", "Lightness", "Brightness", "Contrast", "Mesh map"]
        if not app._section(title, labels):
            return
        imgui.push_id(title + layer.pid)
        stack = layer.mask_effects if mask else layer.effects
        if app._row("Add effect"):
            _, self.add_kind[mask] = imgui.combo("##effect_kind", self.add_kind[mask], kinds)
            if imgui.button("Add##" + title):
                app._finish_property_edit()
                kind = kinds[self.add_kind[mask]]
                params = {"name": "Anchor " + str(len(layer.effects) + 1)} if kind == "anchor" and not mask else {}
                effect = engine.add_effect(kind, layer=layer, mask=mask, **params)
                self.selected[(layer.pid, mask)] = effect.pid
        for index, effect in enumerate(list(stack)):
            if not app._row(str(index + 1) + ". " + effect.name):
                continue
            imgui.push_id(effect.pid)
            changed, enabled = imgui.checkbox("##enabled", effect.enabled)
            app._edit_value("Enable effect", effect, "enabled", enabled, changed)
            imgui.same_line()
            if imgui.selectable(effect.name + "##select", self.selected.get((layer.pid, mask)) == effect.pid)[0]:
                app._finish_property_edit()
                self.selected[(layer.pid, mask)] = effect.pid
            for label, action in (("Up", lambda: engine.move_effect(effect, -1, layer)),
                                  ("Down", lambda: engine.move_effect(effect, 1, layer)),
                                  ("Copy", lambda: engine.copy_effect(effect, layer)),
                                  ("Delete", lambda: engine.remove_effect(effect, layer))):
                if label != "Up" and imgui.get_content_region_avail().x > 200 * app.ui_scale:
                    imgui.same_line(0, 3)
                imgui.begin_disabled((label == "Up" and index == 0) or (label == "Down" and index == len(stack) - 1))
                if imgui.small_button(label):
                    app._finish_property_edit()
                    result = action()
                    if label == "Copy":
                        self.selected[(layer.pid, mask)] = result.pid
                imgui.end_disabled()
            imgui.pop_id()
        selected = next((e for e in stack if e.pid == self.selected.get((layer.pid, mask))), None)
        if selected is not None:
            imgui.push_id(selected.pid + "editor")
            self.editor(layer, selected, mask)
            imgui.pop_id()
        if mask and app._row("Paint target"):
            active = engine.active_mask_paint()
            imgui.text_wrapped(active.name if active else "Layer's base painted mask")
            if imgui.button("Paint base mask"):
                engine.set_mask_paint_target(None)
        imgui.pop_id()
        app._end_section()
        if selected is not None and selected.kind == "anchor" and not mask:
            imgui.text_wrapped("Captures accumulated output after this layer, including its content effects and mask. Row order does not change capture timing.")
        if mask:
            for diagnostic in bind_anchor_references(engine.layers):
                imgui.text_wrapped(diagnostic)

    def editor(self, layer, effect, mask):
        app, engine = self.app, self.app.engine
        if app._row("Effect name"):
            changed, value = imgui.input_text("##effect_name", effect.name)
            app._edit_value("Effect name", effect, "name", value, changed, continuous=True)
        if not (effect.kind == "anchor" and not mask):
            # Scalar mask effects have no color/HSL or encoded-normal blend semantics.
            channel = effect.params.get("channel", 0)
            modes = (list(range(24)) if mask or channel in (1, 2, 3, 6) else
                     [0, 5, 6, 7, 29, 30, 31] if channel == 4 and effect.kind != "hsl" else list(range(29)))
            if effect.blend not in modes:
                modes.append(effect.blend)
            if app._row("Effect blend"):
                changed, index = imgui.combo("##effect_blend", modes.index(effect.blend), [BLEND_MODES[m] for m in modes])
                app._edit_value("Effect blend", effect, "blend", modes[index], changed)
            app.p_slider("Effect opacity", effect, "opacity", dirty=True)
        kind = effect.kind
        if kind == "graph":
            self.graph_editor(effect, mask)
        elif kind == "paint":
            if app._row("Independent paint"):
                if imgui.button("Paint this effect"):
                    engine.set_mask_paint_target(effect)
                for name, value in (("Clear black", 0), ("Fill white", 1)):
                    if imgui.button(name):
                        engine.fill_paint_effect(effect, value)
                imgui.text_wrapped("Rows evaluate top to bottom. This row owns its paint; place filters before or after it.")
        elif kind == "anchor":
            if mask:
                if app._row("Anchor source"):
                    sources = [(lay, e) for lay in engine.all_layers() for e in lay.effects
                               if e.kind == "anchor" and e.params.get("name")]
                    current = effect.params.get("source_pid")
                    preview = next((e.params["name"] for _, e in sources if e.pid == current), "Missing / choose source")
                    if imgui.begin_combo("##anchor_source", preview):
                        for lay, source in sources:
                            if imgui.selectable(f"{lay.name}: {source.params['name']}##{source.pid}", source.pid == current)[0]:
                                self.set_params(effect, source_pid=source.pid, source=source.params["name"])
                        imgui.end_combo()
                self.param(effect, "channel", "Source channel", choices=[d.value_label for d in CHANNEL_DESCRIPTORS])
            else:
                self.param(effect, "name", "Anchor name", "text")
        elif kind == "generator":
            gen = effect.params["gen"]
            app.p_combo("Generator type", gen, "kind", GENERATORS)
            for label, attr, lo, hi in (("Level", "level", 0, 1), ("Softness", "softness", .001, .5),
                    ("Noise breakup", "noise_amount", 0, 2), ("Noise scale", "noise_scale", .01, 30),
                    ("Azimuth", "azimuth", -3.1416, 3.1416), ("Elevation", "elevation", -1.57, 1.57),
                    ("Generator seed", "seed", 0, 100)):
                app.p_slider(label, gen, attr, lo, hi, dirty=True)
            app.p_combo("Generator axis", gen, "axis", ["X", "Y", "Z"])
            app.p_check("Invert generator", gen, "invert")
        elif kind == "fill":
            self.param(effect, "value", "Fill value")
            if app._row("Mask bitmap"):
                imgui.text_wrapped(str(effect.params.get("map") or "Constant value"))
                if imgui.button("Load mask bitmap"):
                    path = app._load_image("Mask effect image")
                    if path:
                        try:
                            engine.resources.texture(path, "gray")
                            self.set_params(effect, map=path)
                        except Exception as error:
                            app.msg(f"Could not load mask image: {error}")
                if imgui.button("Clear mask bitmap"):
                    self.set_params(effect, map=None)
            if app._row("Mask mapping"):
                inherit = effect.params.get("proj") is None
                changed, inherit = imgui.checkbox("Use layer mapping", inherit)
                if changed:
                    self.set_params(effect, proj=None if inherit else Projection())
            projection = effect.params.get("proj")
            if projection is not None:
                self.projection(projection)
        elif kind == "color_select":
            self.param(effect, "tolerance", "ID tolerance", lo=.001, hi=1.)
            self.param(effect, "hardness", "ID hardness")
            if app._row("ID colors"):
                _, self.color = imgui.color_edit3("##idcolor", self.color, imgui.ColorEditFlags_.no_inputs)
                if imgui.button("Add ID color"):
                    self.set_params(effect, colors=(effect.params.get("colors", []) + [list(self.color)])[-8:])
                if imgui.button("Pick ID in viewport"):
                    self.pick_target = (layer.pid, effect.pid)
                for index, color in enumerate(effect.params.get("colors", [])):
                    changed, value = imgui.color_edit3(f"##id_{index}", color, imgui.ColorEditFlags_.no_inputs)
                    colors = list(effect.params["colors"])
                    colors[index] = list(value)
                    values = dict(effect.params, colors=colors)
                    app._edit_value(f"ID color {index}", effect, "params", values, changed, continuous=True)
                    if imgui.small_button(f"Remove##id_{index}"):
                        self.set_params(effect, colors=colors[:index] + colors[index + 1:])
                if self.pick_target:
                    imgui.text_wrapped("Click the 3D model to sample baked ID. Esc cancels.")
        else:
            if not mask:
                if kind == "hsl":
                    self.param(effect, "target", "Color target", choices=["Color", "Emissive"])
                else:
                    if effect.params.get("user_channel"):
                        imgui.text_wrapped("User channel: " + effect.params["user_channel"])
                    elif app._row("Effect channel"):
                        choices = ["All"] + [d.value_label for d in CHANNEL_DESCRIPTORS]
                        changed, value = imgui.combo("##effect_channel", int(effect.params.get("channel", 0)) + 1, choices)
                        values = dict(effect.params, channel=value - 1)
                        app._edit_value("Effect channel", effect, "params", values, changed)
            fields = {
                "levels": [("in_lo", "Input low", 0, 1), ("in_hi", "Input high", 0, 1),
                           ("gamma", "Gamma", .01, 5), ("out_lo", "Output low", 0, 1), ("out_hi", "Output high", 0, 1)],
                "blur": [("radius", "Blur radius", 0, 32)],
                "threshold": [("level", "Threshold", 0, 1), ("softness", "Threshold softness", .001, .5)],
                "hsl": [("hue", "Hue", -1, 1), ("saturation", "Saturation", -1, 1), ("lightness", "Lightness", -1, 1)],
                "brightness_contrast": [("brightness", "Brightness", -1, 1), ("contrast", "Contrast", -1, 1)]}
            if kind == "mesh_map":
                self.param(effect, "map", "Mesh map", choices=MESH_MAPS)
                fields = {"mesh_map": fields["levels"]}
            for key, label, lo, hi in fields.get(kind, []):
                self.param(effect, key, label, lo=lo, hi=hi)

    def graph_editor(self, effect, mask):
        import copy
        from .. import graphs
        imgui.text_wrapped("Native graph v1: editable nodes; filters sample this texture set in UV space.")
        presets = ["grunge", "gradient", "transform", "warp", "sharpen"]
        active="grunge" if effect.params["graph"]["nodes"][0]["op"]=="grunge" else effect.params["graph"]["nodes"][-1]["op"]
        changed, index = imgui.combo("Graph recipe", presets.index(active) if active in presets else -1, presets)
        if changed:
            self.set_params(effect, graph=graphs.preset(presets[index]))
        if not mask and effect.params.get("user_channel"):
            imgui.text_wrapped("User channel: " + effect.params["user_channel"])
        elif not mask:
            changed,channel=imgui.combo("Graph channel",int(effect.params.get("channel",0)),[d.label for d in CHANNEL_DESCRIPTORS])
            if changed:self.set_params(effect,channel=channel)
        graph = effect.params["graph"]
        for ni, n in enumerate(graph["nodes"]):
            imgui.push_id(ni)
            if imgui.tree_node(n["id"] + " (" + n["op"] + ")"):
                for key, (_, lo, hi) in graphs.SPECS[n["op"]].items():
                    changed, value = imgui.slider_float(key, float(n["params"][key]), lo, hi)
                    if changed:
                        updated = copy.deepcopy(graph)
                        updated["nodes"][ni]["params"][key] = value
                        self.app._edit_value("Graph " + key, effect, "params", dict(effect.params, graph=updated), True, continuous=True)
                stops=n["params"].get("stops", [])
                for si, stop in enumerate(n["params"].get("stops", [])):
                    lo=stops[si-1][0]+.0001 if si else 0.
                    hi=stops[si+1][0]-.0001 if si+1<len(stops) else 1.
                    changed,position=imgui.slider_float("Position##stop"+str(si),float(stop[0]),lo,hi)
                    if changed:
                        updated=copy.deepcopy(graph);updated["nodes"][ni]["params"]["stops"][si][0]=position
                        self.app._edit_value("Graph stop position",effect,"params",dict(effect.params,graph=updated),True,continuous=True)
                    changed, color = imgui.color_edit3("Stop " + str(si), stop[1:], imgui.ColorEditFlags_.no_inputs)
                    if changed:
                        updated=copy.deepcopy(graph)
                        updated["nodes"][ni]["params"]["stops"][si][1:]=list(color)
                        self.app._edit_value("Graph stop color", effect, "params", dict(effect.params,graph=updated),True,continuous=True)
                if stops and len(stops)<8 and imgui.button("Add gradient stop"):
                    gaps=[(stops[i+1][0]-stops[i][0],i) for i in range(len(stops)-1)]
                    _,i=max(gaps)
                    updated=copy.deepcopy(graph);values=updated["nodes"][ni]["params"]["stops"]
                    values.insert(i+1,[(a+b)*.5 for a,b in zip(values[i],values[i+1])])
                    self.set_params(effect,graph=updated)
                if len(stops)>2 and imgui.button("Remove last gradient stop"):
                    updated=copy.deepcopy(graph);updated["nodes"][ni]["params"]["stops"].pop()
                    self.set_params(effect,graph=updated)
                imgui.tree_pop()
            imgui.pop_id()

    def projection(self, projection):
        app = self.app
        app.p_combo("Mask projection", projection, "mode", PROJECTIONS)
        app.material_ui._vector("Mask scale", projection, "scale", .01, -1024, 1024)
        app.material_ui._vector("Mask offset", projection, "offset", .005)
        app.material_ui._scalar("Mask rotation", projection, "rotation", -180, 180)
        imgui.begin_disabled(projection.mode not in (2, 4))
        app.p_combo("Mask axis", projection, "axis", ["X", "Y", "Z"])
        imgui.end_disabled()
        imgui.begin_disabled(projection.mode != 1)
        app.p_slider("Mask sharpness", projection, "sharpness", .1, 32, dirty=True)
        imgui.end_disabled()

    def set_params(self, effect, **changes):
        self.app._edit_properties("Edit " + effect.name, [(effect, {"params": dict(effect.params, **changes)})])

    def geometry(self, layer):
        app, engine = self.app, self.app.engine
        if not app._section("Geometry mask", ["Parts", "Geometry"]):
            return
        if app._row("All parts") and imgui.button("Show all geometry"):
            engine.set_geometry_mask(None, layer)
        parts = sorted(set(int(engine.mesh.parts[engine.mesh.indices[t, 0], 0]) for t in engine.ts.tri_ids))
        if parts and parts[-1] >= 1024:
            if app._row("Parts"):
                imgui.text_wrapped("This mesh exceeds the current 1024-part geometry mask limit.")
            app._end_section()
            return
        for part in parts:
            if not app._row(f"Part {part}"):
                continue
            name = engine.mesh.part_names[part] if part < len(engine.mesh.part_names or []) else str(part)
            changed, enabled = imgui.checkbox(name + f"##part_{part}", layer.part_mask is None or part in layer.part_mask)
            if changed:
                selected = set(parts if layer.part_mask is None else layer.part_mask)
                selected.add(part) if enabled else selected.discard(part)
                engine.set_geometry_mask(sorted(selected), layer)
        app._end_section()

    def pick(self):
        if not self.pick_target:
            return False
        app, engine = self.app, self.app.engine
        if imgui.is_key_pressed(imgui.Key.escape):
            self.pick_target = None
            return True
        if not app._over(app.vp_rect) or not imgui.is_mouse_clicked(0):
            return False
        layer = engine.layer
        effect = next((e for e in layer.mask_effects if (layer.pid, e.pid) == self.pick_target), None) if layer else None
        self.pick_target = None
        if effect is not None:
            info = engine.pick_info(*app._mouse_vp())
            if info is not None and info.get("set") == engine.active:
                color = engine.gpu.read_texel(engine.bakes.id, info["uv"])[:3].tolist()
                self.set_params(effect, colors=(effect.params.get("colors", []) + [color])[-8:])
                app.msg("Added baked ID color to selection")
        return True
