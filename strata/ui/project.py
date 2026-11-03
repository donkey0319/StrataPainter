"""Project protection controls. All GPU work stays on the application's main thread."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from imgui_bundle import imgui

from .theme import V2


class ProjectUI:
    def __init__(self, app, config_dir, file_dialogs=None):
        self.app = app
        self.file_dialogs = file_dialogs
        self.recovery_dir = Path(config_dir) / "recovery"
        self.session_id = uuid.uuid4().hex
        self.next_check = time.monotonic() + self.interval * 60
        self.last_snapshot = None
        self.last_recovery = None
        self.records = self.discover_recovery()
        self.open_recovery = bool(self.records)
        self.open_resources = False
        self.selected_resource = 0
        self.confirm_recovery = None
        from .reimport import MeshRevisionUI
        self.mesh_revision = MeshRevisionUI(app)

    @property
    def interval(self):
        return max(0, min(60, int(self.app.settings.get("autosave_minutes", 5))))

    @property
    def backups(self):
        return max(1, min(10, int(self.app.settings.get("project_backups", 3))))

    def register_commands(self, registry):
        self.mesh_revision.register_commands(registry)
        for coordinates, label in (("normalized", "Export Mesh (OBJ)..."), ("source", "Export Mesh in Source Coordinates..."),
                                   ("meters", "Export Mesh in Meters...")):
            registry.add("file.export_mesh_" + coordinates, label, "File",
                         lambda coordinates=coordinates: self.export_mesh(coordinates), [], self.app._has)
        registry.add("file.save_portable", "Save Portable Project...", "File",
                     lambda: self.app._save(save_as=True, portable=True), [], self.app._has,
                     tip="Collect referenced resources into the project archive.")
        registry.add("file.resources", "Project Resources...", "File",
                     lambda: setattr(self, "open_resources", True), [], self.app._has)
        registry.add("file.recover", "Recover Autosave...", "File", self.show_recovery)
        registry.add("file.autosave", "Create Recovery Snapshot", "File", self.autosave_now,
                     [], self.app._has)

    def show_recovery(self):
        self.records = self.discover_recovery()
        self.confirm_recovery = None
        self.open_recovery = True

    def export_mesh(self, coordinates="normalized", path=None):
        if path is None:
            if self.file_dialogs is None:
                return
            path = self.file_dialogs.save_file("Export mesh", "prepared.obj", ["Wavefront OBJ", "*.obj"]).result()
        if not path:
            return
        try:
            from ..exporter import export_mesh
            self.app._finish_property_edit()
            self.app.engine.end_stroke()
            export_mesh(self.app.engine, path, coordinates)
            self.app.msg("Exported mesh with generated UVs: " + str(path))
        except Exception as error:
            self.app.msg("Mesh export failed: " + str(error))

    def discover_recovery(self):
        records = []
        if not self.recovery_dir.is_dir():
            return records
        for metadata_path in self.recovery_dir.glob("*.json"):
            try:
                record = json.loads(metadata_path.read_text(encoding="utf-8"))
                filename = record["file"]
                if not isinstance(filename, str) or Path(filename).name != filename:
                    continue
                snapshot = self.recovery_dir / filename
                if snapshot.suffix != ".strata":
                    continue
                source = record.get("source")
                candidates = [snapshot] + [Path(str(snapshot) + f".bak{i}") for i in range(1, 11)]
                for candidate in candidates:
                    if not candidate.is_file():
                        continue
                    # A successful later manual save supersedes older recovery snapshots.
                    if source and Path(source).is_file() and Path(source).stat().st_mtime >= candidate.stat().st_mtime:
                        continue
                    item = dict(record, path=str(candidate), timestamp=candidate.stat().st_mtime)
                    item["backup"] = candidate != snapshot
                    records.append(item)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return sorted(records, key=lambda r: r["timestamp"], reverse=True)

    def _snapshot_path(self):
        source = self.app.project_path
        identity = os.path.normcase(os.path.abspath(source)) if source else self.session_id
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        return self.recovery_dir / (key + ".strata")

    def autosave_now(self):
        engine = self.app.engine
        if engine.mesh is None:
            return False
        path = self._snapshot_path()
        try:
            self.recovery_dir.mkdir(parents=True, exist_ok=True)
            engine.autosave(str(path), backups=self.backups)
            record = {"file": path.name, "source": self.app.project_path,
                      "name": engine.mesh.name, "timestamp": time.time()}
            metadata = path.with_suffix(".json")
            temporary = metadata.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
            os.replace(temporary, metadata)
            self.last_snapshot = (id(engine.mesh), engine._edit_serial, engine._signature())
            self.last_recovery = str(path)
            self.app.msg("Recovery snapshot saved" +
                         ("; your project still has its unsaved changes." if engine.modified else "."))
            return True
        except Exception as error:
            self.app.msg(f"Recovery snapshot failed: {error}")
            return False

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if now < self.next_check:
            return
        self.next_check = now + max(1, self.interval) * 60
        engine = self.app.engine
        if (not self.interval or engine.mesh is None or self.app.pending or self.app.drag
                or getattr(engine, "_stroke", None) is not None or not engine.modified):
            return
        stamp = (id(engine.mesh), engine._edit_serial, engine._signature())
        if stamp != self.last_snapshot:
            self.autosave_now()

    def recover(self, record):
        # Engine.load is transactional; only update the UI after successful adoption.
        try:
            self.app.engine.load(record["path"])
            self.app.engine.mark_modified()
            if hasattr(self.app, "_release_clip"):
                self.app._release_clip()
            self.app.project_path = record.get("source") or None
            self.app.uv.reset()
            self.app.sel_uids, self.app._last_primary = set(), None
            self.last_snapshot = None
            self.app.msg(f"Recovered {record.get('name', 'project')}; save to keep the recovered work.")
            return True
        except Exception as error:
            self.app.msg(f"Recovery failed: {error}")
            return False

    def relink(self, resource, replacement):
        try:
            identity = resource.get("id") or resource.get("source")
            if not self.app.engine.relink_resources({identity: replacement}):
                raise ValueError("Resource is no longer recorded; save and refresh the resource list.")
            self.app.msg(f"Relinked {os.path.basename(replacement)}")
            return True
        except Exception as error:
            self.app.msg(f"Relink failed: {error}")
            return False

    def settings(self):
        app = self.app
        if not app._section("Project protection", ["Autosave", "Minutes", "Backups"]):
            return
        if app._row("Autosave"):
            changed, enabled = imgui.checkbox("##autosave", self.interval > 0)
            if changed:
                app.settings["autosave_minutes"] = 5 if enabled else 0
                self.next_check = time.monotonic() + max(1, self.interval) * 60
                app._save_settings()
        if self.interval and app._row("Minutes"):
            changed, value = imgui.slider_int("##autosave_minutes", self.interval, 1, 60)
            if changed:
                app.settings["autosave_minutes"] = value
                self.next_check = time.monotonic() + value * 60
                app._save_settings()
        if app._row("Backups"):
            changed, value = imgui.slider_int("##project_backups", self.backups, 1, 10)
            if changed:
                app.settings["project_backups"] = value
                app._save_settings()
        imgui.text_wrapped("Recovery snapshots preserve unsaved work. Save Portable Project collects external resources.")
        app._end_section()

    def dialogs(self):
        self.mesh_revision.draw()
        scale = self.app.ui_scale
        if self.open_recovery and not self.app.pending:
            imgui.open_popup("Recover Project")
            self.open_recovery = False
        imgui.set_next_window_size(V2(660 * scale, 420 * scale), imgui.Cond_.appearing)
        if imgui.begin_popup_modal("Recover Project", None)[0]:
            imgui.text_wrapped("Recovery snapshots are separate from your saved project. Recovering opens a snapshot as unsaved work.")
            if self.confirm_recovery is not None:
                imgui.text_wrapped("The current project has unsaved changes. Save it first or confirm replacement below.")
                if imgui.button("Replace current project"):
                    if self.recover(self.confirm_recovery):
                        imgui.close_current_popup()
                    self.confirm_recovery = None
                imgui.same_line()
                if imgui.button("Keep current project"):
                    self.confirm_recovery = None
            else:
                imgui.begin_child("##recoveries", V2(0, -45 * scale))
                if not self.records:
                    imgui.text_disabled("No newer recovery snapshots found.")
                for i, record in enumerate(self.records):
                    date = time.strftime("%Y-%m-%d %H:%M", time.localtime(record["timestamp"]))
                    suffix = "  (backup)" if record.get("backup") else ""
                    label = f"{record.get('name', 'Project')}  {date}{suffix}##recovery{i}"
                    if imgui.selectable(label, False, imgui.SelectableFlags_.no_auto_close_popups)[0]:
                        if self.app.engine.modified:
                            self.confirm_recovery = record
                        elif self.recover(record):
                            imgui.close_current_popup()
                    imgui.text_wrapped(record.get("source") or "Unsaved project")
                imgui.end_child()
            if imgui.button("Close##recovery") or imgui.is_key_pressed(imgui.Key.escape):
                self.confirm_recovery = None
                imgui.close_current_popup()
            imgui.end_popup()

        if self.open_resources:
            imgui.open_popup("Project Resources")
            self.open_resources = False
        imgui.set_next_window_size(V2(700 * scale, 480 * scale), imgui.Cond_.appearing)
        if imgui.begin_popup_modal("Project Resources", None)[0]:
            records = getattr(self.app.engine, "project_resources", [])
            diagnostics = getattr(self.app.engine, "project_diagnostics", [])
            imgui.text_wrapped("Use Save Portable Project to collect source files. Select a resource to relink it.")
            imgui.begin_child("##project_resources", V2(0, -125 * scale))
            for i, resource in enumerate(records):
                name = os.path.basename(resource.get("source") or resource.get("resolved") or resource.get("id", "Resource"))
                label = f"{name}  [{resource.get('status', 'available')}]##resource{i}"
                if imgui.selectable(label, self.selected_resource == i,
                                    imgui.SelectableFlags_.no_auto_close_popups)[0]:
                    self.selected_resource = i
                imgui.text_wrapped(resource.get("source") or resource.get("resolved") or "Embedded resource")
            if not records:
                imgui.text_disabled("No external resources recorded. Save the project to refresh its resource manifest.")
            for diagnostic in diagnostics:
                imgui.text_wrapped(str(diagnostic.get("message", diagnostic)))
            imgui.end_child()
            imgui.begin_disabled(not records or self.file_dialogs is None)
            if imgui.button("Relink selected...") and records:
                resource = records[min(self.selected_resource, len(records) - 1)]
                chosen = self.file_dialogs.open_file("Relink resource", "", ["All files", "*"]).result()
                if chosen:
                    self.relink(resource, chosen[0])
            imgui.end_disabled()
            imgui.same_line()
            if imgui.button("Save portable..."):
                self.app._save(save_as=True, portable=True)
            if imgui.button("Close##resources") or imgui.is_key_pressed(imgui.Key.escape):
                imgui.close_current_popup()
            imgui.end_popup()
