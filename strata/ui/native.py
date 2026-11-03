"""Searchable native shelf calling the shared library/export engine APIs."""
import os
from imgui_bundle import imgui
from .. import library, exporter
from .theme import V2


class NativeUI:
    KINDS = ["smart_materials", "smart_masks", "brushes", "templates"]
    LABELS = ["Smart materials", "Smart masks", "Brushes", "Export templates"]

    def __init__(self, app):
        self.app, self.kind, self.name = app, 0, "My asset"
        self.entries, self.payloads = [], {}
        self.loaded_kind = None

    def refresh(self):
        self.entries = library.list_library(self.KINDS[self.kind])
        self.loaded_kind = self.kind

    def save(self):
        app, e = self.app, self.app.engine
        if self.kind == 0:
            path = library.save_smart_material(e, app._top_selected() or e.layers, name=self.name)
        elif self.kind == 1:
            if e.layer is None:
                raise ValueError("Select a layer with a mask")
            path = library.save_smart_mask(e, e.layer, name=self.name)
        elif self.kind == 2:
            path = library.save_brush_preset(e.brush, name=self.name)
        else:
            path = library._default_path("templates", self.name)
            exporter.save_template(app._export_template(), path)
        self.refresh()
        app.msg("Saved native asset: " + os.path.basename(path))
        return path

    def apply(self, kind, path, target=None):
        app, e = self.app, self.app.engine
        if kind == "smart_materials":
            library.load_smart_material(e, path, parent=target if target is not None and target.is_group else None)
        elif kind == "smart_masks":
            layer = target or e.layer
            if layer is None:
                raise ValueError("Drop a smart mask on a layer")
            library.apply_smart_mask(e, layer, path, replace=True)
        elif kind == "brushes":
            library.load_brush_preset(e.brush, path)
        elif kind == "templates":
            app.export_custom_template = exporter.load_template(path)
            app.export_overrides = {}
        app.msg("Applied native asset: " + os.path.basename(path))

    def drop(self, token, target):
        try:
            self.apply(*self.payloads[token], target=target)
        except Exception as error:
            self.app.msg(f"Native asset failed: {error}")

    def draw(self):
        app = self.app
        changed, self.kind = imgui.combo("Native category", self.kind, self.LABELS)
        if changed or self.loaded_kind != self.kind:
            self.refresh()
        _, self.name = imgui.input_text("Asset name", self.name)
        if imgui.button("Save current as native asset"):
            try:
                self.save()
            except Exception as error:
                app.msg(f"Asset save failed: {error}")
        if imgui.button("Import native asset..."):
            path = app._load_native_file()
            if path:
                try:
                    library.import_native(path, self.KINDS[self.kind])
                    self.refresh()
                except Exception as error:
                    app.msg(f"Asset import failed: {error}")
        imgui.same_line()
        if imgui.button("Refresh native assets"):
            self.refresh()
        imgui.text_wrapped("Double-click to apply, or drag onto the Layer Stack. Saved dependencies are portable.")
        imgui.begin_child("##native_assets")
        for name, path in self.entries:
            if app.asset_query.casefold() not in name.casefold():
                continue
            imgui.push_id(path)
            if os.path.isfile(path + ".png"):
                app.material_ui._preview(path + ".png", "color")
                imgui.same_line()
            else:
                imgui.button(self.LABELS[self.kind][:1], V2(38 * app.ui_scale, 38 * app.ui_scale))
                imgui.same_line()
            clicked, _ = imgui.selectable(name, False, imgui.SelectableFlags_.allow_double_click, V2(0, 38 * app.ui_scale))
            if clicked and imgui.is_mouse_double_clicked(0):
                try:
                    self.apply(self.KINDS[self.kind], path)
                except Exception as error:
                    app.msg(f"Native asset failed: {error}")
            if imgui.begin_drag_drop_source():
                item = (self.KINDS[self.kind], path)
                token = next((n for n, value in self.payloads.items() if value == item), len(self.payloads))
                self.payloads[token] = item
                imgui.set_drag_drop_payload_py_id("STRATA_NATIVE", token)
                imgui.text(name)
                imgui.end_drag_drop_source()
            imgui.pop_id()
        imgui.end_child()
