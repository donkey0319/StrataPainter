"""Visual output-template authoring over the existing validated export manifest."""
import copy
import json
from imgui_bundle import imgui
from .. import exporter
from ..exportsettings import validate
from .theme import V2


class ExportUI:
    def __init__(self, app):
        self.app = app
        self.draft = None
        self.source_key = None
        self.selected = 0
        self.problem = ""

    def snapshot(self):
        app = self.app
        sets = ([ts.pid for i, ts in enumerate(app.engine.sets) if app.export_sets.get(i, True)]
                if app.export_set_identity == id(app.engine.mesh) else [ts.pid for ts in app.engine.sets])
        return validate({"template": copy.deepcopy(app._export_template()), "folder": app.export_dir,
                         "name": app.export_name, "format": app.export_format, "depth": app.export_depth,
                         "size": app.export_size, "padding": app.export_padding, "dilation": app.export_dilation,
                         "sets": sets, "overrides": copy.deepcopy(app.export_overrides)})

    def save_settings(self):
        self.app._export_manifest()
        self.app._edit_properties("Save export settings", [(self.app.engine, {"export_settings": self.snapshot()})])
        self.app.msg("Export settings saved in the document. Save the project to retain them on disk.")

    def restore(self):
        app = self.app
        data = validate(app.engine.export_settings)
        app.export_custom_template = copy.deepcopy(data.get("template"))
        app.export_name = data.get("name", "")
        app.export_format, app.export_depth = data.get("format", ""), data.get("depth", "")
        app.export_size = data.get("size")
        app.export_padding, app.export_dilation = data.get("padding", "infinite"), data.get("dilation", 16)
        app.export_overrides = copy.deepcopy(data.get("overrides", {}))
        if data:
            app.export_dir = data["folder"]
        app.export_sets = {i: not data or ts.pid in data["sets"] for i, ts in enumerate(app.engine.sets)}
        app.export_set_identity = id(app.engine.mesh)
        app.export_template_json = ""
        self.draft, self.source_key, self.problem = None, None, ""

    def sources(self):
        base = list(exporter.SOURCES) + list(self.app.engine.user_channels)
        return base + [name + "." + component for name in sorted(exporter.COLOR_SOURCES) for component in "rgb"]

    def apply(self):
        candidate = copy.deepcopy(self.draft)
        self.app._export_manifest(template=candidate, overrides={})
        self.app.export_custom_template, self.app.export_overrides = candidate, {}
        self.app.export_template_json = json.dumps(candidate, indent=2)
        self.source_key = json.dumps(candidate, sort_keys=True)
        self.problem = ""

    def slot(self, mapping, key, choices):
        current = mapping.get(key, "")
        values = [""] + list(choices)
        if current not in values:
            values.append(current)
        imgui.text(key.upper())
        imgui.set_next_item_width(-1)
        changed, index = imgui.combo("##slot_" + key, values.index(current), ["Default / empty"] + values[1:])
        if changed:
            if values[index]:
                mapping[key] = values[index]
            else:
                mapping.pop(key, None)
        if imgui.begin_drag_drop_target():
            payload = imgui.accept_drag_drop_payload_py_id("STRATA_EXPORT_SOURCE")
            if payload is not None:
                source = self.sources()[payload.data_id]
                if source in choices:
                    mapping[key] = source
                else:
                    self.problem = "Choose a compatible color source for " + key.upper()
            imgui.end_drag_drop_target()

    def draw(self):
        app = self.app
        key = json.dumps(app._export_template(), sort_keys=True)
        if self.draft is None or key != self.source_key:
            self.draft, self.source_key = copy.deepcopy(app._export_template()), key
            self.problem, self.selected = "", 0
        imgui.text_wrapped("Choose an output, set its layout, then select or drag sources into components. Apply updates the export preview.")
        _, self.draft["name"] = imgui.input_text("Template name", self.draft.get("name", "Custom template"))
        maps = self.draft.setdefault("maps", [])
        if imgui.button("Add output"):
            maps.append({"name": "$mesh_$textureSet_Output" + str(len(maps) + 1), "rgb": "basecolor"})
            self.selected = len(maps) - 1
        imgui.same_line()
        imgui.begin_disabled(not maps)
        if imgui.button("Duplicate output") and maps:
            item = copy.deepcopy(maps[self.selected])
            item["name"] += "_copy"
            maps.insert(self.selected + 1, item)
            self.selected += 1
        imgui.same_line()
        if imgui.button("Remove output") and maps:
            maps.pop(self.selected)
            self.selected = max(0, min(self.selected, len(maps) - 1))
        imgui.end_disabled()
        if imgui.begin_table("##template_columns", 3, imgui.TableFlags_.borders_inner_v | imgui.TableFlags_.resizable):
            for title in ("Output textures", "Channel packing", "Available sources"):
                imgui.table_setup_column(title)
            imgui.table_headers_row()
            imgui.table_next_row()
            imgui.table_next_column()
            imgui.begin_child("##outputs", V2(0, 230 * app.ui_scale))
            for index, mapping in enumerate(maps):
                if imgui.selectable(mapping["name"] + "##output" + str(index), index == self.selected)[0]:
                    self.selected = index
            imgui.end_child()
            imgui.table_next_column()
            imgui.begin_child("##packing", V2(0, 230 * app.ui_scale))
            if maps:
                mapping = maps[self.selected]
                imgui.text("Filename")
                imgui.set_next_item_width(-1)
                _, mapping["name"] = imgui.input_text("##Filename", mapping["name"])
                mode = 0 if "rgb" in mapping else 1 if "rgba" in mapping else 2 if "l" in mapping else 3
                imgui.text("Layout")
                imgui.set_next_item_width(-1)
                changed, selected = imgui.combo("##Layout", mode, ["RGB", "RGBA", "Grayscale", "Packed components"])
                if changed:
                    for component in ("rgb", "rgba", "l", "r", "g", "b", "a"):
                        mapping.pop(component, None)
                    mapping[{0: "rgb", 1: "rgba", 2: "l", 3: "r"}[selected]] = "basecolor" if selected < 2 else "0"
                    mode = selected
                channels = [("rgb",), ("rgba",), ("l",), ("r", "g", "b", "a")][mode]
                for channel in channels:
                    self.slot(mapping, channel, sorted(exporter.COLOR_SOURCES) if mode < 2 else self.sources())
                imgui.text_wrapped("Tokens: $mesh, $textureSet, $project, $udim. Per-output format and depth are in Export settings.")
            imgui.end_child()
            imgui.table_next_column()
            imgui.begin_child("##sources", V2(0, 230 * app.ui_scale))
            for index, source in enumerate(self.sources()):
                imgui.selectable(source, False)
                if imgui.begin_drag_drop_source():
                    imgui.set_drag_drop_payload_py_id("STRATA_EXPORT_SOURCE", index)
                    imgui.text(source)
                    imgui.end_drag_drop_source()
            imgui.end_child()
            imgui.end_table()
        if imgui.button("Apply output template"):
            try:
                self.apply()
            except (ValueError, KeyError, TypeError) as error:
                self.problem = str(error)
        imgui.same_line()
        if imgui.button("Revert template edits"):
            self.draft = None
        if self.problem:
            imgui.text_wrapped(self.problem)
