"""Explicit legacy/OCIO managed color contract, with lazy optional runtime imports."""
from dataclasses import dataclass, field, asdict
import hashlib
import json
from pathlib import Path
import numpy as np

CONFIG = "studio-config-v2.2.0_aces-v1.3_ocio-v2.4"


@dataclass
class ColorSettings:
    mode: str = "legacy"
    config: str = CONFIG
    input_space: str = "sRGB - Texture"
    working_space: str = "Linear Rec.709 (sRGB)"
    display: str = "sRGB - Display"
    view: str = "Un-tone-mapped"
    resource_spaces: dict = field(default_factory=dict)


class ColorPipeline:
    def __init__(self, settings=None):
        if settings is None:
            settings = ColorSettings()
        if isinstance(settings, dict):
            if set(settings) - set(ColorSettings.__dataclass_fields__):
                raise ValueError("Unknown color configuration field")
            settings = ColorSettings(**settings)
        if settings.mode not in ("legacy", "managed"):
            raise ValueError("Unknown color mode")
        if (not isinstance(settings.resource_spaces, dict) or any(
                not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key)
                or value not in ("srgb", "linear") for key, value in settings.resource_spaces.items())):
            raise ValueError("Invalid immutable-resource color interpretation")
        self.settings = settings
        self.managed = settings.mode == "managed"
        self.input_shader = self.display_shader = ""
        self.version, self.config_id = None, None
        if self.managed:
            try:
                import PyOpenColorIO as ocio
            except ImportError as error:
                raise RuntimeError("Managed mode requires requirements-managed.txt (OpenColorIO)") from error
            if (settings.config, settings.input_space, settings.working_space, settings.display, settings.view) != (
                    CONFIG, "sRGB - Texture", "Linear Rec.709 (sRGB)", "sRGB - Display", "Un-tone-mapped"):
                raise ValueError("This build supports only the documented fixed managed color configuration")
            self.config = ocio.Config.CreateFromBuiltinConfig(settings.config)
            self.version, self.config_id = ocio.__version__, self.config.getCacheID()
            processor = self.config.getProcessor(settings.input_space, settings.working_space)
            self.input = processor.getDefaultCPUProcessor()
            self.output = self.config.getProcessor(settings.working_space, settings.input_space).getDefaultCPUProcessor()
            display = ocio.DisplayViewTransform()
            display.setSrc(settings.working_space)
            display.setDisplay(settings.display)
            display.setView(settings.view)
            display_processor = self.config.getProcessor(display)
            self.display = display_processor.getDefaultCPUProcessor()
            def shader(processor, name):
                descriptor = ocio.GpuShaderDesc.CreateShaderDesc()
                descriptor.setLanguage(ocio.GPU_LANGUAGE_GLSL_4_0)
                descriptor.setFunctionName(name)
                descriptor.setResourcePrefix(name + "_")
                processor.getDefaultGPUProcessor().extractGpuShaderInfo(descriptor)
                if list(descriptor.getTextures()) or list(descriptor.get3DTextures()):
                    raise ValueError("The fixed managed transform unexpectedly requires LUT resources")
                return descriptor.getShaderText()
            self.input_shader = shader(processor, "ocio_input")
            self.display_shader = shader(display_processor, "ocio_display")
        self.cache_id = hashlib.sha256(json.dumps({"settings": asdict(settings), "ocio": self.version,
                                                  "config": self.config_id}, sort_keys=True).encode()).hexdigest()

    def metadata(self):
        return {"settings": asdict(self.settings), "ocio_version": self.version, "config_id": self.config_id}

    def working(self, rgb):
        array = np.array(rgb, np.float32, copy=True, order="C")
        if self.managed:
            self.input.applyRGB(array.reshape(-1, 3))
        return array

    def encoded(self, rgb):
        array = np.array(rgb, np.float32, copy=True, order="C")
        if self.managed:
            self.output.applyRGB(array.reshape(-1, 3))
        return array

    def display_values(self, rgb):
        array = np.array(rgb, np.float32, copy=True, order="C")
        if self.managed:
            self.display.applyRGB(array.reshape(-1, 3))
        return array

    def image(self, path, values, kind):
        result = np.array(values, np.float32, copy=True, order="C")
        if not self.managed or kind != "color":
            return result
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        source = self.settings.resource_spaces.get(digest, "linear" if Path(path).suffix.lower() in (".exr", ".hdr", ".pfm") else "srgb")
        if source not in ("linear", "srgb"):
            raise ValueError("Unsupported color-resource interpretation")
        if source == "srgb":
            result[..., :3] = self.working(np.ascontiguousarray(result[..., :3]))
        return result

    def working_shader(self, source):
        if not self.managed:
            return source
        from . import shaders as S
        start = S.COLOR.index("vec3 rgb2hsv")
        return source.replace(S.COLOR[:start], "vec3 toLin(vec3 c) { return c; }\nvec3 toSrgb(vec3 c) { return c; }\n")
