"""Build the fully editable, person-free reconstruction of IMG_2523.JPG."""
import bpy, sys, os, json, math, colorsys, argparse
from pathlib import Path
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from scene_utils import *
from architecture import build_architecture, build_tables
from furniture import build_furniture
from plant import build_plant
from tabletop import build_tabletop


def aim(obj, point):
    obj.rotation_euler=(Vector(point)-obj.location).to_track_quat('-Z','Y').to_euler()


def light(name, pos, target, power, size, color):
    data=bpy.data.lights.new(name,'AREA'); data.energy=power;data.shape='DISK';data.size=size;data.color=color
    ob=bpy.data.objects.new(name,data);collection('90 | Lighting and cameras').objects.link(ob);ob.location=pos;aim(ob,target)
    return ob


def configure_scene():
    scene=bpy.context.scene
    scene.unit_settings.system='METRIC'
    scene.render.engine='CYCLES'
    scene.cycles.samples=48
    scene.cycles.use_denoising=True
    scene.cycles.max_bounces=8
    scene.cycles.transparent_max_bounces=8
    scene.cycles.transmission_bounces=6
    try:
        prefs=bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type='METAL';prefs.get_devices()
        for device in prefs.devices:device.use=device.type=='METAL'
        scene.cycles.device='GPU'
    except Exception:
        scene.cycles.device='CPU'
    scene.render.resolution_x=1080;scene.render.resolution_y=1440;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.render.image_settings.color_mode='RGB'
    scene.render.image_settings.color_depth='8'
    scene.render.film_transparent=False
    scene.world.use_nodes=True
    scene.world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.68,.78,.86,1)
    scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.32
    scene.view_settings.view_transform='AgX'
    scene.view_settings.look='AgX - Medium High Contrast'
    scene.view_settings.exposure=-.45
    light('Window daylight',(-3.2,1.25,3.6),(0,-.25,.5),380,4.0,(.82,.92,1.0))
    light('Soft ceiling ambient',(.1,-.6,3.8),(0,0,.3),171,4.0,(1.0,.88,.73))
    light('Near camera soft fill',(-2.6,-3.7,2.7),(0,0,.8),63,3.4,(1.0,.94,.86))
    light('Exterior daylight',(-1.2,3.8,4.4),(-1,4.8,1.2),1200,4.0,(.84,.95,1))
    data=bpy.data.cameras.new('Photo matched camera')
    cam=bpy.data.objects.new('Camera | Reference composition',data);collection('90 | Lighting and cameras').objects.link(cam)
    cam.location=(-2.45,-3.85,3.0);aim(cam,(0,-.08,.34));data.lens=32;data.sensor_width=36;data.clip_end=100
    scene.camera=cam
    data.dof.use_dof=False
    # An extra camera offers a more open view of all table objects.
    data=bpy.data.cameras.new('Table inspection camera')
    other=bpy.data.objects.new('Camera | Table detail',data);collection('90 | Lighting and cameras').objects.link(other)
    other.location=(-2.65,-3.6,4.2);aim(other,(0,0,.73));data.lens=53
    bpy.context.view_layer.use_pass_cryptomatte_object=True
    bpy.context.view_layer.pass_cryptomatte_depth=6
    bpy.context.view_layer.use_pass_object_index=True
    scene['reference_image']='IMG_2523.JPG'
    scene['reconstruction_notes']='Single-photo geometric reconstruction. No people modeled. Occluded surfaces inferred. All physical instances named and segmented; each component remains editable.'
    scene['segmentation_manifest']='segmentation_manifest.json'
    return scene


def organize_and_manifest():
    groups={}
    type_names={
        'floor':'01 | Architecture', 'floor_plank':'01 | Architecture','wall':'01 | Architecture','ceiling':'01 | Architecture',
        'window_frame':'01 | Architecture','window_glass':'01 | Architecture','structural_column':'01 | Architecture','structural_beam':'01 | Architecture',
        'baseboard':'01 | Architecture','door':'01 | Architecture','door_frame':'01 | Architecture','roller_blind':'01 | Architecture',
        'exterior_building':'02 | Exterior context','exterior_window':'02 | Exterior context','exterior_frame':'02 | Exterior context',
        'exterior_louver':'02 | Exterior context','railing':'02 | Exterior context',
        'desk':'03 | Oak desks','cable_tray':'03 | Oak desks',
    }
    for ob in list(bpy.context.scene.objects):
        if ob.type not in {'MESH','CURVE','FONT','SURFACE','META'}:continue
        if 'instance_id' not in ob:
            segment(ob,ob.get('semantic_class','accessory'),ob.name)
        ident=str(ob['instance_id']); semantic=ob.get('semantic_class','accessory')
        if semantic in type_names:move_to(ob,type_names[semantic])
        groups.setdefault(ident,{'semantic_class':semantic,'objects':[]})['objects'].append(ob.name)
    manifest=[]
    used_colors=set()
    for idx,(ident,item) in enumerate(sorted(groups.items()),1):
        hue=(idx*.618033988749895)%1
        saturation=.50+((idx*17)%5)*.095
        value=.65+((idx*31)%5)*.07
        rgb=colorsys.hsv_to_rgb(hue,saturation,value)
        rgb8=[round(c*255) for c in rgb]
        while tuple(rgb8) in used_colors:
            rgb8=[(rgb8[0]+13)%256,(rgb8[1]+37)%256,(rgb8[2]+73)%256]
        used_colors.add(tuple(rgb8))
        rgb=[c/255 for c in rgb8]
        for name in item['objects']:
            ob=bpy.data.objects[name];ob.pass_index=idx;ob.color=(*rgb,1)
            ob['segmentation_index']=idx
            ob['segmentation_color_hex']='#'+''.join('%02x'%c for c in rgb8)
        manifest.append({'index':idx,'instance_id':ident,'semantic_class':item['semantic_class'],
                         'color_rgb':rgb8,'color_hex':'#'+''.join('%02x'%c for c in rgb8),'objects':item['objects']})
    out=ROOT/'output';out.mkdir(exist_ok=True)
    with open(out/'segmentation_manifest.json','w') as f:
        json.dump({'source':'IMG_2523.JPG','people_modeled':False,'units':'meters','instance_count':len(manifest),
                   'renderable_component_count':sum(len(item['objects']) for item in manifest),
                   'instances':manifest},f,indent=2)
    return manifest


def main():
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    for coll in list(bpy.data.collections):
        if coll.name=='Collection':coll.name='00 | Item groups and room details'
    print('BUILDING ARCHITECTURE',flush=True);build_architecture()
    for ob in bpy.data.objects:
        if ob.type in {'MESH','CURVE','FONT'} and ob.get('semantic_class')!='floor_plank' and ob.get('instance_id')!='floor_base':
            ob.location.x+=.80
    build_tables()
    print('BUILDING FURNITURE',flush=True);build_furniture()
    print('BUILDING PLANT',flush=True);plant=build_plant();plant.location.x+=.80
    print('BUILDING TABLETOP',flush=True);build_tabletop()
    # Refinements established by comparing the full render to the photograph.
    for name,offset in [('Nearest chair with jacket',(-1.30,-.20,0)),('Empty charcoal jacket draped on chair',(-1.30,-.20,0)),
                        ('Empty near desk chair',(-.85,0,0)),('Teal baseball cap',(-.85,0,0)),
                        ('Navy backpack',(-.92,.25,0)),('Taupe backpack',(-1.05,.22,0)),('White shopping tote',(-.82,.25,0))]:
        bpy.data.objects[name].location+=Vector(offset)
    for name,factor in [('Laptop_01_left',1.17),('Laptop_04_right',1.17),('Laptop_05_foreground',1.24),
                        ('Laptop_02_rear_left',1.12),('Laptop_03_rear_right',1.12)]:
        bpy.data.objects[name].scale=(factor,factor,factor)
    robot=bpy.data.objects.get('White_robot_arm_01')
    if robot:robot.scale=(1.3,1.3,1.3)
    scene=configure_scene()
    manifest=organize_and_manifest()
    for ob in bpy.context.selected_objects:ob.select_set(False)
    # Opening the file starts in the reference camera, with useful object-color segmentation available.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                area.spaces.active.region_3d.view_perspective='CAMERA'
                area.spaces.active.shading.type='MATERIAL'
                area.spaces.active.overlay.show_extras=False
    scene.render.filepath=str(ROOT/'output'/'recreated_scene.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'output'/'recreated_scene.blend'))
    print('BUILD_OK',len(manifest),'instances',len(bpy.data.objects),'objects',flush=True)
    if '--preview' in sys.argv:
        scene.render.resolution_percentage=55;scene.cycles.samples=16
        scene.render.filepath=str(ROOT/'output'/'preview.png')
        bpy.ops.render.render(write_still=True)


if __name__=='__main__':main()
