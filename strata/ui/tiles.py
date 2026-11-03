"""Material tile browser and explicit paint-on-release UV paths."""
from contextlib import ExitStack, contextmanager
import numpy as np
from imgui_bundle import imgui
from ..tiles import TileAddress
from ..tilepreview import CHANNELS
from ..channels import CHANNEL_DESCRIPTORS
from ..viewinput import UVMapping
from .theme import V2, col32


class TilesUI:
    def __init__(self, app):
        self.app, self.open = app, False
        self.selected, self.isolate, self.channel = TileAddress(), False, 0
        self.zoom, self.center, self.identity = 1., np.array([.5, .5]), None
        self.path, self.mapping, self.error = None, None, ""
        self.image_path, self.image_channel, self.image_target = "", 0, None
        self.frame_leases = []

    @contextmanager
    def leases(self):
        stack = ExitStack()
        self.frame_leases.append(stack)
        yield stack

    def finish_frame(self):
        for stack in reversed(self.frame_leases):
            stack.close()
        self.frame_leases.clear()

    def fit(self, addresses):
        low = np.min([address.to_list() for address in addresses], axis=0)
        high = np.max([address.to_list() for address in addresses], axis=0) + 1
        self.center, self.zoom = (low + high) / 2, 1.

    def draw(self):
        if not self.open:
            self.path = None
            return
        imgui.set_next_window_size(V2(820, 720), imgui.Cond_.first_use_ever)
        visible, self.open = imgui.begin("Material tiles", self.open)
        try:
            if not visible or not self.open:
                self.path = None
                return
            e = self.app.engine
            ts = e.ts
            if ts is None:
                imgui.text_wrapped("Open a project to inspect material tiles.")
                return
            imgui.text_wrapped("Browser paths paint on release. Main 3D and 2D support live paint. Tiled clone, smudge and quick mask remain unavailable.")
            if ts.tiles is None:
                imgui.text_wrapped("Enabling tiles moves this material's legacy pixels to 1001. Other covered tiles start unpainted. Save a copy to retain a single-tile version.")
                if imgui.button("Enable material tiles"):
                    try:
                        e.enable_tiles()
                        self.error = ""
                    except Exception as error:
                        self.error = str(error)
                if self.error:
                    imgui.text_wrapped(self.error)
                return
            m = ts.tiles
            if self.identity != (id(m), ts.pid):
                self.identity, self.path = (id(m), ts.pid), None
                self.selected = self.selected if self.selected in m.addresses else m.addresses[0]
                self.fit(m.addresses)
            changed, index = imgui.combo("Tile", m.addresses.index(self.selected), [str(address.udim) for address in m.addresses])
            if changed:
                self.selected, self.path = m.addresses[index], None
                if self.isolate:
                    self.fit((self.selected,))
            changed, self.isolate = imgui.checkbox("Isolate tile", self.isolate)
            if changed:
                self.path = None
                self.fit((self.selected,) if self.isolate else m.addresses)
            imgui.same_line()
            if imgui.button("Fit tile grid"):
                self.fit((self.selected,) if self.isolate else m.addresses)
            _, self.channel = imgui.combo("Preview channel", self.channel, list(CHANNELS))
            imgui.text_disabled(f"{len(m.addresses)} tiles | {m.res}px authored | {min(m.res, 256)}px preview")
            if e.layer is not None and e.layer.kind == "fill":
                _, self.image_channel = imgui.combo("Image channel", self.image_channel, [channel.value_label for channel in CHANNEL_DESCRIPTORS])
                channel = CHANNEL_DESCRIPTORS[self.image_channel].key
                target = (e.layer.pid, channel, self.selected.udim)
                if target != self.image_target:
                    self.image_target = target
                    self.image_path = m.sequences.get(e.layer.pid, {}).get(channel, {}).get(str(self.selected.udim), "")
                _, self.image_path = imgui.input_text("Tile image path", self.image_path)
                if imgui.button("Assign tile image"):
                    try:
                        paths = {int(udim): path for udim, path in m.sequences.get(e.layer.pid, {}).get(channel, {}).items()}
                        if self.image_path.strip():
                            paths[self.selected.udim] = self.image_path.strip()
                        else:
                            paths.pop(self.selected.udim, None)
                        e.assign_tile_sequence(e.layer, channel, paths)
                        self.error = ""
                    except Exception as error:
                        self.error = str(error)
                if channel in m.sequences.get(e.layer.pid, {}):
                    imgui.same_line()
                    if imgui.button("Remove channel sequence"):
                        try:
                            e.assign_tile_sequence(e.layer, channel, None)
                            self.image_target, self.error = None, ""
                        except Exception as error:
                            self.error = str(error)
            missing = m.sequence_diagnostics()
            if missing:
                imgui.text_wrapped("Missing tile images: " + ", ".join(f"{item['udim']} {item['channel']} ({item['status']})" for item in missing))
            if self.error:
                imgui.text_wrapped(self.error)
            self.canvas(m)
        finally:
            imgui.end()

    def canvas(self, material):
        e = self.app.engine
        addresses = (self.selected,) if self.isolate else material.addresses
        available = imgui.get_content_region_avail()
        w, h = int(max(float(available.x), 100.)), int(max(float(available.y), 140.))
        origin = imgui.get_cursor_screen_pos()
        imgui.invisible_button("Tile UV canvas", V2(w, h))
        hovered, io = imgui.is_item_hovered(), imgui.get_io()
        low = np.min([address.to_list() for address in addresses], axis=0)
        high = np.max([address.to_list() for address in addresses], axis=0) + 1
        step = min(w / (high[0] - low[0] + .16), h / (high[1] - low[1] + .16)) * self.zoom
        mapping = UVMapping((w, h), 1.08 * step / min(w, h), tuple(self.center))
        mouse = np.array([io.mouse_pos.x - origin.x, h - (io.mouse_pos.y - origin.y)])
        if hovered and io.mouse_wheel and self.path is None:
            anchor = mapping.uv(mouse)
            old_zoom = self.zoom
            self.zoom = float(np.clip(self.zoom * 1.15 ** io.mouse_wheel, .2, 32))
            new_step = step * self.zoom / old_zoom
            # Keep the world point under the pointer fixed while zooming.
            updated = UVMapping((w, h), 1.08 * new_step / min(w, h), tuple(self.center))
            self.center += anchor - updated.uv(mouse)
            step = new_step
            mapping = UVMapping((w, h), updated.zoom, tuple(self.center))
        if hovered and imgui.is_mouse_down(2) and self.path is None:
            self.center += np.array([-io.mouse_delta.x, io.mouse_delta.y]) / step
            mapping = UVMapping((w, h), mapping.zoom, tuple(self.center))
        self.canvas_mapping, self.canvas_origin, self.canvas_size = mapping, (origin.x, origin.y), (w, h)
        def owner():
            effect = e.active_mask_paint()
            return (e.ts.pid, e.layer.pid if e.layer else None, effect.pid if effect else None, e.brush.target)
        if imgui.is_key_pressed(imgui.Key.escape):
            self.path = None
        if hovered and imgui.is_mouse_clicked(0) and e.can_paint():
            from ..journal import freeze_brush
            try:
                self.path_brush = freeze_brush(e.brush)
                self.path_owner = owner()
                self.path, self.mapping = [], mapping
            except Exception as error:
                self.error = str(error)
        if self.path is not None and owner() != self.path_owner:
            self.path, self.error = None, "The paint target changed; the pending UV path was cancelled."
        if self.path is not None:
            if imgui.is_mouse_down(0):
                uv = self.mapping.uv(mouse)
                sample = (*uv, self.app.tablet.pressure)
                if not self.path or np.linalg.norm(np.asarray(sample[:2]) - self.path[-1][:2]) > 1e-6:
                    self.path.append(sample)
            else:
                points, self.path = self.path, None
                try:
                    if points:
                        e.paint_tiles_uv(points, self.mapping, brush=self.path_brush)
                    self.error = ""
                except Exception as error:
                    self.error = str(error)
        dl = imgui.get_window_draw_list()
        dl.push_clip_rect(origin, V2(origin.x + w, origin.y + h), True)
        try:
            dl.add_rect_filled(origin, V2(origin.x + w, origin.y + h), col32(.055, .06, .065))
            def screen(uv):
                point = mapping.pixel(uv)
                return V2(origin.x + point[0], origin.y + h - point[1])
            # ImGui consumes these handles after this function returns. The App
            # releases their leases only after submitting the complete draw list.
            with self.leases() as leases:
                for address in addresses:
                    lo, hi = screen(address.to_list()), screen(np.array(address.to_list()) + 1)
                    top, bottom = V2(lo.x, hi.y), V2(hi.x, lo.y)
                    if bottom.x < origin.x or top.x > origin.x + w or bottom.y < origin.y or top.y > origin.y + h:
                        continue
                    try:
                        texture = leases.enter_context(material.preview(address, self.channel, 256))
                        dl.add_image(imgui.ImTextureRef(texture.glo), top, bottom, V2(0, 1), V2(1, 0))
                    except Exception as error:
                        self.error = str(error)
                    dl.add_rect(top, bottom, col32(.45, .6, .75) if address == self.selected else col32(.3, .3, .3))
                    dl.add_text(V2(top.x + 5, top.y + 4), col32(.95, .95, .95), str(address.udim))
                if self.path:
                    for first, second in zip(self.path, self.path[1:]):
                        dl.add_line(screen(first[:2]), screen(second[:2]), col32(1., .65, .2), 2.)
        finally:
            dl.pop_clip_rect()
