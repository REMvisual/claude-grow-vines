# Deploying grow-vines vines in Unreal Engine

Each `grow_vine.py` run produces `<name>_wpo.fbx` + a `tex/` PBR set. This pack ships the
parameterized master materials, a Material Parameter Collection and a ready-to-go controller
Blueprint. **Engine: authored in UE 5.8** (`.uasset` is version-locked — re-save from your engine
if it won't load). `.uasset` files embed their package path: copy the folders **exactly** as
`Content/VineWPO/` and `Content/PFG/` or the references break.

## What is in `unreal/Content/`
| Path | What |
|---|---|
| `VineWPO/M_Vine_Leaf`, `VineWPO/M_Vine_Bark` | masters: Masked two-sided, 5-UV wipe + unfurl WPO, `GrowthFront = instance × MPC` |
| `VineWPO/T_VineDefault_{Color,Normal,Roughness}` | tiny default textures so the masters compile stand-alone |
| `PFG/MPC_Vines` | Material Parameter Collection: `GrowthFront` (wired into both masters); `SoftBand`, `GrowWindow`, `WPOScale` exist but are placeholders, the per-instance scalars are the live ones |
| `PFG/BP_VineController` | the switcher / auto-player (see `reference/UE_VINE_CONTROLLER.md`) |

Material parameters (both masters): Texture `Color`, `Normal`, `Roughness`; Scalar `GrowthFront`
(0..1 reveal+unfurl, multiplied by the collection), `GrowWindow`, `SoftBand`, `WPOScale`.

## Fast path (editor running with Epic's ModelContextProtocol plugin, port 8001)
Naming contract: every vine folder is `<PREFIX><NN>_<Name>` (e.g. `PFG_07_HoneysuckleArch`,
`V_03_Rose`) and holds `<folder name>_wpo.fbx` + `tex/`. `NN` is the vine number used by the
batch arguments; the controller's `Vines` array is that order, **0-based** (vine 07 = index 6).
Scripts run from any directory; `<skill>` is the skill folder (`~/.claude/skills/grow-vines`).
Copy the two Content folders in before starting (a running editor picks new folders up on the
next content-browser refresh; restarting is the safe option).
```
set VINES_DIR=<folder holding the vine folders>     e.g. D:\show\vines
set VINES_UE_ROOT=/Game/PFG/Vines                    where the vines land in the project
set VINES_PREFIX=V_                                  the folder prefix (default PFG_)
python <skill>/scripts/unreal/ue_import_live.py --dry   # slot -> texture map, touches nothing
python <skill>/scripts/unreal/ue_import_live.py         # mesh (Nanite) + textures + one MIC per slot, saved per vine
python <skill>/scripts/unreal/ue_place.py 1 5           # vines 01-05 + BP_VineController_1 into the OPEN level
python <skill>/scripts/unreal/ue_place.py --save        # saves the open level (with the placed actors); skip = unsaved
python <skill>/scripts/unreal/ue_place.py 6 10          # next batch, then --save again
```
`--dry` is a review step: abort if a leaf/flower slot shows `C=None` or `NO-ALPHA`, fix the
texture names, re-run. The script import lands in centimetres already (bounds match the source
set); the "Offset Uniform Scale = 100" below is for the manual importer only.
Headless read-only check (5 UV sets, Nanite, slots→MI) — runs fine while the editor is open:
```
"<UE>/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" <YourProject>.uproject -run=pythonscript ^
   -script="<skill>/scripts/unreal/ue_verify.py" -unattended -nullrhi -log
```
Then on `BP_VineController_1` set `FullIndices` (full-stage vines) and `SmallIndices` (smaller
vines for the random clusters) — indices into its `Vines` list.

## Manual path
1. **Copy the content in** (`Content/VineWPO/`, `Content/PFG/`).
2. **Import the mesh** with **Offset Uniform Scale = 100** (Interchange), so it lands in centimetres
   matching the baked `dx/dy/dz` deltas. Enable **Nanite**. Keep all 5 UV channels.
3. **Import textures.** Leaf/flower **`Color`** = the packed `*_rgba.png` (RGB colour, **A = cutout**);
   keep the alpha (BC7, never "Compress Without Alpha"). Normal maps `TC_Normalmap`, roughness linear.
4. **Material Instances**: one MI per mesh slot — bark slot from `M_Vine_Bark`, leaf/flower slots
   from `M_Vine_Leaf`; set `Color/Normal/Roughness`. A non-RGBA leaf colour gives square cards.
5. **WPO on the component**: tick **Evaluate World Position Offset** and set a **WPO Disable
   Distance**; keep `r.Nanite.AllowMaskedMaterials=1`.
6. **Drive the growth**: place `BP_VineController`, fill `Vines`, press Play — or write
   `MPC_Vines.GrowthFront` yourself (`SetScalarParameterValue` on the collection): grow 0→1,
   ungrow 1→0, scrub anything (e.g. OSC `/vine/phase`). Look tuning (per instance): `GrowWindow` 0.12–0.15,
   `SoftBand` ≈ 0.03, `WPOScale` 1.0.

## Controller cheat-sheet (`BP_VineController_1`, category Vines)
- `RandomMode` off: `ActiveIndex` picks one of `FullIndices` (`NextVine`/`PrevVine` cycle it).
- `RandomMode` on: shows `RandomMin..RandomMax` random `SmallIndices` grown together; a new set is
  rolled at every cycle boundary (once: each reset, loop: each wrap, ping-pong: each return to 0).
- `LoopMode` 0 once / 1 loop / 2 ping-pong; `Duration` seconds; `Speed` multiplier (live).
- `ResetNow` = restart + re-apply `MaterialOverride`; `NewRandomSet` = re-roll now; `ShowAll`.
- Changing `ActiveIndex` / `LoopMode` / `RandomMode` during Play restarts on its own.
- No Play needed to preview: `ActiveIndex`, `GrowthFront`, `ShowAll` apply in the editor.
