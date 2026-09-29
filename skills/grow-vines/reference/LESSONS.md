# Lessons learned — grow-vines end to end (grow → Unreal → controller)

Distilled from a 20-vine stage-set deployment: 20 vines grown headless, imported live into
UE 5.8, driven by one controller. Each line is something that cost time or was
non-obvious. Process lessons first, then per phase.

## Process
- **Two phases, one hand-off.** Phase 1 ("grow the vines / prompt the trees") ends with a folder
  per vine + `wpo_compliance.json`. Phase 2 starts on the words "open Unreal / ingest / import the
  vines / give me the BP". Nothing in phase 2 needs Blender; nothing in phase 1 needs Unreal.
- **Batches of 5, user checks, then save.** Place actors in batches, stop, let the user look,
  save only after "fine". A show level is not a scratch level.
- **Announce before touching the editor** so the user can go hands-off; ask which level is open
  (`get_current_level`) rather than assuming. The user may have opened a fresh level for the vines.
- **Save as you go.** Import script saves per vine; BP/MPC/masters saved after each rebuild. A GPU
  crash mid-session lost nothing because of this.
- **Verify by reading back, never by exit code.** Material wiring: `get_expression_inputs`.
  Blueprint: `read_graph_dsl` every graph + grep for foreign node ids. Placement: component
  `bVisible` per actor. UV count: headless GeometryScript, not the render-data API.
- **Editor "buttons" are self-clearing bools** when the tooling can't set Call-In-Editor; the user
  accepted tick-boxes for Reset / NewRandomSet.
- **Behaviour changes ride on Tick + ConstructionScript.** Anything the user edits in Details
  during Play must be re-read every tick (`SyncChanges`); anything edited outside Play must be
  applied by the ConstructionScript, or "switching doesn't work".

## Phase 1 — growing (multi-piece sets)
- The skill assumes one wall-like mesh. For a stage set (floor + panels + wings + arc): drop the
  floor/platform group BEFORE joining, drop faces not facing the audience, weld the pieces so only
  true silhouettes are boundary edges, and snap through a crease-aware proxy (openness test +
  silhouette band + escape push) or stems trace triangle seams and panel outlines.
- Seed climbers ON the focus piece's lower band; "outside" seeds snap to neighbours.
- Vortices only read on a single panel or wing, never on the whole multi-piece set.
- Autofit over-scales `base_r` on wide sets (~x2): pass `base_r` explicitly (0.022–0.05 m).
- Name outputs `<PREFIX>_<NN>_<Name>` from the start; every later script sorts by that.

## Phase 2 — Unreal ingest
- `.uasset` files embed their package path. Ship `Content/VineWPO/` + `Content/PFG/` together and
  copy them at exactly those paths.
- A master whose texture parameters default to NULL **fails to compile** (every instance shows the
  default material). Ship tiny default textures and set sampler types to match what instances
  feed (`Normal`, `LinearColor`).
- One MIC per mesh slot, parented to the leaf or bark master. Slot names are the source
  material names, and BagaIvy's are a zoo (colour variants, pistil/stem slots, `Color2`,
  `colo_v2`, `Leaf_Maps`). Resolve by token scoring + side (leaf/flower) + colour variant, pack
  colour+alpha into `*_rgba.png` locally when the alpha ships separately (a `*_maps*.png`
  white-on-black file is a cutout too). Dry-run the map before importing.
- Interchange keeps all 5 UV sets; verify anyway (`ue_verify.py`).
- Play-In-Editor makes every asset-library call answer "asset does not exist". Wait, don't stop
  the user's session.
- `SetActorHiddenInGame` does nothing in the editor viewport; hide the component too.

## Controller design
- Drive growth through a Material Parameter Collection multiplied into the per-instance
  scalar: one write animates every vine, instances keep working, defaults 1×1 change nothing.
- Split vines by **stage coverage** into full-stage (one at a time, indexed) and small/local
  (random clusters of 2–4). Density by vertex count misleads (a centre-panel rose vortex has more
  verts than a whole-set sparse mat).
- Random clusters re-roll at cycle boundaries (once: each reset, loop: each wrap, ping-pong: each
  return to 0), plus a manual re-roll. Users read "new set every loop" as the natural behaviour.
- Keep public functions (`SetVine`, `NextVine`, `PlayGrowth`, …) for Sequencer/OSC even when the
  Details panel is the day-to-day UI.
