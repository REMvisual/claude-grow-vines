# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Unreal vine-switcher controller Blueprint: a drop-in actor exposing
  Grow / Ungrow / Speed / Loop and per-vine switching over the GrowthFront
  scalar (UMG- and OSC-drivable), so multiple vines can be managed and
  cross-faded without material bookkeeping.

## [1.0.0] - 2026-07-13

### Added
- Initial public release
- Natural-language brief to vine recipe mapping (growth mode, density,
  stem thickness, species, flowers)
- Surface-constrained space-colonization growth over any OBJ/FBX/glTF mesh
  or primitive, auto-fitted to the target's bounding box
- 5-UV static FBX export (UVMap, wipe, dx, dy, dz) that reveals and unfurls
  from a single GrowthFront 0-1 scalar
- Baked bark + leaf PBR texture output per run
- Parameterized Unreal master materials (M_Vine_Leaf, M_Vine_Bark, UE 5.7)
- Reimport self-verification plus an independent verify script
- Procedural leaf-card fallback: works without the optional BagaIvy library
- One-time asset fetcher for the CC0 ambientCG bark sets
