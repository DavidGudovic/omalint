-- o.bind("SUPER + F", "Commented out", "true")

-- Replace a default the right way: unbind, then bind.
hl.unbind("SUPER + X")
o.bind("SUPER + X", "Terminal", "alacritty")

o.bind("SUPER + N", "Notes", "omarchy-shell shell toggle acme.notes")
o.bind("SUPER + ALT + C", "Clock Plus", "omarchy-shell shell toggle acme.clock-plus")
o.bind("SUPER + B", "Browser", { launch = "chromium" })

-- The stock config only binds this when a tool exists that never does.
o.bind("SUPER + V", "Paste history", "true")
