"""The checks, in the order the report shows them."""

from . import bar, deps, health, keys, manifests, stale

CHECKS = {
    "manifests": manifests,
    "bar": bar,
    "keys": keys,
    "deps": deps,
    "stale": stale,
    "health": health,
}
