"""Independent reimport verifier for the WPO-wipe deliverable.
Reimports a vine_<NAME>_wpo.fbx in a clean headless Blender, asserts exactly
5 UV layers (UVMap, wipe, dx, dy, dz) and reports per-channel ranges so we can
confirm dx/dy/dz carry real (~+-tens cm) delta data, not zeros.

  blender --background --factory-startup --python verify_wpo_independent.py -- <fbx>
"""
import bpy, sys
import numpy as np

fbx = sys.argv[sys.argv.index("--") + 1:][0]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=fbx)
imp = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
md = imp.data
nl = len(md.loops)
uvs = [u.name for u in md.uv_layers]


def rng(name):
    u = md.uv_layers.get(name)
    if not u:
        return None
    a = np.empty(nl * 2, dtype=np.float32)
    u.data.foreach_get("uv", a)
    U = a[0::2]
    return (round(float(U.min()), 2), round(float(U.max()), 2))


expect = ["UVMap", "wipe", "dx", "dy", "dz"]
ok_uv = len(uvs) == 5 and all(n in uvs for n in expect)
ranges = {n: rng(n) for n in expect}
# dx/dz must be real spatial deltas (tens of cm), not collapsed to ~0
dx, dz = ranges["dx"], ranges["dz"]
ok_dx = bool(dx) and (abs(dx[0]) > 5 or abs(dx[1]) > 5)
ok_dz = bool(dz) and (abs(dz[0]) > 5 or abs(dz[1]) > 5)
verdict = "PASS" if (ok_uv and ok_dx and ok_dz) else "FAIL"
print("INDEP_VERIFY: %s | uv_count=%d uvs=%s | wipe=%s dx=%s dy=%s dz=%s" %
      (verdict, len(uvs), uvs, ranges["wipe"], dx, ranges["dy"], dz), flush=True)
