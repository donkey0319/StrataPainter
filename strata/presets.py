"""Material presets and smart materials (layer stacks driven by baked-map generators)."""
from .layers import Layer, MaskGen

# name: (base colour sRGB, roughness, metallic)
MATERIALS = {
    "Steel": ((0.56, 0.57, 0.58), 0.32, 1.0),
    "Iron": ((0.53, 0.51, 0.49), 0.5, 1.0),
    "Aluminium": ((0.91, 0.92, 0.92), 0.28, 1.0),
    "Gold": ((1.0, 0.77, 0.34), 0.22, 1.0),
    "Copper": ((0.95, 0.64, 0.54), 0.3, 1.0),
    "Brass": ((0.91, 0.78, 0.42), 0.3, 1.0),
    "Red Plastic": ((0.7, 0.08, 0.06), 0.42, 0.0),
    "Blue Paint": ((0.12, 0.25, 0.5), 0.5, 0.0),
    "Olive Paint": ((0.28, 0.31, 0.17), 0.6, 0.0),
    "Orange Paint": ((0.85, 0.36, 0.05), 0.48, 0.0),
    "Rubber": ((0.05, 0.05, 0.05), 0.85, 0.0),
    "Ceramic": ((0.9, 0.9, 0.88), 0.12, 0.0),
    "Rust": ((0.42, 0.2, 0.09), 0.85, 0.0),
    "Dirt": ((0.22, 0.17, 0.12), 0.95, 0.0),
    "Dust": ((0.65, 0.62, 0.57), 1.0, 0.0),
}


def fill(name, mat, **kw) -> Layer:
    col, r, m = MATERIALS[mat]
    lay = Layer(name=name, kind="fill", color=list(col), rough=r, metal=m)
    for k, v in kw.items():
        setattr(lay, k, v)
    return lay


def _worn_paint(paint="Blue Paint", metal="Steel"):
    return [
        fill(f"{metal} base", metal, variation=0.15, var_scale=2.0),
        fill(paint, paint, variation=0.08, height=0.55, enabled=[True, True, True, True],
             gen=MaskGen(kind=1, level=0.86, softness=0.05, noise_amount=0.35, noise_scale=2.0, invert=True)),
        fill("Grime", "Dirt", opacity=0.85, enabled=[True, True, True, False],
             gen=MaskGen(kind=2, level=0.45, softness=0.2, noise_amount=0.5, noise_scale=1.5)),
    ]


SMART_MATERIALS = {
    "Worn Blue Paint on Steel": lambda: _worn_paint("Blue Paint", "Steel"),
    "Worn Orange Paint on Iron": lambda: _worn_paint("Orange Paint", "Iron"),
    "Rusty Iron": lambda: [
        fill("Iron base", "Iron", variation=0.2, var_scale=3.0),
        fill("Rust", "Rust", variation=0.35, bump=0.35, var_scale=3.0, hblend=1,
             gen=MaskGen(kind=6, level=0.55, softness=0.06, noise_scale=1.2)),
        fill("Rust in cavities", "Rust", variation=0.3, bump=0.2, var_scale=4.0, hblend=1,
             gen=MaskGen(kind=2, level=0.35, softness=0.12, noise_amount=0.6, noise_scale=2.0)),
    ],
    "Aged Gold": lambda: [
        fill("Gold", "Gold", variation=0.1, var_scale=2.0),
        fill("Polished edges", "Gold", rough=0.08, enabled=[False, True, False, False],
             gen=MaskGen(kind=1, level=0.8, softness=0.08, noise_amount=0.2)),
        fill("Tarnish", "Dirt", opacity=0.9, enabled=[True, True, True, False],
             gen=MaskGen(kind=2, level=0.4, softness=0.18, noise_amount=0.5, noise_scale=2.0)),
    ],
    "Dusty Rubber": lambda: [
        fill("Rubber", "Rubber", variation=0.15, var_scale=4.0, bump=0.06),
        fill("Dust", "Dust", opacity=0.9, enabled=[True, True, True, False],
             gen=MaskGen(kind=4, level=0.82, softness=0.1, noise_amount=0.5, noise_scale=2.5)),
    ],
    "Glazed Ceramic, Chipped": lambda: [
        fill("Clay", "Dirt", color=[0.55, 0.38, 0.27], rough=0.9, variation=0.2),
        fill("Glaze", "Ceramic", height=0.56,
             gen=MaskGen(kind=1, level=0.9, softness=0.02, noise_amount=0.5, noise_scale=3.0, invert=True)),
    ],
}
