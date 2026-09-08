"""Individually segmented sculptural indoor cane plant for the meeting room."""
import bpy
import math
import random
from mathutils import Vector
from scene_utils import material, cylinder, sphere, segment, collection, move_to, parent_group


def build_plant():
    rng = random.Random(2523)
    coll = collection("07 | Dracaena tree")
    origin = Vector((1.46, 1.74, 0.0))
    parts = []

    def reg(obj, semantic, ident):
        segment(obj, semantic, ident)
        move_to(obj, coll)
        parts.append(obj)
        return obj

    def mesh_obj(name, vertices, faces, mat, semantic, ident):
        mesh = bpy.data.meshes.new(name + " mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.materials.append(mat)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.collection.objects.link(obj)
        for poly in mesh.polygons:
            poly.use_smooth = True
        return reg(obj, semantic, ident)

    charcoal = material("Planter • warm charcoal ceramic", (0.047, 0.057, 0.060, 1), .58)
    gravelmat = material("Pale limestone gravel", (.49, .45, .34, 1), .92)
    gravel_light = material("Warm grey gravel", (.63, .58, .47, 1), .89)
    bark = material("Dracaena • pale fibrous bark", (.43, .34, .20, 1), .87)
    barkdark = material("Dracaena • healed leaf scars", (.29, .225, .13, 1), .93)
    bark_nodes = bark.node_tree.nodes
    bark_links = bark.node_tree.links
    bsdf = bark_nodes.get('Principled BSDF')
    texcoord = bark_nodes.new('ShaderNodeTexCoord')
    mapping = bark_nodes.new('ShaderNodeVectorMath')
    mapping.operation = 'MULTIPLY'
    mapping.inputs[1].default_value = (28, 28, 3)
    bark_links.new(texcoord.outputs['Generated'], mapping.inputs[0])
    noise = bark_nodes.new('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 6
    noise.inputs['Detail'].default_value = 3.5
    noise.inputs['Roughness'].default_value = .78
    bark_links.new(mapping.outputs['Vector'], noise.inputs['Vector'])
    ramp = bark_nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = .16
    ramp.color_ramp.elements[0].color = (.205, .147, .081, 1)
    ramp.color_ramp.elements[1].position = .8
    ramp.color_ramp.elements[1].color = (.62, .54, .38, 1)
    bark_links.new(noise.outputs['Fac'], ramp.inputs[0])
    bark_links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    bump = bark_nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .35
    bump.inputs['Distance'].default_value = .006
    bark_links.new(noise.outputs['Fac'], bump.inputs['Height'])
    bark_links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

    greens = []
    for i, rgb in enumerate([
        (.030, .095, .024), (.043, .123, .033), (.069, .155, .043),
        (.022, .071, .023), (.082, .173, .044), (.105, .205, .056),
        (.037, .108, .046), (.128, .219, .062),
    ]):
        # Deep glossy green as in the reference, with the fresh tips slightly lighter.
        rgb = tuple(c * (.63 if i >= 5 else .57) for c in rgb)
        mat = material("Dracaena leaf %02d" % i, (*rgb, 1), .51)
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        p = nodes.get('Principled BSDF')
        if 'Subsurface Weight' in p.inputs:
            p.inputs['Subsurface Weight'].default_value = .045
        tex = nodes.new('ShaderNodeTexNoise')
        tex.inputs['Scale'].default_value = 5.5
        tex.inputs['Detail'].default_value = 2
        ramp = nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = (*(c * .68 for c in rgb), 1)
        ramp.color_ramp.elements[1].color = (*(min(c * 1.32, 1) for c in rgb), 1)
        links.new(tex.outputs['Fac'], ramp.inputs['Fac'])
        links.new(ramp.outputs['Color'], p.inputs['Base Color'])
        greens.append(mat)

    # Revolved planter includes its visible rolled lip and inner wall.
    profile = [(.174, .014), (.191, .024), (.216, .102), (.239, .255),
               (.252, .470), (.258, .627), (.255, .666), (.242, .670),
               (.237, .645), (.231, .598), (.224, .565)]
    verts = []
    sides = 80
    for radius, height in profile:
        for j in range(sides):
            a = 2 * math.pi * j / sides
            verts.append(tuple(origin + Vector((radius * math.cos(a), radius * math.sin(a), height))))
    faces = []
    for k in range(len(profile) - 1):
        for j in range(sides):
            faces.append((k * sides + j, k * sides + (j + 1) % sides,
                          (k + 1) * sides + (j + 1) % sides, (k + 1) * sides + j))
    faces.append(tuple(reversed(range(sides))))
    mesh_obj("Planter | tall charcoal tapered vessel", verts, faces, charcoal, "planter", "plant_planter_01")
    soil = cylinder("Planter | pebble substrate", origin + Vector((0, 0, .630)), .235, .028, gravelmat, 64)
    reg(soil, "plant_substrate", "plant_substrate_01")

    # Pebbles are distinct objects so selections and instance segmentation remain usable.
    for i in range(115):
        a = rng.uniform(0, 2 * math.pi)
        r = .228 * math.sqrt(rng.random())
        sz = rng.uniform(.006, .015)
        peb = sphere("Limestone pebble %03d" % (i + 1), origin + Vector((r * math.cos(a), r * math.sin(a), .644 + rng.uniform(0, .006))),
                     (sz, sz * rng.uniform(.68, 1.10), sz * .58), gravelmat if i % 3 else gravel_light)
        reg(peb, "pebble", "plant_pebble_%03d" % (i + 1))

    def cane(name, points, radii, ident):
        points = [origin + Vector(p) for p in points]
        vertices, faces = [], []
        n = 13
        for k, center in enumerate(points):
            tangent = points[min(k + 1, len(points) - 1)] - points[max(0, k - 1)]
            tangent.normalize()
            u = tangent.cross(Vector((0, 1, 0))).normalized()
            v = tangent.cross(u).normalized()
            for j in range(n):
                angle = 2 * math.pi * j / n
                radial = radii[k] * (1 + .07 * math.sin(j * 3.8 + k * .9))
                vertices.append(tuple(center + radial * (u * math.cos(angle) + v * math.sin(angle))))
        for k in range(len(points) - 1):
            for j in range(n):
                faces.append((k * n + j, k * n + (j + 1) % n, (k + 1) * n + (j + 1) % n, (k + 1) * n + j))
        faces.append(tuple(range(n - 1, -1, -1)))
        faces.append(tuple((len(points) - 1) * n + j for j in range(n)))
        return mesh_obj(name, vertices, faces, bark, "plant_trunk", ident)

    trunks = [
        ([(-.074, -.005, .625), (-.080, .011, .96), (-.047, .008, 1.33), (-.065, .007, 1.68), (-.035, .003, 2.16)], [.040, .034, .028, .023, .016]),
        ([(.015, -.035, .627), (.070, -.027, .95), (.090, -.041, 1.24), (.183, -.052, 1.62), (.190, -.040, 2.02)], [.043, .038, .030, .025, .016]),
        ([(-.110, .056, .625), (-.135, .08, .91), (-.154, .061, 1.23), (-.205, .040, 1.64), (-.218, .041, 1.95)], [.026, .025, .022, .018, .011]),
        ([(.041, .079, .625), (.070, .102, 1.03), (.010, .115, 1.42), (.038, .099, 1.89), (.062, .102, 2.28)], [.031, .030, .022, .019, .012]),
        ([(.076, -.024, .631), (.125, -.041, .89), (.068, -.117, 1.15), (.076, -.176, 1.51)], [.025, .024, .020, .012]),
    ]
    for i, (pts, radii) in enumerate(trunks):
        cane("Cane trunk %02d" % (i + 1), pts, radii, "plant_trunk_%02d" % (i + 1))
    branches = [
        ([(-.062, .008, 1.60), (-.181, -.041, 1.77), (-.306, -.080, 1.90)], [.023, .017, .009]),
        ([(.170, -.044, 1.64), (.315, -.011, 1.79), (.338, .0, 1.91)], [.023, .015, .010]),
        ([(.033, .11, 1.79), (.150, .210, 2.04), (.170, .229, 2.17)], [.018, .013, .009]),
        ([(-.209, .043, 1.80), (-.280, .211, 1.95), (-.31, .250, 2.05)], [.017, .012, .008]),
        ([(-.034, .008, 2.03), (-.113, -.126, 2.19), (-.149, -.159, 2.29)], [.017, .010, .006]),
        ([(.100, -.151, 1.41), (.225, -.214, 1.56), (.253, -.234, 1.66)], [.018, .012, .007]),
        ([(-.05, .008, 1.47), (-.163, -.092, 1.62), (-.196, -.144, 1.72)], [.021, .013, .008]),
    ]
    for i, (pts, radii) in enumerate(branches):
        cane("Cane branch %02d" % (i + 1), pts, radii, "plant_branch_%02d" % (i + 1))

    # Brown healed collar rings, not an artificially smooth plastic stem.
    for i in range(29):
        ti = i % 5
        pts, radii = trunks[ti]
        f = rng.uniform(.06, .95) * (len(pts) - 1)
        k = min(int(f), len(pts) - 2)
        t = f - k
        p = Vector(pts[k]).lerp(Vector(pts[k + 1]), t)
        r = radii[k] * (1 - t) + radii[k + 1] * t
        collar = cylinder("Cane leaf scar %02d" % (i + 1), origin + p, r * 1.028, .003, barkdark, 13)
        reg(collar, "plant_bark_scar", "plant_scar_%02d" % (i + 1))

    rosettes = [pts[-1] for pts, radii in trunks] + [pts[-1] for pts, radii in branches]
    leaf_id = 0

    def leaf(center, theta, length, width, rise, droop, material_index, curl):
        nonlocal leaf_id
        leaf_id += 1
        base = origin + Vector(center)
        direction = Vector((math.cos(theta), math.sin(theta), 0))
        sideways = Vector((-math.sin(theta), math.cos(theta), 0))
        verts, faces = [], []
        nr, nc = 21, 5
        for k in range(nr):
            t = k / (nr - 1)
            x = length * (.77 * t + .23 * math.sin(t * math.pi / 2))
            z = rise * math.sin(t * math.pi * .85) - droop * t ** 2.1
            offset = sideways * (curl * math.sin(math.pi * t) * t)
            mid = base + direction * x + Vector((0, 0, z)) + offset
            halfwidth = width * .5 * max(.012, math.sin(math.pi * t) ** .70) * (1 + .07 * math.sin(t * 18 + theta))
            twist = math.sin(t * math.pi * 1.2 + theta) * .22 + curl * 2.0 * t
            across = sideways * math.cos(twist) + Vector((0, 0, math.sin(twist)))
            for j in range(nc):
                s = (j / (nc - 1)) * 2 - 1
                fold = .008 * (1 - abs(s)) * math.sin(t * math.pi) - .005 * abs(s) ** 2 * math.sin(t * math.pi)
                rippling = .0035 * math.sin(t * 24 + theta) * abs(s) ** 3 * math.sin(math.pi * t)
                verts.append(tuple(mid + across * halfwidth * s + Vector((0, 0, fold + rippling))))
        for k in range(nr - 1):
            for j in range(nc - 1):
                a = k * nc + j
                faces.append((a, a + 1, a + 1 + nc, a + nc))
        obj = mesh_obj("Dracaena leaf %03d" % leaf_id, verts, faces, greens[material_index], "plant_leaf", "plant_leaf_%03d" % leaf_id)
        solid = obj.modifiers.new("Leaf membrane", 'SOLIDIFY')
        solid.thickness = .0008
        obj["rosette_origin"] = tuple(center)
        return obj

    for ri, center in enumerate(rosettes):
        phase = rng.uniform(0, 2 * math.pi)
        count = 20 if ri < 4 else 15
        for j in range(count):
            theta = phase + j * 2.399963 + rng.uniform(-.20, .20)
            level = j % 4
            length = rng.uniform(.31, .49) * (1.0 if ri < 4 else .90)
            width = rng.uniform(.047, .073) * 1.25
            rise = rng.uniform(.08, .19)
            droop = rng.uniform(.14, .29)
            if level == 3:
                length *= .70
                rise = rng.uniform(.20, .32)
                droop *= .32
            if level == 0:
                rise *= .55
            if j % 5 == 2:
                # Broad mature leaves extend more horizontally through the canopy.
                # These offset the hanging ribbons and give the dense tree its bulk.
                width *= 1.10
                length *= 1.05
                rise *= .80
                droop *= .58
            shifted = (center[0], center[1], center[2] + rng.uniform(-.055, .050))
            leaf(shifted, theta, length, width, rise, droop, rng.randrange(7), rng.uniform(-.06, .06))
        # An upright pair of lighter emerging blades at every growing point.
        for j in range(2):
            leaf(center, phase + j * 1.91, rng.uniform(.14, .23), .049,
                 rng.uniform(.24, .31), .012, 7 if j else 5, .022)

    root = parent_group("Dracaena | fully segmented tree", parts)
    root["semantic_class"] = "plant"
    root["instance_id"] = "plant_01"
    root["description"] = "Cane plant with separate planter, pebbles, pale trunks, branches and individual ribbon leaves"
    move_to(root, coll)
    return root
