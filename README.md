# Segmented Blender reconstruction

Person-free geometric reconstruction of the room in `IMG_2523.JPG`.

## Unity + MuJoCo project

The **UnityProject** folder contains the reconstructed scene in Unity 6000.3.10f1 with the official MuJoCo 3.12.0 integration and matching macOS native library. Open **UnityProject/Assets/Scenes/ReconstructedRoom.unity** and press Play. The 32 chess pieces use native MuJoCo dynamics. The reconstructed arm is hidden and a named mount point is ready for your own robot model. See [Unity setup and controls](UnityProject/README.md) for the full project instructions and validation results.

Open `output/recreated_scene.blend` in Blender 5.2 or newer. The main camera is set to a portrait view inspired by the reference. The additional table-detail camera provides a closer inspection angle.

The scene includes the oak parquet floor, window mullions and shades, diagonal steel brace, room walls and recess, two oak desks, six woven chairs, five open laptops, a 32-piece chess set, white robot arm, articulated device mount, drinkware, electronics and cables, bags, empty loose garments, coat stand, and a multi-cane plant. No people, human meshes, or photographic cutouts are included. Dimensions and hidden surfaces are inferred from a single photograph.

## Delivered files

- `output/recreated_scene.blend` — editable scene, procedural materials, cameras, lighting.
- `output/recreated_scene.png` — finished portrait render.
- `output/instance_segmentation.png` — flat color image identifying physical instances.
- `output/segmentation_manifest.json` — maps each unique color/index to an instance, semantic class and its component objects.
- `output/validation.json` — integrity check and object counts.

## Object segmentation

Every renderable component remains a separate, named Blender object. Components belonging to one physical item share an `instance_id`, such as a laptop's keyboard and screen. Individual chess pieces, leaves, pebbles and parquet boards have their own instance IDs. Each component also stores `semantic_class`, `segmentation_index` and `segmentation_color_hex`, and its Blender object pass index matches the manifest. Object Cryptomatte and Object Index passes are enabled.

The segmentation image uses an opaque emission override. Transparent objects therefore receive their own opaque masks. Boundary pixels can contain antialiasing blends. To inspect colors interactively, use Solid viewport shading, then set Color Type to Object.

## Rebuild and render

From this folder, with Blender on your PATH:

```sh
blender --background --factory-startup --python scripts/build_scene.py
blender --background output/recreated_scene.blend --python scripts/render_scene.py -- beauty
blender --background output/recreated_scene.blend --python scripts/render_scene.py -- segment
```

All geometry and materials are generated locally by the included scripts. There are no external texture or add-on dependencies.
