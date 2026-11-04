"""GLSL sources. Everything targets GL 3.3 core.

Layout of the shared data (all UV space, one texel per surface point):

  accumulated stack   A0 = base colour (sRGB) rgb          A1 = roughness, metallic, height, opacity
                      A2 = emissive (sRGB) rgb             A3 = tangent-space normal, encoded 0-1
  layer content       T0 = colour rgb, coverage            T1 = roughness, metallic, height, opacity
                      T2 = emissive rgb, coverage          T3 = normal rgb (encoded), coverage
                      T4 = coverage of roughness, metallic, height, opacity
  paint layer data    C/N/E: rgb premultiplied by coverage, a = coverage
                      R/M/H/O: r = value * coverage, g = coverage
"""

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
float cellular(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    float d = 1e9;
    for (int z = -1; z <= 1; z++) for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
        vec3 g = vec3(x, y, z);
        vec3 o = vec3(hash13(i + g), hash13(i + g + 17.31), hash13(i + g + 41.17));
        d = min(d, length(g + o - f));
    }
    return d;
}
"""

COLOR = """
vec3 toLin(vec3 c) { c = max(c, 0.0); return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
vec3 toSrgb(vec3 c) { c = max(c, 0.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
vec3 rgb2hsv(vec3 c) {
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
    float d = q.x - min(q.w, q.y);
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + 1e-10)), d / (q.x + 1e-10), q.x);
}
vec3 hsv2rgb(vec3 c) {
    vec3 p = abs(fract(c.xxx + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
    return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
"""

# Painter blend modes (index = strata.layers.BLEND_MODES). a = bottom, b = top.
BLEND = """
vec3 bColorBurn(vec3 a, vec3 b) { return 1.0 - (1.0 - a) / max(b, 1e-4); }
vec3 bColorDodge(vec3 a, vec3 b) { return a / max(1.0 - b, 1e-4); }
vec3 blendMode(vec3 a, vec3 b, int m) {
    if (m == 1) return a * b;
    if (m == 2) return 1.0 - (1.0 - a) * (1.0 - b);
    if (m == 3) return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(0.5, a));
    if (m == 4) return a + b;
    if (m == 8) return a - b;
    if (m == 9) return a / max(b, 1e-4);
    if (m == 10) return b / max(a, 1e-4);
    if (m == 11) return b - a;
    if (m == 12) return min(a, b);
    if (m == 13) return max(a, b);
    if (m == 14) return abs(a - b);
    if (m == 15) return a + b - 2.0 * a * b;
    if (m == 16) return a + b - 0.5;
    if (m == 17) return a + b - 1.0;
    if (m == 18) return bColorBurn(a, b);
    if (m == 19) return bColorDodge(a, b);
    if (m == 20) return (1.0 - 2.0 * b) * a * a + 2.0 * b * a;
    if (m == 21) return mix(2.0 * a * b, 1.0 - 2.0 * (1.0 - a) * (1.0 - b), step(0.5, b));
    if (m == 22) return mix(bColorBurn(a, 2.0 * b), bColorDodge(a, 2.0 * (b - 0.5)), step(0.5, b));
    if (m == 23) return a + 2.0 * b - 1.0;
    if (m == 24) return mix(min(a, 2.0 * b), max(a, 2.0 * (b - 0.5)), step(0.5, b));
    if (m >= 25 && m <= 28) {
        vec3 A = rgb2hsv(a), B = rgb2hsv(b);
        if (m == 25) return B.y < 1e-3 ? a : hsv2rgb(vec3(B.x, A.y, A.z));
        if (m == 26) return hsv2rgb(vec3(A.x, B.y, A.z));
        if (m == 27) return hsv2rgb(vec3(B.x, B.y, A.z));
        return hsv2rgb(vec3(A.x, A.y, B.z));
    }
    return b;   // Normal, Replace, Passthrough
}
float blendScalar(float a, float b, int m) {
    if (m >= 25 && m <= 28) return m == 28 ? b : a;
    return blendMode(vec3(a), vec3(b), m).x;
}
vec3 nDecode(vec3 c) { return normalize(c * 2.0 - 1.0); }
vec3 nEncode(vec3 n) { return n * 0.5 + 0.5; }
vec3 nWhiteout(vec3 a, vec3 b) { return normalize(vec3(a.xy + b.xy, a.z * b.z)); }
vec3 nRNM(vec3 base, vec3 det) {
    vec3 t = base + vec3(0.0, 0.0, 1.0);
    vec3 u = det * vec3(-1.0, -1.0, 1.0);
    return normalize(t * dot(t, u) / t.z - u);
}
// blend encoded normals, returns encoded
vec3 blendNormal(vec3 a, vec3 b, int m, float t) {
    vec3 A = nDecode(a), B = nDecode(b), R;
    if (m == 29) R = nWhiteout(A, B);
    else if (m == 30) R = nRNM(A, B);
    else if (m == 31) R = nRNM(B, A);
    else R = B;
    return nEncode(normalize(mix(A, R, t)));
}
"""

# mesh-wide uniforms used by generators and projections
MESHU = """
uniform float u_meshSize;
uniform vec3 u_bmin, u_bmax, u_center;
"""

# Procedural mask generators (index = strata.layers.GENERATORS)
GENERATOR = """
uniform int u_gKind;
uniform float u_gLevel, u_gSoft, u_gNoiseAmt, u_gNoiseScale;
uniform int u_gInvert, u_gAxis;
uniform float u_gAz, u_gEl;
uniform vec3 u_gSeed;
float genValue(vec3 P, vec3 N, float ao, float cv, float th) {
    int k = u_gKind;
    if (k == 0) return 1.0;
    float x = 0.0;
    vec3 q = P / u_meshSize * u_gNoiseScale;
    int ax = clamp(u_gAxis, 0, 2);
    if (k == 1) x = cv;
    else if (k == 2) x = clamp((1.0 - ao) * 1.3 + max(0.5 - cv, 0.0) * 1.6, 0.0, 1.0);
    else if (k == 3) x = 1.0 - ao;
    else if (k == 4) x = N.y * 0.5 + 0.5;
    else if (k == 5) x = (P.y - u_bmin.y) / max(u_bmax.y - u_bmin.y, 1e-5);
    else if (k == 6) x = fbm(q * 4.0 + u_gSeed * 7.0);
    else if (k == 7) x = th;
    else if (k == 8) x = (P[ax] - u_bmin[ax]) / max(u_bmax[ax] - u_bmin[ax], 1e-5);
    else if (k == 9) {
        vec3 L = vec3(cos(u_gEl) * sin(u_gAz), sin(u_gEl), cos(u_gEl) * cos(u_gAz));
        x = dot(N, L) * 0.5 + 0.5;
    }
    else if (k == 10) x = 1.0 - cv;
    else if (k == 11) x = N[ax] * 0.5 + 0.5;
    else if (k == 12) x = 1.0 - abs(fbm(q * 5.0 + u_gSeed * 5.0) * 2.0 - 1.0);
    else if (k == 13) x = 1.0 - cellular(q * 8.0 + u_gSeed * 3.0);
    if (k != 6 && k != 12 && k != 13)
        x += (fbm(q * 6.0 + u_gSeed * 13.0) - 0.5) * u_gNoiseAmt;
    float s = max(u_gSoft, 0.002);
    float g = smoothstep(u_gLevel - s, u_gLevel + s, x);
    if (u_gInvert == 1) g = 1.0 - g;
    return g;
}
"""

# Image projection for fill layers / fill effects
PROJ = """
uniform int u_projMode;
uniform vec2 u_projScale, u_projOffset;
uniform float u_projRot, u_projSharp;
uniform int u_projAxis,u_hasWarp,u_projClip;uniform mat3 u_projWarp;
vec2 projXf(vec2 t) {
    float c = cos(u_projRot), s = sin(u_projRot);
    t -= 0.5;
    t = vec2(c * t.x - s * t.y, s * t.x + c * t.y);
    t=t*u_projScale+0.5+u_projOffset;
    if(u_hasWarp==1){vec3 q=u_projWarp*vec3(t,1);t=q.xy/q.z;}
    return t;
}
vec2 axisPlane(vec3 q, int ax) { return ax == 0 ? q.zy : (ax == 1 ? q.xz : q.xy); }
vec4 projTex(sampler2D s,vec2 uv){if(u_projClip==1&&(any(lessThan(uv,vec2(0)))||any(greaterThan(uv,vec2(1)))))return vec4(0);return texture(s,uv);}
vec4 projTexGrad(sampler2D s,vec2 uv){if(u_projClip==1&&(any(lessThan(uv,vec2(0)))||any(greaterThan(uv,vec2(1)))))return vec4(0);return textureGrad(s,uv,vec2(0),vec2(0));}
vec4 projSample(sampler2D s, vec2 uv, vec3 P, vec3 N) {
    if (u_projMode == 0) return projTex(s, projXf(uv));
    vec3 q = (P - u_center) / u_meshSize;
    if (u_projMode == 1) {
        vec3 w = pow(abs(N) + 1e-5, vec3(u_projSharp));
        w /= w.x + w.y + w.z;
        return projTex(s, projXf(q.zy + 0.5)) * w.x + projTex(s, projXf(q.xz + 0.5)) * w.y
             + projTex(s, projXf(q.xy + 0.5)) * w.z;
    }
    if (u_projMode == 2) return projTex(s, projXf(axisPlane(q, u_projAxis) + 0.5));
    if (u_projMode == 3) {
        vec3 d = normalize(q + 1e-6);
        vec2 t = vec2(atan(d.z, d.x) / 6.2831853 + 0.5, asin(clamp(d.y, -1.0, 1.0)) / 3.14159265 + 0.5);
        return projTexGrad(s,projXf(t));
    }
    // cylindrical around the chosen axis
    vec3 r = u_projAxis == 0 ? q.yzx : (u_projAxis == 1 ? q.zxy : q.xyz);
    vec2 t = vec2(atan(r.y, r.x) / 6.2831853 + 0.5, r.z + 0.5);
    return projTexGrad(s,projXf(t));
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

# copies up to four textures at once (accumulator snapshots)
COPY4_FS = HEADER + """
uniform sampler2D u_s0, u_s1, u_s2, u_s3;
in vec2 v_uv;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;
void main() {
    o0 = texture(u_s0, v_uv); o1 = texture(u_s1, v_uv); o2 = texture(u_s2, v_uv); o3 = texture(u_s3, v_uv);
}
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

# separable gaussian blur, any texture
BLUR_FS = HEADER + """
uniform sampler2D u_src;
uniform vec2 u_dir;        // texel step
uniform float u_radius;    // texels
in vec2 v_uv; out vec4 o;
void main() {
    int n = int(clamp(ceil(u_radius), 1.0, 48.0));
    float sigma = max(u_radius * 0.5, 0.5);
    vec4 acc = texture(u_src, v_uv); float wsum = 1.0;
    for (int i = 1; i <= n; i++) {
        float w = exp(-0.5 * float(i * i) / (sigma * sigma));
        acc += (texture(u_src, v_uv + u_dir * float(i)) + texture(u_src, v_uv - u_dir * float(i))) * w;
        wsum += 2.0 * w;
    }
    o = acc / wsum;
}
"""

# --------------------------------------------------------------------------- mesh in UV space
UV_BRUSH_VS = HEADER + """
in vec2 in_pos;
out vec3 v_pos; out vec3 v_nrm; out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    v_pos = vec3(v_uv, 0.0); v_nrm = vec3(0.0, 0.0, 1.0);
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

UV_VS = HEADER + """
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv; in vec4 in_tan; in float in_curv; in vec2 in_part; in vec4 in_vcol;
out vec3 v_pos; out vec3 v_nrm; out float v_curv; out vec2 v_uv; out vec2 v_part; out vec4 v_vcol; out vec4 v_tan;
void main() {
    v_pos = in_pos; v_nrm = in_nrm; v_curv = in_curv; v_uv = in_uv; v_part = in_part; v_vcol = in_vcol; v_tan = in_tan;
    gl_Position = vec4(in_uv * 2.0 - 1.0, 0.0, 1.0);
}
"""

BAKE_GEOM_FS = HEADER + COLOR + """
uniform int u_idSource;      // 0 vertex colour, 1 mesh part, 2 material
uniform int u_idGen;         // 0 random, 1 hue shift, 2 grayscale
in vec3 v_pos; in vec3 v_nrm; in float v_curv; in vec2 v_part; in vec4 v_vcol; in vec4 v_tan;
layout(location=0) out vec4 o_pos;
layout(location=1) out vec4 o_nrm;
layout(location=2) out vec4 o_curv;
layout(location=3) out vec4 o_cov;
layout(location=4) out vec4 o_id;
layout(location=5) out vec4 o_part;
layout(location=6) out vec4 o_tan;
vec3 idColor(float i) {
    if (u_idGen == 2) { float g = fract(i * 0.618034 + 0.13); return vec3(g); }
    if (u_idGen == 1) return hsv2rgb(vec3(fract(i * 0.618034), 0.75, 0.95));
    float h = fract(sin(i * 12.9898 + 78.233) * 43758.5453);
    float s = 0.55 + 0.45 * fract(sin(i * 4.1414) * 1234.5);
    return hsv2rgb(vec3(h, s, 0.9));
}
void main() {
    o_cov = vec4(1.0);
    o_pos = vec4(v_pos, 1.0);
    o_nrm = vec4(normalize(v_nrm), 1.0);
    o_curv = vec4(v_curv, v_curv, v_curv, 1.0);
    vec3 idc = u_idSource == 0 ? v_vcol.rgb : idColor(u_idSource == 1 ? v_part.x : v_part.y);
    o_id = vec4(idc, 1.0);
    o_part = vec4(v_part.x, v_part.y, 0.0, 1.0);
    o_tan = vec4(normalize(v_tan.xyz + 1e-9), v_tan.w < 0.0 ? -1.0 : 1.0);
}
"""

# --------------------------------------------------------------------------- high-poly baking
RAYCAST_LIB = """
uniform sampler2D u_tpos, u_tnrm, u_tcol, u_cells, u_items;
uniform int u_W;
uniform ivec3 u_G;
uniform vec3 u_lo, u_hi, u_cell;
uniform int u_maxSteps;
uniform int u_ignoreBack;
ivec2 at(int i) { return ivec2(i % u_W, i / u_W); }
vec3 tpos(int i) { return texelFetch(u_tpos, at(i), 0).xyz; }
bool triHit(int t, vec3 O, vec3 D, float tmax, inout float best, out vec2 bc) {
    bc = vec2(0.0);
    vec3 v0 = tpos(3 * t), v1 = tpos(3 * t + 1), v2 = tpos(3 * t + 2);
    vec3 e1 = v1 - v0, e2 = v2 - v0;
    if (u_ignoreBack == 1 && dot(cross(e1, e2), D) > 0.0) return false;
    vec3 p = cross(D, e2);
    float det = dot(e1, p);
    if (abs(det) < 1e-14) return false;
    float inv = 1.0 / det;
    vec3 s = O - v0;
    float u = dot(s, p) * inv;
    if (u < -1e-6 || u > 1.000001) return false;
    vec3 q = cross(s, e1);
    float v = dot(D, q) * inv;
    if (v < -1e-6 || u + v > 1.000001) return false;
    float tt = dot(e2, q) * inv;
    if (tt < 0.0 || tt > tmax || tt >= best) return false;
    best = tt; bc = vec2(u, v);
    return true;
}
// nearest triangle along O + t*D, t in [0, tmax]; returns -1 on a miss
int castRay(vec3 O, vec3 D, float tmax, out float best, out vec2 bcOut) {
    best = 1e30; bcOut = vec2(0.0);
    int hit = -1;
    vec3 Dn = D + vec3(equal(D, vec3(0.0))) * 1e-12;
    vec3 invD = 1.0 / Dn;
    vec3 t0 = (u_lo - O) * invD, t1 = (u_hi - O) * invD;
    vec3 tmn = min(t0, t1), tmx = max(t0, t1);
    float tin = max(max(tmn.x, tmn.y), max(tmn.z, 0.0));
    float tout = min(min(tmx.x, tmx.y), min(tmx.z, tmax));
    if (tin > tout) return -1;
    vec3 p = O + D * tin;
    ivec3 c = clamp(ivec3(floor((p - u_lo) / u_cell)), ivec3(0), u_G - 1);
    ivec3 stp = ivec3(sign(D));
    vec3 nb = u_lo + (vec3(c) + max(vec3(stp), vec3(0.0))) * u_cell;
    vec3 tM = (nb - O) * invD;
    vec3 tD = abs(u_cell * invD);
    if (stp.x == 0) tM.x = 1e30;
    if (stp.y == 0) tM.y = 1e30;
    if (stp.z == 0) tM.z = 1e30;
    for (int s = 0; s < u_maxSteps; s++) {
        int ci = c.x + u_G.x * (c.y + u_G.y * c.z);
        vec2 fc = texelFetch(u_cells, at(ci), 0).rg;
        int f = int(fc.x + 0.5), n = int(fc.y + 0.5);
        for (int k = 0; k < n; k++) {
            int t = int(texelFetch(u_items, at(f + k), 0).r + 0.5);
            vec2 b;
            if (triHit(t, O, D, tmax, best, b)) { hit = t; bcOut = b; }
        }
        float tn = min(tM.x, min(tM.y, tM.z));
        if (hit >= 0 && best <= tn) break;
        if (tn > tout) break;
        if (tM.x <= tM.y && tM.x <= tM.z) { c.x += stp.x; tM.x += tD.x; }
        else if (tM.y <= tM.z) { c.y += stp.y; tM.y += tD.y; }
        else { c.z += stp.z; tM.z += tD.z; }
        if (any(lessThan(c, ivec3(0))) || any(greaterThanEqual(c, u_G))) break;
    }
    return hit;
}
"""

# cast from a cage above each low-poly texel down into the high poly
BAKE_RAY_SETUP = """
uniform sampler2D u_cage;
uniform int u_hasCage;
uniform sampler2D u_rayCorrection, u_distanceCorrection;
uniform int u_hasRayCorrection, u_hasDistanceCorrection;
uniform float u_front, u_rear;
in vec2 v_uv;
void projectionRay(vec4 P, vec3 n, out vec3 O, out vec3 direction, out float front, out float rear) {
    O = P.xyz + n * u_front;
    direction = n;
    front = u_front;
    if (u_hasCage == 1) {
        vec3 cage = texture(u_cage, v_uv).xyz;
        front = length(cage - P.xyz);
        direction = normalize(cage - P.xyz);
        O = cage;
    }
    rear = u_rear;
    if (u_hasRayCorrection == 1) {
        vec4 field = texture(u_rayCorrection, v_uv);
        vec3 corrected = field.rgb / max(field.a, 1e-6) * 2.0 - 1.0;
        if (length(corrected) > 1e-6) {
            vec3 blended = mix(direction, normalize(corrected), clamp(field.a, 0.0, 1.0));
            if (length(blended) > 1e-6) direction = normalize(blended);
        }
    }
    if (u_hasDistanceCorrection == 1) {
        vec2 field = texture(u_distanceCorrection, v_uv).rg;
        float multiplier = 1.0 + clamp(field.r / max(field.g, 1e-6) * 2.0 - 1.0, -1.0, 1.0) * clamp(field.g, 0.0, 1.0);
        front *= max(multiplier, 0.001);
        rear *= max(multiplier, 0.001);
    }
    if (u_hasRayCorrection == 1 || u_hasDistanceCorrection == 1) O = P.xyz + direction * front;
}
"""

CAGE_BLOCK_FS = HEADER + RAYCAST_LIB + BAKE_RAY_SETUP + """
uniform sampler2D u_pos, u_nrm; uniform float u_bias; out vec4 o;
void main(){vec4 P=texture(u_pos,v_uv); o=vec4(0); if(P.a<0.5)return;
vec3 n=normalize(texture(u_nrm,v_uv).xyz+1e-9), O, direction; float front, rear;
projectionRay(P,n,O,direction,front,rear); float best; vec2 bc;
int t=castRay(P.xyz+direction*u_bias,direction,max(front-2.0*u_bias,0.0),best,bc);
o=vec4(t>=0?1.0:0.0,0,0,1);}
"""

HP_RAY_FS = HEADER + RAYCAST_LIB + BAKE_RAY_SETUP + """
uniform sampler2D u_pos, u_nrm, u_part, u_cageBlocked; uniform int u_partID;
layout(location=0) out vec4 o_pos;
layout(location=1) out vec4 o_nrm;
layout(location=2) out vec4 o_info;
layout(location=3) out vec4 o_col;
void main() {
    if (u_partID >= 0 && int(texture(u_part, v_uv).r + 0.5) != u_partID) discard;
    vec4 P = texture(u_pos, v_uv);
    vec3 n = normalize(texture(u_nrm, v_uv).xyz + 1e-9);
    o_pos = P; o_nrm = vec4(n, 1.0); o_info = vec4(u_front, 0.0, 0.0, 1.0); o_col = vec4(0.0);
    if (P.a < 0.5) return;
    if (u_hasCage == 1 && texture(u_cageBlocked, v_uv).r > 0.5) {o_info.z=-2.0; return;}
    vec3 O, direction; float front, rear;
    projectionRay(P,n,O,direction,front,rear);
    float best; vec2 bc;
    int t = castRay(O, -direction, front + rear, best, bc);
    if (t < 0) return;
    float w = 1.0 - bc.x - bc.y;
    vec3 hn = texelFetch(u_tnrm, at(3 * t), 0).xyz * w + texelFetch(u_tnrm, at(3 * t + 1), 0).xyz * bc.x
            + texelFetch(u_tnrm, at(3 * t + 2), 0).xyz * bc.y;
    vec4 hc = texelFetch(u_tcol, at(3 * t), 0) * w + texelFetch(u_tcol, at(3 * t + 1), 0) * bc.x
            + texelFetch(u_tcol, at(3 * t + 2), 0) * bc.y;
    o_pos = vec4(O - direction * best, 1.0);
    o_nrm = vec4(normalize(hn + 1e-9), 1.0);
    o_info = vec4(u_hasCage == 1 || u_hasRayCorrection == 1 || u_hasDistanceCorrection == 1 ? u_front - dot(o_pos.xyz - P.xyz, n) : best, 1.0, float(t), 1.0);
    o_col = vec4(hc.rgb, 1.0);
}
"""

# high-poly normal -> tangent-space normal map (OpenGL), hit distance -> height map
HP_CONVERT_FS = HEADER + """
uniform sampler2D u_lnrm, u_tan, u_hnrm, u_info;
uniform float u_front, u_rear;
in vec2 v_uv;
layout(location=0) out vec4 o_tn;
layout(location=1) out vec4 o_h;
void main() {
    vec3 N = normalize(texture(u_lnrm, v_uv).xyz + 1e-9);
    vec4 Tw = texture(u_tan, v_uv);
    vec3 T = Tw.xyz - N * dot(N, Tw.xyz);
    T = length(T) > 1e-6 ? normalize(T) : normalize(cross(N, abs(N.y) < 0.9 ? vec3(0, 1, 0) : vec3(1, 0, 0)));
    vec3 B = cross(N, T) * (Tw.w < 0.0 ? -1.0 : 1.0);
    vec4 info = texture(u_info, v_uv);
    bool hit = info.y > 0.5;
    vec3 h = hit ? normalize(texture(u_hnrm, v_uv).xyz) : N;
    vec3 tn = normalize(vec3(dot(h, T), dot(h, B), dot(h, N)));
    o_tn = vec4(tn * 0.5 + 0.5, 1.0);
    float ht = hit ? 0.5 + (u_front - info.x) / max(u_front + u_rear, 1e-9) : 0.5;
    o_h = vec4(vec3(clamp(ht, 0.0, 1.0)), 1.0);
}
"""

# curvature detail from the baked normal map, added to the mesh curvature
CURV_FROM_NORMAL_FS = HEADER + """
uniform sampler2D u_nmap, u_curv;
uniform float u_strength;
in vec2 v_uv; out vec4 o;
void main() {
    vec2 px = 1.0 / vec2(textureSize(u_nmap, 0));
    float dx = texture(u_nmap, v_uv + vec2(px.x, 0)).x - texture(u_nmap, v_uv - vec2(px.x, 0)).x;
    float dy = texture(u_nmap, v_uv + vec2(0, px.y)).y - texture(u_nmap, v_uv - vec2(0, px.y)).y;
    float c = clamp(texture(u_curv, v_uv).r + (dx + dy) * u_strength, 0.0, 1.0);
    o = vec4(c, c, c, 1.0);
}
"""

DEPTH_VS = HEADER + """
uniform mat4 u_vp;
in vec3 in_pos;
void main() { gl_Position = u_vp * vec4(in_pos, 1.0); }
"""
DEPTH_FS = HEADER + "void main() {}\n"

# ambient occlusion + thickness from one orthographic depth map per direction
AO_ACCUM_FS = HEADER + """
uniform sampler2D u_pos;
uniform sampler2D u_nrm;
uniform sampler2D u_depth;
uniform mat4 u_vp;
uniform vec3 u_dir;        // direction towards the depth camera
uniform float u_bias;
uniform float u_dbias;
uniform float u_depthRange;     // far - near (orthographic)
uniform float u_aoMax;          // max occluder distance, 0 = unlimited
uniform float u_spreadCos;      // cos(spread angle)
uniform int u_ground;
uniform float u_groundY;
uniform float u_thickMax;
in vec2 v_uv;
layout(location=0) out vec4 o_ao;
layout(location=1) out vec4 o_th;
float depthAt(vec2 q) { return texture(u_depth, q).r; }
void main() {
    vec4 P = texture(u_pos, v_uv);
    if (P.a < 0.5) { o_ao = vec4(0.0); o_th = vec4(0.0); return; }
    vec3 n = normalize(texture(u_nrm, v_uv).xyz);
    float nd = dot(n, u_dir);
    o_ao = vec4(0.0); o_th = vec4(0.0);
    if (nd > 0.0 && nd >= u_spreadCos) {          // ambient occlusion (hemisphere around n)
        vec4 c = u_vp * vec4(P.xyz + n * u_bias, 1.0);
        vec3 q = c.xyz / c.w * 0.5 + 0.5;
        float vis = 0.0;
        vec2 ts = 1.0 / vec2(textureSize(u_depth, 0));
        for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
            float d = depthAt(q.xy + vec2(x, y) * ts);
            bool occ = q.z - u_dbias > d;
            if (occ && u_aoMax > 0.0 && (q.z - d) * u_depthRange > u_aoMax) occ = false;
            vis += occ ? 0.0 : 1.0;
        }
        vis /= 9.0;
        if (u_ground == 1 && u_dir.y < -1e-3) {
            float t = (P.y - u_groundY) / -u_dir.y;
            if (t > 0.0 && (u_aoMax <= 0.0 || t < u_aoMax)) vis = 0.0;
        }
        o_ao = vec4(vis * nd, nd, 0.0, 1.0);
    }
    if (nd < 0.0) {                               // thickness: distance to where a ray along u_dir exits
        float w = -nd;
        vec4 c = u_vp * vec4(P.xyz - n * u_bias, 1.0);
        vec3 q = c.xyz / c.w * 0.5 + 0.5;
        float d = depthAt(q.xy);
        float dist = max(q.z - d, 0.0) * u_depthRange;
        o_th = vec4(clamp(dist / u_thickMax, 0.0, 1.0) * w, w, 0.0, 1.0);
    }
}
"""

AO_RESOLVE_FS = HEADER + """
uniform sampler2D u_acc;
uniform float u_empty;      // value where nothing accumulated
in vec2 v_uv; out vec4 o;
void main() {
    vec4 a = texture(u_acc, v_uv);
    float v = a.g > 0.0 ? a.r / a.g : u_empty;
    o = vec4(v, v, v, 1.0);
}
"""

# --------------------------------------------------------------------------- layer compositing
# 1) evaluate a layer's content into T0-T4
CONTENT_FS = HEADER + NOISE + MESHU + PROJ + """
uniform sampler2D u_s0, u_s1, u_s2, u_s3, u_s4, u_s5, u_s6;   // paint textures or fill maps (C R M H N E O)
uniform sampler2D u_prev0, u_prev1, u_prev2, u_prev3;
uniform sampler2D u_pos, u_nrm;
uniform sampler2D u_authored;uniform int u_ribbon;
uniform int u_type;            // 0 fill, 1 paint
uniform int u_hasMap[7];
uniform int u_pass[7];         // passthrough: take the channel from the stack below
uniform vec3 u_color, u_normal, u_emissive;
uniform float u_rough, u_metal, u_height, u_opac;
uniform float u_var, u_bump, u_varScale;
uniform vec3 u_seed;
in vec2 v_uv;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;
layout(location=4) out vec4 o4;
float un(vec4 t) { return t.g > 1e-4 ? t.r / t.g : 0.0; }
void main() {
    vec2 materialUV=u_ribbon==1?texture(u_authored,v_uv).rg:v_uv;
    vec3 P = texture(u_pos, v_uv).xyz;
    vec3 N = normalize(texture(u_nrm, v_uv).xyz + 1e-6);
    vec3 col, nm, em; float ro, me, he, op;
    float cC, cR, cM, cH, cN, cE, cO;
    if (u_type == 0) {
        vec3 q = P / u_meshSize * u_varScale * 5.0 + u_seed * 11.0;
        float n1 = 0.5, n2 = 0.5, n3 = 0.5;
        if (u_var > 0.0) { n1 = fbm(q); n2 = fbm(q * 1.7 + 4.2); }
        if (u_bump > 0.0) n3 = fbm(q * 3.1 + 9.1);
        col = u_hasMap[0] == 1 ? projSample(u_s0, materialUV, P, N).rgb : u_color;
        ro = u_hasMap[1] == 1 ? projSample(u_s1, materialUV, P, N).r : u_rough;
        me = u_hasMap[2] == 1 ? projSample(u_s2, materialUV, P, N).r : u_metal;
        he = u_hasMap[3] == 1 ? projSample(u_s3, materialUV, P, N).r : u_height;
        nm = u_hasMap[4] == 1 ? projSample(u_s4, materialUV, P, N).rgb : u_normal;
        em = u_hasMap[5] == 1 ? projSample(u_s5, materialUV, P, N).rgb : u_emissive;
        op = u_hasMap[6] == 1 ? projSample(u_s6, materialUV, P, N).r : u_opac;
        col = clamp(col * (1.0 + (n1 - 0.5) * u_var * 2.0), 0.0, 1.0);
        ro = clamp(ro + (n2 - 0.5) * u_var, 0.0, 1.0);
        he = clamp(he + (n3 - 0.5) * u_bump, 0.0, 1.0);
        cC = cR = cM = cH = cN = cE = cO = 1.0;
    } else {
        vec4 c = texture(u_s0, v_uv), n = texture(u_s4, v_uv), e = texture(u_s5, v_uv);
        vec4 r = texture(u_s1, v_uv), m = texture(u_s2, v_uv), h = texture(u_s3, v_uv), o = texture(u_s6, v_uv);
        cC = clamp(c.a, 0.0, 1.0); cN = clamp(n.a, 0.0, 1.0); cE = clamp(e.a, 0.0, 1.0);
        cR = clamp(r.g, 0.0, 1.0); cM = clamp(m.g, 0.0, 1.0); cH = clamp(h.g, 0.0, 1.0); cO = clamp(o.g, 0.0, 1.0);
        col = cC > 1e-4 ? c.rgb / c.a : vec3(0.0);
        nm = cN > 1e-4 ? n.rgb / n.a : vec3(0.5, 0.5, 1.0);
        em = cE > 1e-4 ? e.rgb / e.a : vec3(0.0);
        ro = un(r); me = un(m); op = cO > 1e-4 ? un(o) : 1.0;
        he = cH > 1e-4 ? un(h) : 0.5;
    }
    if (u_pass[0] + u_pass[1] + u_pass[2] + u_pass[3] + u_pass[4] + u_pass[5] + u_pass[6] > 0) {
        vec4 a0 = texture(u_prev0, v_uv), a1 = texture(u_prev1, v_uv);
        vec4 a2 = texture(u_prev2, v_uv), a3 = texture(u_prev3, v_uv);
        if (u_pass[0] == 1) { col = a0.rgb; cC = 1.0; }
        if (u_pass[1] == 1) { ro = a1.r; cR = 1.0; }
        if (u_pass[2] == 1) { me = a1.g; cM = 1.0; }
        if (u_pass[3] == 1) { he = a1.b; cH = 1.0; }
        if (u_pass[4] == 1) { nm = a3.rgb; cN = 1.0; }
        if (u_pass[5] == 1) { em = a2.rgb; cE = 1.0; }
        if (u_pass[6] == 1) { op = a1.a; cO = 1.0; }
    }
    o0 = vec4(col, cC); o1 = vec4(ro, me, he, op); o2 = vec4(em, cE); o3 = vec4(nm, cN);
    o4 = vec4(cR, cM, cH, cO);
}
"""

# 2) content effects operate on T0-T4 (ping-pong)
CONTENT_EFFECT_FS = HEADER + COLOR + BLEND + """
uniform sampler2D u_t0, u_t1, u_t2, u_t3, u_t4;
uniform sampler2D u_b0, u_b1, u_b2, u_b3, u_b4;      // blurred copy (kind 4)
uniform int u_kind;          // 1 hsl, 2 levels, 3 invert, 4 blur mix, 5 brightness/contrast
uniform int u_channel;       // CHANNELS index, -1 = all
uniform float u_opacity;
uniform vec3 u_hsl;          // hue shift (turns), saturation, lightness (-1..1)
uniform int u_target;        // hsl: 0 colour, 1 emissive
uniform int u_effectBlend;
uniform vec3 u_lvIn;         // in_lo, in_hi, gamma
uniform vec2 u_lvOut;
uniform vec2 u_bc;           // brightness, contrast
in vec2 v_uv;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;
layout(location=4) out vec4 o4;
vec3 lv(vec3 x) {
    x = clamp((x - u_lvIn.x) / max(u_lvIn.y - u_lvIn.x, 1e-5), 0.0, 1.0);
    x = pow(x, vec3(1.0 / max(u_lvIn.z, 1e-3)));
    return mix(vec3(u_lvOut.x), vec3(u_lvOut.y), x);
}
vec3 bc(vec3 x) { return clamp((x - 0.5) * (1.0 + u_bc.y) + 0.5 + u_bc.x, 0.0, 1.0); }
vec3 op3(vec3 x) {
    if (u_kind == 2) return lv(x);
    if (u_kind == 3) return 1.0 - x;
    if (u_kind == 5) return bc(x);
    return x;
}
float op1(float x) { return op3(vec3(x)).x; }
bool on(int c) { return u_channel < 0 || u_channel == c; }
void main() {
    vec4 t0 = texture(u_t0, v_uv), t1 = texture(u_t1, v_uv), t2 = texture(u_t2, v_uv);
    vec4 t3 = texture(u_t3, v_uv), t4 = texture(u_t4, v_uv);
    vec4 r0 = t0, r1 = t1, r2 = t2, r3 = t3, r4 = t4;
    if (u_kind == 1) {
        vec3 c = u_target == 0 ? t0.rgb : t2.rgb;
        vec3 h = rgb2hsv(c);
        h.x = fract(h.x + u_hsl.x);
        h.y = clamp(h.y * (1.0 + u_hsl.y), 0.0, 1.0);
        vec3 rgb = hsv2rgb(h);
        rgb = u_hsl.z >= 0.0 ? mix(rgb, vec3(1.0), u_hsl.z) : rgb * (1.0 + u_hsl.z);
        if (u_target == 0) r0.rgb = rgb; else r2.rgb = rgb;
    } else if (u_kind == 6) {
        vec3 c=texture(u_b0,v_uv).rgb;
        if(on(0))r0.rgb=c;
        if(on(1))r1.r=c.r;
        if(on(2))r1.g=c.r;
        if(on(3))r1.b=c.r;
        if(on(4))r3.rgb=c;
        if(on(5))r2.rgb=c;
        if(on(6))r1.a=c.r;
    } else if (u_kind == 4) {
        vec4 b0 = texture(u_b0, v_uv), b1 = texture(u_b1, v_uv), b2 = texture(u_b2, v_uv);
        vec4 b3 = texture(u_b3, v_uv), b4 = texture(u_b4, v_uv);
        if (on(0)) r0 = vec4(b0.rgb, t0.a);
        if (on(1)) r1.r = b1.r;
        if (on(2)) r1.g = b1.g;
        if (on(3)) r1.b = b1.b;
        if (on(4)) r3 = vec4(b3.rgb, t3.a);
        if (on(5)) r2 = vec4(b2.rgb, t2.a);
        if (on(6)) r1.a = b1.a;
        if (u_channel < 0) { r0.a = b0.a; r2.a = b2.a; r3.a = b3.a; r4 = b4; }
    } else {
        if (on(0)) r0.rgb = op3(t0.rgb);
        if (on(1)) r1.r = op1(t1.r);
        if (on(2)) r1.g = op1(t1.g);
        if (on(3)) r1.b = op1(t1.b);
        if (on(4) && u_kind == 3) r3.rgb = vec3(1.0 - t3.r, 1.0 - t3.g, t3.b);
        if (on(5)) r2.rgb = op3(t2.rgb);
        if (on(6)) r1.a = op1(t1.a);
    }
    if (u_effectBlend == 7) { r0=t0; r1=t1; r2=t2; r3=t3; }
    else if (u_effectBlend != 0) {
        bool allCh = u_kind != 1 && u_channel < 0;
        if (u_kind == 1 ? u_target == 0 : (allCh || u_channel == 0)) r0.rgb = blendMode(t0.rgb, r0.rgb, u_effectBlend);
        if (u_kind != 1) {
            if (allCh || u_channel == 1) r1.r = blendScalar(t1.r,r1.r,u_effectBlend);
            if (allCh || u_channel == 2) r1.g = blendScalar(t1.g,r1.g,u_effectBlend);
            if (allCh || u_channel == 3) r1.b = blendScalar(t1.b,r1.b,u_effectBlend);
            if (allCh || u_channel == 6) r1.a = blendScalar(t1.a,r1.a,u_effectBlend);
            if (allCh || u_channel == 4) r3.rgb = blendNormal(t3.rgb, r3.rgb, u_effectBlend, 1.0);
        }
        if (u_kind == 1 ? u_target == 1 : (allCh || u_channel == 5)) r2.rgb = blendMode(t2.rgb, r2.rgb, u_effectBlend);
    }
    o0 = mix(t0, r0, u_opacity); o1 = mix(t1, r1, u_opacity); o2 = mix(t2, r2, u_opacity);
    o3 = mix(t3, r3, u_opacity); o4 = mix(t4, r4, u_opacity);
}
"""

# 3) masks: base (painted mask x legacy generator), then one pass per mask effect
MASK_BASE_FS = HEADER + NOISE + MESHU + GENERATOR + """
uniform sampler2D u_maskTex;
uniform int u_hasMask;
uniform sampler2D u_pos, u_nrm, u_ao, u_curv, u_thick;
in vec2 v_uv; out vec4 o;
void main() {
    float m = u_hasMask == 1 ? texture(u_maskTex, v_uv).r : 1.0;
    if (u_gKind > 0) {
        vec3 P = texture(u_pos, v_uv).xyz;
        vec3 N = normalize(texture(u_nrm, v_uv).xyz + 1e-6);
        m *= genValue(P, N, texture(u_ao, v_uv).r, texture(u_curv, v_uv).r, texture(u_thick, v_uv).r);
    }
    o = vec4(m, m, m, 1.0);
}
"""

MASK_EFFECT_FS = HEADER + NOISE + COLOR + BLEND + MESHU + GENERATOR + PROJ + """
uniform sampler2D u_prev;
uniform sampler2D u_pos, u_nrm, u_ao, u_curv, u_thick, u_id, u_part, u_hbake;
uniform sampler2D u_map;          // fill image / anchor / blurred mask
uniform sampler2D u_partLUT;
uniform int u_kind;   // 1 fill 2 generator 3 levels 4 invert 5 color select 6 anchor 7 mesh map 8 threshold 9 texture 10 part filter
uniform int u_blend;
uniform float u_opacity;
uniform float u_value;
uniform int u_hasMap;
uniform int u_comp;               // anchor: -1 luminance, else component
uniform int u_meshMap;
uniform vec3 u_lvIn;
uniform vec2 u_lvOut;
uniform vec3 u_colors[8];
uniform int u_nColors;
uniform float u_tol, u_hard;
uniform vec2 u_th;                // threshold level, softness
in vec2 v_uv; out vec4 o;
float lv(float x) {
    x = clamp((x - u_lvIn.x) / max(u_lvIn.y - u_lvIn.x, 1e-5), 0.0, 1.0);
    x = pow(x, 1.0 / max(u_lvIn.z, 1e-3));
    return mix(u_lvOut.x, u_lvOut.y, x);
}
void main() {
    float prev = texture(u_prev, v_uv).r;
    vec3 P = texture(u_pos, v_uv).xyz;
    vec3 N = normalize(texture(u_nrm, v_uv).xyz + 1e-6);
    float v = 0.0;
    bool isOp = false;
    if (u_kind == 1) v = u_hasMap == 1 ? projSample(u_map, v_uv, P, N).r : u_value;
    else if (u_kind == 2) v = genValue(P, N, texture(u_ao, v_uv).r, texture(u_curv, v_uv).r, texture(u_thick, v_uv).r);
    else if (u_kind == 3) { v = lv(prev); isOp = true; }
    else if (u_kind == 4) { v = 1.0 - prev; isOp = true; }
    else if (u_kind == 5) {
        vec3 c = texture(u_id, v_uv).rgb;
        for (int i = 0; i < 8; i++) {
            if (i >= u_nColors) break;
            float d = distance(c, u_colors[i]);
            float t = max(u_tol, 1e-3);
            v = max(v, 1.0 - smoothstep(t * u_hard, t, d));
        }
    }
    else if (u_kind == 6) {
        vec4 a = texture(u_map, v_uv);
        v = u_comp < 0 ? luma(a.rgb) : a[u_comp];
    }
    else if (u_kind == 7) {
        int k = u_meshMap;
        if (k == 0) v = texture(u_ao, v_uv).r;
        else if (k == 1) v = texture(u_curv, v_uv).r;
        else if (k == 2) v = texture(u_thick, v_uv).r;
        else if (k <= 5) v = (P[k - 3] - u_bmin[k - 3]) / max(u_bmax[k - 3] - u_bmin[k - 3], 1e-5);
        else if (k <= 8) v = N[k - 6] * 0.5 + 0.5;
        else if (k == 9) v = luma(texture(u_id, v_uv).rgb);
        else v = texture(u_hbake, v_uv).r;
        v = lv(v);
    }
    else if (u_kind == 8) { v = smoothstep(u_th.x - u_th.y, u_th.x + u_th.y + 1e-5, prev); isOp = true; }
    else if (u_kind == 9) { v = texture(u_map, v_uv).r; isOp = true; }
    else if (u_kind == 11) {v=prev*texture(u_map,v_uv).b;isOp=true;}
    else if (u_kind == 10) {
        int part = int(texture(u_part, v_uv).r + 0.5);
        v = prev * texelFetch(u_partLUT, ivec2(clamp(part, 0, 1023), 0), 0).r;
        isOp = true;
    }
    float r = isOp && u_blend == 0 ? v : clamp(blendScalar(prev, v, u_blend), 0.0, 1.0);
    if (u_blend == 7) r = prev;
    float m = mix(prev, r, u_opacity);
    o = vec4(m, m, m, 1.0);
}
"""

# 4) blend layer content into the stack
BLEND_FS = HEADER + COLOR + BLEND + """
uniform sampler2D u_prev0, u_prev1, u_prev2, u_prev3;
uniform sampler2D u_t0, u_t1, u_t2, u_t3, u_t4;
uniform sampler2D u_mask;
uniform int u_mode[7];
uniform float u_chOp[7];       // layer opacity x channel opacity x enabled
in vec2 v_uv;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;
float alphaFor(int ch, float cov, float m) {
    if (u_mode[ch] == 7) return 0.0;
    if (u_mode[ch] == 5) return u_chOp[ch] * m;
    return cov * u_chOp[ch] * m;
}
vec3 colorBlend(vec3 a, vec3 b, int mode, float t, bool clampIt) {
    vec3 A = toLin(a), B = toLin(b);
    vec3 r = blendMode(A, B, mode);
    if (clampIt) r = clamp(r, 0.0, 1.0); else r = max(r, 0.0);
    return toSrgb(mix(A, r, t));
}
float scalarBlend(float a, float b, int mode, float t) {
    return mix(a, clamp(blendScalar(a, b, mode), 0.0, 1.0), t);
}
float heightBlend(float a, float b, int mode, float t) {
    if (mode == 4 || mode == 16) return a + (b - 0.5) * t;        // add: 0.5 is flat
    if (mode == 8) return a - (b - 0.5) * t;
    if (mode == 0 || mode == 5 || mode == 6) return mix(a, b, t);
    return mix(a, clamp(blendScalar(a, b, mode), 0.0, 1.0), t);
}
void main() {
    vec4 p0 = texture(u_prev0, v_uv), p1 = texture(u_prev1, v_uv), p2 = texture(u_prev2, v_uv), p3 = texture(u_prev3, v_uv);
    vec4 t0 = texture(u_t0, v_uv), t1 = texture(u_t1, v_uv), t2 = texture(u_t2, v_uv), t3 = texture(u_t3, v_uv), t4 = texture(u_t4, v_uv);
    float m = texture(u_mask, v_uv).r;
    float aC = alphaFor(0, t0.a, m), aR = alphaFor(1, t4.r, m), aM = alphaFor(2, t4.g, m), aH = alphaFor(3, t4.b, m);
    float aN = alphaFor(4, t3.a, m), aE = alphaFor(5, t2.a, m), aO = alphaFor(6, t4.a, m);
    vec3 c = aC > 0.0 ? colorBlend(p0.rgb, t0.rgb, u_mode[0], aC, true) : p0.rgb;
    float r = aR > 0.0 ? scalarBlend(p1.r, t1.r, u_mode[1], aR) : p1.r;
    float mt = aM > 0.0 ? scalarBlend(p1.g, t1.g, u_mode[2], aM) : p1.g;
    float h = aH > 0.0 ? heightBlend(p1.b, t1.b, u_mode[3], aH) : p1.b;
    float op = aO > 0.0 ? scalarBlend(p1.a, t1.a, u_mode[6], aO) : p1.a;
    vec3 e = aE > 0.0 ? colorBlend(p2.rgb, t2.rgb, u_mode[5], aE, false) : p2.rgb;
    vec3 n = aN > 0.0 ? blendNormal(p3.rgb, t3.rgb, u_mode[4], aN) : p3.rgb;
    o0 = vec4(c, 1.0); o1 = vec4(r, mt, h, op); o2 = vec4(e, 1.0); o3 = vec4(n, 1.0);
}
"""

# 5) merge a group's result back over what was below it
GROUP_FS = HEADER + COLOR + BLEND + """
uniform sampler2D u_save0, u_save1, u_save2, u_save3;
uniform sampler2D u_cur0, u_cur1, u_cur2, u_cur3;
uniform sampler2D u_mask;
uniform int u_mode[7];
uniform float u_chOp[7];
in vec2 v_uv;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;
float a(int ch, float m) { return u_mode[ch] == 7 ? 0.0 : u_chOp[ch] * m; }
float sb(float x, float y, int ch, float m) {
    int mode = u_mode[ch];
    float t = a(ch, m);
    if (mode == 0 || mode == 5 || mode == 6) return mix(x, y, t);
    return mix(x, blendScalar(x, y, mode), t);
}
void main() {
    vec4 s0 = texture(u_save0, v_uv), s1 = texture(u_save1, v_uv), s2 = texture(u_save2, v_uv), s3 = texture(u_save3, v_uv);
    vec4 c0 = texture(u_cur0, v_uv), c1 = texture(u_cur1, v_uv), c2 = texture(u_cur2, v_uv), c3 = texture(u_cur3, v_uv);
    float m = texture(u_mask, v_uv).r;
    vec3 col = toSrgb(mix(toLin(s0.rgb), clamp(blendMode(toLin(s0.rgb), toLin(c0.rgb), u_mode[0]), 0.0, 1.0), a(0, m)));
    vec3 em = toSrgb(mix(toLin(s2.rgb), max(blendMode(toLin(s2.rgb), toLin(c2.rgb), u_mode[5]), 0.0), a(5, m)));
    vec3 n = blendNormal(s3.rgb, c3.rgb, u_mode[4], a(4, m));
    o0 = vec4(col, 1.0);
    o1 = vec4(sb(s1.r, c1.r, 1, m), sb(s1.g, c1.g, 2, m), sb(s1.b, c1.b, 3, m), sb(s1.a, c1.a, 6, m));
    o2 = vec4(em, 1.0);
    o3 = vec4(n, 1.0);
}
"""

# final normal: normal channel combined with the normal derived from height (OpenGL convention, +Y up)
NORMAL_FROM_HEIGHT_FS = HEADER + COLOR + BLEND + """
uniform sampler2D u_rmh;
uniform sampler2D u_edges;
uniform int u_hasEdges;
uniform sampler2D u_nch;
uniform sampler2D u_baked;
uniform int u_hasNch, u_hasBaked;
uniform float u_strength;
in vec2 v_uv; out vec4 o;
float tileHeight(vec2 uv) {
    if (u_hasEdges == 1) {
        int edge = uv.x < 0.0 ? 0 : (uv.x >= 1.0 ? 1 : (uv.y < 0.0 ? 2 : (uv.y >= 1.0 ? 3 : -1)));
        if (edge >= 0) {
            vec2 sampleUV = vec2(clamp(edge < 2 ? uv.y : uv.x, 0.0, 1.0), (float(edge) + 0.5) / 4.0);
            vec2 value = texture(u_edges, sampleUV).rg;
            if (value.g > 0.5) return value.r;
        }
    }
    return texture(u_rmh, uv).b;
}
void main() {
    vec2 px = 1.0 / vec2(textureSize(u_rmh, 0));
    float l = tileHeight(v_uv - vec2(px.x, 0)), r = tileHeight(v_uv + vec2(px.x, 0));
    float d = tileHeight(v_uv - vec2(0, px.y)), u = tileHeight(v_uv + vec2(0, px.y));
    float s = u_strength * float(textureSize(u_rmh, 0).x) / 256.0;
    vec3 n = normalize(vec3((l - r) * s, (d - u) * s, 1.0));
    if (u_hasNch == 1) n = nWhiteout(nDecode(texture(u_nch, v_uv).rgb), n);
    if (u_hasBaked == 1) n = nWhiteout(nDecode(texture(u_baked, v_uv).rgb), n);
    o = vec4(n * 0.5 + 0.5, 1.0);
}
"""

MASK_PREVIEW_FS = HEADER + """
uniform sampler2D u_src;
in vec2 v_uv; out vec4 o;
void main() { float m = texture(u_src, v_uv).r; o = vec4(m, m, m, 1.0); }
"""

# --------------------------------------------------------------------------- brush
# Shared dab shape: where does a dab land in UV space, and how strongly.
BRUSH_LIB = NOISE + """
uniform vec3 u_hit;
uniform float u_radius;
uniform vec3 u_fT, u_fB, u_fN;      // tangent frame at the hit (T along the stamp's x)
uniform int u_uvView;
uniform vec2 u_uvScale, u_uvCenter;
uniform mat2 u_uvAxes;
uniform sampler2D u_uvCoverage;
uniform int u_align;                // 0 camera, 1 tangent wrap, 2 tangent planar, 3 uv
uniform vec2 u_hitUV;
uniform float u_radiusUV;
uniform vec2 u_rot;                 // cos, sin of the stamp angle
uniform mat4 u_vp;
uniform vec2 u_viewport;
uniform vec2 u_hitPx;
uniform float u_radiusPx;
uniform mat4 u_symInv;              // maps a symmetric copy back to the original stroke
uniform int u_occl;
uniform sampler2D u_pickPos;
uniform float u_tol;
uniform vec3 u_campos;
uniform float u_backCos;
uniform int u_full;                 // polygon fill: every rasterised texel, alpha 1
uniform sampler2D u_alpha;
uniform int u_hasAlpha, u_alphaInv;
uniform float u_hardness;
uniform sampler2D u_stencil;
uniform int u_hasStencil;
uniform mat3 u_stencilXf;
uniform int u_stencilTile;
uniform sampler2D u_quick;
uniform int u_hasQuick;
uniform float u_grain, u_grainScale, u_flow;
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv;
vec2 g_screen, g_stamp;
vec3 g_P;
bool tileUV(inout vec2 t, int mode) {
    bool tx = mode == 1 || mode == 3, ty = mode == 2 || mode == 3;
    if (tx) t.x = fract(t.x);
    if (ty) t.y = fract(t.y);
    return t.x >= 0.0 && t.y >= 0.0 && t.x <= 1.0 && t.y <= 1.0;
}
float dabAlpha() {
    vec3 P = (u_symInv * vec4(v_pos, 1.0)).xyz;
    vec3 N = normalize(mat3(u_symInv) * v_nrm);
    g_P = P;
    vec4 c = u_vp * vec4(P, 1.0);
    g_screen = c.w > 0.0 ? c.xy / c.w * 0.5 + 0.5 : vec2(-1.0);
    if (u_uvView == 1) {
        P = vec3(v_uv, 0.0); N = vec3(0.0, 0.0, 1.0); g_P = P;
        c = vec4(0.0, 0.0, 0.0, 1.0);
        g_screen = (transpose(u_uvAxes) * (v_uv - u_uvCenter)) / u_uvScale + 0.5;
        if (texture(u_uvCoverage, v_uv).r < 0.5) return -1.0;
    }
    g_stamp = v_uv;
    if (u_full == 1) return 1.0;
    vec3 D = P - u_hit;
    float d3 = length(D);
    if (d3 > u_radius * 3.0 || c.w <= 0.0) return -1.0;
    vec2 L;
    float a = 1.0;
    if (u_align == 0) L = (g_screen * u_viewport - u_hitPx) / u_radiusPx;
    else if (u_align == 3) L = (v_uv - u_hitUV) / u_radiusUV;
    else {
        vec2 t = vec2(dot(D, u_fT), dot(D, u_fB));
        if (u_align == 1) { float l = length(t); L = l > 1e-9 ? t / l * (d3 / u_radius) : vec2(0.0); }
        else { L = t / u_radius; a *= 1.0 - smoothstep(0.35, 1.0, abs(dot(D, u_fN)) / u_radius); }
    }
    L = vec2(u_rot.x * L.x + u_rot.y * L.y, -u_rot.y * L.x + u_rot.x * L.y);
    g_stamp = clamp(L * 0.5 + 0.5, 0.0, 1.0);
    if (u_hasAlpha == 1) {
        if (abs(L.x) >= 1.0 || abs(L.y) >= 1.0) return -1.0;
        float t = texture(u_alpha, L * 0.5 + 0.5).r;
        a *= u_alphaInv == 1 ? 1.0 - t : t;
    } else {
        float d = length(L);
        if (d >= 1.0) return -1.0;
        a *= 1.0 - smoothstep(u_hardness * 0.999, 1.0, d);
    }
    vec3 V = normalize(u_campos - P);
    if (u_uvView == 0) a *= smoothstep(u_backCos - 0.05, u_backCos + 0.15, dot(N, V));
    if (u_occl == 1) {
        vec2 s = g_screen;
        if (s.x < 0.0 || s.y < 0.0 || s.x > 1.0 || s.y > 1.0) return -1.0;
        vec4 seen = texture(u_pickPos, s);
        if (seen.a < 0.5 || length(seen.xyz - P) > u_tol) return -1.0;
    }
    if (u_hasStencil == 1) {
        vec2 st = (u_stencilXf * vec3(g_screen * u_viewport, 1.0)).xy;
        a *= tileUV(st, u_stencilTile) ? texture(u_stencil, st).r : 0.0;
    }
    if (u_hasQuick == 1) a *= texture(u_quick, v_uv).r;
    if (u_grain > 0.0) a *= mix(1.0, smoothstep(0.35, 0.65, fbm(P * u_grainScale)), u_grain);
    return a * u_flow;
}
"""

# paint / erase into the 7-channel stroke buffer (or straight into a layer for polygon fill)
BRUSH_PAINT_FS = HEADER + BRUSH_LIB + """
uniform int u_en[7];
uniform vec3 u_color, u_normal, u_emissive;
uniform float u_rough, u_metal, u_height, u_opac;
uniform int u_projActive; // 0: constants, 1: screen projection, 2: brush maps
uniform int u_hasP[7];
uniform sampler2D u_p0, u_p1, u_p2, u_p3, u_p4, u_p5, u_p6;
uniform mat3 u_projXf;
uniform int u_projTile;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;
layout(location=4) out vec4 o4;
layout(location=5) out vec4 o5;
layout(location=6) out vec4 o6;
void main() {
    float a = dabAlpha();
    if (a <= 0.0) discard;
    vec3 col = u_color, nm = u_normal, em = u_emissive;
    float ro = u_rough, me = u_metal, he = u_height, op = u_opac;
    float colA = 1.0;
    if (u_projActive != 0) {
        vec2 t = g_stamp;
        if (u_projActive == 1) {
            t = (u_projXf * vec3(g_screen * u_viewport, 1.0)).xy;
            if (!tileUV(t, u_projTile)) discard;
        }
        if (u_hasP[0] == 1) { vec4 s = texture(u_p0, t); col = s.rgb; colA = s.a; }
        if (u_hasP[1] == 1) ro = texture(u_p1, t).r;
        if (u_hasP[2] == 1) me = texture(u_p2, t).r;
        if (u_hasP[3] == 1) he = texture(u_p3, t).r;
        if (u_hasP[4] == 1) nm = texture(u_p4, t).rgb;
        if (u_hasP[5] == 1) em = texture(u_p5, t).rgb;
        if (u_hasP[6] == 1) op = texture(u_p6, t).r;
    }
    o0 = vec4(col, float(u_en[0]) * a * colA);
    o1 = vec4(ro, 1.0, 0.0, float(u_en[1]) * a);
    o2 = vec4(me, 1.0, 0.0, float(u_en[2]) * a);
    o3 = vec4(he, 1.0, 0.0, float(u_en[3]) * a);
    o4 = vec4(nm, float(u_en[4]) * a);
    o5 = vec4(em, float(u_en[5]) * a);
    o6 = vec4(op, 1.0, 0.0, float(u_en[6]) * a);
}
"""

# single-channel targets: masks and the quick mask
BRUSH_MASK_FS = HEADER + BRUSH_LIB + """
uniform int u_direct;         // 0: write coverage into a stroke buffer; 1: write u_value (polygon fill)
uniform float u_value;
out vec4 o;
void main() {
    float a = dabAlpha();
    if (a <= 0.0) discard;
    o = u_direct == 1 ? vec4(u_value, u_value, u_value, 1.0) : vec4(a);
}
"""

# smudge / clone: pull texels from somewhere else on screen
SAMPLE_TOOL_FS = HEADER + BRUSH_LIB + """
uniform sampler2D u_cur;      // copy of the target texture before this dab
uniform sampler2D u_src;      // where to pull from (u_cur for smudge, stroke snapshot for clone)
uniform sampler2D u_pickUV;
uniform vec2 u_offsetPx;
out vec4 o;
void main() {
    float a = dabAlpha();
    if (a <= 0.0) discard;
    vec2 s2 = g_screen + u_offsetPx / u_viewport;
    if (u_uvView == 0 && (s2.x < 0.0 || s2.y < 0.0 || s2.x > 1.0 || s2.y > 1.0)) discard;
    vec2 suv;
    if (u_uvView == 1) {
        suv = u_uvAxes * ((s2 - 0.5) * u_uvScale) + u_uvCenter;
        if (any(lessThan(suv, vec2(0.0))) || any(greaterThan(suv, vec2(1.0))) || texture(u_uvCoverage, suv).r < 0.5) discard;
    } else {
        if (texture(u_pickPos, s2).a < 0.5) discard;
        suv = texture(u_pickUV, s2).xy;
    }
    o = mix(texture(u_cur, v_uv), texture(u_src, suv), clamp(a, 0.0, 1.0));
}
"""

# merge a stroke buffer into the layer: layer = snapshot (+) stroke x stroke opacity
STROKE_APPLY_FS = HEADER + """
uniform sampler2D u_s0, u_s1, u_s2, u_s3, u_s4, u_s5, u_s6;   // snapshot C R M H N E O
uniform sampler2D u_k0, u_k1, u_k2, u_k3, u_k4, u_k5, u_k6;   // stroke buffer
uniform float u_so;
uniform int u_erase;
in vec2 v_uv;
layout(location=0) out vec4 o0;
layout(location=1) out vec4 o1;
layout(location=2) out vec4 o2;
layout(location=3) out vec4 o3;
layout(location=4) out vec4 o4;
layout(location=5) out vec4 o5;
layout(location=6) out vec4 o6;
vec4 a4(sampler2D s, sampler2D k) {
    vec4 S = texture(s, v_uv), K = texture(k, v_uv);
    float c = clamp(K.a * u_so, 0.0, 1.0);
    return u_erase == 1 ? S * (1.0 - c) : S * (1.0 - c) + K * u_so;
}
vec4 a2(sampler2D s, sampler2D k) {
    vec4 S = texture(s, v_uv), K = texture(k, v_uv);
    float c = clamp(K.g * u_so, 0.0, 1.0);
    return u_erase == 1 ? vec4(S.rg * (1.0 - c), 0.0, 1.0) : vec4(S.rg * (1.0 - c) + K.rg * u_so, 0.0, 1.0);
}
void main() {
    o0 = a4(u_s0, u_k0); o1 = a2(u_s1, u_k1); o2 = a2(u_s2, u_k2); o3 = a2(u_s3, u_k3);
    o4 = a4(u_s4, u_k4); o5 = a4(u_s5, u_k5); o6 = a2(u_s6, u_k6);
}
"""

STROKE_APPLY_MASK_FS = HEADER + """
uniform sampler2D u_snap, u_stroke;
uniform float u_so, u_value;
in vec2 v_uv; out vec4 o;
void main() {
    float s = texture(u_snap, v_uv).r;
    float c = clamp(texture(u_stroke, v_uv).r * u_so, 0.0, 1.0);
    float m = mix(s, u_value, c);
    o = vec4(m, m, m, 1.0);
}
"""

# --------------------------------------------------------------------------- viewport
SCENE_VS = HEADER + """
uniform mat4 u_vp;
uniform sampler2D u_texR;
uniform float u_displacementScale, u_heightMidlevel;
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv; in vec4 in_tan; in float in_curv; in vec2 in_part;
out vec3 v_pos; out vec3 v_nrm; out vec2 v_uv; out vec4 v_tan; out vec2 v_part;
void main() {
    v_pos = in_pos; v_nrm = in_nrm; v_uv = in_uv; v_tan = in_tan; v_part = in_part;
    if (u_displacementScale != 0.0) v_pos += normalize(in_nrm) * ((textureLod(u_texR, in_uv, 0.0).b - u_heightMidlevel) * u_displacementScale);
    gl_Position = u_vp * vec4(v_pos, 1.0);
}
"""

PICK_FS = HEADER + """
uniform int u_triOffset;
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv; in vec2 v_part;
layout(location=0) out vec4 o_pos;
layout(location=1) out vec4 o_nrm;
layout(location=2) out vec4 o_uv;
void main() {
    o_pos = vec4(v_pos, 1.0);
    o_nrm = vec4(normalize(v_nrm), 1.0);
    o_uv = vec4(v_uv, float(gl_PrimitiveID + u_triOffset), v_part.x);
}
"""

ENV = """
uniform float u_envRot;
uniform sampler2D u_envMap;
uniform int u_hasEnv;
uniform float u_envMaxLod;
const float PI = 3.14159265;
vec3 rotY(vec3 d, float a) { float c = cos(a), s = sin(a); return vec3(c*d.x + s*d.z, d.y, -s*d.x + c*d.z); }
vec2 equirect(vec3 d) { return vec2(atan(d.z, d.x) / (2.0 * PI) + 0.5, asin(clamp(d.y, -1.0, 1.0)) / PI + 0.5); }
// soft studio environment: sky gradient + two soft boxes, blurred by roughness
vec3 envColor(vec3 d, float r) {
    d = rotY(d, u_envRot);
    if (u_hasEnv == 1) return textureLod(u_envMap, equirect(d), r * u_envMaxLod).rgb;
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
    if (u_hasEnv == 1) return textureLod(u_envMap, equirect(n), u_envMaxLod).rgb;
    vec3 up = vec3(0.46, 0.47, 0.5), down = vec3(0.1, 0.095, 0.09);
    vec3 k1 = normalize(vec3(0.6, 0.55, 0.6)), k2 = normalize(vec3(-0.8, 0.25, -0.4));
    return mix(down, up, n.y * 0.5 + 0.5) + vec3(0.5, 0.48, 0.46) * max(dot(n, k1), 0.0)
         + vec3(0.12, 0.14, 0.18) * max(dot(n, k2), 0.0);
}
"""

SCENE_FS = HEADER + ENV + NOISE + """
uniform sampler2D u_texC, u_texR, u_texN, u_ao, u_curv, u_maskPrev, u_texE, u_thick, u_id, u_pos, u_wnrm;
uniform sampler2D u_bakedNormal, u_bakedHeight;
uniform sampler2D u_specGloss, u_coat;
uniform int u_materialModel, u_hasCoat;
uniform float u_displacementScale;
uniform vec3 u_campos;
uniform int u_mode;   // strata.renderer.DISPLAY_MODES
uniform float u_exposure;
uniform int u_useAO;
uniform float u_emissiveIntensity;
uniform int u_alphaTest;
uniform vec3 u_bmin, u_bmax;
uniform int u_wire;
in vec3 v_pos; in vec3 v_nrm; in vec2 v_uv; in vec4 v_tan;
out vec4 o;

vec3 srgb2lin(vec3 c) { return pow(c, vec3(2.2)); }
vec3 aces(vec3 x) { return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }

void main() {
    vec3 Ng = normalize(v_nrm);
    if (u_displacementScale != 0.0) { vec3 dn=normalize(cross(dFdx(v_pos),dFdy(v_pos))); Ng=dot(dn,Ng)<0.0?-dn:dn; }
    vec3 T = normalize(v_tan.xyz - Ng * dot(Ng, v_tan.xyz));
    vec3 B = cross(Ng, T) * v_tan.w;
    vec3 tn = texture(u_texN, v_uv).xyz * 2.0 - 1.0;
    vec3 N = normalize(T * tn.x + B * tn.y + Ng * tn.z);
    vec4 c = texture(u_texC, v_uv);
    vec4 rmh = texture(u_texR, v_uv);
    float ao = u_useAO == 1 ? texture(u_ao, v_uv).r : 1.0;
    if (u_mode == 18) { o = vec4(N * 0.5 + 0.5, 1.0); return; }
    vec3 V = normalize(u_campos - v_pos);
    if (u_alphaTest == 1 && rmh.a < 0.5 && u_mode == 0) discard;

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
    if (u_mode == 10) { o = vec4(texture(u_texE, v_uv).rgb, 1.0); return; }
    if (u_mode == 11) { o = vec4(vec3(rmh.a), 1.0); return; }
    if (u_mode == 12) { o = vec4(vec3(texture(u_thick, v_uv).r), 1.0); return; }
    if (u_mode == 13) { o = vec4(texture(u_id, v_uv).rgb, 1.0); return; }
    if (u_mode == 16) { o = vec4(texture(u_bakedNormal, v_uv).rgb, 1.0); return; }
    if (u_mode == 17) { o = vec4(vec3(texture(u_bakedHeight, v_uv).r), 1.0); return; }
    if (u_mode == 14) { o = vec4(normalize(texture(u_wnrm, v_uv).xyz) * 0.5 + 0.5, 1.0); return; }
    if (u_mode == 15) { o = vec4((texture(u_pos, v_uv).xyz - u_bmin) / max(u_bmax - u_bmin, vec3(1e-5)), 1.0); return; }

    vec3 albedo = srgb2lin(c.rgb);
    float rough = clamp(rmh.r, 0.04, 1.0), metal = clamp(rmh.g, 0.0, 1.0);
    vec3 F0 = mix(vec3(0.04), albedo, metal);
    vec4 sg = texture(u_specGloss, v_uv);
    vec2 coat = u_hasCoat == 1 ? texture(u_coat, v_uv).rg : vec2(0.0, 0.1);
    if (u_materialModel == 1) { F0 = clamp(sg.rgb, 0.0, 1.0); rough = clamp(1.0-sg.a, 0.04, 1.0); metal = 0.0; }
    if (u_mode == 19) { o=vec4(vec3(texture(u_bakedHeight,v_uv).r),1.0);return; }
    if (u_mode == 20) { o=vec4(F0,1.0);return; }
    if (u_mode == 21) { o=vec4(vec3(rough),1.0);return; }
    if (u_mode == 22) { o=vec4(coat,0.0,1.0);return; }
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
    if (u_hasEnv == 1) direct *= 0.0;

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
    if (coat.x > 0.0) {
        float cr=clamp(coat.y,0.04,1.0), ca=cr*cr, ca2=ca*ca;
        float cd=ca2/(PI*pow(NoH*NoH*(ca2-1.0)+1.0,2.0));
        float ck=(cr+1.0)*(cr+1.0)/8.0;
        float cg=NoV/(NoV*(1.0-ck)+ck)*NoL/(NoL*(1.0-ck)+ck);
        float cf=.04+.96*pow(1.0-VoH,5.0);
        float cv=.04+.96*pow(1.0-NoV,5.0);
        vec3 coatLight=envColor(R,cr)*cv;
        if(u_hasEnv==0) coatLight+=cd*cg*cf/max(4.0*NoV*NoL,1e-4)*NoL*vec3(3.4,3.25,3.05);
        col=col*(1.0-coat.x*cv)+coat.x*coatLight;
    }
    col += srgb2lin(texture(u_texE, v_uv).rgb) * u_emissiveIntensity;
    col = aces(col * u_exposure);
    o = vec4(pow(col, vec3(1.0 / 2.2)), 1.0);
}
"""

# 2D view: one texture-set channel laid flat in UV space, with a UV wireframe overlay
VIEW2D_VS = HEADER + """
uniform mat3 u_xf;          // uv -> clip
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv;
out vec2 v_uv;
void main() { v_uv = in_uv; vec3 p = u_xf * vec3(in_uv, 1.0); gl_Position = vec4(p.xy, 0.0, 1.0); }
"""
VIEW2D_FS = HEADER + """
uniform sampler2D u_tex;
uniform int u_comp;         // -1 rgb, else single component
uniform vec4 u_tint;
uniform int u_flat;
in vec2 v_uv; out vec4 o;
void main() {
    if (u_flat == 1) { o = u_tint; return; }
    vec4 t = texture(u_tex, v_uv);
    o = vec4(u_comp < 0 ? t.rgb : vec3(t[u_comp]), 1.0);
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

SYMMETRY_GUIDE_VS = HEADER + """
uniform mat4 u_vp;
in vec3 in_pos;
out vec3 v_pos;
void main() {
    v_pos = in_pos;
    gl_Position = u_vp * vec4(in_pos, 1.0);
    gl_Position.z -= 0.00001 * gl_Position.w;
}
"""
SYMMETRY_GUIDE_FS = HEADER + """
uniform vec3 u_center;
uniform int u_axis;
uniform int u_radial;
uniform int u_copies;
in vec3 v_pos;
out vec4 o;
void main() {
    vec3 p = v_pos - u_center;
    float distance = p[u_axis];
    float width = fwidth(distance);
    if (u_radial == 1) {
        vec2 q = u_axis == 0 ? p.yz : (u_axis == 1 ? p.zx : p.xy);
        float angle = atan(q.y, q.x);
        float step = 6.28318530718 / float(u_copies);
        float boundary = floor(angle / step + 0.5) * step;
        vec2 normal = vec2(-sin(boundary), cos(boundary));
        distance = dot(q, normal);
        // Differentiate position to avoid seams where the nearest sector changes.
        width = abs(dot(dFdx(q), normal)) + abs(dot(dFdy(q), normal));
    }
    // Derivatives keep the surface guide about two pixels wide at any zoom.
    if (width < 1e-8) discard;
    float alpha = 1.0 - smoothstep(0.5, 1.5, abs(distance) / width);
    if (alpha <= 0.0) discard;
    o = vec4(1.0, 0.06, 0.04, alpha * 0.95);
}
"""

LINE_VS = HEADER + """
uniform mat4 u_vp;
in vec3 in_pos;
void main() { gl_Position = u_vp * vec4(in_pos, 1.0); }
"""
WIRE_VS = HEADER + """
uniform mat4 u_vp;
uniform vec3 u_campos;
uniform float u_bias;     // fraction of the distance to the camera to pull the vertex in (beats z-fighting)
in vec3 in_pos;
void main() { gl_Position = u_vp * vec4(in_pos + (u_campos - in_pos) * u_bias, 1.0); }
"""
LINE_FS = HEADER + """
uniform vec4 u_color;
out vec4 o;
void main() { o = u_color; }
"""
