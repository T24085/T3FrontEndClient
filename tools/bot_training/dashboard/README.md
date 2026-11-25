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
