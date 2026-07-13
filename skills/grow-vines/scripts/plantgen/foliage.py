"""foliage.py -- Baga leaf/flower card instancing + export-critical fixes.

Vendored & parameterized from rnd/baga_assets/prototype_instance.py (which is an
unguarded script, so it cannot be imported). Provides:

  resolve_species(species)   -> (leaf_names, flower_names) from the audit manifest
  load_cards(db, names)      -> {name: object}  (libraries.load)
  prep_cards(loaded, ...)    -> usable card dicts (poly/uv/material gated)
  add_foliage(bm, skel, ...) -> instance cards along nodes, tag faces w/ host gt
  materialize_textures(mats) -> copy packed pixels -> fresh local PNGs (Baga paths dead)
  flatten_material(mat)      -> flatten Baga node-group BSDF to top-level Principled
"""
import bpy, bmesh, math, os, json, random
from mathutils import Vector, Matrix

# skill-relative: baga_assets is vendored under scripts/assets/ (was <repo>/rnd/)
RND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def _find_baga_dir():
    """Locate the (optional) BagaIvy addon. Order: BAGAIVY_DIR env var, the running
    Blender's user addons dir, then every Blender version's addons dir on this OS.
    Returns None when BagaIvy isn't installed -- callers fall back to the procedural
    leaf-card generator (leaf_fallback.py)."""
    cand = []
    env = os.environ.get("BAGAIVY_DIR")
    if env and env.lower() in ("none", "off", "0", "disabled"):
        return None                       # force the procedural fallback
    if env:
        cand.append(env)
    try:
        p = bpy.utils.user_resource('SCRIPTS', path="addons")
        if p:
            cand.append(os.path.join(p, "BagaIvy"))
    except Exception:
        pass
    import glob as _glob
    roots = []
    if os.environ.get("APPDATA"):                                    # Windows
        roots.append(os.path.join(os.environ["APPDATA"], "Blender Foundation", "Blender"))
    home = os.path.expanduser("~")
    roots.append(os.path.join(home, "Library", "Application Support", "Blender"))  # macOS
    roots.append(os.path.join(home, ".config", "blender"))                          # Linux
    for r in roots:
        cand += _glob.glob(os.path.join(r, "*", "scripts", "addons", "BagaIvy"))
    for c in cand:
        if c and os.path.isfile(os.path.join(c, "BagaIvy_AssetsDatabase.blend")):
            return c
    return None


BAGA_DIR = _find_baga_dir()
DB = os.path.join(BAGA_DIR, "BagaIvy_AssetsDatabase.blend") if BAGA_DIR else ""
IVY_NT = os.path.join(BAGA_DIR, "Ivy_Node_Tree.blend") if BAGA_DIR else ""
MANIFEST = os.path.join(RND, "baga_assets", "baga_asset_manifest.json")
MAX_FLOWER_POLY = 400


def _P(*a):
    print("[FOLIAGE]", *a, flush=True)


def fin(v):
    return all(math.isfinite(c) for c in v)


# ----------------------------------------------------------------- species lookup
def resolve_species(species, max_flower_poly=MAX_FLOWER_POLY):
    """Return (leaf_names, flower_names) by genus prefix from the audit manifest.
    Card naming is irregular across species (Hedera_helix_004 vs
    Trachelospermum_jasminoides_Leaf_001) so we match on name prefix + category."""
    sp = species.lower()
    leaves, flowers = [], []
    try:
        data = json.load(open(MANIFEST))
    except Exception as e:
        # no manifest -> synthesize stable names; load_cards' procedural fallback
        # generates a card per name, so the pipeline still produces foliage.
        _P("manifest load failed:", repr(e), "-- synthesizing fallback card names")
        return ([f"{species}_leaf_{i:03d}" for i in (1, 2, 3)],
                [f"{species}_flower_{i:03d}" for i in (1, 2)])
    for o in data["objects"]:
        if not o["name"].lower().startswith(sp):
            continue
        if o.get("category") == "leaf":
            leaves.append(o["name"])
        elif o.get("category") == "flower" and (o.get("poly_count") or 0) <= max_flower_poly:
            flowers.append(o["name"])
    return leaves, flowers


def _materialize_image(img, dst, noncolor=False):
    """Copy a packed image's decoded pixels into a fresh image with a clean local
    path (Baga/TextureHaven images carry dead filepaths). Returns the new image."""
    w, h = img.size
    if w == 0 or h == 0:
        return None
    px = list(img.pixels[:])
    if not px:
        return None
    ni = bpy.data.images.new(os.path.basename(dst), w, h, alpha=True)
    ni.pixels.foreach_set(px)
    if noncolor:
        ni.colorspace_settings.name = 'Non-Color'
    try:
        ni.filepath_raw = dst; ni.file_format = 'PNG'; ni.save()
        ni.source = 'FILE'; ni.filepath = dst; ni.pack()
    except Exception as e:
        _P("bark image save failed", repr(e))
    return ni


def baga_bark_material(tex_dir, name="BagaBark", uv_scale=(2.0, 1.0, 1.0)):
    """Real bark from Baga's bundled TextureHaven 'Bark Brown 02' (diffuse + normal +
    roughness), rebuilt as a clean Principled on UV0 with tiling. Falls back to None
    if the source blend/material isn't found (caller uses its procedural bark)."""
    if not os.path.exists(IVY_NT):
        return None
    try:
        with bpy.data.libraries.load(IVY_NT) as (s, d):
            d.materials = [n for n in s.materials if "Bark Brown" in n] or \
                          [n for n in s.materials if n == "BIG_Ivy_Bark"]
        src = next((m for m in d.materials if m and m.node_tree), None)
        if not src:
            return None
        diff = norm = rough = None
        for nd in src.node_tree.nodes:
            if nd.type == 'TEX_IMAGE' and nd.image:
                nl = nd.image.name.lower()
                if "diffuse" in nl or "albedo" in nl or "color" in nl:
                    diff = nd.image
                elif "normal" in nl:
                    norm = nd.image
                elif "rough" in nl:
                    rough = nd.image
        os.makedirs(tex_dir, exist_ok=True)
        di = _materialize_image(diff, os.path.join(tex_dir, "bark_diffuse.png")) if diff else None
        if not di:
            return None
        # Use ONLY the (reliable) diffuse + a bump derived from it. The separate
        # normal/roughness maps have generic names ('normal.jpg') that collide with
        # leaf maps already in the scene and materialize blank -> shiny-black bark.
        m = bpy.data.materials.new(name); m.use_nodes = True
        nt = m.node_tree; nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (500, 0)
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
        bsdf.inputs["Roughness"].default_value = 0.9
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = "UVMap"; uvn.location = (-700, 0)
        mp = nt.nodes.new("ShaderNodeMapping"); mp.location = (-500, 0)
        mp.inputs["Scale"].default_value = uv_scale
        nt.links.new(uvn.outputs["UV"], mp.inputs["Vector"])
        dn = nt.nodes.new("ShaderNodeTexImage"); dn.image = di; dn.location = (-250, 100)
        nt.links.new(mp.outputs["Vector"], dn.inputs["Vector"])
        nt.links.new(dn.outputs["Color"], bsdf.inputs["Base Color"])
        # no bump: the Bark Brown 02 diffuse already carries the relief; a bump derived
        # from albedo luminance reads fake. Keep it flat + rough.
        _P("baga bark material built (TextureHaven Bark Brown 02, diffuse)")
        return m
    except Exception as e:
        _P("baga_bark_material failed:", repr(e))
        return None


def species_leaf_material(species, tex_dir):
    """Build a standalone flattened leaf material (RGBA cutout on UVMap) for a species,
    e.g. to texture an imported ABC's foliage object. Returns the material or None."""
    leaf_names, _ = resolve_species(species)
    if not leaf_names:
        return None
    loaded = load_cards(leaf_names[:1])
    cards = prep_cards(loaded, leaf_names[:1], 0.1, "leaf")
    if not cards:
        return None
    mat = cards[0]["mat"]
    remap = materialize_textures([mat], tex_dir)
    flatten_material(mat, remap)
    return mat


def load_cards(names, db=None):
    db = db or DB
    if not db or not os.path.exists(db):
        _P("Baga DB not found -- generating procedural fallback leaf cards")
        from plantgen import leaf_fallback
        return leaf_fallback.build_cards(names)
    with bpy.data.libraries.load(db) as (src, dst):
        avail = set(src.objects)
        dst.objects = [n for n in names if n in avail]
    return {o.name: o for o in dst.objects if o is not None}


def prep_cards(loaded, names, target, kind, max_flower_poly=MAX_FLOWER_POLY):
    cards = []
    for nm in names:
        o = loaded.get(nm)
        if not o or o.type != 'MESH' or not o.data:
            continue
        me = o.data
        if len(me.polygons) == 0:
            continue
        if kind == "flower" and len(me.polygons) > max_flower_poly:
            continue
        if not me.uv_layers.active:
            continue
        if not [m for m in me.materials if m]:
            continue
        dim = max(o.dimensions)
        scl = (target / dim) if dim > 1e-5 else 1.0
        # anchor = the petiole TIP in card-local space (bottom-centre of the length axis Y),
        # so leaves attach to the branch by their stem and scale-in pivots from that tip.
        # VINE_LEAF_ANCHOR_END flips which Y end is the petiole if the card model is inverted.
        vs = me.vertices
        xs = [v.co.x for v in vs]; ys = [v.co.y for v in vs]; zs = [v.co.z for v in vs]
        ay = min(ys) if os.environ.get("VINE_LEAF_ANCHOR_END", "min") == "min" else max(ys)
        anchor = Vector(((min(xs) + max(xs)) * 0.5, ay, (min(zs) + max(zs)) * 0.5))
        cards.append({"name": nm, "me": me, "scl": scl, "anchor": anchor,
                      "mat": [m for m in me.materials if m][0], "kind": kind})
    return cards


# ----------------------------------------------------------------- orientation
def _phyllotaxis_basis(tangent, phase, tilt, roll):
    """Golden-angle phyllotaxis basis around a branch (no surface normal).
    Card local axes: X=width, Y=length, Z=flat normal -> cardZ faces outward."""
    t = tangent.normalized() if tangent.length > 1e-6 else Vector((0, 0, 1))
    up = Vector((0, 0, 1))
    ref = up if abs(t.dot(up)) < 0.95 else Vector((0, 1, 0))
    side0 = t.cross(ref).normalized()
    out0 = side0.cross(t).normalized()
    ca, sa = math.cos(phase), math.sin(phase)
    out = (out0 * ca + side0 * sa).normalized()
    cardZ = out
    cardY = (out * math.sin(tilt) + t * math.cos(tilt)).normalized()
    cardX = cardY.cross(cardZ).normalized()
    cardY = cardZ.cross(cardX).normalized()
    cr, sr = math.cos(roll), math.sin(roll)
    rX = (cardX * cr + cardY * sr).normalized()
    rY = (cardY * cr - cardX * sr).normalized()
    return Matrix(((rX.x, rY.x, cardZ.x),
                   (rX.y, rY.y, cardZ.y),
                   (rX.z, rY.z, cardZ.z)))


def _surface_basis(t_along, surf_n, rng):
    """Natural clinging-ivy leaf: the card lies roughly FLAT against the surface
    (card normal ~ surface normal, leaf face outward), its length pointing up-and-along
    the stem (petiole), with only a small per-leaf in-plane rotation and a slight
    upward lift toward light -- not a full random roll that sprays leaves everywhere."""
    up = Vector((0, 0, 1))
    N = surf_n.normalized() if surf_n.length > 1e-6 else up
    al = t_along - t_along.dot(N) * N                 # stem dir in the wall plane
    al = al.normalized() if al.length > 1e-4 else N.orthogonal().normalized()
    up_t = up - up.dot(N) * N
    up_t = up_t.normalized() if up_t.length > 1e-4 else al
    yaxis = (al * 0.6 + up_t * 0.4)                   # length axis: along stem, leaning up
    yaxis = yaxis.normalized() if yaxis.length > 1e-4 else al
    ang = rng.uniform(-0.5, 0.5)                      # small in-plane spread (~±28°)
    xax0 = yaxis.cross(N).normalized()
    yaxis = (yaxis * math.cos(ang) + xax0 * math.sin(ang)).normalized()
    # tilt the blade OFF the surface so the leaf STANDS OUT from the branch (petiole tip on
    # the branch, blade lifted) instead of lying flat/clinging and intersecting the tube.
    lift = float(os.environ.get("VINE_LEAF_LIFT", "0.5"))
    yaxis = (yaxis + N * lift).normalized()
    cardZ = (N * 0.9 + yaxis * 0.22).normalized()     # face out, slight upward tip
    cardX = yaxis.cross(cardZ).normalized()
    cardY = cardZ.cross(cardX).normalized()
    return Matrix(((cardX.x, cardY.x, cardZ.x),
                   (cardX.y, cardY.y, cardZ.y),
                   (cardX.z, cardY.z, cardZ.z))), N


# ----------------------------------------------------------------- instancing
def add_foliage(bm, skel, uv_layer, gt_face_layer, col_layer, leaf_cards,
                flower_cards, mat_base, mode, params, seed, vlayers=None):
    """Instance leaf/flower cards along the skeleton. Each merged face is tagged
    with its host node's gt (so leaves reveal with their branch) and UV0 carries
    the card's own texture UV. Returns the ordered list of materials used.

    vlayers (optional): bmesh vert layers 'is_card','gt_point','pivot' so the
    growth-anim reveal can SCALE each card in from its stem point (grow, not pop)."""
    rng = random.Random(seed * 31 + 7)
    local_mats = []
    midx = {}

    def mat_index(m):
        key = id(m)
        if key not in midx:
            midx[key] = len(local_mats)
            local_mats.append(m)
        return mat_base + midx[key]

    def add_card(card, M, gt, pivot_world=None):
        me = card["me"]
        uvl = me.uv_layers.active.data
        mi = mat_index(card["mat"])
        # pivot = the petiole-tip attachment point (passed in) -> scale-in grows FROM the
        # branch, not the card centre. Falls back to M's origin for flower/tree cards.
        pv = pivot_world if pivot_world is not None else M.to_translation()
        piv = (pv.x, pv.y, pv.z)
        for poly in me.polygons:
            coords = [M @ me.vertices[vi].co for vi in poly.vertices]
            if not all(fin(c) for c in coords):
                continue
            try:
                vs = [bm.verts.new(c) for c in coords]
                f = bm.faces.new(vs)
            except ValueError:
                continue
            f.material_index = mi
            f.smooth = True
            f[gt_face_layer] = gt
            if vlayers is not None:
                for v in vs:
                    v[vlayers['gt_point']] = gt
                    v[vlayers['is_card']] = 1.0
                    v[vlayers['pivot']] = piv
            for k, lp in enumerate(f.loops):
                li = poly.loop_indices[k]
                lp[uv_layer].uv = tuple(uvl[li].uv)
                if col_layer is not None:
                    lp[col_layer] = (gt, gt, gt, 1.0)

    placed_l = placed_f = 0
    scale_mul = float(params.get("leaf_scale_mul", 1.0))
    flower_prob = float(params.get("flower_prob", 0.0))

    if mode == "vine":
        per_node = int(params.get("leaves_per_node", 2))
        density = float(params.get("leaf_density", 0.6))
        # terminal nodes (no children) = the bark tube ENDS. The probabilistic density
        # gate below was leaving these bare at the perimeter (visible naked stubs), so
        # FORCE a leaf on every on-surface tip to cap the stem ends.
        has_child = set()
        for nd in skel:
            p = nd.get('parent', -1)
            if p is not None and p >= 0:
                has_child.add(p)
        for i, nd in enumerate(skel):
            if not nd.get('on_surf', True):
                continue                       # no foliage on the off-screen reach stems
            is_tip = i not in has_child
            # clumpy, NON-uniform density: a smooth field -> denser & sparser patches
            clump = 0.5 + 0.5 * math.sin(i * 0.7 + nd['gt'] * 9.0)   # 0..1 wave
            if not is_tip and rng.random() > density * (0.30 + 1.5 * clump):
                continue                       # gap -> lighter, varied coverage (tips exempt)
            n_leaves = per_node if rng.random() < 0.35 else 1        # mostly 1, sometimes a clump
            if nd['gt'] >= 0.85 and not is_tip:
                n_leaves = 1                   # thin tips stay sparse (real tips keep their leaf)
            for _ in range(n_leaves):
                if not leaf_cards:
                    break
                card = rng.choice(leaf_cards)
                basis, N = _surface_basis(nd['t'], nd['n'] or Vector((0, 0, 1)), rng)
                scl = card["scl"] * rng.uniform(1.0, 1.8) * scale_mul
                # attach point: petiole tip on the bark TUBE's OUTER skin (nd['r'] out from the
                # centreline along the surface normal), not the host-wall surface. nd['p'] is the
                # tube centreline; the tube bulges nd['r'] outward, so anchoring at the wall buried
                # the leaf base under the outward half of the tube -> bark read "above" the leaves.
                # Small extra epsilon so the petiole just clears the bark.
                base_off = float(os.environ.get("VINE_LEAF_BASE_OFF", "0.002"))
                off = nd['p'] + N * (nd.get('r', 0.0) + base_off) + basis.col[0] * rng.uniform(-0.02, 0.02)
                anchor = card.get("anchor", Vector((0, 0, 0)))
                M = (Matrix.Translation(off) @ basis.to_4x4() @ Matrix.Scale(scl, 4)
                     @ Matrix.Translation(-anchor))      # re-anchor card on its petiole tip
                add_card(card, M, nd['gt'], pivot_world=off)
                placed_l += 1
            if flower_cards and rng.random() < flower_prob * (0.4 + nd['gt']):
                fc = rng.choice(flower_cards)
                basis, N = _surface_basis(nd['t'], nd['n'] or Vector((0, 0, 1)), rng)
                M = (Matrix.Translation(nd['p'] + N * 0.015) @ basis.to_4x4()
                     @ Matrix.Scale(fc["scl"] * rng.uniform(0.9, 1.2), 4))
                add_card(fc, M, nd['gt'])
                placed_f += 1
    else:  # tree canopy: sparser, biased to the crown (high gt), phyllotaxis
        gt_min = float(params.get("canopy_gt_min", 0.35))
        site_prob = float(params.get("canopy_density", 0.6))
        per_site = int(params.get("leaves_per_node", 3))
        phase = 0.0
        for nd in skel:
            if nd['gt'] < gt_min:
                continue
            if rng.random() > site_prob:
                continue
            for _ in range(per_site):
                if not leaf_cards:
                    break
                card = rng.choice(leaf_cards)
                phase += math.radians(137.5)
                tilt = math.radians(rng.uniform(35, 60))
                roll = math.radians(rng.uniform(-18, 18))
                basis = _phyllotaxis_basis(nd['t'], phase, tilt, roll)
                scl = card["scl"] * rng.uniform(0.9, 1.3) * scale_mul
                M = Matrix.Translation(nd['p']) @ basis.to_4x4() @ Matrix.Scale(scl, 4)
                add_card(card, M, nd['gt'])
                placed_l += 1
            if flower_cards and rng.random() < flower_prob * (0.4 + nd['gt']):
                fc = rng.choice(flower_cards)
                phase += math.radians(40)
                basis = _phyllotaxis_basis(nd['t'], phase,
                                           math.radians(rng.uniform(10, 30)),
                                           math.radians(rng.uniform(-30, 30)))
                M = (Matrix.Translation(nd['p']) @ basis.to_4x4()
                     @ Matrix.Scale(fc["scl"] * rng.uniform(0.9, 1.2), 4))
                add_card(fc, M, nd['gt'])
                placed_f += 1

    _P(f"placed {placed_l} leaves, {placed_f} flowers ({mode}, {len(local_mats)} mats)")
    return local_mats


# ----------------------------------------------------------------- export fixes
def materialize_textures(mats, tex_dir):
    """Baga images are PACKED but carry a DEAD on-disk filepath, so embed/COPY
    exports nothing. Copy decoded pixels into fresh image datablocks with clean
    local paths, save+pack, and return {orig_name: new_image} for node re-wiring."""
    os.makedirs(tex_dir, exist_ok=True)
    remap = {}
    seen = set()
    n = 0
    for m in mats:
        if not m.node_tree:
            continue
        for nd in m.node_tree.nodes:
            if nd.type == 'TEX_IMAGE' and nd.image and nd.image.name not in seen:
                img = nd.image
                seen.add(img.name)
                base = os.path.splitext(os.path.splitext(img.name)[0])[0]
                safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in base) + ".png"
                dst = os.path.join(tex_dir, safe)
                try:
                    if img.size[0] == 0 or img.size[1] == 0:
                        continue
                    w, h = img.size
                    px = list(img.pixels[:])
                    if not px:
                        continue
                    ni = bpy.data.images.new(safe, w, h, alpha=True)
                    ni.pixels.foreach_set(px)
                    ni.filepath_raw = dst
                    ni.file_format = 'PNG'
                    ni.save()
                    ni.source = 'FILE'
                    ni.filepath = dst
                    ni.pack()
                    remap[img.name] = ni
                    n += 1
                except Exception as e:
                    _P("tex materialize failed", img.name, repr(e))
    _P(f"materialized {n} textures -> {tex_dir}")
    return remap


# tokens that mark a map as NON-base-color (used to identify the color atlas by elimination)
_NONCOLOR = ("alpha", "normal", "rough", "translucent", "translucency", "_ao",
             "ambient", "metal", "spec", "opacity", "bump", "displ", "gloss", "height")


def _pick_img(mat, want, remap):
    """Find the color or alpha map. Color detection is by ELIMINATION (the map with
    no non-color token) so it works for irregular Baga names like
    'hedera_helix_02_leaf_v2' that lack a 'color'/'maps' token entirely."""
    if not mat.node_tree:
        return None
    cands = [nd.image for nd in mat.node_tree.nodes
             if nd.type == 'TEX_IMAGE' and nd.image]
    if want == "alpha":
        for img in cands:
            if "alpha" in img.name.lower():
                return remap.get(img.name, img)
        return None
    # color: prefer an explicit color token; else the first map with NO non-color token
    pri = ("color", "albedo", "diffuse", "basecolor", "_maps", "maps")
    for img in cands:
        nl = img.name.lower()
        if any(t in nl for t in pri) and not any(t in nl for t in _NONCOLOR):
            return remap.get(img.name, img)
    for img in cands:
        if not any(t in img.name.lower() for t in _NONCOLOR):
            return remap.get(img.name, img)
    return None


def _composite_rgba(color_img, alpha_img):
    """Bake the alpha mask into the color image's A channel -> one RGBA cutout
    texture. Required because the FBX material model carries alpha IN the diffuse
    texture; a SEPARATE alpha map is dropped on FBX roundtrip, leaving leaf cards as
    opaque quads (the muddy-brown defect). Returns a fresh packed RGBA image."""
    cw, ch = color_img.size
    if cw == 0 or ch == 0:
        return color_img
    if (alpha_img.size[0], alpha_img.size[1]) != (cw, ch):
        try:
            alpha_img.scale(cw, ch)
        except Exception:
            return color_img
    cpx = list(color_img.pixels[:])
    apx = alpha_img.pixels[:]
    for i in range(cw * ch):
        cpx[i * 4 + 3] = apx[i * 4]          # alpha map's R -> color's A
    name = os.path.splitext(color_img.name)[0] + "_rgba.png"
    ni = bpy.data.images.new(name, cw, ch, alpha=True)
    ni.pixels.foreach_set(cpx)
    base_dir = os.path.dirname(color_img.filepath) or os.path.dirname(color_img.filepath_raw)
    dst = os.path.join(base_dir or ".", name)
    try:
        ni.filepath_raw = dst; ni.file_format = 'PNG'; ni.save()
        ni.source = 'FILE'; ni.filepath = dst; ni.pack()
    except Exception as e:
        _P("rgba composite save failed", repr(e))
    return ni


def flatten_material(mat, remap):
    """Rebuild a Baga card material as a flat top-level Principled BSDF so the FBX
    exporter (which won't recurse into node groups) embeds the maps. The alpha mask
    is baked INTO the color image's RGBA so it survives the FBX roundtrip as a proper
    cutout (color->Base Color, color.Alpha->Alpha)."""
    color = _pick_img(mat, "color", remap)
    alpha = _pick_img(mat, "alpha", remap)
    if color is None and mat.node_tree:
        for nd in mat.node_tree.nodes:
            if nd.type == 'TEX_IMAGE' and nd.image and not any(
                    t in nd.image.name.lower() for t in _NONCOLOR):
                color = remap.get(nd.image.name, nd.image)
                break
    base = color
    if color is not None and alpha is not None:
        base = _composite_rgba(color, alpha)

    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (100, 0)
    bsdf.inputs["Roughness"].default_value = 0.45
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    if base:
        # Pin the leaf texture to UV0 EXPLICITLY. The mesh has UVMap (leaf coords) +
        # 'wipe' (UV1); after an FBX roundtrip 'wipe' can become the active-render UV,
        # so a TexImage with no UV node samples the wipe gradient -> wrong atlas spot ->
        # muddy brown leaves. An explicit UVMap node makes it correct in any importer.
        uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = "UVMap"; uvn.location = (-560, 100)
        cn = nt.nodes.new("ShaderNodeTexImage"); cn.image = base; cn.location = (-300, 100)
        cn.image.colorspace_settings.name = 'sRGB'
        nt.links.new(uvn.outputs["UV"], cn.inputs["Vector"])
        nt.links.new(cn.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(cn.outputs["Alpha"], bsdf.inputs["Alpha"])
    try:
        mat.use_backface_culling = False
    except Exception:
        pass
    try:
        mat.blend_method = 'CLIP'; mat.alpha_threshold = 0.5
    except Exception:
        pass
