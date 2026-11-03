"""GPU changed-region history: reduce bounds to one texel, then retain only the crop."""
import numpy as np
import moderngl
from . import shaders as S

BOUNDS = S.HEADER + """
uniform sampler2D u_before, u_after, u_bounds;
uniform int u_initial;
uniform ivec2 u_size;
out vec4 o;
void main() {
    ivec2 origin = ivec2(gl_FragCoord.xy) * 8;
    vec2 lo = vec2(1e20), hi = vec2(-1.0);
    for (int y = 0; y < 8; ++y) for (int x = 0; x < 8; ++x) {
        ivec2 p = origin + ivec2(x, y);
        if (any(greaterThanEqual(p, u_size))) continue;
        if (u_initial == 1) {
            if (any(notEqual(texelFetch(u_before, p, 0), texelFetch(u_after, p, 0)))) {
                lo = min(lo, vec2(p)); hi = max(hi, vec2(p + 1));
            }
        } else {
            vec4 b = texelFetch(u_bounds, p, 0);
            if (b.z > b.x) { lo = min(lo, b.xy); hi = max(hi, b.zw); }
        }
    }
    o = vec4(lo, hi);
}
"""

CROP = S.HEADER + """
uniform sampler2D u_source;
uniform ivec2 u_offset;
out vec4 o;
void main() { o = texelFetch(u_source, u_offset + ivec2(gl_FragCoord.xy), 0); }
"""

PATCH = S.HEADER + """
uniform sampler2D u_source;
uniform ivec2 u_offset;
out vec4 o;
void main() { o = texelFetch(u_source, ivec2(gl_FragCoord.xy) - u_offset, 0); }
"""


def changed_bounds(gpu, before, after):
    p = gpu.fs_program("delta_bounds", BOUNDS)
    size, source, level = before.size, None, 0
    gpu.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
    while True:
        output_size = tuple((v + 7) // 8 for v in size)
        output = gpu.scratch("delta_bounds_" + str(level), output_size, 4, "f4")
        fbo = gpu.ctx.framebuffer([output])
        try:
            fbo.use()
            gpu.ctx.viewport = (0, 0, *output_size)
            gpu.bind(p, {"u_before": (0, before), "u_after": (1, after), "u_bounds": (2, source or gpu.black)})
            p["u_initial"], p["u_size"] = int(level == 0), size
            gpu.draw_quad(p)
        finally:
            fbo.release()
        if output_size == (1, 1):
            values = gpu.read(output)[0, 0]
            if values[2] <= values[0]:
                return None
            x, y, x1, y1 = values.astype(int)
            return (int(x), int(y), int(x1 - x), int(y1 - y))
        size, source, level = output_size, output, level + 1


def crop(gpu, texture, rect):
    x, y, w, h = rect
    result = gpu.texture((w, h), texture.components, dtype=texture.dtype, filt=False, purpose="history region")
    fbo = None
    try:
        p = gpu.fs_program("delta_crop", CROP)
        gpu.bind(p, {"u_source": (0, texture)})
        p["u_offset"] = (x, y)
        fbo = gpu.ctx.framebuffer([result])
        fbo.use()
        gpu.ctx.viewport = (0, 0, w, h)
        gpu.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        gpu.draw_quad(p)
        return result
    except Exception:
        result.release()
        raise
    finally:
        if fbo is not None:
            fbo.release()


def patch(gpu, texture, source, rect):
    p = gpu.fs_program("delta_patch", PATCH)
    gpu.bind(p, {"u_source": (0, source)})
    p["u_offset"] = rect[:2]
    fbo = gpu.ctx.framebuffer([texture])
    try:
        fbo.use()
        gpu.ctx.viewport = rect
        gpu.ctx.disable(moderngl.BLEND | moderngl.DEPTH_TEST | moderngl.CULL_FACE)
        gpu.draw_quad(p)
    finally:
        fbo.release()


def texture_bytes(texture):
    return texture.size[0] * texture.size[1] * texture.components * {"f1": 1, "f2": 2, "f4": 4}[texture.dtype]
