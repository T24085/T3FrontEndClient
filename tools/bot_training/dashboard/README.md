# Bot training dashboard source

The Python service and the React content in this directory are the project
source for the native bot training dashboard. Build the React content in the
Data App dashboard project used for this installation. Copy the JSX, CSS, JS,
and MJS dashboard modules from here into its src/content/dashboard directory,
and install theme.css as the project's src/theme.css. The reusable Data App
shell provides the public component API at src/data-app-public.jsx.

The compiled dashboard is an input to serve_dashboard.py. See that program's
--help for the output directory and training configuration arguments. Keep
local settings, training runs, trained weights, terrain PNGs, and the
dashboard data snapshot outside source control.
Use **3D chase** beside **Top down** in the route tracker. The same playback
clock controls both views. The chase camera follows one selected bot and
shows its recorded speed and world elevation. Height above terrain is an
estimate available only within the measured relief grid. The map builders
include that grid when verified terrain is available. Older overview files
still work with a flat overlay.
