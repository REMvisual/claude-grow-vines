"""grow_vine.py -- grow a UE-ready WPO-wipe vine over an arbitrary mesh, headless.

  PYTHONHASHSEED=0 blender --background --factory-startup --python grow_vine.py -- \
     <MESH> <BRIEF> <OUTDIR> [NAME]

  MESH   : path to .fbx (or a primitive keyword: sphere | cube | plane)
  BRIEF  : natural-language brief, e.g. "dense ivy mat creeping from outside"
  OUTDIR : output folder (created)
  NAME   : optional output base name (default: derived from mesh/brief)

Pipeline: intent->recipe (intent_map) -> autofit to mesh bbox -> build_variant (grow+skin+
foliage) -> bake 5 UV channels (UVMap, wipe, dx, dy, dz) -> export FBX -> VERIFY by reimport
(5 channels + non-trivial dx/dz) -> bake bark+leaf PBR textures -> write README + compliance.
Mirrors plantgen/bake_wpo.py's proven build+export+verify; deletion/rename stages are omitted
(nothing obsolete to clean for a fresh mesh).
"""
import bpy, os, sys, json, re, traceback
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "plantgen"))
import hero                                   # noqa: E402
from plantgen import foliage as FOL           # noqa: E402
import intent_map                             # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
MESH = argv[0]
BRIEF = argv[1] if len(argv) > 1 else "ivy mat creeping from outside"
OUT = argv[2] if len(argv) > 2 else os.path.join(os.getcwd(), "vine_out")
NAME = argv[3] if len(argv) > 3 else None
if not NAME:
    stem = "prim_" + MESH if MESH in ("sphere", "cube", "plane") else \
        os.path.splitext(os.path.basename(MESH))[0]
    NAME = "vine_" + re.sub(r"[^A-Za-z0-9_]+", "_", stem)
TEX = os.path.join(OUT, "tex")
os.makedirs(TEX, exist_ok=True)
base = NAME


def L(*a):
    print("[GROWVINE]", *a, flush=True)


def result(rec):
    try:
        with open(os.path.join(OUT, "wpo_compliance.json"), "w") as f:
            json.dump(rec, f, indent=2, default=str)
    except Exception:
        pass
    print("GROWVINE_RESULT: %s name=%s mode=%s uv=%s wpo_mb=%s" %
          ("PASS" if rec.get("ok") else "FAIL", NAME, rec.get("intent_mode"),
           rec.get("uv_layers"), rec.get("wpo_mb")), flush=True)
    sys.exit(0 if rec.get("ok") else 2)


def measure_bbox_diag(mesh_spec):
    """Load target once to measure world bbox diagonal, then leave scene (build reloads)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import plantgen.skeleton as SK
    o = SK.load_target(mesh_spec, bpy.context.scene)
    bpy.context.view_layer.update()
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    mn = [min(c[i] for c in cs) for i in range(3)]
    mx = [max(c[i] for c in cs) for i in range(3)]
    return float(sum((mx[i] - mn[i]) ** 2 for i in range(3)) ** 0.5)


def autofit(recipe, diag, ref=6.0):
    """Scale growth params to the mesh size (params are tuned for a ~6 m target)."""
    s = max(0.15, diag / ref)
    r = dict(recipe)
    r["base_r"] = round(r["base_r"] * s, 4)
    r["growth_dz"] = round(r["growth_dz"] * s, 4)
    r["budget"] = int(min(30000, max(1500, r["budget"] * s ** 1.5)))
    r["n_attractors"] = int(min(16000, max(800, r["n_attractors"] * s ** 1.5)))
    r["_autofit_scale"] = round(s, 3)
    r["_target_diag_m"] = round(diag, 3)
    return r


rec = {"name": NAME, "mesh": MESH, "brief": BRIEF, "ok": False}
try:
    recipe = intent_map.parse(BRIEF, name=NAME)
    # keep only species that actually have leaf cards in the installed Baga library;
    # fall back to ivy so a brief never produces a bare (leafless) stem.
    good = [s for s in recipe["leaf_species"] if FOL.resolve_species(s)[0]]
    if not good:
        L("no requested species had leaf cards %s -> falling back to Hedera_helix"
          % recipe["leaf_species"])
        good = ["Hedera_helix"]
    recipe["leaf_species"] = good
    diag = measure_bbox_diag(MESH)
    recipe = autofit(recipe, diag)
    rec.update({k: recipe[k] for k in ("intent_mode", "growth_mode", "leaf_species",
                "_autofit_scale", "_target_diag_m", "budget", "n_attractors", "base_r")})
    L("recipe:", json.dumps({k: recipe[k] for k in recipe if not k.startswith("brief")}))

    hero.TARGET = MESH                      # build_variant loads this
    obj, target, fol, stats = hero.build_variant(recipe, TEX)
    for o in list(bpy.context.scene.objects):       # plant only
        if o.type == 'MESH' and o is not obj:
            bpy.data.objects.remove(o, do_unlink=True)
    try:
        FOL.materialize_textures(fol, TEX)
    except Exception as e:
        L("materialize warn:", repr(e))
    # export the bark PBR maps too (bark uses source JPGs, not materialized) so the
    # per-run tex/ folder is a complete UE texture set.
    try:
        import shutil
        bdir = os.path.join(HERE, "assets", "bark", recipe["bark"])
        for tok, dst in (("color", "bark_color"), ("normal", "bark_normal"),
                         ("roughness", "bark_roughness")):
            src = hero._find_map(bdir, tok)
            if src:
                shutil.copy2(src, os.path.join(TEX, dst + os.path.splitext(src)[1].lower()))
    except Exception as e:
        L("bark copy warn:", repr(e))

    # --- pack RGBA leaf/flower colour maps -------------------------------------------------
    # M_Vine_Leaf does OpacityMask = reveal * Color.A, but Baga colour maps ship OPAQUE
    # (alpha=1) with the leaf cutout in a SEPARATE *_ALPHA map. Pack RGB(colour)+A(cutout)
    # into <species>_leaf_color_rgba.png so the leaf material masks correctly drop-in.
    rec["leaf_color_rgba"] = []
    try:
        pngs = [f for f in os.listdir(TEX) if f.lower().endswith(".png")]

        def _is_color(fn):
            l = fn.lower()
            return not any(t in l for t in ("alpha", "normal", "rough", "translucent", "displacement"))

        def _pack(color_f, alpha_f, out_name):
            ci = bpy.data.images.load(os.path.join(TEX, color_f), check_existing=False)
            ai = bpy.data.images.load(os.path.join(TEX, alpha_f), check_existing=False)
            ai.colorspace_settings.name = "Non-Color"
            if tuple(ai.size) != tuple(ci.size):
                ai.scale(ci.size[0], ci.size[1])
            w, h = ci.size
            cp = np.empty(w * h * 4, dtype=np.float32); ci.pixels.foreach_get(cp)
            ap = np.empty(w * h * 4, dtype=np.float32); ai.pixels.foreach_get(ap)
            cp = cp.reshape(-1, 4); ap = ap.reshape(-1, 4)
            cp[:, 3] = ap[:, 0]                                   # cutout mask -> alpha
            ni = bpy.data.images.new(out_name, w, h, alpha=True)
            ni.pixels.foreach_set(cp.reshape(-1))
            ni.filepath_raw = os.path.join(TEX, out_name); ni.file_format = "PNG"; ni.save()
            for im in (ci, ai, ni):
                try:
                    bpy.data.images.remove(im)
                except Exception:
                    pass

        for sp in recipe["leaf_species"]:                        # one packed map per leaf slot
            grp = [f for f in pngs if f.lower().startswith(sp.lower())]
            col = next((f for f in grp if _is_color(f)), None)
            alp = next((f for f in grp if "alpha" in f.lower()), None)
            if col and alp:
                out = sp.lower() + "_leaf_color_rgba.png"
                _pack(col, alp, out); rec["leaf_color_rgba"].append(out)
        fl = [f for f in pngs if "flower" in f.lower()]          # flowers, if any
        fcol = next((f for f in fl if _is_color(f)), None)
        falp = next((f for f in fl if "alpha" in f.lower()), None)
        if fcol and falp:
            _pack(fcol, falp, "flower_color_rgba.png"); rec["leaf_color_rgba"].append("flower_color_rgba.png")
        L("packed RGBA leaf/flower colour maps:", rec["leaf_color_rgba"])
    except Exception as e:
        L("rgba pack warn:", repr(e))

    # --- bake the 5 UV channels (same math as bake_wpo.py) ---
    me = obj.data
    for nm in ("gt_point", "pivot"):
        if me.attributes.get(nm) is None:
            raise RuntimeError("missing attribute " + nm)
    nv = len(me.vertices); nl = len(me.loops)
    co = np.empty(nv * 3, dtype=np.float32); me.vertices.foreach_get("co", co); co = co.reshape(nv, 3)
    gt = np.zeros(nv, dtype=np.float32); me.attributes["gt_point"].data.foreach_get("value", gt)
    piv = np.empty(nv * 3, dtype=np.float32); me.attributes["pivot"].data.foreach_get("vector", piv); piv = piv.reshape(nv, 3)
    delta = (piv - co) * 100.0
    vidx = np.empty(nl, dtype=np.int32); me.loops.foreach_get("vertex_index", vidx)

    def make_uv(name, vals):
        uv = me.uv_layers.get(name) or me.uv_layers.new(name=name)
        flat = np.zeros(nl * 2, dtype=np.float32); flat[0::2] = vals[vidx]; uv.data.foreach_set("uv", flat)

    make_uv("wipe", gt); make_uv("dx", delta[:, 0]); make_uv("dy", delta[:, 1]); make_uv("dz", delta[:, 2])

    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    fbx = os.path.join(OUT, base + "_wpo.fbx")
    bpy.ops.export_scene.fbx(filepath=fbx, use_selection=True, path_mode='AUTO',
                             embed_textures=False, mesh_smooth_type='FACE',
                             add_leaf_bones=False, bake_space_transform=False)

    # --- verify by reimport: 5 channels + non-trivial delta data ---
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=fbx)
    imp = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if imp is None:
        raise RuntimeError("reimport produced no mesh")
    md = imp.data; nl2 = len(md.loops)
    uvs = [u.name for u in md.uv_layers]
    rec["uv_layers"] = uvs
    rec["wpo_mb"] = round(os.path.getsize(fbx) / 1e6, 1)

    def urange(name):
        u = md.uv_layers.get(name)
        if not u:
            return None
        a = np.empty(nl2 * 2, dtype=np.float32); u.data.foreach_get("uv", a); U = a[0::2]
        return (round(float(U.min()), 2), round(float(U.max()), 2))

    rec["dx_range"] = urange("dx"); rec["dz_range"] = urange("dz")
    ok_uv = len(uvs) == 5 and all(n in uvs for n in ("UVMap", "wipe", "dx", "dy", "dz"))
    dxr = rec["dx_range"]
    ok_data = bool(dxr) and (abs(dxr[0]) > 0.5 or abs(dxr[1]) > 0.5)
    if not (ok_uv and ok_data):
        raise RuntimeError("verify failed uvs=%s dx=%s" % (uvs, dxr))
    rec["verify"] = "PASS"
    rec["textures"] = sorted(f for f in os.listdir(TEX)
                             if f.lower().endswith((".png", ".jpg", ".jpeg", ".tga")))
    rec["fbx"] = fbx
    rec["ok"] = True
    L("PASS uvs=%s wpo=%sMB tex=%d" % (uvs, rec["wpo_mb"], len(rec["textures"])))
except Exception:
    rec["error"] = traceback.format_exc()
    L("FAILED\n" + rec["error"])

# --- bundle a self-contained UE pack into the run + write deploy README ---
try:
    if rec.get("ok"):
        import shutil
        skill_root = os.path.dirname(HERE)                       # HERE=scripts -> skill root
        src_ue = os.path.join(skill_root, "unreal")
        dst_ue = os.path.join(OUT, "unreal")
        if os.path.isdir(src_ue) and not os.path.isdir(dst_ue):
            shutil.copytree(src_ue, dst_ue)                      # M_Vine_Leaf/Bark + IMPORT.md
        rgba = rec.get("leaf_color_rgba", [])
        leaf = [t for t in rec["textures"] if "leaf" in t.lower() and "rgba" not in t.lower()]
        bark = [t for t in rec["textures"] if t.lower().startswith("bark")]
        with open(os.path.join(OUT, "README.md"), "w") as f:
            f.write(
                "# %s -- UE deploy (self-contained)\n\n"
                "- **Mesh:** `%s_wpo.fbx` (5 UV: UVMap, wipe, dx, dy, dz) -- import at "
                "**Offset Uniform Scale 100**, Nanite ON.\n"
                "- **Materials:** `unreal/Content/VineWPO/` holds the masters `M_Vine_Leaf` + "
                "`M_Vine_Bark` (UE 5.7). Drop into your project's Content, then make a Material "
                "Instance per slot.\n"
                "- **Leaf MI(s)** (one per leaf-species slot): of `M_Vine_Leaf` -- set `Color` to the "
                "matching **`*_leaf_color_rgba.png`**, `Normal`/`Roughness` to that species' "
                "`*_NORMAL*` / `*_rough*` maps.\n"
                "  - **IMPORTANT - the leaf `Color` MUST be the RGBA `_rgba` map.** Its alpha is the "
                "leaf cutout and the material does `OpacityMask = reveal * Color.A`. The plain Baga "
                "colour maps are opaque (alpha=1) -> using them gives square leaf cards. If you must "
                "use a non-RGBA colour, reconnect `OpacityMask` to a separate `*_ALPHA` sampler "
                "instead of `Color.A`.\n"
                "  - On import set the `_rgba` textures' Compression to include alpha (e.g. "
                "**Masks/BC7** or 'Compress Without Alpha' OFF) so the cutout survives.\n"
                "- **Bark MI:** of `M_Vine_Bark` -- `Color/Normal/Roughness` = the `bark_*` maps.\n"
                "- **Drive:** each frame `MID->SetScalarParameterValue(\"GrowthFront\", phase01)` "
                "(0=ungrown -> 1=full). `GrowWindow`/`SoftBand` = edge softness, `WPOScale` = unfurl throw.\n"
                "- Full step-by-step: `unreal/IMPORT.md`.\n\n"
                "Leaf colour (RGBA, use these): %s\nLeaf other maps: %s\nBark maps: %s\n"
                % (base, base, rgba or "(none)", leaf or "(see tex/)", bark or "(see tex/)"))
except Exception as e:
    L("readme warn", repr(e))

result(rec)
