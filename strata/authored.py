"""Persistent surface polylines/ribbons/regions and font-backed UV labels."""
import hashlib
import math
from contextlib import contextmanager
from pathlib import Path
import numpy as np


class AuthoredResourceError(ValueError):
    pass


def topology_key(mesh):
    h=hashlib.sha256()
    for value in (np.asarray(mesh.indices,np.uint32),np.asarray(mesh.uvs,np.float32),np.asarray(mesh.tri_material,np.int32)):
        h.update(value.tobytes())
    return h.hexdigest()


def warp_matrix(corners):
    if corners is None:return np.eye(3)
    q=np.asarray(corners,float)
    if q.shape!=(4,2) or not np.isfinite(q).all() or np.abs(q).max()>32:
        raise ValueError("Warp needs four finite UV corners within -32..32")
    edges=np.roll(q,-1,axis=0)-q
    cross=edges[:,0]*np.roll(edges,-1,axis=0)[:,1]-edges[:,1]*np.roll(edges,-1,axis=0)[:,0]
    if np.any(cross<=1e-7):raise ValueError("Warp quad must be convex, counterclockwise and nondegenerate")
    src=np.array([[0,0],[1,0],[1,1],[0,1]],float);rows=[];rhs=[]
    for (x,y),(u,v) in zip(q,src):
        rows.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);rhs.extend([u,v])
    try:result=np.r_[np.linalg.solve(rows,rhs),1.].reshape(3,3)
    except np.linalg.LinAlgError as error:raise ValueError("Warp quad is singular") from error
    if np.linalg.cond(result)>1e8:raise ValueError("Warp quad is unstable")
    return result


def anchor_uv(mesh,uv,triangles=None):
    uv=np.asarray(uv,float)
    if uv.shape!=(2,) or not np.isfinite(uv).all():raise ValueError("Surface point needs a finite UV pair")
    ids=np.arange(len(mesh.indices)) if triangles is None else np.asarray(triangles)
    tri=mesh.uvs[mesh.indices[ids]].astype(float);a=tri[:,0];b=tri[:,1]-a;c=tri[:,2]-a;d=uv-a
    det=b[:,0]*c[:,1]-b[:,1]*c[:,0];safe=np.where(abs(det)>1e-12,det,1)
    v=(d[:,0]*c[:,1]-d[:,1]*c[:,0])/safe;w=(b[:,0]*d[:,1]-b[:,1]*d[:,0])/safe
    bary=np.stack([1-v-w,v,w],axis=1);hits=np.flatnonzero((abs(det)>1e-12)&(bary.min(1)>=-1e-6))
    if not len(hits):raise ValueError("Path point is outside this material's UV surface")
    world=np.einsum("ij,ijk->ik",bary[hits],mesh.positions[mesh.indices[ids[hits]]])
    if np.linalg.norm(world-world[0],axis=1).max()>max(mesh.radius,1)*1e-6:
        raise ValueError("Ambiguous overlapping UV surface; select a triangle in the 3D view")
    index=int(hits[0]);weights=np.clip(bary[index],0,1);weights/=weights.sum()
    return {"tri":int(ids[index]),"bary":weights.tolist(),"pressure":1.,"width":1.}


def path(mesh,points,kind="path",width=.04):
    return {"version":1,"kind":kind,"topology":topology_key(mesh),"points":points,"width":width,
            "spacing":.25,"repeat":1.,"closed":kind=="region","alpha":None}


def text(font,label="Label"):
    return {"version":1,"kind":"text","font":str(Path(str(font)).expanduser().resolve()),"text":label,"origin":[.1,.5],
            "size":.12,"tracking":0.,"leading":1.2,"align":"left"}


def validate(value,mesh=None,triangles=None):
    if not isinstance(value,dict) or value.get("version")!=1 or value.get("kind") not in ("path","ribbon","region","text"):
        raise ValueError("Unsupported authored object")
    def scalar(key,lo,hi):
        v=value.get(key)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError("Invalid authored "+key)
    if value["kind"]=="text":
        if not isinstance(value.get("font"),str) or not value["font"]:raise ValueError("Choose a font file")
        if not isinstance(value.get("text"),str) or len(value["text"])>2048:raise ValueError("Text is limited to 2048 characters")
        scalar("size",.001,4.);scalar("tracking",-.5,2.);scalar("leading",.5,4.)
        if value.get("align") not in ("left","center","right"):raise ValueError("Invalid text alignment")
        origin=np.asarray(value.get("origin"),float)
        if origin.shape!=(2,) or not np.isfinite(origin).all() or abs(origin).max()>32:raise ValueError("Invalid text origin")
        return value
    scalar("width",.00001,4.);scalar("spacing",.05,2.);scalar("repeat",.001,64.)
    if type(value.get("closed")) is not bool:raise ValueError("Invalid path closure")
    if value["kind"]=="region" and not value["closed"]:raise ValueError("Filled regions must be closed")
    key=value.get("topology")
    if not isinstance(key,str) or len(key)!=64 or any(c not in "0123456789abcdef" for c in key):raise ValueError("Invalid path surface identity")
    if mesh is not None and topology_key(mesh)!=key:raise ValueError("Authored surface paths require unchanged indexed topology, UVs and materials")
    if value.get("alpha") is not None and not isinstance(value["alpha"],str):raise ValueError("Invalid path tip resource")
    points=value.get("points")
    if not isinstance(points,list) or not (3 if value["kind"]=="region" else 2)<=len(points)<=64:raise ValueError("Paths require 2..64 points; regions require at least three")
    allowed=set(triangles) if triangles is not None else None
    for point in points:
        if not isinstance(point,dict) or type(point.get("tri")) is not int or point["tri"]<0:raise ValueError("Invalid path triangle")
        bary=np.asarray(point.get("bary"),float)
        if bary.shape!=(3,) or not np.isfinite(bary).all() or bary.min()<-1e-6 or abs(bary.sum()-1)>1e-5:raise ValueError("Invalid path barycentric anchor")
        for name,lo,hi in (("pressure",0.,1.),("width",.01,16.)):
            v=point.get(name)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError("Invalid path profile")
        if mesh is not None and (point["tri"]>=len(mesh.indices) or (allowed is not None and point["tri"] not in allowed)):raise ValueError("Path point belongs to another material or missing triangle")
    if mesh is not None:
        # Indexed connected charts only. UV seams with split vertices remain distinct.
        cache=getattr(mesh,"_authored_charts",None)
        if cache is None or cache[0]!=key:
            parent=np.arange(len(mesh.positions))
            def root(i):
                while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
                return i
            for tri in mesh.indices:
                a=root(int(tri[0]))
                for b in tri[1:]:parent[root(int(b))]=a
            roots=np.array([root(i) for i in range(len(parent))])
            mesh._authored_charts=(key,roots)
        roots=mesh._authored_charts[1]
        if len({int(roots[mesh.indices[p["tri"],0]]) for p in points})>1:raise ValueError("Path crosses disconnected indexed UV charts; split it into separate paths")
        uv=coordinates(mesh,value)
        if np.any(np.linalg.norm(np.diff(uv[:,:2],axis=0),axis=1)<1e-8):raise ValueError("Adjacent path points must be distinct")
        if value["kind"]=="region":
            xy=uv[:,:2];area=np.sum(xy[:,0]*np.roll(xy[:,1],-1)-xy[:,1]*np.roll(xy[:,0],-1))*.5
            if abs(area)<1e-8:raise ValueError("Region has zero area")
            def cross(a,b):return a[0]*b[1]-a[1]*b[0]
            for i in range(len(xy)):
                a,b=xy[i],xy[(i+1)%len(xy)]
                for j in range(i+2,len(xy)):
                    if (j+1)%len(xy)==i:continue
                    c,d=xy[j],xy[(j+1)%len(xy)]
                    if cross(b-a,c-a)*cross(b-a,d-a)<0 and cross(d-c,a-c)*cross(d-c,b-c)<0:raise ValueError("Self-intersecting regions are unsupported")
    return value


def coordinates(mesh,value):
    return np.array([[*(np.asarray(p["bary"])@mesh.uvs[mesh.indices[p["tri"]]]),p["width"],p["pressure"]] for p in value["points"]],np.float32)


def font_atlas(value,res):
    from PIL import Image,ImageDraw,ImageFont
    validate(value)
    if not Path(value["font"]).is_file():raise AuthoredResourceError("Choose an existing font file: "+value["font"])
    try:font=ImageFont.truetype(value["font"],max(1,round(value["size"]*res)))
    except OSError as error:raise AuthoredResourceError("Text font unavailable or invalid: "+value["font"]) from error
    lines=value["text"].split("\n");tracking=value["tracking"]*value["size"]*res
    lengths=[max(0.,float(font.getlength(line))+max(0,len(line)-1)*tracking) for line in lines]
    ascent,descent=font.getmetrics();step=max(1,round((ascent+descent)*value["leading"]))
    width=max(1,math.ceil(max(lengths,default=0))+4);height=max(1,step*len(lines)+4)
    if width*height>16*1024*1024:raise MemoryError("Text atlas exceeds the 16 MiB budget")
    image=Image.new("L",(width,height));draw=ImageDraw.Draw(image)
    for index,line in enumerate(lines):
        x=2.+(0 if value["align"]=="left" else (width-4-lengths[index])*(.5 if value["align"]=="center" else 1.))
        if tracking==0:draw.text((x,index*step+2),line,font=font,fill=255,anchor="lt")
        else:
            for char in line:
                draw.text((x,index*step+2),char,font=font,fill=255,anchor="lt");x+=font.getlength(char)+tracking
    return np.asarray(image,np.float32)[::-1,:,None]/255.,(width/res,height/res)


SHADER="""
uniform int u_kind,u_count,u_closed;uniform vec4 u_points[64];
uniform float u_width,u_spacing,u_repeat;uniform sampler2D u_tip,u_font;uniform int u_hasTip;
uniform vec2 u_origin,u_textSize,u_tile;uniform sampler2D u_surface;
in vec2 v_uv;out vec4 o;
void main(){vec2 uv=v_uv+u_tile;float cov=0.,best=1e9,total=0.,along=0.,across=.5;bool inside=false;
if(u_kind==4){vec2 base=uv;if(u_projMode==2)base=axisPlane((texture(u_surface,v_uv).xyz-u_center)/u_meshSize,u_projAxis)+.5;vec2 q=projXf(base);cov=all(greaterThanEqual(q,vec2(0)))&&all(lessThanEqual(q,vec2(1)))?1.:0.;o=vec4(q,cov,1);return;}
if(u_kind==3){vec2 base=uv;if(u_projMode==2)base=axisPlane((texture(u_surface,v_uv).xyz-u_center)/u_meshSize,u_projAxis)+.5;vec2 domain=projXf(base);vec2 q=(domain-u_origin)/u_textSize;cov=all(greaterThanEqual(q,vec2(0)))&&all(lessThanEqual(q,vec2(1)))?texture(u_font,q).r:0.;if(u_projClip==1&&(any(lessThan(domain,vec2(0)))||any(greaterThan(domain,vec2(1)))))cov=0.;o=vec4(q,cov,1);return;}
for(int i=0;i<64;i++){if(i>=u_count)break;int j=i+1;if(j==u_count){if(u_closed==0)break;j=0;}vec4 a=u_points[i],b=u_points[j];vec2 edge=b.xy-a.xy;float len=length(edge);if(len<1e-8)continue;
float raw=dot(uv-a.xy,edge)/(len*len),t=clamp(raw,0.,1.);float width=u_width*mix(a.z*a.w,b.z*b.w,t);float radius=max(width*.5,1e-8);
float signedSide=(edge.x*(uv.y-a.y)-edge.y*(uv.x-a.x))/len;float dist=length(uv-mix(a.xy,b.xy,t));
if(u_kind==0){float steps=max(1.,ceil(len/max(u_width*u_spacing,1e-8)));t=round(t*steps)/steps;vec2 delta=uv-mix(a.xy,b.xy,t);dist=length(delta);width=u_width*mix(a.z*a.w,b.z*b.w,t);radius=max(width*.5,1e-8);}
float aa=max(fwidth(dist),1e-6);float hit=1.-smoothstep(radius-aa,radius+aa,dist);
if(u_hasTip==1&&u_kind==0){vec2 tangent=edge/len;vec2 delta=uv-mix(a.xy,b.xy,t);vec2 tip=vec2(dot(delta,tangent),signedSide)/max(width,1e-8)+.5;hit*=texture(u_tip,clamp(tip,0.,1.)).r;}
cov=max(cov,hit);if(dist<best){best=dist;along=(total+t*len)/u_repeat;across=.5+signedSide/max(width,1e-8);}total+=len;
if((a.y>uv.y)!=(b.y>uv.y)){float x=a.x+(uv.y-a.y)*(b.x-a.x)/(b.y-a.y);if(uv.x<x)inside=!inside;}}
if(u_kind==2){float aa=max(fwidth(best),1e-6);cov=inside?.5+.5*smoothstep(0.,aa,best):.5-.5*smoothstep(0.,aa,best);}
if(u_projClip==1){vec2 q=projXf(u_kind==1?vec2(along,across):uv);if(any(lessThan(q,vec2(0)))||any(greaterThan(q,vec2(1))))cov=0.;}
o=vec4(along,across,cov,1.);}
"""


@contextmanager
def evaluate(compositor,layer):
    from . import shaders as S
    from .mathutil import glmat
    import moderngl
    value=layer.authored or {"kind":"decal"}
    if layer.authored is not None:validate(value,compositor.mesh)
    if value["kind"] in ("text","decal") and layer.proj.mode not in (0,2):raise ValueError("Text/decal placement supports UV or planar projection")
    g=compositor.gpu;res=compositor.res;created=[];fbo=None
    if res*res*8>128*1024*1024:raise MemoryError("Authored object coverage exceeds the 128 MiB budget")
    try:
        output=g.texture((res,res),4,dtype="f2");created.append(output)
        prog=g.fs_program("authored-v1",S.HEADER+S.MESHU+S.PROJ+SHADER)
        compositor._set_proj(prog,layer.proj)
        points=np.zeros((64,4),np.float32);font=g.black;size=(1.,1.)
        if value["kind"]=="text":
            pixels,size=font_atlas(value,res)
            font=g.texture((pixels.shape[1],pixels.shape[0]),1,pixels,dtype="f1",repeat=False);created.append(font)
        elif value["kind"]!="decal":points[:len(value["points"])]=coordinates(compositor.mesh,value)
        prog["u_points"].write(points.tobytes())
        kind=("path","ribbon","region","text","decal").index(value["kind"])
        for key,item in {"u_kind":kind,"u_count":len(value.get("points",[])),"u_closed":int(value.get("closed",False)),"u_width":float(value.get("width",.04)),"u_spacing":float(value.get("spacing",.25)),"u_repeat":float(value.get("repeat",1.)),"u_hasTip":int(bool(value.get("alpha"))),"u_textSize":size,"u_origin":tuple(value.get("origin",[0.,0.])),"u_tile":tuple(getattr(compositor,"authored_origin",(0.,0.)))}.items():g.set(prog,key,item)
        try:tip=compositor.resources.alpha(value["alpha"]) if value.get("alpha") else g.white
        except (OSError,ValueError) as error:raise AuthoredResourceError("Path tip unavailable: "+str(value.get("alpha"))) from error
        g.bind(prog,{"u_tip":(0,tip),"u_font":(1,font),"u_surface":(2,compositor.bakes.pos)})
        g.set(prog,"u_center",tuple(float(x) for x in compositor.mesh.center))
        g.set(prog,"u_meshSize",float(compositor.mesh.radius*2))
        fbo=g.ctx.framebuffer([output]);fbo.use();g.ctx.viewport=(0,0,res,res);g.ctx.scissor=None
        g.ctx.disable(moderngl.BLEND|moderngl.DEPTH_TEST|moderngl.CULL_FACE);g.draw_quad(prog)
        yield output
    finally:
        if fbo is not None:fbo.release()
        for texture in created:texture.release()
