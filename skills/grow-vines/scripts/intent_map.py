"""intent_map.py -- turn a natural-language brief into a vine growth recipe.

The brief drives the *contextual* control the user asked for:
  "a dense mat creeping in from OUTSIDE the mesh"   -> organic, perimeter seeds
  "sprouting from the surface / from inside"        -> organic, on-surface scatter seeds
  "bold climbers rising from the base"              -> climb
  "a spiral vortex winding into the front"          -> vortex

Returns a recipe dict with every key plantgen/hero.build_variant reads. Growth params are
BASE values for a ~6 m target; grow_vine.autofit() rescales them to the real mesh bbox.

Pure stdlib (runs both inside Blender's Python and plain python). Deterministic.
"""
import re

# ---- base recipe per growth mode (mirrors the 3 proven hero looks) -------------
BASE = {
    "organic_outside": dict(
        growth_mode="organic", bark="bark006",
        leaf_species=["Hedera_helix", "Trachelospermum_jasminoides", "Ficus_pumila"],
        budget=6500, n_attractors=5500, n_seeds=24, scatter_seeds=0,
        base_r=0.048, branch_p=0.22,
        leaves_per_node=2, leaf_density=0.70, leaf_target=0.10, leaf_scale_mul=1.0,
        flower_prob=0.10, growth_dz=0.045),
    "organic_inside": dict(   # seeds sit ON the surface -> sprouts out of the mesh
        growth_mode="organic", bark="bark006", inside_only=True,
        leaf_species=["Hedera_helix", "Ficus_pumila"],
        budget=6000, n_attractors=5200, n_seeds=4, scatter_seeds=22,
        base_r=0.045, branch_p=0.20,
        leaves_per_node=2, leaf_density=0.68, leaf_target=0.10, leaf_scale_mul=1.0,
        flower_prob=0.08, growth_dz=0.045),
    "climb": dict(
        growth_mode="climb", bark="bark012",
        leaf_species=["Hedera_colchica", "Hedera_algeriensis"],
        budget=4800, n_attractors=2900, n_seeds=10,
        base_r=0.075, branch_p=0.14, climb_wup=0.33, climb_starve=30,
        leaves_per_node=1, leaf_density=0.5, leaf_target=0.14, leaf_scale_mul=1.2,
        flower_prob=0.05, growth_dz=0.060),
    "vortex": dict(
        growth_mode="vortex", bark="bark002",
        leaf_species=["Ficus_pumila", "Muehlenbeckia_complexa", "Hedera_helix"],
        spiral_arms=2, spiral_turns=2.8, spiral_band=0.12,
        budget=13000, n_attractors=7500, n_seeds=2,
        base_r=0.032, branch_p=0.05,
        leaves_per_node=3, leaf_density=1.0, leaf_target=0.072, leaf_scale_mul=0.9,
        flower_prob=0.05, growth_dz=0.038),
}

# ---- species keyword -> Baga genera ---------------------------------------------
SPECIES = {
    r"grape|vitis|vine fruit": ["Vitis_vinifera"],
    r"ivy|hedera": ["Hedera_helix", "Hedera_colchica"],
    r"jasmine|trachelo": ["Trachelospermum_jasminoides"],
    r"fig|ficus|creeping fig": ["Ficus_pumila"],
    r"wire|muehlen|fine|small.?leaf": ["Ficus_pumila"],  # Muehlenbeckia has no loadable cards
    r"clematis": ["Clematis"],
    r"wisteria": ["Wisteria_sinensis"],
    r"honeysuckle|lonicera": ["Lonicera"],
    r"hops|humulus": ["Humulus_lupulus"],
    r"rose|rosa": ["Rosa"],
    r"bougain": ["Bougainvillea"],
}


def _mode(b):
    if re.search(r"vortex|spiral|swirl|wind(ing)?|coil|whirl|into (the|a) (eye|centre|center|point)", b):
        return "vortex"
    if re.search(r"climb|vertical|rising|rise|up the|from the (base|bottom|ground|floor)|columns?", b):
        return "climb"
    if re.search(r"from inside|from the surface|sprout|emerg|out of the (mesh|surface)|erupt", b):
        return "organic_inside"
    return "organic_outside"   # default: creeping mat from outside


def parse(brief, name="vine"):
    """brief: free text. -> recipe dict (BASE params; autofit rescales later)."""
    b = (brief or "").lower()
    key = _mode(b)
    r = dict(BASE[key])
    r["name"] = name
    r["intent_mode"] = key
    r["brief"] = brief

    # leaf species override from brief
    picked = []
    for pat, sp in SPECIES.items():
        if re.search(pat, b):
            picked += sp
    if picked:
        r["leaf_species"] = list(dict.fromkeys(picked))   # de-dup, keep order

    # density: sparse <-> dense/lush
    if re.search(r"sparse|minimal|few|light", b):
        r["budget"] = int(r["budget"] * 0.6); r["n_attractors"] = int(r["n_attractors"] * 0.6)
        r["leaf_density"] = round(r["leaf_density"] * 0.7, 3)
    elif re.search(r"dense|lush|thick mat|overgrown|heavy|full", b):
        r["budget"] = int(r["budget"] * 1.5); r["n_attractors"] = int(r["n_attractors"] * 1.4)
        r["leaf_density"] = round(min(1.0, r["leaf_density"] * 1.25), 3)

    # stem thickness: fine/wire <-> bold/thick
    if re.search(r"fine|wire|thin|delicate", b):
        r["base_r"] = round(r["base_r"] * 0.6, 4)
    elif re.search(r"bold|thick|chunky|heavy stem|statement", b):
        r["base_r"] = round(r["base_r"] * 1.6, 4)

    # flowers
    if re.search(r"flower|bloom|blossom", b):
        r["flower_prob"] = max(r["flower_prob"], 0.25)
    elif re.search(r"no flower|foliage only|leaves only", b):
        r["flower_prob"] = 0.0

    return r
