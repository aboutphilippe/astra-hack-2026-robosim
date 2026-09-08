import bpy,sys
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parent.parent
s=bpy.context.scene
for name,factor in [('Window daylight',.40),('Soft ceiling ambient',.38),('Near camera soft fill',.35)]:bpy.data.objects[name].data.energy*=factor
for name,color in [('Gray translucent roller blind',(.135,.16,.155,1)),('Structural steel warm charcoal',(.048,.049,.048,1)),('Steel edges',(.024,.026,.027,1))]:
    mat=bpy.data.materials[name];mat.diffuse_color=color;mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=color
s.view_settings.exposure=-.45
for name,offset in [('Nearest chair with jacket',(-.73,.05,0)),('Gray quilted jacket',(-.73,.05,0)),('Empty near desk chair',(-.30,0,0)),('Teal baseball cap',(-.30,0,0)),('Navy backpack',(-.57,.08,0)),('Taupe backpack',(-.88,.04,0)),('White shopping tote',(-.57,.04,0))]:
    ob=bpy.data.objects.get(name)
    if ob:ob.location+=Vector(offset)
    else:print('MISSING GROUP',name)
s.render.resolution_percentage=55;s.cycles.samples=16
cam=s.camera
for name,pos,lens in [('preview2',(-2.45,-3.85,3.0),32),('preview3',(-1.65,-3.45,2.85),31)]:
    cam.location=pos;cam.rotation_euler=(Vector((0,.10,.86))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=lens
    s.render.filepath=str(root/'output'/f'{name}.png');bpy.ops.render.render(write_still=True)
print('FURNITURE EMPTIES',[(ob.name,tuple(ob.location)) for ob in bpy.data.objects if ob.type=='EMPTY' and any(x in ob.name.lower() for x in ['jacket','tote','bag','chair'])])
