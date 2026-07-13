"""skeleton.py -- common node schema + vine/tree skeleton adapters.

Wraps the two proven, __main__-guarded skeleton generators
(rnd/vines/vine_scol.py, rnd/trees/tree_gen_sc.py) and re-emits their output
in ONE flat schema so all downstream (skin/foliage/export) is shared:

  node = {'p':Vector, 't':Vector, 'n':Vector|None, 'r':float,
          'parent':int (<child idx, root=-1), 'gt':float 0..1 root->tip}
"""
import bpy, bmesh, math, os, random, sys, importlib.util
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

RND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rnd")


def _load(name, relpath):
    path = os.path.join(RND, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)          # safe: both modules are __main__-guarded
    return m


_vine = _load("pg_vine_scol", os.path.join("vines", "vine_scol.py"))
_tree = _load("pg_tree_gen_sc", os.path.join("trees", "tree_gen_sc.py"))


def fin(v):
    return all(math.isfinite(c) for c in v)


def nrm(v, fb):
    return v.normalized() if v.length > 1e-6 else Vector(fb)


# --------------------------------------------------------------------- targets
def load_target(spec, scene):
    """spec: 'sphere' | 'plane' | <path to .fbx>. Returns the chosen mesh obj."""
    if spec == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=3.0, segments=48, ring_count=32)
        o = bpy.context.active_object
        o.name = "Surface"
        bpy.ops.object.shade_smooth()
        return o
    if spec == "plane":
        bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0, 0, 4))
        o = bpy.context.active_object
        o.rotation_euler = (math.radians(90), 0, 0)  # stand it up as a wall
        bpy.context.view_layer.update()
        o.name = "Surface"
        return o
    if spec == "cube":
        bpy.ops.mesh.primitive_cube_add(size=4.0, location=(0, 0, 2))
        o = bpy.context.active_object
        o.name = "Surface"
        bpy.context.view_layer.update()
        return o
    # otherwise an asset path -- dispatch by extension (.obj / .gltf|.glb / .fbx)
    before = set(scene.objects)
    ext = os.path.splitext(spec)[1].lower()
    if ext == ".obj":
        bpy.ops.wm.obj_import(filepath=spec)              # Blender 5.1 OBJ importer
    elif ext in (".gltf", ".glb"):
        bpy.ops.import_scene.gltf(filepath=spec)
    else:
        bpy.ops.import_scene.fbx(filepath=spec)           # .fbx and fallback
    meshes = [o for o in scene.objects if o.type == 'MESH' and o in (set(scene.objects) - before)]
    if not meshes:
        meshes = [o for o in scene.objects if o.type == 'MESH']
    if not meshes:
        raise SystemExit("load_target: no mesh imported from " + spec)
    # join all imported meshes into ONE target so the vine grows over the whole asset
    if len(meshes) > 1:
        bpy.ops.object.select_all(action='DESELECT')
        for o in meshes:
            o.select_set(True)
        big = max(meshes, key=lambda o: o.dimensions.length)
        bpy.context.view_layer.objects.active = big
        bpy.ops.object.join()
        target = bpy.context.view_layer.objects.active
    else:
        target = meshes[0]
    target.name = "Surface"
    return target


def build_bvh_world(obj):
    """World-space bmesh + BVH + bounds dict for surface-constrained growth."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bm.normal_update()
    bvh = BVHTree.FromBMesh(bm)
    cos = [v.co for v in bm.verts]
    xs = [c.x for c in cos]; ys = [c.y for c in cos]; zs = [c.z for c in cos]
    bounds = dict(xmin=min(xs), xmax=max(xs), ymin=min(ys), ymax=max(ys),
                  zmin=min(zs), zmax=max(zs), ymid=(min(ys) + max(ys)) / 2.0)
    return bm, bvh, bounds


def vine_seeds(bm, bvh, bounds, seed, n_seeds=5):
    """Root several vines on the ACTUAL surface in the lower band, skipping
    downward-facing faces (undersides), each climbing up its local tangent. Sampling
    real surface points (not projecting interior points) makes this work on any shape
    -- wall, sphere, cube -- instead of seeding on the bottom face of a solid."""
    rng = random.Random(seed)
    zmin, zmax = bounds['zmin'], bounds['zmax']
    z_lo = zmin + (zmax - zmin) * 0.03
    z_hi = zmin + (zmax - zmin) * 0.45

    def region(co):
        return z_lo <= co.z <= z_hi

    pts = _vine.sample_surface_attractors(bm, bvh, region, n_pts=n_seeds * 10)
    up = Vector((0, 0, 1))
    cand = []
    for p in pts:
        loc, n, idx, d = bvh.find_nearest(p)
        if loc is None or not fin(loc) or n is None:
            continue
        if n.z < -0.2:                       # skip undersides / bottom faces
            continue
        cand.append((loc, n))
    rng.shuffle(cand)
    seeds_dirs = []
    for loc, n in cand[:n_seeds]:
        climb = nrm(up - up.dot(n) * n, n.orthogonal())   # up along the surface
        d0 = nrm(climb + Vector((rng.uniform(-0.5, 0.5),
                                 rng.uniform(-0.5, 0.5), 0)), climb)
        seeds_dirs.append((loc, d0))
    return seeds_dirs


# --------------------------------------------------------------------- adapters
def vine_skeleton(bm, bvh, bounds, params, seed):
    """Surface-constrained space-colonization vine -> unified flat node list."""
    # expose LOD / density via the proven module globals (read at grow() call time)
    _vine.BUDGET = int(params.get("budget", _vine.BUDGET))
    _vine.MAX_DEPTH = int(params.get("max_depth", _vine.MAX_DEPTH))
    _vine.GROWTH_DZ = float(params.get("growth_dz", _vine.GROWTH_DZ))
    _vine.OFFSET = float(params.get("offset", _vine.OFFSET))

    zmin, zmax = bounds['zmin'], bounds['zmax']
    z_lo = zmin + (zmax - zmin) * 0.05
    z_hi = zmin + (zmax - zmin) * 0.92

    def region(co):
        return z_lo <= co.z <= z_hi

    attractors = _vine.sample_surface_attractors(
        bm, bvh, region, n_pts=int(params.get("n_attractors", 900)))
    seeds_dirs = vine_seeds(bm, bvh, bounds, seed, int(params.get("n_seeds", 5)))
    if not attractors or not seeds_dirs:
        raise SystemExit("vine_skeleton: no attractors/seeds (check target surface)")

    nodes = _vine.grow(bvh, attractors, seeds_dirs, seed,
                       branch_p=float(params.get("branch_p", 0.10)))
    _vine.compute_growth(nodes)
    out = []
    for nd in nodes:
        out.append({'p': nd['p'].copy(), 't': nd['t'].copy(), 'n': nd['n'].copy(),
                    'r': float(nd['r']), 'parent': int(nd['parent']),
                    'gt': float(nd.get('g', 0.0))})
    print(f"[SKEL] vine: {len(out)} nodes (seed {seed})", flush=True)
    return out


def tree_skeleton(params, seed):
    """Space-colonization tree -> unified flat node list (n=None, gt=depth/max_d)."""
    rng = random.Random(seed)
    np.random.seed(seed)
    pp = dict(_tree.P)
    pp.update(params.get("pp", {}))
    # per-seed silhouette variation (same recipe as tree_gen_sc.main)
    pp['crown_rx'] *= rng.uniform(0.85, 1.2)
    pp['crown_ry'] = pp['crown_rx']
    pp['crown_rz'] *= rng.uniform(0.9, 1.25)
    pp['trunk_height'] *= rng.uniform(0.85, 1.15)
    pp['grav'] *= rng.uniform(0.7, 1.3)
    vol = (pp['crown_rx'] * pp['crown_ry'] * pp['crown_rz']) / (2.6 * 2.6 * 2.4)
    pp['n_attractors'] = int(_tree.P['n_attractors'] * vol * params.get("density", 1.0))

    nodes, root, max_d = _tree.grow(pp, rng)
    max_d = max_d or 1.0

    def node_tangent(n):
        if n.children:
            d = n.children[0].pos - n.pos
            if d.length > 1e-6 and fin(d):
                return d.normalized()
        if n.parent is not None:
            d = n.pos - n.parent.pos
            if d.length > 1e-6 and fin(d):
                return d.normalized()
        return Vector((0, 0, 1))

    # BFS from root -> guarantees parent appended (and indexed) before any child
    flat = []
    idx_of = {}
    queue = [root]
    while queue:
        n = queue.pop(0)
        par = idx_of[id(n.parent)] if n.parent is not None else -1
        idx_of[id(n)] = len(flat)
        flat.append({'p': n.pos.copy(), 't': node_tangent(n), 'n': None,
                     'r': float(n.radius), 'parent': par,
                     'gt': float(min(1.0, n.depth_d / max_d))})
        queue.extend(n.children)
    print(f"[SKEL] tree: {len(flat)} nodes (seed {seed}) height~{max_d:.2f}", flush=True)
    return flat
