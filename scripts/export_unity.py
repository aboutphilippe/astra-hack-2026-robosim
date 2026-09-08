"""Create an evaluated, segmented FBX and portable material metadata for Unity.

Run with Blender --background output/recreated_scene.blend --python scripts/export_unity.py.
Never saves changes to the source .blend. Every source renderable remains a separate
named mesh, under an instance empty, with original names retained in a JSON sidecar.
"""
import bpy
import json
import math
import shutil
import struct
import zlib
from pathlib import Path

import numpy as np
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'UnityProject/Assets/Reconstruction/Source'
TEXTURES = ROOT / 'UnityProject/Assets/Reconstruction/Textures'
SOURCE.mkdir(parents=True, exist_ok=True)
TEXTURES.mkdir(parents=True, exist_ok=True)


def unity(v):
    return [float(v[0]), float(v[2]), float(v[1])]


def bounds(points):
    a = np.asarray(points, dtype=np.float64)
    return {'min': a.min(axis=0).tolist(), 'max': a.max(axis=0).tolist()}


def png_rgb(path, linear):
    """Write an ordinary sRGB PNG without depending on non-bundled Python packages."""
    rgb = np.clip(linear, 0, 1)
    srgb = np.where(rgb <= .0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - .055)
    data = np.uint8(np.clip(np.rint(srgb * 255), 0, 255))
    height, width, _ = data.shape
    raw = b''.join(b'\x00' + row.tobytes() for row in data)
    def chunk(kind, value):
        return struct.pack('!I', len(value)) + kind + value + struct.pack('!I', zlib.crc32(kind + value) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'sRGB', b'\x00') + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def material_texture(mat, portable_name, color):
    """Portable UV textures approximate the reference procedural wood and cloth."""
    name = mat.name.lower()
    nodes = mat.node_tree.nodes if mat.use_nodes else []
    ramps = [n for n in nodes if n.type == 'VALTORGB']
    is_wood = any(word in name for word in ('oak', 'walnut', 'bark'))
    is_fabric = any(word in name for word in ('fabric', 'nylon', 'weave', 'webbing', 'cotton', 'roller blind', 'nonwoven'))
    is_leaf = 'dracaena leaf' in name
    if not (is_wood or is_fabric or is_leaf):
        return '', 'none'
    size = 1024 if is_wood else 512
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    rng = np.random.default_rng(sum(map(ord, mat.name)))
    if ramps:
        dark = np.array(ramps[0].color_ramp.elements[0].color[:3])
        light = np.array(ramps[0].color_ramp.elements[-1].color[:3])
    else:
        dark = np.array(color[:3]) * .84
        light = np.array(color[:3]) * 1.13
    if is_wood:
        # Grain runs along the U axis. Warp it over several octaves so the image
        # reads as timber, with individually colored planks retained in the FBX.
        warp = .12 * np.sin(x * math.tau * 1.4) + .05 * np.sin(x * math.tau * 3.1 + y * 3)
        a = .5 + .5 * np.sin((y * 39 + warp) * math.tau)
        b = .5 + .5 * np.sin((y * 111 + warp * 2.8 + .25 * np.sin(x * 8)) * math.tau)
        c = .5 + .5 * np.sin((y * 13 + .16 * np.sin(x * 5.7 + y * 2)) * math.tau)
        noise = rng.random((size, size), dtype=np.float32)
        fac = np.clip(.28 + .25*a + .16*b + .20*c + .07*noise, 0, 1)
        kind = 'wood'
    elif is_leaf:
        fac = np.clip(.46 + .13*np.sin(x*12+y*3) + .09*np.sin(y*23-x*5) + .07*rng.random((size,size)), 0, 1)
        kind = 'leaf'
    else:
        # Each tile holds 16 warp and weft threads; UVs repeat at physical scale.
        sx, sy = np.sin(x * math.tau * 16), np.sin(y * math.tau * 16)
        checker = ((np.floor(x*16) + np.floor(y*16)) % 2)
        fac = np.clip(.27 + .25*(sx*.5+.5)*(1-checker) + .25*(sy*.5+.5)*checker + .17*rng.random((size,size)), 0, 1)
        kind = 'fabric'
    rgb = dark[None,None,:] + (light-dark)[None,None,:] * fac[:,:,None]
    path = TEXTURES / (portable_name + '_albedo.png')
    png_rgb(path, rgb)
    return 'Assets/Reconstruction/Textures/' + path.name, kind


def portable_materials():
    result, lookup, kinds = [], {}, {}
    for i, original in enumerate(sorted(bpy.data.materials, key=lambda m: m.name), 1):
        if original.users == 0:
            continue
        name = f'material_{i:04d}'
        bs = original.node_tree.nodes.get('Principled BSDF') if original.use_nodes else None
        def value(key, default):
            return bs.inputs[key].default_value if bs and key in bs.inputs else default
        color = list(value('Base Color', original.diffuse_color))
        roughness = float(value('Roughness', .5))
        metallic = float(value('Metallic', 0))
        transmission = float(value('Transmission Weight', 0))
        emission = list(value('Emission Color', (0, 0, 0, 1)))[:3]
        emission_strength = float(value('Emission Strength', 0))
        texture, kind = material_texture(original, name, color)
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        shader = mat.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Roughness'].default_value = roughness
        shader.inputs['Metallic'].default_value = metallic
        shader.inputs['Transmission Weight'].default_value = transmission
        shader.inputs['Emission Color'].default_value = (*emission, 1)
        shader.inputs['Emission Strength'].default_value = emission_strength
        mat.diffuse_color = color
        if texture:
            image = bpy.data.images.load(str(ROOT / 'UnityProject' / texture), check_existing=True)
            node = mat.node_tree.nodes.new('ShaderNodeTexImage')
            node.image = image
            mat.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
        lookup[original.name] = mat
        kinds[name] = kind
        result.append({'name': name, 'original_name': original.name,
                       'base_color_linear': [1,1,1,color[3]] if texture else color,
                       'original_color_linear': color, 'roughness': roughness,
                       'metallic': metallic, 'transmission': transmission,
                       'emission_color_linear': emission, 'emission_strength': emission_strength,
                       'texture_path': texture, 'texture_kind': kind,
                       'double_sided': ('leaf' in original.name.lower() or kind == 'fabric')})
    return result, lookup, kinds


def assign_uv(mesh, kinds, dimensions, name):
    if not mesh.vertices:
        return
    uv = mesh.uv_layers.active or mesh.uv_layers.new(name='UVMap')
    verts = np.array([v.co[:] for v in mesh.vertices], dtype=np.float64)
    low, high = verts.min(axis=0), verts.max(axis=0)
    span = np.maximum(high-low, .000001)
    coords = (verts-low) / span
    for poly in mesh.polygons:
        mat = mesh.materials[poly.material_index] if mesh.materials and poly.material_index < len(mesh.materials) else None
        kind = kinds.get(mat.name, 'none') if mat else 'none'
        if kind == 'none':
            continue
        normal = np.abs(poly.normal[:])
        axes = [a for a in range(3) if a != int(normal.argmax())]
        if kind == 'wood':
            # Match modeled timber direction: table/planks local X, doors Z.
            primary = 2 if ('door' in name.lower() or 'trunk' in name.lower()) else 0
            if primary in axes and axes[0] != primary:
                axes.reverse()
        for loop_index in poly.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            p = coords[vertex_index]
            if kind == 'fabric':
                q = p * np.array(dimensions) * 38
            else:
                q = p
            uv.data[loop_index].uv = (float(q[axes[0]]), float(q[axes[1]]))


def main():
    source_scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    original_objects = sorted([o for o in source_scene.objects if o.type in {'MESH','CURVE','FONT','SURFACE','META'}], key=lambda o:o.name)
    source_manifest = json.loads((ROOT/'output/segmentation_manifest.json').read_text())
    assert len(original_objects) == source_manifest['renderable_component_count'] == 3538
    assert source_manifest['instance_count'] == 1025
    assert all('instance_id' in o and 'segmentation_index' in o for o in original_objects)
    materials, mat_lookup, mat_kinds = portable_materials()
    cameras = []
    for cam in [o for o in source_scene.objects if o.type == 'CAMERA']:
        matrix = cam.matrix_world.to_3x3()
        projection = cam.calc_matrix_camera(depsgraph, x=source_scene.render.resolution_x, y=source_scene.render.resolution_y, scale_x=source_scene.render.pixel_aspect_x, scale_y=source_scene.render.pixel_aspect_y)
        cameras.append({'name':cam.name,'position_unity':unity(cam.matrix_world.translation),
                        'forward_unity':unity(matrix@Vector((0,0,-1))), 'up_unity':unity(matrix@Vector((0,1,0))),
                        'lens_mm':cam.data.lens, 'sensor_width_mm':cam.data.sensor_width,
                        'fov_vertical_deg':math.degrees(2*math.atan(1/projection[1][1])),
                        'active':cam == source_scene.camera})
    lights = [{'name':o.name,'type':o.data.type,'position_unity':unity(o.matrix_world.translation),
               'forward_unity':unity(o.matrix_world.to_3x3()@Vector((0,0,-1))),
               'color_linear':list(o.data.color), 'energy':o.data.energy,'size':getattr(o.data,'size',0)}
              for o in source_scene.objects if o.type=='LIGHT']
    export_collection = bpy.data.collections.new('UNITY_EXPORT_ONLY')
    source_scene.collection.children.link(export_collection)
    groups, instances = {}, []
    for instance in source_manifest['instances']:
        index = int(instance['index'])
        group_name = f'instance_{index:06d}'
        group = bpy.data.objects.new(group_name, None)
        group['instance_id'] = instance['instance_id']
        group['semantic_class'] = instance['semantic_class']
        group['segmentation_index'] = index
        export_collection.objects.link(group)
        groups[instance['instance_id']] = group
        instances.append({'instance_id':instance['instance_id'], 'index':index,
                          'semantic_class':instance['semantic_class'], 'color_rgb':instance['color_rgb'],
                          'export_group':group_name,'component_names':[]})
    instance_lookup = {item['instance_id']:item for item in instances}
    components, export_objects, scene_points = [], list(groups.values()), []
    total_vertices = total_triangles = 0
    for i, original in enumerate(original_objects, 1):
        name = f'component_{i:06d}'
        evaluated = original.evaluated_get(depsgraph)
        mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
        assert mesh and len(mesh.vertices), f'Empty evaluated geometry: {original.name}'
        mesh.name = name + '_mesh'
        original_material_names = [m.name if m else '' for m in mesh.materials]
        mesh.materials.clear()
        for mat_name in original_material_names:
            if mat_name in mat_lookup:
                mesh.materials.append(mat_lookup[mat_name])
        assign_uv(mesh, mat_kinds, original.dimensions, original.name)
        # Store geometry in world coordinates: every instance and component is
        # identity, so all groups can be reconstructed without opaque parent pivots.
        mesh.transform(original.matrix_world)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        export_collection.objects.link(obj)
        instance_id = str(original['instance_id'])
        obj.parent = groups[instance_id]
        obj['instance_id'] = instance_id
        obj['segmentation_index'] = int(original['segmentation_index'])
        obj['semantic_class'] = original['semantic_class']
        obj['source_object_name'] = original.name
        points = [unity(v.co) for v in mesh.vertices]
        b = bounds(points)
        scene_points.extend((b['min'], b['max']))
        mesh.calc_loop_triangles()
        total_vertices += len(mesh.vertices)
        total_triangles += len(mesh.loop_triangles)
        components.append({'export_name':name, 'original_name':original.name,
                           'instance_id':instance_id, 'segmentation_index':int(original['segmentation_index']),
                           'semantic_class':original['semantic_class'], 'group_name':groups[instance_id].name,
                           'bounds_unity':b, 'materials':[m.name for m in mesh.materials],
                           'vertex_count':len(mesh.vertices),'triangle_count':len(mesh.loop_triangles),
                           'source_type':original.type})
        instance_lookup[instance_id]['component_names'].append(name)
        export_objects.append(obj)
        if i % 250 == 0:
            print(f'CONVERTED {i}/{len(original_objects)}', flush=True)
    metadata = {'schema_version':1, 'source_image':'IMG_2523.JPG','source_blend':'output/recreated_scene.blend',
                'people_modeled':False,'units':'meters','coordinate_mapping':'Blender(x,y,z) -> Unity(x,z,y)',
                'fbx_axis_forward':'-Z','fbx_axis_up':'Y','fbx_bake_space_transform':True,
                'geometry_transforms':'Vertices baked to source world; component and group transforms identity.',
                'component_count':len(components),'instance_count':len(instances),
                'components':components,'instances':instances,'materials':materials,'cameras':cameras,'lights':lights,
                'scene_bounds_unity':bounds(scene_points),
                'render_resolution':[source_scene.render.resolution_x,source_scene.render.resolution_y],
                'material_note':'Procedural timber, bark, leaf, and cloth color translated into portable sRGB PNG approximations; geometry and segmentation preserved.'}
    (SOURCE/'scene_metadata.json').write_text(json.dumps(metadata,indent=2))
    shutil.copyfile(ROOT/'output/segmentation_manifest.json', SOURCE/'segmentation_manifest.json')
    print('METADATA_READY',str(SOURCE/'scene_metadata.json'),flush=True)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in export_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = export_objects[-1]
    path = SOURCE/'reconstructed_scene.fbx'
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True,
                             object_types={'MESH','EMPTY'}, axis_forward='-Z',axis_up='Y',
                             global_scale=1.0,apply_unit_scale=True,apply_scale_options='FBX_SCALE_UNITS',
                             use_space_transform=True,bake_space_transform=True,
                             use_mesh_modifiers=False,mesh_smooth_type='FACE',
                             use_mesh_edges=False,use_tspace=False,use_custom_props=True,
                             add_leaf_bones=False,bake_anim=False,path_mode='RELATIVE',embed_textures=False)
    report = {'success':True,'blender_version':bpy.app.version_string,'fbx':str(path),
              'metadata':str(SOURCE/'scene_metadata.json'),'components':len(components),
              'instances':len(instances),'vertices':total_vertices,'triangles':total_triangles,
              'materials':len(materials),'portable_textures':sum(bool(m['texture_path']) for m in materials),
              'fbx_bytes':path.stat().st_size,'people_modeled':False,
              'source_types':{t:sum(c['source_type']==t for c in components) for t in sorted({c['source_type'] for c in components})}}
    (ROOT/'output/unity_export_report.json').write_text(json.dumps(report,indent=2))
    print('UNITY_EXPORT_OK',json.dumps(report),flush=True)


if __name__ == '__main__':
    main()
