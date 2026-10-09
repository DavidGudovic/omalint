o.bind("SUPER + SPACE", "Omarchy menu", "omarchy-menu toggle")
o.bind("SUPER + CTRL + E", "Emojis", "omarchy-shell shell toggle omarchy.emojis")
o.bind("F9", "Start dictation", "voxtype record start")
o.bind("F9", "Stop dictation", "voxtype record stop", { release = true })

-- Only bound when the tool exists, which it never does.
if o.cmd_present("omadoctor-fixture-missing-tool") then
  o.bind("SUPER + V", "Fixture tool", "omadoctor-fixture-missing-tool")
end

-- Bound while a selection is on screen, not at startup.
hl.on("layer.opened", function(layer)
  hl.bind("RETURN", hl.dsp.exec_cmd("omarchy-capture-region --take-window"), { description = "Capture window" })
end)
