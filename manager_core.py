"""Configuration and task control shared by the GUI and packaged executable."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import auto_folder_icons as icons


CONFIG_PATH = icons.DATA_DIR / "config.json"
TASK_NAME = "Auto Game Folder Icons"


def task_script_path() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    return base / "task.ps1"


def canonical(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def load_roots(path: Path = CONFIG_PATH) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("roots"), list):
        raise ValueError(f"Invalid manager configuration: {path}")
    roots = []
    seen = set()
    for item in data["roots"]:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"Invalid watched folder in {path}")
        normalized = canonical(item)
        if normalized not in seen:
            roots.append(str(Path(item).expanduser().resolve()))
            seen.add(normalized)
    return roots


def save_roots(roots: list[str], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    unique = []
    seen = set()
    for item in roots:
        normalized = canonical(item)
        if normalized not in seen:
            unique.append(str(Path(item).expanduser().resolve()))
            seen.add(normalized)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        json.dump({"version": 1, "roots": unique}, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
        staged = Path(handle.name)
    os.replace(staged, path)


def task_command(action: str, executable: Path | None = None) -> str:
    if action not in {"status", "install", "remove", "remove-current"}:
        raise ValueError(f"Unsupported task action: {action}")
    script = task_script_path()
    if not script.is_file():
        raise FileNotFoundError(f"Task helper is missing: {script}")
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
               "-Action", action]
    if executable is not None:
        command.extend(["-ExePath", str(executable)])
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=60)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"Task command failed: {action}")
    return result.stdout.strip()


def task_status() -> dict:
    return json.loads(task_command("status"))


def import_legacy_root_if_needed() -> list[str]:
    roots = load_roots()
    if roots or CONFIG_PATH.exists():
        return roots
    status = task_status()
    old_root = status.get("root")
    if status.get("state") == "legacy" and old_root and Path(old_root).is_dir():
        roots = [str(Path(old_root).resolve())]
        save_roots(roots)
    return roots


def scan_roots(roots: list[str], max_candidates_per_root: int | None = None) -> int:
    if not roots:
        icons.LOG.info("No watched game libraries are configured")
        return 0
    with icons.SingleInstance() as acquired:
        if not acquired:
            icons.LOG.info("A game-folder scan is already running")
            return 0
        results = [icons.scan(Path(root).resolve(), max_candidates=max_candidates_per_root) for root in roots]
    return max(results, default=0)


def set_cover(folder: Path, image_path: Path) -> None:
    from PIL import Image

    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("The selected game folder is unavailable")
    if (folder / ".no-folder-icon").exists():
        raise ValueError("Remove the exclusion before choosing a cover")
    with icons.SingleInstance() as acquired:
        if not acquired:
            raise RuntimeError("A game-folder scan is already running")
        state = icons.load_state()
        key = str(folder.resolve()).lower()
        if state["folders"].get(key, {}).get("status") == "managed":
            raise ValueError("Restore this tool's current icon before choosing a different cover.")
        with Image.open(image_path) as image:
            master = icons.make_master(image.convert("RGBA"))
        record = icons.apply_icon(folder, folder.name, master, f"chosen:{image_path.name}", state)
        state["folders"][key] = record
        icons.save_state(state)


def restore_folder(folder: Path) -> int:
    with icons.SingleInstance() as acquired:
        if not acquired:
            raise RuntimeError("A game-folder scan is already running")
        return icons.restore_managed(folder.parent.resolve(), only_folder=folder.resolve())
