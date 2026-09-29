"""ue_import_live.py -- import the vines into the RUNNING UE 5.8 editor via Epic's MCP (port 8001).

Mirrors (headless variant, not shipped) (headless) but drives the live editor, so the assets appear immediately:
  mesh -> /Game/PFG/Vines/<name>/<name> (no materials/textures, combine, Nanite on)
  tex  -> /Game/PFG/Vines/<name>/Tex/T_*  (normal: TC_Normalmap/linear, rough: linear, rgba colour: BC7)
  MIs  -> /Game/PFG/Vines/<name>/Materials/MI_<name>_<slot> parented to /Game/VineWPO/M_Vine_{Bark,Leaf}
  save -> AssetTools.save_assets on everything touched.
Usage: python ue_import_live.py [names...]     (no names = all PFG_* folders)   -> _ue_live_result.json
Idempotent: existing assets are reused, settings/params re-applied.
"""
import os, sys, re, json, time
import uemcp

ROOT_DISK = os.environ.get("VINES_DIR", "./vines_out"); ROOT_UE = os.environ.get("VINES_UE_ROOT", "/Game/PFG/Vines")
PREFIX = os.environ.get("VINES_PREFIX", "PFG_")  # vine folder/asset name prefix
M_LEAF = "/Game/VineWPO/M_Vine_Leaf"; M_BARK = "/Game/VineWPO/M_Vine_Bark"
AT = "editor_toolset.toolsets.asset.AssetTools"; SM = "editor_toolset.toolsets.static_mesh.StaticMeshTools"
TX = "editor_toolset.toolsets.texture.TextureTools"; OT = "editor_toolset.toolsets.object.ObjectTools"
MI = "editor_toolset.toolsets.material_instance.MaterialInstanceTools"
RESULT = os.path.join(ROOT_DISK, "_ue_live_result.json")

c = None


def R(p):
    return {"refPath": p + "." + p.rsplit("/", 1)[1]}


def call(ts, tool, args):
    global c
    if c is None:
        c = uemcp.Client(port=8001); c.init()
    r = c.call(ts, tool, args)
    if isinstance(r, dict) and "error" in r:
        raise RuntimeError("%s.%s %s -> %s" % (ts.rsplit(".", 1)[1], tool, json.dumps(args)[:200], r["error"]))
    return r.get("returnValue", r) if isinstance(r, dict) else r


def wait_no_pie():
    """EditorAssetLibrary (exists/save/is_dirty) refuses with 'The Editor is currently in a play mode' during PIE."""
    said = False
    while call("EditorToolset.EditorAppToolset", "IsPIERunning", {}):
        if not said:
            print("  ... editor is in Play-In-Editor; waiting for PIE to stop (checking every 10 s)", flush=True)
            said = True
        time.sleep(10)
    if said:
        print("  ... PIE stopped, continuing", flush=True)


def exists(p):
    """AssetTools.exists went False-for-everything mid-session (2026-09-26); find_assets stays reliable."""
    folder, leaf = p.rsplit("/", 1)
    found = call(AT, "find_assets", {"folder_path": folder, "name": leaf, "asset_type": "", "recursive": False, "tags": {}}) or []
    return any(str(f).lower() == p.lower() for f in found)


def pick(files, *needles, exclude=()):
    for f in files:
        l = f.lower()
        if all(n in l for n in needles) and not any(x in l for x in exclude):
            return f
    return None


TYPE_WORDS = ("alpha", "normal", "rough", "translucent", "displacement", "rgba", "opacity")
VARIANTS = {"purple", "yellow", "white", "pink", "red", "blue", "orange", "violet"}
NOISE = {"color", "colour", "basecolor", "colo", "leaf", "leaves", "flower", "flowers", "pistil", "steam", "stem", "maps", "map"}


def toks(name):
    s = re.sub(r"\.\d{3}$", "", os.path.splitext(name)[0].lower())
    out = []
    for t in re.split(r"[\s_.\-]+", s):
        t = re.sub(r"\d+$", "", t)
        if t and not re.fullmatch(r"v", t):
            out.append(t)
    return out


def ftype(fn):
    l = fn.lower()
    for w in TYPE_WORDS:
        if w in l:
            return "rough" if w == "rough" else w
    return "color"


def is_color(fn):
    return ftype(fn) == "color"


def sibling(color_f, files, typ, kind=None):
    """file of type `typ` sharing color_f's core tokens (minus colour variants), same leaf/flower side,
    fewest extra tokens wins (a stray 'leaf'/'flower' token counts as extra)."""
    ct = set(toks(color_f))
    core = ct - NOISE - VARIANTS
    side = "flower" if ct & {"flower", "flowers"} else "leaf" if "leaf" in ct else (kind if kind in ("leaf", "flower") else None)
    best = None
    for f in files:
        if ftype(f) != typ:
            continue
        ft = set(toks(f))
        if not core <= ft:
            continue
        fside = "flower" if ft & {"flower", "flowers"} else "leaf" if "leaf" in ft else None
        if side and fside and side != fside:
            continue
        extra = len(ft - core - {"color", "colour", "basecolor", "colo", typ, "roughness", "roughnessv", "normale"})
        if side is None:
            key = (0 if fside is None else 1 if fside == "flower" else 2, extra)
        else:
            key = (0 if fside == side else 1, extra)
        if best is None or key < best[0]:
            best = (key, f)
    return best[1] if best else None


TEXD_HINT = []


def has_mask_look(path):
    """True if the image is a near-binary grayscale mask (RGB channels equal, mostly 0/255)."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB").resize((256, 256))
        r, g, b = [ch.tobytes() for ch in im.split()]
        if r != g or g != b:
            return False
        mid = sum(1 for v in r if 16 < v < 240)
        return mid < len(r) * 0.05
    except Exception:
        return False


def has_own_alpha(path):
    try:
        from PIL import Image
        im = Image.open(path)
        if "A" not in im.getbands():
            return False
        lo, hi = im.getchannel("A").getextrema()
        return lo < 250
    except Exception:
        return False


def resolve_slot(slot, files):
    """-> (kind, dict(Color=, Alpha=, Normal=, Roughness=), how)  kind in bark|flower|leaf"""
    st = toks(slot)
    if st and st[0] == "bark":
        return "bark", dict(Color=pick(files, "bark_color"), Alpha=None, Normal=pick(files, "bark_normal"),
                            Roughness=pick(files, "bark_rough")), "bark"
    kind = "flower" if any(t in ("flower", "flowers", "pistil") for t in st) else ("leaf" if st and set(st) & {"leaf", "leaves", "steam", "stem"} else None)
    core = set(st) - NOISE
    stem = re.sub(r"\.\d{3}$", "", slot).lower()
    colors = [f for f in files if is_color(f) and f.lower().endswith((".png", ".jpg", ".jpeg")) and not f.lower().startswith("bark")]
    exact = [f for f in colors if os.path.splitext(f)[0].lower() == stem]
    how = "exact"
    if exact:
        col = exact[0]
    else:
        how = "score"
        scored = []
        for f in colors:
            ft = set(toks(f))
            if kind == "flower" and "leaf" in ft:
                continue
            if kind == "leaf" and ("flower" in ft or "flowers" in ft):
                continue
            if kind is None and "leaf" in ft and any(os.path.splitext(g)[0].lower() == stem for g in colors):
                continue
            n = len(core & ft)
            if n == 0:
                continue
            has_color_word = any(w in f.lower() for w in ("color", "colour", "colo"))
            side_ok = True if kind is None else ("leaf" in ft) if kind == "leaf" else bool(ft & {"flower", "flowers"})
            extra = len(ft - core - NOISE)
            scored.append((-n, 0 if core <= ft else 1, 0 if side_ok else 1, 0 if has_color_word else 1, extra, f))
        if scored:
            col = sorted(scored)[0][-1]
        else:
            how = "fallback"
            # BagaIvy's Clematis asset ships the generic 'Leaf_steam' / 'Flower_Pistil' slots
            clem = [f for f in colors if f.lower().startswith("clematis_")
                    and (("leaf" in toks(f)) if kind == "leaf" else bool(set(toks(f)) & {"flower", "flowers"}))]
            if clem:
                col = clem[0]; how = "fallback-clematis"
            elif kind == "flower":
                col = "flower_color_rgba.png" if "flower_color_rgba.png" in files else None
            else:
                rg = [f for f in files if f.lower().endswith("_leaf_color_rgba.png")]
                col = next((f for f in rg if not f.lower().startswith("hedera")), rg[0] if rg else None)
    if not col:
        kind = kind or "leaf"
        return kind, dict(Color=None, Alpha=None, Normal=None, Roughness=None), how
    if col.lower().endswith("rgba.png"):
        return kind, dict(Color=col, Alpha=None, Normal=None, Roughness=None), how
    alp = sibling(col, files, "alpha", kind)
    if alp is None:  # BagaIvy sometimes ships the cutout as a '*_maps*' file (white-on-black mask)
        cand = sibling(col, [f for f in files if "maps" in f.lower() and f != col], "color", kind)
        if cand and has_mask_look(os.path.join(TEXD_HINT[0], cand) if TEXD_HINT else cand):
            alp = cand
    if kind != "flower" and ("flower" in toks(col) or (alp and "flower" in toks(alp))):
        kind = "flower"
    kind = kind or "leaf"
    return kind, dict(Color=col, Alpha=alp, Normal=sibling(col, files, "normal", kind),
                      Roughness=sibling(col, files, "rough", kind)), how


def packed_rgba(texd, color_f, alpha_f):
    """pack RGB(color)+A(alpha.R) -> <colorstem>_rgba.png next to them (idempotent); returns file name."""
    out = os.path.splitext(color_f)[0] + "_rgba.png"
    op = os.path.join(texd, out)
    if not os.path.isfile(op) or os.path.getmtime(op) < max(os.path.getmtime(os.path.join(texd, color_f)), os.path.getmtime(os.path.join(texd, alpha_f))):
        from PIL import Image
        ci = Image.open(os.path.join(texd, color_f)).convert("RGB")
        ai = Image.open(os.path.join(texd, alpha_f))
        ai = ai.split()[0] if ai.mode not in ("L", "1") else ai.convert("L")
        if ai.size != ci.size:
            ai = ai.resize(ci.size, Image.LANCZOS)
        ci.putalpha(ai); ci.save(op, "PNG")
    return out


def slot_textures(slot, files, texd=None):
    TEXD_HINT[:] = [texd] if texd else []
    kind, tx, how = resolve_slot(slot, files)
    col = tx.pop("Color"); alp = tx.pop("Alpha")
    if col and alp and texd:
        col = packed_rgba(texd, col, alp)
    elif col and texd and kind != "bark" and not col.lower().endswith("rgba.png"):
        how += "/own-alpha" if has_own_alpha(os.path.join(texd, col)) else "/NO-ALPHA"
    tx = dict(Color=col, **tx)
    tx["_how"] = how
    return kind, tx


def import_texture(src, folder, name, kind):
    ap = folder + "/" + name
    if not exists(ap):
        call(TX, "import_file", {"folder_path": folder, "asset_name": name, "source_file": src})
    if kind == "normal":
        vals = {"compressionSettings": "TC_Normalmap", "sRGB": False, "bFlipGreenChannel": False}
    elif kind == "rough":
        vals = {"compressionSettings": "TC_Default", "sRGB": False}
    elif kind == "color_rgba":
        vals = {"compressionSettings": "TC_BC7", "sRGB": True, "compressionNoAlpha": False}
    else:
        vals = {"sRGB": True}
    ok = call(OT, "set_properties", {"instance": R(ap), "values": json.dumps(vals)})
    back = json.loads(call(OT, "get_properties", {"instance": R(ap), "properties": list(vals)}))
    bad = {k: (back.get(k), v) for k, v in vals.items() if back.get(k) != v}
    if bad:
        raise RuntimeError("texture settings not applied on %s: %s (set_properties=%r)" % (ap, bad, ok))
    return ap


def do_vine(name):
    wait_no_pie()
    rec = dict(name=name, ok=False); t0 = time.time()
    d = os.path.join(ROOT_DISK, name); fbx = (d + "/" + name + "_wpo.fbx").replace("\\", "/")
    texd = d + "/tex"
    if not os.path.isfile(fbx):
        rec["error"] = "missing fbx " + fbx; return rec
    dest = ROOT_UE + "/" + name; mesh_path = dest + "/" + name
    if exists(mesh_path):
        rec["mesh"] = "existing"
    else:
        r = call(SM, "import_file", {"folder_path": dest, "asset_name": name, "source_file": fbx,
                                     "import_materials": False, "import_textures": False, "combine_meshes": True})
        rec["mesh"] = "imported"
        if not exists(mesh_path):
            rec["error"] = "mesh import failed: %r" % (r,); return rec
    m = R(mesh_path)
    b = call(SM, "get_bounds", {"mesh": m})
    rec["bounds_cm"] = dict(min=[round(b["min"][k]) for k in "xyz"], max=[round(b["max"][k]) for k in "xyz"])
    if not call(SM, "is_nanite_enabled", {"mesh": m}):
        call(SM, "set_nanite_enabled", {"mesh": m, "enabled": True})
    rec["nanite"] = bool(call(SM, "is_nanite_enabled", {"mesh": m}))
    files = sorted(os.listdir(texd))
    touched = [mesh_path]
    slots = []
    for slot in call(SM, "get_material_slots", {"mesh": m}):
        kind, tx = slot_textures(slot, files, texd); how = tx.pop("_how")
        parent = M_BARK if kind == "bark" else M_LEAF
        mi_name = ("MI_%s_%s" % (name, re.sub(r"[^A-Za-z0-9]+", "_", slot)))[:120]
        mi_path = dest + "/Materials/" + mi_name
        if not exists(mi_path):
            call(MI, "create", {"folder_path": dest + "/Materials", "asset_name": mi_name, "parent": R(parent)})
        else:
            call(MI, "set_parent", {"instance": R(mi_path), "parent": R(parent)})
        used = {}
        for param, fn in tx.items():
            if not fn:
                continue
            tkind = "normal" if param == "Normal" else "rough" if param == "Roughness" else \
                ("color_rgba" if fn.lower().endswith("rgba.png") else "color")
            tname = "T_" + re.sub(r"[^A-Za-z0-9]+", "_", os.path.splitext(fn)[0])
            tp = import_texture(texd + "/" + fn, dest + "/Tex", tname, tkind)
            call(MI, "set_texture_parameter", {"instance": R(mi_path), "name": param, "value": R(tp)})
            got = call(MI, "get_texture_parameter", {"instance": R(mi_path), "name": param})
            if not (isinstance(got, dict) and got.get("refPath", "").lower().startswith(tp.lower())):
                raise RuntimeError("texture param %s on %s reads back %r" % (param, mi_path, got))
            used[param] = fn; touched.append(tp)
        call(SM, "set_material", {"mesh": m, "slot_name": slot, "material": R(mi_path)})
        got = call(SM, "get_material", {"mesh": m, "slot_name": slot})
        if not (isinstance(got, dict) and got.get("refPath", "").lower().startswith(mi_path.lower())):
            raise RuntimeError("slot %s on %s reads back %r" % (slot, name, got))
        touched.append(mi_path)
        slots.append(dict(slot=slot, kind=kind, how=how, mi=mi_path, textures=used))
    rec["slots"] = slots
    wait_no_pie()
    saved = call(AT, "save_assets", {"asset_paths": sorted(set(touched))})
    rec["saved"] = saved
    rec["ok"] = all(s["textures"].get("Color") for s in slots) and rec["nanite"]
    rec["secs"] = round(time.time() - t0, 1)
    return rec


def main():
    names = sys.argv[1:] or sorted(n for n in os.listdir(ROOT_DISK) if n.startswith(PREFIX) and os.path.isdir(os.path.join(ROOT_DISK, n)))
    for p in (M_LEAF, M_BARK):
        if not exists(p):
            raise SystemExit("master material missing: " + p)
    out = json.load(open(RESULT)) if os.path.isfile(RESULT) else []
    out = [r for r in out if r["name"] not in names]
    for n in names:
        print("===", n, flush=True)
        try:
            rec = do_vine(n)
        except Exception as e:
            rec = dict(name=n, ok=False, error=repr(e))
        print(json.dumps(rec)[:400], flush=True)
        out.append(rec)
        json.dump(sorted(out, key=lambda r: r["name"]), open(RESULT, "w"), indent=1)
    print("DONE ok=%d/%d" % (sum(1 for r in out if r.get("ok") and r["name"] in names), len(names)))


FBX_MAT_RE = rb"([A-Za-z0-9_ .\-]{2,80})" + bytes([0, 1]) + b"Material"


def dry():
    import glob
    for d in sorted(glob.glob(ROOT_DISK + "/" + PREFIX + "*/")):
        d = d.replace("\\", "/"); n = os.path.basename(d.rstrip("/"))
        b = open(d + n + "_wpo.fbx", "rb").read()
        slots = sorted(set(m.group(1).decode() for m in re.finditer(FBX_MAT_RE, b)))
        files = sorted(os.listdir(d + "tex"))
        print("##", n)
        for s in slots:
            kind, tx = slot_textures(s, files, d + "tex")
            print("  %-42s %-6s %-14s C=%s N=%s R=%s" % (s, kind, tx.pop("_how"), tx["Color"], tx["Normal"], tx["Roughness"]))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--dry"]:
        dry()
    else:
        main()
