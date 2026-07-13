"""plantgen -- unified headless plant generator.

Consolidates four render-verified R&D building blocks into one batchable
generator that produces, per plant variation:
  (A) a real-geometry growth-animation Alembic  (Mode A: GN reveal -> .abc)
  (B) a static mesh + 2nd-UV "wipe"             (Mode B: .fbx + .abc)
with leaf/flower cards for photoreal foliage (BagaIvy library if installed,
procedural fallback cards otherwise).

Modules:
  skeleton.py       -- common node schema + vine/tree skeleton adapters
  skin.py           -- one parallel-transport tube skinner for both
  foliage.py        -- leaf/flower card instancing + texture/material export fixes
  leaf_fallback.py  -- procedural leaf cards when the BagaIvy library is absent
  hero.py           -- the build_variant engine (skeleton -> skin -> foliage -> mesh)
  rnd/              -- vendored proven skeleton generators (vine_scol, tree_gen_sc)

Unified node schema (flat list, parent index < child index, root parent == -1):
  {'p': Vector, 't': Vector(dir), 'n': Vector|None(surface normal), 'r': float,
   'parent': int, 'gt': float(root->tip 0..1)}
"""
