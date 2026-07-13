---
name: grow-vines
description: Grow a UE-ready WPO-wipe vine over any mesh from a natural-language brief. Given a mesh (OBJ/FBX/glTF or a primitive) and a brief like "dense ivy mat creeping from outside" / "bold climbers from the base" / "a spiral vortex into the front", it grows a vine via space colonization, bakes bark+leaf PBR textures, and exports a 5-UV static FBX (UVMap, wipe, dx, dy, dz) that reveals + unfurls from a single GrowthFront 0-1 scalar — plus the parameterized Unreal materials to deploy it. Triggers on "grow vines", "grow a vine on this mesh", "vine over X", "make a growing vine", "WPO vine", "GrowthFront vine".
---

# grow-vines

Turns a **mesh + a natural-language brief** into a deployable growing vine. The brief is the
control surface — it picks where the vine starts and how it spreads.

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

## Deploy in Unreal
`unreal/Content/VineWPO/` ships the parameterized masters **`M_Vine_Leaf`** and
**`M_Vine_Bark`** (UE 5.7). Per vine, make Material Instances, set `Color/Normal/Roughness`
to the baked maps, import the FBX at **Offset Uniform Scale 100** with Nanite, and drive
`GrowthFront` 0→1. Full steps: `unreal/IMPORT.md`. Shader reference: `reference/UE_VINE_WIPE_SHADER.md`.

## Running as a subagent
Self-contained: dispatch with the mesh path, the brief, and an output dir. Run the headless
command above, then the independent verify, then report the compliance JSON + texture list. Do
not modify `scripts/plantgen/` (it is the vendored, proven generator).

## How it works (internals)
`scripts/intent_map.py` (brief → recipe) → `scripts/grow_vine.py` (autofit → build → bake 5 UVs
→ export → reimport-verify → textures) over the vendored `scripts/plantgen/` core
(`skeleton`, `skin`, `foliage` + `leaf_fallback`, `hero`, `rnd/` skeleton generators). Same
build+export path proven across the 25 baked looks.
