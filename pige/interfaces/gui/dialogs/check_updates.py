"""Dialogue : vérifier les mises à jour GitHub et lancer pip install."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, scrolledtext, ttk

from pige.utils.updates import UpdateCheckResult, check_for_updates, get_installed_version, pip_upgrade_spec

logger = logging.getLogger(__name__)


def show_check_updates_dialog(parent: tk.Tk) -> None:
    """Ouvre le dialogue de vérification / installation des mises à jour."""
    win = tk.Toplevel(parent)
    win.title("Mises à jour PIGE")
    win.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)
    win.resizable(True, True)
    win.minsize(420, 320)
    win.columnconfigure(0, weight=1)
    win.rowconfigure(1, weight=1)

    header = ttk.Label(
        win,
        text="Vérification des releases sur GitHub…",
        font=("TkDefaultFont", 10),
        wraplength=520,
    )
    header.grid(row=0, column=0, sticky=tk.W, padx=12, pady=(12, 6))

    notes = scrolledtext.ScrolledText(win, height=12, wrap=tk.WORD, font=("TkDefaultFont", 9), state=tk.DISABLED)
    notes.grid(row=1, column=0, sticky=tk.NSEW, padx=12, pady=6)

    btn_frame = ttk.Frame(win)
    btn_frame.grid(row=2, column=0, sticky=tk.EW, padx=12, pady=(6, 12))

    btn_install = ttk.Button(btn_frame, text="Mettre à jour (pip)", state=tk.DISABLED)
    btn_install.pack(side=tk.LEFT, padx=(0, 8))

    btn_browser = ttk.Button(btn_frame, text="Ouvrir sur GitHub", state=tk.DISABLED)
    btn_browser.pack(side=tk.LEFT, padx=(0, 8))

    btn_retry = ttk.Button(btn_frame, text="Vérifier à nouveau")
    btn_retry.pack(side=tk.LEFT, padx=(0, 8))

    btn_close = ttk.Button(btn_frame, text="Fermer", command=win.destroy)
    btn_close.pack(side=tk.RIGHT)

    state: dict = {"result": None, "tag_for_pip": None}

    def set_notes(text: str) -> None:
        notes.config(state=tk.NORMAL)
        notes.delete("1.0", tk.END)
        notes.insert("1.0", text)
        notes.config(state=tk.DISABLED)

    def apply_result(r: UpdateCheckResult) -> None:
        state["result"] = r
        state["tag_for_pip"] = None
        btn_install.config(state=tk.DISABLED)
        btn_browser.config(state=tk.DISABLED)

        if r.error:
            header.config(text="Impossible de vérifier les mises à jour")
            set_notes(r.error)
            return

        assert r.latest_version is not None
        tag = f"v{r.latest_version}" if not r.latest_version.startswith("v") else r.latest_version
        state["tag_for_pip"] = tag

        lines = [
            f"Version installée : {r.current_version}",
            f"Dernière release GitHub : {r.latest_version}",
            "",
        ]
        if r.release_title:
            lines.append(f"Titre : {r.release_title}")
            lines.append("")
        if r.update_available:
            header.config(text="Une mise à jour est disponible")
            lines.append("Vous pouvez mettre à jour avec pip (environnement Python actuel) ou ouvrir la page de la release.")
            btn_install.config(state=tk.NORMAL)
            if r.release_url:
                btn_browser.config(state=tk.NORMAL)
        elif r.up_to_date:
            header.config(text="Vous êtes à jour")
            lines.append("Aucune release plus récente que votre installation.")
            if r.release_url:
                btn_browser.config(state=tk.NORMAL)
        else:
            header.config(text="Version locale plus récente")
            lines.append("Votre installation semble plus récente que la dernière release GitHub (développement local ?).")
            if r.release_url:
                btn_browser.config(state=tk.NORMAL)

        if r.release_notes:
            lines.extend(["", "--- Notes de version ---", "", r.release_notes])

        set_notes("\n".join(lines))

    def run_check() -> None:
        parent.after(0, lambda: header.config(text="Contact de GitHub…"))
        parent.after(0, lambda: set_notes("Veuillez patienter."))

        def worker() -> None:
            try:
                r = check_for_updates()
            except Exception as e:
                logger.exception("check_for_updates")
                r = UpdateCheckResult(current_version=get_installed_version(), error=str(e))
            parent.after(0, lambda res=r: apply_result(res))

        threading.Thread(target=worker, daemon=True).start()

    def on_install() -> None:
        tag = state.get("tag_for_pip")
        r = state.get("result")
        if not tag or not r or not r.update_available:
            return
        spec = pip_upgrade_spec(tag)
        msg = (
            f"PIGE va être mis à jour avec pip dans l’interpréteur actuel :\n\n"
            f"  {sys.executable}\n\n"
            f"Commande :\n  python -m pip install --upgrade \"{spec}\"\n\n"
            "Fermez PIGE après la mise à jour puis relancez l’application.\n"
            "Continuer ?"
        )
        if not messagebox.askyesno("Confirmer la mise à jour", msg, parent=win):
            return
        header.config(text="Mise à jour en cours…")
        set_notes("Exécution de pip…")

        def pip_worker() -> None:
            try:
                _no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                proc = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", spec],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    creationflags=_no_window if sys.platform == "win32" else 0,
                )
                out = (proc.stdout or "") + "\n" + (proc.stderr or "")
                code = proc.returncode
            except subprocess.TimeoutExpired:
                out = "Délai dépassé (10 min)."
                code = -1
            except Exception as e:
                out = str(e)
                code = -1

            def done() -> None:
                if code == 0:
                    header.config(text="Mise à jour terminée")
                    messagebox.showinfo(
                        "Mise à jour",
                        "Installation terminée. Fermez PIGE et relancez-le pour utiliser la nouvelle version.",
                        parent=win,
                    )
                else:
                    header.config(text="Échec de la mise à jour")
                    messagebox.showerror(
                        "pip",
                        "La commande pip a échoué. Détails dans la zone de texte.",
                        parent=win,
                    )
                set_notes(out.strip() or "(aucune sortie)")

            parent.after(0, done)

        threading.Thread(target=pip_worker, daemon=True).start()

    def on_browser() -> None:
        r = state.get("result")
        url = r.release_url if r else None
        if url:
            webbrowser.open(url)

    btn_install.config(command=on_install)
    btn_browser.config(command=on_browser)
    btn_retry.config(command=run_check)

    run_check()
