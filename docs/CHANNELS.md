# Channel descriptors

`strata/channels.py` is the CPU-only source of existing channel semantics. Its
frozen `ChannelDescriptor` records are exposed in `CHANNEL_DESCRIPTORS`, with an
immutable `BY_KEY` lookup. Historical `CHANNELS`, `CH_KEYS`, `CH_COMPONENTS` and
`N_CH` remain available through `strata.layers` with their existing types/order.

| Index/key | Property | Layer / brush / empty composite default | Paint components | Accumulator components | Resource kind |
|---|---|---|---|---|---|
| 0 / C | color | (.5,.5,.5) / (.75,.2,.12) / (.5,.5,.5) | 4 | 0: RGB | color |
| 1 / R | rough | .5 / .45 / .6 | 2 | 1: R | data |
| 2 / M | metal | 0 / 0 / 0 | 2 | 1: G | data |
| 3 / H | height | .5 / .65 / .5 | 2 | 1: B | data |
| 4 / N | normal | (.5,.5,1) for all roles | 4 | 3: RGB | data |
| 5 / E | emissive | (0,0,0) / (1,.6,.2) / (0,0,0) | 4 | 2: RGB | color |
| 6 / O | opac | 1 / 1 / 1 | 2 | 1: A | data |

Paint storage uses half-float (`f2`) textures throughout. RGB channels carry
coverage in the fourth component; scalar channels carry value plus coverage.
Composited color, emissive and encoded tangent-normal slots retain normalized
8-bit (`f1`) storage. The shared rough/metal/height/opacity slot retains `f2`.
`ACC_CLEAR` and `ACC_DTYPES` are derived from descriptors and preserve the existing
four-slot GPU layout exactly, including RGB-slot alpha values of one.

`channel_default(key, role)` returns a fresh mutable list for vector values and a
scalar otherwise. Roles are `layer`, `brush` and `composite`.
`enabled_defaults(role)` returns fresh flags: layers initially enable C/R/M/H,
brushes C/R/M. Old short channel labels remain intact; `value_label` provides
full property-control labels, including Roughness and Metallic.

Descriptors drive model defaults, channel allocation/adapters, resource kinds,
uniform values, material picking and direct export metadata. `export_sources`
lists existing direct source names; final normal exports use the combined
normal result, while material picking reads the raw encoded normal channel.
Derived diffuse/specular/smoothness/glossiness sources remain exporter logic.

The fill and brush material panels expose all seven constant values from these
descriptors. Channel toggles retain their existing enabled defaults. The opacity
channel (`opac`) is distinct from layer opacity (`opacity`): the former is a
material value, while the latter controls how much the entire layer contributes.
Fill edits use document transactions; brush values remain session settings.
Texture-set channel previews include emissive and opacity as well as the original
five views. T05 adds bitmap slots, projection editing and per-channel blending;
see [fill materials](FILL_MATERIALS.md).

This consolidation preserves existing shaders, channel ordering, project schemas
and appearance. It adds no custom channels or automatic color-space conversion.
The existing color/data resource distinction does not provide OCIO processing,
and emissive compositing remains 8-bit even though painted emissive storage is
half-float. Those limitations need separate implementation packages.

T18 extends this fixed core with project-local scalar channels and shader bindings
without changing the seven-channel layout. See SHADER_WORKFLOWS.md.
