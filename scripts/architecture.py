import bpy, math, random
from mathutils import Vector
from scene_utils import *


def wood(name, light, dark, direction=(3,80,4)):
    mat = material(name, light, .48)
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    tex = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeVectorMath'); mapping.operation='MULTIPLY'
    mapping.inputs[1].default_value=direction
    links.new(tex.outputs['Generated'],mapping.inputs[0])
    noise=nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value=3
    noise.inputs['Detail'].default_value=3.5; noise.inputs['Roughness'].default_value=.72
    links.new(mapping.outputs[0],noise.inputs['Vector'])
    ramp=nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position=.23; ramp.color_ramp.elements[0].color=(*dark,1)
    ramp.color_ramp.elements[1].position=.79; ramp.color_ramp.elements[1].color=(*light,1)
    links.new(noise.outputs['Fac'],ramp.inputs[0])
    bs=nodes.get('Principled BSDF'); links.new(ramp.outputs[0],bs.inputs['Base Color'])
    bump=nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.15; bump.inputs['Distance'].default_value=.0008
    links.new(noise.outputs['Fac'],bump.inputs['Height']); links.new(bump.outputs['Normal'],bs.inputs['Normal'])
    return mat


def tagged(obj, semantic, instance):
    return segment(obj,semantic,instance)


def build_architecture():
    random.seed(11)
    white=material('Warm painted plaster',(.78,.79,.74),.88)
    ceiling=material('Ceiling ivory',(.84,.84,.79),.9)
    charcoal=material('Structural steel warm charcoal',(.048,.049,.048),.4,.48)
    darkedge=material('Steel edges',(.024,.026,.027),.43,.5)
    brass=material('Champagne anodized window frames',(.37,.31,.20),.33,.7)
    recess=material('Unlit recess walls',(.035,.049,.057),.9)
    door=wood('Walnut door',(.18,.123,.072),(.075,.046,.027),(3,2,70))
    grout=material('Gaps between oak planks',(.11,.065,.025),.9)
    tagged(cube('Floor underlayment',(0,0,-.039),(10,12,.055),grout),'floor','floor_base')
    woods=[]
    for i in range(9):
        c=.89+i*.035
        woods.append(wood('Oak plank tone %02d'%i,(.46*c,.248*c,.092*c),(.28*c,.126*c,.039*c)))
    # Broad oak blocks interlock at right angles, as in the reference parquet.
    w=.245; length=4*w
    for i in range(-12,13):
        for j in range(-30,31):
            a=(4*i+j)*w; b=(4*i-j)*w
            for k,(x,y,angle) in enumerate([(a+length/2,b+w/2,0),(a+3.5*w,b+w+length/2,math.pi/2)]):
                if not (-4.7<x<4.7 and -5.2<y<4.6):continue
                ident='parquet_%02d_%02d_%d'%(i+12,j+30,k)
                ob=tagged(cube(ident,(x,y,-.010),(length-.0015,w-.0015,.022),random.choice(woods),.001), 'floor_plank',ident)
                ob.rotation_euler.z=angle

    # Floor-to-ceiling glazed facade and its low brass sill.
    glass=material('Cool architectural glass',(.60,.80,.83),.10,.08)
    bs=glass.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Transmission Weight'].default_value=.88
    bs.inputs['IOR'].default_value=1.46
    for i in range(4):
        x=-3.3+i*.89
        tagged(cube('Glazing panel %d'%i,(x+.425,2.40,1.90),(.85,.016,3.78),glass),'window_glass','window_%d'%i)
        tagged(cube('Vertical mullion %d'%i,(x,2.36,1.92),(.044,.10,3.84),brass,.005),'window_frame','mullion_%d'%i)
    tagged(cube('Right window mullion',(.26,2.36,1.92),(.055,.1,3.84),brass,.004),'window_frame','mullion_right')
    tagged(cube('Window bottom sill',(-1.50,2.31,.095),(3.62,.19,.075),brass,.008),'window_frame','window_sill')
    for z in [.70,1.47]:
        tagged(cube('Glass horizontal rail %.2f'%z,(-1.5,2.36,z),(3.6,.055,.025),brass,.002),'window_frame','horizontal_rail_%.2f'%z)
    blind=material('Gray translucent roller blind',(.135,.16,.155),.92)
    nt=blind.node_tree; noise=nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value=210
    bump=nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.12; bump.inputs['Distance'].default_value=.001
    nt.links.new(noise.outputs['Fac'],bump.inputs['Height']); nt.links.new(bump.outputs['Normal'],nt.nodes.get('Principled BSDF').inputs['Normal'])
    for i,(a,b) in enumerate([(-3.3,-1.54),(-1.51,.25)]):
        tagged(cube('Roller shade %d'%i,((a+b)/2,2.28,2.985),(b-a,.022,1.65),blind,.002),'roller_blind','roller_blind_%d'%i)
        tagged(cube('Blind lower hem %d'%i,((a+b)/2,2.267,2.16),(b-a,.028,.018),blind,.004),'roller_blind','roller_blind_%d'%i)
    # Diagonal metal brace, the strongest architectural feature in the photograph.
    a=Vector((-1.87,2.16,.10)); b=Vector((1.49,2.16,3.90))
    beam=tagged(cube('Massive diagonal structural brace',(a+b)/2,(.37,.29,(b-a).length),charcoal,.012),'structural_beam','diagonal_brace')
    beam.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler()
    for y in [2.008,2.312]:
        aa=a.copy(); bb=b.copy(); aa.y=y; bb.y=y
        edge=tagged(cube('Brace steel flange %.2f'%y,(aa+bb)/2,(.403,.018,(bb-aa).length),charcoal,.005),'structural_beam','diagonal_brace')
        edge.rotation_euler=(bb-aa).to_track_quat('Z','Y').to_euler()
    tagged(cube('Left dark structural column',(-3.37,2.15,1.85),(.17,.29,3.7),darkedge,.009),'structural_column','left_column')
    # Dark doorway, white pier behind tree, and right-hand alcove.
    tagged(cube('Deep doorway rear',(.66,2.89,1.6),(.81,.10,3.2),recess),'wall','recess_back')
    tagged(cube('Recess left return',(.28,2.64,1.6),(.10,.55,3.2),recess),'wall','recess_left')
    tagged(cube('Recess ceiling',(.65,2.6,3.17),(.8,.65,.1),recess),'ceiling','recess_ceiling')
    tagged(cube('White pier behind tree',(1.47,2.42,1.8),(.87,.22,3.6),white,.004),'wall','white_pier')
    tagged(cube('Pier skirting',(1.47,2.284,.06),(.90,.035,.12),ceiling,.003),'baseboard','pier_baseboard')
    tagged(cube('Door jamb left',(1.936,2.45,1.6),(.065,.23,3.2),brass,.004),'door_frame','alcove_door_frame')
    tagged(cube('Walnut door inside alcove',(2.33,2.71,1.52),(.71,.06,3.04),door,.006),'door','walnut_door')
    tagged(cube('Right white wall',(2.99,2.47,1.7),(.64,.24,3.4),white,.003),'wall','right_wall')
    tagged(cube('Right wall continuation',(5.8,2.47,1.85),(5,.24,3.7),white,.003),'wall','right_wall')
    tagged(cube('Right room side wall',(3.40,-.7,1.85),(.18,6.4,3.7),white,.004),'wall','right_side_wall')
    tagged(cube('Right wall skirting',(2.99,2.326,.06),(.65,.03,.12),ceiling,.003),'baseboard','right_baseboard')
    pale=material('Alcove stone floor',(.53,.52,.46),.65)
    tagged(cube('Alcove gray floor',(2.17,2.04,.006),(1.35,1.22,.028),pale,.002),'floor','alcove_floor')
    plate=material('Ivory switch plates',(.67,.68,.50),.46)
    tagged(cube('Light switch plate',(1.15,2.289,1.42),(.075,.009,.115),plate,.006),'switch','wall_switch')
    tagged(cube('Light switch rocker',(1.15,2.280,1.425),(.027,.007,.057),white,.004),'switch','wall_switch')
    tagged(cube('Thermostat white surround',(1.18,2.282,1.18),(.087,.02,.115),ceiling,.008),'thermostat','thermostat')
    tagged(cube('Thermostat dark screen',(1.18,2.265,1.188),(.046,.007,.068),darkedge,.002),'thermostat','thermostat')
    tagged(cube('Room number plaque',(2.87,2.34,1.56),(.19,.01,.22),darkedge,.003),'sign','room_number')
    cu=bpy.data.curves.new('Room numeral','FONT'); cu.body='3';cu.align_x='CENTER';cu.align_y='CENTER';cu.size=.14;cu.extrude=.0003
    ob=bpy.data.objects.new('Room 3',cu);bpy.context.collection.objects.link(ob);ob.location=(2.87,2.328,1.56);ob.rotation_euler=(math.pi/2,0,0);ob.data.materials.append(ceiling)
    tagged(ob,'sign','room_number')
    # Minimal cream standing rack with a blue-gray hanging garment.
    rackmat=material('Coat rack powdercoat',(.63,.64,.57),.48,.24)
    for k,x in enumerate([2.17,2.60]):
        tagged(tube('Coat stand side %d'%k,[(x,2.15,.025),(x,2.15,1.84),(x-.055,2.10,1.95)],.012,rackmat),'coat_rack','coat_rack')
    tagged(tube('Coat rack top rail',[(2.11,2.1,1.95),(2.33,2.09,1.87),(2.55,2.1,1.95)],.012,rackmat),'coat_rack','coat_rack')
    cloth=material('Hanging blue gray fabric',(.12,.19,.24),.95)
    verts=[];faces=[]
    for iz in range(19):
        for ix in range(15):
            u=ix/14;v=iz/18
            verts.append((2.11+.27*u+.045*math.sin(v*2),2.095-.025*math.sin(u*26+v*2),1.81-.85*v+.03*math.sin(u*9)))
    for iz in range(18):
        for ix in range(14):
            a=iz*15+ix;faces.append((a,a+1,a+16,a+15))
    me=bpy.data.meshes.new('Folded hanging cloth mesh');me.from_pydata(verts,[],faces);me.update()
    ob=bpy.data.objects.new('Blue cloth hanging on stand',me);bpy.context.collection.objects.link(ob);ob.data.materials.append(cloth)
    so=ob.modifiers.new('Fabric thickness','SOLIDIFY');so.thickness=.003
    for p in me.polygons:p.use_smooth=True
    tagged(ob,'hanging_garment','blue_hanging_cloth')
    boxmat=material('Blue supply carton',(.025,.065,.55),.63)
    tagged(cube('Blue supply box',(1.96,2.19,.13),(.25,.29,.26),boxmat,.008),'storage_box','blue_box')
    bagmat=material('Alcove black nylon bag',(.012,.019,.022),.84)
    ob=tagged(cube('Small dark bag behind planter',(2.02,2.30,.415),(.20,.15,.34),bagmat,.065),'backpack','alcove_black_bag')
    tagged(tube('Alcove bag top handle',[(1.96,2.30,.56),(1.99,2.30,.62),(2.055,2.30,.62),(2.08,2.30,.56)],.009,bagmat),'backpack','alcove_black_bag')
    # Neighboring glass building seen beyond the facade.
    extwhite=material('Exterior silver building skin',(.61,.72,.71),.48,.32)
    extglass=material('Exterior aqua window panels',(.25,.55,.59),.22,.52)
    extyellow=material('Exterior pale yellow details',(.59,.55,.23),.5,.3)
    tagged(cube('Opposite building',(-1.6,5.08,2.3),(8,.25,6),extwhite),'exterior_building','neighbor_building')
    for ix in range(14):
        x=-5+ix*.52
        tagged(cube('Neighbor glazing %02d'%ix,(x,4.925,2.3),(.43,.04,5.8),extglass),'exterior_window','neighbor_window_%02d'%ix)
        tagged(cube('Neighbor vertical frame %02d'%ix,(x+.24,4.88,2.3),(.031,.07,5.9),extwhite),'exterior_frame','neighbor_frame_%02d'%ix)
        if ix%3==0:
            tagged(cube('Yellow facade fin %02d'%ix,(x-.17,4.8,2.3),(.024,.13,5.85),extyellow),'exterior_frame','neighbor_fin_%02d'%ix)
    for iz in range(100):
        z=-.5+iz*.064
        tagged(cube('Exterior horizontal louver %03d'%iz,(-1.6,4.83,z),(8,.1,.014),extwhite),'exterior_louver','neighbor_louver_%03d'%iz)
    rail=material('Balcony stainless rails',(.46,.51,.49),.27,.72)
    for z in [.39,.58,.77,.96]:
        tagged(tube('Exterior balcony horizontal rail %.2f'%z,[(-4,3.20,z),(.5,3.2,z)],.012,rail),'railing','outside_balcony')
    for x in [-3,-1.9,-.8,.3]:
        tagged(cube('Balcony upright %.2f'%x,(x,3.2,.49),(.026,.026,1.06),rail,.002),'railing','outside_balcony')


def build_tables():
    oak=wood('Desk pale oak veneer',(.63,.44,.235),(.42,.255,.115),(3,90,5))
    endgrain=wood('Desk edge grain',(.54,.36,.18),(.39,.23,.10),(3,40,4))
    white=material('Desk legs white enamel',(.77,.80,.79),.29,.22)
    steel=material('Under table black steel',(.025,.029,.03),.4,.6)
    foot=material('Desk rubber foot',(.024,.024,.021),.75)
    for i,x in enumerate([-.553,.553]):
        ident='desk_%d'%(i+1)
        tagged(cube('Desk %d oak top'%(i+1),(x,0,.774),(1.101,1.8,.042),oak,.005),'desk',ident)
        tagged(cube('Desk %d apron'%(i+1),(x,0,.737),(.95,1.55,.025),endgrain,.004),'desk',ident)
        tagged(cube('Desk %d underside crossbar'%(i+1),(x,0,.680),(.070,1.43,.055),steel,.007),'desk',ident)
        for j,y in enumerate([-.59,.59]):
            tagged(cube('Desk %d leg %d outer column'%(i+1,j),(x,y,.361),(.098,.092,.637),white,.009),'desk',ident)
            tagged(cube('Desk %d leg %d upper sleeve'%(i+1,j),(x,y,.635),(.085,.083,.21),white,.007),'desk',ident)
            tagged(cube('Desk %d leg %d floor runner'%(i+1,j),(x,y,.051),(.90,.085,.06),white,.018),'desk',ident)
            tagged(cube('Desk %d upper support %d'%(i+1,j),(x,y,.711),(.85,.065,.045),white,.006),'desk',ident)
            for dx in [-.38,.38]:
                tagged(cylinder('Desk foot', (x+dx,y,.017),.028,.018,foot),'desk',ident)
        tagged(tube('Desk %d cable tray'%(i+1),[(x-.39,.23,.68),(x-.39,.25,.59),(x+.39,.25,.59),(x+.39,.23,.68)],.008,steel),'cable_tray','desk_tray_%d'%i)
