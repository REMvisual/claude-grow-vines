"""ue_verify.py -- READ-ONLY headless check of the imported vines (UV channel count, Nanite, slots->MI).

  "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" <YourProject>.uproject \
      -run=pythonscript -script="<skill>/scripts/unreal/ue_verify.py" -unattended -nullrhi -log

UV count comes from the StaticMeshDescription (source data) -- render-data based
EditorStaticMeshLibrary.get_num_uv_channels reads 0 under -nullrhi (2026-09-26).
Writes <VINES_DIR>/_ue_verify_result.json. Never saves anything.
"""
import os, json, traceback
import unreal

ROOT_DISK = os.environ.get("VINES_DIR", "./vines_out")
PREFIX = os.environ.get("VINES_PREFIX", "PFG_")  # vine folder/asset name prefix
ROOT_UE = os.environ.get("VINES_UE_ROOT", "/Game/PFG/Vines")
OUT = os.path.join(os.environ.get("VINES_DIR", "./vines_out"), "_ue_verify_result.json")
EAL = unreal.EditorAssetLibrary


def uv_count_from_description(m):
    """GeometryScript: copy LOD0 source model into a DynamicMesh and ask for the UV set count."""
    dm = unreal.DynamicMesh()
    opts = unreal.GeometryScriptCopyMeshFromAssetOptions()
    lod = unreal.GeometryScriptMeshReadLOD(lod_type=unreal.GeometryScriptLODType.SOURCE_MODEL, lod_index=0)
    r = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(m, dm, opts, lod)
    outcome = r[1] if isinstance(r, tuple) else None
    cands = []
    for cname in [a for a in dir(unreal) if a.startswith("GeometryScript_")]:
        cls = getattr(unreal, cname)
        for fn in dir(cls):
            if "uv" in fn.lower() and ("num" in fn.lower() or "count" in fn.lower() or "sets" in fn.lower()):
                cands.append((cname, fn))
    n = None; used = None
    for cname, fn in cands:
        try:
            v = getattr(getattr(unreal, cname), fn)(dm)
            if isinstance(v, int):
                n, used = v, cname + "." + fn
                break
        except Exception:
            continue
    extra = {"cands": ["%s.%s" % c for c in cands][:12], "used": used}
    if n is None:
        return None, "geometryscript(%s) %s" % (outcome, json.dumps(extra))
    if hasattr(unreal.GeometryScript_UVs, "get_mesh_uv_bounding_box"):
        for ch in range(n):
            try:
                bb = unreal.GeometryScript_UVs.get_mesh_uv_bounding_box(dm, ch)
                extra["uv%d" % ch] = [round(bb.min.x, 2), round(bb.min.y, 2), round(bb.max.x, 2), round(bb.max.y, 2)]
            except Exception as e:
                extra["uv%d" % ch] = repr(e)[:80]
    return n, "geometryscript(%s) %s" % (outcome, json.dumps(extra))


res = []
for n in sorted(os.listdir(os.environ.get("VINES_DIR", "./vines_out"))):
    if not n.startswith(PREFIX) or not os.path.isdir(os.path.join(ROOT_DISK, n)):
        continue
    rec = dict(name=n)
    try:
        p = ROOT_UE + "/" + n + "/" + n
        if not EAL.does_asset_exist(p):
            rec["error"] = "missing " + p
        else:
            m = unreal.load_asset(p)
            rec["uv_channels"], rec["uv_method"] = uv_count_from_description(m)
            md = m.get_static_mesh_description(0)
            for fn in ("get_vertex_count", "get_polygon_count"):
                if md is not None and hasattr(md, fn):
                    try:
                        rec[fn] = getattr(md, fn)()
                    except Exception:
                        pass
            rec["nanite"] = bool(m.get_editor_property("nanite_settings").enabled)
            slots = []
            for sm in m.get_editor_property("static_materials"):
                mi = sm.material_interface
                slots.append(dict(slot=str(sm.material_slot_name), mi=mi.get_path_name() if mi else None,
                                  parent=mi.get_base_material().get_path_name() if mi else None))
            rec["slots"] = slots
            rec["ok"] = rec["uv_channels"] == 5 and rec["nanite"] and all(s["mi"] for s in slots)
    except Exception:
        rec["error"] = traceback.format_exc()
    unreal.log("[PFGVERIFY] " + json.dumps(rec)[:300])
    res.append(rec)
with open(OUT, "w") as f:
    json.dump(res, f, indent=1)
unreal.log("[PFGVERIFY] DONE ok=%d/%d" % (sum(1 for r in res if r.get("ok")), len(res)))
