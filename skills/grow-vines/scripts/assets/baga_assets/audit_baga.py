"""
AUDIT: enumerate every object in the BagaIvy asset DB, classify, group by species,
record geometry/material/texture facts, flag broken/oversized assets.
Run: blender --background --factory-startup --python audit_baga.py
Writes baga_asset_manifest.json + baga_asset_manifest.md in this folder.
"""
import bpy, os, json, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.environ.get("BAGAIVY_DIR", ""), "BagaIvy_AssetsDatabase.blend")
if not os.path.isfile(DB):
    DB = os.path.join(bpy.utils.user_resource('SCRIPTS', path="addons"),
                      "BagaIvy", "BagaIvy_AssetsDatabase.blend")
def P(*a): print("[AUDIT]", *a, flush=True)

# ---- 1) get every object name in the library
with bpy.data.libraries.load(DB) as (src, dst):
    all_names = list(src.objects)
P("objects in DB:", len(all_names))

# ---- classify ---------------------------------------------------------------
def classify(name):
    n = name.lower()
    if "flower" in n or "bloom" in n or "blossom" in n: return "flower"
    if "fruit" in n or "berry" in n: return "fruit"
    if "leaf" in n or "leaves" in n: return "leaf"
    # Hedera helix leaves carry NO 'leaf' token (Hedera_helix_00N). Treat bare
    # 'Genus_species_00N' (no other token) as leaf — they are the leaf cards.
    if re.match(r"^[A-Za-z]+[ _]+[A-Za-z]+[ _]+\d+$", name.strip()):
        return "leaf"
    return "other"

def species_of(name):
    s = name.strip()
    # strip trailing index + type tokens
    s = re.sub(r"[ _]*(leaf|leaves|flower|bloom|blossom|fruit|berry)[ _]*\d*$", "", s, flags=re.I)
    s = re.sub(r"[ _]+\d+$", "", s)            # trailing _00N
    s = re.sub(r"[ _]*(leaf|leaves|flower|bloom|blossom|fruit|berry)$", "", s, flags=re.I)
    # collapse genus species
    m = re.match(r"^([A-Za-z]+)[ _]+([A-Za-z]+)", s)
    if m: return f"{m.group(1)}_{m.group(2)}".lower()
    return s.strip().lower() or "unknown"

# ---- 2) load ALL objects in batches to inspect geometry/materials -----------
records = []
BATCH = 60
def img_status(img):
    if img is None: return "none"
    if img.packed_file is not None: return "packed"
    # check pixels availability
    try:
        if img.size[0] > 0 and img.size[1] > 0: return "valid_unpacked"
    except Exception:
        pass
    return "missing"

processed = 0
for i in range(0, len(all_names), BATCH):
    chunk = all_names[i:i+BATCH]
    with bpy.data.libraries.load(DB) as (src, dst):
        dst.objects = chunk
    loaded = [o for o in dst.objects if o is not None]
    for o in loaded:
        # base name without any .001 collision suffix Blender may add
        nm = re.sub(r"\.\d+$", "", o.name)
        rec = {"name": nm, "raw_name": o.name, "obj_type": o.type}
        rec["category"] = classify(nm)
        rec["species"] = species_of(nm)
        if o.type == 'MESH' and o.data:
            me = o.data
            rec["poly_count"] = len(me.polygons)
            rec["vert_count"] = len(me.vertices)
            rec["has_uv"] = len(me.uv_layers) > 0
            mats = [m for m in me.materials if m]
            rec["materials"] = [m.name for m in mats]
            tex = []
            for m in mats:
                if m.use_nodes and m.node_tree:
                    for nd in m.node_tree.nodes:
                        if nd.type == 'TEX_IMAGE' and nd.image:
                            tex.append({"image": nd.image.name, "status": img_status(nd.image),
                                        "size": list(nd.image.size)})
            rec["textures"] = tex
            rec["tex_ok"] = bool(tex) and all(t["status"] == "packed" or t["status"] == "valid_unpacked" for t in tex)
            # bbox max dim (local, in meters)
            try:
                dim = max(o.dimensions)
                rec["bbox_max_dim_m"] = round(dim, 4)
            except Exception:
                rec["bbox_max_dim_m"] = None
            # flags
            flags = []
            if rec["poly_count"] == 0: flags.append("EMPTY_GEOMETRY")
            if not rec["has_uv"]: flags.append("NO_UV")
            if not mats: flags.append("NO_MATERIAL")
            if not tex: flags.append("NO_TEXTURE")
            if not rec["tex_ok"] and tex: flags.append("BROKEN_TEXTURE")
            if rec["bbox_max_dim_m"] and rec["bbox_max_dim_m"] > 5.0: flags.append("OVERSIZED")
            if rec["poly_count"] > 200: flags.append("HIGH_POLY")
            rec["flags"] = flags
        else:
            rec["poly_count"] = 0; rec["materials"] = []; rec["textures"] = []
            rec["has_uv"] = False; rec["bbox_max_dim_m"] = None; rec["tex_ok"] = False
            rec["flags"] = ["NON_MESH"] if o.type != 'MESH' else ["NO_DATA"]
        records.append(rec)
    # purge loaded datablocks to keep memory sane
    for o in loaded:
        try: bpy.data.objects.remove(o)
        except Exception: pass
    processed += len(loaded)
    P(f"processed {processed}/{len(all_names)}")

# ---- 3) aggregate -----------------------------------------------------------
species = {}
cat_counts = {"leaf":0,"flower":0,"fruit":0,"other":0}
for r in records:
    cat_counts[r["category"]] = cat_counts.get(r["category"],0)+1
    sp = species.setdefault(r["species"], {"leaf":[],"flower":[],"fruit":[],"other":[]})
    sp[r["category"]].append(r["name"])

broken = [r for r in records if r["flags"] and any(f in r["flags"] for f in
          ("EMPTY_GEOMETRY","NO_MATERIAL","NO_TEXTURE","BROKEN_TEXTURE","NO_UV","OVERSIZED"))]

manifest = {
    "db_path": DB,
    "total_objects": len(records),
    "category_counts": cat_counts,
    "species_count": len(species),
    "species": species,
    "broken_or_flagged": [{"name":r["name"],"flags":r["flags"]} for r in broken],
    "objects": records,
}
jpath = os.path.join(HERE, "baga_asset_manifest.json")
with open(jpath, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=1)
P("wrote", jpath)

# ---- 4) markdown summary ----------------------------------------------------
def md_species_table():
    lines = ["| Species | Leaves | Flowers | Fruit | Other | Sample leaf size (m) |",
             "|---|---|---|---|---|---|"]
    for sp in sorted(species):
        d = species[sp]
        # find a leaf sample size
        sz = ""
        for r in records:
            if r["species"]==sp and r["category"]=="leaf" and r.get("bbox_max_dim_m"):
                sz = f"{r['bbox_max_dim_m']:.3f}"; break
        lines.append(f"| {sp} | {len(d['leaf'])} | {len(d['flower'])} | {len(d['fruit'])} | {len(d['other'])} | {sz} |")
    return "\n".join(lines)

clean_species = []
for sp in sorted(species):
    leaves = [r for r in records if r["species"]==sp and r["category"]=="leaf"]
    if leaves and all(not [f for f in r["flags"] if f not in ("HIGH_POLY",)] for r in leaves):
        clean_species.append((sp, len(species[sp]["leaf"]), len(species[sp]["flower"]), len(species[sp]["fruit"])))

md = f"""# BagaIvy Asset Database — Audit Manifest

**DB:** `{DB}`
**Total objects:** {len(records)}
**Species:** {len(species)}
**Categories:** leaf={cat_counts['leaf']}, flower={cat_counts['flower']}, fruit={cat_counts['fruit']}, other={cat_counts['other']}
**Flagged/broken objects:** {len(broken)}

## Species breakdown

{md_species_table()}

## Flagged / broken assets ({len(broken)})

"""
if broken:
    md += "| Object | Flags |\n|---|---|\n"
    for r in broken[:200]:
        md += f"| {r['name']} | {', '.join(r['flags'])} |\n"
else:
    md += "_None — all assets have geometry, UVs, materials and packed textures._\n"

md += f"""
## Clean species with leaves (recommended candidates)

| Species | Leaves | Flowers | Fruit |
|---|---|---|---|
"""
for sp, l, fl, fr in clean_species:
    md += f"| {sp} | {l} | {fl} | {fr} |\n"

mpath = os.path.join(HERE, "baga_asset_manifest.md")
with open(mpath, "w", encoding="utf-8") as f:
    f.write(md)
P("wrote", mpath)
P("=== AUDIT DONE ===")
