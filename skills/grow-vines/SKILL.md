---
name: grow-vines
description: Grow a UE-ready WPO-wipe vine over any mesh from a natural-language brief. Given a mesh (OBJ/FBX/glTF or a primitive) and a brief like "dense ivy mat creeping from outside" / "bold climbers from the base" / "a spiral vortex into the front", it grows a vine via space colonization, bakes bark+leaf PBR textures, and exports a 5-UV static FBX (UVMap, wipe, dx, dy, dz) that reveals + unfurls from a single GrowthFront 0-1 scalar — plus the parameterized Unreal materials to deploy it. Triggers on "grow vines", "grow a vine on this mesh", "vine over X", "make a growing vine", "WPO vine", "GrowthFront vine" — and, once vines exist, on "open Unreal", "ingest / import the vines into Unreal", "vine controller", "switch between vines", "grow them in the level", "the BP for the vines".
---

# grow-vines

Turns a **mesh + a natural-language brief** into a deployable growing vine. The brief is the
control surface — it picks where the vine starts and how it spreads.

## The pipeline (two phases, one hand-off)
| Phase | User says | You do | Done when |
|---|---|---|---|
| 1 Grow | "grow vines on X", "prompt the trees", "20 vines for the set" | run `grow_vine.py` once per vine (headless Blender), independent verify | one folder per vine with `<name>_wpo.fbx`, `tex/`, `wpo_compliance.json` PASS |
| 2 Ingest | "open Unreal", "ingest / import the vines", "here's the BP" | **Deploy in Unreal** below: content folders in → `ue_import_live.py` → `ue_verify.py` → `ue_place.py` in batches of 5 (user checks, then `--save`) → set the controller's Full/Small lists | all vines in the open level, `BP_VineController_1` switching and growing them, level saved |

Phase 2 needs a running UE 5.8 editor with Epic's ModelContextProtocol plugin (port 8001);
phase 1 needs no Unreal. Read `reference/LESSONS.md` before either phase on a multi-piece set
(stage, floor + panels) — the defaults assume one wall-like mesh.

## Prerequisites
- **Blender 4.2+** (developed and verified on 5.1) run headless, e.g.
  `"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"` on Windows.
- **Bark textures** (one-time): `python scripts/fetch_assets.py` downloads the three
  ambientCG bark PBR sets (CC0) into `scripts/assets/bark/`.
- **BagaIvy addon (optional, recommended)** — the photoreal leaf/flower card library.
  If installed (auto-detected, or point `BAGAIVY_DIR` at its addon folder), leaves are
  photoscanned cards across 60 species. **Without it the skill still works**: a procedural
  leaf-card generator (`scripts/plantgen/leaf_fallback.py`) synthesizes stylized leaf and
  flower cards per species — good silhouettes at set-dressing distance.
- Always run **headless** with `--factory-startup` and `PYTHONHASHSEED=0` (determinism).
- No live Blender/Unreal MCP is required for generation.

## How to run (one isolated headless Blender per vine)
```
PYTHONHASHSEED=0 "<blender>" --background --factory-startup \
  --python "<skill>/scripts/grow_vine.py" -- <MESH> "<BRIEF>" <OUTDIR> [NAME]
```
- `<MESH>`: path to a `.obj` / `.fbx` / `.gltf` / `.glb` (multi-part assets are joined into one target), or a primitive keyword `sphere` | `cube` | `plane`.
- `<BRIEF>`: free text (see Brief → behaviour below).
- `<OUTDIR>`: output folder (created).
- `[NAME]`: optional output base name.

Example:
```
PYTHONHASHSEED=0 "$BL" --background --factory-startup \
  --python "$SK/scripts/grow_vine.py" -- "C:/models/pillar.fbx" \
  "bold ivy climbers rising from the base" "C:/out/pillar_vine"
```

## Brief → behaviour (contextual)
| Say… | Result |
|---|---|
| "creeping mat **from outside**", "overgrown", "ground-cover" (default) | seeds beyond the silhouette, mats over the surface |
| "**from inside** / from the surface", "sprouting/erupting out of the mesh" | on-surface scatter seeds — vine emerges from the mesh |
| "**climbing** / vertical / rising from the base", "bold columns" | vertical climbers from the bottom edge |
| "**spiral / vortex / winding into** a point" | structured logarithmic-spiral swirl |

Also understood: density (`sparse` ↔ `dense/lush`), stem thickness (`fine/wire` ↔ `bold/thick`),
species (`grape, ivy, jasmine, fig, wire, clematis, wisteria, honeysuckle, hops, rose,
bougainvillea`), and flowers (`flowering` ↔ `foliage only`). Growth params **auto-fit** to the
mesh's bounding box, so any size works. See `presets/recipes.json`.

## What a run produces (in `<OUTDIR>`)
- `vine_<name>_wpo.fbx` — static mesh, **5 UV channels** `UVMap, wipe(=gt_point), dx, dy, dz`.
- `tex/` — bark + leaf PBR maps (`*_leaf_*` + `bark_color/normal/roughness`).
- `wpo_compliance.json` — verify record; `README.md` — per-run deploy summary.

## Verify (don't trust the gate)
The run self-verifies by reimport, but to confirm independently:
```
"<blender>" --background --factory-startup \
  --python "<skill>/scripts/verify_wpo_independent.py" -- "<OUTDIR>/vine_<name>_wpo.fbx"
```
Expect `INDEP_VERIFY: PASS` — exactly 5 UV layers and `dx/dz` ranges of ±(tens of cm), i.e.
real unfurl deltas, not zeros.

## Deploy in Unreal (phase 2)
`unreal/Content/` ships a ready-to-go set (UE 5.8): masters **`M_Vine_Leaf`** / **`M_Vine_Bark`**
(`VineWPO/`, `GrowthFront = instance x collection`), the collection **`MPC_Vines`** and the
switcher/auto-player **`BP_VineController`** (`PFG/`). In order:
1. Copy `unreal/Content/VineWPO/` and `unreal/Content/PFG/` into the project **at those paths**.
2. Editor open, MCP listening: tell the user you are about to touch assets, then
   `python scripts/unreal/ue_import_live.py --dry` (slot→texture map) and without `--dry`
   (mesh + Nanite + textures + one MIC per slot, saved per vine). Env: `VINES_DIR` (folder of
   vine folders), `VINES_UE_ROOT` (`/Game/...` destination), `VINES_PREFIX` (folder prefix; folders
   are `<PREFIX><NN>_<Name>`, vine number NN drives the batches, `Vines` array is 0-based).
3. `ue_verify.py` headless (5 UV sets, Nanite, every slot bound) — read the JSON, not the exit code.
4. Ask which level is open; `python scripts/unreal/ue_place.py 1 5`, stop, user checks, then
   `--save` (saves the open level) and the next five. The controller is placed with the first batch.
5. On `BP_VineController_1` set `FullIndices` (full-stage vines) and `SmallIndices` (smaller
   vines) — see the density rule in `reference/UE_VINE_CONTROLLER.md` §3.
6. Hand over the controls: `unreal/IMPORT.md` "Controller cheat-sheet".
Rebuild the Blueprint from source with `scripts/unreal/ue_bp_vinecontroller.py` if it must change.
Gotchas that will bite: `reference/LESSONS.md`. Shader: `reference/UE_VINE_WIPE_SHADER.md`.

## Running as a subagent
Self-contained: dispatch with the mesh path, the brief, and an output dir. Run the headless
command above, then the independent verify, then report the compliance JSON + texture list. Do
not modify `scripts/plantgen/` (it is the vendored, proven generator).

## How it works (internals)
`scripts/intent_map.py` (brief → recipe) → `scripts/grow_vine.py` (autofit → build → bake 5 UVs
→ export → reimport-verify → textures) over the vendored `scripts/plantgen/` core
(`skeleton`, `skin`, `foliage` + `leaf_fallback`, `hero`, `rnd/` skeleton generators). Same
build+export path proven across the 25 baked looks.
