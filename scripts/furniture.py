"""Individually segmented seating, bags and loose garments from IMG_2523."""
import bpy
import math
import random
from mathutils import Vector, Matrix
from scene_utils import material, cube, cylinder, sphere, tube, segment, collection, move_to, parent_group


def _smooth(obj):
    if obj.type == 'MESH':
        for p in obj.data.polygons:
            p.use_smooth = True
    return obj


def _mesh(name, verts, faces, mat, subdiv=0, thickness=0):
    mesh = bpy.data.meshes.new(name + '_mesh')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    ob = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(mat)
    if subdiv:
        mod = ob.modifiers.new('Soft cloth subdivision', 'SUBSURF')
        mod.levels = subdiv
        mod.render_levels = subdiv
    if thickness:
        mod = ob.modifiers.new('Fabric thickness', 'SOLIDIFY')
        mod.thickness = thickness
    return _smooth(ob)


def _fabric(name, color, rough=.83, weave=.2, scale=290):
    mat = material(name, color, roughness=rough)
    mat.use_nodes = True
    n = mat.node_tree.nodes
    l = mat.node_tree.links
    bs = n.get('Principled BSDF')
    tex = n.new('ShaderNodeTexNoise')
    tex.inputs['Scale'].default_value = scale
    tex.inputs['Detail'].default_value = 2
    bump = n.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = weave
    bump.inputs['Distance'].default_value = .002
    l.new(tex.outputs['Fac'], bump.inputs['Height'])
    l.new(bump.outputs['Normal'], bs.inputs['Normal'])
    if 'Sheen Weight' in bs.inputs:
        bs.inputs['Sheen Weight'].default_value = .15
    return mat


def _woven():
    mat = _fabric('Chair • warm gray basket-weave upholstery', (.43, .416, .37, 1), .92, .25, 490)
    n, l = mat.node_tree.nodes, mat.node_tree.links
    bs = n.get('Principled BSDF')
    coord = n.new('ShaderNodeTexCoord')
    a = n.new('ShaderNodeTexWave'); a.wave_type = 'BANDS'; a.bands_direction = 'X'
    b = n.new('ShaderNodeTexWave'); b.wave_type = 'BANDS'; b.bands_direction = 'Y'
    for wave in (a, b):
        wave.inputs['Scale'].default_value = 145
        wave.inputs['Distortion'].default_value = .25
        l.new(coord.outputs['Generated'], wave.inputs['Vector'])
    mix = n.new('ShaderNodeMixRGB'); mix.blend_type = 'MULTIPLY'; mix.inputs[0].default_value = 1
    l.new(a.outputs['Color'], mix.inputs[1]); l.new(b.outputs['Color'], mix.inputs[2])
    ramp = n.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = .1
    ramp.color_ramp.elements[0].color = (.285, .282, .25, 1)
    ramp.color_ramp.elements[1].position = .88
    ramp.color_ramp.elements[1].color = (.58, .55, .47, 1)
    l.new(mix.outputs[0], ramp.inputs[0]); l.new(ramp.outputs['Color'], bs.inputs['Base Color'])
    return mat


def _finish_since(existing, semantic, instance, label, loc=(0,0,0), rotation=0):
    bpy.context.view_layer.update()
    obs = [ob for ob in bpy.data.objects if ob not in existing]
    transform = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rotation, 4, 'Z')
    target = collection('06 • Chairs, bags and garments')
    for ob in obs:
        ob.matrix_world = transform @ ob.matrix_world
        segment(ob, semantic, instance)
        move_to(ob, target)
    parent_group(label, obs)
    return obs


def _rounded_outline(width, depth, z, radius=.04, y_offset=0):
    pts=[]
    for x,y,a0 in [(width/2-radius,depth/2-radius,0),(-width/2+radius,depth/2-radius,90),(-width/2+radius,-depth/2+radius,180),(width/2-radius,-depth/2+radius,270)]:
        for i in range(9):
            a=math.radians(a0+i*90/8)
            pts.append((x+radius*math.cos(a), y+y_offset+radius*math.sin(a),z))
    pts.append(pts[0])
    return pts


def _chair(label, instance, loc, angle, fabric, black, trim):
    before=set(bpy.data.objects)
    seat=cube(label+' | slim upholstered seat',(0,-.012,.464),(.493,.474,.036),fabric,bevel=.032)
    _smooth(seat)
    tube(label+' | seat perimeter piping',_rounded_outline(.489,.47,.478,.03,-.012),.0033,trim)
    # Thin, gently reclined panel, with visible black binding on the backrest.
    back=cube(label+' | upholstered back',(0,.244,.701),(.49,.032,.46),fabric,bevel=.026)
    back.rotation_euler.x=math.radians(-9)
    _smooth(back)
    # Elliptically rounded trim follows the full panel perimeter.
    pts=[]
    for x,z,a0 in [(.211,.89,0),(-.211,.89,90),(-.211,.506,180),(.211,.506,270)]:
        for i in range(9):
            a=math.radians(a0+i*90/8)
            xx=x+.031*math.cos(a); zz=z+.031*math.sin(a)
            yy=.244+(zz-.701)*math.tan(math.radians(9))-.016
            pts.append((xx,yy,zz))
    pts.append(pts[0]);tube(label+' | sewn backrest border',pts,.0034,trim)
    for side in [-1,1]:
        x=side*.257
        # Bent steel sled is a continuous U from front seat to floor and up back.
        pts=[(x,-.212,.452),(x,-.254,.40),(x,-.29,.09),(x,-.288,.042),(x,-.267,.024),(x,.289,.024),(x,.327,.039),(x,.331,.083),(x,.282,.43),(x,.245,.49),(x,.286,.867)]
        tube(label+f' | {side:+d} continuous sled frame',pts,.0125,black)
        cylinder(label+f' | front floor glide {side}',(x,-.258,.016),.017,.017,black,vertices=20)
        cylinder(label+f' | rear floor glide {side}',(x,.278,.016),.017,.017,black,vertices=20)
        for z in [.54,.83]:
            y=.244+(z-.701)*math.tan(math.radians(9))+.018
            dot=sphere(label+' | back fixing screw',(side*.218,y,z),(.005,.003,.005),black)
    tube(label+' | under-seat crossbar front',[(-.254,-.185,.435),(.254,-.185,.435)],.01,black)
    tube(label+' | under-seat crossbar rear',[(-.254,.17,.435),(.254,.17,.435)],.01,black)
    _finish_since(before,'chair',instance,label,loc,angle)


def _bag_body(name,width,depth,height,mat,center=(0,0,0)):
    # A fabric silhouette with a flattened bottom and rounded shoulders.
    verts=[];faces=[]
    zs=[0,.015,.05,.14,.28,.48,.68,.83,.93,.975,1]
    radii=[.72,.91,.98,1,1,1,.98,.91,.77,.52,.06]
    n=48
    for j,(z,r) in enumerate(zip(zs,radii)):
        for i in range(n):
            a=2*math.pi*i/n
            xx=math.copysign(abs(math.cos(a))**.63,math.cos(a))
            yy=math.copysign(abs(math.sin(a))**.65,math.sin(a))
            wrinkle=1+.016*math.sin(i*1.8+j*2)
            verts.append((center[0]+xx*width*.5*r*wrinkle,center[1]+yy*depth*.5*r,center[2]+z*height))
    for j in range(len(zs)-1):
        for i in range(n):
            k=j*n+i; q=j*n+(i+1)%n
            faces.append((k,q,q+n,k+n))
    faces.append(tuple(range(n-1,-1,-1)))
    faces.append(tuple((len(zs)-1)*n+i for i in range(n)))
    return _mesh(name,verts,faces,mat,2)


def _ribbon(name,points,width,mat,thickness=.006):
    # Padded woven ribbon: its narrow thickness makes it visibly empty.
    verts=[]; faces=[]
    for i,p in enumerate(points):
        pp=Vector(p)
        tangent=Vector(points[min(i+1,len(points)-1)])-Vector(points[max(0,i-1)])
        side=tangent.cross(Vector((0,1,0)))
        if side.length<.001: side=Vector((1,0,0))
        side.normalize()
        for t in [-1,-.76,0,.76,1]:
            v=pp+side*(width*.5*t)
            v.y-=.008*(1-t*t)
            verts.append(tuple(v))
    for j in range(len(points)-1):
        for i in range(4):
            k=j*5+i;faces.append((k,k+1,k+6,k+5))
    return _mesh(name,verts,faces,mat,2,thickness)


def _backpack(label,instance,loc,angle,color,taupe=False):
    before=set(bpy.data.objects)
    cloth=_fabric(label+' • nylon',color,.82,.13,230)
    seam=_fabric(label+' • dark binding',tuple(c*.65 for c in color[:3])+(1,),.87,.2,260)
    strap=_fabric(label+' • webbing',tuple(c*.84 for c in color[:3])+(1,),.88,.2,350)
    hardware=material(label+' • zipper metal',(.12,.14,.15,1),.3,.65)
    width=.39 if taupe else .36; height=.56 if taupe else .60; depth=.20 if taupe else .21
    _bag_body(label+' | main fabric shell',width,depth,height,cloth)
    # Main padded back, visible through the shoulder straps.
    pad=cube(label+' | padded back panel',(0,-depth*.48,height*.43),(width*.79,.018,height*.71),cloth,bevel=.05)
    _smooth(pad)
    face_seam=[(-width*.37,-depth*.53,.024),(-width*.45,-depth*.53,height*.15),(-width*.46,-depth*.52,height*.55),(-width*.38,-depth*.49,height*.82),(-width*.22,-depth*.40,height*.965),(0,-depth*.24,height*.993),(width*.22,-depth*.40,height*.965),(width*.38,-depth*.49,height*.82),(width*.46,-depth*.52,height*.55),(width*.45,-depth*.53,height*.15),(width*.37,-depth*.53,.024)]
    tube(label+' | stitched perimeter of padded back',face_seam,.0023,seam)
    tube(label+' | central back-panel seam',[(0,-depth*.59,height*.16),(0,-depth*.59,height*.40),(0,-depth*.57,height*.68)],.0013,seam)
    # Top and sides have a zipper opening, with paired stitching.
    arch=[(-width*.43,.025,.06),(-width*.48,.025,height*.46),(-width*.44,.025,height*.77),(-width*.30,.025,height*.94),(0,.025,height*1.003),(width*.30,.025,height*.94),(width*.44,.025,height*.77),(width*.48,.025,height*.46),(width*.43,.025,.06)]
    tube(label+' | long zipper track',arch,.004,seam)
    tube(label+' | long zipper piping',[(x,y+.006,z) for x,y,z in arch],.002,cloth)
    for side in [-1,1]:
        x=side*width*.29
        points=[(x*.81,-.076,height*.89),(x*.92,-.14,height*.78),(x*1.08,-.181,height*.61),(x*1.28,-.183,height*.41),(x*1.33,-.177,height*.28),(x*1.17,-.155,height*.15)]
        _ribbon(label+f' | shoulder strap {side}',points,.076 if taupe else .070,strap,.008)
        # Length adjustment webbing continues down to the bag corners.
        tail=[(x*1.17,-.155,height*.15),(x*1.3,-.152,.055),(x*1.45,-.14,.018),(x*1.80,-.22,.012),(x*2.15,-.27,.012)]
        _ribbon(label+f' | loose adjuster strap {side}',tail,.023,strap,.003)
        buckle=cube(label+' | rectangular strap buckle',(x*1.17,-.162,height*.155),(.043,.012,.027),hardware,bevel=.005)
        tube(label+' | stitched shoulder strap edge',[(xx+side*.022,yy-.007,zz) for xx,yy,zz in points],.0011,seam)
        _bag_body(label+f' | gusseted side pocket {side}',.075,.13,.21,cloth,(side*(width*.46),.005,.08))
        tube(label+' | elastic pocket lip',[(side*(width*.47)+.04*math.cos(a),.01+.05*math.sin(a),.272+.006*math.sin(a*2)) for a in [i*math.pi/12 for i in range(25)]],.003,seam)
    # Sturdy loop handle folds over the top.
    points=[(-.065,0,height*.94),(-.066,-.006,height*1.04),(-.045,-.012,height*1.09),(.045,-.012,height*1.09),(.066,-.006,height*1.04),(.065,0,height*.94)]
    handle_mat=_fabric(label+' • brown leather carry handle',(.20,.095,.034,1),.72,.08,120) if taupe else strap
    _ribbon(label+' | carry handle',points,.027,handle_mat,.004)
    for xx in [-.026,.026]:
        pull=cube(label+' | zipper slider',(xx,.018,height*.985),(.016,.015,.024),hardware,bevel=.004)
        tube(label+' | zipper pull loop',[(xx,.008,height*.98),(xx,.003,height*.945),(xx+.01,.003,height*.94),(xx+.01,.008,height*.977)],.0022,hardware)
    # Larger foreground silhouette, leaning back as in the reference.  The
    # shoulder straps remain on local -Y, facing the reconstruction camera.
    lean=math.radians(-15 if taupe else -9)
    bpy.context.view_layer.update()
    pose=Matrix.Translation(Vector((0,0,.032 if taupe else .022))) @ Matrix.Rotation(lean,4,'X') @ Matrix.Scale(1.25,4)
    for ob in [o for o in bpy.data.objects if o not in before]:
        if 'loose adjuster strap' in ob.name and ob.type=='MESH':
            # Free webbing lies on the floor even though the pack leans.
            for v in ob.data.vertices:
                old_z=v.co.z
                v.co=pose @ v.co
                if old_z<.027:
                    v.co.z=.008
        else:
            ob.matrix_world=pose @ ob.matrix_world
    _finish_since(before,'backpack',instance,label,loc,angle)


def _tote(loc):
    before=set(bpy.data.objects)
    cloth=_fabric('Shopping tote • wrinkled off-white nonwoven',(.83,.82,.75,1),.9,.14,160)
    orange=_fabric('Shopping tote • orange contents',(.95,.145,.014,1),.76,.1,140)
    edge=material('Shopping tote • stitched edge',(.55,.54,.48,1),.9)
    w=.37; d=.23; h=.39
    verts=[];faces=[];n=48;rows=13
    for j in range(rows):
        z=h*j/(rows-1)
        for i in range(n):
            a=2*math.pi*i/n
            xx=math.copysign(abs(math.cos(a))**.4,math.cos(a))
            yy=math.copysign(abs(math.sin(a))**.4,math.sin(a))
            taper=.80+.20*j/(rows-1)
            wr=.009*math.sin(i*1.7+j*.65)*math.sin(math.pi*j/(rows-1))
            verts.append((xx*w/2*taper+wr,yy*d/2*taper+wr,z+.019*(j/(rows-1))**5*math.sin(a*3)))
    for j in range(rows-1):
        for i in range(n):
            k=j*n+i;q=j*n+(i+1)%n;faces.append((k,q,q+n,k+n))
    faces.append(tuple(range(n-1,-1,-1)))
    _mesh('Tote | flexible open shopping bag',verts,faces,cloth,1,.003)
    tube('Tote | folded upper hem',verts[-n:]+[verts[-n]],.004,cloth)
    for sy in [-1,1]:
        pts=[(-.09,sy*.112,.37),(-.10,sy*.12,.46),(-.067,sy*.116,.51),(.045,sy*.116,.51),(.097,sy*.12,.46),(.09,sy*.112,.37)]
        _ribbon('Tote | soft loop handle',pts,.026,cloth,.003)
    random.seed(52)
    # A few collapsed fabric folds protrude inside the open mouth.
    for k in range(4):
        verts=[];faces=[]
        for j in range(9):
            for i in range(13):
                x=-.13+i*.022
                y=-.075+k*.045+(j/8-.5)*.054
                z=.285+.075*math.sin(i*.63+k)+.035*math.sin(j*.6+i*.27+k)
                verts.append((x,y,z))
        for j in range(8):
            for i in range(12):
                p=j*13+i;faces.append((p,p+1,p+14,p+13))
        _mesh('Tote | orange fabric fold '+str(k),verts,faces,orange,1,.002)
    # Fragment of the orange printed mark on front, kept as separate mesh ink.
    printmat=material('Tote • orange printed ink',(.9,.18,.065,1),.8)
    for x,z in [(-.105,.055),(-.075,.06),(-.045,.07),(-.015,.06),(.025,.075),(.06,.06)]:
        p=cube('Tote | orange print',(x,-.111,z),(.018,.001,.032),printmat,bevel=.003)
    _finish_since(before,'shopping_bag','shopping_tote_01','White shopping tote',loc,-.20)


def _sleeve(name,points,radii,mat,seammat):
    verts=[];faces=[];n=20
    for j,p in enumerate(points):
        tangent=Vector(points[min(j+1,len(points)-1)])-Vector(points[max(j-1,0)])
        tangent.normalize()
        ax=tangent.cross(Vector((0,1,0)))
        if ax.length<.01: ax=Vector((1,0,0))
        ax.normalize(); by=tangent.cross(ax).normalized()
        for i in range(n):
            a=2*math.pi*i/n
            puff=1+.12*math.sin(j*2)
            v=Vector(p)+ax*math.cos(a)*radii[j]*puff+by*math.sin(a)*radii[j]*.44*puff
            verts.append(tuple(v))
        if j%3==0 and j>0:
            ring=verts[-n:]+[verts[-n]]
            tube(name+' | quilted sleeve seam '+str(j),ring,.0018,seammat)
    for j in range(len(points)-1):
        for i in range(n):
            k=j*n+i;q=j*n+(i+1)%n;faces.append((k,q,q+n,k+n))
    # Open, collapsed cuffs; the sleeve contains no limb.
    _mesh(name,verts,faces,mat,2,.003)
    tube(name+' | cuff binding',verts[-n:]+[verts[-n]],.006,seammat)


def _jacket(loc,angle):
    before=set(bpy.data.objects)
    mat=_fabric('Jacket • charcoal nylon',(.195,.213,.228,1),.79,.065,220)
    seam=material('Jacket • quilting thread and binding',(.12,.137,.15,1),.88)
    # Flattened coat drapes over the chair back, then down the outside.
    # Mesh folds and stitched baffles follow gravity, leaving the jacket empty.
    nx=36;ny=64
    verts=[];faces=[]
    def point(u,v):
        width=.30-.035*math.sin(v*math.pi)
        x=u*width+.016*math.sin(v*5+u)
        if v<.22:
            a=v/.22
            y=.01+.30*a
            z=.71+.205*math.sin(a*math.pi*.5)
        else:
            a=(v-.22)/.78
            y=.31+.105*a+.025*math.sin(a*5)
            z=.915-.78*a
        # Broad down-filled baffles separated by narrow stitched troughs.
        baffle=(.5+.5*math.cos(v*math.pi*24))**1.3
        y+=.017*baffle+.009*math.sin(u*13+v*27)
        z+=.004*math.sin(u*16+v*28)
        x+=.005*math.sin(v*45+u*9)
        return(x,y,z)
    for j in range(ny+1):
        for i in range(nx+1):verts.append(point(i/nx*2-1,j/ny))
    for j in range(ny):
        for i in range(nx):
            k=j*(nx+1)+i;faces.append((k,k+1,k+nx+2,k+nx+1))
    _mesh('Jacket | folded quilted body',verts,faces,mat,1,.009)
    for v in [i/12 for i in range(1,12)]:
        pts=[point(i/40*2-1,v) for i in range(41)]
        pts=[(x,y+.003,z) for x,y,z in pts]
        tube('Jacket | horizontal baffle seam '+str(round(v,2)),pts,.0018,seam)
    for side in [-1,1]:
        tube('Jacket | side edge binding',[point(side,i/50) for i in range(51)],.004,seam)
    # The open folded collar rests at the top; it is not a neck or body.
    tube('Jacket | empty folded collar',[(-.115,.215,.879),(-.102,.25,.949),(-.05,.28,.969),(.058,.28,.956),(.105,.23,.91)],.016,mat)
    # One long sleeve falls toward floor, the other folds across the side.
    pts=[(-.26,.27,.85),(-.31,.26,.80),(-.34,.30,.71),(-.37,.35,.61),(-.41,.40,.50),(-.43,.43,.40),(-.43,.46,.29),(-.43,.49,.18),(-.40,.53,.09)]
    _sleeve('Jacket | left empty draped sleeve',pts,[.088,.084,.079,.076,.073,.07,.066,.061,.057],mat,seam)
    pts=[(.26,.23,.85),(.33,.23,.78),(.38,.19,.69),(.43,.14,.61),(.46,.04,.54),(.43,-.04,.50),(.38,-.11,.48)]
    _sleeve('Jacket | right empty folded sleeve',pts,[.09,.089,.085,.082,.077,.068,.059],mat,seam)
    # Slanted pocket zipper and a few dark snap details.
    tube('Jacket | pocket opening',[(.10,.398,.57),(.18,.412,.44)],.003,seam)
    for z in [.31,.53,.73]:
        p=sphere('Jacket | snap button',(.275,.409,z),(.008,.003,.008),seam)
    _finish_since(before,'jacket','jacket_01','Empty charcoal jacket draped on chair',loc,angle)


def _cap(loc):
    before=set(bpy.data.objects)
    cloth=_fabric('Cap • dusty teal cotton',(.018,.105,.135,1),.86,.11,230)
    thread=material('Cap • topstitch',(.038,.145,.165,1),.85)
    lettering=material('Cap • lime embroidery',(.67,.82,.12,1),.8)
    verts=[];faces=[];n=48;rings=14
    for j in range(rings):
        a=(.025+(math.pi/2-.025)*j/(rings-1))
        for i in range(n):
            t=2*math.pi*i/n
            verts.append((.093*math.sin(a)*math.cos(t),.106*math.sin(a)*math.sin(t),.106*math.cos(a)))
    for j in range(rings-1):
        for i in range(n):
            k=j*n+i;q=j*n+(i+1)%n;faces.append((k,q,q+n,k+n))
    _mesh('Cap | empty six-panel crown',verts,faces,cloth,1,.002)
    for k in range(6):
        t=k*math.pi/3
        pts=[]
        for j in range(15):
            a=.015+(math.pi/2-.015)*j/14
            pts.append((.094*math.sin(a)*math.cos(t),.107*math.sin(a)*math.sin(t),.107*math.cos(a)))
        tube('Cap | crown panel seam',pts,.0009,thread)
    sphere('Cap | top button',(0,0,.108),(.007,.007,.004),cloth)
    verts=[];faces=[]
    for j in range(9):
        for i in range(25):
            u=i/24*2-1;v=j/8
            x=u*(.081+.012*v)
            y=-.061-v*(.102*math.sqrt(max(.001,1-u*u)))
            z=-.004-.018*v+.015*u*u
            verts.append((x,y,z))
    for j in range(8):
        for i in range(24):
            k=j*25+i;faces.append((k,k+1,k+26,k+25))
    _mesh('Cap | curved projecting brim',verts,faces,cloth,1,.004)
    # Embroidery reads as small stitched lime letter fragments.
    for k in range(4):
        x=-.035+k*.023
        tube('Cap | embroidered mark',[(x,-.083,.058),(x+.007,-.09,.063),(x+.015,-.084,.058),(x+.005,-.088,.052)],.002,lettering)
    _finish_since(before,'baseball_cap','baseball_cap_01','Teal baseball cap',loc,-.9)


def build_furniture():
    fabric=_woven()
    black=material('Chair • satin black tubular steel',(.022,.029,.032,1),.39,.62)
    trim=_fabric('Chair • dark charcoal fabric piping',(.067,.071,.066,1),.87,.13,280)
    chairs=[('West occupied position', 'chair_01',(-1.38,.02,0),math.pi/2),
            ('Far left chair','chair_02',(-.56,1.22,0),0),
            ('Far right chair','chair_03',(.62,1.22,0),0),
            ('East occupied position','chair_04',(1.39,-.18,0),-math.pi/2),
            ('Empty near desk chair','chair_05',(-.28,-1.22,0),math.pi),
            ('Nearest chair with jacket','chair_06',(.92,-1.98,0),math.pi)]
    for label,instance,loc,angle in chairs:
        _chair(label,instance,loc,angle,fabric,black,trim)
    _backpack('Navy backpack','backpack_01',(-1.03,-1.54,.015),-.20,(.026,.052,.086,1))
    _backpack('Taupe backpack','backpack_02',(-.68,-2.03,.015),-.13,(.35,.325,.265,1),True)
    _tote((-.48,-1.52,.006))
    _jacket((.92,-1.98,0),math.pi)
    _cap((-.49,-1.49,.927))
