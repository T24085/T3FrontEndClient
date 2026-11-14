"""Apply Clan Wars branding around the signed Direct Starter."""
from pathlib import Path
import tkinter as tk


TITLE = 'Tribes Rivals: Clan Wars (community mod)'


def launch(root, *, on_ready):
    import desktop_launcher
    from direct_client import main

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
                if label.cget('text') == 'TRIBES 3':
                    self.clan_wars_logo = icon.subsample(8)
                    label.configure(text='Clan Wars', image=self.clan_wars_logo, compound='left',
                                    font=('Segoe UI', 18, 'bold'))
                elif label.cget('text') == 'COMMUNITY STARTER':
                    label.configure(text='TRIBES RIVALS  \u00b7  COMMUNITY MOD')

    desktop_launcher.Desktop = ClanWarsDesktop
    try:
        main(root, on_ready=on_ready)
    finally:
        desktop_launcher.Desktop = base_desktop
