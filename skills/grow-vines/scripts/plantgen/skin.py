"""skin.py -- SMOOTH curve-bevel-style tube skinner for vines AND trees.

Replaces the old hex/parallel-transport TUBE skinner (which looked "steppy":
faceted cross-sections + per-segment kinks) with the approved SMOOTH skin, the
same idea as rnd/trees/improved_tree.py's curve-bevel:

  - Decompose the unified flat node list into root->tip STRANDS (follow the
    thickest child; each sibling starts a new strand that INCLUDES the parent
    node so it stays connected).
  - Per strand, build a SMOOTH centerline by Catmull-Rom interpolation through
    the strand nodes (resolution_u sub-steps per node span) with smoothly
    interpolated radius / growth(gt) / arc-length. This removes segment kinks.
  - Skin that centerline as a round tube: a parallel-transported ring of
    2*(bevel_resolution+1) segments (no twist, round cross-section). This
    removes the hex faceting.
  - resolution_u=4, bevel_resolution=3 -> ~8-seg rings, real-time tri budget.

Still writes faces into the passed bmesh `bm` with the SAME layers as before so
nothing downstream changes:
  - UV0 (uv_layer): U around the ring, V along WORLD ARC-LENGTH (fixes bark
    V-tiling smear on long vine runs -- V is meters*tile, not normalized 0..1).
  - per-face float "gt_face" (gt_face_layer) = segment root-end gt (tip reveal).
  - optional per-corner color (col_layer): R=G=B=gt for sanity renders.
  - optional per-vert vlayers is_card(=0)/gt_point/pivot for the growth reveal
    (each ring's pivot sits one sub-step rootward so the tube slides out smoothly
    as the growth front passes -- same blunt-cylinder reveal as before).

Public function name + signature + return type are UNCHANGED:
  skin(bm, skel, uv_layer, gt_face_layer, col_layer=None, mat_index=0,
       taper=0.0, vlayers=None) -> int (# faces).
"""
import math
import bmesh
from mathutils import Vector

# --- real-time skin resolution (curve-bevel equivalents) ---
RESOLUTION_U = 4        # smooth sub-steps per node span on THICK stems (curve resolution_u)
BEVEL_RESOLUTION = 3    # round cross-section on THICK stems -> 2*(bevel_res+1) = 8 segs
V_TILE = 2.0            # bark V repeats per world meter along the stem (anti-smear)


def fin(v):
    return all(math.isfinite(c) for c in v)


def _ring_segs_max():
    # curve bevel: a full bevel circle has 4*(bevel_resolution+1) verts; we use a
    # cheaper-but-still-round 2*(bevel_resolution+1) so a thick stem stays real-time.
    return max(6, 2 * (BEVEL_RESOLUTION + 1))


def _segs_for(r, segs_max):
    """Radius-adaptive cross-section count: prominent thick stems get the full round
    `segs_max` (8); thinner stems drop to 6, and the many sub-visible thin tendrils
    drop to 4 to keep a dense vine real-time. Still round enough that no facets read
    at viewing distance (thin tendrils are pixels-wide on screen)."""
    if r > 0.045:  return segs_max          # trunks / main stems: full round (8)
    if r > 0.020:  return max(6, segs_max - 2)   # mid stems: 6
    return 4                                  # thin tendrils (the bulk): 4


def _res_for(r):
    """Radius-adaptive smoothness along length: thick stems get full RESOLUTION_U
    sub-steps (kill kinks where it shows); thin near-straight tendrils need almost
    none (a tendril spans 1-2 nodes and reads straight)."""
    if r > 0.045:  return RESOLUTION_U        # 4
    if r > 0.020:  return max(2, RESOLUTION_U - 1)   # 3
    return 1                                   # thin tendrils: node-to-node straight


def _catmull(p0, p1, p2, p3, t):
    """Centripetal-ish Catmull-Rom point at t in [0,1] between p1 and p2."""
    t2 = t * t
    t3 = t2 * t
    return (p1 * 2.0
            + (p2 - p0) * t
            + (p0 * 2.0 - p1 * 5.0 + p2 * 4.0 - p3) * t2
            + (p3 - p0 + (p1 - p2) * 3.0) * t3) * 0.5


def _smooth_centerline(pts, rads, gts, taper):
    """Catmull-Rom interpolate a strand (list of node pos/radius/gt) into a dense
    smooth polyline. Returns lists: positions, radii, gts, cumulative arc-length."""
    n = len(pts)
    if n < 2:
        return list(pts), list(rads), list(gts), [0.0] * n
    op, orr, og = [], [], []
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i] + (pts[i] - pts[i + 1])
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1] + (pts[i + 1] - pts[i])
        # per-span sub-steps from the thicker endpoint (thick stems smooth, thin cheap)
        steps = max(1, _res_for(max(rads[i], rads[i + 1])))
        last = (i == n - 2)
        sub = steps + 1 if last else steps      # include the final endpoint once
        for s in range(sub):
            t = s / steps
            pos = _catmull(p0, p1, p2, p3, t)
            if not fin(pos):
                pos = p1.lerp(p2, t)
            rr = rads[i] * (1.0 - t) + rads[i + 1] * t
            gg = gts[i] * (1.0 - t) + gts[i + 1] * t
            rr = max(0.004, rr * (1.0 - taper * gg))
            op.append(pos)
            orr.append(rr)
            og.append(gg)
    # cumulative WORLD arc-length (meters) for non-stretching bark V
    arc = [0.0]
    for k in range(1, len(op)):
        d = (op[k] - op[k - 1]).length
        arc.append(arc[-1] + (d if math.isfinite(d) else 0.0))
    return op, orr, og, arc


def _ring(P, t, ref, r, segs):
    """A round ring of `segs` verts at P, perpendicular to tangent t, using a
    parallel-transported reference normal `ref` (no twist along the strand)."""
    t = t.normalized() if t.length > 1e-6 else Vector((0, 0, 1))
    n = ref - ref.dot(t) * t
    n = n.normalized() if n.length > 1e-4 else t.orthogonal().normalized()
    b = t.cross(n).normalized()
    cos = []
    for s in range(segs):
        a = (s / segs) * math.tau
        v = P + (math.cos(a) * n + math.sin(a) * b) * r
        cos.append(v if fin(v) else P.copy())
    return cos, n


def _strands(skel):
    """Decompose the flat node list into root->tip strands: follow the thickest
    child; each sibling starts its OWN strand that INCLUDES the parent index so it
    stays connected (mirrors improved_tree.strands_from_tree)."""
    children = {}
    for i, nd in enumerate(skel):
        p = nd['parent']
        if p >= 0:
            children.setdefault(p, []).append(i)
    roots = [i for i, nd in enumerate(skel) if nd['parent'] < 0]
    chains = []
    # pending = (parent_idx_or_None, start_idx)
    pending = [(None, r) for r in roots]
    while pending:
        par, node = pending.pop()
        chain = [par, node] if par is not None else [node]
        cur = node
        while children.get(cur):
            cs = sorted(children[cur], key=lambda c: -skel[c]['r'])
            for sib in cs[1:]:
                pending.append((cur, sib))
            cur = cs[0]
            chain.append(cur)
        if len(chain) >= 2:
            chains.append(chain)
    return chains


def skin(bm, skel, uv_layer, gt_face_layer, col_layer=None, mat_index=0,
         taper=0.0, vlayers=None):
    """Skin `skel` (unified flat node list) into SMOOTH welded tubes inside `bm`.

    taper>0 shrinks radius toward the tip by `taper` at gt=1 (vines taper tips).
    vlayers (optional) = dict of bmesh vert layers is_card/gt_point/pivot so the
    growth-anim reveal can slide tube segments in. Returns the face count.
    """
    segs_max = _ring_segs_max()
    faces = 0
    new_verts = []          # only the stem verts we create (for a targeted weld)

    for chain in _strands(skel):
        pts = [skel[i]['p'] for i in chain]
        rads = [max(0.004, skel[i]['r']) for i in chain]
        gts = [skel[i]['gt'] for i in chain]
        cl_p, cl_r, cl_g, cl_arc = _smooth_centerline(pts, rads, gts, taper)
        if len(cl_p) < 2:
            continue

        # ONE cross-section count per strand (from its thickest point) -> uniform tube,
        # clean bridging, radius-adaptive tri budget (thin tendrils get fewer segs).
        segs = _segs_for(max(cl_r), segs_max)

        # build rings with one continuous parallel-transported reference normal
        rings = []          # list of (list[BMVert], center, tangent, gt, arc)
        ref = None
        for k in range(len(cl_p)):
            if k == 0:
                t = cl_p[1] - cl_p[0]
            elif k == len(cl_p) - 1:
                t = cl_p[k] - cl_p[k - 1]
            else:
                t = cl_p[k + 1] - cl_p[k - 1]
            if t.length <= 1e-6 or not fin(t):
                t = Vector((0, 0, 1))
            t = t.normalized()
            if ref is None:
                ref = t.orthogonal().normalized()
            cos, ref = _ring(cl_p[k], t, ref, cl_r[k], segs)
            vs = [bm.verts.new(c) for c in cos]
            new_verts.extend(vs)
            rings.append((vs, cl_p[k], t, cl_g[k], cl_arc[k]))

        # per-vert reveal layers: pivot slides each ring back onto the PREVIOUS
        # ring (full radius) so a segment extends as a blunt cylinder, not a point.
        if vlayers is not None:
            for k, (vs, ctr, t, gp, arc) in enumerate(rings):
                if k > 0:
                    seg = ctr - rings[k - 1][1]
                else:
                    seg = Vector((0, 0, 0))
                for v in vs:
                    v[vlayers['gt_point']] = gp
                    v[vlayers['is_card']] = 0.0
                    v[vlayers['pivot']] = (v.co.x - seg.x,
                                           v.co.y - seg.y,
                                           v.co.z - seg.z)

        # bridge consecutive rings into a smooth tube
        for k in range(len(rings) - 1):
            va, _ca, _ta, ga, arc_a = rings[k]
            vb, _cb, _tb, gb, arc_b = rings[k + 1]
            gtf = min(ga, gb)                       # segment root-end gt
            va_v = arc_a * V_TILE                    # world-arc-length V (no smear)
            vb_v = arc_b * V_TILE
            for s in range(segs):
                s2 = (s + 1) % segs
                a0, a1 = va[s], va[s2]
                b1, b0 = vb[s2], vb[s]
                try:
                    f = bm.faces.new((a0, a1, b1, b0))
                except ValueError:
                    continue
                f.material_index = mat_index
                f.smooth = True
                f[gt_face_layer] = gtf
                uvs = [(s / segs, va_v), ((s + 1) / segs, va_v),
                       ((s + 1) / segs, vb_v), (s / segs, vb_v)]
                gts_corner = [ga, ga, gb, gb]
                for ci, lp in enumerate(f.loops):
                    lp[uv_layer].uv = uvs[ci]
                    if col_layer is not None:
                        g = gts_corner[ci]
                        lp[col_layer] = (g, g, g, 1.0)
                faces += 1

    # weld coincident junction rings so sibling strands connect to their parent
    # strand -> ONE connected stem mesh (clean Dijkstra wipe + clean ABC). Only the
    # stem verts are touched; foliage cards are added later by a separate pass.
    if new_verts:
        try:
            bmesh.ops.remove_doubles(bm, verts=new_verts, dist=5e-4)
        except Exception as e:
            print("[SKIN] weld skipped:", repr(e), flush=True)

    print(f"[SKIN] smooth tube faces: {faces} "
          f"(segs={segs}, res_u={RESOLUTION_U}, V=arc*{V_TILE})", flush=True)
    return faces
