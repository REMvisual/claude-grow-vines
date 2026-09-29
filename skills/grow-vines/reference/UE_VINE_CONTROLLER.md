# UE vine controller — MPC + BP_VineController (known process)

What ships in `unreal/Content/` and how it was built, so it can be re-deployed or re-authored
without rediscovering anything. Authored live in **UE 5.8** through Epic's ModelContextProtocol
plugin (`scripts/unreal/uemcp.py` raw client + the `ue_*.py` drivers). Verified on a 20-vine
stage set.

## 1. Growth wiring (why a Material Parameter Collection)
`M_Vine_Leaf` / `M_Vine_Bark` originally read a per-instance scalar `GrowthFront`. Driving 20
vines × 3–16 material slots through MIDs is heavy and error-prone, so both masters now compute

    GrowthFront_effective = ScalarParameter("GrowthFront")  ×  CollectionParameter(MPC_Vines, "GrowthFront")

wired into both Custom (HLSL) nodes (`LeafRevealMask` opacity + `VineUnfurlWPO`). Defaults are 1 × 1,
so nothing changes visually until something writes the collection. One `SetScalarParameterValue`
on the collection drives every vine; the per-instance scalar still works as a manual scale.

`MPC_Vines` scalars: `GrowthFront`(1) `SoftBand`(0.03) `GrowWindow`(0.15) `WPOScale`(1). Only
`GrowthFront` is wired; the other three are placeholders for a future wiring pass — the live
look controls are still the per-instance scalars (`GrowWindow` 0.12–0.15, `SoftBand` 0.03).

The masters' texture parameters default to `T_VineDefault_{Color,Normal,Roughness}` (tiny flat
textures shipped next to them) — a master with NULL texture defaults **fails to compile** and every
instance goes to the default material.

## 2. BP_VineController (Actor) — behaviour
One actor in the level. Holds a list of vine actors and drives the collection.

| Variable (category Vines, instance-editable) | Meaning |
|---|---|
| `Vines` (Actor[]) | every vine actor, in order (set by `ue_place.py`) |
| `FullIndices` (int[]) | indices into `Vines` of the full-stage vines (the "more" ones) |
| `SmallIndices` (int[]) | indices of the smaller / local vines (the "less" ones) — the random pool |
| `ActiveIndex` | which of `FullIndices` is shown in single mode |
| `RandomMode` | off = single full vine; on = a random cluster of `RandomMin..RandomMax` small vines grown together |
| `RandomMin` / `RandomMax` | cluster size (2..4 by default) |
| `AutoPlay`, `Duration` (s), `Speed`, `LoopMode` (0 once, 1 loop, 2 ping-pong) | playback |
| `GrowthFront` | manual scrub when AutoPlay is off (also previews in the editor) |
| `ShowAll` | show every vine at once |
| `MaterialOverride` | optional material applied to every slot of every vine (empty = per-vine MIs) |
| `ResetNow` | tick = restart with the current loop mode + re-apply material override (self-clears) |
| `NewRandomSet` | tick = new random cluster now (self-clears) |
| `Collection` | the MPC (default `MPC_Vines`) |

Rules:
- **Random mode re-rolls the cluster at every cycle boundary**: once → each reset, loop → each
  wrap to 0, ping-pong → each return to 0. Entering Play or switching modes also re-rolls.
- Changing `ActiveIndex`, `LoopMode` or `RandomMode` **during Play** is picked up every tick
  (`SyncChanges`) and restarts the growth. `Duration` / `Speed` are read every tick.
- In the editor (no Play) the ConstructionScript applies visibility + growth, so scrubbing
  `ActiveIndex` / `GrowthFront` / `ShowAll` in Details previews immediately.
- Visibility = `SetActorHiddenInGame` **and** `SetVisibility` on the StaticMeshComponent
  (the first alone does nothing in the editor viewport).
- Public functions for Sequencer / OSC / other BPs: `SetVine(Index)`, `NextVine`, `PrevVine`,
  `PlayGrowth`, `StopGrowth`, `ResetGrowth`, `ResetSim`, `PickRandomSet`, `ApplyMaterial`.
- "Buttons" are self-clearing bools because the MCP cannot set *Call In Editor* on a function.

Graphs: `ApplyGrowth` (writes the MPC), `ApplyVisibility`, `ApplyMaterial`, `PlayGrowth`,
`StopGrowth`, `ResetGrowth`, `SetVine`, `ResetSim`, `PickRandomSet` (shuffle pool, take k),
`SyncChanges`, `NextVine`, `PrevVine`, EventGraph (BeginPlay + Tick), ConstructionScript.
Source of truth for the graphs: `scripts/unreal/ue_bp_vinecontroller.py` (rebuilds every graph
from the DSL, compiles with warnings-as-errors, reads every graph back and greps for foreign nodes).

## 3. Density split (the "more / less" itemisation)
Classify by **stage coverage**, not vertex count: whole-set mats/climbers are "full", single-panel
vortices / one-wing climbers / crest-only vines are "small" and combine well 2–4 at a time.
Example 20-vine set: full = 01,03,06,09,10,12,13,14,19,20; small = 02,04,05,07,08,11,15,16,17,18
(a whole-set but sparse mat is the usual borderline case: put it wherever it reads better). Set the two index arrays on the placed controller.

## 4. Process (repeatable)
1. Copy `unreal/Content/VineWPO/*` and `unreal/Content/PFG/*` into the project **at those paths**
   (`.uasset` files embed their package path; anywhere else = redirect/mismatch). Do it before the
   editor opens, or refresh the content browser.
2. `ue_import_live.py` — mesh (Nanite) + textures + one MIC per slot into `<VINES_UE_ROOT>/<name>/`;
   `--dry` prints the slot→texture map (abort on `C=None` / `NO-ALPHA`). Packs colour+alpha to
   `*_rgba.png` locally when the asset ships them separately (BagaIvy), incl. `*_maps*.png` cutouts.
3. `ue_verify.py` (headless, read-only, can run beside the open editor) — 5 UV sets via
   GeometryScript, Nanite, slots→MI.
4. `ue_place.py <from> <to>` in the open level (batches; `--save` saves the level once the user
   has checked), then set `FullIndices` / `SmallIndices` on `BP_VineController_1` (0-based
   indices into `Vines`, which is vine-number order).
5. Test in editor without Play (ActiveIndex / GrowthFront / ShowAll), then Play.

## 5. Gotchas that cost time (all live-verified)
- Editor in **PIE** ⇒ `AssetTools.exists/save/is_dirty` all say "asset does not exist". Wait for PIE.
- `write_graph_dsl` **appends**; clear graphs first. Function names must be unique — `Reset`/`Play`
  silently bound to unrelated engine nodes and still compiled.
- Object refs in `ObjectTools.set_properties` are `{"refPath": ...}` inside a **JSON string**.
- Texture sampler types must match the textures instances will feed (`Normal`, `LinearColor`).
- A GPU crash mid-session lost nothing because every step saves as it goes — keep it that way.
