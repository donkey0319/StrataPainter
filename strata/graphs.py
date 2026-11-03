"""Versioned native procedural DAGs. No Adobe runtime or graph-name inference."""
import math
from contextlib import contextmanager

SPECS = {
    "input": {}, "constant": {"value": (0.5, -16., 16.)},
    "grunge": {"scale": (8., .01, 2048.), "seed": (0., 0., 65535.), "roughness": (.5, 0., 1.), "ridge": (0., 0., 1.)},
    "ramp": {"angle": (0., -180., 180.), "offset": (0., -2., 2.)},
    "gradient": {},
    "transform": {"scale_x": (1., .001, 1024.), "scale_y": (1., .001, 1024.), "offset_x": (0., -16., 16.), "offset_y": (0., -16., 16.), "angle": (0., -180., 180.)},
    "warp": {"strength": (8., -256., 256.), "angle": (0., -180., 180.)},
    "sharpen": {"strength": (1., 0., 8.), "radius": (1., .1, 32.)},
    "mix": {"weight": (.5, 0., 1.)},
}
ARITY = {"input": 0, "constant": 0, "grunge": 0, "ramp": 0, "gradient": 1, "transform": 1, "warp": 2, "sharpen": 1, "mix": 2}
OPS = list(SPECS)


def node(op, identifier, inputs=()):
    result = {"id": identifier, "op": op, "inputs": list(inputs), "params": {key: spec[0] for key, spec in SPECS[op].items()}}
    if op == "gradient":
        result["params"]["stops"] = [[0., 0., 0., 0.], [1., 1., 1., 1.]]
    return result


def preset(name="grunge"):
    if name == "grunge":
        nodes = [node("grunge", "noise"), node("gradient", "color", ["noise"])]
    else:
        nodes = [node("input", "source"), node(name, "filter", ["source"])]
        if name == "warp":
            nodes.insert(1, node("grunge", "noise"))
            nodes[-1]["inputs"].append("noise")
    return {"version": 1, "nodes": nodes, "output": nodes[-1]["id"]}


def validate(graph):
    if not isinstance(graph, dict) or graph.get("version") != 1:
        raise ValueError("Unsupported native graph version")
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 32:
        raise ValueError("Native graphs require 1..32 nodes")
    seen = set()
    for n in nodes:
        if not isinstance(n, dict) or n.get("op") not in SPECS:
            raise ValueError("Unsupported native graph operation")
        key, op, inputs, params = n.get("id"), n["op"], n.get("inputs"), n.get("params")
        if not isinstance(key, str) or not key or len(key) > 64 or key in seen:
            raise ValueError("Invalid or duplicate graph node ID")
        if not isinstance(inputs, list) or len(inputs) != ARITY[op] or any(not isinstance(x, str) or x not in seen for x in inputs):
            raise ValueError("Graph inputs must reference prior nodes with the required arity")
        if not isinstance(params, dict) or set(params) != set(SPECS[op]) | ({"stops"} if op == "gradient" else set()):
            raise ValueError("Invalid graph parameters")
        for name, (_, lo, hi) in SPECS[op].items():
            value = params[name]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError("Graph parameter outside its documented range: " + name)
        if op == "gradient":
            stops = params["stops"]
            if not isinstance(stops, list) or not 2 <= len(stops) <= 8:
                raise ValueError("Gradient requires 2..8 ordered stops")
            prior = -1.
            for stop in stops:
                if (not isinstance(stop, list) or len(stop) != 4 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in stop) or
                    not prior < stop[0] <= 1 or stop[0] < 0 or any(not -16 <= v <= 16 for v in stop[1:])):
                    raise ValueError("Invalid gradient stop")
                prior = stop[0]
        seen.add(key)
    if graph.get("output") not in seen:
        raise ValueError("Missing native graph output")
    return graph


SHADER = """
uniform sampler2D u_source,u_a,u_b; uniform int u_op,u_component,u_count;
uniform vec4 u_p,u_q,u_stops[8]; uniform vec2 u_px;
in vec2 v_uv; out vec4 o;
float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7))+u_p.y)*43758.5453);}
float noise(vec2 p){vec2 i=floor(p),f=fract(p); f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);}
void main(){vec2 uv=v_uv; vec4 a=texture(u_a,uv),b=texture(u_b,uv);o=a;
if(u_op==0){vec4 s=texture(u_source,uv);o=u_component<0?vec4(s.rgb,1):vec4(vec3(s[u_component]),1);}
else if(u_op==1)o=vec4(vec3(u_p.x),1);
else if(u_op==2){float sum=0.,amp=1.,total=0.;vec2 p=uv*u_p.x;for(int i=0;i<6;i++){float n=noise(p);sum+=mix(n,1.-abs(2.*n-1.),u_p.w)*amp;total+=amp;amp*=u_p.z;p=p*2.03+vec2(7.1,3.7);}o=vec4(vec3(sum/total),1);}
else if(u_op==3)o=vec4(vec3(clamp(dot(uv-.5,vec2(cos(radians(u_p.x)),sin(radians(u_p.x))))+.5+u_p.y,0.,1.)),1);
else if(u_op==4){float x=dot(a.rgb,vec3(.2126,.7152,.0722));vec3 c=u_stops[0].yzw;for(int i=1;i<8;i++){if(i>=u_count)break;float t=clamp((x-u_stops[i-1].x)/max(u_stops[i].x-u_stops[i-1].x,1e-6),0.,1.);c=mix(c,u_stops[i].yzw,t);}o=vec4(c,1);}
else if(u_op==5){float r=radians(u_q.x);vec2 p=(uv-.5)/u_p.xy;p=mat2(cos(r),-sin(r),sin(r),cos(r))*p+.5-u_p.zw;o=texture(u_a,fract(p));}
else if(u_op==6){vec2 d=vec2(cos(radians(u_p.y)),sin(radians(u_p.y)))*(b.r*2.-1.)*u_p.x*u_px;o=texture(u_a,fract(uv+d));}
else if(u_op==7){vec2 d=u_px*u_p.y;vec4 avg=(texture(u_a,uv+vec2(d.x,0))+texture(u_a,uv-vec2(d.x,0))+texture(u_a,uv+vec2(0,d.y))+texture(u_a,uv-vec2(0,d.y)))*.25;o=vec4((a+(a-avg)*u_p.x).rgb,1);}
else if(u_op==8)o=mix(a,b,u_p.x);
}
"""


@contextmanager
def evaluate(gpu, graph, source, component=-1, max_bytes=256*1024*1024):
    """Yield one f2 RGBA result; bound live intermediates and release on all paths."""
    from .shaders import HEADER
    import numpy as np
    validate(graph)
    values, uses = {}, {}
    for n in graph["nodes"]:
        for key in n["inputs"]:
            uses[key] = uses.get(key, 0) + 1
    uses[graph["output"]] = uses.get(graph["output"], 0) + 1
    program = gpu.fs_program("native-graph-v1", HEADER + SHADER)
    try:
        for n in graph["nodes"]:
            if (len(values)+1)*source.size[0]*source.size[1]*8 > max_bytes:
                raise MemoryError("Native graph intermediate budget exceeded")
            output = gpu.texture(source.size, 4, dtype="f2")
            values[n["id"]] = output
            inputs = [values[key] for key in n["inputs"]]
            gpu.bind(program, {"u_source": (0, source), "u_a": (1, inputs[0] if inputs else gpu.black), "u_b": (2, inputs[1] if len(inputs)>1 else gpu.black)})
            params = n["params"]
            scalar = [float(params[key]) for key in SPECS[n["op"]]]
            scalar += [0.]*(8-len(scalar))
            for key,value in {"u_op":OPS.index(n["op"]),"u_component":component,"u_px":(1/source.size[0],1/source.size[1]),"u_p":tuple(scalar[:4]),"u_q":tuple(scalar[4:8]),"u_count":len(params.get("stops",[]))}.items():
                gpu.set(program,key,value)
            stops=np.zeros((8,4),np.float32)
            for i,stop in enumerate(params.get("stops",[])):stops[i]=stop
            program["u_stops"].write(stops.tobytes())
            fbo=gpu.ctx.framebuffer([output])
            try:
                fbo.use();gpu.ctx.viewport=(0,0,*source.size);gpu.ctx.scissor=None
                import moderngl
                gpu.ctx.disable(moderngl.BLEND|moderngl.DEPTH_TEST|moderngl.CULL_FACE)
                gpu.draw_quad(program)
            finally:fbo.release()
            for key in n["inputs"]:
                uses[key]-=1
                if not uses[key]:values.pop(key).release()
            if not uses.get(n["id"],0):values.pop(n["id"]).release()
        yield values[graph["output"]]
    finally:
        for texture in values.values():texture.release()
