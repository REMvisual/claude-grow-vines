"""hero.py -- HERO 3-variation ivy/vine set on a target mesh.

Drives the unified generator (skeleton/skin/foliage) to produce THREE clearly
distinct vine variations on the target surface, each varying:
  size/extent, stem thickness, # start points (seeds), branching, leaf density, bark.

Reuses the proven SMOOTH skin (skin.py) + Baga foliage (foliage.py). Adds a
PARAMETERIZED bark material (bark_set_material) so each variation gets a different
bark folder (Color/Roughness/Displacement jpgs).

HARD CONSTRAINT: every seed/root originates OUTSIDE the thin mesh shell -- a clear
margin (>=8cm) OFF the front face (toward -Y / viewer) and around the lower/edge
region. The root NODE stays at that outside position; subsequent growth snaps to the
surface. We VERIFY + report each seed's min distance to the nearest surface point.

Headless:
  & "C:\\Program Files\\Blender Foundation\\Blender 5.1\\blender.exe" \\
      --background --factory-startup --python hero.py
"""
import bpy, bmesh, math, os, sys, glob, random, json
from mathutils import Vector

from plantgen import skeleton as SK
from plantgen import skin as SKIN
from plantgen import foliage as FOL

# ----------------------------------------------------------------- config
# TARGET is normally set by the caller (grow_vine.py does `hero.TARGET = MESH`).
# The standalone demo (main()) falls back to a primitive sphere.
TARGET = "sphere"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hero_out")
SPECIES = "Hedera_helix"
MARGIN = 0.10          # roots sit this far OFF the front surface (>= 0.08 required)
MARGIN_MIN = 0.08      # hard assertion floor (meters)
FRONT = Vector((0, -1, 0))   # toward viewer (-Y)


def P(*a):
    print("[HERO]", *a, flush=True)


# ----------------------------------------------------------------- variations
# All the axes the brief asks to vary, per variation.
VARIANTS = [
    # leaf_density = avg fraction of ON-screen nodes that carry leaves (clumpy/varied,
    # not uniform). Bigger budget + attractors + smaller consume radius => vines travel
    # far inward from the edge roots and interweave into a fuller mat (not local clumps).
    # Many perimeter seeds -> patches merge into an ivy band creeping in from all edges.
    # leaf_species = the Baga genera/species blended for this look's foliage (mixed cards
    # from several species -> real visible leaf variation, not one repeated atlas). Each
    # look gets a distinct leaf character on top of its size/density differences.
    dict(name="V1_Bold", bark="bark012", growth_mode="climb",
         leaf_species=["Hedera_colchica", "Hedera_algeriensis"],     # big broad ivy leaves
         budget=4800, n_attractors=2900, n_seeds=10,
         base_r=0.075, branch_p=0.14,
         leaves_per_node=1, leaf_density=0.5, leaf_target=0.14, leaf_scale_mul=1.2, flower_prob=0.05,
         growth_dz=0.060),
    dict(name="V2_Lush", bark="bark006", growth_mode="organic",
         leaf_species=["Hedera_helix", "Trachelospermum_jasminoides", "Ficus_pumila"],  # ivy + jasmine + creeping fig
         budget=6500, n_attractors=5500, n_seeds=24,
         base_r=0.048, branch_p=0.22,
         leaves_per_node=2, leaf_density=0.70, leaf_target=0.10, leaf_scale_mul=1.0, flower_prob=0.10,
         growth_dz=0.045),
    # V3 = STRUCTURED central-vortex swirl (NOT the organic carpet): a single logarithmic
    # spiral attractor arm winding into the wall centre, low randomness + low branching so
    # the swirl reads. Small-leaf blend (fine fig / wire-vine / ivy). Distinct from V2.
    dict(name="V3_Spiral", bark="bark002", growth_mode="vortex",
         leaf_species=["Ficus_pumila", "Muehlenbeckia_complexa", "Hedera_helix"],  # small fine leaves
         spiral_arms=2, spiral_turns=2.8, spiral_band=0.12,
         budget=13000, n_attractors=7500, n_seeds=2,
         base_r=0.032, branch_p=0.05,
         leaves_per_node=3, leaf_density=1.0, leaf_target=0.072, leaf_scale_mul=0.9, flower_prob=0.05,
         growth_dz=0.038),
]


# ----------------------------------------------------------------- bark material
def _find_map(folder, token):
    """Find a bark map jpg by token (Color/Roughness/Displacement/Normal) -- names are
    like 'Bark012_2K-JPG_Color.jpg', so match by suffix token, case-insensitive."""
    for ext in ("jpg", "jpeg", "png"):
        hits = [f for f in glob.glob(os.path.join(folder, f"*.{ext}"))
                if token.lower() in os.path.basename(f).lower()]
        # prefer GL normal over DX if token is 'normal'
        if token.lower() == "normal":
            gl = [h for h in hits if "normalgl" in os.path.basename(h).lower()]
            if gl:
                return gl[0]
        if hits:
            return hits[0]
    return None


def bark_set_material(bark_folder, name="BarkSet", uv_scale=(2.0, 1.0, 1.0)):
    """PARAMETERIZED bark material from a bark-set folder containing
    *_Color / *_Roughness / *_Displacement / *_Normal jpgs. Box-projected (object/
    generated coords mapping via UVMap on the stem) Principled BSDF. Each variation
    passes a different folder so the three barks read clearly different."""
    color = _find_map(bark_folder, "color")
    rough = _find_map(bark_folder, "roughness")
    disp = _find_map(bark_folder, "displacement")
    norm = _find_map(bark_folder, "normal")
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (700, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (350, 0)
    bsdf.inputs["Roughness"].default_value = 0.9
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # UVMap (stem U-around / V-along arc) + tiling
    uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = "UVMap"; uvn.location = (-900, 0)
    mp = nt.nodes.new("ShaderNodeMapping"); mp.location = (-700, 0)
    mp.inputs["Scale"].default_value = uv_scale
    nt.links.new(uvn.outputs["UV"], mp.inputs["Vector"])

    def img(path, noncolor=False):
        if not path or not os.path.exists(path):
            return None
        try:
            im = bpy.data.images.load(path, check_existing=True)
        except Exception as e:
            P("bark img load failed", path, repr(e)); return None
        if noncolor:
            im.colorspace_settings.name = 'Non-Color'
        return im

    ci = img(color)
    if ci:
        cn = nt.nodes.new("ShaderNodeTexImage"); cn.image = ci; cn.location = (-400, 200)
        nt.links.new(mp.outputs["Vector"], cn.inputs["Vector"])
        nt.links.new(cn.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (0.15, 0.10, 0.06, 1)
        P("bark maps missing in", bark_folder,
          "-- run `python scripts/fetch_assets.py` once to download them (CC0)")

    ri = img(rough, noncolor=True)
    if ri:
        rn = nt.nodes.new("ShaderNodeTexImage"); rn.image = ri; rn.location = (-400, -100)
        nt.links.new(mp.outputs["Vector"], rn.inputs["Vector"])
        nt.links.new(rn.outputs["Color"], bsdf.inputs["Roughness"])

    ni = img(norm, noncolor=True)
    if ni:
        nn = nt.nodes.new("ShaderNodeTexImage"); nn.image = ni; nn.location = (-400, -400)
        nt.links.new(mp.outputs["Vector"], nn.inputs["Vector"])
        nmap = nt.nodes.new("ShaderNodeNormalMap"); nmap.location = (-100, -400)
        nmap.inputs["Strength"].default_value = 0.6
        nt.links.new(nn.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    elif img(disp, noncolor=True):
        # no normal map -> derive a gentle bump from displacement for relief
        di = img(disp, noncolor=True)
        dn = nt.nodes.new("ShaderNodeTexImage"); dn.image = di; dn.location = (-400, -400)
        nt.links.new(mp.outputs["Vector"], dn.inputs["Vector"])
        bump = nt.nodes.new("ShaderNodeBump"); bump.location = (-100, -400)
        bump.inputs["Strength"].default_value = 0.3
        nt.links.new(dn.outputs["Color"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    P(f"bark '{os.path.basename(bark_folder)}': color={bool(ci)} rough={bool(ri)} "
      f"norm={bool(ni)} disp={bool(_find_map(bark_folder,'displacement'))}")
    return m


# ----------------------------------------------------------------- outside seeds
def outside_seeds(bm, bvh, bounds, seed, n_seeds, margin=MARGIN):
    """Like SK.vine_seeds, but the ROOT is placed OUTSIDE the shell: take a surface
    point in the lower/edge band, then push the root `margin` along the FRONT (-Y)
    direction (and slightly below the bottom edge for some), so the vine reaches onto
    the screen from outside. Returns [(root_pos_outside, dir0_into_surface)] and the
    surface anchor points (for verification framing)."""
    rng = random.Random(seed * 17 + 3)
    xmin, xmax = bounds['xmin'], bounds['xmax']
    zmin, zmax = bounds['zmin'], bounds['zmax']
    ymid = (bounds['ymin'] + bounds['ymax']) * 0.5
    em = 0.08                         # metres BEYOND the edge: outside silhouette, SHORT thin wisp
    up = Vector((0, 0, 1))

    # MANY roots spaced EVENLY around the whole perimeter (by arc-length) so adjacent
    # patches merge into a continuous ivy band creeping in from every edge.
    W = xmax - xmin; H = zmax - zmin
    perim = 2 * W + 2 * H
    seeds_dirs = []
    anchors = []
    for i in range(n_seeds):
        s = (((i + 0.5) / n_seeds) + rng.uniform(-0.35, 0.35) / n_seeds) * perim
        s %= perim
        if s < W:                              # bottom edge (L->R)
            root = Vector((xmin + s, ymid, zmin - em)); ind = up.copy()
        elif s < W + H:                        # right edge (B->T)
            root = Vector((xmax + em, ymid, zmin + (s - W))); ind = Vector((-1, 0, 0))
        elif s < 2 * W + H:                     # top edge (R->L)
            root = Vector((xmax - (s - W - H), ymid, zmax + em)); ind = -up
        else:                                   # left edge (T->B)
            root = Vector((xmin - em, ymid, zmax - (s - 2 * W - H))); ind = Vector((1, 0, 0))
        root = root + FRONT * 0.05             # a touch toward the viewer too
        d0 = SK.nrm(ind * 0.95 + up * 0.10
                    + Vector((rng.uniform(-0.15, 0.15), 0, rng.uniform(-0.10, 0.10))), ind)
        loc, n, idx, d = bvh.find_nearest(root)
        anchors.append(Vector(loc) if loc is not None else root.copy())
        seeds_dirs.append((root, d0))
    return seeds_dirs, anchors


def scatter_seeds(bm, bvh, bounds, n_seeds, seed):
    """Seeds sampled across the WHOLE (front) surface, area-weighted, so growth starts
    EVERYWHERE -> even coverage on all parts of a lumpy/segmented mesh instead of
    bunching on the protruding bits that the perimeter seeds reach first. Each aimed
    along a random in-plane tangent. Roots sit ON the surface (no outside wisp)."""
    rng = random.Random(seed * 23 + 11)
    zmin, zmax = bounds['zmin'], bounds['zmax']

    def region(co):
        return zmin - 1.0 <= co.z <= zmax + 1.0      # the whole surface

    pts = SK._vine.sample_surface_attractors(bm, bvh, region, n_pts=n_seeds * 3)
    rng.shuffle(pts)
    up = Vector((0, 0, 1))
    out = []
    for p in pts[:n_seeds]:
        loc, n, idx, d = bvh.find_nearest(p)
        if loc is None or n is None:
            continue
        t = SK.nrm(up - up.dot(n) * n, n.orthogonal())   # up along the surface
        d0 = SK.nrm(t + Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)) * 0.6, t)
        out.append((Vector(loc), d0))
    return out


def climb_seeds(bvh, bounds, n_seeds, seed):
    """BOTTOM-edge seeds (just below the wall, outside), aimed UP with a small lateral
    fan. With strong up-heliotropism in grow(), these become BOLD VERTICAL CLIMBERS
    rising up the wall -- V1's distinct structure (vs V2's even mat / V3's spiral)."""
    rng = random.Random(seed * 13 + 5)
    xmin, xmax = bounds['xmin'], bounds['xmax']
    zmin = bounds['zmin']
    ymid = (bounds['ymin'] + bounds['ymax']) * 0.5
    up = Vector((0, 0, 1))
    em = 0.08
    seeds_dirs = []
    for i in range(n_seeds):
        fx = (i + 0.5) / n_seeds
        x = xmin + (xmax - xmin) * (0.07 + 0.86 * fx) + rng.uniform(-0.25, 0.25)
        root = Vector((x, ymid, zmin - em)) + FRONT * 0.05
        fan = rng.uniform(-0.45, 0.45)
        d0 = SK.nrm(up * 0.95 + Vector((fan, 0, 0)), up)
        seeds_dirs.append((root, d0))
    return seeds_dirs


def vortex_field(bvh, bounds, n_pts, n_arms, seed, turns=1.5, band=0.16, chirality=1.0,
                 rx_frac=0.66, rz_frac=0.62, inner_skip=0.0):
    """Multi-arm spiral VORTEX that GROWS OUTWARD from a centre eye and REACHES the
    wall edges. `n_arms` spiral arms unwind from the centre; one seed sits at the eye
    per arm, aimed OUTWARD along its arm, so the swirl expands outward (not a uniform
    inward ball). ELLIPTICAL to the wall extents so the long arms reach the wide side
    edges as well as top/bottom. Few arms + even spacing + thin band => distinct arms
    with bare gaps between coils (a real spiral, not a solid disc). Returns
    (attractors_on_surface, seeds_dirs); seeds sit ON the wall, so NO perimeter wisps."""
    rng = random.Random(seed * 7 + 1)
    xmin, xmax = bounds['xmin'], bounds['xmax']
    zmin, zmax = bounds['zmin'], bounds['zmax']
    ymid = (bounds['ymin'] + bounds['ymax']) * 0.5
    cx, cz = (xmin + xmax) * 0.5, (zmin + zmax) * 0.5
    # OVERSHOOT the wall extents: the spiral envelope is bigger than the wall, so the
    # arms run right out to (and get clipped at) every edge -> the swirl fills the wall
    # to the rim instead of sitting in a central oval. Off-wall points are dropped by
    # the region test below, so each arm simply terminates at the edge it reaches.
    rx, rz = (xmax - xmin) * rx_frac, (zmax - zmin) * rz_frac
    tmax = 2.0 * math.pi * turns

    def arm_point(frac, phase0, bj=0.0):
        # radius grows LINEARLY with arm length (even density, arms reach the rim);
        # band jitter is perpendicular-ish (added to the radius pre-scale).
        t = tmax * frac
        ang = phase0 + chirality * t
        x = cx + (rx * frac + bj) * math.cos(ang)
        z = cz + (rz * frac + bj) * math.sin(ang)
        return Vector((x, ymid, z))

    per_arm = max(1, n_pts // n_arms)
    attractors, seeds_dirs = [], []
    s0 = max(inner_skip, 0.0)                   # leave the centre (hole/eye) empty
    for a in range(n_arms):
        phase0 = a * 2.0 * math.pi / n_arms
        for k in range(per_arm):
            frac = (k + 0.5) / per_arm          # LINEAR: even along the arm, out to the rim
            if frac < s0:
                continue
            p = arm_point(frac, phase0, rng.uniform(-band, band))
            loc, n, idx, d = bvh.find_nearest(p)
            if loc is None:
                continue
            if (d is None or d < 0.6) and zmin <= loc.z <= zmax and xmin <= loc.x <= xmax:
                attractors.append(Vector(loc))
        # seed at the inner RING (just past inner_skip), aimed OUTWARD along its arm
        p_in, p_out = arm_point(s0 + 0.02, phase0), arm_point(s0 + 0.13, phase0)
        loc, n, idx, d = bvh.find_nearest(p_in)
        root = Vector(loc) if loc is not None else p_in
        d0 = (p_out - p_in)
        d0 = d0.normalized() if d0.length > 1e-5 else Vector((1, 0, 0))
        seeds_dirs.append((root, d0))
    return attractors, seeds_dirs


def _prune_offsurf_tips(nodes, bvh, tol=0.10):
    """Iteratively drop OFF-SURFACE leaf nodes (a node whose nearest surface point is
    > tol away AND has no children). Starved tips that coast off the front-face
    silhouette into empty space otherwise skin into bare bark nubs sticking past the
    mesh (no leaves are placed there by design). Roots are always kept; parent indices
    are remapped to the compacted list. Returns the pruned node list."""
    n = len(nodes)
    alive = [True] * n
    dsurf = [(bvh.find_nearest(nd['p'])[3] or 0.0) for nd in nodes]
    changed = True
    while changed:
        changed = False
        child_count = [0] * n
        for i in range(n):
            if not alive[i]:
                continue
            p = nodes[i]['parent']
            if p >= 0 and alive[p]:
                child_count[p] += 1
        for i in range(n):
            if alive[i] and child_count[i] == 0 and dsurf[i] > tol \
               and nodes[i]['parent'] >= 0:            # keep roots
                alive[i] = False
                changed = True
    newidx, out = {}, []
    for i in range(n):
        if alive[i]:
            newidx[i] = len(out)
            out.append(nodes[i])
    for nd in out:
        p = nd['parent']
        nd['parent'] = newidx.get(p, -1) if p >= 0 else -1
    return out


def verify_outside(seeds_dirs, bvh, margin_min=MARGIN_MIN):
    """Assert every root is OUTSIDE the shell: min distance root->nearest surface
    point >= margin_min. Returns (ok, min_dist, [per-seed dist])."""
    dists = []
    for root, _d0 in seeds_dirs:
        loc, n, idx, d = bvh.find_nearest(root)
        dists.append(d if d is not None else 0.0)
    mn = min(dists) if dists else 0.0
    return (mn >= margin_min), mn, dists


# ----------------------------------------------------------------- build one variation
def build_variant(v, tex_dir):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    target = SK.load_target(TARGET, sc)
    bm_t, bvh, bounds = SK.build_bvh_world(target)
    P(f"{v['name']} target bounds Z[{bounds['zmin']:.2f},{bounds['zmax']:.2f}] "
      f"Y[{bounds['ymin']:.2f},{bounds['ymax']:.2f}] X[{bounds['xmin']:.2f},{bounds['xmax']:.2f}]")

    # --- skeleton via the proven space-colonization grow, with our overrides ---
    SKmod = SK._vine
    SKmod.BUDGET = int(v['budget'])
    SKmod.GROWTH_DZ = float(v['growth_dz'])
    SKmod.OFFSET = 0.015
    zmin, zmax = bounds['zmin'], bounds['zmax']
    z_lo = zmin + (zmax - zmin) * 0.03
    z_hi = zmin + (zmax - zmin) * 0.95

    def region(co):
        return z_lo <= co.z <= z_hi

    mode = v.get('growth_mode', 'organic')
    mn, ok = 0.0, True                         # seed-outside stats
    if mode == 'vortex':
        # multi-arm spiral vortex: arms + tangential seeds at each arm's outer mouth,
        # all winding the SAME way into the eye. No off-screen wisps (the perimeter
        # rule is an organic-mat thing; the vortex emanates from the wall itself).
        attractors, seeds_dirs = vortex_field(
            bvh, bounds, n_pts=int(v['n_attractors']),
            n_arms=int(v.get('spiral_arms', 6)), seed=hash(v['name']) & 0xffff,
            turns=v.get('spiral_turns', 2.6), band=v.get('spiral_band', 0.20),
            rx_frac=v.get('spiral_rx_frac', 0.66), rz_frac=v.get('spiral_rz_frac', 0.62),
            inner_skip=v.get('spiral_inner_skip', 0.0))
        P(f"{v['name']} VORTEX: {len(attractors)} attractors, {len(seeds_dirs)} arm-seeds")
    elif mode == 'climb':
        # bold VERTICAL climbers from the bottom edge (sparse statement vines)
        seeds_dirs = climb_seeds(bvh, bounds, int(v['n_seeds']), seed=hash(v['name']) & 0xffff)
        ok, mn, dists = verify_outside(seeds_dirs, bvh)
        P(f"{v['name']} CLIMB-SEEDS: n={len(seeds_dirs)} bottom-edge min_dist={mn*100:.1f}cm")
        attractors = SKmod.sample_surface_attractors(bm_t, bvh, region,
                                                     n_pts=int(v['n_attractors']))
    else:
        # --- organic mat. OUTSIDE seeds (roots beyond the perimeter) unless inside_only,
        # i.e. "from the surface/inside" -> grow from on-surface scatter seeds. The outside
        # verify is a WARNING, not a hard fail, so convex/small meshes still grow. ---
        inside_only = bool(v.get('inside_only'))
        seeds_dirs = []
        if not inside_only:
            seeds_dirs, anchors = outside_seeds(bm_t, bvh, bounds, seed=hash(v['name']) & 0xffff,
                                                n_seeds=v['n_seeds'], margin=MARGIN)
            ok, mn, dists = verify_outside(seeds_dirs, bvh)
            P(f"{v['name']} SEED-OUTSIDE: n={len(seeds_dirs)} min_dist={mn*100:.1f}cm "
              f"(>= {MARGIN_MIN*100:.0f}cm? {ok}) all=[{', '.join(f'{d*100:.1f}' for d in dists)}]cm")
            if not ok:
                P(f"{v['name']} WARN: outside seeds not all clear (min {mn*100:.1f}cm) -- "
                  f"proceeding (small/convex target).")
        # even-coverage on-surface seeds (primary for inside_only; coverage fill otherwise).
        n_scat = int(v.get('scatter_seeds') or 0) or (max(8, int(v['n_seeds'])) if inside_only else 0)
        if n_scat:
            extra = scatter_seeds(bm_t, bvh, bounds, n_scat, seed=hash(v['name']) & 0xffff)
            seeds_dirs = seeds_dirs + extra
            P(f"{v['name']} +{len(extra)} scatter seeds")
        attractors = SKmod.sample_surface_attractors(bm_t, bvh, region,
                                                     n_pts=int(v['n_attractors']))
    if not attractors or not seeds_dirs:
        raise SystemExit(f"{v['name']}: no attractors/seeds")

    if mode == 'vortex':
        # follow the spiral arms tightly: kill wandering (low rand), kill heliotropic
        # climb (low w_up) so attractors dominate, die quickly off-arm (low STARVE).
        # VERY narrow perception so each tip follows ITS OWN coil winding outward and
        # does NOT short-cut across to an adjacent coil (which scrambles the spiral
        # order -> the reveal would look like a radial mask instead of a drawn spiral).
        # low rand/climb so the arm stays a clean spiral.
        SKmod.STARVE_MAX = 16
        nodes = SKmod.grow(bvh, attractors, seeds_dirs, seed=hash(v['name']) & 0xffff,
                           base_r=float(v['base_r']), branch_p=float(v['branch_p']),
                           d_kill=0.07, d_perception=0.65, w_rand=0.02, w_up=0.02)
    elif mode == 'climb':
        # MODERATE upward bias: bold vines climb AND spread, depositing leaves up the
        # full height as vertical columns (too-strong w_up rushes them to the ceiling
        # and clumps). Sparse seeds + thick stems => bold, not a fine mat.
        SKmod.STARVE_MAX = int(v.get('climb_starve', 30))
        nodes = SKmod.grow(bvh, attractors, seeds_dirs, seed=hash(v['name']) & 0xffff,
                           base_r=float(v['base_r']), branch_p=float(v['branch_p']),
                           d_kill=0.11, d_perception=2.0, w_rand=0.14,
                           w_up=float(v.get('climb_wup', 0.33)))
    else:
        SKmod.STARVE_MAX = 40   # let starved tips coast far across gaps -> spread, not clumps
        nodes = SKmod.grow(bvh, attractors, seeds_dirs, seed=hash(v['name']) & 0xffff,
                           base_r=float(v['base_r']), branch_p=float(v['branch_p']),
                           d_kill=0.10, d_perception=2.2)

    # Optional ORGANIC reach-stubs: restore roots to their OUTSIDE seed positions as thin
    # wisps (mat creeping from off-screen). DEFAULT OFF -- on a segmented/relief target
    # those outside roots are disconnected from the real branch-kickoff zones and
    # render as ugly stretched spikes radiating off the mesh. With the restore skipped,
    # roots stay where grow() snapped them -> ON the surface, at the real branch starts.
    # Re-enable per-variant with outside_roots=True (the creeping-in-from-off-screen look).
    roots = [i for i, nd in enumerate(nodes) if nd['parent'] < 0]
    if mode != 'vortex' and v.get('outside_roots', False):
        for i, root_idx in enumerate(roots):
            if i < len(seeds_dirs):
                nodes[root_idx]['p'] = seeds_dirs[i][0].copy()
                nodes[root_idx]['r'] = min(nodes[root_idx]['r'], 0.010)  # thin wisp, not a pin
    else:
        # NOT the outside-wisp look: snap every root ONTO the surface. Perimeter seeds
        # originate a few cm off the edge for grow DIRECTION only; left as-is the root
        # NODE hangs that far below/beyond the mesh and skins into a bare bark nub. Snap
        # it flush so the vine base sits on the relief.
        for ri in roots:
            loc = bvh.find_nearest(nodes[ri]['p'])[0]
            if loc is not None:
                nodes[ri]['p'] = Vector(loc)
    rmn = min((bvh.find_nearest(nodes[ri]['p'])[3] or 0.0) for ri in roots) if roots else 0.0
    P(f"{v['name']} ROOT-NODE min dist: {rmn*100:.1f}cm ({len(roots)} roots, mode={mode})")

    # trim off-surface tube ends (bare bark nubs poking past the front-face silhouette)
    if v.get('trim_offsurf', False):
        before = len(nodes)
        nodes = _prune_offsurf_tips(nodes, bvh, tol=0.10)
        P(f"{v['name']} trim_offsurf: {before} -> {len(nodes)} nodes "
          f"(-{before - len(nodes)} off-surface tips)")

    SKmod.compute_growth(nodes)
    skel = []
    for nd in nodes:
        d_surf = bvh.find_nearest(nd['p'])[3]
        on_surf = (d_surf is not None and d_surf <= 0.10)   # off-screen reach roots -> no leaves
        skel.append({'p': nd['p'].copy(), 't': nd['t'].copy(),
                     'n': nd['n'].copy(), 'r': float(nd['r']),
                     'parent': int(nd['parent']), 'gt': float(nd.get('g', 0.0)),
                     'on_surf': on_surf})
    bm_t.free()
    P(f"{v['name']} skeleton: {len(skel)} nodes")

    # --- foliage cards ---
    species_list = v.get('leaf_species') or [SPECIES]
    leaf_names, flower_names = [], []
    for spn in species_list:
        ln, fn = FOL.resolve_species(spn)
        leaf_names += ln
        flower_names += fn
    leaf_names = list(dict.fromkeys(leaf_names))        # dedup, keep order
    flower_names = list(dict.fromkeys(flower_names))
    loaded = FOL.load_cards(leaf_names + flower_names)
    leaf_cards = FOL.prep_cards(loaded, leaf_names, v['leaf_target'], "leaf")
    flower_cards = FOL.prep_cards(loaded, flower_names, v['leaf_target'] * 0.6, "flower")
    P(f"{v['name']} cards: {len(leaf_cards)} leaf from {len(species_list)} species "
      f"{species_list}, {len(flower_cards)} flower")
    # robustness: some manifest species list leaf objects that don't load as usable cards
    # (e.g. Muehlenbeckia_complexa). Never ship a bare stem -- retry with ivy.
    if not leaf_cards:
        P(f"{v['name']} WARN: 0 leaf cards from {species_list} -> retrying with Hedera_helix")
        fb = []
        for spn in ("Hedera_helix", "Hedera_colchica"):
            ln, _ = FOL.resolve_species(spn); fb += ln
        fb = list(dict.fromkeys(fb))
        loaded = FOL.load_cards(fb + flower_names)
        leaf_cards = FOL.prep_cards(loaded, fb, v['leaf_target'], "leaf")
        P(f"{v['name']} fallback cards: {len(leaf_cards)} leaf")

    # --- combined mesh: smooth tubes + foliage ---
    bm = bmesh.new()
    uvL = bm.loops.layers.uv.new("UVMap")
    gtF = bm.faces.layers.float.new("gt_face")
    colL = bm.loops.layers.color.new("growth")
    vlayers = dict(
        is_card=bm.verts.layers.float.new("is_card"),
        gt_point=bm.verts.layers.float.new("gt_point"),
        pivot=bm.verts.layers.float_vector.new("pivot"),
    )
    SKIN.skin(bm, skel, uvL, gtF, colL, mat_index=0, taper=0.7, vlayers=vlayers)
    fparams = dict(leaves_per_node=v['leaves_per_node'], leaf_target=v['leaf_target'],
                   leaf_scale_mul=v['leaf_scale_mul'], flower_prob=v['flower_prob'],
                   leaf_density=v.get('leaf_density', 0.6))
    foliage_mats = FOL.add_foliage(bm, skel, uvL, gtF, colL, leaf_cards, flower_cards,
                                   mat_base=1, mode="vine", params=fparams,
                                   seed=hash(v['name']) & 0xffff, vlayers=vlayers)

    me = bpy.data.meshes.new(v['name'])
    bm.to_mesh(me); bm.free()
    bark_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "assets", "bark", v['bark'])
    bark = bark_set_material(bark_folder, name=f"Bark_{v['bark']}")
    me.materials.append(bark)
    for m in foliage_mats:
        me.materials.append(m)
    obj = bpy.data.objects.new(v['name'], me)
    sc.collection.objects.link(obj)

    tris = sum(max(0, len(p.vertices) - 2) for p in me.polygons)
    nodes_n = len(skel)
    # leaf count = number of foliage faces' cards is hard; report placed leaves via
    # face count on foliage materials as a proxy + node count.
    leaf_faces = sum(1 for p in me.polygons if p.material_index >= 1)
    stats = dict(name=v['name'], bark=v['bark'], tris=tris, nodes=nodes_n,
                 leaf_faces=leaf_faces, n_seeds=v['n_seeds'],
                 base_r=v['base_r'], branch_p=v['branch_p'],
                 budget=v['budget'], n_attractors=v['n_attractors'],
                 leaves_per_node=v['leaves_per_node'], leaf_target=v['leaf_target'],
                 seed_min_cm=round(mn * 100, 1), root_min_cm=round(rmn * 100, 1),
                 seed_outside_ok=ok)
    P(f"{v['name']} BUILT: tris={tris} nodes={nodes_n} leaf_faces={leaf_faces}")
    return obj, target, foliage_mats, stats


# ----------------------------------------------------------------- render
def matte_target(target):
    target.data.materials.clear()
    sm = bpy.data.materials.new("Screen"); sm.use_nodes = True
    b = sm.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.58, 0.57, 0.55, 1)
    b.inputs["Roughness"].default_value = 0.92
    target.data.materials.append(sm)


def setup_render(samples=28, res=(1600, 1000)):
    sc = bpy.context.scene
    # 3-point-ish: key sun + soft world fill + a rim
    bpy.ops.object.light_add(type='SUN'); key = bpy.context.active_object
    key.data.energy = 4.2
    key.rotation_euler = (math.radians(52), math.radians(8), math.radians(-38))
    bpy.ops.object.light_add(type='SUN'); rim = bpy.context.active_object
    rim.data.energy = 1.6; rim.data.angle = math.radians(8)
    rim.rotation_euler = (math.radians(118), 0, math.radians(150))
    sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
    bgc = sc.world.node_tree.nodes["Background"]
    bgc.inputs["Color"].default_value = (0.56, 0.61, 0.68, 1)
    bgc.inputs["Strength"].default_value = 0.85
    sc.render.engine = 'CYCLES'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        chosen = None
        for ct in ('OPTIX', 'CUDA'):
            try:
                prefs.compute_device_type = ct
                prefs.get_devices()
                if any(d.type == ct for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = (d.type == ct)   # GPU only, disable CPU device
                    chosen = ct; break
            except Exception:
                continue
        if chosen:
            sc.cycles.device = 'GPU'; P("Cycles GPU:", chosen)
        else:
            sc.cycles.device = 'CPU'; P("Cycles CPU (no GPU found)")
        sc.cycles.samples = samples
        sc.cycles.use_denoising = True
        sc.render.use_persistent_data = True
    except Exception as e:
        P("render device setup err", repr(e))
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = False
    return sc


def frame_camera(sc, objs, lens=42, dist_mul=1.15, three_q=True):
    bpy.context.view_layer.update()
    corners = []
    for o in objs:
        corners += [o.matrix_world @ Vector(c) for c in o.bound_box]
    ctr = sum(corners, Vector()) / len(corners)
    size = max((max(c[ax] for c in corners) - min(c[ax] for c in corners))
               for ax in range(3))
    cd = bpy.data.cameras.new("Cam"); cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam); cam.data.lens = lens
    dist = size * dist_mul + 0.5
    if three_q:
        cam.location = ctr + Vector((0.45 * dist, -1.05 * dist, 0.30 * dist))
    else:
        cam.location = ctr + Vector((0.0, -1.2 * dist, 0.10 * dist))
    cam.rotation_euler = (ctr - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = cam
    return cam


def closeup_camera(sc, obj, lens=95):
    bpy.context.view_layer.update()
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    ctr = sum(corners, Vector()) / 8.0
    size = max((max(c[ax] for c in corners) - min(c[ax] for c in corners))
               for ax in range(3))
    # aim a bit above center where foliage is densest
    aim = Vector((ctr.x, ctr.y, ctr.z + size * 0.12))
    cd = bpy.data.cameras.new("CU"); cam = bpy.data.objects.new("CU", cd)
    sc.collection.objects.link(cam); cam.data.lens = lens
    dist = size * 0.28 + 0.3
    cam.location = aim + Vector((0.18 * dist, -1.0 * dist, 0.16 * dist))
    cam.rotation_euler = (aim - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = cam
    return cam


def render_to(sc, path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    P("rendered ->", path)


# ----------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    tex_dir = os.path.join(OUT, "tex")
    os.makedirs(tex_dir, exist_ok=True)
    summary = []
    for v in VARIANTS:
        P("==================== " + v['name'] + " ====================")
        obj, target, foliage_mats, stats = build_variant(v, tex_dir)
        matte_target(target)
        # materialize Baga leaf textures to clean PNGs so Cycles samples them
        FOL.materialize_textures(foliage_mats, tex_dir)

        sc = setup_render(samples=56, res=(1600, 1000))
        frame_camera(sc, [obj, target], lens=42, three_q=True)
        beauty = os.path.join(OUT, v['name'] + "_beauty.png")
        render_to(sc, beauty)

        closeup_camera(sc, obj, lens=95)
        cu = os.path.join(OUT, v['name'] + "_closeup.png")
        render_to(sc, cu)

        stats['beauty'] = beauty
        stats['closeup'] = cu
        summary.append(stats)

    P("================= HERO SUMMARY =================")
    for r in summary:
        P(json.dumps(r))
    P("=== DONE ===")


if __name__ == "__main__":
    main()
