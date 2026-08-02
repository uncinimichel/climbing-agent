"""How climbing trades off weather, travel and venue fit.

A leaf module with no imports so the scorer, the renderer and the sport object
can all read the same three numbers without importing each other. The dashboard
prints these percentages in its methodology copy, so a change here changes both
the maths and the explanation — which is the point.

Weather leads the destination choice; travel is a tiebreak, not a proximity
bonus that lets a nearby-but-poor venue out-rank a far-but-excellent one.
"""
W_WEATHER, W_TRAVEL, W_FIT = 65, 15, 20

COMPOSITE = {"weather": W_WEATHER, "travel": W_TRAVEL, "fit": W_FIT}
