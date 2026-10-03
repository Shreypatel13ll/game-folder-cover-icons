from __future__ import annotations

import argparse
import base64
import ctypes
import difflib
import hashlib
import html
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import msvcrt
import os
from pathlib import Path
import random
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


APP_NAME = "GameFolderIcons"
VERSION = 1
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / APP_NAME
CACHE_DIR = DATA_DIR / "cache"
STATE_PATH = DATA_DIR / "state.json"
LOG_PATH = DATA_DIR / "automation.log"
LOCK_PATH = DATA_DIR / "scan.lock"

ICON_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
              (48, 48), (64, 64), (128, 128), (256, 256)]
MANAGED_PREFIX = ".folder-icon-auto-"
MANAGED_MARKER = "; ManagedBy=GameFolderIcons/v1"
MIN_FOLDER_AGE_SECONDS = 120
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
NETWORK_TIMEOUT = 20

FILE_ATTRIBUTE_READONLY = 0x00000001
FILE_ATTRIBUTE_HIDDEN = 0x00000002
FILE_ATTRIBUTE_SYSTEM = 0x00000004
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
ERROR_ALREADY_EXISTS = 183

GENERIC_NAMES = {
    "game", "launcher", "setup", "install", "installer", "client", "start", "play",
    "unity", "unity player", "unreal engine", "shipping", "win64", "win32",
}
EXE_REJECT = re.compile(
    r"(?i)(unins|uninstall|setup|install|crash|report|redist|vcredist|dxsetup|"
    r"easyanticheat|eac|unitycrash|benchmark|server|editor|helper|updater|launcher|javaw?)"
)
FOLDER_SUFFIXES = re.compile(
    r"(?i)\b(?:anker\s*games|fitgirl|dodi|repack|gog|steamrip|portable|"
    r"x64|x86|win64|windows)\b|\bv?\d+(?:\.\d+){1,4}\b"
)


def setup_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        if sys.stdout is not None:
            stream = logging.StreamHandler(sys.stdout)
            stream.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
            logger.addHandler(stream)
    return logger


LOG = setup_logging()


class SingleInstance:
    def __enter__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.handle = open(LOCK_PATH, "a+b")
        self.handle.seek(0)
        if self.handle.read(1) == b"":
            self.handle.seek(0)
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def __exit__(self, exc_type, exc, tb):
        if self.handle is not None:
            self.handle.seek(0)
            try:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                self.handle.close()


def get_attrs(path: Path) -> int:
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == INVALID_FILE_ATTRIBUTES:
        raise ctypes.WinError()
    return int(attrs)


def set_attrs(path: Path, attrs: int) -> None:
    if not ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs):
        raise ctypes.WinError()


def load_state() -> dict:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if state.get("version") == VERSION and isinstance(state.get("folders"), dict):
            return state
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {"version": VERSION, "folders": {}, "history": []}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=DATA_DIR, delete=False, suffix=".tmp") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    os.replace(temp_path, STATE_PATH)


def clean_title(value: str) -> str:
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", value)
    value = value.replace("_", " ").replace("-", " ").replace(".", " ")
    value = re.sub(r"[\[\(].*?[\]\)]", " ", value)
    value = FOLDER_SUFFIXES.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_.")
    return value


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.lower().replace("&", " and ")
    value = re.sub(r"\b(?:the|edition|game|pc)\b", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def title_score(query: str, result: str) -> float:
    a, b = normalized(query), normalized(result)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a.split()) == 1 or len(b.split()) == 1:
        return 0.0
    if set(re.findall(r"\d+", a)) != set(re.findall(r"\d+", b)):
        return 0.0
    addons = {"soundtrack", "dlc", "demo", "playtest", "server", "editor", "artbook"}
    if (set(b.split()) & addons) - set(a.split()):
        return 0.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    aset, bset = set(a.split()), set(b.split())
    jaccard = len(aset & bset) / max(1, len(aset | bset))
    containment = len(aset & bset) / max(1, min(len(aset), len(bset)))
    acronym_a = "".join(part[0] for part in a.split() if part)
    acronym_b = "".join(part[0] for part in b.split() if part)
    acronym = 0.0
    if acronym_a and acronym_a in bset:
        acronym = 0.90
    if acronym_b and acronym_b in aset:
        acronym = max(acronym, 0.90)
    return max(seq, 0.65 * jaccard + 0.35 * containment, acronym)


def is_good_title(value: str) -> bool:
    value = clean_title(value)
    return len(value) >= 3 and normalized(value) not in GENERIC_NAMES and bool(re.search(r"[A-Za-z]", value))


def limited_files(root: Path, max_depth: int = 6, max_dirs: int = 1800) -> list[Path]:
    found: list[Path] = []
    queue: list[tuple[Path, int]] = [(root, 0)]
    visited = 0
    while queue and visited < max_dirs:
        current, depth = queue.pop(0)
        visited += 1
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            suffix = Path(entry.name).suffix.lower()
                            if suffix in {".exe", ".txt", ".acf", ".info", ".json", ".ico", ".png", ".jpg", ".jpeg", ".webp"}:
                                found.append(Path(entry.path))
                        elif depth < max_depth and entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() not in {"__pycache__", ".git", ".svn"}:
                                queue.append((Path(entry.path), depth + 1))
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def read_text_best_effort(path: Path, limit: int = 1_000_000) -> str:
    payload = path.read_bytes()[:limit]
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return payload.decode(encoding)
        except UnicodeError:
            continue
    return payload.decode("utf-8", "replace")


def exe_version_strings(path: Path) -> dict[str, str]:
    version = ctypes.windll.version
    dummy = ctypes.c_uint(0)
    size = version.GetFileVersionInfoSizeW(str(path), ctypes.byref(dummy))
    if not size:
        return {}
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return {}

    pointer = ctypes.c_void_p()
    length = ctypes.c_uint(0)
    translations = [(0x0409, 0x04B0), (0x0409, 0x04E4)]
    if version.VerQueryValueW(buffer, r"\VarFileInfo\Translation", ctypes.byref(pointer), ctypes.byref(length)):
        raw = ctypes.string_at(pointer.value, length.value)
        translations = []
        for index in range(0, len(raw) - 3, 4):
            lang = int.from_bytes(raw[index:index + 2], "little")
            codepage = int.from_bytes(raw[index + 2:index + 4], "little")
            translations.append((lang, codepage))

    values: dict[str, str] = {}
    for key in ("ProductName", "FileDescription"):
        for lang, codepage in translations[:6]:
            query = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{key}"
            value_ptr = ctypes.c_void_p()
            value_len = ctypes.c_uint(0)
            if version.VerQueryValueW(buffer, query, ctypes.byref(value_ptr), ctypes.byref(value_len)) and value_ptr.value:
                value = ctypes.wstring_at(value_ptr.value, max(0, value_len.value - 1)).strip()
                if value:
                    values[key] = value
                    break
    return values


def discover(folder: Path) -> dict:
    files = limited_files(folder)
    app_id = None
    app_id_source = None
    manifest_title = None
    gog_title = None
    gog_id = None
    unity_title = None

    for path in files:
        if path.name.lower().startswith("appmanifest_") and path.suffix.lower() == ".acf":
            text = read_text_best_effort(path)
            app_match = re.search(r'"appid"\s+"(\d+)"', text, re.I)
            name_match = re.search(r'"name"\s+"([^"]+)"', text, re.I)
            file_match = re.search(r"appmanifest_(\d+)\.acf$", path.name, re.I)
            if app_match and file_match and app_match.group(1) == file_match.group(1):
                app_id = app_match.group(1)
                app_id_source = "manifest"
            if name_match:
                manifest_title = name_match.group(1).strip()
                break
    if not app_id:
        ignored_appids = {"480", "228980"}
        appid_files = sorted(
            (path for path in files if path.name.lower() == "steam_appid.txt"),
            key=lambda path: len(path.relative_to(folder).parts),
        )
        for path in appid_files:
            match = re.fullmatch(r"\s*(\d{3,10})\s*", read_text_best_effort(path, 256))
            if match and match.group(1) not in ignored_appids:
                app_id = match.group(1)
                app_id_source = "steam_appid"
                break
    for path in files:
        if path.name.lower().startswith("goggame-") and path.suffix.lower() == ".info":
            try:
                info = json.loads(read_text_best_effort(path))
                if is_good_title(str(info.get("name", ""))):
                    gog_title = str(info["name"]).strip()
                    raw_id = str(info.get("rootGameId") or info.get("gameId") or "").strip()
                    if raw_id.isdigit():
                        gog_id = raw_id
                    break
            except (json.JSONDecodeError, OSError):
                continue
    for path in files:
        if path.name.lower() == "app.info" and path.parent.name.lower().endswith("_data"):
            try:
                lines = [line.strip() for line in read_text_best_effort(path, 20_000).splitlines() if line.strip()]
                if len(lines) >= 2 and is_good_title(lines[1]):
                    unity_title = lines[1]
                    break
            except OSError:
                continue

    exes = []
    for path in files:
        if path.suffix.lower() != ".exe" or EXE_REJECT.search(path.name):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        metadata = exe_version_strings(path)
        titles = [metadata.get("ProductName", ""), metadata.get("FileDescription", ""), clean_title(path.stem)]
        title = next((item.strip() for item in titles if is_good_title(item)), "")
        if title:
            exes.append((size, path, title))
    exes.sort(key=lambda item: item[0], reverse=True)

    titles = []
    for value in (manifest_title, gog_title, unity_title):
        if value and is_good_title(value) and value not in titles:
            titles.append(value)
    for _size, _path, value in exes[:8]:
        if value not in titles and is_good_title(value):
            titles.append(value)
    folder_title = clean_title(folder.name)
    if is_good_title(folder_title) and folder_title not in titles:
        titles.append(folder_title)

    return {
        "appid": app_id,
        "appid_source": app_id_source,
        "gog_id": gog_id,
        "titles": titles,
        "primary_title": titles[0] if titles else None,
        "main_exe": str(exes[0][1]) if exes else None,
        "has_game_evidence": bool(app_id or manifest_title or gog_title or unity_title or exes),
        "files": files,
    }


def http_bytes(url: str) -> tuple[bytes, str]:
    if not url.lower().startswith("https://"):
        raise ValueError("Only HTTPS artwork URLs are permitted")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GameFolderIcons/1.0",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
        content_type = response.headers.get("Content-Type", "")
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Artwork is larger than the configured limit")
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Artwork download exceeded the configured limit")
        return data, content_type


def image_from_bytes(data: bytes, min_short_edge: int = 180) -> Image.Image:
    if len(data) < 2_000:
        raise ValueError("Image payload is too small")
    with Image.open(io.BytesIO(data)) as probe:
        probe.verify()
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source)
        if image.format == "ICO" and hasattr(image, "ico"):
            largest = max(image.ico.sizes(), key=lambda size: size[0] * size[1])
            image = image.ico.getimage(largest)
        image = image.convert("RGBA")
        if min(image.size) < min_short_edge:
            raise ValueError(f"Image resolution is too small: {image.size}")
        return image.copy()


def search_steam(titles: list[str]) -> dict | None:
    candidates_by_id: dict[str, dict] = {}
    for title in titles[:4]:
        url = "https://store.steampowered.com/api/storesearch/?term=" + urllib.parse.quote(title) + "&l=english&cc=US"
        try:
            data, _ = http_bytes(url)
            payload = json.loads(data.decode("utf-8"))
        except Exception as exc:
            LOG.warning("Steam search failed for %r: %s", title, exc)
            continue
        for item in payload.get("items", [])[:10]:
            if item.get("type") != "app" or not item.get("id") or not item.get("name"):
                continue
            score = title_score(title, str(item["name"]))
            candidate = {
                "appid": str(item["id"]),
                "name": str(item["name"]),
                "tiny_image": item.get("tiny_image"),
                "score": score,
                "query": title,
            }
            appid = candidate["appid"]
            if appid not in candidates_by_id or score > candidates_by_id[appid]["score"]:
                candidates_by_id[appid] = candidate
    ranked = sorted(candidates_by_id.values(), key=lambda item: item["score"], reverse=True)
    best = ranked[0] if ranked else None
    runner_up = ranked[1]["score"] if len(ranked) > 1 else 0.0
    if best and best["score"] >= 0.88:
        if best["score"] < 0.999 and runner_up > best["score"] - 0.12:
            return None
        return best
    return None


def gog_artwork(game_id: str, title: str, cache_key: str) -> tuple[Image.Image, str] | None:
    cached = CACHE_DIR / f"{cache_key}.png"
    if cached.exists():
        try:
            return image_from_bytes(cached.read_bytes()), f"cache:{cached.name}"
        except Exception:
            pass
    query = urllib.parse.quote("like:" + title)
    url = (
        "https://catalog.gog.com/v1/catalog?query=" + query +
        "&limit=10&productType=in%3Agame&countryCode=US&locale=en-US&currencyCode=USD"
    )
    try:
        data, _ = http_bytes(url)
        payload = json.loads(data.decode("utf-8"))
        product = next((item for item in payload.get("products", []) if str(item.get("id")) == game_id), None)
        if product and product.get("coverVertical"):
            art_url = str(product["coverVertical"])
            art_data, _ = http_bytes(art_url)
            image = image_from_bytes(art_data)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            image.save(cached, "PNG", optimize=True)
            return image, art_url
    except Exception as exc:
        LOG.warning("GOG artwork lookup failed for %s (%s): %s", title, game_id, exc)
    return None


def steam_artwork(appid: str, cache_key: str) -> tuple[Image.Image, str] | None:
    cached = CACHE_DIR / f"{cache_key}.png"
    if cached.exists():
        try:
            return image_from_bytes(cached.read_bytes()), f"cache:{cached.name}"
        except Exception:
            pass

    direct = [
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900_2x.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_capsule_2x.jpg",
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_capsule.jpg",
    ]
    for url in direct:
        try:
            data, _content_type = http_bytes(url)
            image = image_from_bytes(data)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            image.save(cached, "PNG", optimize=True)
            return image, url
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError):
            continue

    page_url = f"https://store.steampowered.com/app/{appid}/?l=english&cc=US"
    try:
        page, _ = http_bytes(page_url)
        page_text = page.decode("utf-8", "replace")
        match = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)', page_text, re.I)
        if not match:
            match = re.search(r'<link\s+rel=["\']image_src["\']\s+href=["\']([^"\']+)', page_text, re.I)
        if match:
            url = html.unescape(match.group(1))
            data, _ = http_bytes(url)
            image = image_from_bytes(data)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            image.save(cached, "PNG", optimize=True)
            return image, url
    except Exception as exc:
        LOG.warning("Steam artwork page fallback failed for app %s: %s", appid, exc)
    return None


def local_artwork(files: list[Path]) -> tuple[Image.Image, str] | None:
    candidates = []
    key_pattern = re.compile(r"(?i)(cover|poster|box.?art|key.?art|capsule|library|goggame|app.?icon|logo)")
    for path in files:
        if path.name.lower().startswith(MANAGED_PREFIX) or path.suffix.lower() not in {".ico", ".png", ".jpg", ".jpeg", ".webp"}:
            continue
        score = 0
        if key_pattern.search(path.stem):
            score += 5
        if path.suffix.lower() == ".ico":
            score += 3
        try:
            score += min(3, int(path.stat().st_size / 100_000))
        except OSError:
            continue
        candidates.append((score, path))
    for _score, path in sorted(candidates, reverse=True)[:20]:
        try:
            image = image_from_bytes(path.read_bytes(), min_short_edge=64 if path.suffix.lower() == ".ico" else 180)
            return image, str(path)
        except Exception:
            continue
    return None


def safe_font(size: int, bold: bool = False):
    name = "seguisb.ttf" if bold else "segoeui.ttf"
    try:
        return ImageFont.truetype(str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / name), size)
    except OSError:
        return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int = 3) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if current and draw.textlength(test, font=font) > width:
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break
        else:
            current = test
    remaining_start = sum(len(line.split()) for line in lines)
    remaining_words = words[remaining_start:]
    if remaining_words:
        current = " ".join(remaining_words)
        while draw.textlength(current, font=font) > width and len(current) > 4:
            current = current[:-2].rstrip() + "…"
    if current:
        lines.append(current)
    return lines[:max_lines]


def title_card(title: str) -> Image.Image:
    digest = hashlib.sha256(title.encode("utf-8")).digest()
    c1 = tuple(38 + byte % 115 for byte in digest[:3])
    c2 = tuple(18 + byte % 90 for byte in digest[3:6])
    width, height = 900, 1200
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        for x in range(width):
            glow = 0.15 * (1 - abs((x / width) - 0.5) * 2)
            pixels[x, y] = tuple(int(c1[i] * (1 - ratio) + c2[i] * ratio + 28 * glow) for i in range(3)) + (255,)
    draw = ImageDraw.Draw(image, "RGBA")
    for index in range(7):
        inset = 50 + index * 55
        draw.rounded_rectangle((inset, inset + 40, width - inset, height - inset + 40), radius=70,
                               outline=(255, 255, 255, max(8, 42 - index * 5)), width=4)
    initials = "".join(word[0] for word in re.findall(r"[A-Za-z0-9]+", title)[:3]).upper() or "G"
    initials_font = safe_font(230, bold=True)
    bbox = draw.textbbox((0, 0), initials, font=initials_font, stroke_width=4)
    iw, ih = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - iw) / 2, 285 - ih / 2), initials, font=initials_font,
              fill=(255, 255, 255, 220), stroke_width=4, stroke_fill=(0, 0, 0, 80))
    title_font = safe_font(64, bold=True)
    lines = wrap_text(draw, title, title_font, 760, 3)
    total = len(lines) * 78
    y = 785 - total / 2
    for line in lines:
        tw = draw.textlength(line, font=title_font)
        draw.text(((width - tw) / 2, y), line, font=title_font, fill=(255, 255, 255, 245),
                  stroke_width=3, stroke_fill=(0, 0, 0, 110))
        y += 78
    draw.text((width / 2, 1085), "GAME", anchor="mm", font=safe_font(30, bold=True), fill=(255, 255, 255, 145))
    return image


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def make_master(source: Image.Image) -> Image.Image:
    source = source.convert("RGBA")
    canvas = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    tile_pos, tile_size = (36, 36), (952, 952)
    background = ImageOps.fit(source, tile_size, Image.Resampling.LANCZOS, centering=(0.5, 0.40))
    background = background.filter(ImageFilter.GaussianBlur(34))
    background = ImageEnhance.Brightness(ImageEnhance.Color(background).enhance(1.10)).enhance(0.58)
    tile_mask = rounded_mask(tile_size, 142)

    shadow_mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(shadow_mask).rounded_rectangle((46, 54, 978, 986), radius=140, fill=180)
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(24))
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 145))
    shadow_layer.putalpha(shadow_mask)
    canvas.alpha_composite(shadow_layer)
    canvas.paste(background, tile_pos, tile_mask)

    scale = min(735 / source.width, 882 / source.height)
    size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    cover = source.resize(size, Image.Resampling.LANCZOS)
    cover_mask = rounded_mask(size, max(18, round(min(size) * 0.045)))
    alpha = cover.getchannel("A")
    alpha_bytes = bytes((a * b) // 255 for a, b in zip(alpha.tobytes(), cover_mask.tobytes()))
    cover.putalpha(Image.frombytes("L", size, alpha_bytes))
    x, y = (1024 - size[0]) // 2, (1024 - size[1]) // 2 - 4

    cover_shadow = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(cover_shadow).rounded_rectangle((x + 2, y + 14, x + size[0] + 2, y + size[1] + 14),
                                                  radius=max(18, round(min(size) * 0.045)), fill=205)
    cover_shadow = cover_shadow.filter(ImageFilter.GaussianBlur(22))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 150))
    layer.putalpha(cover_shadow)
    canvas.alpha_composite(layer)
    canvas.alpha_composite(cover, dest=(x, y))

    outline = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(outline).rounded_rectangle((1, 1, size[0] - 2, size[1] - 2),
                                             radius=max(18, round(min(size) * 0.045)),
                                             outline=(255, 255, 255, 70), width=3)
    canvas.alpha_composite(outline, dest=(x, y))
    return canvas


def write_and_validate_ico(master: Image.Image, destination: Path) -> str:
    frames = []
    for size in ICON_SIZES:
        frame = master.resize(size, Image.Resampling.LANCZOS)
        if size[0] <= 64:
            frame = frame.filter(ImageFilter.UnsharpMask(radius=0.65, percent=135, threshold=2))
        frames.append(frame)
    frames[-1].save(destination, format="ICO", sizes=ICON_SIZES, append_images=frames[:-1])
    with Image.open(destination) as icon:
        if set(icon.ico.sizes()) != set(ICON_SIZES):
            raise ValueError("Generated ICO is missing required sizes")
        for size in ICON_SIZES:
            frame = icon.ico.getimage(size).convert("RGBA")
            if frame.size != size or frame.getchannel("A").getbbox() is None:
                raise ValueError(f"Generated ICO has an invalid {size} frame")
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def decode_ini(data: bytes) -> str:
    for encoding in ("utf-16", "utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    return data.decode("utf-8", "replace")


def existing_icon(folder: Path) -> tuple[bool, str | None, bool]:
    ini = folder / "desktop.ini"
    if not ini.exists():
        return False, None, False
    try:
        text = decode_ini(ini.read_bytes())
    except OSError:
        return False, None, False
    marker = MANAGED_MARKER.lower() in text.lower()
    match = re.search(r"(?im)^\s*IconResource\s*=\s*([^,\r\n]+)", text)
    if not match:
        file_match = re.search(r"(?im)^\s*IconFile\s*=\s*([^\r\n]+)", text)
        icon_name = file_match.group(1).strip().strip('"') if file_match else None
    else:
        icon_name = match.group(1).strip().strip('"')
    if not icon_name:
        return False, None, marker
    icon_path = Path(icon_name)
    if not icon_path.is_absolute():
        icon_path = folder / icon_path
    return icon_path.exists(), str(icon_path), marker


def merge_ini(existing: bytes | None, icon_name: str) -> bytes:
    if existing is None:
        return (MANAGED_MARKER + "\r\n[.ShellClassInfo]\r\n" + f"IconResource={icon_name},0\r\n").encode("utf-16")
    text = decode_ini(existing)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not any(MANAGED_MARKER.lower() == line.strip().lower() for line in lines):
        lines.insert(0, MANAGED_MARKER)
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        if line.strip().lower() == "[.shellclassinfo]":
            start = index
            for later in range(index + 1, len(lines)):
                value = lines[later].strip()
                if value.startswith("[") and value.endswith("]"):
                    end = later
                    break
            break
    new_line = f"IconResource={icon_name},0"
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.extend(["", "[.ShellClassInfo]", new_line])
    else:
        replaced = False
        output = []
        for index, line in enumerate(lines):
            inside = start < index < end
            key = line.split("=", 1)[0].strip().lower() if "=" in line else ""
            if inside and key in {"iconresource", "iconfile", "iconindex"}:
                if not replaced:
                    output.append(new_line)
                    replaced = True
                continue
            output.append(line)
        lines = output
        if not replaced:
            lines.insert(start + 1, new_line)
    return ("\r\n".join(lines).rstrip("\r\n") + "\r\n").encode("utf-16")


def notify_shell(folder: Path, root: Path) -> None:
    shell32 = ctypes.windll.shell32
    flags = 0x0005 | 0x1000  # SHCNF_PATHW | SHCNF_FLUSH
    shell32.SHChangeNotify(0x00002000, flags, ctypes.c_wchar_p(str(folder)), None)
    shell32.SHChangeNotify(0x00001000, flags, ctypes.c_wchar_p(str(root)), None)


def apply_icon(folder: Path, title: str, master: Image.Image, source: str, state: dict) -> dict:
    ini = folder / "desktop.ini"
    existing_bytes = ini.read_bytes() if ini.exists() else None
    folder_attrs = get_attrs(folder)
    ini_attrs = get_attrs(ini) if ini.exists() else None

    with tempfile.TemporaryDirectory(prefix="gfi-") as temp_name:
        temp_icon = Path(temp_name) / "icon.ico"
        icon_hash = write_and_validate_ico(master, temp_icon)
        icon_name = f"{MANAGED_PREFIX}{icon_hash[:10]}.ico"
        icon_path = folder / icon_name
        staged = folder / f"{icon_name}.tmp"
        try:
            shutil.copyfile(temp_icon, staged)
            os.replace(staged, icon_path)
            set_attrs(icon_path, get_attrs(icon_path) | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)

            if ini.exists():
                set_attrs(ini, get_attrs(ini) & ~(FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
            ini.write_bytes(merge_ini(existing_bytes, icon_name))
            set_attrs(ini, get_attrs(ini) | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)
            set_attrs(folder, get_attrs(folder) | FILE_ATTRIBUTE_READONLY)
            notify_shell(folder, folder.parent)
        except Exception:
            if staged.exists():
                staged.unlink(missing_ok=True)
            if icon_path.exists():
                try:
                    set_attrs(icon_path, get_attrs(icon_path) & ~(FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM | FILE_ATTRIBUTE_READONLY))
                    icon_path.unlink()
                except OSError:
                    pass
            if existing_bytes is None:
                if ini.exists():
                    try:
                        set_attrs(ini, get_attrs(ini) & ~(FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM | FILE_ATTRIBUTE_READONLY))
                        ini.unlink()
                    except OSError:
                        pass
            else:
                ini.write_bytes(existing_bytes)
                if ini_attrs is not None:
                    set_attrs(ini, ini_attrs)
            set_attrs(folder, folder_attrs)
            raise

    record = {
        "status": "managed",
        "title": title,
        "source": source,
        "icon": str(icon_path),
        "icon_sha256": icon_hash,
        "managed_at": int(time.time()),
        "backup": {
            "folder_attributes": folder_attrs,
            "desktop_ini_existed": existing_bytes is not None,
            "desktop_ini_attributes": ini_attrs,
            "desktop_ini_base64": base64.b64encode(existing_bytes).decode("ascii") if existing_bytes is not None else None,
        },
    }
    state.setdefault("history", []).append({"folder": str(folder), **{k: record[k] for k in ("title", "source", "icon", "managed_at")}})
    state["history"] = state["history"][-200:]
    return record


def retry_record(previous: dict | None, status: str, message: str, delay: int) -> dict:
    attempts = int((previous or {}).get("attempts", 0)) + 1
    jitter = random.randint(0, max(1, delay // 5))
    return {
        "status": status,
        "message": message,
        "attempts": attempts,
        "last_attempt": int(time.time()),
        "retry_after": int(time.time()) + delay + jitter,
    }


def process_folder(folder: Path, state: dict, force_retry: bool = False) -> str:
    key = str(folder.resolve()).lower()
    previous = state["folders"].get(key)
    valid, icon_path, managed = existing_icon(folder)
    if valid:
        if previous is None:
            state["folders"][key] = {"status": "existing_icon", "icon": icon_path, "managed": managed}
        return "skipped-existing"
    if (folder / ".no-folder-icon").exists():
        state["folders"][key] = {"status": "ignored", "reason": ".no-folder-icon marker"}
        return "ignored"
    if previous and not force_retry and int(previous.get("retry_after", 0)) > int(time.time()):
        return "backoff"
    try:
        if time.time() - folder.stat().st_ctime < MIN_FOLDER_AGE_SECONDS:
            state["folders"][key] = retry_record(previous, "settling", "Folder is still new", 120)
            return "settling"
        evidence = discover(folder)
        if not evidence["has_game_evidence"] or not evidence["primary_title"]:
            state["folders"][key] = retry_record(previous, "pending", "No game executable or manifest detected yet", 900)
            return "pending"

        title = evidence["primary_title"]
        appid = evidence["appid"]
        gog_id = evidence["gog_id"]
        steam_match = None
        if not appid or evidence["appid_source"] == "steam_appid":
            steam_match = search_steam(evidence["titles"])
            if steam_match and (not appid or steam_match["appid"] == appid):
                appid = steam_match["appid"]
                title = steam_match["name"]
            elif evidence["appid_source"] == "steam_appid":
                appid = None

        artwork = None
        if gog_id:
            artwork = gog_artwork(gog_id, title, f"gog-{gog_id}")
        if appid:
            artwork = artwork or steam_artwork(appid, f"steam-{appid}")
        if artwork is None:
            artwork = local_artwork(evidence["files"])
        if artwork is None:
            if appid or gog_id:
                raise RuntimeError("Online cover lookup failed and no suitable local artwork was found")
            artwork = (title_card(title), "generated-title-card")

        image, source = artwork
        master = make_master(image)
        state["folders"][key] = apply_icon(folder, title, master, source, state)
        LOG.info("Applied icon: %s -> %s (%s)", folder.name, title, source)
        return "managed"
    except Exception as exc:
        attempts = int((previous or {}).get("attempts", 0)) + 1
        delay_steps = [60, 300, 900, 3600, 21600, 86400]
        delay = delay_steps[min(attempts - 1, len(delay_steps) - 1)]
        state["folders"][key] = retry_record(previous, "retry", str(exc), delay)
        LOG.exception("Failed to process %s", folder)
        return "failed"


def direct_child_folders(root: Path) -> list[Path]:
    folders = []
    for child in root.iterdir():
        try:
            if not child.is_dir() or child.is_symlink():
                continue
            attrs = get_attrs(child)
            if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            if child.name.startswith(".") or child.name.startswith("__"):
                continue
            if attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                continue
            folders.append(child)
        except OSError:
            continue
    return sorted(folders, key=lambda path: path.name.lower())


def scan(root: Path, force_retry: bool = False) -> int:
    if not root.is_dir():
        LOG.error("Games root is unavailable: %s", root)
        return 2
    state = load_state()
    root_prefix = str(root.resolve()).lower().rstrip("\\/") + os.sep
    for key in list(state["folders"]):
        if key.startswith(root_prefix) and not Path(key).exists():
            del state["folders"][key]
    state["history"] = [entry for entry in state.get("history", []) if Path(entry.get("folder", "")).exists()]
    counts: dict[str, int] = {}
    folders = direct_child_folders(root)
    for folder in folders:
        result = process_folder(folder, state, force_retry=force_retry)
        counts[result] = counts.get(result, 0) + 1
        save_state(state)
    state["last_scan"] = int(time.time())
    state["last_root"] = str(root)
    state["last_counts"] = counts
    save_state(state)
    LOG.info("Scan complete for %s: %s", root, counts)
    return 0 if not counts.get("failed") else 1


def restore_managed(root: Path) -> int:
    """Restore only unchanged folder customizations recorded by this tool."""
    state = load_state()
    restored = 0
    conflicts = 0
    for key, record in list(state["folders"].items()):
        if record.get("status") != "managed":
            continue
        folder = Path(key)
        if folder.parent.resolve() != root.resolve() or not folder.is_dir() or folder.is_symlink():
            continue
        try:
            if get_attrs(folder) & FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            icon = Path(record["icon"])
            if icon.parent.resolve() != folder.resolve() or not icon.name.startswith(MANAGED_PREFIX):
                raise ValueError("Recorded icon path is outside its game folder")
            if not icon.is_file() or hashlib.sha256(icon.read_bytes()).hexdigest() != record["icon_sha256"]:
                raise ValueError("Managed icon is missing or has been changed")

            backup = record["backup"]
            original = (base64.b64decode(backup["desktop_ini_base64"])
                        if backup["desktop_ini_existed"] else None)
            ini = folder / "desktop.ini"
            expected = merge_ini(original, icon.name)
            current = ini.read_bytes() if ini.exists() else None
            if current != expected:
                raise ValueError("desktop.ini has changed since the icon was applied")

            set_attrs(ini, get_attrs(ini) & ~(FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
            if original is None:
                ini.unlink()
            else:
                ini.write_bytes(original)
                set_attrs(ini, int(backup["desktop_ini_attributes"]))

            set_attrs(icon, get_attrs(icon) & ~(FILE_ATTRIBUTE_READONLY | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))
            icon.unlink()
            if not (int(backup["folder_attributes"]) & FILE_ATTRIBUTE_READONLY):
                set_attrs(folder, get_attrs(folder) & ~FILE_ATTRIBUTE_READONLY)
            notify_shell(folder, root)
            state["folders"][key] = {"status": "restored", "restored_at": int(time.time())}
            save_state(state)
            restored += 1
        except Exception as exc:
            conflicts += 1
            LOG.warning("Could not restore %s: %s", folder, exc)
    LOG.info("Restore complete for %s: %s restored, %s conflicts", root, restored, conflicts)
    return 0 if conflicts == 0 else 1


def self_test() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destination = CACHE_DIR / "self-test.ico"
    master = make_master(title_card("Game Folder Icons"))
    digest = write_and_validate_ico(master, destination)
    LOG.info("Self-test passed (%s, %s)", destination, digest[:12])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatically add cover-art icons to new game folders.")
    parser.add_argument("--root", type=Path, help="Directory containing one folder per game")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--restore", action="store_true", help="Restore unchanged icons added by this tool")
    parser.add_argument("--force-retry", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.root is None:
        parser.error("--root is required for a scan or restore")
    with SingleInstance() as acquired:
        if not acquired:
            LOG.error("Another scan is already running")
            return 3 if args.restore else 0
        if args.restore:
            return restore_managed(args.root.resolve())
        return scan(args.root.resolve(), force_retry=args.force_retry)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        LOG.exception("Fatal automation error")
        raise
