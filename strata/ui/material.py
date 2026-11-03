"""Fill-map, projection and per-channel authoring controls.

All document writes go through engine transactions. This component keeps only
session selection/preview state; paths and projection settings live in layers.
"""
from __future__ import annotations

import math
import os

from imgui_bundle import imgui

from ..channels import CHANNEL_DESCRIPTORS, BY_KEY
from ..imageio import read_image
from ..layers import BLEND_MODES, PROJECTIONS
from .theme import V2


RESOLUTIONS = [64, 128, 256, 512, 1024, 2048, 4096, 8192]


class MaterialUI:
    def __init__(self, app):
        self.app = app
        self.imported_images = []
        self.transform_tool = None
        self.warp_corner=0
        self.transform_layer_pid = None
        self._resolution = {}
        self._preview_errors = {}

    def import_resources(self, paths):
        """Decode dropped/imported files before offering them in the image list."""
        registered = []
        for path in paths:
            path = os.path.abspath(os.path.expanduser(os.fspath(path)))
            try:
                read_image(path)
            except Exception as error:
                self.app.msg(f"Image import failed: {os.path.basename(path)}: {error}")
                continue
            if path not in self.imported_images:
                self.imported_images.append(path)
            registered.append(path)
        return registered

    def resource_paths(self):
        """Current project image references plus independently imported images."""
        engine = self.app.engine
        paths = list(self.imported_images)
        for layer in engine.all_layers_all_sets():
            paths.extend((layer.maps or {}).values())
            for effect in layer.effects + layer.mask_effects:
                if effect.kind == "fill" and effect.params.get("map"):
                    paths.append(effect.params["map"])
        for record in engine.project_resources:
            if "high_poly" not in record.get("roles", []):
                path = record.get("resolved") or record.get("source")
                if path:
                    paths.append(path)
        return list(dict.fromkeys(path for path in paths if path and not path.startswith(("bake:", "builtin:"))))

    def assign_map(self, layer, key, path):
        """Use one validated, undoable assignment for file dialogs and the picker."""
        self.app._finish_property_edit()
        try:
            changed = self.app.engine.assign_fill_map(layer, key, path or None)
        except Exception as error:
            self.app.msg(f"Could not assign {BY_KEY[key].value_label} map: {error}")
            return False
        if path:
            path = layer.maps[key]
            if path not in self.imported_images:
                self.imported_images.append(path)
        self.app.msg(f"{BY_KEY[key].value_label} map {'assigned' if path else 'cleared'}")
        return changed

    def _preview(self, path, kind):
        app = self.app
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        cache_key = (path, mtime)
        if cache_key in self._preview_errors:
            imgui.text_disabled("Image unavailable")
            if imgui.is_item_hovered():
                imgui.set_tooltip(self._preview_errors[cache_key])
            return
        try:
            texture = (app.engine.bakes.maps().get(path[5:]) if path.startswith("bake:") else
                       app.engine.resources.texture(path, "preview" if kind == "color" else kind))
            if texture is not None:
                side = min(48 * app.ui_scale, imgui.get_content_region_avail().x)
                imgui.image(imgui.ImTextureRef(texture.glo), V2(side, side), V2(0, 1), V2(1, 0))
                if imgui.is_item_hovered():
                    imgui.set_tooltip(f"{path}\n{texture.size[0]} x {texture.size[1]} ({kind})")
        except Exception as error:
            self._preview_errors[cache_key] = str(error)
            imgui.text_disabled("Image unavailable")

    def draw(self, layer):
        self.bitmap_slots(layer)
        self.projection(layer)

    def bitmap_slots(self, layer):
        app = self.app
        labels = [channel.value_label + " map" for channel in CHANNEL_DESCRIPTORS]
        if not app._section("Bitmap maps", labels):
            return
        paths = self.resource_paths()
        for channel in CHANNEL_DESCRIPTORS:
            key = channel.key
            if not app._row(channel.value_label + " map", "Maps override the constant value for this channel."):
                continue
            imgui.push_id("fillmap_" + key)
            path = (layer.maps or {}).get(key)
            changed, enabled = imgui.checkbox("Enabled##mapenabled_" + key, bool(layer.enabled[channel.index]))
            flags = list(layer.enabled)
            flags[channel.index] = enabled
            app._edit_value("Enable " + channel.value_label + " map", layer, "enabled", flags, changed)
            if path:
                self._preview(path, channel.resource_kind)
                imgui.same_line()
                imgui.text_wrapped(os.path.basename(path))
                if imgui.is_item_hovered():
                    imgui.set_tooltip(path)
                if app.engine.color.managed and key in ("C", "E"):
                    import hashlib
                    from pathlib import Path
                    try:
                        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                        current = app.engine.color.settings.resource_spaces.get(digest)
                        labels = ["Auto input space", "sRGB input", "Linear input"]
                        values = [None, "srgb", "linear"]
                        changed, selected = imgui.combo("Color interpretation##" + key, values.index(current), labels)
                        if changed:
                            app.engine.set_resource_color_space(path, values[selected])
                    except Exception as error:
                        imgui.text_wrapped(str(error))
            else:
                imgui.text_disabled("Constant value")
            if imgui.button("Load / Relink##fillmap_" + key):
                replacement = app._load_image("Select " + channel.value_label + " map")
                if replacement:
                    self.assign_map(layer, key, replacement)
            if imgui.get_content_region_avail().x > 190 * app.ui_scale:
                imgui.same_line(0, 3)
            imgui.begin_disabled(not path)
            if imgui.button("Clear##fillmap_" + key):
                self.assign_map(layer, key, None)
            imgui.end_disabled()
            imgui.set_next_item_width(-1)
            if imgui.begin_combo("##resource_" + key, "Choose imported image..."):
                if not paths:
                    imgui.text_disabled("Load an image or drop image files into the app.")
                for index, candidate in enumerate(paths):
                    if imgui.selectable(os.path.basename(candidate) + f"##resource_{key}_{index}", candidate == path)[0]:
                        self.assign_map(layer, key, candidate)
                    if imgui.is_item_hovered():
                        imgui.set_tooltip(candidate)
                imgui.end_combo()
            imgui.pop_id()
        app._end_section()

    def _vector(self, label, projection, attribute, speed, lo=0., hi=0.):
        app = self.app
        if not app._row(label, "Negative scale mirrors the image; scale cannot be zero." if attribute == "scale" else ""):
            return
        changed, values = imgui.drag_float2("##" + label, list(getattr(projection, attribute)), speed, lo, hi, "%.3f")
        if changed:
            if not all(math.isfinite(value) for value in values):
                app._finish_property_edit(cancel=True)
                app.msg(label + " requires finite numbers")
                return
            if lo < hi:
                values = [max(lo, min(hi, value)) for value in values]
            if attribute == "scale":
                values = [value if abs(value) >= .001 else math.copysign(.001, value or previous)
                          for value, previous in zip(values, projection.scale)]
        app._edit_value(label, projection, attribute, list(values), changed, continuous=True)

    def _scalar(self, label, projection, attribute, lo, hi, fmt="%.2f", tip=""):
        app = self.app
        if not app._row(label, tip):
            return
        changed, value = imgui.slider_float("##" + label, float(getattr(projection, attribute)), lo, hi, fmt,
                                            imgui.SliderFlags_.always_clamp)
        if changed and not math.isfinite(value):
            app._finish_property_edit(cancel=True)
            app.msg(label + " requires a finite number")
            return
        app._edit_value(label, projection, attribute, max(lo, min(hi, value)), changed, continuous=True)

    def projection(self, layer):
        app, projection = self.app, layer.proj
        labels = ["Mapping", "Projection scale", "Projection offset", "Projection rotation", "Projection axis",
                  "Tri-planar sharpness", "Physical repeat", "Source physical units", "Transform", "Warp", "Decal", "Reset projection"]
        if not app._section("Fill projection", labels):
            return
        if projection.decal or (layer.authored and layer.authored["kind"]=="text"):
            if app._row("Mapping"):
                modes=[0,2];changed,index=imgui.combo("##authored_mapping",modes.index(projection.mode),[PROJECTIONS[i] for i in modes])
                if changed:app._edit_value("Mapping",projection,"mode",modes[index],True)
        else:app.p_combo("Mapping", projection, "mode", PROJECTIONS)
        self._vector("Projection scale", projection, "scale", .01, -1024., 1024.)
        from ..uvprep import meters_per_project_unit
        try:
            meters_per_project_unit(app.engine.mesh)
            units_known = True
        except ValueError:
            units_known = False
        imgui.begin_disabled(not units_known or projection.mode not in (1, 2))
        self._scalar("Physical repeat", projection, "repeat_meters", 0., 10., "%.4f m",
                     tip="Planar/tri-planar period in meters. Zero uses ordinary projection scale; nonzero scale multiplies physical frequency.")
        imgui.end_disabled()
        if app._row("Source physical units"):
            imgui.text_unformatted(app.engine.mesh.extra.get("physical", {}).get("unit", "unspecified"))
        self._vector("Projection offset", projection, "offset", .005)
        self._scalar("Projection rotation", projection, "rotation", -180., 180., "%.1f deg")
        imgui.begin_disabled(projection.mode not in (2, 4))
        app.p_combo("Projection axis", projection, "axis", ["X", "Y", "Z"],
                    tip="Axis applies to planar and cylindrical mapping.")
        imgui.end_disabled()
        imgui.begin_disabled(projection.mode != 1)
        self._scalar("Tri-planar sharpness", projection, "sharpness", .1, 32.,
                     tip="Blend sharpness applies to tri-planar mapping.")
        imgui.end_disabled()
        if app._row("Transform"):
            has_maps = bool(layer.maps) or layer.authored is not None
            imgui.begin_disabled(not has_maps)
            inline = imgui.get_content_region_avail().x > 235 * app.ui_scale
            for index, tool in enumerate(("translate", "rotate", "scale", "warp")):
                if index and inline:
                    imgui.same_line(0, 2)
                if imgui.button(tool.title() + "##fill_transform"):
                    app._finish_property_edit()
                    self.transform_tool, self.transform_layer_pid = tool, layer.pid
            imgui.end_disabled()
            if self.transform_layer_pid == layer.pid and self.transform_tool:
                if imgui.button("Done##fill_transform"):
                    app._finish_property_edit()
                    self.transform_tool = self.transform_layer_pid = None
                imgui.text_wrapped("Left-drag in viewport; Esc cancels gesture; Done returns to painting.")
            elif not has_maps:
                imgui.text_wrapped("Load a bitmap map to see projection changes.")
        if app._row("Warp corner"):
            _,self.warp_corner=imgui.combo("##warp_corner",self.warp_corner,["Bottom left","Bottom right","Top right","Top left"])
            corners=[list(point) for point in projection.warp] if projection.warp is not None else [[0.,0.],[1.,0.],[1.,1.],[0.,1.]]
            changed,point=imgui.drag_float2("##warp_coordinates",corners[self.warp_corner],.002,-32,32)
            if changed:
                corners[self.warp_corner]=list(point)
                try:app._edit_value("Warp corner",projection,"warp",corners,True,continuous=True)
                except ValueError as error:app.msg(str(error))
        if app._row("Decal clipping"):
            imgui.begin_disabled(projection.mode not in (0,2))
            changed,value=imgui.checkbox("Clip outside projection",projection.decal)
            if changed:app._edit_value("Decal clipping",projection,"decal",value,True)
            imgui.end_disabled()
        if app._row("Reset projection") and imgui.button("Reset mapping##fill_projection"):
            app._edit_properties("Reset fill projection", [(projection, {
                "mode": 0, "scale": [1., 1.], "offset": [0., 0.], "rotation": 0., "axis": 1, "sharpness": 4., "warp":None, "decal":False})])
        app._end_section()

    def channel_blending(self, layer):
        app = self.app
        labels = [channel.value_label + " blend" for channel in CHANNEL_DESCRIPTORS]
        labels.extend(channel.value_label + " opacity" for channel in CHANNEL_DESCRIPTORS)
        if not app._section("Channel blending", labels, default_open=False):
            return
        for channel in CHANNEL_DESCRIPTORS:
            key, index = channel.key, channel.index
            modes = ([0, 5, 6, 7, 29, 30, 31] if key == "N" else
                     list(range(29)) if key in ("C", "E") else list(range(24)))
            modes = [-1] + modes
            current = layer.chan_blend[index]
            current = -1 if current is None else current
            if current not in modes:
                modes.append(current)  # preserve imported legacy settings visibly
            names = ["Inherit layer/default" if mode < 0 else
                     BLEND_MODES[mode] if mode < len(BLEND_MODES) else f"Imported mode {mode}" for mode in modes]
            if app._row(channel.value_label + " blend"):
                changed, chosen = imgui.combo("##blend_" + key, modes.index(current), names)
                values = list(layer.chan_blend)
                values[index] = modes[chosen]
                app._edit_value(channel.value_label + " blend", layer, "chan_blend", values, changed)
            if app._row(channel.value_label + " opacity", "Contribution of this channel within the layer."):
                changed, value = imgui.slider_float("##opacity_" + key, float(layer.chan_opacity[index]), 0., 1., "%.2f")
                values = list(layer.chan_opacity)
                values[index] = value
                app._edit_value(channel.value_label + " opacity", layer, "chan_opacity", values, changed, continuous=True)
        app._end_section()

    def texture_set_resolution(self):
        app, engine = self.app, self.app.engine
        texture_set = engine.ts
        if texture_set is None or not app._row("Resolution", "Replay supported native operations, resample raster bases, and rebake mesh maps. Clears undo history after success."):
            return
        sizes = sorted(set(RESOLUTIONS + [texture_set.res]))
        selection = self._resolution.get(texture_set.pid, texture_set.res)
        if selection not in sizes:
            selection = texture_set.res
        changed, index = imgui.combo("##Fill set resolution", sizes.index(selection), [f"{size} x {size}" for size in sizes])
        if changed:
            selection = self._resolution[texture_set.pid] = sizes[index]
        imgui.text_wrapped("Applies to this set only. A successful resize clears undo history.")
        imgui.text_wrapped("Native paint is regenerated. Legacy/imported raster bases and clone/smudge checkpoints are resampled.")
        imgui.begin_disabled(selection == texture_set.res)
        if imgui.button("Apply resolution"):
            app._finish_property_edit()
            target_index = next(i for i, candidate in enumerate(engine.sets) if candidate is texture_set)
            def change_resolution():
                try:
                    engine.set_resolution(selection, ts_index=target_index)
                    app.msg(f"{texture_set.name}: resolution changed to {selection}px")
                except Exception as error:
                    app.msg(f"Resolution change failed: {error}")
            app._run_busy("Resizing " + texture_set.name, change_resolution,
                          "Replaying native paint, resampling raster bases and rebuilding mesh maps")
        imgui.end_disabled()
