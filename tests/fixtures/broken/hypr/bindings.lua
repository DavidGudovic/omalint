-- Rebinding a default without unbinding it first: both actions run.
o.bind("SUPER + F", "File manager", { launch = "nautilus" })

-- The same key twice in this file.
o.bind("SUPER + G", "Git client", "lazygit")
o.bind("super+g", "Games", "steam")

-- Done properly: no conflict.
hl.unbind("SUPER + X")
o.bind("SUPER + X", "Terminal", "alacritty")

-- Press and release on one key are two different bindings.
o.bind("SUPER + H", "Hold start", "true")
o.bind("SUPER + H", "Hold stop", "true", { release = true })

-- Plugins that are gone or switched off.
o.bind("SUPER + Z", "Vanished", "omarchy-shell shell toggle acme.gone")
o.bind("SUPER + Y", "Disabled", "omarchy-shell shell summon acme.disabled '{}'")
o.bind("SUPER + U", "Good", "omarchy-shell shell toggle acme.good")
