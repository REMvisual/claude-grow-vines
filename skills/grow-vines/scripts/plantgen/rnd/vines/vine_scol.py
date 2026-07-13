"""
vine_scol.py  --  Surface-constrained SPACE COLONIZATION vine/ivy generator (headless).

WHY a rewrite (vs vine_gen_v2/v3):
  v2/v3 used pure Luft-style per-step force weighting from a few seeds with one
  shared initial direction. Result: spindly, sparse, all sweeping ONE way, and the
  node budget got eaten by a couple of long primary runs => no lush coverage.

This approach (Runions et al. space colonization, constrained to the mesh surface,
fused with Luft adhesion):
  1. Sample many ATTRACTOR points directly ON the target surface inside a growth
     region (area-weighted face sampling). Attractors are what make it LUSH and
     SPACE-FILLING and remove the one-direction bias -- growth chases attractors
     spread all over the wall, not a single heliotropic sweep.
  2. Several seeds, each with a VARIED initial fan direction.
  3. Each iteration, every growing tip finds attractors in its perception cone,
     averages the pull, blends in Luft forces (up heliotropism, gravity, small
     random, surface adhesion), projects onto the surface tangent plane, and snaps
     back to the surface via BVH (thigmotropism / clinging).
  4. Attractors inside kill-radius are consumed -> even coverage, dense fill.
  5. Branching emerges naturally: a node with attractors pulling in clearly
     separated directions spawns an extra tip. Hard node BUDGET + depth cap.
  6. Skeleton -> hex tubes with proper ROOT->TIP taper. Per-vertex normalized
     "growth" value (0 at seed -> 1 at tips, continuous through branches) baked as
     vertex-color layer "growth". Leaf cards instanced along older segments.

Hard-won guards (these crashed earlier protos):
  - global node BUDGET + per-tip depth cap; every Vector finite()-checked.
  - degenerate steps skipped; normalized() always length-guarded.
  - print(flush=True) everywhere.

Run:
  & "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" --background --factory-startup --python vine_scol.py
"""
import bpy, bmesh, math, os, random, sys
import numpy as np
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

# ---------------------------------------------------------------- config
HERE   = os.path.dirname(os.path.abspath(__file__))
OUT    = os.path.join(HERE, "renders")
# standalone-demo target: set VINE_DEMO_FBX to grow over your own wall mesh;
# unset, the demo grows over a primitive wall plane. (The skill entry point
# grow_vine.py never uses this -- it passes the mesh explicitly.)
FBX_IN = os.environ.get("VINE_DEMO_FBX", "")

RING       = 6          # hex tube
GROWTH_DZ  = 0.045      # step length per iteration (skeleton resolution)
OFFSET     = 0.015      # ride this far off the surface (clinging gap)
BUDGET     = 3800       # HARD total skeleton-node cap (crash guard + tri budget)
MAX_DEPTH  = 4          # branch recursion cap
STARVE_MAX = 8          # iters a tip may coast without attractors before dying (tunable)
TARGET_NAME= "Surface"

def P(*a): print("[VINE]", *a, flush=True)
def fin(v): return all(math.isfinite(c) for c in v)
def nrm(v, fb):
    return v.normalized() if v.length > 1e-6 else Vector(fb)

# ---------------------------------------------------------------- surface sampling
def sample_surface_attractors(bm, bvh, region_fn, n_pts, jitter_off=0.0):
    """Area-weighted random points ON the surface, filtered by region_fn(co)->bool."""
    bm.faces.ensure_lookup_table()
    faces = [f for f in bm.faces if len(f.verts) >= 3]
    areas = np.array([f.calc_area() for f in faces], dtype=np.float64)
    if areas.sum() <= 0: return []
    probs = areas / areas.sum()
    pts = []
    tries = 0
    while len(pts) < n_pts and tries < n_pts * 40:
        tries += 1
        f = faces[np.random.choice(len(faces), p=probs)]
        vs = f.verts[:3]
        u, v = random.random(), random.random()
        if u + v > 1.0: u, v = 1.0 - u, 1.0 - v
        co = vs[0].co + u * (vs[1].co - vs[0].co) + v * (vs[2].co - vs[0].co)
        if not fin(co): continue
        if region_fn(co):
            pts.append(Vector(co))
    return pts

# ---------------------------------------------------------------- space colonization grow
def grow(bvh, attractors, seeds_dirs, seed,
         d_perception=1.3,   # attractor sense radius
         d_kill=0.24,        # consume attractor radius (>step => no circling in place)
         w_attract=1.0, w_up=0.18, w_grav=0.03, w_rand=0.16, w_adhere=0.40,
         base_r=0.060, tip_r=0.012, branch_sep=0.9,
         branch_p=0.10):
    """
    Returns list of chains. Each chain = list of node dicts:
      p(pos) n(surf normal) t(tangent dir) r(radius) g(0..1 growth) parent(idx into flat list)
    growth value is computed afterwards from graph distance.
    """
    random.seed(seed); np.random.seed(seed)
    up = Vector((0, 0, 1))

    # KD-tree of attractors for fast nearest queries; track alive set
    A = [Vector(a) for a in attractors if fin(a)]
    alive = [True] * len(A)
    kd = KDTree(len(A))
    for i, a in enumerate(A): kd.insert(a, i)
    kd.balance()

    nodes = []     # flat list of dict(p,n,t,r,depth,parent)
    state = {'n': 0}

    def snap(p):
        loc, n, idx, d = bvh.find_nearest(p)
        return loc, n

    # active tips: dict(pos, dir, normal, depth, parent_idx, length)
    tips = []
    for s, d0 in seeds_dirs:
        loc, n = snap(Vector(s))
        if loc is None or not fin(loc): continue
        p0 = loc + n * OFFSET
        nodes.append(dict(p=p0.copy(), n=n.copy(), t=Vector(d0), r=base_r,
                          depth=0, parent=-1))
        state['n'] += 1
        tips.append(dict(pos=p0.copy(), dir=nrm(Vector(d0), (0, 0, 1)),
                         normal=n.copy(), depth=0, parent=len(nodes) - 1, length=0.0))

    max_iter = 4000
    it = 0
    while tips and state['n'] < BUDGET and it < max_iter:
        it += 1
        new_tips = []
        for tip in tips:
            if state['n'] >= BUDGET: break
            Pp = tip['pos']; D = tip['dir']; N = tip['normal']
            if not (fin(Pp) and fin(D) and fin(N)): continue

            # --- gather attractors in perception cone/sphere (weighted by 1/dist
            #     so the tip is pulled mostly by the NEAREST unclaimed space, which
            #     makes it travel/spread rather than average to a stationary clump)
            near = kd.find_range(Pp, d_perception)
            pull = Vector((0, 0, 0))
            pulled_dirs = []
            n_used = 0
            for (co, idx, dist) in near:
                if not alive[idx]: continue
                dv = co - Pp
                if dv.length < 1e-5: continue
                ddir = dv.normalized()
                # forward-biased perception (don't grow backwards into eaten space)
                if ddir.dot(D) < -0.1: continue
                w = 1.0 / (0.25 + dist)
                pull += ddir * w
                pulled_dirs.append(ddir)
                n_used += 1

            # heliotropism (climb the wall) -- ALWAYS present so a tip that has run
            # out of nearby attractors keeps climbing into fresh territory instead
            # of dying in a clump. This is what makes it cover the whole surface.
            climb = nrm(up - up.dot(N) * N, D)
            attract_dir = nrm(pull, climb) if n_used > 0 else climb

            rv = Vector((random.uniform(-1, 1) for _ in range(3)))
            grav = Vector((0, 0, -1))
            adhere = -N                                   # pull toward surface (clinging)

            # if starved of attractors, coast on momentum (mild climb) only briefly
            wa = w_attract if n_used > 0 else 0.0
            wu = w_up if n_used > 0 else 0.45

            des = (attract_dir * wa +
                   climb * wu +
                   rv * w_rand +
                   grav * w_grav +
                   adhere * w_adhere)
            des = des - des.dot(N) * N                    # tangent projection
            des = nrm(des, climb)
            # strong momentum => smooth travelling vines, not jittery clumps
            D2 = nrm(D * 0.62 + des * 0.38, N)

            # a starved tip coasts only briefly then dies (no long droops)
            tip['starve'] = tip.get('starve', 0) + (1 if n_used == 0 else 0)
            if tip['starve'] > STARVE_MAX:
                continue

            # --- step + snap to surface (clinging)
            loc, n2 = snap(Pp + D2 * GROWTH_DZ)
            if loc is None or not fin(loc) or not fin(n2): continue
            Pn = loc + n2 * OFFSET
            step = Pn - Pp
            if step.length < 1e-5: continue
            Dn = step.normalized()

            depth = tip['depth']
            r = base_r * (0.55 ** depth)   # thinner per branch level (taper handled later globally)
            nodes.append(dict(p=Pn.copy(), n=n2.copy(), t=Dn.copy(), r=r,
                              depth=depth, parent=tip['parent']))
            new_idx = len(nodes) - 1
            state['n'] += 1

            # --- consume attractors
            for (co, idx, dist) in kd.find_range(Pn, d_kill):
                alive[idx] = False

            # --- branching: RARE lateral offshoots (probabilistic). Only fire when
            #     the tip is on an established run (some length) and depth allows.
            #     Direction = fanned off the main dir along the surface (lateral
            #     spread), biased toward a divergent attractor cluster if one exists.
            if (depth < MAX_DEPTH and state['n'] < BUDGET and
                    tip['length'] > 0.5 and random.random() < branch_p):
                bdir = None
                if len(pulled_dirs) >= 2:
                    best = None; bestdot = 2.0
                    for pd in pulled_dirs:
                        dt = pd.dot(Dn)
                        if dt < bestdot: bestdot = dt; best = pd
                    if best is not None and bestdot < 0.6:
                        bdir = nrm(best - best.dot(n2) * n2, Dn)
                if bdir is None:
                    # fan laterally off the main direction (left/right along surface)
                    side = random.choice([-1, 1])
                    lat = nrm(Dn.cross(n2), n2.orthogonal()) * side
                    ang = math.radians(random.uniform(35, 65))
                    bdir = nrm(Dn * math.cos(ang) + lat * math.sin(ang), Dn)
                new_tips.append(dict(pos=Pn.copy(), dir=bdir, normal=n2.copy(),
                                     depth=depth + 1, parent=new_idx, length=0.0))

            # continue the main tip (reset starve counter when it found attractors)
            new_tips.append(dict(pos=Pn.copy(), dir=Dn, normal=n2.copy(),
                                 depth=depth, parent=new_idx,
                                 length=tip['length'] + step.length,
                                 starve=0 if n_used > 0 else tip['starve']))
        tips = new_tips

    P(f"  grow: nodes={state['n']} iters={it} attractors_left={sum(alive)}/{len(A)}")
    return nodes

# ---------------------------------------------------------------- growth value (root->tip)
def compute_growth(nodes):
    """Graph distance from root, normalized 0..1 per connected tree, continuous
    through branches (a branch inherits its parent's distance)."""
    n = len(nodes)
    dist = [0.0] * n
    # nodes are appended in growth order, parent index < child index always,
    # so a single forward pass gives correct accumulated distance.
    for i, nd in enumerate(nodes):
        par = nd['parent']
        if par >= 0:
            seg = (nd['p'] - nodes[par]['p']).length
            dist[i] = dist[par] + seg
    mx = max(dist) if dist else 1.0
    mx = mx if mx > 1e-6 else 1.0
    for i, nd in enumerate(nodes):
        nd['g'] = dist[i] / mx
    return mx

# ---------------------------------------------------------------- build mesh
def build(nodes, name, bk_mat, lf_mat, leaf_srcs):
    bm = bmesh.new()
    cl = bm.loops.layers.color.new("growth")
    u0 = bm.loops.layers.uv.new("UVMap")
    ug = bm.loops.layers.uv.new("growth")

    def addface(coords, uvs, gts, mi):
        if not all(fin(c) for c in coords): return
        try:
            vs = [bm.verts.new(c) for c in coords]
            f = bm.faces.new(vs)
        except ValueError:
            return
        f.material_index = mi; f.smooth = True
        for k, lp in enumerate(f.loops):
            lp[u0].uv = uvs[k]; lp[ug].uv = (gts[k], 0.5)
            g = gts[k]; lp[cl] = (g, g, g, 1.0)

    # global taper: radius shrinks with growth value so tips are thin everywhere
    def radius(nd):
        base = nd['r']
        return max(0.004, base * (1.0 - 0.7 * nd['g']))

    def ringco(p, t, ref, r):
        t = nrm(t, (0, 0, 1))
        n = nrm(ref - ref.dot(t) * t, t.orthogonal())
        b = nrm(t.cross(n), n.orthogonal())
        out = []
        for s in range(RING):
            a = (s / RING) * math.tau
            v = p + (math.cos(a) * n + math.sin(a) * b) * r
            out.append(v if fin(v) else p.copy())
        return out

    # precompute child links for tube connectivity
    children = {}
    for i, nd in enumerate(nodes):
        par = nd['parent']
        if par >= 0: children.setdefault(par, []).append(i)

    # build a tube segment for every parent->child edge
    vlen_cache = {}
    for i, nd in enumerate(nodes):
        par = nd['parent']
        if par < 0: continue
        a = nodes[par]; b = nd
        ta = nrm(b['p'] - a['p'], a['t'])
        ra = radius(a); rb = radius(b)
        rgA = ringco(a['p'], ta, a['n'], ra)
        rgB = ringco(b['p'], ta, b['n'], rb)
        ga, gb = a['g'], b['g']
        va = ga * 8.0; vb = gb * 8.0  # bark V tiling along length
        for s in range(RING):
            s2 = (s + 1) % RING
            addface([rgA[s], rgA[s2], rgB[s2], rgB[s]],
                    [(s / RING, va), ((s + 1) / RING, va),
                     ((s + 1) / RING, vb), (s / RING, vb)],
                    [ga, ga, gb, gb], 0)

    # leaves: instance Baga (or fallback) leaf cards along EVERY node, multiple per
    # node -> dense lush canopy that hides the stems (real ivy is mostly leaf).
    if leaf_srcs:
        for i, nd in enumerate(nodes):
            # leaves everywhere, a bit fewer at the very thinnest tips
            n_leaves = 2 if nd['g'] < 0.85 else 1
            for li_ in range(n_leaves):
                src, sc = random.choice(leaf_srcs)
                N = nd['n']; al = nrm(nd['t'], N.orthogonal())
                side = random.choice([-1, 1])
                ua0 = nrm(al.cross(N), N.orthogonal()) * side
                # random roll around the stem so leaves fan in all directions
                roll = random.uniform(0, math.tau)
                ua = nrm(ua0 * math.cos(roll) + N * math.sin(roll), ua0)
                va = nrm(al * random.uniform(0.5, 0.9) + N * 0.4 + ua * random.uniform(-0.3, 0.3), N)
                za = nrm(ua.cross(va), N)
                basis = Matrix(((ua.x, va.x, za.x),
                                (ua.y, va.y, za.y),
                                (ua.z, va.z, za.z)))
                scl = sc * random.uniform(1.0, 1.8)
                off = nd['p'] + N * 0.012 + ua * random.uniform(-0.02, 0.02)
                M = (Matrix.Translation(off) @
                     basis.to_4x4() @ Matrix.Scale(scl, 4))
                uvl = src.uv_layers.active.data if src.uv_layers.active else None
                for poly in src.polygons:
                    coords = [M @ src.vertices[vi].co for vi in poly.vertices]
                    uvs = ([tuple(uvl[li].uv) for li in poly.loop_indices]
                           if uvl else [(0, 0)] * len(poly.vertices))
                    addface(coords, uvs, [nd['g']] * len(poly.vertices), 1)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=5e-4)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(bk_mat); me.materials.append(lf_mat)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    tris = sum(max(0, len(p.vertices) - 2) for p in me.polygons)
    return obj, tris

# ---------------------------------------------------------------- materials
def make_bark_mat(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.13, 0.09, 0.05, 1)
    b.inputs["Roughness"].default_value = 0.9
    return m

def make_leaf_card_mat(name):
    """Fallback procedural leaf material (used if Baga assets unavailable)."""
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.10, 0.32, 0.07, 1)
    b.inputs["Roughness"].default_value = 0.55
    return m

def make_leaf_card_geo():
    """A simple quad leaf-card mesh datablock (fallback) with a UV layer."""
    me = bpy.data.meshes.new("leafcard")
    verts = [(-0.06, 0, 0), (0.06, 0, 0), (0.05, 0.13, 0), (-0.05, 0.13, 0)]
    me.from_pydata(verts, [], [(0, 1, 2, 3)]); me.update()
    me.uv_layers.new(name="UVMap")
    uvd = me.uv_layers.active.data
    for lp, uv in zip(uvd, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        lp.uv = uv
    return me

# ---------------------------------------------------------------- scene setup
def main():
    os.makedirs(OUT, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    # --- target surface
    if FBX_IN and os.path.exists(FBX_IN):
        bpy.ops.import_scene.fbx(filepath=FBX_IN)
    else:
        bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0, 0, 4))
        bpy.context.active_object.rotation_euler = (math.radians(90), 0, 0)
        bpy.context.view_layer.update()
    meshes = [o for o in sc.objects if o.type == 'MESH']
    if not meshes:
        P("ERROR no mesh imported"); return
    target = max(meshes, key=lambda o: o.dimensions.length)
    target.name = TARGET_NAME
    P("target:", target.name, "dims", tuple(round(x, 2) for x in target.dimensions),
      "loc", tuple(round(x, 2) for x in target.location))

    # world-space bmesh + BVH
    bm = bmesh.new(); bm.from_mesh(target.data); bm.transform(target.matrix_world)
    bvh = BVHTree.FromBMesh(bm)

    # bounds (world)
    cos = [v.co for v in bm.verts]
    xs = [c.x for c in cos]; ys = [c.y for c in cos]; zs = [c.z for c in cos]
    xmin, xmax = min(xs), max(xs); zmin, zmax = min(zs), max(zs)
    ymid = (min(ys) + max(ys)) / 2.0
    P("bounds X", round(xmin, 2), round(xmax, 2), "Z", round(zmin, 2), round(zmax, 2),
      "Ymid", round(ymid, 2))

    # growth region: lower-mid of the wall (vines start low, climb up)
    z_lo = zmin + (zmax - zmin) * 0.05
    z_hi = zmin + (zmax - zmin) * 0.92
    def region(co):
        return z_lo <= co.z <= z_hi

    # --- attractors ON surface
    attractors = sample_surface_attractors(bm, bvh, region, n_pts=900)
    P("attractors sampled:", len(attractors))

    # --- seeds along the bottom, each with a VARIED fan direction (kills the
    #     one-direction look of v2/v3)
    # seeds spread across X at varied low/mid heights (several ivy plants rooted
    # at different spots) -> more even coverage, varied per-seed fan direction
    seed_xs = np.linspace(xmin + (xmax - xmin) * 0.10,
                          xmax - (xmax - xmin) * 0.10, 5)
    seeds_dirs = []
    for k, sx in enumerate(seed_xs):
        zf = 0.06 + 0.20 * random.random()   # rooted low-ish, slightly varied
        target_pt = Vector((sx, ymid, zmin + (zmax - zmin) * zf))
        loc, n, idx, d = bvh.find_nearest(target_pt)
        if loc is None or not fin(loc): continue
        # varied initial direction: up + strong lateral fan (kills one-direction look)
        fan = random.uniform(-1.1, 1.1)
        up = Vector((0, 0, 1))
        tangent_x = nrm(Vector((1, 0, 0)) - Vector((1, 0, 0)).dot(n) * n, Vector((1, 0, 0)))
        d0 = nrm(up * random.uniform(0.5, 0.9) + tangent_x * fan, up)
        seeds_dirs.append((loc, d0))
    P("seeds:", len(seeds_dirs))

    bm.free()

    # --- leaf sources: try Baga (if installed), fallback to procedural quad
    leaf_srcs = []
    lf_mat = None
    _baga = os.environ.get("BAGAIVY_DIR", "")
    DB = os.path.join(_baga, "BagaIvy_AssetsDatabase.blend") if _baga else ""
    LEAF_NAMES = ["Hedera_helix_004", "Hedera_helix_005", "Hedera_helix_006"]
    if DB and os.path.exists(DB):
        try:
            with bpy.data.libraries.load(DB) as (s, d):
                d.objects = [n for n in s.objects if n in LEAF_NAMES]
            lf_objs = [o for o in d.objects if o and o.type == 'MESH' and o.data.materials]
            if lf_objs:
                lf_mat = lf_objs[0].data.materials[0]
                for o in lf_objs:
                    dim = max(o.dimensions)
                    sc_n = (0.12 / dim) if dim > 1e-5 else 1.0
                    leaf_srcs.append((o.data, sc_n))
                P("Baga leaves loaded:", [o.name for o in lf_objs])
        except Exception as e:
            P("Baga load failed:", e)
    if not leaf_srcs:
        lf_mat = make_leaf_card_mat("LeafFallback")
        leaf_srcs = [(make_leaf_card_geo(), 1.0)]
        P("using fallback procedural leaf card")

    # --- GROW
    bk_mat = make_bark_mat("Bark")
    nodes = grow(bvh, attractors, seeds_dirs, seed=42)
    maxd = compute_growth(nodes)
    P("growth max graph dist:", round(maxd, 2))
    obj, tris = build(nodes, "Vine_wall", bk_mat, lf_mat, leaf_srcs)
    P("Vine_wall tris:", tris)

    # --- matte the target so vine reads
    target.data.materials.clear()
    sm = bpy.data.materials.new("S"); sm.use_nodes = True
    sm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.62, 0.6, 0.57, 1)
    sm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.95
    target.data.materials.append(sm)

    # --- lighting + world
    bpy.ops.object.light_add(type='SUN'); L = bpy.context.active_object
    L.data.energy = 4.0; L.rotation_euler = (math.radians(52), 0, math.radians(-25))
    sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.6, 0.66, 1)

    # --- render
    sc.render.engine = 'CYCLES'
    try: sc.cycles.device = 'CPU'; sc.cycles.samples = 20
    except Exception: pass
    sc.render.resolution_x = 1200; sc.render.resolution_y = 800

    cd = bpy.data.cameras.new("C"); cam = bpy.data.objects.new("C", cd)
    sc.collection.objects.link(cam); sc.camera = cam; cam.data.lens = 32

    cx = (xmin + xmax) / 2.0; cz = (zmin + zmax) / 2.0
    look = Vector((cx, ymid, cz))
    def render(fp, loc):
        cam.location = loc
        cam.rotation_euler = (look - cam.location).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = os.path.join(OUT, fp)
        bpy.ops.render.render(write_still=True); P("rendered", fp)

    span = max(xmax - xmin, zmax - zmin)
    render("wall_front.png", Vector((cx, ymid - span * 1.1, cz + span * 0.1)))
    render("wall_3q.png",    Vector((cx - span * 0.7, ymid - span * 0.9, cz + span * 0.35)))

    # growth-gradient proof render (emission ramp on "growth")
    gm = bpy.data.materials.new("GRAD"); gm.use_nodes = True; gt = gm.node_tree
    for nd_ in list(gt.nodes): gt.nodes.remove(nd_)
    out = gt.nodes.new("ShaderNodeOutputMaterial")
    e = gt.nodes.new("ShaderNodeEmission")
    a2 = gt.nodes.new("ShaderNodeVertexColor"); a2.layer_name = "growth"
    ramp = gt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.05, 0.0, 0.3, 1)
    ramp.color_ramp.elements[1].color = (1, 0.9, 0.1, 1)
    sep = gt.nodes.new("ShaderNodeSeparateColor")
    gt.links.new(a2.outputs["Color"], sep.inputs[0])
    gt.links.new(sep.outputs[0], ramp.inputs[0])
    gt.links.new(ramp.outputs[0], e.inputs[0])
    gt.links.new(e.outputs[0], out.inputs[0])
    orig = list(obj.data.materials)
    obj.data.materials.clear(); obj.data.materials.append(gm)
    render("wall_growth_gradient.png", Vector((cx, ymid - span * 1.1, cz + span * 0.1)))
    # restore
    obj.data.materials.clear()
    for m in orig: obj.data.materials.append(m)

    P("=== DONE wall ===")

if __name__ == "__main__":
    main()
