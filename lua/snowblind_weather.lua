-- Compatibility entry point for older launcher templates.
local source = debug.getinfo(1, 'S').source
local folder = assert(source:match('^@(.*[/\\])'), 'weather_module_path_required')
return assert(loadfile(folder .. 'weather.lua'))()
