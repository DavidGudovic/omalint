o.bind("SUPER + W", "Close window", hl.dsp.window.close())
o.bind("SUPER + F", "Full screen", hl.dsp.window.fullscreen({ mode = "fullscreen" }))
o.bind("SUPER + X", "Pop window out", "omarchy-hyprland-window-pop")

-- Omarchy binds two actions to one key on purpose here.
o.bind("ALT + TAB", "Focus on next window", hl.dsp.window.cycle_next())
o.bind("ALT + TAB", "Reveal active window on top", hl.dsp.window.bring_to_top())

for workspace = 1, 3 do
  o.bind("SUPER + code:" .. tostring(workspace + 9), "Switch to workspace " .. workspace, hl.dsp.focus({ workspace = tostring(workspace) }))
end
