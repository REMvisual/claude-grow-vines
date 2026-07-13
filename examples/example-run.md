# Example run - "dense flowering jasmine mat creeping from outside"

A real (procedural-fallback) run on a primitive sphere, trimmed for brevity.
This is what the skill prints and produces; nothing here is mocked.

## Command

```bash
PYTHONHASHSEED=0 "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" \
  --background --factory-startup \
  --python "$HOME/.claude/skills/grow-vines/scripts/grow_vine.py" -- \
  sphere "dense flowering jasmine mat creeping from outside" out/jasmine_mat JasmineMat
```

## Console (abridged)

```
[GROWVINE] recipe: {"growth_mode": "organic", "bark": "bark006",
  "leaf_species": ["Trachelospermum_jasminoides"], "budget": 22225,
  "n_attractors": 16000, "n_seeds": 24, "base_r": 0.0831, "branch_p": 0.22,
  "leaves_per_node": 2, "leaf_density": 0.875, "flower_prob": 0.25,
  "intent_mode": "organic_outside", "_autofit_scale": 1.732}
[HERO] JasmineMat SEED-OUTSIDE: n=24 min_dist=9.5cm (>= 8cm? True)
[VINE]   grow: nodes=22225 iters=50 attractors_left=3873/16000
[HERO] JasmineMat skeleton: 22225 nodes
[FOLIAGE] Baga DB not found -- generating procedural fallback leaf cards
[LEAF-FB] built 8 procedural fallback cards
[HERO] JasmineMat cards: 6 leaf from 1 species, 2 flower
[SKIN] smooth tube faces: 377876 (segs=4, res_u=4, V=arc*2.0)
[FOLIAGE] placed 20684 leaves, 5281 flowers (vine, 8 mats)
[HERO] JasmineMat BUILT: tris=2002070 nodes=22225 leaf_faces=623160
[FOLIAGE] materialized 8 textures -> out/jasmine_mat/tex
[GROWVINE] PASS uvs=['UVMap', 'wipe', 'dx', 'dy', 'dz'] wpo=103.2MB tex=11
GROWVINE_RESULT: PASS name=JasmineMat mode=organic_outside
```

With the BagaIvy addon installed, the `[FOLIAGE]` lines instead load photoscanned
jasmine cards from the library - same pipeline, richer leaves.

## Independent verify

```
INDEP_VERIFY: PASS | uv_count=5 uvs=['UVMap', 'wipe', 'dx', 'dy', 'dz'] |
  wipe=(0.0, 1.0) dx=(-19.41, 19.5) dy=(-19.42, 19.47) dz=(-19.51, 19.18)
```

The dx/dy/dz ranges are real unfurl deltas in tens of centimetres - the leaves
physically scale in from their stems when GrowthFront sweeps 0 to 1.

## Output folder

```
out/jasmine_mat/
  JasmineMat_wpo.fbx        # 5-UV static mesh (import at Offset Uniform Scale 100)
  wpo_compliance.json       # the verify record (see example-wpo_compliance.json)
  README.md                 # per-run deploy summary
  tex/
    bark_color.jpg  bark_normal.jpg  bark_roughness.jpg
    fb_trachelospermum_jasminoides_leaf_001_card.png   # RGBA cutout cards
    ...
```
