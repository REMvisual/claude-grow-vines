"""
Headless space-colonization TREE generator (Runions, Lane, Prusinkiewicz 2007).
- Attractor cloud inside a randomized crown envelope (ellipsoid lobes).
- Iterative growth: each node pulled toward the average direction of attractors
  within its influence radius; fixed step size; attractors removed within kill dist.
- Pipe-model / Murray's-law radii: parent^n = sum(child^n), smooth trunk->twig taper.
- Slight gravimorphism (branch droop) + phototropism (upward bias) blended in.
- Skins the node tree into tapered tubes (hex on trunk, fewer segs on twigs).
- Bakes normalized ROOT->TIP "growth" value (0 at trunk base -> 1 at tips) as a
  CORNER BYTE_COLOR vertex-color layer "growth" (R=G=B=t). Downstream growth-wipe.
- Proof renders: Cycles CPU, 2 angles x 2 seeds, sun + ground + simple bark mat.

Run: blender --background --factory-startup --python tree_gen_sc.py
Refs: algorithmicbotany.org/papers/colonization.egwnp2007.large.pdf
"""
import bpy, bmesh, math, os, random, sys
import numpy as np
from mathutils import Vector, Matrix
from mathutils import kdtree

# ------------------------------------------------------------------ config
HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "out")

SEEDS = [7, 42]                 # two variations to show variety
RENDER_SAMPLES = 20
RES_X, RES_Y   = 1100, 760

# space-colonization core params (canonical ratios: kill~2*step, infl~8-16*step)
P = dict(
    n_attractors = 1400,       # crown point cloud size
    step         = 0.18,       # D: branch segment length (grow distance)
    kill_dist    = 0.34,       # ~2*step: remove attractor when a node is this close
    infl_dist    = 2.4,        # influence radius (large -> smoother, fuller crown)
    max_nodes    = 4500,       # HARD budget (safety)
    max_iters    = 600,        # HARD iteration budget
    trunk_height = 2.8,        # bare trunk before crown begins
    crown_center = 4.6,        # z of crown centroid
    crown_rx     = 2.6,        # crown ellipsoid radii
    crown_ry     = 2.6,
    crown_rz     = 2.4,
    n_lobes      = 4,          # sub-lobes for an irregular envelope
    grav         = 0.18,       # gravimorphism: downward droop blended into grow dir
    photo        = 0.16,       # phototropism: upward bias blended into grow dir
    # radii (pipe model)
    tip_radius   = 0.012,
    pipe_exp     = 2.0,        # Murray/da Vinci exponent (2 = area-preserving)
    trunk_max_r  = 0.34,       # cap trunk thickness so big crowns don't balloon
    trunk_min_r  = 0.05,       # floor so trunk never collapses
)

def fin(v):
    return all(math.isfinite(c) for c in v)

# ------------------------------------------------------------------ attractors
def make_attractors(pp, rng):
    """Random points inside a multi-lobe ellipsoidal crown envelope."""
    cz = pp['crown_center']
    # lobe centers jittered around crown center
    lobes = []
    for _ in range(pp['n_lobes']):
        lc = Vector((
            rng.uniform(-0.6, 0.6) * pp['crown_rx'],
            rng.uniform(-0.6, 0.6) * pp['crown_ry'],
            cz + rng.uniform(-0.4, 0.7) * pp['crown_rz'],
        ))
        lr = Vector((
            pp['crown_rx'] * rng.uniform(0.5, 0.9),
            pp['crown_ry'] * rng.uniform(0.5, 0.9),
            pp['crown_rz'] * rng.uniform(0.5, 0.9),
        ))
        lobes.append((lc, lr))
    pts = []
    tries = 0
    target = pp['n_attractors']
    while len(pts) < target and tries < target * 40:
        tries += 1
        lc, lr = lobes[rng.randrange(len(lobes))]
        # rejection-sample inside unit sphere then scale
        x = rng.uniform(-1, 1); y = rng.uniform(-1, 1); z = rng.uniform(-1, 1)
        if x*x + y*y + z*z > 1.0:
            continue
        p = Vector((lc.x + x*lr.x, lc.y + y*lr.y, lc.z + z*lr.z))
        if p.z < pp['trunk_height'] + 0.3:    # keep cloud above the bare trunk
            continue
        if fin(p):
            pts.append(p)
    return pts

# ------------------------------------------------------------------ growth (space colonization)
class Node:
    __slots__ = ('pos', 'parent', 'children', 'dir', 'radius', 'depth_d')
    def __init__(self, pos, parent):
        self.pos = pos
        self.parent = parent
        self.children = []
        self.dir = Vector((0, 0, 1))
        self.radius = 0.0
        self.depth_d = 0.0   # accumulated path distance root->this (for growth value)

def grow(pp, rng):
    attractors = make_attractors(pp, rng)
    up = Vector((0, 0, 1))

    # --- pre-trunk: stack a straight-ish trunk up to crown so SC starts from a stem
    nodes = []
    root = Node(Vector((0, 0, 0)), None)
    nodes.append(root)
    cur = root
    nz = 0.0
    while nz < pp['trunk_height']:
        nz += pp['step']
        wob = Vector((rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04), 0))
        np_ = Vector((cur.pos.x + wob.x, cur.pos.y + wob.y, nz))
        nn = Node(np_, cur)
        cur.children.append(nn)
        nodes.append(nn)
        cur = nn

    step = pp['step']
    kill2 = pp['kill_dist'] ** 2
    infl  = pp['infl_dist']
    grav_v = Vector((0, 0, -1))

    it = 0
    while attractors and it < pp['max_iters'] and len(nodes) < pp['max_nodes']:
        it += 1
        # build KD-tree over current nodes
        kd = kdtree.KDTree(len(nodes))
        for i, n in enumerate(nodes):
            kd.insert(n.pos, i)
        kd.balance()

        # each attractor influences its single nearest node within infl_dist
        pulls = {}  # node_idx -> accumulated unit-dir sum
        alive = []
        for a in attractors:
            co, idx, dist = kd.find(a)
            if dist is None:
                alive.append(a); continue
            if dist <= pp['kill_dist']:
                continue  # attractor reached -> drop it
            if dist <= infl:
                d = (a - nodes[idx].pos)
                if d.length > 1e-6:
                    pulls.setdefault(idx, Vector((0, 0, 0)))
                    pulls[idx] += d.normalized()
            alive.append(a)
        attractors = alive

        if not pulls:
            break  # no node can grow toward anything -> done

        # spawn one new node per influenced node
        new_nodes = []
        for idx, acc in pulls.items():
            parent = nodes[idx]
            gdir = acc
            if gdir.length < 1e-6:
                continue
            gdir = gdir.normalized()
            # tropisms: blend up (photo) + down (gravi)
            gdir = gdir + up * pp['photo'] + grav_v * pp['grav']
            # tiny noise for organic wiggle
            gdir = gdir + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1),
                                  rng.uniform(-1, 1))) * 0.10
            if gdir.length < 1e-6 or not fin(gdir):
                continue
            gdir = gdir.normalized()
            npos = parent.pos + gdir * step
            if not fin(npos):
                continue
            nn = Node(npos, parent)
            nn.dir = gdir
            parent.children.append(nn)
            new_nodes.append(nn)

        if not new_nodes:
            break
        nodes.extend(new_nodes)

    # --- accumulate path distance root->node (growth value source)
    # BFS from root
    stack = [root]
    while stack:
        n = stack.pop()
        for c in n.children:
            seg = (c.pos - n.pos).length
            c.depth_d = n.depth_d + (seg if math.isfinite(seg) else 0.0)
            stack.append(c)
    max_d = max((n.depth_d for n in nodes), default=1.0) or 1.0

    # --- pipe-model radii: post-order, tip=tip_radius, parent^e = sum(child^e)
    e = pp['pipe_exp']
    order = sorted(nodes, key=lambda n: n.depth_d, reverse=True)  # tips first
    for n in order:
        if not n.children:
            n.radius = pp['tip_radius']
        else:
            s = sum((c.radius ** e) for c in n.children)
            r = s ** (1.0 / e)
            n.radius = min(pp['trunk_max_r'], max(pp['tip_radius'], r))
    root.radius = min(pp['trunk_max_r'], max(root.radius, pp['trunk_min_r']))

    return nodes, root, max_d

# ------------------------------------------------------------------ skinning (tapered tubes)
def _ring_at(P, t, n_ref, r, segs, VERTS):
    """Build a ring of `segs` verts at P, oriented by tangent t and reference normal n_ref."""
    t = t.normalized() if t.length > 1e-6 else Vector((0, 0, 1))
    n = (n_ref - n_ref.dot(t) * t)
    n = n.normalized() if n.length > 1e-4 else t.orthogonal()
    b = t.cross(n).normalized()
    base = len(VERTS); idx = []
    for s in range(segs):
        a = (s / segs) * math.tau
        v = P + (math.cos(a) * n + math.sin(a) * b) * r
        if not fin(v):
            v = P
        VERTS.append(v); idx.append(base + s)
    return idx, n   # return the actually-used normal so children can inherit it

def build_mesh(nodes, root, max_d, name, mat):
    """Skin the node tree into continuous tapered tubes using a parallel-transport
    frame propagated along each path (no per-segment ring rotation -> no banding).
    Bakes growth corner color."""
    VERTS = []
    FACES = []          # (v4, growth4)

    # fixed segment count per node (chosen by radius) so a node's ring matches its parent's.
    # We pick the SMALLER of parent/child counts at a join and let from_pydata weld nothing;
    # to keep rings consistent we assign each node ONE seg count = by its own radius, and
    # when parent/child counts differ we bridge by the min count (drop extra parent verts).
    def segs_for(r):
        if r > 0.07: return 10
        if r > 0.035: return 8
        if r > 0.018: return 6
        return 4

    # Build a ring per node (cached) with a parallel-transported reference normal.
    # ring_cache[node] = (idx_list, segs, normal_used, tangent_used)
    ring_cache = {}

    # root tangent = toward its first child (or up)
    def node_tangent(n):
        if n.children:
            d = (n.children[0].pos - n.pos)
            if d.length > 1e-6 and fin(d):
                return d.normalized()
        if n.parent is not None:
            d = (n.pos - n.parent.pos)
            if d.length > 1e-6 and fin(d):
                return d.normalized()
        return Vector((0, 0, 1))

    # iterative DFS carrying the inherited reference normal for parallel transport
    start_t = node_tangent(root)
    start_n = start_t.orthogonal().normalized()
    stack = [(root, start_n)]
    while stack:
        n, ref_n = stack.pop()
        t = node_tangent(n)
        segs = segs_for(max(n.radius, 1e-4))
        idx, used_n = _ring_at(n.pos, t, ref_n, max(n.radius, 1e-4), segs, VERTS)
        ring_cache[n] = (idx, segs)
        for c in n.children:
            # parallel transport the normal across the bend (project onto child tangent plane)
            stack.append((c, used_n))

    # bridge parent ring -> child ring
    stack = [root]
    while stack:
        n = stack.pop()
        idx_n, sp_n = ring_cache[n]
        ga = n.depth_d / max_d
        for c in n.children:
            stack.append(c)
            idx_c, sp_c = ring_cache[c]
            sp = min(sp_n, sp_c)
            gb = c.depth_d / max_d
            for s in range(sp):
                s2 = (s + 1) % sp
                # sample indices proportionally if counts differ
                a0 = idx_n[(s * sp_n) // sp]
                a1 = idx_n[(s2 * sp_n) // sp]
                b1 = idx_c[(s2 * sp_c) // sp]
                b0 = idx_c[(s * sp_c) // sp]
                FACES.append(([a0, a1, b1, b0], [ga, ga, gb, gb]))

    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in VERTS], [], [f[0] for f in FACES])
    me.update()

    # vertex color "growth" (CORNER, BYTE_COLOR) R=G=B=t
    vc = me.color_attributes.new(name="growth", type='BYTE_COLOR', domain='CORNER').data
    li = 0
    for f in FACES:
        for k in range(4):
            t = max(0.0, min(1.0, f[1][k]))
            vc[li].color = (t, t, t, 1.0); li += 1

    for poly in me.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    me.materials.append(mat)
    tris = sum(max(0, len(f[0]) - 2) for f in FACES)
    return obj, tris

# ------------------------------------------------------------------ materials / scene
def bark_material(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; bsdf = nt.nodes.get("Principled BSDF")
    # procedural bark-ish: noise -> color ramp brown
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 6.0
    noise.inputs["Detail"].default_value = 6.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.06, 0.035, 0.02, 1)
    ramp.color_ramp.elements[1].color = (0.22, 0.14, 0.08, 1)
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs[0])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.9
    return m

def setup_scene():
    sc = bpy.context.scene
    # ground
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
    g = bpy.context.active_object; g.name = "Ground"
    gm = bpy.data.materials.new("GroundMat"); gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.30, 0.34, 0.22, 1)
    gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 1.0
    g.data.materials.append(gm)
    # sun
    bpy.ops.object.light_add(type='SUN'); L = bpy.context.active_object
    L.data.energy = 4.5; L.rotation_euler = (math.radians(48), 0, math.radians(-35))
    # world sky
    sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.62, 0.72, 1)
    sc.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.7
    # render
    sc.render.engine = 'CYCLES'
    try:
        sc.cycles.device = 'CPU'; sc.cycles.samples = RENDER_SAMPLES
    except Exception:
        pass
    sc.render.resolution_x = RES_X; sc.render.resolution_y = RES_Y
    sc.render.film_transparent = False
    return sc

def make_camera(sc, name, loc, look):
    cd = bpy.data.cameras.new(name); cam = bpy.data.objects.new(name, cd)
    sc.collection.objects.link(cam)
    cam.location = Vector(loc); cam.data.lens = 42
    cam.rotation_euler = (Vector(look) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    return cam

# ------------------------------------------------------------------ main
def main():
    os.makedirs(OUT, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = setup_scene()
    mat = bark_material("Bark")

    results = []
    objs = []
    for vi, sd in enumerate(SEEDS):
        rng = random.Random(sd)
        np.random.seed(sd)
        pp = dict(P)
        # per-seed silhouette variation
        pp['crown_rx'] *= rng.uniform(0.85, 1.2)
        pp['crown_ry'] = pp['crown_rx']
        pp['crown_rz'] *= rng.uniform(0.9, 1.25)
        pp['trunk_height'] *= rng.uniform(0.85, 1.15)
        pp['grav'] *= rng.uniform(0.7, 1.3)
        # normalize attractor count to crown volume so node counts stay in a tight band
        vol_scale = (pp['crown_rx'] * pp['crown_ry'] * pp['crown_rz']) / (2.6 * 2.6 * 2.4)
        pp['n_attractors'] = int(P['n_attractors'] * vol_scale)

        nodes, root, max_d = grow(pp, rng)
        obj, tris = build_mesh(nodes, root, max_d, f"Tree_seed{sd}", mat)
        # space the two trees apart
        obj.location.x = vi * 7.0
        objs.append(obj)
        results.append((sd, len(nodes), tris, max_d))
        print(f"[TREE] seed={sd} nodes={len(nodes)} tris={tris} height~{max_d:.2f}", flush=True)

    # ---- renders: 2 angles, each showing both seed variations side by side
    look = Vector((3.5, 0, 3.0))
    cam_front = make_camera(sc, "CamFront", (3.5, -13.0, 4.0), look)
    cam_side  = make_camera(sc, "CamSide",  (15.0, -6.0, 5.0), look)

    rendered = []
    for cname, cam in (("front", cam_front), ("side", cam_side)):
        sc.camera = cam
        fp = os.path.join(OUT, f"tree_{cname}.png")
        sc.render.filepath = fp
        bpy.ops.render.render(write_still=True)
        rendered.append(fp)
        print(f"[TREE] rendered {fp}", flush=True)

    # ---- a single-tree close render of seed0 + a growth-value gradient proof
    for o in objs:
        o.hide_render = (o is not objs[0])
    objs[0].hide_render = False
    cam_close = make_camera(sc, "CamClose", (0.0, -8.5, 3.4), Vector((0, 0, 3.2)))
    sc.camera = cam_close
    fp = os.path.join(OUT, "tree_seed0_closeup.png")
    sc.render.filepath = fp; bpy.ops.render.render(write_still=True)
    rendered.append(fp); print(f"[TREE] rendered {fp}", flush=True)

    # growth gradient proof material on seed0
    gm = bpy.data.materials.new("GrowthGrad"); gm.use_nodes = True
    gt = gm.node_tree
    em = gt.nodes.new("ShaderNodeEmission")
    a2 = gt.nodes.new("ShaderNodeVertexColor"); a2.layer_name = "growth"
    ramp = gt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.05, 0.0, 0.35, 1)
    ramp.color_ramp.elements[1].color = (1.0, 0.9, 0.1, 1)
    sep = gt.nodes.new("ShaderNodeSeparateColor")
    gt.links.new(a2.outputs["Color"], sep.inputs[0])
    gt.links.new(sep.outputs[0], ramp.inputs[0])
    gt.links.new(ramp.outputs[0], em.inputs[0])
    out = gt.nodes["Material Output"]; gt.links.new(em.outputs[0], out.inputs[0])
    objs[0].data.materials.clear(); objs[0].data.materials.append(gm)
    fp = os.path.join(OUT, "tree_seed0_growth.png")
    sc.render.filepath = fp; bpy.ops.render.render(write_still=True)
    rendered.append(fp); print(f"[TREE] rendered {fp}", flush=True)

    print("[TREE] === DONE ===", flush=True)
    for sd, nn, tris, md in results:
        print(f"   seed{sd}: nodes={nn} tris={tris} height={md:.2f}", flush=True)
    for r in rendered:
        print("   render ->", r, flush=True)

if __name__ == "__main__":
    main()
