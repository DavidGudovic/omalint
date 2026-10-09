-- Stand-in for Omarchy's default Hyprland setup.
require("default.hypr.helpers")

if _G.omarchy_default_bindings ~= false then
  require("default.hypr.bindings.tiling")
  require("default.hypr.bindings.utilities")
end
