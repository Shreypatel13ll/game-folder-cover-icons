"""Small Windows GUI for managing game-folder cover icons."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import auto_folder_icons as icons
import manager_core as core


APP_TITLE = "Game Folder Icons Manager"
APP_VERSION = "1.0.0"


class ManagerWindow:
    def __init__(self) -> None:
        import ttkbootstrap as ttk  # Scheduled scans never load the GUI theme.

        self.window = ttk.Window(themename="litera")
        self.window.title(APP_TITLE)
        self.window.geometry("940x680")
        self.window.minsize(840, 660)
        icon_path = (Path(sys.executable).parent / "app.ico" if getattr(sys, "frozen", False)
                     else Path(__file__).parent / "build" / "app.ico")
        if icon_path.is_file():
            self.window.iconbitmap(str(icon_path))
        style = ttk.Style()
        style.configure("Treeview", rowheight=29, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        self.roots = core.import_legacy_root_if_needed()
        self.busy = False
        self.task_state = "none"
        self.status_text = tk.StringVar(value="Ready")
        self.task_text = tk.StringVar(value="Checking automatic scans…")

        body = ttk.Frame(self.window, padding=20)
        body.pack(fill="both", expand=True)
        title = ttk.Label(body, text="Game Folder Icons", font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")
        ttk.Label(body, text="Watch game libraries and manage the cover icon on each game folder.",
                  foreground="#5C6F82").pack(anchor="w", pady=(2, 16))

        task_row = ttk.Frame(body)
        task_row.pack(fill="x", pady=(0, 10))
        ttk.Label(task_row, textvariable=self.task_text).pack(side="left", fill="x", expand=True)
        self.task_button = ttk.Button(task_row, text="Turn on automatic scans", command=self.toggle_task,
                                      bootstyle="primary")
        self.task_button.pack(side="right")

        libraries = ttk.Labelframe(body, text="Watched game libraries", padding=8)
        libraries.pack(fill="x", pady=(0, 12))
        games = ttk.Labelframe(body, text="Game folders in selected library", padding=8)
        games.pack(fill="both", expand=True)

        library_list = ttk.Frame(libraries)
        library_list.pack(fill="x")
        self.root_tree = ttk.Treeview(library_list, columns=("path", "state"), show="headings", height=2)
        self.root_tree.heading("path", text="Folder")
        self.root_tree.heading("state", text="Status")
        self.root_tree.column("path", minwidth=400, stretch=True)
        self.root_tree.column("state", width=120, stretch=False)
        self.root_tree.pack(side="left", fill="x", expand=True)
        root_scroll = ttk.Scrollbar(library_list, orient="vertical", command=self.root_tree.yview)
        root_scroll.pack(side="right", fill="y")
        self.root_tree.configure(yscrollcommand=root_scroll.set)
        self.root_tree.bind("<<TreeviewSelect>>", lambda _event: self.refresh_games())
        library_buttons = ttk.Frame(libraries)
        library_buttons.pack(fill="x", pady=(8, 0))
        for label, handler, style in (("Add library…", self.add_root, "primary"),
                                      ("Stop watching", self.remove_root, "secondary-outline"),
                                      ("Scan now", self.scan_root, "primary-outline"),
                                      ("Open folder", self.open_root, "secondary-outline")):
            ttk.Button(library_buttons, text=label, command=handler, bootstyle=style).pack(side="left", padx=(0, 7))

        game_list = ttk.Frame(games)
        game_list.pack(fill="both", expand=True)
        self.game_tree = ttk.Treeview(game_list, columns=("name", "state"), show="headings", height=5)
        self.game_tree.heading("name", text="Game folder")
        self.game_tree.heading("state", text="Icon status")
        self.game_tree.column("name", minwidth=350, stretch=True)
        self.game_tree.column("state", width=170, stretch=False)
        self.game_tree.pack(side="left", fill="both", expand=True)
        game_scroll = ttk.Scrollbar(game_list, orient="vertical", command=self.game_tree.yview)
        game_scroll.pack(side="right", fill="y")
        self.game_tree.configure(yscrollcommand=game_scroll.set)
        game_buttons = ttk.Frame(games)
        game_buttons.pack(fill="x", pady=(8, 0))
        for label, handler, style in (("Choose cover…", self.choose_cover, "primary"),
                                      ("Exclude / include", self.toggle_exclusion, "secondary-outline"),
                                      ("Restore managed icon", self.restore_icon, "secondary-outline"),
                                      ("Open game", self.open_game, "secondary-outline")):
            ttk.Button(game_buttons, text=label, command=handler, bootstyle=style).pack(side="left", padx=(0, 7))

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(footer, textvariable=self.status_text, foreground="#5C6F82").pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="View log", command=self.open_log, bootstyle="link").pack(side="right")
        ttk.Button(footer, text="Refresh", command=self.refresh, bootstyle="link").pack(side="right", padx=(0, 7))
        self.refresh()

    def run(self) -> None:
        self.window.mainloop()

    def selected_root(self) -> Path | None:
        selected = self.root_tree.selection()
        return Path(self.root_tree.item(selected[0], "values")[0]) if selected else None

    def selected_game(self) -> Path | None:
        selected = self.game_tree.selection()
        return Path(selected[0]) if selected else None

    def require_root(self) -> Path | None:
        root = self.selected_root()
        if root is None:
            messagebox.showinfo(APP_TITLE, "Select a watched library first.", parent=self.window)
        return root

    def require_game(self) -> Path | None:
        game = self.selected_game()
        if game is None:
            messagebox.showinfo(APP_TITLE, "Select a game folder first.", parent=self.window)
        return game

    def refresh(self) -> None:
        chosen = self.selected_root()
        self.roots = core.load_roots()
        for item in self.root_tree.get_children():
            self.root_tree.delete(item)
        for root in self.roots:
            state = "Available" if Path(root).is_dir() else "Missing"
            self.root_tree.insert("", "end", iid=root, values=(root, state))
        if chosen and str(chosen) in self.roots:
            self.root_tree.selection_set(str(chosen))
        elif self.roots:
            self.root_tree.selection_set(self.roots[0])
        try:
            status = core.task_status()
            self.task_state = status["state"]
            labels = {
                "current": "Automatic scans: on (every ten minutes)",
                "legacy": "Older automatic scanner is active; switch it to this manager to watch multiple libraries.",
                "none": "Automatic scans: off",
                "unrelated": "Another scheduled task uses this name; it will not be changed.",
            }
            self.task_text.set(labels.get(self.task_state, "Automatic scan status unknown"))
            self.task_button.configure(text={"current": "Turn off", "legacy": "Switch to manager", "none": "Turn on"}
                                       .get(self.task_state, "Unavailable"),
                                       state="disabled" if self.task_state == "unrelated" else "normal")
        except Exception as exc:
            self.task_text.set(f"Could not check automatic scans: {exc}")
            self.task_button.configure(state="disabled")
        self.refresh_games()

    def refresh_games(self) -> None:
        for item in self.game_tree.get_children():
            self.game_tree.delete(item)
        root = self.selected_root()
        if root is None or not root.is_dir():
            return
        state = icons.load_state().get("folders", {})
        try:
            folders = icons.direct_child_folders(root)
        except OSError as exc:
            self.status_text.set(f"Could not read {root}: {exc}")
            return
        for folder in folders:
            record = state.get(str(folder.resolve()).lower(), {})
            if (folder / ".no-folder-icon").exists():
                icon_state = "Excluded"
            else:
                has_icon, _, _ = icons.existing_icon(folder)
                if has_icon and record.get("status") == "managed":
                    icon_state = "Managed icon"
                elif has_icon:
                    icon_state = "Existing custom icon"
                elif record.get("status") == "retry":
                    icon_state = "Retry pending"
                else:
                    icon_state = "No icon yet"
            self.game_tree.insert("", "end", iid=str(folder), values=(folder.name, icon_state))
        self.status_text.set(f"{len(folders)} game folders in {root}")

    def add_root(self) -> None:
        chosen = filedialog.askdirectory(parent=self.window, title="Choose a folder containing game folders")
        if not chosen:
            return
        path = str(Path(chosen).resolve())
        if core.canonical(path) in {core.canonical(root) for root in self.roots}:
            messagebox.showinfo(APP_TITLE, "This library is already watched.", parent=self.window)
            return
        core.save_roots(self.roots + [path])
        self.refresh()
        self.root_tree.selection_set(path)
        self.refresh_games()

    def remove_root(self) -> None:
        root = self.require_root()
        if root is None:
            return
        if not messagebox.askyesno(APP_TITLE, f"Stop watching {root}?\n\nExisting folder icons will stay in place.", parent=self.window):
            return
        core.save_roots([item for item in self.roots if core.canonical(item) != core.canonical(root)])
        self.refresh()

    def _background(self, label: str, operation) -> None:
        if self.busy:
            messagebox.showinfo(APP_TITLE, "Another operation is still running.", parent=self.window)
            return
        self.busy = True
        self.status_text.set(label)

        def worker():
            try:
                result = operation()
                self.window.after(0, lambda: self._finished(label, result, None))
            except Exception as exc:
                self.window.after(0, lambda error=str(exc): self._finished(label, None, error))

        threading.Thread(target=worker, daemon=True).start()

    def _finished(self, label: str, result, error: str | None) -> None:
        self.busy = False
        if error:
            messagebox.showerror(APP_TITLE, error, parent=self.window)
            self.status_text.set(f"{label} failed")
        else:
            self.refresh()
            failed_scan = isinstance(result, int) and result != 0
            self.status_text.set(f"{label}: check the log for details" if failed_scan else f"{label} complete")

    def scan_root(self) -> None:
        root = self.require_root()
        if root is not None:
            self._background("Scan", lambda: core.scan_roots([str(root)]))

    def choose_cover(self) -> None:
        game = self.require_game()
        if game is None:
            return
        record = icons.load_state().get("folders", {}).get(str(game.resolve()).lower(), {})
        if record.get("status") == "managed":
            messagebox.showinfo(APP_TITLE, "Restore this tool's current icon before choosing a different cover.",
                                parent=self.window)
            return
        has_icon, _, _ = icons.existing_icon(game)
        if has_icon and not messagebox.askyesno(APP_TITLE,
                                                "Replace this folder's current icon? Its previous icon setting will be saved for restoration.",
                                                parent=self.window):
            return
        chosen = filedialog.askopenfilename(parent=self.window, title="Choose a cover image",
                                            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        if chosen:
            self._background("Choose cover", lambda: core.set_cover(game, Path(chosen)))

    def toggle_exclusion(self) -> None:
        game = self.require_game()
        if game is None:
            return
        marker = game / ".no-folder-icon"
        try:
            if marker.exists():
                if not marker.is_file():
                    raise ValueError("The exclusion marker is not a regular file")
                marker.unlink()
            else:
                marker.touch(exist_ok=False)
            self.refresh_games()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc), parent=self.window)

    def restore_icon(self) -> None:
        game = self.require_game()
        if game is None:
            return
        record = icons.load_state().get("folders", {}).get(str(game.resolve()).lower(), {})
        if record.get("status") != "managed":
            messagebox.showinfo(APP_TITLE, "This icon was not added by this tool, so it will not be changed.", parent=self.window)
            return
        if messagebox.askyesno(APP_TITLE, f"Restore the previous icon state for {game.name}?", parent=self.window):
            self._background("Restore icon", lambda: core.restore_folder(game))

    def toggle_task(self) -> None:
        if self.task_state == "current":
            if messagebox.askyesno(APP_TITLE, "Turn off automatic scans? Existing folder icons will stay.", parent=self.window):
                self._background("Turn off automatic scans", lambda: core.task_command("remove"))
            return
        if not self.roots:
            messagebox.showinfo(APP_TITLE, "Add a game library before enabling automatic scans.", parent=self.window)
            return
        if not getattr(sys, "frozen", False):
            messagebox.showinfo(APP_TITLE, "Install the packaged app to enable automatic scans from this window.", parent=self.window)
            return
        self._background("Turn on automatic scans", lambda: core.task_command("install", Path(sys.executable)))

    def open_root(self) -> None:
        root = self.require_root()
        if root is not None and root.is_dir():
            os.startfile(root)

    def open_game(self) -> None:
        game = self.require_game()
        if game is not None and game.is_dir():
            os.startfile(game)

    def open_log(self) -> None:
        if icons.LOG_PATH.is_file():
            os.startfile(icons.LOG_PATH)
        else:
            messagebox.showinfo(APP_TITLE, "No scan log has been created yet.", parent=self.window)


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--scheduled", action="store_true", help="Scan all watched libraries without opening the GUI")
    parser.add_argument("--uninstall-task", action="store_true", help="Remove only the owned automatic-scan task")
    parser.add_argument("--check", action="store_true", help="Print a diagnostic summary and exit")
    parser.add_argument("--smoke-gui", action="store_true", help="Open and close the GUI for a build check")
    parser.add_argument("--version", action="store_true", help="Print the app version")
    args = parser.parse_args()
    if args.version:
        print(APP_VERSION)
        return 0
    if args.uninstall_task:
        core.task_command("remove-current")
        return 0
    if args.check:
        print(json.dumps({"version": APP_VERSION, "roots": core.load_roots(), "task": core.task_status()}, indent=2))
        return 0
    if args.scheduled:
        try:
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
        except OSError:
            pass
        return core.scan_roots(core.load_roots(), max_candidates_per_root=2)
    if args.smoke_gui:
        window = ManagerWindow()
        window.window.update()
        window.window.destroy()
        return 0
    ManagerWindow().run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        icons.LOG.exception("Manager failed")
        if sys.stderr is None:
            messagebox.showerror(APP_TITLE, str(exc))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
