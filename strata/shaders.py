"""GLSL sources. Everything targets GL 3.3 core."""

HEADER = "#version 330 core\n"

NOISE = """
float hash13(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 31.32);
    return fract((p.x + p.y) * p.z);
}
float vnoise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    vec3 u = f * f * (3.0 - 2.0 * f);
    float a = hash13(i), b = hash13(i + vec3(1,0,0)), c = hash13(i + vec3(0,1,0)), d = hash13(i + vec3(1,1,0));
    float e = hash13(i + vec3(0,0,1)), f1 = hash13(i + vec3(1,0,1)), g = hash13(i + vec3(0,1,1)), h = hash13(i + vec3(1,1,1));
    return mix(mix(mix(a,b,u.x), mix(c,d,u.x), u.y), mix(mix(e,f1,u.x), mix(g,h,u.x), u.y), u.z);
}
float fbm(vec3 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { s += a * vnoise(p); p = p * 2.03 + vec3(17.1, 3.7, 9.2); a *= 0.5; }
    return s / 0.96875;
}
"""

# --------------------------------------------------------------------------- full-screen quad
FSQ_VS = HEADER + """
in vec2 in_pos;
out vec2 v_uv;
void main() { v_uv = in_pos * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.0, 1.0); }
"""

BLIT_FS = HEADER + """
uniform sampler2D u_src;
in vec2 v_uv; out vec4 o;
void main() { o = texture(u_src, v_uv); }
"""

# value + coverage dilation (expands data one texel outwards per pass)
DILATE_FS = HEADER + """
uniform sampler2D u_src;
uniform sampler2D u_cov;
in vec2 v_uv;
layout(location=0) out vec4 o_val;
layout(location=1) out vec4 o_cov;
void main() {
    vec2 px = 1.0 / vec2(textureSize(u_src, 0));
    float c = texture(u_cov, v_uv).r;
    if (c > 0.5) { o_val = texture(u_src, v_uv); o_cov = vec4(1.0); return; }
    vec4 acc = vec4(0.0); float n = 0.0;
    for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
        vec2 q = v_uv + vec2(x, y) * px;
        if (texture(u_cov, q).r > 0.5) { acc += texture(u_src, q); n += 1.0; }
    }
    if (n > 0.0) { o_val = acc / n; o_cov = vec4(1.0); }
    else { o_val = texture(u_src, v_uv); o_cov = vec4(0.0); }
}
"""

# --------------------------------------------------------------------------- mesh in UV space
UV_VS = HEADER + """
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv; in vec4 in_tan; in float in_curv;
out vec3 v_pos; out vec3 v_nrm; out float v_curv; out vec2 v_uv;
void main() {
    v_pos = in_pos; v_nrm = in_nrm; v_curv = in_curv; v_uv = in_uv;
    gl_Position = vec4(in_uv * 2.0 - 1.0, 0.0, 1.0);
}
"""

BAKE_GEOM_FS = HEADER + """
in vec3 v_pos; in vec3 v_nrm; in float v_curv;
layout(location=0) out vec4 o_pos;
layout(location=1) out vec4 o_nrm;
layout(location=2) out vec4 o_curv;
layout(location=3) out vec4 o_cov;
void main() {
    o_cov = vec4(1.0);
    o_pos = vec4(v_pos, 1.0);
    o_nrm = vec4(normalize(v_nrm), 1.0);
    o_curv = vec4(v_curv, v_curv, v_curv, 1.0);
}
"""

DEPTH_VS = HEADER + """
uniform mat4 u_vp;
in vec3 in_pos;
void main() { gl_Position = u_vp * vec4(in_pos, 1.0); }
"""
DEPTH_FS = HEADER + "void main() {}\n"

AO_ACCUM_FS = HEADER + """
uniform sampler2D u_pos;
uniform sampler2D u_nrm;
uniform sampler2D u_depth;
uniform mat4 u_vp;
uniform vec3 u_dir;      // direction towards the light
uniform float u_bias;
uniform float u_dbias;
in vec2 v_uv; out vec4 o;
void main() {
    vec4 P = texture(u_pos, v_uv);
    if (P.a < 0.5) { o = vec4(0.0); return; }
    vec3 n = normalize(texture(u_nrm, v_uv).xyz);
    float w = max(dot(n, u_dir), 0.0);
    if (w <= 0.0) { o = vec4(0.0); return; }
    vec4 c = u_vp * vec4(P.xyz + n * u_bias, 1.0);
    vec3 q = c.xyz / c.w * 0.5 + 0.5;
    float vis = 0.0;
    vec2 ts = 1.0 / vec2(textureSize(u_depth, 0));
    for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++)
        vis += (q.z - u_dbias <= texture(u_depth, q.xy + vec2(x, y) * ts).r) ? 1.0 : 0.0;
    vis /= 9.0;
    o = vec4(vis * w, w, 0.0, 1.0);
}
"""

AO_RESOLVE_FS = HEADER + """
uniform sampler2D u_acc;
in vec2 v_uv; out vec4 o;
void main() {
    vec4 a = texture(u_acc, v_uv);
    float ao = a.g > 0.0 ? a.r / a.g : 1.0;
    o = vec4(ao, ao, ao, 1.0);
}
"""

# --------------------------------------------------------------------------- layer compositing
COMPOSITE_FS = HEADER + NOISE + """
uniform sampler2D u_prevC;   // rgb = base color (sRGB), a unused
uniform sampler2D u_prevR;   // r = roughness, g = metallic, b = height
uniform sampler2D u_pC, u_pR, u_pM, u_pH;   // paint layer (premultiplied value, coverage)
uniform sampler2D u_mask;
uniform sampler2D u_pos, u_nrm, u_ao, u_curv;

uniform int u_type;          // 0 fill, 1 paint
uniform vec3 u_color; uniform float u_rough, u_metal, u_height;
uniform ivec4 u_en;
uniform float u_opacity;
uniform int u_blend;         // 0 normal 1 multiply 2 screen 3 overlay 4 add
uniform int u_hblend;        // 0 normal 1 add
uniform float u_var, u_bump, u_varScale;
uniform int u_hasMask;
uniform int u_gen;           // 0 none 1 edges 2 cavity 3 ao 4 upward 5 gradient 6 noise
uniform float u_level, u_soft, u_noiseAmt, u_noiseScale;
uniform int u_invert;
uniform float u_meshSize;
uniform vec3 u_bmin, u_bmax;
uniform vec3 u_seed;
uniform int u_maskOnly;

in vec2 v_uv;
layout(location=0) out vec4 o_c;
layout(location=1) out vec4 o_r;

vec3 blendColor(vec3 a, vec3 b, int m) {
    if (m == 1) return a * b;
    if (m == 2) return 1.0 - (1.0 - a) * (1.0 - b);
    if (m == 3) return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(0.5, a));
    if (m == 4) return min(a + b, vec3(1.0));
    return b;
}

float maskValue(vec3 P, vec3 N) {
    float m = 1.0;
    if (u_hasMask == 1) m *= texture(u_mask, v_uv).r;
    if (u_gen > 0) {
        float x = 0.0;
        float ao = texture(u_ao, v_uv).r;
        float cv = texture(u_curv, v_uv).r;
        if (u_gen == 1) x = cv;
        else if (u_gen == 2) x = clamp((1.0 - ao) * 1.3 + max(0.5 - cv, 0.0) * 1.6, 0.0, 1.0);
        else if (u_gen == 3) x = 1.0 - ao;
        else if (u_gen == 4) x = N.y * 0.5 + 0.5;
        else if (u_gen == 5) x = (P.y - u_bmin.y) / max(u_bmax.y - u_bmin.y, 1e-5);
        else if (u_gen == 6) x = fbm(P / u_meshSize * u_noiseScale * 4.0 + u_seed * 7.0);
        if (u_gen != 6)
            x += (fbm(P / u_meshSize * u_noiseScale * 6.0 + u_seed * 13.0) - 0.5) * u_noiseAmt;
        float s = max(u_soft, 0.002);
        float g = smoothstep(u_level - s, u_level + s, x);
        if (u_invert == 1) g = 1.0 - g;
        m *= g;
    }
    return m;
}

void main() {
    vec4 pc = texture(u_prevC, v_uv);
    vec4 pr = texture(u_prevR, v_uv);
    vec3 P = texture(u_pos, v_uv).xyz;
    vec3 N = normalize(texture(u_nrm, v_uv).xyz + 1e-6);
    float m = maskValue(P, N);
    if (u_maskOnly == 1) { o_c = vec4(m, m, m, 1.0); o_r = vec4(0.0); return; }

    vec3 col; float ro, me, he;
    vec4 cov;   // per channel coverage
    if (u_type == 0) {
        vec3 q = P / u_meshSize * u_varScale * 5.0 + u_seed * 11.0;
        float n1 = fbm(q), n2 = fbm(q * 1.7 + 4.2), n3 = fbm(q * 3.1 + 9.1);
        col = clamp(u_color * (1.0 + (n1 - 0.5) * u_var * 2.0), 0.0, 1.0);
        ro = clamp(u_rough + (n2 - 0.5) * u_var, 0.0, 1.0);
        me = u_metal;
        he = clamp(u_height + (n3 - 0.5) * u_bump, 0.0, 1.0);
        cov = vec4(1.0);
    } else {
        vec4 c = texture(u_pC, v_uv), r = texture(u_pR, v_uv), mt = texture(u_pM, v_uv), h = texture(u_pH, v_uv);
        cov = clamp(vec4(c.a, r.g, mt.g, h.g), 0.0, 1.0);
        col = cov.x > 1e-4 ? c.rgb / cov.x : vec3(0.0);
        ro  = cov.y > 1e-4 ? r.r / cov.y : 0.0;
        me  = cov.z > 1e-4 ? mt.r / cov.z : 0.0;
        he  = cov.w > 1e-4 ? h.r / cov.w : 0.5;
    }
    vec4 a = cov * u_opacity * m * vec4(u_en);
    vec3 outC = mix(pc.rgb, blendColor(pc.rgb, col, u_blend), a.x);
    float outR = mix(pr.r, ro, a.y);
    float outM = mix(pr.g, me, a.z);
    float outH = u_hblend == 1 ? pr.b + (he - 0.5) * a.w : mix(pr.b, he, a.w);
    o_c = vec4(outC, 1.0);
    o_r = vec4(outR, outM, outH, 1.0);
}
"""

# height -> tangent-space normal (OpenGL convention, +Y up)
NORMAL_FROM_HEIGHT_FS = HEADER + """
uniform sampler2D u_rmh;
uniform float u_strength;
in vec2 v_uv; out vec4 o;
void main() {
    vec2 px = 1.0 / vec2(textureSize(u_rmh, 0));
    float l = texture(u_rmh, v_uv - vec2(px.x, 0)).b, r = texture(u_rmh, v_uv + vec2(px.x, 0)).b;
    float d = texture(u_rmh, v_uv - vec2(0, px.y)).b, u = texture(u_rmh, v_uv + vec2(0, px.y)).b;
    float s = u_strength * float(textureSize(u_rmh, 0).x) / 256.0;
    vec3 n = normalize(vec3((l - r) * s, (d - u) * s, 1.0));
    o = vec4(n * 0.5 + 0.5, 1.0);
}
"""

# --------------------------------------------------------------------------- brush
BRUSH_FS = HEADER + NOISE + """
uniform vec3 u_hit;
uniform float u_radius, u_hardness, u_flow, u_grain, u_grainScale;
uniform vec3 u_campos;
uniform mat4 u_vp;
uniform sampler2D u_pickPos;
uniform float u_tol;
uniform vec3 u_color; uniform float u_rough, u_metal, u_height;
uniform ivec4 u_en;
uniform int u_mode;          // 0 paint, 1 erase, 2 mask
uniform float u_maskValue;
in vec3 v_pos; in vec3 v_nrm;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;

void main() {
    float d = length(v_pos - u_hit) / u_radius;
    if (d >= 1.0) discard;
    float a = 1.0 - smoothstep(u_hardness * 0.999, 1.0, d);
    vec3 V = normalize(u_campos - v_pos);
    a *= smoothstep(0.0, 0.25, dot(normalize(v_nrm), V));
    // occlusion: is this surface point what the camera actually sees?
    vec4 c = u_vp * vec4(v_pos, 1.0);
    vec2 s = c.xy / c.w * 0.5 + 0.5;
    if (s.x < 0.0 || s.y < 0.0 || s.x > 1.0 || s.y > 1.0) discard;
    vec4 seen = texture(u_pickPos, s);
    if (seen.a < 0.5 || length(seen.xyz - v_pos) > u_tol) discard;
    if (u_grain > 0.0) a *= mix(1.0, smoothstep(0.35, 0.65, fbm(v_pos * u_grainScale)), u_grain);
    a *= u_flow;
    if (a <= 0.0) discard;
    if (u_mode == 2) {
        o0 = vec4(u_maskValue, u_maskValue, u_maskValue, a);
        o1 = o2 = o3 = vec4(0.0);
        return;
    }
    vec4 e = vec4(u_en) * a;
    if (u_mode == 1) {   // erase: blend func (ZERO, 1-SRC_ALPHA)
        o0 = vec4(0, 0, 0, e.x); o1 = vec4(0, 0, 0, e.y); o2 = vec4(0, 0, 0, e.z); o3 = vec4(0, 0, 0, e.w);
        return;
    }
    // paint: (SRC_ALPHA, 1-SRC_ALPHA) for rgb, (ONE, 1-SRC_ALPHA) for alpha -> premultiplied storage
    o0 = vec4(u_color, e.x);
    o1 = vec4(u_rough, 1.0, 0.0, e.y);
    o2 = vec4(u_metal, 1.0, 0.0, e.z);
    o3 = vec4(u_height, 1.0, 0.0, e.w);
}
"""

# --------------------------------------------------------------------------- viewport
SCENE_VS = HEADER + """
uniform mat4 u_vp;
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv; in vec4 in_tan; in float in_curv;
out vec3 v_pos; out vec3 v_nrm; out vec2 v_uv; out vec4 v_tan;
void main() {
    v_pos = in_pos; v_nrm = in_nrm; v_uv = in_uv; v_tan = in_tan;
    gl_Position = u_vp * vec4(in_pos, 1.0);
}
"""

PICK_FS = HEADER + """
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv;
layout(location=0) out vec4 o_pos;
layout(location=1) out vec4 o_nrm;
void main() { o_pos = vec4(v_pos, 1.0); o_nrm = vec4(normalize(v_nrm), 1.0); }
"""

ENV = """
uniform float u_envRot;
const float PI = 3.14159265;
vec3 rotY(vec3 d, float a) { float c = cos(a), s = sin(a); return vec3(c*d.x + s*d.z, d.y, -s*d.x + c*d.z); }
// soft studio environment: sky gradient + two soft boxes, blurred by roughness
vec3 envColor(vec3 d, float r) {
    d = rotY(d, u_envRot);
    float t = d.y * 0.5 + 0.5;
    vec3 sky = mix(vec3(0.20, 0.19, 0.18), vec3(0.55, 0.58, 0.62), smoothstep(0.2, 0.9, t));
    sky = mix(sky, vec3(0.08, 0.075, 0.07), smoothstep(0.52, 0.0, t) * 0.8);
    float b = mix(0.002, 0.6, r * r);
    vec3 k1 = normalize(vec3(0.6, 0.55, 0.6)), k2 = normalize(vec3(-0.8, 0.25, -0.4));
    float s1 = smoothstep(0.975 - b, 0.975 + b * 0.3, dot(d, k1));
    float s2 = smoothstep(0.93 - b, 0.93 + b * 0.3, dot(d, k2));
    float w = 1.0 / (1.0 + r * 6.0);
    return sky + vec3(1.0, 0.97, 0.92) * s1 * 6.0 * w + vec3(0.7, 0.8, 1.0) * s2 * 2.0 * w;
}
vec3 envIrradiance(vec3 n) {
    n = rotY(n, u_envRot);
    vec3 up = vec3(0.46, 0.47, 0.5), down = vec3(0.1, 0.095, 0.09);
    vec3 k1 = normalize(vec3(0.6, 0.55, 0.6)), k2 = normalize(vec3(-0.8, 0.25, -0.4));
    return mix(down, up, n.y * 0.5 + 0.5) + vec3(0.5, 0.48, 0.46) * max(dot(n, k1), 0.0)
         + vec3(0.12, 0.14, 0.18) * max(dot(n, k2), 0.0);
}
"""

SCENE_FS = HEADER + ENV + NOISE + """
uniform sampler2D u_texC, u_texR, u_texN, u_ao, u_curv, u_maskPrev;
uniform vec3 u_campos;
uniform int u_mode;   // 0 material 1 basecolor 2 rough 3 metal 4 height 5 normal 6 mask 7 ao 8 curvature 9 uv checker
uniform float u_exposure;
uniform int u_useAO;
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv; in vec4 v_tan;
out vec4 o;

vec3 srgb2lin(vec3 c) { return pow(c, vec3(2.2)); }
vec3 aces(vec3 x) { return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }

void main() {
    vec3 Ng = normalize(v_nrm);
    vec3 T = normalize(v_tan.xyz - Ng * dot(Ng, v_tan.xyz));
    vec3 B = cross(Ng, T) * v_tan.w;
    vec3 tn = texture(u_texN, v_uv).xyz * 2.0 - 1.0;
    vec3 N = normalize(T * tn.x + B * tn.y + Ng * tn.z);
    vec4 c = texture(u_texC, v_uv);
    vec4 rmh = texture(u_texR, v_uv);
    float ao = u_useAO == 1 ? texture(u_ao, v_uv).r : 1.0;
    vec3 V = normalize(u_campos - v_pos);

    if (u_mode == 1) { o = vec4(c.rgb, 1.0); return; }
    if (u_mode == 2) { o = vec4(vec3(rmh.r), 1.0); return; }
    if (u_mode == 3) { o = vec4(vec3(rmh.g), 1.0); return; }
    if (u_mode == 4) { o = vec4(vec3(rmh.b), 1.0); return; }
    if (u_mode == 5) { o = vec4(texture(u_texN, v_uv).rgb, 1.0); return; }
    if (u_mode == 6) { o = vec4(vec3(texture(u_maskPrev, v_uv).r), 1.0); return; }
    if (u_mode == 7) { o = vec4(vec3(texture(u_ao, v_uv).r), 1.0); return; }
    if (u_mode == 8) { o = vec4(vec3(texture(u_curv, v_uv).r), 1.0); return; }
    if (u_mode == 9) {
        vec2 g = floor(v_uv * 16.0);
        float k = mod(g.x + g.y, 2.0);
        vec3 col = mix(vec3(0.25), vec3(0.8), k) * mix(vec3(1.0, 0.6, 0.5), vec3(0.5, 0.7, 1.0), v_uv.x);
        o = vec4(col * (0.5 + 0.5 * max(dot(N, V), 0.0)), 1.0); return;
    }

    vec3 albedo = srgb2lin(c.rgb);
    float rough = clamp(rmh.r, 0.04, 1.0), metal = clamp(rmh.g, 0.0, 1.0);
    vec3 F0 = mix(vec3(0.04), albedo, metal);
    float NoV = max(dot(N, V), 1e-4);

    // key light (GGX)
    vec3 L = normalize(rotY(vec3(0.5, 0.75, 0.45), -u_envRot));
    vec3 H = normalize(L + V);
    float NoL = max(dot(N, L), 0.0), NoH = max(dot(N, H), 0.0), VoH = max(dot(V, H), 0.0);
    float a = rough * rough, a2 = a * a;
    float D = a2 / (PI * pow(NoH * NoH * (a2 - 1.0) + 1.0, 2.0));
    float k = (rough + 1.0) * (rough + 1.0) / 8.0;
    float G = NoV / (NoV * (1.0 - k) + k) * NoL / (NoL * (1.0 - k) + k);
    vec3 F = F0 + (1.0 - F0) * pow(1.0 - VoH, 5.0);
    vec3 spec = D * G * F / max(4.0 * NoV * NoL, 1e-4);
    vec3 kd = (1.0 - F) * (1.0 - metal);
    vec3 direct = (kd * albedo / PI + spec) * NoL * vec3(3.4, 3.25, 3.05);

    // ambient (analytic environment BRDF approximation)
    vec4 c0 = vec4(-1, -0.0275, -0.572, 0.022), c1 = vec4(1, 0.0425, 1.04, -0.04);
    vec4 r = rough * c0 + c1;
    float a004 = min(r.x * r.x, exp2(-9.28 * NoV)) * r.x + r.y;
    vec2 AB = vec2(-1.04, 1.04) * a004 + r.zw;
    vec3 R = reflect(-V, N);
    vec3 ambSpec = envColor(R, rough) * (F0 * AB.x + AB.y);
    vec3 ambDiff = envIrradiance(N) * albedo * (1.0 - metal);
    float specOcc = clamp(pow(NoV + ao, exp2(-16.0 * rough - 1.0)) - 1.0 + ao, 0.0, 1.0);
    vec3 col = direct * mix(1.0, ao, 0.5) + ambDiff * ao + ambSpec * specOcc;
    col = aces(col * u_exposure);
    o = vec4(pow(col, vec3(1.0 / 2.2)), 1.0);
}
"""

BG_FS = HEADER + """
in vec2 v_uv; out vec4 o;
void main() {
    vec3 a = vec3(0.105, 0.11, 0.12), b = vec3(0.19, 0.2, 0.215);
    float v = smoothstep(0.0, 1.0, v_uv.y);
    float vig = 1.0 - 0.25 * length(v_uv - 0.5);
    o = vec4(mix(a, b, v) * vig, 1.0);
}
"""

LINE_VS = HEADER + """
uniform mat4 u_vp;
in vec3 in_pos;
void main() { gl_Position = u_vp * vec4(in_pos, 1.0); }
"""
LINE_FS = HEADER + """
uniform vec4 u_color;
out vec4 o;
void main() { o = u_color; }
"""
