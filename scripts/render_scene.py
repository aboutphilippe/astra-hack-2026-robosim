"""Render the beauty image and a deterministic flat-color physical-instance map."""
import bpy, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
scene=bpy.context.scene
mode=sys.argv[sys.argv.index('--')+1] if '--' in sys.argv else 'beauty'
scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGB'
scene.render.image_settings.color_depth='8'
if mode=='segment':
    scene.render.dither_intensity=0
    mat=bpy.data.materials.new('Instance ID emission override');mat.use_nodes=True
    nt=mat.node_tree;nt.nodes.clear()
    info=nt.nodes.new('ShaderNodeObjectInfo');em=nt.nodes.new('ShaderNodeEmission');out=nt.nodes.new('ShaderNodeOutputMaterial')
    nt.links.new(info.outputs['Color'],em.inputs['Color']);nt.links.new(em.outputs[0],out.inputs['Surface'])
    bpy.context.view_layer.material_override=mat
    scene.view_settings.view_transform='Raw';scene.view_settings.look='None';scene.view_settings.exposure=0;scene.view_settings.gamma=1
    scene.cycles.samples=1;scene.cycles.use_denoising=False
    scene.render.filter_size=.01
    bpy.context.view_layer.use_pass_cryptomatte_object=False
    scene.render.filepath=str(ROOT/'output'/'instance_segmentation.png')
else:
    scene.cycles.samples=64
    scene.render.filepath=str(ROOT/'output'/'recreated_scene.png')
bpy.ops.render.render(write_still=True)
