"""leaf_fallback.py -- procedural leaf/flower card generator (no BagaIvy required).

When the optional BagaIvy addon isn't installed, foliage.load_cards routes here.
For every requested card name this module synthesizes a card OBJECT that satisfies
the same contract the Baga library objects do (see foliage.prep_cards):

  - MESH with polygons, an active UV layer mapped 0..1 over the card
  - one material whose node tree carries a TEX_IMAGE with a packed RGBA image
    (color in RGB, cutout mask in A) so foliage.materialize_textures /
    flatten_material / the FBX export path work unchanged

Cards are deterministic per name (crc32-seeded), leaf shape/tint varies by the
species prefix of the name, flower cards get a petal rosette. These are stylized
painterly cards -- good silhouettes at set-dressing distance -- not photoscans;
install BagaIvy for photoreal foliage.
"""
import bpy, math, os, zlib, random
import numpy as np
from mathutils import Vector

TEX_W = TEX_H = 256
CARD_LEN = 0.16          # metres, typical leaf blade length (prep_cards rescales anyway)


def _P(*a):
    print("[LEAF-FB]", *a, flush=True)


# ----------------------------------------------------------------- texture paint
def _leaf_pixels(rng, tint):
    """Vectorized painterly leaf: lobed silhouette + veins + edge darkening.
    Returns float32 (H,W,4) RGBA, petiole at v=0, tip at v=1."""
    u, v = np.meshgrid(np.linspace(-0.5, 0.5, TEX_W, dtype=np.float32),
                       np.linspace(0.0, 1.0, TEX_H, dtype=np.float32))
    t = np.clip(v, 1e-4, 1.0)
    # half-width profile: ovate base, optional ivy lobes, light serration
    lobe = rng.uniform(0.0, 0.35)
    wmax = rng.uniform(0.30, 0.42)
    w = wmax * np.sin(math.pi * t ** rng.uniform(0.65, 0.9))
    w = w * (1.0 + lobe * np.sin(3.0 * math.pi * t) * np.exp(-2.5 * t))
    w = w * (1.0 + 0.03 * np.sin(46.0 * math.pi * t))          # serrated edge
    inside = np.abs(u) < w
    # shading: base green, darker toward the rim, lighter along the mid gradient
    edge = np.clip(np.abs(u) / np.maximum(w, 1e-4), 0.0, 1.0)
    g = 0.28 + 0.30 * (1.0 - edge) + 0.10 * np.sin(math.pi * t)
    r = g * tint[0]
    b = g * tint[2]
    gg = g * tint[1]
    # central vein + pinnate side veins (dark lines)
    vein = (np.abs(u) < 0.008) | (
        np.abs(np.abs(u) - (t % 0.18) * 2.2 * w) < 0.006)
    r = np.where(vein, r * 0.55, r)
    gg = np.where(vein, gg * 0.62, gg)
    b = np.where(vein, b * 0.55, b)
    a = inside.astype(np.float32)
    rgba = np.stack([r, gg, b, a], axis=-1).astype(np.float32)
    rgba[..., :3] *= a[..., None]          # keep matte black outside the cutout
    return rgba


def _flower_pixels(rng, petal_rgb):
    """Vectorized petal rosette with a warm centre disc."""
    u, v = np.meshgrid(np.linspace(-0.5, 0.5, TEX_W, dtype=np.float32),
                       np.linspace(-0.5, 0.5, TEX_H, dtype=np.float32))
    rad = np.sqrt(u * u + v * v)
    ang = np.arctan2(v, u)
    petals = rng.choice([5, 6, 8])
    rr = 0.46 * (0.45 + 0.55 * np.abs(np.cos(petals * ang / 2.0)))
    inside = rad < rr
    core = rad < 0.07
    shade = 1.0 - 0.55 * np.clip(rad / np.maximum(rr, 1e-4), 0.0, 1.0) ** 2
    r = petal_rgb[0] * shade
    g = petal_rgb[1] * shade
    b = petal_rgb[2] * shade
    r = np.where(core, 0.95, r)
    g = np.where(core, 0.80, g)
    b = np.where(core, 0.25, b)
    a = inside.astype(np.float32)
    rgba = np.stack([r, g, b, a], axis=-1).astype(np.float32)
    rgba[..., :3] *= a[..., None]
    return rgba


def _make_image(name, rgba):
    img = bpy.data.images.new(name, TEX_W, TEX_H, alpha=True)
    img.colorspace_settings.name = 'sRGB'
    img.pixels.foreach_set(rgba.ravel())
    try:
        img.pack()
    except Exception:
        pass                                  # materialize_textures reads pixels anyway
    return img


# ----------------------------------------------------------------- species tint
_LEAF_TINTS = [
    (0.55, 1.00, 0.45), (0.42, 1.00, 0.40), (0.62, 1.00, 0.38),
    (0.50, 1.00, 0.55), (0.35, 1.00, 0.48),
]
_PETAL_RGBS = [
    (0.95, 0.92, 0.90), (0.93, 0.55, 0.75), (0.72, 0.50, 0.95),
    (0.90, 0.35, 0.35), (0.95, 0.75, 0.30), (0.55, 0.60, 0.95),
]


def _seed_for(name):
    return zlib.crc32(name.encode("utf8")) & 0xffffffff


# ----------------------------------------------------------------- card meshes
def _card_mesh(name, kind, rng):
    """Gently cupped grid card. Petiole at local -Y end (min Y) so
    foliage.prep_cards anchors it on the stem exactly like a Baga card."""
    segs_x, segs_y = 4, 6
    L = CARD_LEN if kind == "leaf" else CARD_LEN * 0.7
    W = L * (0.85 if kind == "leaf" else 1.0)
    verts, faces, uvs = [], [], []
    for j in range(segs_y + 1):
        ty = j / segs_y
        for i in range(segs_x + 1):
            tx = i / segs_x
            x = (tx - 0.5) * W
            y = ty * L
            z = 0.05 * L * math.sin(math.pi * ty) * (1.0 - abs(tx - 0.5))  # slight cup
            verts.append((x, y, z))
    for j in range(segs_y):
        for i in range(segs_x):
            a = j * (segs_x + 1) + i
            faces.append((a, a + 1, a + segs_x + 2, a + segs_x + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            vi = me.loops[li].vertex_index
            x, y, _ = me.vertices[vi].co
            uvl.data[li].uv = (x / W + 0.5, y / L)
    me.update()
    return me


def _card_material(name, img):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    bsdf.inputs["Roughness"].default_value = 0.5
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.location = (-350, 200)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    try:
        mat.blend_method = 'CLIP'
        mat.alpha_threshold = 0.5
    except Exception:
        pass
    return mat


# ----------------------------------------------------------------- entry point
def build_cards(names):
    """{name: object} for every requested card name -- drop-in replacement for
    foliage.load_cards when the Baga library is unavailable."""
    out = {}
    for nm in names:
        rng = random.Random(_seed_for(nm))
        kind = "flower" if ("flower" in nm.lower() or "fruit" in nm.lower()) else "leaf"
        species = nm.split("_")[0].lower()
        if kind == "leaf":
            tint = _LEAF_TINTS[_seed_for(species) % len(_LEAF_TINTS)]
            rgba = _leaf_pixels(rng, tint)
        else:
            petal = _PETAL_RGBS[_seed_for(species) % len(_PETAL_RGBS)]
            rgba = _flower_pixels(rng, petal)
        img = _make_image(f"fb_{nm.lower()}_card.png", rgba)
        me = _card_mesh(nm, kind, rng)
        me.materials.append(_card_material(f"FB_{nm}", img))
        obj = bpy.data.objects.new(nm, me)
        out[nm] = obj
    _P(f"built {len(out)} procedural fallback cards")
    return out
