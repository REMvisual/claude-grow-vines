# Deploying a grow-vines vine in Unreal Engine

Each `grow_vine.py` run produces `vine_<name>_wpo.fbx` + a `tex/` PBR set. This pack ships the
two parameterized master materials that drive the growth. **Engine: authored in UE 5.7**
(`.uasset` is version-locked — re-save from your engine if it won't load).

## Material parameters (verified on `M_Vine_Leaf` / `M_Vine_Bark`)
| Type | Names |
|---|---|
| Texture | `Color`, `Normal`, `Roughness` |
| Scalar | `GrowthFront` (0..1 reveal+unfurl), `GrowWindow` (unfurl edge width), `SoftBand` (opacity edge), `WPOScale` (unfurl throw) |

Both materials are **Masked, two-sided**, with the WPO + opacity-reveal graph from
`reference/UE_VINE_WIPE_SHADER.md` already wired to the 5 UV channels
(`UVMap, wipe=gt_point, dx, dy, dz`).

## Steps
1. **Copy the materials in.** Put `Content/VineWPO/` (`M_Vine_Leaf`, `M_Vine_Bark`, and
   `reference/` example) into your project's `Content/`. (Or migrate the two `.uasset`s.)
2. **Import the mesh.** Import `vine_<name>_wpo.fbx` with **Offset Uniform Scale = 100**
   (UE 5.5+ Interchange), so it lands in centimetres matching the baked `dx/dy/dz` deltas.
   Enable **Nanite** on the static mesh. Keep all 5 UV channels (do not let import drop UVs).
3. **Import textures.** Import the run's `tex/*`. The leaf **`Color`** map is the packed
   **`*_leaf_color_rgba.png`** (RGB = colour, **A = leaf cutout**); plus that species' `*_NORMAL*`
   and `*_rough*`. Bark maps are `bark_color/bark_normal/bark_roughness`.
   - On the `_rgba` textures, keep the **alpha channel** (Compression that preserves alpha, e.g.
     BC7/Masks; do NOT tick "Compress Without Alpha"), or the cutout is lost.
4. **Make Material Instances.**
   - `MI_<name>_Leaf` from `M_Vine_Leaf` → `Color` = the **`*_leaf_color_rgba.png`**,
     `Normal`/`Roughness` = that species' maps. **The leaf `Color` MUST be RGBA** — the material
     masks via `OpacityMask = reveal * Color.A`. Feeding a non-RGBA (opaque) colour map yields
     square leaf cards; if you only have a plain colour + separate `*_ALPHA`, **reconnect**
     `OpacityMask` to a dedicated alpha `TextureSample` instead of `Color.A`.
   - One leaf MI **per leaf-species slot** (multi-species blends export several leaf slots).
   - `MI_<name>_Bark` from `M_Vine_Bark` → `Color`/`Normal`/`Roughness` = the `bark_*` maps.
   Assign each MI to its mesh material slot (bark tube slot = bark, leaf-card slot(s) = leaf).
5. **Enable WPO on the component.** On the static-mesh component tick **Evaluate World
   Position Offset** (off-by-default for Nanite WPO in some versions) and set a sensible
   **WPO Disable Distance**. Keep `r.Nanite.AllowMaskedMaterials=1` (default on).
6. **Drive the growth.** Make a Material Instance *Dynamic* per vine and each frame:
   `MID->SetScalarParameterValue("GrowthFront", phase01)`.
   - grow = 0→1, ungrow = 1→0, scrub = any value (e.g. from OSC `/vine/<id>/phase`).
   - Tune look: `GrowWindow` ≈ 0.12, `SoftBand` ≈ 0.03, `WPOScale` = 1.0 (raise for a bigger
     unfurl throw).

## Notes
- The reveal is driven entirely by the single `GrowthFront` scalar — reverse/loop/scrub are free.
- This is the 5-UV build (no per-leaf `card` lag channel); the leaf reveal lag, if wanted, is
  applied uniformly via the material rather than per-card.
