"""ue_place.py -- place vine actors + the controller in the CURRENTLY OPEN level via Epic's MCP.

  python ue_place.py 1 5        # place vines 01..05 (idempotent; existing actors are reused)
  python ue_place.py --save     # save the level (only after the user checked the batch)

Each vine -> StaticMeshActor at the origin, label "PFG_NN_<name>", tag PFGVine, outliner folder PFG_Vines.
BP_VineController_1 (created once) gets every placed vine in its Vines array, in numeric order.
Never saves unless --save is given.
"""
import os, sys, json
import uemcp

SC = "editor_toolset.toolsets.scene.SceneTools"; OT = "editor_toolset.toolsets.object.ObjectTools"
AC = "editor_toolset.toolsets.actor.ActorTools"; AT = "editor_toolset.toolsets.asset.AssetTools"
ROOT_DISK = os.environ.get("VINES_DIR", "./vines_out"); ROOT_UE = os.environ.get("VINES_UE_ROOT", "/Game/PFG/Vines")
PREFIX = os.environ.get("VINES_PREFIX", "PFG_")  # vine folder/asset name prefix
FOLDER = "PFG_Vines"; CTRL_LABEL = "BP_VineController_1"
c = uemcp.Client(port=8001); c.init()


def call(ts, t, a=None):
    r = c.call(ts, t, a or {})
    if isinstance(r, dict) and "error" in r:
        raise RuntimeError("%s %s -> %s" % (t, json.dumps(a)[:150], r["error"]))
    return r.get("returnValue", r) if isinstance(r, dict) else r


def J(x):
    return json.loads(x) if isinstance(x, str) else x


def actor_label(a):
    return str(call(AC, "get_label", {"actor": a}) or "")


def find_by_label(label):
    for a in call(SC, "find_actors", {"root": None, "name": label, "actor_type": "", "tag": "", "bounds": None, "collision_channels": []}) or []:
        if actor_label(a) == label:
            return a
    return None


def vine_names():
    return sorted(n for n in os.listdir(ROOT_DISK) if n.startswith(PREFIX) and os.path.isdir(os.path.join(ROOT_DISK, n)))


def place_vine(name):
    a = find_by_label(name)
    if a is None:
        a = call(SC, "add_to_scene_from_asset", {"asset_path": ROOT_UE + "/" + name + "/" + name, "name": name,
                                                 "xform": {"location": {"x": 0, "y": 0, "z": 0}}, "parent": None, "snap_to_ground": False})
        created = True
    else:
        created = False
    call(AC, "set_label", {"actor": a, "label": name})
    if not call(AC, "has_tag", {"actor": a, "tag": "PFGVine"}):
        call(AC, "add_tag", {"actor": a, "tag": "PFGVine"})
    call(SC, "set_actor_folder", {"actor": a, "folder_path": FOLDER})
    return a, created


def ensure_controller():
    ctl = find_by_label(CTRL_LABEL)
    if ctl is None:
        ctl = call(SC, "add_to_scene_from_asset", {"asset_path": "/Game/PFG/BP_VineController", "name": CTRL_LABEL,
                                                   "xform": {"location": {"x": 0, "y": 0, "z": 0}}, "parent": None, "snap_to_ground": False})
        call(AC, "set_label", {"actor": ctl, "label": CTRL_LABEL})
        call(SC, "set_actor_folder", {"actor": ctl, "folder_path": FOLDER})
    return ctl


def main():
    if sys.argv[1:2] == ["--save"]:
        lvl = call(SC, "get_current_level")
        print("saving level", lvl, call(AT, "save_assets", {"asset_paths": [lvl]}))
        return
    lo, hi = int(sys.argv[1]), int(sys.argv[2])
    names = [n for n in vine_names() if lo <= int(n.split("_")[1]) <= hi]
    print("level:", call(SC, "get_current_level"))
    placed = []
    for n in names:
        a, created = place_vine(n)
        print(("placed " if created else "reused ") + n, a["refPath"].split(".")[-1])
        placed.append(a)
    ctl = ensure_controller()
    # controller's Vines array = every PFGVine actor currently in the level, numeric order
    allv = []
    for a in call(SC, "find_actors", {"root": None, "name": "", "actor_type": "", "tag": "PFGVine", "bounds": None, "collision_channels": []}) or []:
        allv.append((actor_label(a), a))
    allv.sort(key=lambda x: x[0])
    call(OT, "set_properties", {"instance": ctl, "values": json.dumps({"Vines": [a for _, a in allv]})})
    back = J(call(OT, "get_properties", {"instance": ctl, "properties": ["Vines", "ActiveIndex", "AutoPlay", "Collection"]}))
    print("controller Vines:", [v["refPath"].split(".")[-1] for v in back.get("Vines", [])])
    print("controller:", {k: v for k, v in back.items() if k != "Vines"})
    # verification: folder contents + hidden flags
    infolder = call(SC, "get_actors_in_folder", {"folder_path": FOLDER, "recursive": False}) or []
    print("actors in folder %s: %d" % (FOLDER, len(infolder)))
    for lbl, a in allv:
        p = J(call(OT, "get_properties", {"instance": a, "properties": ["bHidden"]}))
        b = call(AC, "get_actor_bounds", {"actor": a})
        print("  %-28s hidden=%s tags=%s bounds=%s" % (lbl, p.get("bHidden"), call(AC, "get_tags", {"actor": a}), json.dumps(b)[:120]))
    print("DONE batch %02d-%02d (level NOT saved)" % (lo, hi))


if __name__ == "__main__":
    main()
