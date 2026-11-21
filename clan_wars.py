"""Apply the Phoenix Rising title to older bundled Direct clients."""
from pathlib import Path
import tkinter as tk


TITLE = 'Tribes 3 Mod Community Edition: Phoenix Rising'


def launch(root, *, on_ready):
    import desktop_launcher
    from direct_client import main

    if getattr(desktop_launcher, 'APP_TITLE', None) == TITLE:
        return main(root, on_ready=on_ready)

    base_desktop = desktop_launcher.Desktop

    class ClanWarsDesktop(base_desktop):
        def __init__(self, window, *args, **kwargs):
            super().__init__(window, *args, **kwargs)
            window.title(TITLE)
            icon = tk.PhotoImage(master=window, file=str(Path(root)/'branding/clan-wars.png'))
            window.iconphoto(True, icon)
            self.clan_wars_icon = icon
            for label in self.sidebar.winfo_children():
                if not isinstance(label, tk.Label):
                    continue
                if label.cget('text') in ('TRIBES 3', 'Clan Wars'):
                    label.configure(text='Phoenix Rising', image='',
                                    font=('Segoe UI', 18, 'bold'))
                elif label.cget('text') in ('COMMUNITY STARTER', 'TRIBES RIVALS  \u00b7  COMMUNITY MOD'):
                    label.configure(text='Tribes 3 Mod Community Edition', wraplength=165, justify='left')

    desktop_launcher.Desktop = ClanWarsDesktop
    try:
        main(root, on_ready=on_ready)
    finally:
        desktop_launcher.Desktop = base_desktop
