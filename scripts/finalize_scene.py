import bpy,sys,json,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from build_scene import organize_and_manifest
s=bpy.context.scene
robot=bpy.data.objects['White_robot_arm_01'];robot.scale=(1.3,1.3,1.3)
manifest=organize_and_manifest()
renderable=[o for o in s.objects if o.type in {'MESH','CURVE','FONT','SURFACE','META'}]
assert all('instance_id' in o and 'semantic_class' in o and 'segmentation_index' in o for o in renderable)
assert len({tuple(i['color_rgb']) for i in manifest})==len(manifest)
counts=collections.Counter(i['semantic_class'] for i in manifest)
for key,count in [('laptop',5),('chess_piece',32),('chair',6),('desk',2),('robot_arm',1)]:assert counts[key]==count,(key,counts[key])
assert not any(x in counts for x in ['person','human','body','face'])
assert s.camera and s.camera.type=='CAMERA'
info={'valid':True,'blender_version':bpy.app.version_string,'physical_instances':len(manifest),
      'renderable_components':len(renderable),'all_components_segmented':True,'all_instance_colors_unique':True,
      'people_modeled':False,'semantic_counts':dict(sorted(counts.items()))}
(ROOT/'output'/'validation.json').write_text(json.dumps(info,indent=2))
text=bpy.data.texts.get('START HERE • Scene and segmentation') or bpy.data.texts.new('START HERE • Scene and segmentation')
text.clear();text.write((ROOT/'README.md').read_text())
s.render.resolution_percentage=100;s.cycles.samples=64
s.render.filepath=str(ROOT/'output'/'recreated_scene.png')
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'output'/'recreated_scene.blend'))
print(json.dumps(info),flush=True)
bpy.ops.render.render(write_still=True)
