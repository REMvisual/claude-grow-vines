# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Collection-driven `SoftBand` / `GrowWindow` / `WPOScale`; real Call-In-Editor buttons; a UMG panel.

## [1.1.0] - 2026-09-28

### Added
- `BP_VineController` (UE 5.8): drop-in actor that auto-plays growth (once / loop / ping-pong,
  live Duration and Speed), switches between full-stage vines by index (`SetVine`, `NextVine`,
  `PrevVine`), or grows random clusters of 2-4 smaller vines that re-roll at every cycle
  boundary; `ResetNow` / `NewRandomSet` / `ShowAll` / `MaterialOverride`; previews in the editor
  without Play. Rebuildable from source with `scripts/unreal/ue_bp_vinecontroller.py`.
- `MPC_Vines` Material Parameter Collection; both masters now compute
  `GrowthFront = instance parameter x collection parameter`, so one write animates every vine.
- Tiny default textures (`T_VineDefault_*`) so the masters compile stand-alone.
- Scripted Unreal ingest over Epic's ModelContextProtocol plugin (`scripts/unreal/`):
  `ue_import_live.py` (mesh + Nanite + textures + one material instance per slot, with a
  token-scoring slot-to-texture resolver and local RGBA packing), `ue_place.py` (batch placement
  + controller into the open level), `ue_verify.py` (headless read-only 5-UV check), `uemcp.py`.
- `reference/UE_VINE_CONTROLLER.md` (controller design, density split rule, repeatable process)
  and `reference/LESSONS.md` (lessons from a 20-vine stage deployment).
- SKILL.md now describes the two-phase pipeline (grow, then "open Unreal" and ingest).

### Changed
- Unreal content is authored in UE 5.8 (was 5.7) and ships as `unreal/Content/VineWPO/` +
  `unreal/Content/PFG/`, to be copied at exactly those paths.
- `unreal/IMPORT.md` rewritten around the scripted path and the controller cheat-sheet.
- BagaIvy audit helpers read the addon location from `BAGAIVY_DIR` / `BAGAIVY_DB`.

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
