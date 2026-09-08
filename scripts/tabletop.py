"""Editable tabletop reconstruction, organized by physical item and instance ID."""
import bpy
import math
import random
from mathutils import Vector
from scene_utils import material, cube, cylinder, sphere, tube, segment, collection, move_to

TAU = math.tau
M = {}
COLL = None
ACTIVE = None


def group(name, semantic, location=(0, 0, 0), rotation=0):
    global ACTIVE
    root = bpy.data.objects.new(name, None)
    COLL.objects.link(root)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = .04
    root.location = location
    root.rotation_euler[2] = rotation
    root['semantic_class'] = semantic
    root['instance_id'] = name
    ACTIVE = root
    return root


def tag(obj):
    move_to(obj, COLL)
    obj.parent = ACTIVE
    segment(obj, ACTIVE['semantic_class'], ACTIVE['instance_id'])
    return obj


def box(name, loc, size, mat, bevel=0, rot=None):
    obj = tag(cube(name, loc, size, M.get(mat, mat), bevel))
    if rot:
        obj.rotation_euler = rot
    return obj


def cyl(name, loc, radius, depth, mat, vertices=40, rot=None):
    obj = tag(cylinder(name, loc, radius, depth, M.get(mat, mat), vertices))
    if rot:
        obj.rotation_euler = rot
    return obj


def ball(name, loc, size, mat):
    return tag(sphere(name, loc, size, M.get(mat, mat)))


def cable(name, points, radius=.002, mat='rubber'):
    return tag(tube(name, points, radius, M.get(mat, mat)))


def rod(name, p1, p2, radius, mat='black', vertices=24):
    a, b = Vector(p1), Vector(p2)
    obj = cyl(name, (a+b)/2, radius, (b-a).length, mat, vertices)
    obj.rotation_euler = (b-a).to_track_quat('Z', 'Y').to_euler()
    return obj


def mesh(name, verts, faces, mat):
    data = bpy.data.meshes.new(name + '_mesh')
    data.from_pydata(verts, [], faces)
    data.materials.append(M.get(mat, mat))
    data.update()
    obj = bpy.data.objects.new(name, data)
    COLL.objects.link(obj)
    return tag(obj)


def lathe(name, profile, mat, resolution=40):
    verts = [(r*math.cos(TAU*i/resolution), r*math.sin(TAU*i/resolution), z)
             for z, r in profile for i in range(resolution)]
    faces=[]
    for j in range(len(profile)-1):
        for i in range(resolution):
            k=j*resolution+i
            kn=j*resolution+(i+1)%resolution
            faces.append((k, kn, kn+resolution, k+resolution))
    faces.append(tuple(reversed(range(resolution))))
    faces.append(tuple((len(profile)-1)*resolution+i for i in range(resolution)))
    obj=mesh(name, verts, faces, mat)
    for p in obj.data.polygons:
        p.use_smooth=True
    return obj


def text_obj(name, value, loc, size, mat, rot=(0,0,0), align='CENTER'):
    curve=bpy.data.curves.new(name+'_font','FONT')
    curve.body=value
    curve.size=size
    curve.align_x=align
    curve.align_y='CENTER'
    curve.extrude=.00005
    curve.materials.append(M.get(mat,mat))
    ob=bpy.data.objects.new(name,curve)
    COLL.objects.link(ob)
    ob.location=loc
    ob.rotation_euler=rot
    return tag(ob)


def screen_pos(x, y, z, tilt):
    # Coordinates relative to the hinge, with the screen rising away from the user.
    return (x, .118 + y*math.cos(tilt)+z*math.sin(tilt), .025-y*math.sin(tilt)+z*math.cos(tilt))


def laptop(name, location, angle, silver=True, seed=1):
    rng=random.Random(seed)
    group(name,'laptop',(location[0],location[1],.799),angle)
    shell='aluminum' if silver else 'dark_metal'
    box(name+'_base',(0,0,.009),(.365,.247,.016),shell,.009)
    box(name+'_front_lip',(0,-.116,.013),(.073,.009,.004),'dark_metal',.003)
    box(name+'_keyboard_well',(0,.029,.018),(.305,.127,.0026),'keywell',.004)
    # Individual key caps make the keyboard readable even in a close view.
    for row in range(5):
        for col in range(13):
            kx=-.143+col*.0238
            ky=.077-row*.023
            box(f'{name}_key_{row:02}_{col:02}',(kx,ky,.0204),(.0207,.0182,.0035),'key',.002)
            if row<4 and col%2==0:
                box(f'{name}_key_legend_{row:02}_{col:02}',(kx-.003,ky+.002,.0223),(.0026,.0034,.0004),'legend',.0005)
    box(name+'_spacebar',(0,-.047,.0204),(.101,.015,.0033),'key',.002)
    box(name+'_trackpad',(0,-.084,.0182),(.124,.052,.0013),'trackpad',.004)
    for side in [-1,1]:
        for col in range(3):
            for row in range(22):
                box(f'{name}_speaker_{side}_{col}_{row}',(side*(.161+col*.003),-.030+row*.0052,.0188),(.0012,.0012,.0005),'speaker')
    cyl(name+'_hinge',(0,.115,.021),.0075,.320,'dark_metal',rot=(0,math.pi/2,0))
    tilt=math.radians(15 if silver else 13)
    box(name+'_display_shell',screen_pos(0,0,.119,tilt),(.365,.011,.240),shell,.008,(-tilt,0,0))
    box(name+'_display_bezel',screen_pos(0,-.0062,.12,tilt),(.350,.0015,.224),'bezel',.005,(-tilt,0,0))
    box(name+'_display_glass',screen_pos(0,-.0072,.123,tilt),(.329,.0007,.201),'screen',.001,(-tilt,0,0))
    ball(name+'_webcam',screen_pos(0,-.0075,.232,tilt),(.0015,.0007,.0015),'lens')
    # Abstract development windows: no people or photographic textures.
    box(name+'_screen_topbar',screen_pos(0,-.0079,.217,tilt),(.326,.0005,.011),'ui_bar',0,(-tilt,0,0))
    box(name+'_screen_sidebar',screen_pos(-.139,-.0079,.12,tilt),(.039,.0005,.178),'ui_side',0,(-tilt,0,0))
    for k in range(3):
        ball(name+'_window_dot_'+str(k),screen_pos(-.151+k*.009,-.0083,.218,tilt),(.0022,.0007,.0022),['red','yellow','green'][k])
    for k in range(8):
        box(name+'_file_'+str(k),screen_pos(-.139,-.0085,.197-k*.013,tilt),(.021+rng.random()*.01,.0003,.0021),'code_gray',0,(-tilt,0,0))
    for line in range(19):
        z=.202-line*.0087
        indent=(line%5)*.008
        x=-.111+indent
        for tok in range(rng.randint(2,5)):
            length=rng.uniform(.011,.037)
            if x+length>.152:
                break
            color=rng.choice(['code_gray','code_gray','code_cyan','code_rose','code_amber'])
            box(f'{name}_code_{line}_{tok}',screen_pos(x+length/2,-.0086,z,tilt),(length,.0003,.0019),color,.0004,(-tilt,0,0))
            x+=length+.004
    box(name+'_display_wordmark',screen_pos(0,-.0078,.011,tilt),(.017,.0005,.0015),'legend',0,(-tilt,0,0))
    # Flush ports along the visible sides.
    for side in [-1,1]:
        for j in range(2):
            box(f'{name}_usbc_{side}_{j}',(side*.1823,.045-j*.022,.010),(.0008,.012,.0036),'socket',.001)


def chess_piece(kind, name, x, y, white, rotation=0):
    group(name,'chess_piece',(x,y,.820),rotation)
    mat='ivory_piece' if white else 'walnut_piece'
    base=[(0,.014),(.003,.016),(.006,.0165),(.009,.013),(.012,.012),(.015,.010)]
    if kind=='pawn':
        lathe(name+'_body',base+[(.019,.008),(.030,.006),(.034,.009),(.037,.009),(.039,.007)],mat)
        ball(name+'_head',(0,0,.047),(.010,.010,.010),mat)
    elif kind=='rook':
        lathe(name+'_body',base+[(.020,.010),(.041,.010),(.044,.013),(.049,.013),(.052,.014)],mat)
        for k in range(6):
            a=k*TAU/6
            box(name+'_battlement_'+str(k),(.011*math.cos(a),.011*math.sin(a),.056),(.008,.007,.010),mat,.001,(0,0,a))
    elif kind=='knight':
        lathe(name+'_pedestal',base+[(.019,.011),(.022,.012)],mat)
        # Extruded sculpted horse-head silhouette, with mane, muzzle and ears.
        profile=[(-.011,.021),(.011,.021),(.009,.038),(.017,.045),(.015,.053),(.004,.059),(-.002,.067),(-.007,.063),(-.009,.058),(-.012,.048)]
        verts=[(xx, yy, zz) for yy in [-.007,.007] for xx,zz in profile]
        n=len(profile)
        faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
        faces +=[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
        horse=mesh(name+'_horse_head',verts,faces,mat)
        bevel=horse.modifiers.new('Rounded carved edges','BEVEL'); bevel.width=.002; bevel.segments=3
        horse.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
        for s in [-1,1]:
            ball(name+'_eye_'+str(s),(.005,s*.0078,.054),(.0015,.0007,.0015),'piece_eye')
        for k in range(5):
            box(name+'_mane_'+str(k),(-.010,0,.033+k*.0046),(.003,.015,.0013),'wood_dark',.0005)
    elif kind=='bishop':
        lathe(name+'_body',base+[(.021,.010),(.043,.006),(.046,.011),(.050,.011),(.052,.007)],mat)
        ball(name+'_mitre',(0,0,.060),(.010,.009,.016),mat)
        box(name+'_mitre_cut',(.003,-.0087,.064),(.0012,.0013,.017),'wood_dark',.0004,(0,.40,0))
        ball(name+'_finial',(0,0,.075),(.0032,.0032,.0032),mat)
    elif kind=='queen':
        lathe(name+'_body',base+[(.020,.011),(.048,.006),(.053,.012),(.058,.012),(.061,.009),(.067,.013)],mat)
        for k in range(8):
            a=k*TAU/8
            ball(name+'_crown_'+str(k),(.011*math.cos(a),.011*math.sin(a),.070),(.0028,.0028,.0048),mat)
        ball(name+'_crown_center',(0,0,.073),(.005,.005,.006),mat)
    else:
        lathe(name+'_body',base+[(.021,.011),(.047,.0065),(.053,.012),(.057,.012),(.061,.009),(.066,.009)],mat)
        box(name+'_cross_vertical',(0,0,.078),(.006,.006,.027),mat,.001)
        box(name+'_cross_horizontal',(0,0,.081),(.019,.006,.006),mat,.001)


def chess():
    cx,cy=-.14,-.32
    group('Chessboard_01','chessboard',(cx,cy,.798),.075)
    box('Chessboard_walnut_frame',(0,0,.008),(.428,.428,.018),'wood_dark',.003)
    box('Chessboard_inlay_surround',(0,0,.018),(.408,.408,.003),'maple')
    size=.0468
    for iy in range(8):
        for ix in range(8):
            box(f'Chessboard_square_{chr(65+ix)}{iy+1}',((ix-3.5)*size,(iy-3.5)*size,.020), (size,size,.002),'maple' if (ix+iy)%2 else 'walnut')
    for k in range(8):
        text_obj('Chessboard_file_'+str(k),chr(65+k),((k-3.5)*size,-.201,.022),.008,'ivory_piece')
        text_obj('Chessboard_rank_'+str(k),str(k+1),(-.201,(k-3.5)*size,.022),.008,'ivory_piece')
    order=['rook','knight','bishop','queen','king','bishop','knight','rook']
    ca,sa=math.cos(.075),math.sin(.075)
    for white,rank,pawnrank in [(True,0,1),(False,7,6)]:
        for file in range(8):
            for kind,r in [(order[file],rank),('pawn',pawnrank)]:
                px=(file-3.5)*size; py=(r-3.5)*size
                # A few advanced pawns preserve a credible active game layout.
                if kind=='pawn' and file in ([3,4] if white else [2,4]):
                    py += size*(2 if white else -1)
                xx=cx+px*ca-py*sa; yy=cy+px*sa+py*ca
                chess_piece(kind,f'Chess_{"White" if white else "Black"}_{kind}_{file+1:02}',xx,yy,white,.075+(0 if white else math.pi))


def mug(name, loc, color='ceramic_black', scale=1, angle=0, fluted=False):
    group(name,'mug',(loc[0],loc[1],.798),angle)
    r=.032*scale; h=.088*scale
    profile=[(0,r*.75),(.004,r*.82),(h*.94,r),(h,r*.98),(h,r*.88),(.010,r*.72)]
    lathe(name+'_cup',profile,color)
    cyl(name+'_coffee',(0,0,h-.010),r*.865,.001,'coffee')
    points=[(r*.92+.030*scale*math.sin(math.pi*t/18),0,h*.52+.029*scale*math.cos(math.pi*t/18)) for t in range(19)]
    if not fluted:
        cable(name+'_handle',points,.006*scale,color)
    if fluted:
        for k in range(36):
            a=TAU*k/36
            cable(name+'_flute_'+str(k),[(r*.84*math.cos(a),r*.84*math.sin(a),.010),(r*.98*math.cos(a),r*.98*math.sin(a),h-.004)],.0011,color)


def bottle():
    group('Black_insulated_bottle_01','water_bottle',(.61,.42,.798),0)
    lathe('Bottle_powder_coat_body',[(0,.031),(.007,.034),(.162,.034),(.173,.032),(.181,.025),(.195,.024)],'bottle_black')
    cyl('Bottle_screw_cap',(0,0,.202),.025,.024,'rubber')
    cyl('Bottle_cap_top',(0,0,.215),.024,.003,'bottle_black')
    for k in range(30):
        a=TAU*k/30
        box('Bottle_cap_rib_'+str(k),(.025*math.cos(a),.025*math.sin(a),.201),(.002,.002,.017),'rubber',.0005,(0,0,a))


def drink_can():
    group('Lime_soda_can_01','drink_can',(.32,.04,.798),-.18)
    lathe('Soda_can_aluminum',[(0,.027),(.004,.030),(.117,.030),(.125,.027),(.129,.027)],'can_green')
    cyl('Soda_can_top',(0,0,.129),.027,.0018,'aluminum')
    cyl('Soda_can_top_recess',(0,0,.130),.023,.001,'dark_aluminum')
    cyl('Soda_can_pull_tab',(0,-.005,.132),.007,.0018,'aluminum',vertices=32)
    cyl('Soda_can_opening',(0,.011,.131),.007,.0004,'socket')
    # Big vertical lettering printed down the cylinder's visible front.
    text_obj('Soda_can_lettering','hint',(0,-.0306,.067),.027,'can_ink',(math.pi/2,0,math.pi/2))
    text_obj('Soda_can_flavor','LIME',(0,-.0305,.016),.007,'can_ink',(math.pi/2,0,0))


def phone(name, loc, angle=0, black=True):
    group(name,'mobile_phone',(loc[0],loc[1],.802),angle)
    box(name+'_frame',(0,0,.004),(.073,.144,.009),'dark_metal',.010)
    box(name+'_glass',(0,0,.009),(.067,.136,.001),'phone_screen',.009)
    box(name+'_earpiece',(0,.059,.0098),(.013,.0014,.0005),'black',.0005)
    box(name+'_gesture_bar',(0,-.058,.0097),(.019,.0012,.0003),'code_gray',.0005)
    ball(name+'_front_camera',(.009,.059,.010),(.0018,.0018,.0005),'lens')


def mouse(name, loc, angle=0):
    group(name,'computer_mouse',(loc[0],loc[1],.798),angle)
    ball(name+'_body',(0,0,.014),(.032,.052,.020),'rubber')
    box(name+'_button_seam',(0,.022,.034),(.0008,.040,.001),'black',.0003)
    cyl(name+'_scroll_wheel',(0,.020,.034),.005,.008,'dark_aluminum',rot=(math.pi/2,0,0))


def small_accessories():
    group('Clear_ridged_drinking_cup_01','drinking_cup',(1.00,.055,.799),0)
    lathe('Clear_cup_shell',[(0,.024),(.004,.026),(.087,.033),(.089,.033),(.089,.0315),(.005,.024)],'clear_plastic')
    for j in range(11):
        z=.010+j*.0067
        r=.026+.007*z/.089
        cable('Clear_cup_ridge_'+str(j),[(r*math.cos(TAU*k/50),r*math.sin(TAU*k/50),z) for k in range(51)],.0009,'clear_plastic')
    cyl('Clear_cup_water',(0,0,.034),.027,.058,'water')
    group('Folded_sunglasses_01','eyeglasses',(.849,.232,.803),.3)
    for side in [-1,1]:
        pts=[(side*.023+.020*math.cos(TAU*k/40),.014*math.sin(TAU*k/40),.004) for k in range(41)]
        cable('Sunglasses_frame_'+str(side),pts,.0025,'rubber')
        lens=ball('Sunglasses_lens_'+str(side),(side*.023,0,.003),(.018,.012,.001),'lens')
        cable('Sunglasses_folded_temple_'+str(side),[(side*.042,0,.006),(side*.026,.028,.012),(-side*.022,.035,.011)],.0023,'rubber')
    cable('Sunglasses_bridge',[(-.005,0,.005),(0,.002,.006),(.005,0,.005)],.002,'rubber')


def power_and_sign():
    group('White_power_strip_01','power_strip',(-.18,.08,.798),-.15)
    box('Power_strip_body',(0,0,.014),(.230,.068,.027),'plastic_white',.009)
    for idx in range(4):
        x=-.082+idx*.055
        cyl('Power_strip_receptacle_'+str(idx),(x,0,.028),.021,.001,'ivory_piece')
        for dx in [-.006,.006]:
            box(f'Power_strip_socket_{idx}_{dx}',(x+dx,.003,.029),(.0025,.009,.001),'socket',.0005)
        cyl('Power_strip_ground_'+str(idx),(x,-.009,.029),.0023,.001,'socket',vertices=12)
    box('Power_strip_switch',(.105,0,.029),(.012,.022,.003),'red',.002)
    for name,loc,size,color in [('Charger_01',(-.27,.091,.842),(.058,.052,.055),'black'),('Charger_02',(-.20,.086,.839),(.051,.046,.052),'black'),('White_USB_charger_03',(-.35,.12,.816),(.043,.043,.034),'plastic_white')]:
        group(name,'power_adapter',loc,.1)
        box(name+'_body',(0,0,0),size,color,.004)
        box(name+'_seam',(0,0,size[2]*.40),(size[0]+.0005,size[1]+.0005,.001),'dark_metal' if color=='black' else 'light_gray')
    group('USB_hub_01','usb_hub',(-.50,-.006,.809),-.13)
    box('USB_hub_shell',(0,0,.005),(.102,.035,.011),'dark_aluminum',.003)
    for k in range(3):
        box('USB_hub_port_'+str(k),(-.029+k*.027,-.0178,.005),(.015,.0008,.005),'socket',.001)
    group('QR_information_stand_01','table_sign',(-.04,.25,.798),-.05)
    box('QR_stand_acrylic_foot',(0,0,.003),(.105,.060,.006),'acrylic',.002)
    box('QR_stand_frame',(0,.010,.088),(.103,.006,.170),'acrylic',.002)
    box('QR_stand_paper',(0,.0065,.088),(.097,.0008,.163),'paper')
    text_obj('QR_stand_heading','CONNECT',(0,.0058,.146),.009,'ink',(math.pi/2,0,0))
    # Deterministic QR-like printed grid with the three standard finder corners.
    rng=random.Random(191)
    n=25; step=.00245
    def finder(x,y,ox,oy):
        dx=x-ox;dy=y-oy
        return 0<=dx<7 and 0<=dy<7 and (dx in [0,6] or dy in [0,6] or (2<=dx<=4 and 2<=dy<=4))
    for iy in range(n):
        for ix in range(n):
            reserved=(ix<8 and iy<8) or(ix>=17 and iy<8)or(ix<8 and iy>=17)
            dark=finder(ix,iy,0,0)or finder(ix,iy,18,0)or finder(ix,iy,0,18) or(not reserved and rng.random()<.48)
            if dark:
                box(f'QR_print_{ix}_{iy}',((ix-12)*step,.0058,.100+(iy-12)*step),(step*.97,.0003,step*.97),'ink')
    text_obj('QR_stand_caption','SCAN TO JOIN',(0,.0057,.055),.006,'ink',(math.pi/2,0,0))
    for k in range(3):
        box('QR_stand_footer_'+str(k),(0,.0057,.041-k*.005),(.053-k*.008,.0003,.001),'code_gray')


def robot_arm():
    group('White_robot_arm_01','robot_arm',(-.74,-.42,.799),-.15)
    box('Robot_base_lower',(0,0,.014),(.120,.121,.027),'plastic_white',.008)
    box('Robot_base_electronics',(0,0,.044),(.094,.083,.041),'plastic_white',.009)
    box('Robot_base_label',(0,-.042,.047),(.052,.001,.016),'light_gray',.001)
    cyl('Robot_base_turret',(0,0,.078),.043,.027,'plastic_white')
    cyl('Robot_yaw_servo',(0,0,.094),.026,.013,'servo_black')
    joints=[(0,0,.097),(-.02,0,.192),(.095,.015,.252),(.174,.020,.170),(.224,.025,.169)]
    for j,p in enumerate(joints[:-1]):
        box('Robot_servo_'+str(j),p,(.041,.059,.039),'servo_black',.004)
        cyl('Robot_joint_hub_'+str(j),(p[0],p[1]-.038,p[2]),.025,.016,'plastic_white',rot=(math.pi/2,0,0))
        cyl('Robot_joint_screw_'+str(j),(p[0],p[1]-.047,p[2]),.006,.002,'aluminum',rot=(math.pi/2,0,0))
        for side in [-1,1]:
            a=Vector(joints[j])+Vector((0,side*.036,0))
            b=Vector(joints[j+1])+Vector((0,side*.036,0))
            ob=box(f'Robot_link_{j}_{side}',(a+b)/2,(.029,.013,(b-a).length+.015),'plastic_white',.007)
            ob.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler()
            rod(f'Robot_link_recess_{j}_{side}',a*.67+b*.33,a*.33+b*.67,.007,'light_gray')
    end=Vector(joints[-1])
    box('Robot_gripper_servo',end,(.049,.033,.030),'servo_black',.003)
    box('Robot_gripper_plate',end+Vector((.023,0,0)),(.013,.066,.032),'plastic_white',.003)
    for s in [-1,1]:
        box('Robot_gripper_finger_'+str(s),end+Vector((.049,s*.035,-.005)),(.053,.011,.024),'plastic_white',.004,(0,0,-s*.18))
        box('Robot_gripper_pad_'+str(s),end+Vector((.071,s*.027,-.007)),(.014,.008,.021),'rubber',.002)
    for j in range(4):
        x=-.038+(j%2)*.076; y=-.040+(j//2)*.080
        cyl('Robot_base_bolt_'+str(j),(x,y,.030),.004,.0015,'aluminum',vertices=12)
    cable('Robot_servo_ribbon_black',[(-.012,-.032,.054),(-.050,-.054,.124),(-.025,-.059,.205),(.040,-.054,.231),(.112,-.046,.217),(.163,-.037,.175)],.003,'rubber')
    cable('Robot_servo_ribbon_orange',[(-.017,-.036,.046),(-.056,-.059,.125),(-.029,-.063,.211),(.042,-.058,.237),(.120,-.048,.220),(.169,-.041,.173)],.0019,'orange')
    box('Robot_front_connector',(-.024,-.045,.041),(.023,.010,.011),'black',.001)


def articulated_mount():
    group('Articulated_camera_mount_01','camera_mount',(-.99,-.32,.799),.12)
    box('Camera_mount_table_clamp',(0,0,-.012),(.063,.078,.045),'black',.006)
    box('Camera_mount_clamp_lower',(0,.020,-.055),(.063,.051,.012),'black',.002)
    cyl('Camera_mount_clamp_screw',(0,.02,-.055),.007,.081,'dark_aluminum')
    box('Camera_mount_clamp_handle',(0,.02,-.094),(.060,.012,.012),'black',.003)
    points=[(0,0,.014),(-.045,.016,.200),(-.038,.036,.310),(.181,.111,.370)]
    for j in range(len(points)-1):
        for s in [-1,1]:
            delta=Vector((0,s*.012,0))
            rod(f'Camera_mount_link_{j}_{s}',Vector(points[j])+delta,Vector(points[j+1])+delta,.006,'black')
        p=points[j]
        cyl('Camera_mount_knuckle_'+str(j),p,.018,.041,'rubber',rot=(math.pi/2,0,0))
    for j in [0,1]:
        a=Vector(points[j]);b=Vector(points[j+1]); ab=b-a
        coil=[]
        for k in range(180):
            t=.22+.50*k/179
            phase=TAU*14*k/179
            p=a+ab*t+Vector((.003*math.cos(phase),.006*math.sin(phase),0))
            coil.append(p)
        cable('Camera_mount_tension_spring_'+str(j),coil,.0012,'dark_aluminum')
    end=Vector(points[-1])
    ball('Camera_mount_ball_head',end,(.018,.018,.018),'black')
    box('Camera_mount_phone_cradle',end+Vector((0,0,.025)),(.040,.031,.078),'rubber',.005,(0,.2,0))
    box('Camera_mount_phone',end+Vector((0,-.016,.027)),(.074,.009,.138),'dark_metal',.009,(.12,.2,-.1))
    box('Camera_mount_phone_glass',end+Vector((0,-.022,.027)),(.068,.001,.128),'phone_screen',.007,(.12,.2,-.1))
    cable('Camera_mount_cable',[(0,-.03,0),(-.07,-.02,.05),(-.07,.018,.18),(-.055,.026,.30),(.05,.061,.32),(.17,.085,.37)],.0024,'rubber')


def mini_tripod():
    group('Mini_tripod_camera_01','mini_tripod',(.43,-.17,.799),-.2)
    for k in range(3):
        a=TAU*k/3+.15
        foot=(.066*math.cos(a),.066*math.sin(a),.006)
        rod('Mini_tripod_leg_'+str(k),(0,0,.062),foot,.004,'rubber')
        ball('Mini_tripod_foot_'+str(k),foot,(.008,.008,.004),'rubber')
    rod('Mini_tripod_column',(0,0,.057),(0,0,.136),.008,'dark_metal')
    ball('Mini_tripod_head',(0,0,.135),(.012,.012,.013),'rubber')
    box('Mini_tripod_webcam',(0,0,.167),(.025,.025,.063),'rubber',.006)
    cyl('Mini_tripod_lens',(0,-.014,.172),.008,.005,'lens',rot=(math.pi/2,0,0))
    box('Mini_tripod_led',(.008,-.015,.192),(.003,.001,.002),'green')


def wires():
    paths=[
      ('USB_cable_left_laptop',[(-.61,-.04,.811),(-.52,-.055,.819),(-.49,.040,.812),(-.40,.055,.811),(-.28,.072,.855)],'rubber',.0025),
      ('White_power_cable',[(-.17,.05,.820),(-.12,-.06,.814),(.020,-.025,.815),(.077,.076,.813),(.23,.08,.814),(.27,.006,.811)],'plastic_white',.0027),
      ('Rear_laptop_charge_cable',[(.42,.48,.81),(.36,.36,.813),(.11,.35,.812),(.04,.22,.814),(-.14,.12,.835)],'plastic_white',.0022),
      ('Foreground_laptop_cable',[(.295,-.75,.812),(.34,-.59,.812),(.35,-.39,.813),(.25,-.16,.812),(-.11,.064,.827)],'rubber',.0022),
      ('Robot_power_cable',[(-.77,-.46,.832),(-.87,-.52,.811),(-.95,-.37,.810),(-.94,-.17,.811),(-.63,-.13,.812),(-.45,.0,.815)],'rubber',.0026),
      ('Power_strip_mains',[(-.30,.085,.812),(-.50,.19,.811),(-.91,.11,.812),(-1.13,.04,.75),(-1.15,.015,.34),(-1.10,-.04,.11)],'plastic_white',.004),
      ('Robot_bundle_red',[(-.78,-.44,.842),(-.84,-.43,.84),(-1.04,-.51,.76),(-1.06,-.53,.48),(-1.02,-.49,.44)],'red',.0015),
      ('Robot_bundle_black',[(-.77,-.44,.842),(-.82,-.42,.84),(-1.03,-.50,.76),(-1.05,-.53,.47),(-1.02,-.49,.44)],'rubber',.002),
    ]
    for name,path,mat,r in paths:
        group(name,'cable')
        cable(name+'_insulation',path,r,mat)
    for idx,(cx,cy,sx,sy) in enumerate([(-.52,-.13,.076,.040),(-.89,-.36,.053,.041),(-.43,.14,.037,.024)]):
        group('Coiled_cable_'+str(idx+1),'cable')
        pts=[]
        for k in range(130):
            t=k/129*TAU*2.6
            pts.append((cx+sx*math.cos(t),cy+sy*math.sin(t),.808+k*.00004))
        cable('Cable_coil_'+str(idx+1),pts,.0022,'rubber')
    group('White_charging_cable_loop_01','cable')
    pts=[(-.35+.056*math.cos(TAU*k/90),.30+.033*math.sin(TAU*k/90),.809+.003*math.sin(TAU*k/90)) for k in range(91)]
    cable('White_cable_loop',pts,.0021,'plastic_white')


def materials():
    palette={
      'aluminum':((.49,.52,.54,1),.27,.8), 'dark_aluminum':((.16,.18,.19,1),.3,.75),
      'dark_metal':((.10,.105,.11,1),.32,.55), 'black':((.008,.009,.010,1),.42,0),
      'keywell':((.017,.019,.021,1),.55,0), 'key':((.015,.018,.021,1),.43,0),
      'legend':((.53,.56,.57,1),.5,0), 'trackpad':((.38,.41,.43,1),.37,.6),
      'speaker':((.026,.029,.033,1),.5,0), 'bezel':((.006,.007,.010,1),.3,0),
      'screen':((.012,.019,.029,1),.26,0), 'lens':((.007,.021,.029,1),.15,.5),
      'ui_bar':((.034,.040,.057,1),.4,0), 'ui_side':((.021,.030,.042,1),.4,0),
      'code_gray':((.32,.40,.48,1),.5,0), 'code_cyan':((.14,.48,.61,1),.5,0),
      'code_rose':((.60,.24,.36,1),.5,0), 'code_amber':((.63,.44,.26,1),.5,0),
      'red':((.69,.10,.065,1),.48,0), 'yellow':((.86,.57,.12,1),.4,0),
      'green':((.18,.55,.18,1),.5,0), 'socket':((.002,.003,.004,1),.66,0),
      'rubber':((.018,.022,.024,1),.72,0), 'maple':((.64,.43,.19,1),.40,0),
      'walnut':((.18,.075,.035,1),.4,0), 'wood_dark':((.095,.044,.023,1),.42,0),
      'ivory_piece':((.81,.66,.41,1),.31,0), 'walnut_piece':((.16,.065,.03,1),.30,0),
      'piece_eye':((.014,.009,.006,1),.3,0), 'ceramic_black':((.012,.014,.015,1),.23,0),
      'ceramic_white':((.85,.84,.77,1),.22,0), 'coffee':((.025,.010,.004,1),.19,0),
      'bottle_black':((.044,.052,.053,1),.62,0), 'can_green':((.46,.91,.045,1),.35,.28),
      'can_ink':((.013,.07,.10,1),.45,0), 'phone_screen':((.007,.015,.018,1),.16,.25),
      'plastic_white':((.81,.83,.78,1),.39,0), 'light_gray':((.49,.54,.53,1),.6,0),
      'acrylic':((.78,.84,.83,1),.22,.05), 'paper':((.91,.90,.83,1),.76,0),
      'ink':((.016,.019,.016,1),.85,0), 'servo_black':((.022,.028,.030,1),.47,0),
      'orange':((.96,.25,.025,1),.5,0),
      'clear_plastic':((.91,.95,.96,1),.13,0), 'water':((.89,.96,.98,1),.09,0),
    }
    for name,(color,rough,metal) in palette.items():
        M[name]=material('Tabletop_'+name,color,rough,metal)
    for name in ['screen','code_cyan','code_rose','code_gray','code_amber']:
        bsdf=M[name].node_tree.nodes.get('Principled BSDF')
        if bsdf and 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value=palette[name][0]
            bsdf.inputs['Emission Strength'].default_value=.25 if name!='screen' else .06
    for name in ['clear_plastic','water']:
        bsdf=M[name].node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Transmission Weight'].default_value=.92
            bsdf.inputs['IOR'].default_value=1.46 if name=='clear_plastic' else 1.333


def build_tabletop():
    global COLL
    COLL=collection('04_Tabletop_Objects')
    materials()
    laptop('Laptop_01_left',(-.79,.035),-math.pi/2,True,13)
    laptop('Laptop_02_rear_left',(-.50,.60),math.pi,False,24)
    laptop('Laptop_03_rear_right',(.53,.62),math.pi,False,35)
    laptop('Laptop_04_right',(.81,-.14),math.pi/2,True,46)
    laptop('Laptop_05_foreground',(.12,-.79),0,True,57)
    chess()
    robot_arm()
    articulated_mount()
    mug('Black_fluted_tumbler_01',(-.84,.38),'ceramic_black',.95,math.pi/2,True)
    mug('White_coffee_mug_02',(-.48,.27),'ceramic_white',1,-.65)
    mug('Black_coffee_mug_03',(-.19,.61),'ceramic_black',.84,1.1)
    mug('Black_coffee_mug_04',(.70,.22),'ceramic_black',.95,-.8)
    bottle()
    drink_can()
    phone('Mobile_phone_01_left',(-.57,-.18),1.0)
    phone('Mobile_phone_02_right',(.91,.18),1.14)
    mouse('Computer_mouse_01',(.91,.34),-math.pi/2)
    mouse('Computer_mouse_02',(.85,-.40),-.2)
    small_accessories()
    power_and_sign()
    mini_tripod()
    wires()
    # Tiny accessories visible near the chess setup.
    group('White_cable_reel_01','cable_reel',(-.48,.08,.804),0)
    box('Charging_reel_rectangular_base',(0,0,-.001),(.102,.103,.007),'aluminum',.011)
    cyl('Cable_reel_white_ring',(0,0,.003),.045,.006,'plastic_white')
    cyl('Cable_reel_center',(0,0,.0065),.033,.001,'light_gray')
    group('Black_headset_case_01','headset_case',(-.21,.77,.805),-.2)
    ball('Headset_soft_case',(0,0,.021),(.080,.055,.025),'rubber')
    cable('Headset_case_zipper',[(.078*math.cos(TAU*k/60),.054*math.sin(TAU*k/60),.025) for k in range(61)],.0013,'dark_aluminum')
    return COLL
