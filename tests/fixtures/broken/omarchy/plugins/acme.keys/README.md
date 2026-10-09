# Keys

## Keyboard shortcut

Add this to `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + F", "Keys", "omarchy-shell shell toggle acme.keys")
```

Or, on an older setup:

```
bindd = SUPER SHIFT, K, Keys, exec, omarchy-shell shell toggle acme.keys
```
