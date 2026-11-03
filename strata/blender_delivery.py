"""Standalone Blender delivery importer. Also shipped inside every delivery ZIP."""
import argparse
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import numpy as np
import bpy
from mathutils import Vector
# Works both beside the installed source and after extracting the delivery ZIP.
_spec=importlib.util.spec_from_file_location("_strata_delivery_archive_v1",Path(__file__).with_name("bundleio.py"))
_archive=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_archive)
unpack,geometry=_archive.unpack,_archive.geometry


def import_bundle(path):
    """Create a new collection, preserving the user's existing scene and materials."""
    created_materials=[];created_images=[];collection=None;obj=None
    try:
        with tempfile.TemporaryDirectory(prefix="strata-blender-") as temporary:
            root=Path(temporary);meta=unpack(path,root)
            data=geometry(root/meta["geometry"]["file"],len(meta["materials"]))
            materials=[];displacements={}
            for mi,record in enumerate(meta["materials"]):
                material=bpy.data.materials.new(record["name"]);created_materials.append(material);material.use_nodes=True
                material["strata_set_pid"]=record["pid"];material["strata_model"]=record["model"]
                nodes,links=material.node_tree.nodes,material.node_tree.links;nodes.clear()
                output=nodes.new("ShaderNodeOutputMaterial");textures={};images={}
                for semantic,texture in record["textures"].items():
                    image=bpy.data.images.load(str(root/texture["file"]),check_existing=False);created_images.append(image)
                    image.colorspace_settings.name="Non-Color";image.pack()
                    node=nodes.new("ShaderNodeTexImage");node.image=image;node.label=semantic;node.name="Strata "+semantic
                    textures[semantic]=node.outputs["Color"];images[semantic]=image
                normal=nodes.new("ShaderNodeNormalMap");normal.space="TANGENT";normal.uv_map="UVMap"
                links.new(textures["normal_opengl"],normal.inputs["Color"])
                def principled(name):
                    shader=nodes.new("ShaderNodeBsdfPrincipled");shader.label=name
                    links.new(normal.outputs["Normal"],shader.inputs["Normal"]);return shader
                if record["model"]=="metal_rough":
                    shader=principled("Metallic / roughness")
                    for semantic,socket in (("basecolor","Base Color"),("roughness","Roughness"),("metallic","Metallic")):
                        links.new(textures[semantic],shader.inputs[socket])
                    if "coat" in textures:
                        links.new(textures["coat"],shader.inputs["Coat Weight"]);links.new(textures["coat_roughness"],shader.inputs["Coat Roughness"])
                    surface=shader.outputs[0]
                else:
                    conductor=principled("Independent linear F0");conductor.inputs["Metallic"].default_value=1
                    links.new(textures["specular"],conductor.inputs["Base Color"])
                    rough=nodes.new("ShaderNodeMath");rough.operation="SUBTRACT";rough.inputs[0].default_value=1
                    links.new(textures["glossiness"],rough.inputs[1]);links.new(rough.outputs[0],conductor.inputs["Roughness"])
                    diffuse=nodes.new("ShaderNodeBsdfDiffuse");links.new(normal.outputs[0],diffuse.inputs["Normal"])
                    energy=nodes.new("ShaderNodeVectorMath");energy.operation="SUBTRACT";energy.inputs[0].default_value=(1,1,1)
                    links.new(textures["specular"],energy.inputs[1])
                    color=nodes.new("ShaderNodeVectorMath");color.operation="MULTIPLY";links.new(textures["basecolor"],color.inputs[0]);links.new(energy.outputs[0],color.inputs[1]);links.new(color.outputs[0],diffuse.inputs["Color"])
                    add=nodes.new("ShaderNodeAddShader");links.new(conductor.outputs[0],add.inputs[0]);links.new(diffuse.outputs[0],add.inputs[1]);surface=add.outputs[0]
                    if "coat" in textures:
                        coat=principled("Clearcoat reflection");coat.inputs["Metallic"].default_value=1;coat.inputs["Base Color"].default_value=(1,1,1,1)
                        links.new(textures["coat_roughness"],coat.inputs["Roughness"])
                        fresnel=nodes.new("ShaderNodeFresnel");fresnel.inputs["IOR"].default_value=1.5;links.new(normal.outputs[0],fresnel.inputs["Normal"])
                        weight=nodes.new("ShaderNodeMath");weight.operation="MULTIPLY";links.new(fresnel.outputs[0],weight.inputs[0]);links.new(textures["coat"],weight.inputs[1])
                        mix=nodes.new("ShaderNodeMixShader");links.new(weight.outputs[0],mix.inputs[0]);links.new(surface,mix.inputs[1]);links.new(coat.outputs[0],mix.inputs[2]);surface=mix.outputs[0]
                emission=nodes.new("ShaderNodeEmission");links.new(textures["emissive"],emission.inputs["Color"])
                add=nodes.new("ShaderNodeAddShader");links.new(surface,add.inputs[0]);links.new(emission.outputs[0],add.inputs[1]);surface=add.outputs[0]
                transparent=nodes.new("ShaderNodeBsdfTransparent");mix=nodes.new("ShaderNodeMixShader")
                links.new(textures["opacity"],mix.inputs[0]);links.new(transparent.outputs[0],mix.inputs[1]);links.new(surface,mix.inputs[2]);links.new(mix.outputs[0],output.inputs["Surface"])
                materials.append(material)
                if "displacement_meters" in images:
                    image=images["displacement_meters"];w,h=image.size
                    displacements[mi]=np.array(image.pixels[:],np.float32).reshape(h,w,4)[:,:,0]
            positions=data["positions"].copy();normals=data["normals"].copy();uvs=data["uvs"].copy();indices=data["indices"].copy();assignment=data["material_indices"]
            if displacements:
                if meta["geometry"]["units"]!="m":raise ValueError("Physical displacement requires meter-space geometry")
                vertices=indices.reshape(-1);positions=positions[vertices];normals=normals[vertices];uvs=uvs[vertices]
                indices=np.arange(len(vertices)).reshape(-1,3);owners=np.repeat(assignment,3)
                for mi,image in displacements.items():
                    chosen=np.flatnonzero(owners==mi);h,w=image.shape
                    pixel=np.clip(uvs[chosen]*[w,h]-.5,[0,0],[w-1,h-1]);lo=np.floor(pixel).astype(int);hi=np.minimum(lo+1,[w-1,h-1]);f=pixel-lo
                    height=(image[lo[:,1],lo[:,0]]*(1-f[:,0])+image[lo[:,1],hi[:,0]]*f[:,0])*(1-f[:,1])+(image[hi[:,1],lo[:,0]]*(1-f[:,0])+image[hi[:,1],hi[:,0]]*f[:,0])*f[:,1]
                    positions[chosen]+=normals[chosen]*height[:,None]
            # Right-handed Y-up project coordinates become Blender Z-up.
            positions=positions[:,[0,2,1]]*[1,-1,1];normals=normals[:,[0,2,1]]*[1,-1,1]
            mesh=bpy.data.meshes.new(meta["geometry"]["name"]);mesh.from_pydata(positions.tolist(),[],indices.tolist());mesh.update()
            obj=bpy.data.objects.new(meta["geometry"]["name"],mesh)
            collection=bpy.data.collections.new("Strata: "+meta["geometry"]["name"]);collection.objects.link(obj)
            uv=mesh.uv_layers.new(name="UVMap");vertices=np.array([loop.vertex_index for loop in mesh.loops])
            uv.data.foreach_set("uv",np.ascontiguousarray(uvs[vertices],np.float32).ravel())
            for material in materials:mesh.materials.append(material)
            mesh.polygons.foreach_set("material_index",assignment.astype(np.int32))
            for polygon in mesh.polygons:polygon.use_smooth=True
            mesh.normals_split_custom_set(normals[vertices].tolist())
            obj["strata_manifest"]=json.dumps(meta);obj["strata_units"]=meta["geometry"]["units"]
            bpy.context.scene.collection.children.link(collection)
            if meta["geometry"]["units"]=="m":bpy.context.scene.unit_settings.system="METRIC"
            return obj,meta
    except Exception:
        if obj is not None:
            mesh=obj.data;bpy.data.objects.remove(obj,do_unlink=True)
            if mesh.users==0:bpy.data.meshes.remove(mesh)
        if collection is not None:bpy.data.collections.remove(collection)
        for material in created_materials:bpy.data.materials.remove(material)
        for image in created_images:bpy.data.images.remove(image)
        raise


def render_scene(obj,output,size=512,samples=32):
    scene=bpy.context.scene;scene.render.engine="CYCLES";scene.cycles.samples=samples;scene.cycles.use_denoising=False
    points=[obj.matrix_world@Vector(corner) for corner in obj.bound_box];lo=Vector(tuple(min(p[i] for p in points) for i in range(3)));hi=Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center=(lo+hi)*.5;radius=max((hi-lo).length*.5,.001)
    camera_data=bpy.data.cameras.new("Strata render camera");camera=bpy.data.objects.new("Strata render camera",camera_data);scene.collection.objects.link(camera)
    camera.location=center+Vector((1.4,-2.5,1.2))*radius;camera.rotation_euler=(center-camera.location).to_track_quat("-Z","Y").to_euler();camera_data.clip_start=radius*.001;camera_data.clip_end=radius*100;scene.camera=camera
    light_data=bpy.data.lights.new("Strata key","AREA");light_data.energy=200*radius**2;light_data.size=radius*2
    light=bpy.data.objects.new("Strata key",light_data);scene.collection.objects.link(light);light.location=center+Vector((1,-2,3))*radius;light.rotation_euler=(center-light.location).to_track_quat("-Z","Y").to_euler()
    scene.world.use_nodes=True;scene.world.node_tree.nodes["Background"].inputs["Color"].default_value=(.15,.15,.15,1)
    scene.render.resolution_x=scene.render.resolution_y=size;scene.render.resolution_percentage=100
    scene.view_settings.view_transform="Standard";scene.render.image_settings.file_format="PNG";scene.render.filepath=str(Path(output).resolve())
    bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("bundle");parser.add_argument("--save");parser.add_argument("--render");parser.add_argument("--size",type=int,default=512);parser.add_argument("--samples",type=int,default=32)
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    if not 16<=args.size<=4096 or not 1<=args.samples<=1024:raise ValueError("Render limits: 16..4096 pixels and 1..1024 samples")
    if args.render:
        # The offline wrapper starts a fresh factory process; interactive import never deletes a scene.
        for obj in list(bpy.context.scene.objects):bpy.data.objects.remove(obj,do_unlink=True)
    obj,meta=import_bundle(args.bundle)
    if args.render:render_scene(obj,args.render,args.size,args.samples)
    if args.save:bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save).resolve()))
    print("STRATA_DELIVERY_RESULT "+json.dumps({"blender":bpy.app.version_string,"materials":len(meta["materials"]),"vertices":len(obj.data.vertices),"render":args.render,"saved":args.save}))

if __name__=="__main__":main()
