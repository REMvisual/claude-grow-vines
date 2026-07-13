# UE Vine Wipe Material — Level 1 (reveal) & Level 2 (WPO scale-in)

How to reproduce the Blender growth-preview grow-in on a
**Nanite static mesh + material**, driven by a single `GrowthFront` 0–1 scalar (your TD/OSC
value). Level 1 = the simple opacity reveal (you're building this). Level 2 = add World
Position Offset so geometry physically scales in from its stem (matches the smooth video).

The vine's growth coordinate is `gt_point` ∈ [0,1] (0 at root, 1 at tips), stored per vertex.
Everything keys off comparing `gt_point` to `GrowthFront`.

---

## Level 1 — opacity reveal (simple, ~30 min)

Data needed (already on `vine_<look>_static_wipe.fbx`): UV1 `wipe` where **U = gt_point**.

Material: Domain **Surface**, Blend Mode **Masked**, **Two-Sided** (leaves), Nanite-OK.

```
TexCoord(1) ─► Mask(R) ──────────────► wipe            // = gt_point, per pixel
ScalarParameter "GrowthFront" (0..1)
ScalarParameter "SoftBand"   (≈0.03)

reveal = saturate( (GrowthFront - wipe) / SoftBand )   // 1 where grown, soft 0..1 edge, 0 ahead
```
- **Bark material:** `Opacity Mask = reveal`.
- **Leaf material:** sample the leaf color/alpha on **UV0** (pin an explicit `TexCoord(0)` into
  the sampler or it grabs the wipe UV → brown), then `Opacity Mask = reveal * LeafTex.A`.
- Drive it: per vine, make a **Material Instance Dynamic** and each frame
  `MID->SetScalarParameterValue("GrowthFront", phase01)` from your OSC handler.
  Grow = phase 0→1, ungrow = 1→0, scrub = whatever TD sends. Reverse/loop are free.
- Optional "leaf lag" (leaves trail the branch front like the ABC): for the leaf material use
  `reveal = saturate((GrowthFront - wipe - LeafLag)/SoftBand)`, `LeafLag ≈ 0.15`.

That's the whole simple path. Smooth fade, dozens of instances, instant scrub. It does **not**
physically unfurl geometry — that's Level 2.

---

## Level 2 — WPO scale-in (matches the smooth video)

### The idea (same math the ABC bakes)
Blender's reveal does: `pos = pivot + (pos - pivot) * s`, i.e. each vertex starts collapsed at
its `pivot` (stem) and scales out to its real position as the front passes. Rearranged for a
World Position Offset (an *offset added* to the vertex):

```
delta = pivot - pos                       // vector from vertex to its stem (local space)
s     = smoothstep( 0, 1, (GrowthFront - gt_point - LeafLag*is_card) / Window )
WPO   = delta * (1 - s)                   // s=1 grown → 0 offset; s=0 ungrown → sits at pivot
```
`Window ≈ 0.12` (tube) / use `LeafWindow ≈ 0.16` for cards if you want softer leaves;
`LeafLag ≈ 0.15` only applied to cards (`is_card=1`).

### Data the mesh must carry (baked by the new export — see the WPO FBX below)
Stored in **UV channels, U component only** (FBX flips UV **V** on import; keeping each scalar
in U makes it flip-proof). All in the same units as the imported geometry (see scale note):

| Channel | U holds | V |
|---|---|---|
| UV0 `UVMap` | leaf atlas U | leaf atlas V (normal texture UVs) |
| UV1 `wipe` | `gt_point` | 0 |
| UV2 `dx` | `delta.x` (cm) | 0 |
| UV3 `dy` | `delta.y` (cm) | 0 |
| UV4 `dz` | `delta.z` (cm) | 0 |
| UV5 `card` | `is_card` (0/1) | 0 | *(historical 6-UV variant only)*

`delta = pivot - vertex_pos`, pre-multiplied ×100 so it's in **centimetres** (matches the mesh
once imported at ×100 — see scale note). UE static meshes allow 8 UV sets. ✔

> **Shipped build = 5 UVs** (`UVMap, wipe, dx, dy, dz`). The `card` channel is a historical
> Level-2 variant kept for reference; without it, apply any leaf-lag uniformly in the material.

### The material graph (Level 1 reveal + this WPO)
```
gt_point  = TexCoord(1).R
is_card   = TexCoord(5).R
delta     = MakeFloat3( TexCoord(2).R, TexCoord(3).R, TexCoord(4).R )   // local-space cm

front_c   = GrowthFront - LeafLag * is_card          // cards trail by LeafLag
s         = smoothstep(0,1, (front_c - gt_point) / Window)   // UE: SmoothStep node
WPO_local = delta * (1 - s)
World Position Offset = TransformVector<Local→World>( WPO_local )   // applies component scale

// opacity (same as Level 1, but reuse front_c so leaves lag in opacity too)
reveal    = saturate( (front_c - gt_point) / SoftBand )
Opacity Mask = reveal            // * LeafTex.A on the leaf material
```
Nodes: `TransformVector` set **Local Space → World Space**; `SmoothStep` (Min 0, Max 1);
`GrowthFront`/`Window`/`LeafLag`/`SoftBand` as Scalar Parameters.

### Nanite + WPO settings (don't skip)
- Static mesh: **Nanite enabled**.
- Material: tick **"Used with Nanite"** is automatic, but you MUST enable **"Evaluate World
  Position Offset"** on the **mesh component** (it's off-by-default for Nanite WPO in some
  versions) and set a sensible **WPO Disable Distance** so far vines stop paying for WPO.
- Keep the leaf material **Masked**, never Translucent (translucent → whole mesh drops off
  Nanite). Masked + two-sided + WPO all coexist on Nanite (5.1+).
- `r.Nanite.AllowMaskedMaterials=1` (default on).

### Scale note (why delta is ×100)
The mesh is exported in metres but you import the FBX with **Offset Uniform Scale = 100**
(UE 5.5/5.6 Interchange) so it lands in centimetres, matching the ABC. FBX import scales
**geometry** but NOT UV-stored data, so `delta` is pre-scaled ×100 in Blender to already be in
cm. Result: geometry (cm) and delta (cm) agree, and `TransformVector(Local→World)` (component
scale 1) keeps the offset in cm = UE world units. If you instead import the FBX at scale 1,
the vine is 100× too small — use Offset Uniform Scale 100.

---

## The WPO FBX
Use `vine_<look>_growth_wpo.fbx` (produced by the skill's export step -- `scripts/grow_vine.py` -- separate from the
shipped `_static_wipe.fbx` so Level 1 stays untouched). It is the fully-grown mesh with the
UV channels above (5 in the shipped build). For Level 1 you can keep using `_static_wipe.fbx`; switch to the `_wpo` FBX
only when you wire up Level 2.

## Driving from TD (both levels identical)
`MID->SetScalarParameterValue("GrowthFront", phase01)` from OSC `/vine/<id>/phase 0..1`.
Grow/ungrow/scrub/loop are all just how you move that one number. Level 2 adds nothing to the
control surface — the WPO reads the same `GrowthFront`.
