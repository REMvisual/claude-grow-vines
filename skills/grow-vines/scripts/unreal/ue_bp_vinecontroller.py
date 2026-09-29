"""ue_bp_vinecontroller.py -- (re)build the graphs of /Game/PFG/BP_VineController via Epic's MCP.

Idempotent: clears and rewrites every graph it owns. Variables + CDO defaults are created if missing.
Function names are deliberately unique (ResetGrowth/PlayGrowth/StopGrowth): the DSL resolves a bare
`CallFunction|Reset` to unrelated engine nodes when the name collides (seen 2026-09-26).
"""
import json, sys
import uemcp

BT = "editor_toolset.toolsets.blueprint.BlueprintTools"; AT = "editor_toolset.toolsets.asset.AssetTools"
OT = "editor_toolset.toolsets.object.ObjectTools"
BP_PATH = "/Game/PFG/BP_VineController"
bp = {"refPath": BP_PATH + ".BP_VineController"}
c = uemcp.Client(port=8001); c.init()


def call(ts, t, a):
    r = c.call(ts, t, a)
    if isinstance(r, dict) and "error" in r:
        raise RuntimeError("%s %s -> %s" % (t, json.dumps(a)[:150], r["error"]))
    return r.get("returnValue", r) if isinstance(r, dict) else r


def graph(n):
    return call(BT, "get_graph", {"blueprint": bp, "graph_name": n})


def clear(g, keep_entries=True):
    allnodes = call(BT, "find_nodes", {"graph": g, "title": "", "node_class": "", "entry_points_only": False}) or []
    entries = (call(BT, "find_nodes", {"graph": g, "title": "", "node_class": "", "entry_points_only": True}) or []) if keep_entries else []
    keep = {e["refPath"] for e in entries}
    n = 0
    for nd in allnodes:
        if nd["refPath"] not in keep:
            call(BT, "delete_node", {"node": nd}); n += 1
    return n


FUNCS = {
"ApplyGrowth": """(fn ApplyGrowth ()
  (Rendering|Material|SetScalarParameterValue
    :Collection (Variables|Vines|GetCollection)
    :ParameterName "GrowthFront"
    :ParameterValue (Variables|Vines|GetGrowthFront)))""",
"ApplyVisibility": """(fn ApplyVisibility ()
  (bind vines (Variables|Vines|GetVines))
  (bind showAll (Variables|Vines|GetShowAll))
  (bind rnd (Variables|Vines|GetRandomMode))
  (bind full (Variables|Vines|GetFullIndices))
  (bind nfull (Utilities|Array|Length :TargetArray full))
  (bind fullIdx (Utilities|Array|Get(acopy) full
                  (Math|Integer|Clamp(Integer) :Value (Variables|Vines|GetActiveIndex) :Min 0
                                               :Max (Math|Integer|Max(Integer) :A (- nfull 1) :B 0))))
  (bind sel (Variables|Default|GetSelected))
  (bind n (Utilities|Array|Length :TargetArray vines))
  (for i (range n)
    (bind a (Utilities|Array|Get(acopy) vines i))
    (bind vis (or showAll (select rnd (Utilities|Array|ContainsItem :TargetArray sel :ItemToFind i) (== i fullIdx))))
    (Rendering|SetActorHiddenInGame :self a :bNewHidden (not vis))
    (bind sma (Utilities|Casting|CastToStaticMeshActor :Object a)
      (:then
        (Rendering|SetVisibility :self (Class|StaticMeshActor|GetStaticMeshComponent :self sma)
          :bNewVisibility vis :bPropagateToChildren true))
      (:CastFailed))))""",
"ApplyMaterial": """(fn ApplyMaterial ()
  (bind mat (Variables|Vines|GetMaterialOverride))
  (bind vines (Variables|Vines|GetVines))
  (for a vines
    (bind sma (Utilities|Casting|CastToStaticMeshActor :Object a)
      (:then
        (bind comp (Class|StaticMeshActor|GetStaticMeshComponent :self sma))
        (bind cnt (Rendering|Material|GetNumMaterials :self comp))
        (bind mesh (Class|StaticMeshComponent|GetStaticMesh :self comp))
        (for s (range cnt)
          (Utilities|IsValid mat
            (:"Is Valid"
              (Rendering|Material|SetMaterial :self comp :ElementIndex s :Material mat))
            (:"Is Not Valid"
              (Rendering|Material|SetMaterial :self comp :ElementIndex s
                :Material (StaticMesh|GetMaterial :self mesh :MaterialIndex s))))))
      (:CastFailed))))""",
"PlayGrowth": "(fn PlayGrowth ()\n  (Variables|Default|SetPlaying true))",
"StopGrowth": "(fn StopGrowth ()\n  (Variables|Default|SetPlaying false))",
"ResetGrowth": "(fn ResetGrowth ()\n  (Variables|Vines|SetGrowthFront 0.0)\n  (Variables|Default|SetDir 1.0)\n  (CallFunction|ApplyGrowth))",
"SetVine": """(fn SetVine (Index)
  (bind n (Utilities|Array|Length :TargetArray (Variables|Vines|GetFullIndices)))
  (Variables|Vines|SetActiveIndex (Math|Integer|Clamp(Integer) :Value Index :Min 0 :Max (- n 1)))
  (CallFunction|ApplyVisibility)
  (if (Variables|Vines|GetAutoPlay)
    (CallFunction|ResetGrowth)
    (CallFunction|PlayGrowth)))""",
"ResetSim": """(fn ResetSim ()
  (Variables|Vines|SetResetNow false)
  (Variables|Default|SetLastLoopMode (Variables|Vines|GetLoopMode))
  (if (Variables|Vines|GetRandomMode)
    (CallFunction|PickRandomSet))
  (CallFunction|ApplyVisibility)
  (CallFunction|ApplyMaterial)
  (CallFunction|ResetGrowth)
  (if (Variables|Vines|GetAutoPlay)
    (CallFunction|PlayGrowth)))""",
"PickRandomSet": """(fn PickRandomSet ()
  (Variables|Vines|SetNewRandomSet false)
  (bind pool (Variables|Vines|GetSmallIndices))
  (Utilities|Array|Shuffle :TargetArray pool)
  (bind npool (Utilities|Array|Length :TargetArray pool))
  (bind k (Math|Integer|Clamp(Integer)
            :Value (Math|Random|RandomIntegerinRange :Min (Variables|Vines|GetRandomMin) :Max (Variables|Vines|GetRandomMax))
            :Min 0 :Max npool))
  (bind sel (Variables|Default|GetSelected))
  (Utilities|Array|Clear :TargetArray sel)
  (for j (range k)
    (Utilities|Array|Add :TargetArray sel :NewItem (Utilities|Array|Get(acopy) pool j))))""",
"SyncChanges": """(fn SyncChanges ()
  (bind idx (Variables|Vines|GetActiveIndex))
  (if (!= idx (Variables|Default|GetLastIndex))
    (CallFunction|SetVine :Index idx)
    (Variables|Default|SetLastIndex (Variables|Vines|GetActiveIndex)))
  (bind rnd (Variables|Vines|GetRandomMode))
  (if (or (Variables|Vines|GetNewRandomSet) (!= rnd (Variables|Default|GetLastRandomMode)))
    (Variables|Default|SetLastRandomMode rnd)
    (Variables|Vines|SetNewRandomSet false)
    (CallFunction|ResetSim)
    (elif (or (Variables|Vines|GetResetNow) (!= (Variables|Vines|GetLoopMode) (Variables|Default|GetLastLoopMode)))
      (CallFunction|ResetSim))))""",
"NextVine": """(fn NextVine ()
  (bind n (Utilities|Array|Length :TargetArray (Variables|Vines|GetFullIndices)))
  (bind nxt (+ (Variables|Vines|GetActiveIndex) 1))
  (CallFunction|SetVine :Index (select (>= nxt n) 0 nxt)))""",
"PrevVine": """(fn PrevVine ()
  (bind n (Utilities|Array|Length :TargetArray (Variables|Vines|GetFullIndices)))
  (bind prv (- (Variables|Vines|GetActiveIndex) 1))
  (CallFunction|SetVine :Index (select (< prv 0) (- n 1) prv)))""",
}
ORDER = ["ApplyGrowth", "ApplyVisibility", "ApplyMaterial", "PlayGrowth", "StopGrowth", "ResetGrowth", "SetVine", "ResetSim", "PickRandomSet", "SyncChanges", "NextVine", "PrevVine"]

EVENTS = """
(event EventBeginPlay
  (Variables|Default|SetLastIndex (Variables|Vines|GetActiveIndex))
  (Variables|Default|SetLastLoopMode (Variables|Vines|GetLoopMode))
  (Variables|Default|SetLastRandomMode (Variables|Vines|GetRandomMode))
  (if (Variables|Vines|GetRandomMode)
    (CallFunction|PickRandomSet))
  (CallFunction|ApplyVisibility)
  (CallFunction|ApplyMaterial)
  (if (Variables|Vines|GetAutoPlay)
    (CallFunction|ResetGrowth)
    (CallFunction|PlayGrowth)
    (else
      (CallFunction|ApplyGrowth))))

(event EventTick (DeltaSeconds)
  (CallFunction|SyncChanges)
  (if (Variables|Default|GetPlaying)
    (bind g (+ (Variables|Vines|GetGrowthFront)
               (* (/ (* DeltaSeconds (Variables|Vines|GetSpeed))
                     (Math|Float|Max(Float) (Variables|Vines|GetDuration) 0.01))
                  (Variables|Default|GetDir))))
    (bind mode (Variables|Vines|GetLoopMode))
    (if (>= g 1.0)
      (if (== mode 0)
        (Variables|Vines|SetGrowthFront 1.0)
        (Variables|Default|SetPlaying false)
        (elif (== mode 1)
          (Variables|Vines|SetGrowthFront 0.0)
          (if (Variables|Vines|GetRandomMode)
            (CallFunction|PickRandomSet)
            (CallFunction|ApplyVisibility))
          (else
            (Variables|Vines|SetGrowthFront 1.0)
            (Variables|Default|SetDir (- 0.0 1.0)))))
      (elif (<= g 0.0)
        (Variables|Vines|SetGrowthFront 0.0)
        (Variables|Default|SetDir 1.0)
        (if (Variables|Vines|GetRandomMode)
          (CallFunction|PickRandomSet)
          (CallFunction|ApplyVisibility))
        (else
          (Variables|Vines|SetGrowthFront g))))
    (CallFunction|ApplyGrowth)))
"""
CONSTRUCTION = """(event ConstructionScript
  (if (Variables|Vines|GetNewRandomSet)
    (CallFunction|PickRandomSet))
  (if (Variables|Vines|GetResetNow)
    (Variables|Vines|SetResetNow false)
    (Variables|Vines|SetGrowthFront 0.0))
  (CallFunction|ApplyVisibility)
  (CallFunction|ApplyGrowth))"""


def ensure_vars():
    have = {v["name"] if isinstance(v, dict) else str(v) for v in (call(BT, "list_variables", {"blueprint": bp, "graph": None}) or [])}
    for n, t, cat, editable, cont in [("LastIndex", "int", "Default", False, None), ("LastLoopMode", "int", "Default", False, None), ("ResetNow", "bool", "Vines", True, None),
                                      ("FullIndices", "int", "Vines", True, "ARRAY"), ("SmallIndices", "int", "Vines", True, "ARRAY"), ("Selected", "int", "Default", False, "ARRAY"),
                                      ("RandomMode", "bool", "Vines", True, None), ("RandomMin", "int", "Vines", True, None), ("RandomMax", "int", "Vines", True, None),
                                      ("NewRandomSet", "bool", "Vines", True, None), ("LastRandomMode", "bool", "Default", False, None)]:
        if n not in have:
            call(BT, "add_variable", {"blueprint": bp, "name": n, "type_name": t, "graph": None, "container_type": cont})
            call(BT, "set_variable_category", {"blueprint": bp, "variable_name": n, "category": cat})
            call(BT, "set_variable_instance_editable", {"blueprint": bp, "variable_name": n, "instance_editable": editable})
            print("added var", n)


def main():
    ensure_vars()
    names = {f["name"] for f in call(BT, "list_functions", {"blueprint": bp})}
    for old in ["Reset", "Play", "Stop"]:
        if old in names:
            call(BT, "remove_function_graph", {"blueprint": bp, "graph_name": old}); print("removed", old)
    # clear the graphs that call other functions first, so no dangling call node breaks compiles
    for gname in ["EventGraph", "SetVine", "NextVine", "PrevVine", "ResetGrowth", "ResetSim", "PickRandomSet", "SyncChanges", "UserConstructionScript"]:
        if gname in names or gname in ("EventGraph", "UserConstructionScript"):
            clear(graph(gname), keep_entries=(gname != "EventGraph"))
    names = {f["name"] for f in call(BT, "list_functions", {"blueprint": bp})}
    for n in ORDER:
        if n not in names:
            g = call(BT, "add_function_graph", {"blueprint": bp, "graph_name": n})
            if n == "SetVine":
                call(BT, "add_function_param", {"graph": g, "param_name": "Index", "param_type": "int", "input_param": True, "container_type": None})
        else:
            g = graph(n); clear(g)
        call(BT, "write_graph_dsl", {"graph": g, "code": FUNCS[n]}); print(n, "OK")
    eg = graph("EventGraph"); clear(eg, keep_entries=False)
    call(BT, "write_graph_dsl", {"graph": eg, "code": EVENTS}); print("EventGraph OK")
    cs = graph("UserConstructionScript"); clear(cs)
    call(BT, "write_graph_dsl", {"graph": cs, "code": CONSTRUCTION}); print("ConstructionScript OK")
    print("compile", call(BT, "compile_blueprint", {"blueprint": bp, "warnings_as_errors": True}))
    bad_total = 0
    for gname in ["EventGraph", "UserConstructionScript"] + ORDER:
        txt = str(call(BT, "read_graph_dsl", {"graph": graph(gname)}))
        bad = [l for l in txt.splitlines() if "TypedElement" in l or "Animation|Play" in l or "|Reset)" in l]
        bad_total += len(bad)
        print("##", gname, "BAD " + str(bad[:2]) if bad else "ok")
        if gname in ("EventGraph", "SetVine", "UserConstructionScript"):
            print(txt[:1200])
    cdo = call(BT, "get_default_object", {"blueprint": bp})
    call(OT, "set_properties", {"instance": cdo, "values": json.dumps({"LastIndex": -1, "LastLoopMode": -1, "ResetNow": False, "RandomMin": 2, "RandomMax": 4, "RandomMode": False, "NewRandomSet": False, "LastRandomMode": False})})
    print("save", call(AT, "save_assets", {"asset_paths": [BP_PATH]}))
    print("BP_OK" if bad_total == 0 else "BP_HAS_BAD_NODES")


if __name__ == "__main__":
    main()
