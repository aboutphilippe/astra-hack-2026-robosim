import bpy
import math
from mathutils import Vector


def material(name, color, roughness=.5, metallic=0):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    rgba = tuple(color) if len(color) == 4 else (*color, 1)
    mat.diffuse_color = rgba
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = rgba
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    return mat


def finish(obj, name, mat):
    obj.name = name
    if mat is not None:
        obj.data.materials.append(mat)
    return obj


def cube(name, location, scale, mat, bevel=0):
    x,y,z=(v*.5 for v in scale)
    verts=[(-x,-y,-z),(-x,-y,z),(-x,y,-z),(-x,y,z),(x,-y,-z),(x,-y,z),(x,y,-z),(x,y,z)]
    faces=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
    mesh=bpy.data.meshes.new(name+' mesh');mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);obj.location=location
    finish(obj, name, mat)
    if bevel:
        mod = obj.modifiers.new('Soft manufactured edges', 'BEVEL')
        mod.width = bevel
        mod.segments = 3
        mod = obj.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
    return obj


def cylinder(name, location, radius, depth, mat, vertices=32):
    n=vertices
    verts=[(radius*math.cos(i*math.tau/n),radius*math.sin(i*math.tau/n),z) for z in [-depth/2,depth/2] for i in range(n)]
    faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
    faces.extend((i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n))
    mesh=bpy.data.meshes.new(name+' mesh');mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);obj.location=location
    finish(obj,name,mat)
    for face in obj.data.polygons:
        face.use_smooth = len(face.vertices) == 4
    bevel = obj.modifiers.new('Edge highlights', 'BEVEL')
    bevel.width = min(.003, depth*.1, radius*.1)
    bevel.segments = 2
    obj.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    return obj


def sphere(name, location, scale, mat):
    n=20;rings=12
    verts=[(0,0,1)]
    verts.extend((math.sin(j*math.pi/rings)*math.cos(i*math.tau/n),math.sin(j*math.pi/rings)*math.sin(i*math.tau/n),math.cos(j*math.pi/rings)) for j in range(1,rings) for i in range(n))
    verts.append((0,0,-1));bottom=len(verts)-1
    faces=[(0,1+i,1+(i+1)%n) for i in range(n)]
    for j in range(rings-2):
        a=1+j*n
        faces.extend((a+i,a+n+i,a+n+(i+1)%n,a+(i+1)%n) for i in range(n))
    a=1+(rings-2)*n
    faces.extend((a+i,bottom,a+(i+1)%n) for i in range(n))
    mesh=bpy.data.meshes.new(name+' mesh');mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);obj.location=location
    finish(obj,name,mat)
    obj.scale = scale
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def tube(name, points, radius, mat):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    curve.resolution_u = 12
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new('BEZIER')
    spline.bezier_points.add(len(points)-1)
    for bp, co in zip(spline.bezier_points, points):
        bp.co = co
        bp.handle_left_type = 'AUTO'
        bp.handle_right_type = 'AUTO'
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    return finish(obj, name, mat)


def segment(obj, semantic, instance):
    obj['semantic_class'] = semantic
    obj['instance_id'] = str(instance)
    return obj


def collection(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def move_to(obj, coll):
    if isinstance(coll, str):
        coll = collection(coll)
    for existing in list(obj.users_collection):
        existing.objects.unlink(obj)
    coll.objects.link(obj)
    return obj


def parent_group(name, objects):
    bpy.context.view_layer.update()
    parent = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(parent)
    for obj in objects:
        world = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_world = world
    return parent


def rod_between(name, start, end, radius, mat):
    a, b = Vector(start), Vector(end)
    obj = cylinder(name, (a+b)*.5, radius, (b-a).length, mat)
    obj.rotation_euler = (b-a).to_track_quat('Z', 'Y').to_euler()
    return obj
