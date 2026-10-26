#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l4d2-plugins-install-update-tool: 同步 L4D2 SourceMod 插件仓库并检测 Require 依赖。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape as html_unescape
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

SM_DIR_MAP = {
    "plugins": "plugins",
    "scripting": "scripting",
    "translations": "translations",
    "gamedata": "gamedata",
    "configs": "configs",
    "cfg": "configs",
    "data": "data",
    "extensions": "extensions",
}

GAME_DIR_MAP = {
    "sound": "sound",
    "sounds": "sound",
    "materials": "materials",
    "models": "models",
    "particles": "particles",
}

SKIP_TOP_DIRS = {
    ".git",
    ".github",
    "image",
    "images",
    "logs",
    "log",
}

SKIP_REPO_ROOT_DIRS = {
    ".git",
    ".github",
    "scripting",  # 仓库根目录编译器，不是插件
    "scripting_1.11",
    "scripting_1.12",
}

SKIP_FILE_NAMES = {
    "readme.md",
    "readme.txt",
    "license",
    "license.md",
    ".gitattributes",
    ".gitignore",
}

CONFIG_LIKE_ROOTS = {"configs", "cfg", "data"}
NONE_TOKENS = {"", "none", "n/a", "no", "无", "無", "-"}

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.txt"
OLD_GAME_DIR_FILE = SCRIPT_DIR / "game_dir.txt"
LOG_FILE = SCRIPT_DIR / "log.txt"
AM_COOKIE_FILE = SCRIPT_DIR / ".cache" / "am_cf_cookies.json"

REQUIRE_HEAD_RE = re.compile(r"^\*\s*Require(\s*\|[^:]*)?\s*:?\s*(.*)$", re.I)
REQUIRE_ITEM_RE = re.compile(r"^(?:\d+\.|[-*+])\s+(.+)$")
MD_LINK_RE = re.compile(
    r"\[(?:\[INC\]\s*)?([^\]]+)\]\(([^)]+)\)",
    re.I,
)
AM_ATTACH_RE = re.compile(r"attachmentid=(\d+)", re.I)
AM_COMPILER_RE = re.compile(r"vbcompiler\.php\?file_id=(\d+)", re.I)
COMMAND_BUFFER_SP_URL = (
    "https://forums.alliedmods.net/attachment.php"
    "?s=44f0a096b0ccc27fa4edb3f93ae0037a&attachmentid=170776&d=1781971302"
)
LADDER_PATCH_SP_URL = "https://forums.alliedmods.net/attachment.php?attachmentid=193611&d=1644698569"
REMOVE_ITEM_COLLISION_SP_URL = (
    "https://forums.alliedmods.net/attachment.php?attachmentid=188755&d=1655402146"
)
AM_SOURCE_SP_BY_AID = {
    "170776": {"name": "command_buffer.sp", "url": COMMAND_BUFFER_SP_URL},
    "193611": {"name": "l4d2_ladder_patch.sp", "url": LADDER_PATCH_SP_URL},
    "188755": {"name": "l4d_remove_item_collision.sp", "url": REMOVE_ITEM_COLLISION_SP_URL},
}
AM_ATTACH_HREF_RE = re.compile(
    r"""href=["']([^"']*attachment\.php\?[^"']*attachmentid=(\d+)[^"']*)["']""",
    re.I,
)
AM_ATTACH_LABEL_RE = re.compile(
    r"""href=["']([^"']*attachmentid=(\d+)[^"']*)["'][^>]*>([^<]{1,120})""",
    re.I,
)
AM_ATTACH_NAMED_RE = re.compile(
    r"attachmentid=(\d+)[^\"'<>]*[\"'][^>]*>([^<]+\.(?:txt|sp|smx|zip|inc))",
    re.I,
)
AM_ATTACH_TABLE_RE = re.compile(
    r"([A-Za-z0-9_.\-]+\.(?:txt|sp|smx|zip|inc))\s*\([^)]{0,80}\)"
    r".{0,800}?attachmentid=(\d+)",
    re.I | re.S,
)
AM_GET_SOURCE_RE = re.compile(
    r"(?:Get\s+Plugin(?:\s+or\s+Get\s+Source)?|Get\s+Source)\s*\(\s*"
    r"([A-Za-z0-9][A-Za-z0-9_.\-&,+]*\.sp)\b",
    re.I,
)
AM_FILE_TOKEN_RE = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9_.\-&,+]*\.(?:txt|sp|smx|zip|inc))\b",
    re.I,
)
AM_INSTALLED_FILE = SCRIPT_DIR / ".cache" / "am_installed.json"
GD_DEFINE_RE = re.compile(r'#define\s+(GAMEDATA(?:_FILE)?)\s+"([^"]+)"')
GD_LOAD_STR_RE = re.compile(
    r'(?:LoadGameConfigFile|GameDataWrapper|(?:new\s+)?GameData)\s*\(\s*"([^"]+)"\s*\)'
)
GD_LOAD_MACRO_RE = re.compile(r"LoadGameConfigFile\s*\(\s*(GAMEDATA(?:_FILE)?)\s*\)")
GITHUB_REPO_RE = re.compile(
    r"https?://github\.com/([\w.\-]+)/([\w.\-]+?)(?:\.git)?(?=/|$|\?|#)",
    re.I,
)

PRIVATE_PLUGIN_TREE = "https://github.com/fbef0102/Game-Private_Plugin/tree/main"

FIX_README_RAW = (
    "https://raw.githubusercontent.com/fbef0102/Game-Private_Plugin/main/"
    "Tutorial_教學區/Chinese_繁體中文/Server/安裝實用的修復/README.md"
)
FIX_README_PAGE = (
    "https://github.com/fbef0102/Game-Private_Plugin/tree/main/"
    "Tutorial_教學區/Chinese_繁體中文/Server/安裝實用的修復"
)
COOP8_README_RAW = (
    "https://raw.githubusercontent.com/fbef0102/Game-Private_Plugin/main/"
    "Tutorial_教學區/Chinese_繁體中文/Game/L4D2/8位玩家遊玩戰役模式/README.md"
)
COOP8_README_PAGE = (
    "https://github.com/fbef0102/Game-Private_Plugin/tree/main/"
    "Tutorial_教學區/Chinese_繁體中文/Game/L4D2/8位玩家遊玩戰役模式"
)
ZOMBIE_SPAWN_FIX_URL = "https://github.com/umlka/l4d2/tree/main/zombie_spawn_fix"
SPAWN_INFECTED_NOLIMIT_URL = (
    "https://github.com/fbef0102/L4D1_2-Plugins/tree/master/spawn_infected_nolimit"
)
UNRESTRICT_PANIC_URL = (
    "https://github.com/Target5150/MoYu_Server_Stupid_Plugins/tree/master/"
    "The%20Last%20Stand/l4d_unrestrict_panic_battlefield"
)
WITCH_PIPEBOMB_URL = (
    "https://github.com/LuxLuma/Left-4-fix/blob/master/"
    "left%204%20fix/general/witch_pipebomb_exploit_fix_%26_death_optmizer.sp"
)
SOURCE_KEYVALUES_URL = "https://github.com/fdxx/l4d2_source_keyvalues"
BUILTINVOTES_URL = "https://github.com/fbef0102/builtinvotes/releases"
BUILTINVOTES_WIN_ZIPS = [
    "https://github.com/fbef0102/builtinvotes/releases/download/v0.8.0/builtinvotes-sm1.12-win.0.8.0.zip",
]
REQUIRE_INSTALL_URLS = {
    "zombie_spawn_fix": ZOMBIE_SPAWN_FIX_URL,
    "spawn_infected_nolimit": SPAWN_INFECTED_NOLIMIT_URL,
    "l4d_unrestrict_panic_battlefield": UNRESTRICT_PANIC_URL,
    "sceneprocessor": "https://forums.alliedmods.net/showthread.php?p=2766130",
    "l4d2_source_keyvalues": SOURCE_KEYVALUES_URL,
    "builtinvotes": BUILTINVOTES_URL,
    "linux_auto_restart": "https://github.com/fbef0102/Sourcemod-Plugins/tree/main/linux_auto_restart",
    "server_loader": "https://github.com/fbef0102/Sourcemod-Plugins/tree/main/server_loader",
    "smd_advertisements": "https://github.com/fbef0102/Sourcemod-Plugins/tree/main/smd_advertisements",
    "smd_dynamichostname": "https://github.com/fbef0102/Sourcemod-Plugins/tree/main/smd_DynamicHostname",
    "cannounce": "https://github.com/fbef0102/Sourcemod-Plugins/tree/main/cannounce",
}
PLUGIN_EXTRA_REQUIRES = {
    "l4dinfectedbots": [
        ("spawn_infected_nolimit", SPAWN_INFECTED_NOLIMIT_URL),
        ("zombie_spawn_fix", ZOMBIE_SPAWN_FIX_URL),
        ("l4d_unrestrict_panic_battlefield", UNRESTRICT_PANIC_URL),
    ],
    "l4d2_vscript_purifier_v2": [
        ("l4d2_source_keyvalues", SOURCE_KEYVALUES_URL),
    ],
    "l4d2_vscript_purifier": [
        ("l4d2_source_keyvalues", SOURCE_KEYVALUES_URL),
    ],
}
PLUGIN_REQUIRED_GAMEDATA = {
    "l4d_use_priority": ("l4d_use_priority",),
    "use_priority": ("l4d_use_priority",),
}
AC_NAME_RE = re.compile(
    r"smac|anti[- ]?cheat|little[- ]?anti|sendfilefix|spray_exploit|"
    r"hackers_block|blocksmplugins|familyshare|vacbans|sv_protect_cvar|"
    r"block_packet",
    re.I,
)
MD_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$")
MD_ITEM_LINK_RE = re.compile(
    r"^(?:\*|[-+]|\d+\.)\s*(?:\((?P<tag>[^)]+)\)\s*)?\[(?P<name>[^\]]+)\]\((?P<url>[^)]+)\)(?P<rest>.*)$"
)


@dataclass
class RepoSpec:
    key: str
    git_url: str
    branch: str = "master"
    enabled: bool = True

    @property
    def url(self) -> str:
        return self.git_url

    @property
    def owner_name(self) -> tuple[str, str]:
        parsed = urlparse(self.git_url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) < 2:
            return "unknown", self.key
        owner, name = parts[0], parts[1]
        if name.endswith(".git"):
            name = name[:-4]
        return owner, name

    @property
    def name(self) -> str:
        return self.owner_name[1]

    @property
    def api(self) -> str:
        owner, name = self.owner_name
        return f"https://api.github.com/repos/{owner}/{name}"

    @property
    def html(self) -> str:
        owner, name = self.owner_name
        return f"https://github.com/{owner}/{name}"

    @property
    def cache(self) -> Path:
        return SCRIPT_DIR / ".cache" / self.name


DEFAULT_REPOS = [
    RepoSpec("l4d", "https://github.com/fbef0102/L4D1_2-Plugins.git", "master"),
    RepoSpec("sm", "https://github.com/fbef0102/Sourcemod-Plugins.git", "main"),
]
PRIVATE_REPO = RepoSpec("private", "https://github.com/fbef0102/Game-Private_Plugin.git", "main")
CATALOG_REPO = RepoSpec("catalog", "https://github.com/fbef0102/Game-Private_Plugin.git", "main")
PRIVATE_L4D_PREFIX = "L4D_插件/"
PRIVATE_README_CACHE = SCRIPT_DIR / ".cache" / "private_readmes"


@dataclass
class AppConfig:
    game_dir: Path | None
    repos: list[RepoSpec]
    disabled_repos: list[RepoSpec] = field(default_factory=list)

    def listed_repos(self) -> list[RepoSpec]:
        return list(self.repos) + list(self.disabled_repos)


_APP_CONFIG: AppConfig | None = None


@dataclass
class Requirement:
    name: str
    url: str = ""
    note: str = ""
    slug: str = ""


@dataclass
class RemotePlugin:
    name: str
    path: Path
    repo: RepoSpec
    smx_names: list[str] = field(default_factory=list)
    requires: list[Requirement] = field(default_factory=list)

    @property
    def keys(self) -> set[str]:
        out = {self.name.lower()}
        out.update(Path(n).stem.lower() for n in self.smx_names)
        return out


@dataclass
class LocalPlugin:
    name: str
    path: Path
    disabled: bool


@dataclass
class FileAction:
    src: Path
    dest: Path
    kind: str
    plugin: str


@dataclass
class CheckResult:
    ok: bool
    where: str


@dataclass
class FixItem:
    name: str
    url: str
    slug: str
    section: str
    category: str
    tag: str
    note: str
    games: set[str]
    oses: set[str]


@dataclass
class TutorialSpec:
    key: str
    title: str
    keep_title: str
    raw_url: str
    page_url: str
    keep_sections: tuple[str, ...] = ()
    skip_sections: tuple[str, ...] = ()
    use_fix_filters: bool = False


@dataclass
class LocalEnv:
    game_dir: Path
    plugins: list[LocalPlugin]
    plugin_names: set[str]
    includes: set[str]
    extensions: set[str]
    addon_names: set[str]
    has_metamod: bool
    has_sourcemod: bool

    def plugin(self, name: str) -> LocalPlugin | None:
        key = name.lower()
        enabled = None
        any_hit = None
        for p in self.plugins:
            if p.name.lower() == key:
                any_hit = p
                if not p.disabled:
                    enabled = p
        return enabled or any_hit


def default_config_text(game_dir: Path | None = None) -> str:
    path = game_dir or Path(r"D:\Steam\steamapps\common\Left 4 Dead 2\left4dead2")
    return (
        "# 求生之路2 插件同步配置（改完保存即可，双击 update_installed.bat 用菜单操作）\n"
        "#\n"
        "# game_dir 指向带 addons\\sourcemod 的 left4dead2 目录。\n"
        "# 写成上一级 “Left 4 Dead 2” 也可以，程序会自动进入 left4dead2。\n"
        "#\n"
        "# repo 一行一个，格式: 简称|git地址|分支\n"
        "# 未启用的仓库请行首加 #，或写成 简称|地址|分支|off\n"
        "# 未启用的仍显示在菜单「选择启用仓库」，可选中后单独使用；「全部」只含已启用的。\n"
        "#\n"
        f"game_dir = {path}\n"
        "\n"
        "repo = fbef0102|https://github.com/fbef0102/L4D1_2-Plugins.git|master\n"
        "repo = Sourcemod|https://github.com/fbef0102/Sourcemod-Plugins.git|main\n"
        "repo = Target5150|https://github.com/Target5150/MoYu_Server_Stupid_Plugins.git|master\n"
        "repo = Mineralcr|https://github.com/Mineralcr/L4D2_Public_Plugins.git|main\n"
        "repo = xiaolinRM|https://github.com/xiaolinRM/L4D2Plugins.git|main\n"
        "repo = SirPlease|https://github.com/SirPlease/L4D2-Competitive-Rework|master\n"
        "repo = blueblur0730|https://github.com/blueblur0730/modified-plugins.git|main\n"
        "repo = apples1949|https://github.com/apples1949/douban-l4d2-plugins-set.git|main\n"
        "repo = NanakaNeko|https://github.com/NanakaNeko/l4d2_plugins_coop|main\n"
        "repo = LuxLuma|https://github.com/LuxLuma/Left-4-fix|master\n"
        "repo = MatthewNeko|https://github.com/MatthewNeko/NekoSpecials-L4D2/|NS7-SM1.11+\n"
    )


def _repo_flag_enabled(flag: str) -> bool:
    text = (flag or "").strip().lower()
    if not text:
        return True
    return text not in {
        "0",
        "false",
        "off",
        "no",
        "n",
        "disable",
        "disabled",
        "未启用",
        "停用",
        "关闭",
    }


def parse_repo_value(val: str) -> RepoSpec:
    parts = [p.strip() for p in val.split("|")]
    if not parts or not parts[0]:
        raise ValueError(f"无效的 repo 行: {val}")
    enabled = True
    if len(parts) >= 4:
        enabled = _repo_flag_enabled(parts[3])
        parts = parts[:3]
    if len(parts) == 1:
        git_url = parts[0]
        name = Path(urlparse(git_url).path).name.removesuffix(".git")
        key = re.sub(r"[^a-z0-9]+", "", name.lower())[:16] or "repo"
        return RepoSpec(key, git_url, "", enabled)
    key, git_url = parts[0], parts[1]
    branch = parts[2] if len(parts) > 2 else ""
    return RepoSpec(key, git_url, branch, enabled)


def migrate_old_game_dir() -> Path | None:
    if not OLD_GAME_DIR_FILE.is_file():
        return None
    for raw in OLD_GAME_DIR_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip().strip('"').strip("'")
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            if key.strip().lower() in {"game_dir", "gamedir", "path"}:
                line = val.strip().strip('"').strip("'")
        if line:
            return Path(line)
    return None


def ensure_config_file() -> None:
    if CONFIG_FILE.is_file():
        return
    old = migrate_old_game_dir()
    CONFIG_FILE.write_text(default_config_text(old), encoding="utf-8")
    if OLD_GAME_DIR_FILE.is_file():
        try:
            OLD_GAME_DIR_FILE.unlink()
        except OSError:
            pass


def load_app_config() -> AppConfig:
    ensure_config_file()
    game_dir: Path | None = None
    repos: list[RepoSpec] = []
    disabled_repos: list[RepoSpec] = []
    for raw in CONFIG_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line:
            continue
        commented = re.match(r"^[#;]\s*repo\s*=\s*(.+)$", line, re.I)
        if commented:
            try:
                spec = parse_repo_value(commented.group(1).strip().strip('"').strip("'"))
                spec.enabled = False
                disabled_repos.append(spec)
            except ValueError:
                pass
            continue
        if line.startswith("#") or line.startswith(";"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key_raw = key.strip()
        if key_raw.startswith("#") or key_raw.startswith(";"):
            continue
        key_l = key_raw.lower()
        val = val.strip().strip('"').strip("'")
        if not val or val.startswith("#"):
            continue
        if key_l in {"game_dir", "gamedir", "path"}:
            game_dir = Path(val)
        elif key_l == "repo":
            spec = parse_repo_value(val)
            if spec.enabled:
                repos.append(spec)
            else:
                disabled_repos.append(spec)
    if not repos:
        repos = list(DEFAULT_REPOS)
    return AppConfig(game_dir=game_dir, repos=repos, disabled_repos=disabled_repos)


def format_repo_line(spec: RepoSpec, enabled: bool) -> str:
    if spec.branch:
        body = f"{spec.key}|{spec.git_url}|{spec.branch}"
    else:
        body = f"{spec.key}|{spec.git_url}"
    if enabled:
        return f"repo = {body}"
    return f"#repo = {body}"


def save_enabled_repos(enabled_keys: set[str]) -> None:
    want = {k.lower() for k in enabled_keys}
    raw_text = CONFIG_FILE.read_text(encoding="utf-8-sig")
    newline = "\r\n" if "\r\n" in raw_text else "\n"
    out: list[str] = []
    for raw in raw_text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        m = re.match(r"^[#;]?\s*repo\s*=\s*(.+)$", line, re.I)
        if not m:
            out.append(raw)
            continue
        try:
            spec = parse_repo_value(m.group(1).strip().strip('"').strip("'"))
        except ValueError:
            out.append(raw)
            continue
        indent = raw[: len(raw) - len(raw.lstrip())]
        enabled = spec.key.lower() in want
        out.append(indent + format_repo_line(spec, enabled))
    CONFIG_FILE.write_text(newline.join(out) + newline, encoding="utf-8")


def get_config(reload: bool = False) -> AppConfig:
    global _APP_CONFIG
    if _APP_CONFIG is None or reload:
        _APP_CONFIG = load_app_config()
    return _APP_CONFIG


def normalize_game_dir(path: Path) -> Path:
    path = path.expanduser()
    try:
        path = path.resolve()
    except OSError:
        return path
    if (path / "addons" / "sourcemod").is_dir():
        return path
    nested = path / "left4dead2"
    if (nested / "addons" / "sourcemod").is_dir():
        return nested
    if nested.is_dir() and not (path / "addons").is_dir():
        return nested
    return path


def default_game_dir() -> Path:
    env = os.environ.get("L4D2_GAME_DIR", "").strip().strip('"')
    if env:
        return normalize_game_dir(Path(env))
    cfg = get_config().game_dir
    if cfg:
        return normalize_game_dir(cfg)
    candidate = SCRIPT_DIR.parent / "left4dead2"
    if (candidate / "addons" / "sourcemod").is_dir():
        return candidate
    cwd = Path.cwd()
    for p in (cwd, cwd / "left4dead2", cwd.parent / "left4dead2"):
        if (p / "addons" / "sourcemod").is_dir():
            return p
    return candidate


def sm_root(game_dir: Path) -> Path:
    return game_dir / "addons" / "sourcemod"


def looks_like_l4d2_dir(game_dir: Path) -> bool:
    if game_dir.name.lower() == "left4dead2":
        return True
    return any(
        (game_dir / name).exists()
        for name in ("gameinfo.txt", "steam.inf", "left4dead2.exe", "left4dead2.dll")
    )


def ensure_game_addons(game_dir: Path, *, announce_full_install: bool = True) -> bool:
    addons = game_dir / "addons"
    if addons.is_dir():
        return False
    addons.mkdir(parents=True, exist_ok=True)
    print(f"未找到 addons 文件夹，已创建: {addons}")
    if announce_full_install:
        print("将安装全部基础依赖环境。")
    return True


def log_failure(title: str, detail: str = "", url: str = "") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{ts}] {title}"]
    text = str(detail).strip()
    if text:
        for row in text.splitlines():
            lines.append(f"  {row}")
    if url:
        lines.append(f"  {url}")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# 本进程会话内已同步的仓库/依赖缓存，避免菜单反复操作打爆 GitHub / AlliedMods
_SESSION_SYNCED_REPOS: set[str] = set()
_SESSION_REPO_META: dict[str, dict] = {}
_SESSION_DEP_SYNCED: set[str] = set()
_SESSION_HTTP_JSON: dict[str, dict | list] = {}
_SESSION_AM_BODIES: dict[str, bytes] = {}


def _repo_session_key(repo: RepoSpec) -> str:
    # 用缓存目录作键（勿含可变 branch，避免 meta 改分支后重复 fetch）
    return str(repo.cache.resolve()) if repo.cache.exists() else str(repo.cache)


def github_headers() -> dict[str, str]:
    headers = {
        "User-Agent": "l4d2-plugin-updater",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def http_json(url: str, *, fatal: bool = True) -> dict | list:
    cached = _SESSION_HTTP_JSON.get(url)
    if cached is not None:
        return cached
    req = urllib.request.Request(url, headers=github_headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            _SESSION_HTTP_JSON[url] = data
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        err = RuntimeError(f"GitHub API 请求失败 {e.code}: {url}\n{body}")
        if fatal:
            raise SystemExit(str(err)) from e
        raise err from e


def fetch_repo_meta(repo: RepoSpec) -> dict:
    key = f"{repo.api}|{repo.branch or ''}"
    cached = _SESSION_REPO_META.get(key)
    if cached is not None:
        repo.branch = cached.get("default_branch") or repo.branch
        return cached
    data = http_json(repo.api)
    repo.branch = data.get("default_branch") or repo.branch
    commits = http_json(f"{repo.api}/commits/{repo.branch}")
    meta = {
        "full_name": data.get("full_name"),
        "html_url": data.get("html_url"),
        "updated_at": data.get("updated_at"),
        "default_branch": data.get("default_branch") or repo.branch,
        "sha": commits.get("sha", "")[:12],
        "commit_date": ((commits.get("commit") or {}).get("committer") or {}).get("date", ""),
        "commit_message": ((commits.get("commit") or {}).get("message") or "").splitlines()[0],
    }
    _SESSION_REPO_META[key] = meta
    # default_branch 可能变了，用最终分支再记一份
    _SESSION_REPO_META[f"{repo.api}|{repo.branch or ''}"] = meta
    return meta


_DETECTED_PROXY: str | None = None
_GIT_PROXY_LOGGED = False


def _normalize_proxy_url(raw: str, socks: bool = False) -> str:
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return ""
    text = text.split()[0]
    if "://" not in text:
        scheme = "socks5" if socks else "http"
        text = f"{scheme}://{text.lstrip('/')}"
    return text


def _parse_windows_proxy_server(server: str) -> str:
    text = (server or "").strip()
    if not text:
        return ""
    if "=" not in text and ";" not in text:
        socks = text.lower().startswith("socks")
        return _normalize_proxy_url(text, socks=socks)
    parts: dict[str, str] = {}
    for chunk in text.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            kind, _, addr = chunk.partition("=")
            parts[kind.strip().lower()] = addr.strip()
        else:
            parts.setdefault("http", chunk)
    for key in ("https", "http"):
        if parts.get(key):
            return _normalize_proxy_url(parts[key], socks=False)
    if parts.get("socks"):
        return _normalize_proxy_url(parts["socks"], socks=True)
    return ""


def _windows_internet_proxy() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
            if not enable:
                return ""
            server, _ = winreg.QueryValueEx(key, "ProxyServer")
            return _parse_windows_proxy_server(str(server or ""))
    except OSError:
        return ""


def _winhttp_proxy() -> str:
    if sys.platform != "win32":
        return ""
    try:
        result = subprocess.run(
            ["netsh", "winhttp", "show", "proxy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
    except Exception:
        return ""
    text = result.stdout or ""
    m = re.search(r"Proxy Server\(s\)?:\s*(.+)", text, re.I)
    if not m:
        return ""
    server = m.group(1).strip()
    if not server or "direct" in server.lower() or server.lower() == "none":
        return ""
    return _parse_windows_proxy_server(server.split()[0])


def _git_config_proxy() -> str:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "http.proxy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
    except Exception:
        return ""
    return _normalize_proxy_url((result.stdout or "").strip())


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _listening_local_proxy() -> str:
    # V2RayN HTTP 混合口、Clash、SOCKS 常见端口
    http_ports = (10809, 7890, 7897, 20171, 6152, 8889, 1081)
    socks_ports = (10808, 1080, 7891)
    for port in http_ports:
        if _port_open("127.0.0.1", port):
            return f"http://127.0.0.1:{port}"
    for port in socks_ports:
        if _port_open("127.0.0.1", port):
            return f"socks5://127.0.0.1:{port}"
    return ""


def detect_local_proxy() -> str:
    global _DETECTED_PROXY
    if _DETECTED_PROXY is not None:
        return _DETECTED_PROXY
    env = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("ALL_PROXY")
        or os.environ.get("all_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
    urllib_proxies = urllib.request.getproxies()
    urllib_proxy = (urllib_proxies.get("https") or urllib_proxies.get("http") or "").strip()
    candidates = [
        _normalize_proxy_url(env),
        _git_config_proxy(),
        _windows_internet_proxy(),
        _normalize_proxy_url(urllib_proxy),
        _winhttp_proxy(),
        _listening_local_proxy(),
    ]
    proxy = next((p for p in candidates if p), "")
    _DETECTED_PROXY = proxy
    return proxy


def git_proxy_attempts() -> list[tuple[str, list[str], dict[str, str]]]:
    """默认先走本机代理，失败再直连。"""
    attempts: list[tuple[str, list[str], dict[str, str]]] = []
    proxy = detect_local_proxy()
    if proxy:
        args = ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
        env = {
            "HTTP_PROXY": proxy,
            "HTTPS_PROXY": proxy,
            "ALL_PROXY": proxy,
            "http_proxy": proxy,
            "https_proxy": proxy,
            "all_proxy": proxy,
        }
        attempts.append((proxy, args, env))
    attempts.append(("", [], {}))
    return attempts


def run_git(args: list[str], cwd: Path | None = None) -> None:
    global _GIT_PROXY_LOGGED
    last = ""
    for proxy, prefix, extra_env in git_proxy_attempts():
        if proxy and not _GIT_PROXY_LOGGED:
            print(f"Git 使用本机代理: {proxy}")
            _GIT_PROXY_LOGGED = True
        elif not proxy and not _GIT_PROXY_LOGGED:
            print("未检测到本机代理，Git 直连。")
            _GIT_PROXY_LOGGED = True
        env = os.environ.copy()
        env.update(extra_env)
        cmd = ["git", *prefix, *args]
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if result.returncode == 0:
            return
        last = (result.stderr or result.stdout or "").strip()
        if proxy:
            print("代理拉取失败，改为直连重试。")
    raise RuntimeError("git 命令失败: git " + " ".join(args) + "\n" + last)


def cache_has_plugins(cache: Path) -> bool:
    if not cache.is_dir():
        return False
    for child in cache.iterdir():
        if child.name.startswith("."):
            continue
        if child.is_dir():
            return True
    return False


def sync_cache(repo: RepoSpec, force: bool = False) -> Path:
    cache = repo.cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    key = _repo_session_key(repo)
    if not force and key in _SESSION_SYNCED_REPOS and (
        (cache / ".git").is_dir() or cache_has_plugins(cache)
    ):
        print(f"本会话已同步，跳过更新: {repo.key}")
        return cache
    if (cache / ".git").is_dir():
        print(f"正在更新本地缓存: {cache}")
        fetch_args = ["fetch", "--depth", "1", "origin"]
        if repo.branch:
            fetch_args.append(repo.branch)
        try:
            run_git(fetch_args, cwd=cache)
            ref = f"origin/{repo.branch}" if repo.branch else "FETCH_HEAD"
            run_git(["reset", "--hard", ref], cwd=cache)
            run_git(["clean", "-fd"], cwd=cache)
        except Exception as e:
            if cache_has_plugins(cache):
                print("在线更新失败，改用本地已有缓存继续（内容可能不是最新）。")
                err = str(e).strip().splitlines()[-1]
                if err:
                    print(f"  {err}")
                _SESSION_SYNCED_REPOS.add(key)
                return cache
            raise
    else:
        if cache.exists() and force:
            shutil.rmtree(cache)
            _SESSION_SYNCED_REPOS.discard(key)
        print(f"正在克隆仓库到缓存: {repo.url}")
        args = ["clone", "--depth", "1"]
        if repo.branch:
            args += ["--branch", repo.branch]
        args += [repo.url, str(cache)]
        run_git(args)
    _SESSION_SYNCED_REPOS.add(key)
    return cache


def collect_smx(folder: Path) -> list[str]:
    names: list[str] = []
    plugins_dir = folder / "plugins"
    search_roots = [plugins_dir] if plugins_dir.is_dir() else []
    search_roots.append(folder)
    seen: set[str] = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        for smx in root.rglob("*.smx"):
            key = smx.name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(smx.name)
    return names


def find_readme(folder: Path) -> Path | None:
    for name in ("readme.md", "README.md", "Readme.md"):
        p = folder / name
        if p.is_file():
            return p
    return None


def slug_from_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("/"):
        return unquote(url.strip("/").split("/")[0])
    parsed = urlparse(url)
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    if "releases" in parts:
        return ""
    if "showthread.php" in parts[-1].lower():
        return ""
    last = parts[-1]
    if last.startswith("#"):
        return ""
    last = last.split("#")[0]
    if last.lower() in {"english", "server", "install_other_file", "tree", "main", "master"}:
        return ""
    return last


def normalize_key(name: str) -> str:
    text = name.strip()
    text = re.sub(r"^\[INC\]\s*", "", text, flags=re.I)
    text = text.replace("[INC]", "")
    text = re.sub(r"[\[\]()`]", "", text)
    text = text.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_require_item(raw: str) -> Requirement | None:
    raw = raw.strip().replace("<br/>", " ").replace("<br>", " ")
    raw = re.sub(r"<[^>]+>", "", raw).strip()
    if normalize_key(raw) in NONE_TOKENS:
        return None
    url = ""
    note = ""
    name = raw
    m = MD_LINK_RE.search(raw)
    if m:
        name, url = m.group(1).strip(), m.group(2).strip()
        suffix = raw[m.end() :].strip(" :：-")
        if suffix:
            note = suffix
    else:
        # 不要把 https:// 里的冒号当成备注分隔符
        m2 = re.match(r"^(.+?)\s*[:：]\s+(.*)$", raw)
        if m2 and "://" not in m2.group(1):
            name, note = m2.group(1).strip(), m2.group(2).strip()
    slug = slug_from_url(url)
    if not slug:
        slug = re.sub(r"^\[INC\]\s*", "", name, flags=re.I)
        slug = re.sub(r"[^\w.\-]+", "_", slug).strip("_")
    if normalize_key(name) in NONE_TOKENS:
        return None
    return Requirement(name=name, url=url, note=note, slug=slug)


def _plain_text(line: str) -> str:
    text = line.replace("<br/>", " ").replace("<br>", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_requires(readme: Path) -> list[Requirement]:
    items: list[Requirement] = []
    in_section = False
    numbered = re.compile(r"^(\d+)\.\s+(.+)$")
    for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        text = _plain_text(line)
        hm = REQUIRE_HEAD_RE.match(text) if indent == 0 else None
        if hm:
            in_section = True
            leftover = (hm.group(2) or "").strip()
            leftover = re.sub(r"^[:：]\s*", "", leftover).strip()
            if leftover and normalize_key(leftover) in NONE_TOKENS:
                break
            if leftover:
                for part in re.split(r"[,，;；]+", leftover):
                    item = parse_require_item(part)
                    if item:
                        items.append(item)
            continue
        if not in_section:
            continue
        if indent == 0:
            break
        m = numbered.match(text)
        if m:
            item = parse_require_item(m.group(2))
            if item:
                items.append(item)
        elif normalize_key(text) in NONE_TOKENS:
            break
    return items


def rewrite_relative_require_urls(requires: list[Requirement], repo: RepoSpec | None) -> list[Requirement]:
    if not repo:
        return requires
    owner, name = repo.owner_name
    if owner == "unknown":
        m = GITHUB_REPO_RE.search(repo.url or "")
        if not m:
            return requires
        owner, name = m.group(1), m.group(2)
        if name.lower().endswith(".git"):
            name = name[:-4]
    branch = repo.branch or "master"
    for req in requires:
        url = (req.url or "").strip()
        if url.startswith("/") and "://" not in url:
            req.url = f"https://github.com/{owner}/{name}/tree/{branch}/{url.lstrip('/')}"
    return requires


def apply_require_url_overrides(requires: list[Requirement]) -> list[Requirement]:
    for req in requires:
        forced = forced_am_sp_url(req.name, req.slug, req.url)
        if forced:
            req.url = forced
            continue
        key = dep_merge_key(req)
        slug = (req.slug or "").lower().replace("-", "_")
        if key in REQUIRE_INSTALL_URLS:
            req.url = REQUIRE_INSTALL_URLS[key]
        elif slug in REQUIRE_INSTALL_URLS:
            req.url = REQUIRE_INSTALL_URLS[slug]
    return requires


def augment_plugin_requires(
    plugin_name: str,
    requires: list[Requirement],
    repo: RepoSpec | None = None,
) -> list[Requirement]:
    requires = rewrite_relative_require_urls(list(requires), repo)
    requires = apply_require_url_overrides(requires)
    have = {dep_merge_key(r) for r in requires}
    have |= {(r.slug or "").lower().replace("-", "_") for r in requires}
    have |= {normalize_key(r.name).replace(" ", "_") for r in requires}
    for name, url in PLUGIN_EXTRA_REQUIRES.get(plugin_name.lower(), []):
        if name in have:
            continue
        requires.append(Requirement(name=name, url=url, slug=name))
    return apply_require_url_overrides(requires)


PACK_SKIP_NAMES = {
    "sourcemod",
    "addons",
    "left4dead2",
    "plugins",
    "scripting",
    "cfg",
    "configs",
    "gamedata",
    "translations",
    "extensions",
    "data",
    "bin",
}

SM_CONTENT_DIRS = (
    "plugins",
    "scripting",
    "gamedata",
    "configs",
    "data",
    "extensions",
    "translations",
)

STOCK_SM_STEMS = {
    "admin-flatfile",
    "adminhelp",
    "adminmenu",
    "antiflood",
    "basebans",
    "basechat",
    "basecomm",
    "basecommands",
    "basetriggers",
    "basevotes",
    "clientprefs",
    "funcommands",
    "funvotes",
    "playercommands",
    "reservedslots",
    "sounds",
    "admin-sql-prefetch",
    "admin-sql-threaded",
    "mapchooser",
    "nominations",
    "randomcycle",
    "rockthevote",
    "sql-admin-manager",
}

HELPER_SM_STEMS = {
    "lmccore",
    "colors",
    "localizer",
    "left4dhooks_test",
}

DOUBAN_FOLDER_RE = re.compile(r"^(必选|可选|自选)[-_]")
PLATFORM_FOLDER_RE = re.compile(r"插件平台|sourcemod.*platform|1\.1[12]插件", re.I)
EN_FOLDER_TOKEN_RE = re.compile(r"\(([A-Za-z][A-Za-z0-9_+\-]*(?:\.[A-Za-z0-9]+)?)\)")
VERSION_TOKEN_RE = re.compile(r"^v?\d+(?:\.\d+)*[a-z]?$", re.I)


def sourcemod_has_content(sm: Path) -> bool:
    if not sm.is_dir():
        return False
    if any(sm.glob("*.smx")):
        return True
    return any((sm / name).is_dir() for name in SM_CONTENT_DIRS)


def looks_like_plugin(folder: Path) -> bool:
    if folder.name.lower() in PACK_SKIP_NAMES:
        return False
    game = folder / "left4dead2"
    if game.is_dir():
        if sourcemod_has_content(game / "addons" / "sourcemod"):
            return True
        addons = game / "addons"
        if addons.is_dir():
            if (addons / "metamod").is_dir() or (addons / "stripper").is_dir():
                return True
            if any(addons.glob("*.vpk")) or any(addons.glob("*.vdf")) or any(
                addons.glob("*.dll")
            ) or any(addons.glob("*.so")):
                return True
        cfg = game / "cfg"
        if cfg.is_dir() and any(cfg.rglob("*.cfg")):
            return True
    if sourcemod_has_content(folder / "addons" / "sourcemod"):
        return True
    if (folder / "addons" / "sourcemod" / "plugins").is_dir():
        return True
    if (folder / "plugins").is_dir():
        return True
    if any(folder.glob("*.smx")) or any(folder.glob("plugins/*.smx")):
        return True
    scripting = folder / "scripting"
    if scripting.is_dir() and any(scripting.glob("*.sp")):
        return True
    return find_readme(folder) is not None and (
        (folder / "gamedata").is_dir() or (folder / "translations").is_dir()
    )


def plugin_content_root(path: Path) -> Path:
    if path.is_file():
        return path
    for cand in (
        path / "left4dead2" / "addons" / "sourcemod",
        path / "addons" / "sourcemod",
        path,
    ):
        if sourcemod_has_content(cand):
            return cand
    return path


def pack_folder_note(folder_name: str) -> str:
    text = folder_name.strip()
    # 豆瓣酱 JS-MODS：保留完整目录名（含必选/可选/自选），供列表展示
    if DOUBAN_FOLDER_RE.match(text) or PLATFORM_FOLDER_RE.search(text):
        return text
    text = re.sub(r"^(自选|必备|推荐|必选|可选)[-_]", "", text)
    # 去掉成对括号；嵌套括号用重复扫描
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\([^()]*\)", "", text)
    text = re.sub(r"\s+", " ", text).strip("-_ ")
    if len(text) > 40:
        text = text[:40].rstrip() + "…"
    return text or folder_name


def pack_category_rank(folder_or_name: str) -> int:
    """Sort key: 平台 → 必选 → 可选 → 自选 → 其它。"""
    text = (folder_or_name or "").strip()
    if PLATFORM_FOLDER_RE.search(text) or text.lower().startswith("1.12"):
        return 0
    if text.startswith("必选"):
        return 1
    if text.startswith("可选"):
        return 2
    if text.startswith("自选"):
        return 3
    return 4


def _is_english_plugin_id(token: str) -> bool:
    t = (token or "").strip()
    if not t or VERSION_TOKEN_RE.match(t):
        return False
    low = t.lower()
    if low in {
        "lux",
        "harry",
        "harrypotter",
        "silvershot",
        "sorallll",
        "fdxx",
        "lakwsh",
        "mart",
        "visor",
        "bullet28",
        "forgetest",
        "psykoitik",
        "psykotik",
        "crasher_3637",
    }:
        return False
    if low.endswith(".ext"):
        return True
    if "_" in t or t.lower().startswith(("l4d", "sm_", "ps_", "lmc")):
        return True
    # CamelCase plugin ids like WeaponHandling / Defib_Fix already handled; bare words are usually authors
    return bool(re.fullmatch(r"[A-Z][A-Za-z0-9]+", t)) and len(t) >= 6


def _stems_from_sm_dir(root: Path, sub: str, suffix: str) -> list[str]:
    folder = root / sub
    if not folder.is_dir():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for f in sorted(folder.rglob(f"*{suffix}")):
        if not f.is_file():
            continue
        stem = f.stem
        key = stem.lower()
        if key in seen or key.endswith("_test") or key.endswith(".games"):
            continue
        if sub == "gamedata" and key.endswith(".games"):
            continue
        seen.add(key)
        out.append(stem)
    return out


def _ascii_mod_stem(name: str) -> str:
    text = re.sub(r"[^\w]+", "_", name).strip("_")
    if text and not any("\u4e00" <= c <= "\u9fff" for c in text):
        return text
    return "lobby_8player_mod"


def derive_plugin_english_name(folder: Path, smx_names: list[str]) -> str:
    """Prefer a stable English plugin id over Chinese JS-MODS folder titles."""
    folder_name = folder.name if folder.is_dir() else folder.stem
    if PLATFORM_FOLDER_RE.search(folder_name):
        os_tag = "linux" if "linux" in folder_name.lower() else "windows"
        return f"sourcemod_platform_{os_tag}"

    root = plugin_content_root(folder)
    smx_stems = [Path(n).stem for n in smx_names]
    primary = [s for s in smx_stems if s.lower() not in STOCK_SM_STEMS]
    primary = [s for s in primary if s.lower() not in HELPER_SM_STEMS] or primary
    if len(primary) == 1:
        return primary[0]
    if len(primary) > 1:
        return "+".join(sorted(primary, key=str.lower))

    for stem in _stems_from_sm_dir(root, "scripting", ".sp"):
        if stem.lower() in STOCK_SM_STEMS or stem.lower() in HELPER_SM_STEMS:
            continue
        return stem

    gd = _stems_from_sm_dir(root, "gamedata", ".txt")
    gd = [s for s in gd if not s.lower().endswith((".games", "_sig"))]
    cfg_root = root / "configs" / "sourcescramble"
    if cfg_root.is_dir():
        for f in sorted(cfg_root.glob("*.txt")):
            if f.stem.lower() not in {x.lower() for x in gd}:
                gd.append(f.stem)
    if len(gd) == 1:
        return gd[0]
    if len(gd) > 1:
        return "+".join(sorted(gd, key=str.lower))

    # CFG / MOD / extension packs（先于括号作者名）
    game = folder / "left4dead2"
    if game.is_dir():
        addons = game / "addons"
        if addons.is_dir():
            if list(addons.glob("l4dtoolz.*")):
                return "l4dtoolz"
            if (addons / "stripper").is_dir():
                return "stripper"
            if (addons / "metamod").is_dir():
                return "metamod"
            vpks = sorted(addons.glob("*.vpk"))
            if vpks:
                stem = Path(vpks[0].name).stem
                if any("\u4e00" <= c <= "\u9fff" for c in stem):
                    return _ascii_mod_stem(stem)
                return stem
        cfg = game / "cfg"
        if cfg.is_dir():
            cfgs = sorted(p.stem for p in cfg.rglob("*.cfg") if p.is_file())
            if len(cfgs) == 1:
                return cfgs[0]
            if cfgs:
                return "+".join(cfgs)

    for tok in EN_FOLDER_TOKEN_RE.findall(folder_name):
        if _is_english_plugin_id(tok):
            return Path(tok).stem

    if smx_stems:
        return smx_stems[0]
    return folder_name


NEST_SKIP_DIRS = SKIP_REPO_ROOT_DIRS | {
    "image",
    "images",
    "include",
    "addons",
    "sourcemod",
    "cfg",
    "configs",
    "materials",
    "models",
    "sound",
    "sounds",
    "particles",
    "scripting_1.11",
    "scripting_1.12",
}


def iter_plugin_dirs(root: Path, *, deep: bool) -> list[Path]:
    found: list[Path] = []
    max_depth = 4 if deep else 1

    def walk(folder: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            children = sorted(folder.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name.lower() in NEST_SKIP_DIRS:
                continue
            if looks_like_plugin(child):
                found.append(child)
                continue
            if deep:
                walk(child, depth + 1)

    walk(root, 1)
    return found


def scan_flat_sm_plugins(repo: RepoSpec) -> list[RemotePlugin]:
    plugins: list[RemotePlugin] = []
    seen: set[str] = set()
    files: list[Path] = []
    for sm in (
        repo.cache / "addons" / "sourcemod",
        repo.cache / "left4dead2" / "addons" / "sourcemod",
        repo.cache,
    ):
        pdir = sm / "plugins"
        if not pdir.is_dir():
            continue
        files.extend(pdir.glob("*.smx"))
        for sub in ("optional", "disabled"):
            extra = pdir / sub
            if extra.is_dir():
                files.extend(extra.glob("*.smx"))
    root_scripting = repo.cache / "scripting"
    if root_scripting.is_dir() and not (repo.cache / "addons" / "sourcemod").is_dir():
        files.extend(root_scripting.glob("*.sp"))
    for src in sorted(files, key=lambda p: p.name.lower()):
        stem = src.stem
        key = stem.lower()
        if key in seen:
            continue
        seen.add(key)
        smx_names = [src.name] if src.suffix.lower() == ".smx" else []
        plugins.append(
            RemotePlugin(
                name=stem,
                path=src,
                repo=repo,
                smx_names=smx_names,
            )
        )
    return plugins


def scan_remote_plugins(repo: RepoSpec, *, deep: bool = True) -> list[RemotePlugin]:
    plugins: list[RemotePlugin] = []
    if not repo.cache.is_dir():
        return plugins
    seen: set[str] = set()
    for child in iter_plugin_dirs(repo.cache, deep=deep):
        root = plugin_content_root(child)
        smx_names = collect_smx(root)
        # Also collect smx under left4dead2 tree when content_root fell back
        if not smx_names and (child / "left4dead2").is_dir():
            smx_names = collect_smx(child / "left4dead2" / "addons" / "sourcemod")
        name = derive_plugin_english_name(child, smx_names)
        readme = find_readme(child) or find_readme(root)
        requires = parse_requires(readme) if readme else []
        requires = augment_plugin_requires(name, requires, repo)
        plugins.append(
            RemotePlugin(
                name=name,
                path=child,
                repo=repo,
                smx_names=smx_names,
                requires=requires,
            )
        )
        seen.add(name.lower())
        seen.add(child.name.lower())
        for smx in smx_names:
            seen.add(Path(smx).stem.lower())
    for rp in scan_flat_sm_plugins(repo):
        if rp.name.lower() in seen:
            continue
        plugins.append(rp)
        seen.add(rp.name.lower())
    plugins.sort(
        key=lambda rp: (
            pack_category_rank(rp.path.name if rp.path.is_dir() else rp.name),
            rp.name.lower(),
        )
    )
    return plugins


def _github_tree_main(owner_repo: str) -> list[dict]:
    owner, name = owner_repo.split("/", 1)
    cache = SCRIPT_DIR / ".cache" / f"{owner}_{name}_tree.json"
    if cache.is_file() and time.time() - cache.stat().st_mtime < 86400:
        try:
            return json.loads(cache.read_text(encoding="utf-8")).get("tree") or []
        except Exception:
            pass
    data = http_json(f"https://api.github.com/repos/{owner}/{name}/git/trees/main?recursive=1")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data.get("tree") or [] if isinstance(data, dict) else []


def _fetch_private_readme(rel: str) -> Path:
    dest = PRIVATE_README_CACHE / rel.replace("/", "__")
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = "https://raw.githubusercontent.com/fbef0102/Game-Private_Plugin/main/" + quote(rel, safe="/")
    write_bytes(dest, http_bytes(url))
    return dest


def load_private_l4d_plugins() -> list[RemotePlugin]:
    print("正在读取 Game-Private_Plugin / L4D_插件 全部 Require …")
    tree = _github_tree_main("fbef0102/Game-Private_Plugin")
    grouped: dict[str, dict] = {}
    for item in tree:
        path = str(item.get("path") or "")
        if not path.startswith(PRIVATE_L4D_PREFIX):
            continue
        parts = path.split("/")
        if len(parts) < 3:
            continue
        cat, name = parts[1], parts[2]
        if name.lower().startswith("require"):
            continue
        key = f"{cat}/{name}"
        row = grouped.setdefault(key, {"name": name, "smx": [], "readme": ""})
        fname = parts[-1]
        if item.get("type") == "blob" and fname.lower().endswith(".smx"):
            row["smx"].append(fname)
        if item.get("type") == "blob" and fname.lower() in {"readme.md", "readme.txt"}:
            row["readme"] = path
    plugins: list[RemotePlugin] = []
    for _key, row in sorted(grouped.items()):
        requires: list[Requirement] = []
        if row["readme"]:
            try:
                requires = parse_requires(_fetch_private_readme(row["readme"]))
            except Exception as e:
                print(f"  读取 {row['name']} Require 失败: {e}")
        requires = augment_plugin_requires(row["name"], requires, PRIVATE_REPO)
        plugins.append(
            RemotePlugin(
                name=row["name"],
                path=PRIVATE_README_CACHE / row["name"],
                repo=PRIVATE_REPO,
                smx_names=row["smx"],
                requires=requires,
            )
        )
    print(f"已解析 {len(plugins)} 个私有插件的 Require")
    return plugins


def scan_local_plugins(game_dir: Path) -> list[LocalPlugin]:
    plugins_dir = sm_root(game_dir) / "plugins"
    if not plugins_dir.is_dir():
        return []
    found: list[LocalPlugin] = []
    for smx in plugins_dir.rglob("*.smx"):
        disabled = "disabled" in [p.lower() for p in smx.relative_to(plugins_dir).parts[:-1]]
        found.append(LocalPlugin(name=smx.stem, path=smx, disabled=disabled))
    found.sort(key=lambda x: x.name.lower())
    return found


def scan_local_env(game_dir: Path) -> LocalEnv:
    sm = sm_root(game_dir)
    addons = game_dir / "addons"
    plugins = scan_local_plugins(game_dir)
    plugin_names = {p.name.lower() for p in plugins}

    includes: set[str] = set()
    inc_dir = sm / "scripting" / "include"
    if inc_dir.is_dir():
        for p in inc_dir.rglob("*"):
            includes.add(p.name.lower())
            includes.add(p.stem.lower())

    extensions: set[str] = set()
    ext_dir = sm / "extensions"
    if ext_dir.is_dir():
        for p in ext_dir.rglob("*"):
            if p.is_file():
                extensions.add(p.name.lower())
                extensions.add(p.name.split(".")[0].lower())

    addon_names: set[str] = set()
    if addons.is_dir():
        for p in addons.iterdir():
            addon_names.add(p.name.lower())
            addon_names.add(p.stem.lower())

    return LocalEnv(
        game_dir=game_dir,
        plugins=plugins,
        plugin_names=plugin_names,
        includes=includes,
        extensions=extensions,
        addon_names=addon_names,
        has_metamod=(addons / "metamod.vdf").is_file() or (addons / "metamod").is_dir(),
        has_sourcemod=sm.is_dir(),
    )


def match_plugins(
    remote: list[RemotePlugin], local: list[LocalPlugin]
) -> tuple[list[tuple[RemotePlugin, list[LocalPlugin]]], list[RemotePlugin], list[LocalPlugin]]:
    local_by_name: dict[str, list[LocalPlugin]] = {}
    for lp in local:
        local_by_name.setdefault(lp.name.lower(), []).append(lp)

    matched: list[tuple[RemotePlugin, list[LocalPlugin]]] = []
    used_local: set[str] = set()
    for rp in remote:
        hits: list[LocalPlugin] = []
        for key in rp.keys:
            for lp in local_by_name.get(key, []):
                if lp.path.resolve() not in {h.path.resolve() for h in hits}:
                    hits.append(lp)
                    used_local.add(str(lp.path.resolve()))
        if hits:
            matched.append((rp, hits))

    matched_names = {m[0].name.lower() for m in matched}
    remote_only = [rp for rp in remote if rp.name.lower() not in matched_names]
    local_only = [lp for lp in local if str(lp.path.resolve()) not in used_local]
    return matched, remote_only, local_only


def iter_flat_plugin_files(plugin: RemotePlugin) -> list[tuple[Path, str, Path]]:
    src = plugin.path
    stem = src.stem
    results: list[tuple[Path, str, Path]] = []
    suffix = src.suffix.lower()
    parent = src.parent
    if suffix == ".smx":
        results.append((src, "plugins", Path(src.name)))
        sm = parent.parent if parent.name.lower() == "plugins" else parent
    else:
        results.append((src, "scripting", Path(src.name)))
        sm = parent.parent if parent.name.lower() == "scripting" else parent
    extras = [
        (sm / "scripting" / f"{stem}.sp", "scripting", Path(f"{stem}.sp")),
        (sm / "gamedata" / f"{stem}.txt", "gamedata", Path(f"{stem}.txt")),
        (sm / "translations" / f"{stem}.phrases.txt", "translations", Path(f"{stem}.phrases.txt")),
        (sm / "translations" / f"{stem}.txt", "translations", Path(f"{stem}.txt")),
    ]
    seen = {src.resolve()}
    for file, mapped, rel in extras:
        if not file.is_file():
            continue
        try:
            key = file.resolve()
        except OSError:
            key = file
        if key in seen:
            continue
        seen.add(key)
        results.append((file, mapped, rel))
    return results


def _append_sm_tree_files(sm_root_dir: Path, results: list[tuple[Path, str, Path]]) -> None:
    if not sm_root_dir.is_dir():
        return
    for child in sm_root_dir.iterdir():
        name = child.name.lower()
        if name in SKIP_TOP_DIRS or name in SKIP_FILE_NAMES:
            continue
        if child.is_file():
            suffix = child.suffix.lower()
            if suffix == ".sp":
                results.append((child, "scripting", Path(child.name)))
            elif suffix == ".smx":
                results.append((child, "plugins", Path(child.name)))
            elif suffix == ".inc":
                results.append((child, "scripting", Path("include") / child.name))
            elif suffix == ".txt":
                try:
                    head = child.read_bytes()[:4000]
                except OSError:
                    continue
                if looks_like_gamedata(head):
                    results.append((child, "gamedata", Path(child.name)))
            continue
        if name in SM_DIR_MAP:
            mapped = SM_DIR_MAP[name]
            for file in child.rglob("*"):
                if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                    results.append((file, mapped, file.relative_to(child)))
        elif name in GAME_DIR_MAP:
            mapped = GAME_DIR_MAP[name]
            for file in child.rglob("*"):
                if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                    results.append((file, f"game:{mapped}", file.relative_to(child)))


def iter_game_tree_plugin_files(pack: Path, game_tree: Path) -> list[tuple[Path, str, Path]]:
    """JS-MODS / release packs shaped as left4dead2/{addons,cfg}/..."""
    results: list[tuple[Path, str, Path]] = []
    sm = game_tree / "addons" / "sourcemod"
    _append_sm_tree_files(sm, results)
    cfg = game_tree / "cfg"
    if cfg.is_dir():
        for file in cfg.rglob("*"):
            if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                results.append((file, "game:cfg", file.relative_to(cfg)))
    addons = game_tree / "addons"
    if addons.is_dir():
        for child in addons.iterdir():
            if child.name.lower() == "sourcemod":
                continue
            if child.is_file():
                if child.name.lower() not in SKIP_FILE_NAMES:
                    results.append((child, "game:addons", Path(child.name)))
                continue
            if child.is_dir():
                for file in child.rglob("*"):
                    if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                        results.append((file, "game:addons", file.relative_to(addons)))
    for name, mapped in GAME_DIR_MAP.items():
        folder = game_tree / name
        if not folder.is_dir():
            continue
        for file in folder.rglob("*"):
            if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                results.append((file, f"game:{mapped}", file.relative_to(folder)))
    return results


def iter_plugin_files(plugin: RemotePlugin) -> list[tuple[Path, str, Path]]:
    if plugin.path.is_file():
        return iter_flat_plugin_files(plugin)
    game_tree = plugin.path / "left4dead2"
    if game_tree.is_dir():
        return iter_game_tree_plugin_files(plugin.path, game_tree)
    results: list[tuple[Path, str, Path]] = []
    root = plugin_content_root(plugin.path)
    for child in root.iterdir():
        name = child.name.lower()
        if name in SKIP_TOP_DIRS or name in SKIP_FILE_NAMES:
            continue
        if name == "cfg" and child.is_dir() and (plugin.path / "addons").is_dir():
            for file in child.rglob("*"):
                if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                    results.append((file, "game:cfg", file.relative_to(child)))
            continue
        if child.is_file():
            suffix = child.suffix.lower()
            if suffix == ".sp":
                results.append((child, "scripting", Path(child.name)))
            elif suffix == ".smx":
                results.append((child, "plugins", Path(child.name)))
            elif suffix == ".inc":
                results.append((child, "scripting", Path("include") / child.name))
            elif suffix == ".txt":
                try:
                    head = child.read_bytes()[:4000]
                except OSError:
                    continue
                if looks_like_gamedata(head):
                    results.append((child, "gamedata", Path(child.name)))
            continue
        if name in SM_DIR_MAP:
            mapped = SM_DIR_MAP[name]
            for file in child.rglob("*"):
                if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                    results.append((file, mapped, file.relative_to(child)))
        elif name in GAME_DIR_MAP:
            mapped = GAME_DIR_MAP[name]
            for file in child.rglob("*"):
                if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                    results.append((file, f"game:{mapped}", file.relative_to(child)))
    return results


def resolve_dest(
    game_dir: Path,
    mapped_root: str,
    rel: Path,
    local_hits: list[LocalPlugin],
) -> Path:
    if mapped_root.startswith("game:"):
        return game_dir / mapped_root.split(":", 1)[1] / rel
    dest_base = sm_root(game_dir) / mapped_root
    if mapped_root == "plugins" and rel.suffix.lower() == ".smx":
        for hit in local_hits:
            if hit.path.stem.lower() == rel.stem.lower():
                return hit.path
    return dest_base / rel


def plan_actions(
    matched: list[tuple[RemotePlugin, list[LocalPlugin]]],
    game_dir: Path,
    update_configs: bool,
) -> list[FileAction]:
    actions: list[FileAction] = []
    for rp, hits in matched:
        for src, mapped_root, rel in iter_plugin_files(rp):
            dest = resolve_dest(game_dir, mapped_root, rel, hits)
            # .smx applies MemPatches; never install sourcescramble_manager duplicate
            if is_zombie_spawn_fix_manager_config(src) or is_zombie_spawn_fix_manager_config(dest):
                continue
            root_name = mapped_root.split(":")[-1]
            dest_exists = dest.is_file()
            if dest_exists and sha256_file(src) == sha256_file(dest):
                kind = "skip_same"
            elif (not update_configs) and root_name in CONFIG_LIKE_ROOTS and dest_exists:
                kind = "skip_config"
            elif dest_exists:
                kind = "update"
            else:
                kind = "new"
            actions.append(FileAction(src=src, dest=dest, kind=kind, plugin=rp.name))
    return actions


def backup_file(src: Path, backup_root: Path, game_dir: Path) -> None:
    try:
        rel = src.relative_to(game_dir)
    except ValueError:
        rel = Path(src.name)
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def apply_actions(
    actions: list[FileAction],
    game_dir: Path,
    dry_run: bool,
) -> dict[str, int]:
    counts = {"new": 0, "update": 0, "skip_same": 0, "skip_config": 0, "backup": 0}
    backup_root = SCRIPT_DIR / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    for act in actions:
        counts[act.kind] += 1
        if act.kind in {"skip_same", "skip_config"}:
            continue
        print(f"[{act.kind:6}] {act.plugin}: {act.dest}")
        if dry_run:
            continue
        if act.kind == "update" and act.dest.is_file():
            backup_file(act.dest, backup_root, game_dir)
            counts["backup"] += 1
        act.dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(act.src, act.dest)
    if not dry_run:
        global _COMPILE_SEARCH_ROOTS
        prev_roots = list(_COMPILE_SEARCH_ROOTS)
        extra_roots: list[Path] = []
        seen_dirs: set[str] = set()
        for act in actions:
            plugin_dir = act.src.parent
            if plugin_dir.name.lower() in SM_DIR_MAP:
                plugin_dir = plugin_dir.parent
            key = str(plugin_dir.resolve()) if plugin_dir.exists() else str(plugin_dir)
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            extra_roots.append(plugin_dir)
            install_repo_compile_includes(plugin_dir, game_dir)
        _COMPILE_SEARCH_ROOTS = prev_roots + extra_roots
        try:
            dests = [act.dest for act in actions]
            extra = compile_copied_scripts(game_dir, dests)
            extra += ensure_gamedata_for_copied(game_dir, dests)
            counts["compiled"] = len(extra)
        finally:
            _COMPILE_SEARCH_ROOTS = prev_roots
        if remove_zombie_spawn_fix_manager_config(game_dir):
            print("已跳过/移除 configs/sourcescramble/zombie_spawn_fix.txt（由插件自身打补丁）")
    if not dry_run and counts["backup"]:
        print(f"已备份覆盖前的文件到: {backup_root}")
    return counts


def print_meta(repo: RepoSpec, meta: dict) -> None:
    print(f"仓库: {meta['html_url']}")
    print(f"分支: {meta['default_branch']}  提交: {meta['sha']}  {meta['commit_date']}")
    print(f"最近提交: {meta['commit_message']}")
    print(f"仓库更新时间: {meta['updated_at']}")
    print()


def selected_repos(args: argparse.Namespace) -> list[RepoSpec]:
    cfg = get_config()
    want = (args.repo or "all").lower()
    if want == "all":
        return list(cfg.repos)
    hits = [r for r in cfg.listed_repos() if r.key.lower() == want]
    if not hits:
        keys = ", ".join(r.key for r in cfg.listed_repos())
        raise SystemExit(f"未知仓库「{args.repo}」。config.txt 中的简称: all, {keys}")
    return hits


def load_remotes(repos: list[RepoSpec]) -> list[RemotePlugin]:
    all_remote: list[RemotePlugin] = []
    for repo in repos:
        try:
            meta = fetch_repo_meta(repo)
            print_meta(repo, meta)
        except Exception as e:
            print(f"仓库: {repo.html}")
            print(f"无法读取 GitHub 仓库信息（将用本地缓存）: {e}")
        sync_cache(repo)
        all_remote.extend(scan_remote_plugins(repo))
    return all_remote


def filter_by_names(plugins: list[RemotePlugin], names: list[str]) -> list[RemotePlugin]:
    want = {n.lower() for n in names}
    selected = [rp for rp in plugins if rp.keys & want or rp.name.lower() in want]
    found = set()
    for rp in selected:
        found |= rp.keys
        found.add(rp.name.lower())
    missing = [n for n in names if n.lower() not in found]
    if missing:
        raise SystemExit("仓库中找不到: " + ", ".join(missing))
    return selected


# ---------- Require 检测 ----------

def _has_addon(env: LocalEnv, *needles: str) -> bool:
    blob = " ".join(env.addon_names)
    return any(n.lower() in blob for n in needles)


def _has_ext(env: LocalEnv, *needles: str) -> bool:
    return any(n.lower() in env.extensions for n in needles)


def _has_inc(env: LocalEnv, *needles: str) -> bool:
    return any(n.lower() in env.includes for n in needles)


def _has_private_require(env: LocalEnv) -> bool:
    return all(
        _has_inc(env, name)
        for name in ("l4d2_weapons", "stringtables_data", "l4d2_hittable_control")
    )


def _has_plugin(env: LocalEnv, *needles: str) -> LocalPlugin | None:
    for n in needles:
        hit = env.plugin(n)
        if hit:
            return hit
        key = n.lower()
        for p in env.plugins:
            if key in p.name.lower():
                return p
    return None


def check_requirement(req: Requirement, env: LocalEnv) -> CheckResult:
    key = normalize_key(req.name)
    slug = req.slug
    slug_l = slug.lower()
    if req.url and "alliedmods.net" in req.url.lower():
        remembered = remembered_am_ok(req.url, env)
        if remembered is not None:
            return remembered

    alias_checks: list[tuple[set[str], callable]] = [
        ({"sourcemod", "source mod", "sourcemod + metamod", "metamod sourcemod"},
         lambda: CheckResult(env.has_sourcemod, "addons/sourcemod") if env.has_sourcemod else CheckResult(False, "缺少 SourceMod")),
        ({"metamod", "metamod:source", "metamod source"},
         lambda: CheckResult(env.has_metamod, "addons/metamod") if env.has_metamod else CheckResult(False, "缺少 Metamod")),
        ({"left4dhooks", "left 4 dhooks", "left 4 dhooks direct"},
         lambda: _plugin_result(env, "left4dhooks") or CheckResult(_has_inc(env, "left4dhooks"), "scripting/include/left4dhooks.inc")),
        ({"l4dtoolz", "l4d toolz"},
         lambda: CheckResult(_has_addon(env, "l4dtoolz", "l3rdtool"), "addons/l4dtoolz 或 l3rdtool")
         if _has_addon(env, "l4dtoolz", "l3rdtool") else CheckResult(False, "addons 下未找到 l4dtoolz/l3rdtool")),
        ({"multi colors", "multicolors", "inc multi colors"},
         lambda: CheckResult(_has_inc(env, "multicolors", "colors"), "scripting/include/multicolors")
         if _has_inc(env, "multicolors", "colors") else CheckResult(False, "缺少 multicolors.inc")),
        ({"dhooks", "inc dhooks", "dynamic hooks"},
         lambda: CheckResult(_has_ext(env, "dhooks") or _has_inc(env, "dhooks"), "extensions/dhooks")
         if (_has_ext(env, "dhooks") or _has_inc(env, "dhooks")) else CheckResult(False, "缺少 DHooks 扩展")),
        ({"sourcescramble", "source scramble"},
         lambda: CheckResult(_has_ext(env, "sourcescramble") or _has_inc(env, "sourcescramble"), "extensions/sourcescramble")
         if (_has_ext(env, "sourcescramble") or _has_inc(env, "sourcescramble")) else CheckResult(False, "缺少 SourceScramble 扩展")),
        ({"sdkhooks", "sdk hooks"},
         lambda: CheckResult(_has_ext(env, "sdkhooks"), "extensions/sdkhooks")
         if _has_ext(env, "sdkhooks") else CheckResult(False, "缺少 SDKHooks")),
        ({"actions", "action", "actions.ext", "actions ext"},
         lambda: CheckResult(_has_ext(env, "actions") or _has_inc(env, "actions"), "extensions/actions")
         if (_has_ext(env, "actions") or _has_inc(env, "actions")) else CheckResult(False, "缺少 Actions 扩展")),
        ({"collisionhook", "collision hook"},
         lambda: CheckResult(_has_ext(env, "collisionhook"), "extensions/collisionhook")
         if _has_ext(env, "collisionhook") else CheckResult(False, "缺少 CollisionHook 扩展")),
        ({"builtinvotes", "builtin votes", "built in votes"},
         lambda: CheckResult(_has_ext(env, "builtinvotes") or _has_inc(env, "builtinvotes"), "extensions/builtinvotes")
         if (_has_ext(env, "builtinvotes") or _has_inc(env, "builtinvotes")) else CheckResult(False, "缺少 builtinvotes 扩展")),
        ({"smlib", "smlib colors"},
         lambda: CheckResult(_has_inc(env, "smlib"), "scripting/include/smlib")
         if _has_inc(env, "smlib") else CheckResult(False, "缺少 smlib")),
        ({"sceneprocessor", "scene processor"},
         lambda: _plugin_result(env, "sceneprocessor")
         or (
             CheckResult(True, "scripting/include/sceneprocessor.inc")
             if _has_inc(env, "sceneprocessor")
             else None
         )
         or (
             CheckResult(True, "extensions/sceneprocessor")
             if _has_ext(env, "sceneprocessor")
             else None
         )
         or CheckResult(False, "缺少 sceneprocessor")),
        ({"thirdpersonshoulder detect", "thirdpersonshoulder_detect"},
         lambda: _plugin_result(env, "ThirdPersonShoulder_Detect", "thirdpersonshoulder_detect")),
        ({"attachments api"},
         lambda: _plugin_result(env, "l4d_attachments_api", "attachments_api") or CheckResult(_has_inc(env, "attachments_api"), "include/attachments_api")),
        ({"weapon prop give fix"},
         lambda: _plugin_result(env, "weapon_prop_give_fix", "l4d_weapon_prop_give_fix", "l4d2_give_weapon_fix", "GiveWeaponFix")),
        ({"zombie spawn fix"},
         lambda: _plugin_result(env, "zombie_spawn_fix")),
        ({"spawn infected nolimit"},
         lambda: _plugin_result(env, "spawn_infected_nolimit")),
        ({"unrestrict panic battlefield", "l4d unrestrict panic battlefield"},
         lambda: _plugin_result(env, "l4d_unrestrict_panic_battlefield")),
        ({"memoryex", "memory ex", "memory extended", "inc memoryex", "inc memory extended"},
         lambda: CheckResult(_has_inc(env, "memoryex"), "scripting/include/MemoryEx.inc")
         if _has_inc(env, "memoryex") else CheckResult(False, "缺少 MemoryEx.inc")),
        ({"sendproxy", "left4sendproxy"},
         lambda: CheckResult(_has_ext(env, "sendproxy") or _has_inc(env, "sendproxy"), "extensions/sendproxy")
         if (_has_ext(env, "sendproxy") or _has_inc(env, "sendproxy")) else CheckResult(False, "缺少 sendproxy 扩展")),
        ({"l4d2 weapons", "inc l4d2 weapons"},
         lambda: CheckResult(_has_inc(env, "l4d2_weapons"), "scripting/include/l4d2_weapons.inc")
         if _has_inc(env, "l4d2_weapons") else CheckResult(False, "缺少 l4d2_weapons.inc")),
        ({"stringtables data", "inc stringtables data", "stringtables_data"},
         lambda: CheckResult(_has_inc(env, "stringtables_data"), "scripting/include/stringtables_data.inc")
         if _has_inc(env, "stringtables_data") else CheckResult(False, "缺少 stringtables_data.inc")),
        ({"l4d2 hittable control", "inc l4d2 hittable control", "l4d2_hittable_control"},
         lambda: CheckResult(_has_inc(env, "l4d2_hittable_control"), "scripting/include/l4d2_hittable_control.inc")
         if _has_inc(env, "l4d2_hittable_control") else CheckResult(False, "缺少 l4d2_hittable_control.inc")),
        ({"l4d2 source keyvalues", "source keyvalues", "l4d2_source_keyvalues"},
         lambda: CheckResult(_has_inc(env, "l4d2_source_keyvalues"), "scripting/include/l4d2_source_keyvalues.inc")
         if _has_inc(env, "l4d2_source_keyvalues") else CheckResult(False, "缺少 l4d2_source_keyvalues.inc")),
        ({"use priority patch", "l4d use priority"},
         lambda: _plugin_result(env, "l4d_use_priority", "use_priority")),
        ({"transition restore fix"},
         lambda: _plugin_result(env, "transition_restore_fix")),
        ({"witch prevent target loss"},
         lambda: _plugin_result(env, "witch_prevent_target_loss")),
        ({"geoip", "geoip2", "country and city database"},
         lambda: CheckResult(_has_ext(env, "geoip") or (env.game_dir / "addons" / "sourcemod" / "configs" / "geoip").exists(),
                             "extensions/geoip") if (_has_ext(env, "geoip")) else CheckResult(False, "缺少 GeoIP 数据库/扩展")),
    ]
    for keys, fn in alias_checks:
        if key in keys:
            result = fn()
            if result is None:
                return CheckResult(False, req.url or "未在本地找到")
            return result

    if slug_l:
        hit = _plugin_result(env, slug, slug.replace("-", "_"))
        if hit and hit.ok:
            plugin = _has_plugin(env, slug, slug.replace("-", "_"))
            if (
                plugin
                and req.url
                and "alliedmods.net" in req.url.lower()
                and plugin.name.lower() == _title_slug(req.name)
                and plugin.name.count("_") >= 2
            ):
                return CheckResult(False, "本地文件名来自标题而非原附件，将按原名重新下载")
            return hit
        if _has_inc(env, slug_l, slug_l.replace("-", "_")):
            return CheckResult(True, f"include/{slug}")
        if _has_ext(env, slug_l, slug_l.replace("-", "_")):
            return CheckResult(True, f"extensions/{slug}")
        if _has_addon(env, slug_l):
            return CheckResult(True, f"addons/{slug}")

    clean = re.sub(r"[^\w]+", "_", key).strip("_")
    hit = _plugin_result(env, clean, key.replace(" ", "_"), key.replace(" ", ""))
    if hit:
        plugin = _has_plugin(env, clean, key.replace(" ", "_"), key.replace(" ", ""))
        if (
            plugin
            and req.url
            and "alliedmods.net" in req.url.lower()
            and plugin.name.lower() == _title_slug(req.name)
            and plugin.name.count("_") >= 2
        ):
            return CheckResult(False, "本地文件名来自标题而非原附件，将按原名重新下载")
        return hit
    if _has_inc(env, clean):
        return CheckResult(True, f"include/{clean}")
    if _has_ext(env, clean):
        return CheckResult(True, f"extensions/{clean}")

    if "l4dtoolz" in key and _has_addon(env, "l4dtoolz", "l3rdtool"):
        return CheckResult(True, "addons/l4dtoolz 或 l3rdtool")

    extra = req.url or req.note
    where = extra if extra else "未在本地找到对应插件/扩展/include"
    return CheckResult(False, where)


def dep_merge_key(req: Requirement) -> str:
    key = normalize_key(req.name)
    key = re.sub(r"^\((?:l4d2? only)\)\s*", "", key)
    aliases = (
        ("memoryex", ("memoryex", "memory extended", "memory ex")),
        ("sendproxy", ("sendproxy", "left4sendproxy")),
        ("l4d2_weapons", ("l4d2 weapons",)),
        ("zombie_spawn_fix", ("zombie spawn fix",)),
        ("spawn_infected_nolimit", ("spawn infected nolimit",)),
        ("l4d_unrestrict_panic_battlefield", ("unrestrict panic battlefield",)),
        ("witch_prevent_target_loss", ("witch prevent target loss",)),
        ("use_priority", ("use priority",)),
        ("weapon_prop_give_fix", ("weapon prop give",)),
        ("l4dtoolz", ("l4dtoolz",)),
        ("transition_restore_fix", ("transition restore",)),
        ("builtinvotes", ("builtinvotes", "builtin votes")),
        ("collisionhook", ("collisionhook", "collision hook")),
        ("smlib", ("smlib",)),
        ("sceneprocessor", ("sceneprocessor", "scene processor")),
        ("l4d2_transition_info_fix", ("transition info fix",)),
        ("l4d2_mission_manager", ("mission manager",)),
        ("actions", ("actions.ext", "actions ext")),
        ("dhooks", ("dhooks", "dynamic hooks")),
        ("sourcescramble", ("sourcescramble", "source scramble")),
        ("l4d2_vscript_purifier_v2", ("vscript purifier",)),
        ("l4d2_source_keyvalues", ("source keyvalues",)),
        ("linux_auto_restart", ("linux auto restart",)),
        ("server_loader", ("server loader",)),
        ("smd_advertisements", ("smd advertisements",)),
        ("smd_dynamichostname", ("smd dynamichostname", "dynamic hostname")),
        ("cannounce", ("cannounce", "connect announce")),
    )
    if key in {"action", "actions"}:
        return "actions"
    for canon, needles in aliases:
        if any(n in key for n in needles):
            return canon
    url = (req.url or "").lower()
    if "actions.ext" in url or "t=336374" in url:
        return "actions"
    if req.url:
        return req.url.split("#")[0].rstrip("/").lower()
    return key or req.slug.lower()


def game_engine_id(game_dir: Path) -> str:
    """Return 'l4d1' or 'l4d2' based on the game directory path."""
    path = str(game_dir).replace("\\", "/").lower().rstrip("/")
    if path.endswith("/left4dead2") or "/left4dead2/" in path + "/":
        return "l4d2"
    if path.endswith("/left4dead") or "/left4dead/" in path + "/":
        return "l4d1"
    return "l4d2"


def plugin_engine_only(sp_path: Path) -> str | None:
    """Return 'l4d1'/'l4d2' if AskPluginLoad2 rejects the other engine, else None."""
    try:
        text = sp_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if re.search(r"only supports Left 4 Dead 1\b", text, re.I):
        return "l4d1"
    if re.search(r"only supports Left 4 Dead 2\b", text, re.I):
        return "l4d2"
    m = re.search(
        r"GetEngineVersion\s*\(\)[\s\S]{0,240}?"
        r"!=\s*(Engine_Left4Dead2?)\b[\s\S]{0,240}?APLRes_SilentFailure",
        text,
    )
    if m:
        return "l4d2" if m.group(1).endswith("2") else "l4d1"
    return None


def plugin_wrong_engine(env: LocalEnv, plugin_name: str) -> bool:
    """True if local .sp declares it will not load on this game."""
    sp = sm_root(env.game_dir) / "scripting" / f"{plugin_name}.sp"
    if not sp.is_file():
        return False
    only = plugin_engine_only(sp)
    return bool(only and only != game_engine_id(env.game_dir))


def plugin_missing_gamedata(env: LocalEnv, plugin_name: str) -> list[str]:
    if plugin_wrong_engine(env, plugin_name):
        return []
    sm = sm_root(env.game_dir)
    needed: set[str] = set(PLUGIN_REQUIRED_GAMEDATA.get(plugin_name.lower(), ()))
    sp = sm / "scripting" / f"{plugin_name}.sp"
    if sp.is_file():
        needed |= gamedata_names_from_sp(sp)
    missing: list[str] = []
    for name in sorted(needed):
        fname = name if name.lower().endswith(".txt") else f"{name}.txt"
        if not (sm / "gamedata" / fname).is_file():
            missing.append(fname)
    return missing


def _plugin_result(env: LocalEnv, *names: str) -> CheckResult | None:
    hit = _has_plugin(env, *names)
    if not hit:
        return None
    missing = plugin_missing_gamedata(env, hit.name)
    if missing:
        return CheckResult(False, "缺少 gamedata: " + ", ".join(missing))
    tag = " [disabled]" if hit.disabled else ""
    return CheckResult(True, f"{hit.path.name}{tag}")


def _title_slug(name: str) -> str:
    return re.sub(r"[^\w]+", "_", name).strip("_").lower()


def encode_url(url: str) -> str:
    parsed = urlparse(url)
    path = quote(unquote(parsed.path), safe="/:@")
    return parsed._replace(path=path).geturl()


def _direct_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_bytes(url: str, timeout: int = 120) -> bytes:
    headers = github_headers()
    headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://forums.alliedmods.net/",
        }
    )
    req = urllib.request.Request(encode_url(url), headers=headers)
    host = (urlparse(url).hostname or "").lower()
    if (
        host in {"127.0.0.1", "localhost"}
        or "alliedmods.net" in host
        or "sourcemod.net" in host
    ):
        opener = _direct_opener()
        with opener.open(req, timeout=timeout) as resp:
            return resp.read()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_wayback(url: str) -> bytes:
    target = (url or "").split("#")[0].strip()
    if not target:
        raise RuntimeError("Wayback 地址为空")
    api = (
        "https://web.archive.org/cdx/search/cdx?url="
        + quote(target, safe="")
        + "&output=json&fl=timestamp,original,statuscode&filter=statuscode:200&limit=50"
    )
    print(f"   Wayback 快照: {target}")
    rows = json.loads(http_bytes(api).decode("utf-8", errors="replace"))
    if not isinstance(rows, list) or len(rows) < 2:
        raise RuntimeError(f"Wayback 没有可用快照: {target}")
    hits = [r for r in rows[1:] if r and str(r[0]).isdigit()]
    if not hits:
        raise RuntimeError(f"Wayback 没有可用快照: {target}")
    hits.sort(key=lambda r: str(r[0]), reverse=True)
    ts, original = str(hits[0][0]), str(hits[0][1] if len(hits[0]) > 1 else target)
    snap = f"https://web.archive.org/web/{ts}id_/{original}"
    blob = http_bytes(snap)
    if not blob:
        raise RuntimeError(f"Wayback 快照为空: {snap}")
    return blob


def is_am_forum_url(url: str) -> bool:
    return "forums.alliedmods.net" in urlparse(url).netloc.lower()


def is_cloudflare_challenge(data: bytes, title: str = "") -> bool:
    text = (data[:12000].decode("utf-8", errors="ignore") + " " + title).lower()
    needles = (
        "just a moment",
        "请稍候",
        "cf-mitigated",
        "checking your browser",
        "验证您是真人",
        "正在进行安全验证",
    )
    return any(n in text for n in needles)


def load_am_cookies() -> list[dict]:
    if not AM_COOKIE_FILE.is_file():
        return []
    try:
        data = json.loads(AM_COOKIE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_am_cookies(cookies: list[dict]) -> None:
    AM_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    slim = []
    for c in cookies:
        slim.append(
            {
                "name": c.get("name"),
                "value": c.get("value"),
                "domain": c.get("domain") or ".alliedmods.net",
                "path": c.get("path") or "/",
            }
        )
    AM_COOKIE_FILE.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")


def _find_chrome_exe() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for p in candidates:
        if p and p.is_file():
            return p
    return None


def _scrub_chrome_session(user_dir: Path) -> None:
    default = user_dir / "Default"
    for rel in (
        "Current Session",
        "Last Session",
        "Current Tabs",
        "Last Tabs",
        "Sessions",
        "Session Storage",
    ):
        p = default / rel
        try:
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def _ensure_curl_cffi():
    try:
        from curl_cffi import requests as cf_requests
        return cf_requests
    except ImportError:
        print("正在安装 curl_cffi …")
        subprocess.run([sys.executable, "-m", "pip", "install", "curl_cffi"], check=True)
        from curl_cffi import requests as cf_requests
        return cf_requests


def _free_debug_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _cf_title(title: str) -> bool:
    t = (title or "").strip().lower()
    return t in {"just a moment...", "just a moment", "请稍候…", "请稍候", "请稍候..."} or "验证您是真人" in (title or "")


def _ws_127(url: str) -> str:
    return (
        (url or "")
        .replace("ws://localhost", "ws://127.0.0.1")
        .replace("ws://[::1]", "ws://127.0.0.1")
        .replace("ws://::1", "ws://127.0.0.1")
    )


class _CdpSock:
    """Chrome DevTools WebSocket，强制直连 127.0.0.1，不走系统代理。"""

    def __init__(self, ws_url: str, default_port: int = 0) -> None:
        parsed = urlparse(_ws_127(ws_url))
        port = int(parsed.port or default_port or 0)
        if not port:
            raise RuntimeError(f"无效的 Chrome 调试地址: {ws_url}")
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        self._sock = socket.create_connection(("127.0.0.1", port), timeout=30)
        self._buf = b""
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://127.0.0.1\r\n"
            "\r\n"
        )
        self._sock.sendall(handshake.encode("ascii"))
        header = self._recv_until(b"\r\n\r\n")
        status = header.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"CDP 握手失败: {status.decode('utf-8', 'replace')}")
        self._n = 0

    def _recv_until(self, sep: bytes) -> bytes:
        while sep not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Chrome 调试连接已断开")
            self._buf += chunk
        data, self._buf = self._buf.split(sep, 1)
        return data

    def _recvn(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise ConnectionError("Chrome 调试连接已断开")
            self._buf += chunk
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray()
        header.append(0x80 | (opcode & 0x0F))
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(n.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(n.to_bytes(8, "big"))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_message(self) -> str:
        parts = bytearray()
        while True:
            b1 = self._recvn(1)[0]
            b2 = self._recvn(1)[0]
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            n = b2 & 0x7F
            if n == 126:
                n = int.from_bytes(self._recvn(2), "big")
            elif n == 127:
                n = int.from_bytes(self._recvn(8), "big")
            mask = self._recvn(4) if masked else b""
            payload = self._recvn(n)
            if masked:
                payload = bytes(payload[i] ^ mask[i % 4] for i in range(n))
            if opcode == 0x8:
                raise ConnectionError("Chrome 关闭了调试通道")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            parts.extend(payload)
            if b1 & 0x80:
                return bytes(parts).decode("utf-8")

    def call(self, method: str, params: dict | None = None, timeout: int = 60) -> dict:
        self._n += 1
        nid = self._n
        payload: dict = {"id": nid, "method": method}
        if params:
            payload["params"] = params
        self._sock.settimeout(timeout)
        self._send_frame(0x1, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self._recv_message())
            if msg.get("id") != nid:
                continue
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg.get("result") or {}
        raise TimeoutError(method)

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass


class AlliedModsSession:
    """启动普通 Chrome（不挂 Playwright）。验证期间只看调试端口的标题，不碰网页。"""

    HOME = "https://forums.alliedmods.net/"

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._port = 0
        self._ua = ""
        self._cookies: list[dict] = []
        self._verified = False

    def open(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        chrome = _find_chrome_exe()
        if chrome is None:
            raise RuntimeError("找不到本机 Chrome。请安装 Google Chrome 后再试。")
        self._port = _free_debug_port()
        user_dir = SCRIPT_DIR / ".cache" / "am_profile_real"
        user_dir.mkdir(parents=True, exist_ok=True)
        _scrub_chrome_session(user_dir)
        args = [
            str(chrome),
            f"--remote-debugging-port={self._port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            self.HOME,
        ]
        print(f"启动普通 Chrome（不自动控制页面）: {chrome}")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 40
        last_err = ""
        while time.time() < deadline:
            try:
                info = self._debug_json("/json/version")
                self._ua = str(info.get("User-Agent") or "")
                return
            except Exception as e:
                last_err = str(e)
                time.sleep(0.25)
        raise RuntimeError(f"Chrome 调试端口未就绪: {last_err}")

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        self._verified = False
        self._cookies = []
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def _debug_json(self, path: str):
        url = f"http://127.0.0.1:{self._port}{path}"
        req = urllib.request.Request(url, headers={"Host": "127.0.0.1"})
        with _direct_opener().open(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))

    def _open_cdp(self, ws_url: str) -> _CdpSock:
        return _CdpSock(ws_url, default_port=self._port)

    def _forum_tab(self) -> dict | None:
        try:
            tabs = self._debug_json("/json")
        except Exception:
            return None
        if not isinstance(tabs, list):
            return None
        for tab in tabs:
            url = str(tab.get("url") or "")
            if "alliedmods.net" in url and not url.startswith("devtools://"):
                return tab
        return None

    def _tab_passed(self, tab: dict) -> bool:
        url = str(tab.get("url") or "")
        title = str(tab.get("title") or "").strip()
        if "alliedmods.net" not in url:
            return False
        if not title:
            return False
        if url.startswith(("chrome-error:", "about:", "data:", "chrome://")):
            return False
        if _cf_title(title):
            return False
        low = title.lower()
        if "just a moment" in low or "attention required" in low or "cloudflare" in low:
            return False
        if "challenges.cloudflare.com" in url:
            return False
        return True

    def wait_cf(self, timeout: int = 300) -> None:
        print("请在弹出的普通 Chrome 里勾选「验证您是真人」。")
        print("勾选通过前不会开始下载；请不要关闭窗口。")
        deadline = time.time() + timeout
        ok_streak = 0
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError("Chrome 已关闭。请再运行一次，并保持验证窗口开着。")
            tab = self._forum_tab()
            if tab and self._tab_passed(tab):
                ok_streak += 1
                if ok_streak >= 5:
                    try:
                        self._cookies = self._cdp_cookies()
                        save_am_cookies(self._cookies)
                    except Exception as e:
                        print(f"读取 Cookie 暂未成功（{e}），改为在已验证窗口内下载。")
                    print("已通过 Cloudflare 验证，开始下载。")
                    return
            else:
                ok_streak = 0
            time.sleep(1.2)
        raise RuntimeError("等待勾选 Cloudflare 超时。请再运行一次，并在弹出的 Chrome 里勾选验证框。")

    def _filter_am_cookies(self, cookies: list) -> list[dict]:
        out = []
        for c in cookies or []:
            domain = str(c.get("domain") or "")
            if "alliedmods" in domain or "cloudflare" in domain:
                out.append(c)
        return out

    def _cdp_cookies(self) -> list[dict]:
        info = self._debug_json("/json/version")
        ws_url = str(info.get("webSocketDebuggerUrl") or "")
        if ws_url:
            sock = self._open_cdp(ws_url)
            try:
                try:
                    result = sock.call("Storage.getCookies")
                except Exception:
                    result = sock.call("Network.getAllCookies")
                found = self._filter_am_cookies(result.get("cookies") or [])
                if found:
                    return found
            finally:
                sock.close()
        tab = self._forum_tab()
        if not tab:
            return []
        sock = self._open_cdp(str(tab.get("webSocketDebuggerUrl") or ""))
        try:
            try:
                sock.call("Network.enable")
            except Exception:
                pass
            result = sock.call(
                "Network.getCookies",
                {"urls": ["https://forums.alliedmods.net/", "https://alliedmods.net/"]},
            )
            found = self._filter_am_cookies(result.get("cookies") or [])
            if found:
                return found
            eval_result = sock.call(
                "Runtime.evaluate",
                {"expression": "document.cookie", "returnByValue": True},
            )
            raw = str((eval_result.get("result") or {}).get("value") or "")
            parsed = []
            for part in raw.split(";"):
                if "=" not in part:
                    continue
                name, value = part.split("=", 1)
                parsed.append(
                    {
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".alliedmods.net",
                        "path": "/",
                    }
                )
            return parsed
        finally:
            sock.close()

    def _cookie_header(self, url: str) -> str:
        host = urlparse(url).hostname or ""
        parts = []
        for c in self._cookies:
            domain = str(c.get("domain") or "").lstrip(".")
            if domain and domain not in host and not host.endswith("." + domain):
                continue
            name = c.get("name")
            value = c.get("value")
            if name and value is not None:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    def _http_with_cookies(self, url: str) -> bytes:
        headers = {
            "User-Agent": self._ua or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Referer": "https://forums.alliedmods.net/",
        }
        cookie = self._cookie_header(url)
        if cookie:
            headers["Cookie"] = cookie
        cf_requests = _ensure_curl_cffi()
        saved_proxy = {}
        for key in list(os.environ):
            if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "ws_proxy"}:
                saved_proxy[key] = os.environ.pop(key)
        try:
            sess = cf_requests.Session(impersonate="chrome")
            sess.trust_env = False
            resp = sess.get(
                encode_url(url),
                headers=headers,
                timeout=120,
                allow_redirects=True,
                proxies={"http": None, "https": None},
            )
            return resp.content or b""
        finally:
            os.environ.update(saved_proxy)

    def _urllib_with_cookies(self, url: str) -> bytes:
        headers = {
            "User-Agent": self._ua or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Referer": "https://forums.alliedmods.net/",
        }
        cookie = self._cookie_header(url)
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(encode_url(url), headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=120) as resp:
            return resp.read() or b""

    def _page_fetch(self, url: str) -> bytes:
        tab = self._forum_tab()
        if not tab:
            raise RuntimeError("找不到论坛标签页")
        sock = self._open_cdp(str(tab.get("webSocketDebuggerUrl") or ""))
        try:
            expr = (
                "(async () => {"
                f" const r = await fetch({json.dumps(encode_url(url))},"
                " {credentials:'include', redirect:'follow'});"
                " const buf = await r.arrayBuffer();"
                " const bytes = new Uint8Array(buf);"
                " let binary = '';"
                " const step = 0x8000;"
                " for (let i = 0; i < bytes.length; i += step) {"
                "  binary += String.fromCharCode.apply(null, bytes.subarray(i, i + step));"
                " }"
                " return {status: r.status, b64: btoa(binary)};"
                "})()"
            )
            result = sock.call(
                "Runtime.evaluate",
                {"expression": expr, "awaitPromise": True, "returnByValue": True},
                timeout=120,
            )
            if result.get("exceptionDetails"):
                raise RuntimeError(str(result.get("exceptionDetails")))
            val = (result.get("result") or {}).get("value") or {}
            status = int(val.get("status") or 0)
            raw = val.get("b64") or ""
            body = base64.b64decode(raw) if raw else b""
            if status >= 400 or not body:
                raise RuntimeError(f"浏览器内 fetch 失败 HTTP {status}: {url}")
            return body
        finally:
            sock.close()

    def _cdp_download(self, url: str) -> bytes:
        tab = self._forum_tab()
        if not tab:
            raise RuntimeError("找不到论坛标签页")
        ws_url = str(tab.get("webSocketDebuggerUrl") or "")
        sock = self._open_cdp(ws_url)
        try:
            sock.call("Page.enable")
            sock.call("Network.enable")
            tree = sock.call("Page.getFrameTree")
            frame_id = ((tree.get("frameTree") or {}).get("frame") or {}).get("id")
            if not frame_id:
                raise RuntimeError("没有 frameId")
            result = sock.call(
                "Network.loadNetworkResource",
                {
                    "frameId": frame_id,
                    "url": encode_url(url),
                    "options": {"disableCache": False, "includeCredentials": True},
                },
                timeout=120,
            )
            resource = result.get("resource") or {}
            if not resource.get("success"):
                code = resource.get("httpStatusCode")
                raise RuntimeError(f"CDP 下载失败 HTTP {code}: {url}")
            handle = resource.get("stream")
            if not handle:
                raise RuntimeError("CDP 没有返回数据流")
            chunks: list[bytes] = []
            while True:
                part = sock.call("IO.read", {"handle": handle, "size": 262144}, timeout=120)
                data = part.get("data") or ""
                if part.get("base64Encoded"):
                    chunks.append(base64.b64decode(data))
                else:
                    chunks.append(data.encode("utf-8") if isinstance(data, str) else data)
                if part.get("eof"):
                    break
            try:
                sock.call("IO.close", {"handle": handle})
            except Exception:
                pass
            return b"".join(chunks)
        finally:
            sock.close()

    def ensure_verified(self) -> None:
        if self._verified:
            return
        saved = load_am_cookies()
        if saved:
            self._cookies = saved
            try:
                probe = self._http_with_cookies(self.HOME)
                if probe and not is_cloudflare_challenge(probe) and b"alliedmod" in probe.lower():
                    self._verified = True
                    print("沿用上次论坛验证 Cookie，无需再勾选。")
                    return
            except Exception:
                pass
        self.open()
        self.wait_cf()
        self._verified = True

    def fetch(self, url: str) -> bytes:
        cache_key = encode_url((url or "").split("#", 1)[0].strip())
        hit = _SESSION_AM_BODIES.get(cache_key)
        if hit is not None:
            return hit
        self.ensure_verified()
        print(f"   后台下载: {url}")
        last_err: Exception | None = None
        for fn in (self._page_fetch, self._cdp_download, self._http_with_cookies, self._urllib_with_cookies):
            try:
                body = fn(url)
            except Exception as e:
                last_err = e
                continue
            if body and not is_cloudflare_challenge(body):
                _SESSION_AM_BODIES[cache_key] = body
                return body
        try:
            body = fetch_wayback(url)
            if body and not is_cloudflare_challenge(body):
                _SESSION_AM_BODIES[cache_key] = body
                return body
        except Exception as e:
            last_err = e
        extra = f" ({last_err})" if last_err else ""
        raise RuntimeError(f"论坛下载失败: {url}{extra}")


_AM_SESSION: AlliedModsSession | None = None


def get_am_session() -> AlliedModsSession:
    global _AM_SESSION
    if _AM_SESSION is None:
        _AM_SESSION = AlliedModsSession()
    return _AM_SESSION


def close_am_session() -> None:
    global _AM_SESSION
    if _AM_SESSION is not None:
        _AM_SESSION.close()
        _AM_SESSION = None


def http_text(url: str) -> str:
    return http_bytes(url).decode("utf-8", errors="replace")


def github_raw_url(url: str) -> str:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc == "raw.githubusercontent.com":
        return url
    if "github.com" in parsed.netloc and len(parts) >= 5 and parts[2] in {"blob", "raw"}:
        owner, repo, _, branch, *rest = parts
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{'/'.join(rest)}"
    return url


def normalize_github_slug(owner_repo: str) -> str:
    text = (owner_repo or "").strip().strip("/")
    if text.lower().endswith(".git"):
        text = text[:-4]
    parts = [p for p in text.split("/") if p]
    if len(parts) >= 2:
        owner, name = parts[0], parts[1]
        if name.lower().endswith(".git"):
            name = name[:-4]
        return f"{owner}/{name}"
    return text


def cache_git_repo(owner_repo: str, branch: str = "") -> Path:
    owner_repo = normalize_github_slug(owner_repo)
    try:
        for repo in get_config().repos:
            ow, nm = repo.owner_name
            if f"{ow}/{nm}".lower() == owner_repo.lower():
                return sync_cache(repo)
    except SystemExit as e:
        raise RuntimeError(str(e)) from None
    except Exception:
        pass
    dest = SCRIPT_DIR / ".cache" / "deps" / owner_repo.replace("/", "_")
    url = f"https://github.com/{owner_repo}.git"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dep_key = str(dest.resolve()) if dest.exists() else str(dest)
    try:
        if (dest / ".git").is_dir():
            if dep_key in _SESSION_DEP_SYNCED:
                return dest
            try:
                run_git(["fetch", "--depth", "1", "origin"], cwd=dest)
                run_git(["reset", "--hard", "FETCH_HEAD"], cwd=dest)
            except Exception as e:
                if cache_has_plugins(dest):
                    print(f"依赖仓库在线更新失败，改用本地缓存 {owner_repo}")
                    _SESSION_DEP_SYNCED.add(dep_key)
                    return dest
                raise RuntimeError(str(e)) from e
            _SESSION_DEP_SYNCED.add(dep_key)
            return dest
        args = ["clone", "--depth", "1"]
        if branch:
            args += ["--branch", branch]
        args += [url, str(dest)]
        run_git(args)
        _SESSION_DEP_SYNCED.add(str(dest.resolve()) if dest.exists() else str(dest))
    except SystemExit as e:
        raise RuntimeError(str(e)) from None
    return dest


def copy_sm_tree(src_root: Path, game_dir: Path) -> list[Path]:
    copied: list[Path] = []
    sm = sm_root(game_dir)
    mapping = dict(SM_DIR_MAP)
    for child in src_root.iterdir() if src_root.is_dir() else []:
        name = child.name.lower()
        if name == "cfg" and (src_root / "addons").is_dir():
            continue
        if name in mapping and child.is_dir():
            for file in child.rglob("*"):
                if file.is_file() and file.name.lower() not in SKIP_FILE_NAMES:
                    dest = sm / mapping[name] / file.relative_to(child)
                    if is_zombie_spawn_fix_manager_config(file) or is_zombie_spawn_fix_manager_config(dest):
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, dest)
                    copied.append(dest)
    return copied


def write_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def find_spcomp(game_dir: Path) -> Path | None:
    scripting = sm_root(game_dir) / "scripting"
    for name in ("spcomp.exe", "spcomp64.exe", "spcomp", "spcomp64"):
        p = scripting / name
        if p.is_file():
            return p
    return None


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


MISSING_INC_RE = re.compile(r"cannot read from file:\s*\"([^\"]+)\"", re.I)
_COMPILE_SEARCH_ROOTS: list[Path] = []


def iter_repo_include_dirs(start: Path | None) -> list[Path]:
    if start is None:
        return []
    cur = start.resolve() if start.exists() else None
    if cur is None:
        return []
    if cur.is_file():
        cur = cur.parent
    found: list[Path] = []
    seen: set[str] = set()
    for _ in range(10):
        for cand in (cur / "include", cur / "scripting" / "include"):
            if cand.is_dir():
                key = str(cand.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(cand)
        if (cur / ".git").exists() or cur.name.lower() == "deps":
            break
        if cur.parent == cur:
            break
        cur = cur.parent
    return found


def dest_for_cached_include(found: Path, dest_inc: Path) -> Path:
    parts = found.parts
    low = [p.lower() for p in parts]
    if "include" in low:
        i = len(low) - 1 - low[::-1].index("include")
        rel = Path(*parts[i + 1 :]) if i + 1 < len(parts) else Path(found.name)
        return dest_inc / rel
    return dest_inc / found.name


def locate_cached_include(need: str, extra_roots: list[Path] | None = None) -> Path | None:
    rel = need.replace("\\", "/").strip().strip("/")
    if not rel.lower().endswith(".inc"):
        rel += ".inc"
    fname = Path(rel).name
    roots: list[Path] = []
    for p in list(extra_roots or []) + list(_COMPILE_SEARCH_ROOTS):
        if p and Path(p).exists():
            roots.append(Path(p))
    deps = SCRIPT_DIR / ".cache" / "deps"
    cache = SCRIPT_DIR / ".cache"
    if deps.is_dir():
        roots.append(deps)
        for child in deps.iterdir():
            if child.is_dir():
                roots.extend((child / "include", child / "scripting" / "include"))
    if cache.is_dir():
        roots.append(cache)

    checked: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        key = str(root.resolve()) if root.is_dir() or root.is_file() else str(root)
        if key in checked:
            continue
        checked.add(key)
        if root.is_file():
            if root.name.lower() == fname.lower():
                return root
            continue
        if not root.is_dir():
            continue
        for cand in (root / rel, root / fname, root / "include" / rel, root / "scripting" / "include" / rel):
            if cand.is_file():
                return cand
        for sub in (root / "include", root / "scripting" / "include"):
            if sub.is_dir():
                hit = sub / rel
                if hit.is_file():
                    return hit
    if deps.is_dir():
        for hit in deps.rglob(fname):
            if not hit.is_file():
                continue
            norm = str(hit).replace("\\", "/")
            if norm.lower().endswith("/" + rel.lower()) or norm.lower().endswith(rel.lower()):
                return hit
        hits = [p for p in deps.rglob(fname) if p.is_file()]
        if hits:
            return hits[0]
    return None


def install_found_include(found: Path, game_dir: Path) -> Path:
    dest_inc = sm_root(game_dir) / "scripting" / "include"
    dest = dest_for_cached_include(found, dest_inc)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(found, dest)
    return dest


def install_repo_compile_includes(src: Path, game_dir: Path) -> list[Path]:
    copied: list[Path] = []
    dest_inc = sm_root(game_dir) / "scripting" / "include"
    dest_inc.mkdir(parents=True, exist_ok=True)
    for inc_dir in iter_repo_include_dirs(src):
        if not inc_dir.is_dir():
            continue
        for folder in inc_dir.iterdir():
            if not (folder.is_dir() and folder.name.startswith("@")):
                continue
            for file in folder.rglob("*.inc"):
                dest = dest_inc / file.relative_to(inc_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, dest)
                copied.append(dest)
    if src.is_dir():
        for inc_dir in (src / "include", src / "scripting" / "include"):
            if not inc_dir.is_dir():
                continue
            for file in inc_dir.rglob("*.inc"):
                dest = dest_inc / file.relative_to(inc_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_file():
                    continue
                shutil.copy2(file, dest)
                copied.append(dest)
    return copied


def parse_missing_includes(output: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for m in MISSING_INC_RE.finditer(output or ""):
        name = m.group(1).strip()
        key = name.replace("\\", "/").lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def gamedata_names_from_sp(sp_path: Path) -> set[str]:
    names: set[str] = set()
    try:
        text = sp_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return names
    macros: dict[str, str] = {}
    for m in GD_DEFINE_RE.finditer(text):
        macros[m.group(1)] = m.group(2)
        names.add(m.group(2))
    for m in GD_LOAD_STR_RE.finditer(text):
        names.add(m.group(1))
    for m in GD_LOAD_MACRO_RE.finditer(text):
        if m.group(1) in macros:
            names.add(macros[m.group(1)])
    return {n.strip() for n in names if n.strip()}


def unescape_sp_string(s: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            n = s[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(n, n))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


SP_WRITELINE_RE = re.compile(
    r'(?:hFile|hfile|file)\.WriteLine\(\s*"((?:\\.|[^"\\])*)"\s*(?:,\s*([^)\n]+))?\s*\)',
    re.I,
)


def extract_embedded_gamedata(sp_path: Path) -> str | None:
    try:
        text = sp_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    macros: dict[str, str] = {}
    for m in re.finditer(r"#define\s+(\w+)\s+(\d+)\b", text):
        macros[m.group(1)] = m.group(2)
    in_write = False
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not in_write:
            if re.search(r'OpenFile\s*\(\s*sPath\s*,\s*"w"', s, re.I):
                in_write = True
            continue
        if re.match(r"delete\s+hFile\b", s, re.I) or s in {"}", "}}"}:
            if lines:
                break
        m = SP_WRITELINE_RE.search(raw)
        if not m:
            continue
        body = unescape_sp_string(m.group(1))
        arg = (m.group(2) or "").strip()
        if arg:
            key = arg.split(",")[0].strip()
            if key in macros and "%" in body:
                try:
                    body = body % int(macros[key])
                except (TypeError, ValueError):
                    body = body.replace("%d", macros[key])
        lines.append(body)
    blob = "\n".join(lines).strip() + ("\n" if lines else "")
    if '"Games"' not in blob and '"Signatures"' not in blob:
        return None
    return blob


def locate_cached_gamedata(need: str, extra_roots: list[Path] | None = None) -> Path | None:
    fname = Path(need.replace("\\", "/").strip()).name
    if not fname.lower().endswith(".txt"):
        fname += ".txt"
    roots: list[Path] = []
    for p in list(extra_roots or []) + list(_COMPILE_SEARCH_ROOTS):
        if p and Path(p).exists():
            roots.append(Path(p))
    deps = SCRIPT_DIR / ".cache" / "deps"
    cache = SCRIPT_DIR / ".cache"
    if deps.is_dir():
        roots.append(deps)
        for child in deps.iterdir():
            if child.is_dir():
                roots.extend((child / "gamedata", child / "addons" / "sourcemod" / "gamedata"))
    if cache.is_dir():
        roots.append(cache)
    checked: set[str] = set()
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        key = str(root)
        if key in checked:
            continue
        checked.add(key)
        if root.is_file():
            if root.name.lower() == fname.lower():
                candidates.append(root)
            continue
        if not root.is_dir():
            continue
        for cand in (
            root / fname,
            root / "gamedata" / fname,
            root / "addons" / "sourcemod" / "gamedata" / fname,
        ):
            if cand.is_file():
                candidates.append(cand)
    for cand in candidates:
        try:
            if looks_like_gamedata(cand.read_bytes()):
                return cand
        except OSError:
            continue
    search = deps if deps.is_dir() else None
    if search is not None:
        for hit in search.rglob(fname):
            if not hit.is_file():
                continue
            try:
                if looks_like_gamedata(hit.read_bytes()):
                    return hit
            except OSError:
                continue
    return None


def ensure_gamedata_for_copied(game_dir: Path, copied: list[Path]) -> list[Path]:
    extra: list[Path] = []
    sm = sm_root(game_dir)
    gd_dir = sm / "gamedata"
    gd_dir.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    stems: set[str] = set()
    for p in copied:
        if not p:
            continue
        suffix = p.suffix.lower()
        if suffix == ".sp" and p.is_file():
            names |= gamedata_names_from_sp(p)
            stems.add(p.stem)
        elif suffix == ".smx":
            stems.add(p.stem)
            sp = sm / "scripting" / f"{p.stem}.sp"
            if sp.is_file():
                names |= gamedata_names_from_sp(sp)
        elif suffix == ".txt" and "gamedata" in [x.lower() for x in p.parts]:
            continue
    required = set(names)
    optional = set(stems) - required
    for name in sorted(required | optional):
        dest = gd_dir / (name if name.lower().endswith(".txt") else f"{name}.txt")
        if dest.is_file():
            continue
        found = locate_cached_gamedata(name)
        embedded: str | None = None
        if found is None:
            for p in copied:
                if p.suffix.lower() == ".sp" and p.is_file():
                    embedded = extract_embedded_gamedata(p)
                    if embedded:
                        break
            if embedded is None:
                sp_local = sm / "scripting" / f"{Path(name).stem}.sp"
                if sp_local.is_file():
                    embedded = extract_embedded_gamedata(sp_local)
        if found is None and not embedded:
            if name in required:
                print(f"   缺少 gamedata: {dest.name}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if found is not None:
            shutil.copy2(found, dest)
        else:
            dest.write_text(embedded or "", encoding="utf-8")
        print(f"   已补全 gamedata: {dest.relative_to(sm)}")
        extra.append(dest)
    return extra


def original_filename(text: str) -> str:
    text = html_unescape((text or "").replace("\xa0", " "))
    m = AM_FILE_TOKEN_RE.search(text)
    return m.group(1) if m else ""


def parse_am_plugin_source_name(html: str) -> str:
    html = html_unescape(html or "")
    m = AM_GET_SOURCE_RE.search(html)
    if m:
        return m.group(1)
    idx = html.lower().find("vbcompiler.php?file_id=")
    if idx >= 0:
        window = html[max(0, idx - 600) : idx + 600]
        m2 = AM_FILE_TOKEN_RE.search(window)
        if m2 and m2.group(1).lower().endswith(".sp"):
            return m2.group(1)
    m3 = re.search(r"\(([A-Za-z0-9_.\-&,+]+\.sp)\s*[-–]", html)
    return m3.group(1) if m3 else ""


def load_am_installed() -> dict:
    if AM_INSTALLED_FILE.is_file():
        try:
            return json.loads(AM_INSTALLED_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def remember_am_install(url: str, files: list[str]) -> None:
    key = (url or "").split("#")[0].rstrip("/").lower()
    if not key or not files:
        return
    data = load_am_installed()
    data[key] = sorted({Path(f).name for f in files if f})
    AM_INSTALLED_FILE.parent.mkdir(parents=True, exist_ok=True)
    AM_INSTALLED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def remembered_am_ok(url: str, env: LocalEnv) -> CheckResult | None:
    key = (url or "").split("#")[0].rstrip("/").lower()
    names = load_am_installed().get(key)
    if not names:
        return None
    sm = sm_root(env.game_dir)
    missing: list[str] = []
    for name in names:
        n = name.lower()
        if n.endswith(".smx"):
            cands = [sm / "plugins" / name, sm / "plugins" / "disabled" / name]
        elif n.endswith(".sp"):
            cands = [sm / "scripting" / name]
        elif n.endswith(".inc"):
            cands = [sm / "scripting" / "include" / name]
        elif n.endswith(".txt"):
            cands = [sm / "gamedata" / name]
        else:
            cands = [sm / "plugins" / name, sm / "gamedata" / name, sm / "scripting" / name]
        if not any(p.is_file() for p in cands):
            missing.append(name)
    if missing:
        return CheckResult(False, "缺少原附件: " + ", ".join(missing))
    return CheckResult(True, ", ".join(names[:6]))


def _abs_am_url(href: str) -> str:
    href = href.replace("&amp;", "&").strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return "https://forums.alliedmods.net/" + href.lstrip("/")


def parse_am_attachments(html: str) -> list[tuple[str, str, str]]:
    named: dict[str, str] = {}
    urls: dict[str, str] = {}
    for m in AM_ATTACH_HREF_RE.finditer(html):
        urls[m.group(2)] = _abs_am_url(m.group(1))
    for m in AM_ATTACH_LABEL_RE.finditer(html):
        aid = m.group(2)
        urls[aid] = _abs_am_url(m.group(1))
        label = re.sub(r"\s+", " ", m.group(3)).strip()
        fname = original_filename(label)
        if fname:
            named[aid] = fname
    for m in AM_ATTACH_NAMED_RE.finditer(html):
        fname = original_filename(m.group(2))
        if fname:
            named[m.group(1)] = fname
    for m in AM_ATTACH_TABLE_RE.finditer(html):
        named[m.group(2)] = Path(m.group(1).strip()).name
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    order = list(urls) + [aid for aid in named]
    for aid in order:
        if aid in seen:
            continue
        seen.add(aid)
        url = urls.get(aid) or f"https://forums.alliedmods.net/attachment.php?attachmentid={aid}"
        out.append((aid, named.get(aid, ""), url))
    return out


def compile_sp(game_dir: Path, sp_path: Path, dest_smx: Path) -> None:
    spcomp = find_spcomp(game_dir)
    if not spcomp:
        raise RuntimeError("找不到 addons/sourcemod/scripting/spcomp.exe，无法编译 .sp")
    dest_smx.parent.mkdir(parents=True, exist_ok=True)
    include = sm_root(game_dir) / "scripting" / "include"
    local_smx = sp_path.with_suffix(".smx")
    last_output = ""
    for _attempt in range(5):
        if local_smx.is_file() and local_smx.resolve() != dest_smx.resolve():
            local_smx.unlink()
        result = subprocess.run(
            [str(spcomp), sp_path.name, f"-o{local_smx.name}", f"-i{include}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(sp_path.parent),
        )
        last_output = (result.stdout or "") + (result.stderr or "")
        produced = local_smx if local_smx.is_file() else None
        if produced is None:
            alt = sp_path.parent / f"{sp_path.stem}.smx"
            if alt.is_file():
                produced = alt
        if result.returncode == 0 and produced is not None and produced.is_file():
            if produced.resolve() != dest_smx.resolve():
                if dest_smx.is_file():
                    dest_smx.unlink()
                shutil.move(str(produced), str(dest_smx))
            return
        missing = parse_missing_includes(last_output)
        if not missing:
            break
        got_any = False
        for name in missing:
            found = locate_cached_include(name, extra_roots=iter_repo_include_dirs(sp_path.parent))
            if found is None:
                print(f"   缺少 include: {name}（仓库 include 中未找到）")
                continue
            dest = install_found_include(found, game_dir)
            print(f"   已从仓库补全 include: {dest.relative_to(sm_root(game_dir))}")
            got_any = True
        if not got_any:
            break
    raise RuntimeError(last_output.strip() or "编译失败")


def extract_zip_to_sourcemod(
    data: bytes,
    game_dir: Path,
    recompile_existing: bool = False,
) -> list[Path]:
    copied: list[Path] = []
    sm = sm_root(game_dir)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        prefix = ""
        for marker in ("addons/sourcemod/", "addons\\sourcemod\\"):
            hit = next((n for n in names if marker.replace("\\", "/") in n.replace("\\", "/")), "")
            if hit:
                idx = hit.replace("\\", "/").index("addons/sourcemod/")
                prefix = hit.replace("\\", "/")[: idx + len("addons/sourcemod/")]
                break
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("\\", "/")
            if prefix:
                if not rel.startswith(prefix):
                    continue
                out = sm / rel[len(prefix) :]
            else:
                parts = Path(rel).parts
                mapped = None
                for i, part in enumerate(parts):
                    if part.lower() in SM_DIR_MAP:
                        mapped = Path(SM_DIR_MAP[part.lower()]).joinpath(*parts[i + 1 :])
                        break
                if mapped is None:
                    continue
                out = sm / mapped
            if out.name.lower() in SKIP_FILE_NAMES:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            copied.append(out)
    copied.extend(compile_copied_scripts(game_dir, copied, recompile_existing=recompile_existing))
    return copied


def install_memoryex(game_dir: Path) -> str:
    repo = cache_git_repo("dragokas/Memory-Extended")
    inc = sm_root(game_dir) / "scripting" / "include"
    shutil.copy2(repo / "MemoryEx.inc", inc / "MemoryEx.inc")
    dest_dir = inc / "MemoryEx"
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(repo / "MemoryEx", dest_dir)
    return "已安装 MemoryEx.inc 到 scripting/include"


def install_sendproxy(game_dir: Path) -> str:
    data = http_json("https://api.github.com/repos/jensewe/Left4SendProxy/releases/latest")
    assets = data.get("assets") or []
    win = [a for a in assets if "win" in a["name"].lower()]
    pick = next((a for a in win if "sm1.12" in a["name"].lower()), None)
    pick = pick or next((a for a in win if "smlatest" in a["name"].lower()), None)
    pick = pick or (win[0] if win else None)
    if not pick:
        raise RuntimeError("Left4SendProxy 发行版里没有 Windows 包")
    blob = http_bytes(pick["browser_download_url"])
    copied = extract_zip_to_sourcemod(blob, game_dir)
    return f"已安装 sendproxy（{pick['name']}，{len(copied)} 个文件）"


def github_file_bytes(owner: str, repo: str, path: str, branch: str = "main") -> bytes:
    api = f"https://api.github.com/repos/{owner}/{repo}/contents/{quote(path, safe='/')}?ref={branch}"
    data = http_json(api, fatal=False)
    if isinstance(data, dict) and data.get("download_url"):
        return http_bytes(data["download_url"])
    if isinstance(data, dict) and data.get("content"):
        import base64
        return base64.b64decode(data["content"])
    raise RuntimeError(f"无法下载 {owner}/{repo}/{path}")


def download_github_dir(owner: str, repo: str, path: str, dest: Path, branch: str = "main") -> int:
    dest.mkdir(parents=True, exist_ok=True)
    api = f"https://api.github.com/repos/{owner}/{repo}/contents/{quote(path, safe='/')}?ref={branch}"
    data = http_json(api, fatal=False)
    if not isinstance(data, list):
        raise RuntimeError(f"无法列出 {owner}/{repo}/{path}")
    n = 0
    for item in data:
        name = item.get("name") or ""
        if not name or name.lower() in SKIP_FILE_NAMES:
            continue
        if item.get("type") == "dir":
            n += download_github_dir(owner, repo, item.get("path") or f"{path}/{name}", dest / name, branch)
            continue
        if item.get("type") != "file":
            continue
        dl = item.get("download_url")
        blob = http_bytes(dl) if dl else github_file_bytes(owner, repo, item.get("path") or f"{path}/{name}", branch)
        write_bytes(dest / name, blob)
        n += 1
    return n


def install_l4d2_weapons(game_dir: Path) -> str:
    blob = github_file_bytes(
        "fbef0102",
        "Game-Private_Plugin",
        "L4D_插件/Require_檔案/scripting/include/l4d2_weapons.inc",
        "main",
    )
    dest = sm_root(game_dir) / "scripting" / "include" / "l4d2_weapons.inc"
    write_bytes(dest, blob)
    return "已安装 l4d2_weapons.inc"


def _zombie_spawn_fix_sources(game_dir: Path) -> tuple[Path, Path]:
    """Return (sp, gamedata) paths to install from. Prefer local patch pack, else GitHub cache."""
    local = Path(__file__).resolve().parent / "patches" / "zombie_spawn_fix"
    sp = local / "zombie_spawn_fix.sp"
    gd = local / "zombie_spawn_fix.txt"
    if sp.is_file() and gd.is_file():
        return sp, gd
    repo = cache_git_repo("umlka/l4d2")
    src = repo / "zombie_spawn_fix"
    sp = src / "zombie_spawn_fix.sp"
    gd = src / "zombie_spawn_fix.txt"
    if not sp.is_file() or not gd.is_file():
        raise RuntimeError("找不到 zombie_spawn_fix.sp / zombie_spawn_fix.txt 源文件")
    return sp, gd


def remove_zombie_spawn_fix_manager_config(game_dir: Path) -> bool:
    """Do not install configs/sourcescramble/zombie_spawn_fix.txt (dual MemPatch with .smx)."""
    sm = sm_root(game_dir)
    removed = False
    for path in (
        sm / "configs" / "sourcescramble" / "zombie_spawn_fix.txt",
        sm / "configs" / "sourcescramble" / "zombie_spawn_fix.txt.disabled_by_plugin",
    ):
        if path.is_file():
            try:
                path.unlink()
                removed = True
            except OSError:
                pass
    return removed


def is_zombie_spawn_fix_manager_config(path: Path) -> bool:
    """True for configs/sourcescramble/zombie_spawn_fix.txt (must never be installed)."""
    parts = [p.lower() for p in path.parts]
    try:
        i = parts.index("sourcescramble")
    except ValueError:
        return False
    return i > 0 and parts[i - 1] == "configs" and path.name.lower() == "zombie_spawn_fix.txt"


def install_zombie_spawn_fix(game_dir: Path) -> str:
    """Only gamedata + compiled plugins/zombie_spawn_fix.smx; never sourcescramble manager cfg."""
    sm = sm_root(game_dir)
    sp_src, gd_src = _zombie_spawn_fix_sources(game_dir)
    sp_dest = sm / "scripting" / "zombie_spawn_fix.sp"
    gd_dest = sm / "gamedata" / "zombie_spawn_fix.txt"
    smx_dest = sm / "plugins" / "zombie_spawn_fix.smx"
    write_bytes(sp_dest, sp_src.read_bytes())
    write_bytes(gd_dest, gd_src.read_bytes())
    compile_sp(game_dir, sp_dest, smx_dest)
    if not smx_dest.is_file() or not looks_like_smx(smx_dest.read_bytes()):
        raise RuntimeError("zombie_spawn_fix.sp 编译失败，未生成有效 .smx")
    removed = remove_zombie_spawn_fix_manager_config(game_dir)
    msg = "已安装 zombie_spawn_fix（gamedata + plugins/*.smx）"
    if removed:
        msg += "；已移除 configs/sourcescramble/zombie_spawn_fix.txt"
    return msg


def install_spawn_infected_nolimit(game_dir: Path) -> str:
    return install_from_github_url(SPAWN_INFECTED_NOLIMIT_URL, game_dir, hint="spawn_infected_nolimit")


def install_unrestrict_panic(game_dir: Path) -> str:
    return install_from_github_url(UNRESTRICT_PANIC_URL, game_dir, hint="l4d_unrestrict_panic_battlefield")


def install_witch_prevent_target_loss(game_dir: Path) -> str:
    repo = cache_git_repo("LuxLuma/Left-4-fix")
    src = repo / "left 4 fix" / "witch" / "witch_prevent_target_loss"
    copied = copy_sm_tree(src, game_dir)
    smx = sm_root(game_dir) / "plugins" / "witch_prevent_target_loss.smx"
    if not smx.is_file():
        sp = sm_root(game_dir) / "scripting" / "witch_prevent_target_loss.sp"
        if not sp.is_file():
            hits = list(src.rglob("*.sp"))
            if hits:
                sp = sm_root(game_dir) / "scripting" / hits[0].name
                shutil.copy2(hits[0], sp)
        if sp.is_file():
            compile_sp(game_dir, sp, smx)
    return f"已安装 witch_prevent_target_loss（{len(copied)} 个文件）"


def alliedmods_page_urls(url: str) -> list[str]:
    out: list[str] = []

    def add(u: str) -> None:
        u = (u or "").strip()
        if u and u not in out:
            out.append(u)

    add(url)
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    path = (parsed.path or "").lower()
    pid = (qs.get("p") or [""])[0]
    tid = (qs.get("t") or [""])[0]
    if "showpost.php" in path and pid:
        add(f"https://forums.alliedmods.net/showthread.php?p={pid}")
    if tid:
        add(f"https://forums.alliedmods.net/showthread.php?t={tid}")
    return out


def am_url_ids(url: str) -> set[str]:
    qs = parse_qs(urlparse(url or "").query)
    ids = set()
    for key in ("t", "p", "threadid"):
        ids.update(str(v) for v in (qs.get(key) or []) if v)
    return ids


def forced_am_sp_url(name: str = "", slug: str = "", url: str = "") -> str:
    blob = re.sub(r"[^\w.]+", "_", " ".join([name or "", slug or "", url or ""]).lower())
    if any(
        x in blob
        for x in (
            "309656",
            "170776",
            "command_buffer",
            "buffer_overflow_fixer",
            "command_and_convar",
        )
    ):
        return COMMAND_BUFFER_SP_URL
    if any(x in blob for x in ("336298", "193611", "l4d2_ladder_patch", "ladder_server_crash")):
        return LADDER_PATCH_SP_URL
    if any(x in blob for x in ("328327", "188755", "remove_item_collision", "carryables_collision")) or (
        "remove_weapons" in blob and "collision" in blob
    ):
        return REMOVE_ITEM_COLLISION_SP_URL
    return ""


def am_source_sp_spec(url: str, name: str = "", slug: str = "") -> dict | None:
    qs = parse_qs(urlparse(url or "").query)
    for aid in qs.get("attachmentid") or []:
        spec = AM_SOURCE_SP_BY_AID.get(str(aid))
        if spec:
            out = dict(spec)
            if "attachment.php" in (url or ""):
                out["url"] = url
            return out
    forced = forced_am_sp_url(name, slug, url)
    if not forced:
        return None
    aid = (parse_qs(urlparse(forced).query).get("attachmentid") or [""])[0]
    out = dict(AM_SOURCE_SP_BY_AID[aid])
    out["url"] = forced
    return out


def am_force_local_compile(url: str, name: str = "", slug: str = "") -> bool:
    return am_source_sp_spec(url, name, slug) is not None


def install_am_direct_sp(spec: dict, game_dir: Path, remember_url: str = "") -> str:
    sm = sm_root(game_dir)
    am = get_am_session()
    dest = sm / "scripting" / spec["name"]
    smx = sm / "plugins" / f"{Path(spec['name']).stem}.smx"
    print(f"   下载源码 {spec['name']}")
    blob = am.fetch(spec["url"])
    if not blob or is_cloudflare_challenge(blob) or not looks_like_sourcepawn(blob):
        hint = (blob or b"").lstrip()[:160].decode("utf-8", errors="replace").replace("\n", " ")
        raise RuntimeError(f"未能下载源码 {spec['name']}: {spec['url']}（内容: {hint or '空'}）")
    write_bytes(dest, blob)
    print(f"   编译 {dest.name} -> plugins/{smx.name}")
    compile_sp(game_dir, dest, smx)
    remember_am_install(remember_url or spec["url"], [dest.name, smx.name])
    return f"已下载源码并编译: {dest.name} -> {smx.name}"


def looks_like_smx(data: bytes) -> bool:
    """SourceMod 字节码以 FFPS 开头；论坛常把源码/图片误标成 .smx。"""
    if not data or len(data) < 4:
        return False
    return data[:4] == b"FFPS"


def looks_like_png(data: bytes) -> bool:
    return bool(data) and data[:8] == b"\x89PNG\r\n\x1a\n"


def looks_like_sourcepawn(data: bytes) -> bool:
    if looks_like_smx(data) or looks_like_png(data) or (data[:2] == b"PK"):
        return False
    # Gamedata KeyValues often contain /* comments */ — must not count as .sp
    if looks_like_gamedata(data):
        return False
    text = data.lstrip()[:32768].decode("utf-8", errors="ignore")
    if not text:
        return False
    start = text.lstrip()
    low = start[:400].lower()
    if start.startswith("<") or low.startswith("<!doctype") or "<html" in low:
        return False
    return any(
        s in text
        for s in (
            "#include",
            "#pragma",
            "public Plugin",
            "public void OnPluginStart",
            "#define PLUGIN_",
        )
    )


def fetch_am_plugin_source(am: AlliedModsSession, file_id: str) -> bytes:
    urls = [
        f"https://www.sourcemod.net/vbcompiler.php?file_id={file_id}&download=1",
        f"https://forums.alliedmods.net/vbcompiler.php?file_id={file_id}&download=1",
        f"https://www.sourcemod.net/vbcompiler.php?file_id={file_id}&action=source",
    ]
    last_err: Exception | None = None
    for url in urls:
        try:
            blob = am.fetch(url)
        except Exception as e:
            last_err = e
            continue
        if blob and looks_like_sourcepawn(blob):
            return blob
    extra = f" ({last_err})" if last_err else ""
    raise RuntimeError(f"未能下载论坛源码 file_id={file_id}{extra}")


def install_from_alliedmods(req: Requirement, game_dir: Path) -> str:
    sm = sm_root(game_dir)
    installed: list[str] = []
    if dep_merge_key(req) == "zombie_spawn_fix" or "333351" in (req.url or ""):
        return install_zombie_spawn_fix(game_dir)
    spec = am_source_sp_spec(req.url, req.name, req.slug)
    if spec:
        return install_am_direct_sp(spec, game_dir, req.url)
    am = get_am_session()
    html = ""
    last_err: Exception | None = None
    for page in alliedmods_page_urls(req.url):
        try:
            html = html_unescape(am.fetch(page).decode("utf-8", errors="replace"))
            if html:
                break
        except Exception as e:
            last_err = e
            html = ""
    if not html and spec is None:
        raise last_err or RuntimeError("论坛页下载失败")
    source_sp = parse_am_plugin_source_name(html) if html else ""
    compiler_ids = AM_COMPILER_RE.findall(html) if html else []
    attachments = parse_am_attachments(html) if html else []
    copied_paths: list[Path] = []
    force_src = spec is not None
    spec_aids = set()
    if spec:
        spec_aids = set(parse_qs(urlparse(spec["url"]).query).get("attachmentid") or [])
        print(f"   下载指定源码 {spec['name']}，用本地 spcomp 编译")
        blob = am.fetch(spec["url"])
        if not blob or is_cloudflare_challenge(blob) or not looks_like_sourcepawn(blob):
            raise RuntimeError(f"未能下载源码 {spec['name']}: {spec['url']}")
        dest = sm / "scripting" / spec["name"]
        write_bytes(dest, blob)
        copied_paths.append(dest)
        installed.append(dest.name)
        smx = sm / "plugins" / f"{Path(spec['name']).stem}.smx"
        print(f"   编译 {dest.name} -> plugins/{smx.name}")
        compile_sp(game_dir, dest, smx)
        copied_paths.append(smx)
        installed.append(smx.name)
        source_sp = spec["name"]
    elif compiler_ids and source_sp and not force_src:
        file_id = compiler_ids[0]
        compiler = f"https://www.sourcemod.net/vbcompiler.php?file_id={file_id}"
        try:
            blob = am.fetch(compiler)
        except Exception:
            blob = http_bytes(compiler)
        smx_name = Path(source_sp).with_suffix(".smx").name
        dest = sm / "plugins" / smx_name
        if blob.lstrip().startswith(b"<") or blob.lstrip().lower().startswith(b"<!doctype"):
            raise RuntimeError("AlliedModders 编译器返回了网页而不是 .smx")
        if looks_like_sourcepawn(blob):
            # 在线编译器有时返回源码；改走本地编译
            sp_dest = sm / "scripting" / Path(source_sp).with_suffix(".sp").name
            write_bytes(sp_dest, blob)
            copied_paths.append(sp_dest)
            installed.append(sp_dest.name)
            print(f"   在线编译器返回源码，改用本地编译 {sp_dest.name}")
            compile_sp(game_dir, sp_dest, dest)
            copied_paths.append(dest)
            installed.append(dest.name)
        elif looks_like_smx(blob):
            write_bytes(dest, blob)
            copied_paths.append(dest)
            installed.append(dest.name)
        else:
            raise RuntimeError(
                f"AlliedModders 编译器返回了无效内容（非 .smx，头: {blob[:8]!r}）"
            )
    elif compiler_ids and not source_sp:
        print("   论坛页未解析到原 .sp 文件名，跳过按标题改名的编译下载，改为只保存原附件")
    for aid, filename, attach_url in attachments:
        if aid in spec_aids:
            continue
        if spec and (filename or "").lower() == spec["name"].lower():
            continue
        blob = b""
        try:
            blob = am.fetch(attach_url)
        except Exception:
            try:
                blob = am.fetch(f"https://forums.alliedmods.net/attachment.php?attachmentid={aid}")
            except Exception:
                try:
                    blob = http_bytes(f"https://www.sourcemod.net/vbcompiler.php?file_id={aid}")
                except Exception:
                    blob = b""
        if not blob or is_cloudflare_challenge(blob) or blob.lstrip().startswith(b"<"):
            continue
        if looks_like_png(blob):
            print(f"   跳过图片附件 {aid}（不是插件）")
            continue
        name = original_filename(filename) or original_filename(attach_url)
        # 按内容纠正扩展名，避免源码/图片被存成 .smx
        if looks_like_smx(blob):
            if not name or not name.lower().endswith(".smx"):
                stem = Path(name or source_sp or f"am_{aid}").stem
                name = f"{stem}.smx"
        elif looks_like_sourcepawn(blob):
            if not name or name.lower().endswith((".smx", ".txt", ".png", ".jpg")):
                stem = Path(name or source_sp or f"am_{aid}").stem
                name = f"{stem}.sp"
        elif looks_like_gamedata(blob):
            if not name or not name.lower().endswith(".txt"):
                stem = Path(name or source_sp or f"am_{aid}").stem
                name = f"{stem}.txt"
        if not name:
            if looks_like_gamedata(blob) and source_sp:
                name = Path(source_sp).with_suffix(".txt").name
            elif looks_like_sourcepawn(blob) and source_sp:
                name = Path(source_sp).with_suffix(".sp").name
            elif looks_like_smx(blob) and source_sp:
                name = Path(source_sp).with_suffix(".smx").name
        if not name:
            print(f"   跳过未识别文件名的附件 {aid}")
            continue
        if blob[:2] == b"PK":
            copied = extract_zip_to_sourcemod(blob, game_dir, recompile_existing=force_src)
            copied_paths.extend(copied)
            installed.extend(p.name for p in copied[:5])
            continue
        if looks_like_gamedata(blob):
            dest = sm / "gamedata" / Path(name).with_suffix(".txt").name
            write_bytes(dest, blob)
            copied_paths.append(dest)
            installed.append(dest.name)
            continue
        text_head = blob[:80].decode("utf-8", errors="ignore")
        if (
            name.lower().endswith(".sp")
            or looks_like_sourcepawn(blob)
            or "#include" in text_head
            or blob.strip().startswith(b"#")
            or blob.lstrip().startswith(b"/*")
        ):
            sp_name = Path(name).with_suffix(".sp").name
            dest = sm / "scripting" / sp_name
            write_bytes(dest, blob)
            copied_paths.append(dest)
            installed.append(dest.name)
            smx = sm / "plugins" / f"{Path(sp_name).stem}.smx"
            try:
                compile_sp(game_dir, dest, smx)
                if not looks_like_smx(smx.read_bytes()):
                    raise RuntimeError("编译产出不是有效 .smx")
                copied_paths.append(smx)
                installed.append(smx.name)
            except Exception as e:
                installed.append(f"{dest.name}（未编译: {e}）")
            continue
        if name.lower().endswith(".inc"):
            dest = sm / "scripting" / "include" / name
            write_bytes(dest, blob)
            copied_paths.append(dest)
            installed.append(dest.name)
            continue
        if name.lower().endswith(".smx"):
            if force_src:
                print(f"   跳过论坛 smx {name}，改用本地编译")
                continue
            if not looks_like_smx(blob):
                print(f"   跳过伪 .smx 附件 {name}（内容不是插件字节码）")
                continue
            dest = sm / "plugins" / name
            write_bytes(dest, blob)
            copied_paths.append(dest)
            installed.append(dest.name)
    copied_paths.extend(ensure_gamedata_for_copied(game_dir, copied_paths))
    if force_src:
        copied_paths.extend(compile_copied_scripts(game_dir, copied_paths, recompile_existing=True))
    remember_am_install(req.url, [p.name for p in copied_paths if p.suffix.lower() in {".smx", ".sp", ".txt", ".inc"}])
    if not installed:
        raise RuntimeError("论坛页里没有找到可下载附件（请确认已勾选 Cloudflare 验证）")
    if force_src and not any(p.suffix.lower() == ".smx" for p in copied_paths):
        raise RuntimeError("已改为本地编译，但没有生成 .smx（请确认源码已下载且 spcomp.exe 可用）")
    return "已从 AlliedModders 最新帖安装: " + ", ".join(installed[:8])


def looks_like_gamedata(data: bytes) -> bool:
    head = data[:4000].decode("utf-8", errors="replace")
    return any(s in head for s in ('"Games"', '"Signatures"', '"MemPatches"', '"Offsets"'))


def classify_sm_dest(sm: Path, filename: str, data: bytes | None = None) -> Path | None:
    name = filename.lower()
    if name in SKIP_FILE_NAMES:
        return None
    if data is not None:
        if looks_like_png(data):
            return None
        if looks_like_smx(data):
            stem = Path(filename).stem + ".smx"
            return sm / "plugins" / stem
        if looks_like_sourcepawn(data) and not name.endswith(".inc"):
            stem = Path(filename).stem + ".sp"
            return sm / "scripting" / stem
    if name.endswith(".smx"):
        if data is not None and not looks_like_smx(data):
            return None
        return sm / "plugins" / filename
    if name.endswith((".dll", ".so", ".dylib")) or ".ext." in name or name.endswith(".autoload"):
        return sm / "extensions" / filename
    if name.endswith(".sp"):
        return sm / "scripting" / filename
    if name.endswith(".inc"):
        return sm / "scripting" / "include" / filename
    if name.endswith(".phrases.txt"):
        return sm / "translations" / filename
    if name.endswith(".txt") and (data is None or looks_like_gamedata(data)):
        return sm / "gamedata" / filename
    return None


def _should_skip_compile_sp(sp: Path) -> bool:
    """跳过测试样本源码，例如 builtinvotes_test.sp。"""
    stem = sp.stem.lower()
    if stem.endswith("_test") or stem.endswith("-test"):
        return True
    return stem in {"builtinvotes_test"}


def compile_copied_scripts(
    game_dir: Path,
    copied: list[Path],
    recompile_existing: bool = False,
) -> list[Path]:
    extra: list[Path] = []
    sm = sm_root(game_dir)
    scripting = sm / "scripting"
    plugins = sm / "plugins"
    include = scripting / "include"
    scripting.mkdir(parents=True, exist_ok=True)
    plugins.mkdir(parents=True, exist_ok=True)
    provided_smx = {p.stem.lower() for p in copied if p.suffix.lower() == ".smx"}
    sources: list[Path] = []
    seen: set[str] = set()
    for sp in copied:
        if not sp.is_file() or sp.suffix.lower() != ".sp":
            continue
        if _is_under(sp, include):
            continue
        if _is_under(sp, scripting) and sp.parent.resolve() != scripting.resolve():
            continue
        dest_sp = sp
        if not _is_under(sp, scripting):
            dest_sp = scripting / sp.name
            dest_sp.parent.mkdir(parents=True, exist_ok=True)
            if dest_sp.resolve() != sp.resolve():
                shutil.copy2(sp, dest_sp)
                if _is_under(sp, plugins):
                    try:
                        sp.unlink()
                    except OSError:
                        pass
        key = str(dest_sp.resolve())
        if key in seen:
            continue
        seen.add(key)
        sources.append(dest_sp)
    for sp in sources:
        if _should_skip_compile_sp(sp):
            print(f"   跳过测试源码（不编译）: {sp.name}")
            continue
        if (not recompile_existing) and sp.stem.lower() in provided_smx:
            continue
        smx = plugins / f"{sp.stem}.smx"
        try:
            print(f"   编译 {sp.name} -> plugins/{smx.name}")
            compile_sp(game_dir, sp, smx)
            extra.append(smx)
        except Exception as e:
            print(f"   编译 {sp.name} 失败: {e}")
            log_failure(f"编译失败: {sp.name}", e)
    extra.extend(ensure_gamedata_for_copied(game_dir, copied + extra))
    return extra


def install_plugin_tree(src: Path, game_dir: Path, hint: str = "") -> str:
    sm = sm_root(game_dir)
    copied = copy_sm_tree(src, game_dir)
    for cand in (src / "addons" / "sourcemod", src / "sourcemod"):
        if cand.is_dir():
            copied.extend(copy_sm_tree(cand, game_dir))
            break
    if not copied:
        for cand in src.rglob("*"):
            if cand.is_dir() and cand.name.lower() == "sourcemod" and (cand / "plugins").is_dir():
                copied = copy_sm_tree(cand, game_dir)
                break
    if src.is_dir():
        for file in src.iterdir():
            if not file.is_file() or file.name.lower() in SKIP_FILE_NAMES:
                continue
            data = file.read_bytes()
            dest = classify_sm_dest(sm, file.name, data)
            if dest is None:
                continue
            write_bytes(dest, data)
            copied.append(dest)
    copied.extend(install_repo_compile_includes(src, game_dir))
    global _COMPILE_SEARCH_ROOTS
    prev_roots = list(_COMPILE_SEARCH_ROOTS)
    _COMPILE_SEARCH_ROOTS = prev_roots + [src] + iter_repo_include_dirs(src)
    try:
        copied.extend(compile_copied_scripts(game_dir, copied))
    finally:
        _COMPILE_SEARCH_ROOTS = prev_roots
    if not copied:
        raise RuntimeError(f"{src} 中没有可安装的 SourceMod 文件")
    label = hint or src.name
    return f"已安装 {label}（{len(copied)} 个文件）"


def install_blob_bytes(game_dir: Path, filename: str, data: bytes) -> Path:
    sm = sm_root(game_dir)
    dest = classify_sm_dest(sm, filename, data)
    if dest is None:
        dest = sm / "plugins" / filename
    write_bytes(dest, data)
    return dest


def try_fetch_sibling_gamedata(owner: str, repo: str, branch: str, file_parts: list[str], game_dir: Path) -> Path | None:
    if not file_parts:
        return None
    parts = list(file_parts)
    if parts[-1].lower().endswith(".sp"):
        parts[-1] = Path(parts[-1]).stem + ".txt"
    else:
        return None
    if "scripting" in [p.lower() for p in parts]:
        i = [p.lower() for p in parts].index("scripting")
        parts[i] = "gamedata"
    else:
        parts = parts[:-1] + ["gamedata", parts[-1]]
        if len(file_parts) >= 2:
            parts = file_parts[:-1] + [Path(file_parts[-1]).stem + ".txt"]
    rel = "/".join(parts)
    try:
        blob = github_file_bytes(owner, repo, rel, branch)
    except Exception:
        alt = "/".join(file_parts[:-1] + [Path(file_parts[-1]).stem + ".txt"])
        if alt == rel:
            return None
        try:
            blob = github_file_bytes(owner, repo, alt, branch)
        except Exception:
            return None
    if not looks_like_gamedata(blob) and not file_parts[-1].lower().endswith(".sp"):
        return None
    dest = sm_root(game_dir) / "gamedata" / Path(rel).name
    write_bytes(dest, blob)
    return dest


def unpack_plugin_archive(blob: bytes, game_dir: Path, filename: str = "") -> list[Path]:
    copied: list[Path] = []
    if blob[:2] == b"PK":
        copied = extract_zip_to_sourcemod(blob, game_dir)
        if not copied:
            copied = extract_game_zip(blob, game_dir)
        if not copied:
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    data_f = zf.read(info)
                    dest = classify_sm_dest(sm_root(game_dir), Path(info.filename).name, data_f)
                    if dest is None:
                        continue
                    write_bytes(dest, data_f)
                    copied.append(dest)
    elif filename:
        copied = [install_blob_bytes(game_dir, filename, blob)]
    copied.extend(compile_copied_scripts(game_dir, copied))
    return copied


def install_github_release(owner: str, repo: str, game_dir: Path) -> str:
    data = http_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
    assets = data.get("assets") or []
    if not assets:
        raise RuntimeError(f"{owner}/{repo} 没有发行附件")
    tag = str(data.get("tag_name") or "")

    def score(name: str) -> int:
        n = name.lower()
        if any(x in n for x in ("linux", ".tar", "ubuntu", "debian")):
            return -100
        s = 1
        if n.endswith(".zip"):
            s += 20
        if n.endswith(".smx"):
            s += 15
        if "windows" in n or re.search(r"(?:^|[._-])win(?:dows)?(?:[._-]|$)", n):
            s += 50
        if "sm1.12" in n:
            s += 30
        elif "smlatest" in n:
            s += 8
        return s

    ranked = sorted(assets, key=lambda a: score(a["name"]), reverse=True)
    if not ranked or score(ranked[0]["name"]) < 0:
        raise RuntimeError(f"{owner}/{repo} 发行版没有 Windows 包")
    pick = ranked[0]
    blob = http_bytes(pick["browser_download_url"])
    copied = unpack_plugin_archive(blob, game_dir, pick["name"])
    if not copied:
        raise RuntimeError(f"无法从 {pick['name']} 抽出插件文件")
    label = f"{tag} {pick['name']}".strip()
    return f"已从发行版安装 {label}（{len(copied)} 个文件）"


def install_from_github_url(url: str, game_dir: Path, hint: str = "") -> str:
    raw = github_raw_url(url)
    m = GITHUB_REPO_RE.search(url)
    if not m:
        raise RuntimeError(f"无法解析 GitHub 地址: {url}")
    owner, repo = normalize_github_slug(f"{m.group(1)}/{m.group(2)}").split("/", 1)
    if "/releases" in url:
        return install_github_release(owner, repo, game_dir)
    if raw.endswith(".inc") or (("/blob/" in url) and url.lower().endswith(".inc")):
        name = Path(urlparse(raw).path).name
        dest = sm_root(game_dir) / "scripting" / "include" / name
        write_bytes(dest, http_bytes(raw))
        return f"已下载 {name}"
    parsed = urlparse(url)
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    kind = parts[2] if len(parts) > 2 else ""
    branch = ""
    rest: list[str] = []
    if kind in {"blob", "tree", "raw"} and len(parts) > 3:
        branch = parts[3]
        rest = parts[4:]
    if kind == "blob" and rest:
        rel = "/".join(rest)
        blob = github_file_bytes(owner, repo, rel, branch)
        dest = install_blob_bytes(game_dir, rest[-1], blob)
        copied = [dest]
        gd = try_fetch_sibling_gamedata(owner, repo, branch, rest, game_dir)
        if gd:
            copied.append(gd)
        copied.extend(compile_copied_scripts(game_dir, copied))
        return f"已安装 {hint or dest.name}（{len(copied)} 个文件）"
    local = cache_git_repo(f"{owner}/{repo}", branch if branch else "")
    sub = local.joinpath(*rest) if rest else local
    if not sub.exists():
        raise RuntimeError(f"缓存中找不到路径: {sub}")
    global _COMPILE_SEARCH_ROOTS
    prev_roots = list(_COMPILE_SEARCH_ROOTS)
    _COMPILE_SEARCH_ROOTS = prev_roots + [local, sub] + iter_repo_include_dirs(sub)
    try:
        install_repo_compile_includes(local, game_dir)
        if sub.is_file():
            data = sub.read_bytes()
            dest = install_blob_bytes(game_dir, sub.name, data)
            copied = [dest]
            copied.extend(compile_copied_scripts(game_dir, copied))
            return f"已安装 {hint or dest.name}（{len(copied)} 个文件）"
        return install_plugin_tree(sub, game_dir, hint or sub.name)
    finally:
        _COMPILE_SEARCH_ROOTS = prev_roots


def install_resolve_collision_fix(game_dir: Path) -> str:
    sm = sm_root(game_dir)
    copied = 0
    dll = github_file_bytes(
        "SirPlease",
        "L4D2-Competitive-Rework",
        "addons/sourcemod/extensions/l4d2_resolve_collision_fix.ext.2.l4d2.dll",
        "master",
    )
    dest_dll = sm / "extensions" / "l4d2_resolve_collision_fix.ext.2.l4d2.dll"
    write_bytes(dest_dll, dll)
    copied += 1
    gd = github_file_bytes(
        "Vinillia",
        "resolve-collision-fix",
        "sourcemod/gamedata/l4d2_resolve_collision.txt",
        "master",
    )
    write_bytes(sm / "gamedata" / "l4d2_resolve_collision.txt", gd)
    copied += 1
    autoload = sm / "extensions" / "l4d2_resolve_collision_fix.autoload"
    if not autoload.is_file():
        autoload.write_text("", encoding="utf-8")
        copied += 1
    return f"已安装 l4d2_resolve_collision_fix（{copied} 个文件）"


def install_sceneprocessor(game_dir: Path) -> str:
    last_err: Exception | None = None
    for url in (
        "https://forums.alliedmods.net/showthread.php?p=2766130",
        "https://forums.alliedmods.net/showthread.php?t=241585&page=6",
        "https://forums.alliedmods.net/showthread.php?t=241585&goto=newpost",
    ):
        req = Requirement(name="sceneprocessor", url=url, slug="sceneprocessor")
        try:
            return install_from_alliedmods(req, game_dir)
        except Exception as e:
            last_err = e
    raise RuntimeError(last_err or "sceneprocessor 最新版下载失败")


INSTALLERS = {
    "memoryex": install_memoryex,
    "sendproxy": install_sendproxy,
    "l4d2_weapons": install_l4d2_weapons,
    "zombie_spawn_fix": install_zombie_spawn_fix,
    "spawn_infected_nolimit": install_spawn_infected_nolimit,
    "l4d_unrestrict_panic_battlefield": install_unrestrict_panic,
    "witch_prevent_target_loss": install_witch_prevent_target_loss,
    "l4d2_resolve_collision_fix": install_resolve_collision_fix,
    "sceneprocessor": install_sceneprocessor,
}


def install_extra_requires_for(plugin_name: str, env: LocalEnv, dry_run: bool) -> list[str]:
    rows = PLUGIN_EXTRA_REQUIRES.get((plugin_name or "").lower().replace("-", "_"), [])
    if not rows:
        return []
    msgs: list[str] = []
    current = env
    for name, url in rows:
        req = Requirement(name=name, url=url, slug=name)
        if check_requirement(req, current).ok:
            continue
        print(f"   Require: {name}")
        msgs.append(try_install_requirement(req, current, dry_run))
        current = scan_local_env(current.game_dir)
    return msgs


def with_plugin_extras(names: list[str], env: LocalEnv, dry_run: bool, msg: str) -> str:
    notes: list[str] = []
    seen: set[str] = set()
    for raw in names:
        key = re.sub(r"[^\w]+", "_", (raw or "").lower()).strip("_")
        if not key or key in seen:
            continue
        seen.add(key)
        notes.extend(install_extra_requires_for(key, env, dry_run))
    if notes:
        return msg + "；同时安装 Require: " + "；".join(notes)
    return msg


def try_install_requirement(req: Requirement, env: LocalEnv, dry_run: bool) -> str:
    key = dep_merge_key(req)
    url = (req.url or "").lower()
    env_fn = lookup_plugin_installer(key)
    extra_names = [key, req.slug or "", req.name]
    if env_fn and key not in {"metamod", "sourcemod"}:
        if dry_run:
            return f"预览: 将安装依赖 {key}"
        return with_plugin_extras(extra_names, env, dry_run, env_fn(env.game_dir))
    install_url = REQUIRE_INSTALL_URLS.get(key)
    if install_url:
        if dry_run:
            return f"预览: 将从 {install_url} 安装"
        fn = INSTALLERS.get(key) or lookup_plugin_installer(key)
        if fn:
            return with_plugin_extras(extra_names, env, dry_run, fn(env.game_dir))
        return with_plugin_extras(
            extra_names,
            env,
            dry_run,
            install_from_github_url(install_url, env.game_dir, hint=key),
        )
    if key in {"l4dtoolz"}:
        return "跳过: l4dtoolz 需按教程手动安装（本地已检测到则不会出现此项）"
    if "fastdl" in key or "developer.valvesoftware.com" in url:
        return "跳过: FastDL 需按教程自行配置"
    if "install_other_file" in url and "l4dtoolz" not in key:
        return "跳过: 教程类依赖需手动安装"
    if dry_run:
        return "预览: 将尝试自动下载"
    fn = (
        INSTALLERS.get(key)
        or INSTALLERS.get((req.slug or "").lower().replace("-", "_"))
        or lookup_plugin_installer(key)
        or lookup_plugin_installer((req.slug or "").lower().replace("-", "_"))
    )
    if fn:
        return with_plugin_extras(extra_names, env, dry_run, fn(env.game_dir))
    url = req.url or ""
    if "github.com" in url or "raw.githubusercontent.com" in url:
        return with_plugin_extras(
            extra_names,
            env,
            dry_run,
            install_from_github_url(url, env.game_dir, hint=req.slug or req.name),
        )
    if "alliedmods.net" in url or "sourcemod.net" in url:
        return with_plugin_extras(extra_names, env, dry_run, install_from_alliedmods(req, env.game_dir))
    embedded = try_write_embedded_gamedata(req, env, dry_run)
    if embedded:
        return with_plugin_extras(extra_names, env, dry_run, embedded)
    stem = Path((req.slug or req.name or "").strip()).stem
    if stem and plugin_wrong_engine(env, stem):
        return f"跳过: {stem} 不支持当前游戏引擎，无需补 gamedata"
    if stem and (sm_root(env.game_dir) / "scripting" / f"{stem}.sp").is_file():
        raise RuntimeError(
            "本地缺 gamedata，源码无内嵌且无下载 URL，需手动补 "
            f"addons/sourcemod/gamedata/{stem}.txt"
        )
    raise RuntimeError("没有自动安装来源，需手动打开链接")


def try_write_embedded_gamedata(req: Requirement, env: LocalEnv, dry_run: bool) -> str | None:
    stem = Path((req.slug or req.name or "").strip()).stem
    if not stem:
        return None
    sm = sm_root(env.game_dir)
    sp = sm / "scripting" / f"{stem}.sp"
    if not sp.is_file():
        return None
    missing = plugin_missing_gamedata(env, stem)
    if not missing:
        return None
    text = extract_embedded_gamedata(sp)
    if not text or not looks_like_gamedata(text.encode("utf-8")):
        return None
    if dry_run:
        return "预览: 将从源码写出 " + ", ".join(missing)
    written: list[str] = []
    for fname in missing:
        dest = sm / "gamedata" / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        written.append(dest.name)
    return "已从源码写出 gamedata: " + ", ".join(written)


def collect_missing(
    plugins: list[RemotePlugin],
    env: LocalEnv,
    local_names: set[str] | None = None,
) -> list[dict]:
    groups: dict[str, dict] = {}
    for rp in plugins:
        for req in rp.requires:
            result = check_requirement(req, env)
            if result.ok:
                continue
            key = dep_merge_key(req)
            item = groups.setdefault(
                key,
                {"key": key, "req": req, "needed_by": [], "result": result},
            )
            label = f"{rp.repo.key}/{rp.name}"
            if label not in item["needed_by"]:
                item["needed_by"].append(label)
    for p in env.plugins:
        if local_names is not None and p.name.lower() not in local_names:
            continue
        for name, url in PLUGIN_EXTRA_REQUIRES.get(p.name.lower(), []):
            req = Requirement(name=name, url=url, slug=name)
            result = check_requirement(req, env)
            if result.ok:
                continue
            key = dep_merge_key(req)
            item = groups.setdefault(
                key,
                {"key": key, "req": req, "needed_by": [], "result": result},
            )
            label = f"本地插件 {p.name}"
            if label not in item["needed_by"]:
                item["needed_by"].append(label)
    return list(groups.values())


def collect_local_gamedata_gaps(
    plugins: list[RemotePlugin],
    env: LocalEnv,
    groups: list[dict],
    local_names: set[str] | None = None,
) -> list[dict]:
    have = {item["key"] for item in groups}
    by_name: dict[str, Requirement] = {}
    for rp in plugins:
        for req in rp.requires:
            by_name[dep_merge_key(req)] = req
            if req.slug:
                by_name[req.slug.lower().replace("-", "_")] = req
    extra = list(groups)
    for p in env.plugins:
        if local_names is not None and p.name.lower() not in local_names:
            continue
        miss = plugin_missing_gamedata(env, p.name)
        if not miss:
            continue
        key = p.name.lower()
        if key in have:
            continue
        req = by_name.get(key) or Requirement(name=p.name, slug=p.name, url="")
        extra.append(
            {
                "key": key,
                "req": req,
                "needed_by": [f"本地插件 {p.name}"],
                "result": CheckResult(False, "缺少 gamedata: " + ", ".join(miss)),
            }
        )
        have.add(key)
    return extra


def print_missing_groups(groups: list[dict]) -> None:
    if not groups:
        return
    print("=== 缺失依赖（已合并重复项） ===")
    for item in groups:
        req: Requirement = item["req"]
        needed = ", ".join(item["needed_by"])
        src = req.url or item["result"].where
        print(f"  [缺] {req.name}")
        print(f"       需要它的插件: {needed}")
        if src:
            print(f"       来源: {src}")


def fetch_missing_deps(groups: list[dict], env: LocalEnv, dry_run: bool) -> tuple[int, int]:
    ok_n = fail_n = 0
    if not groups:
        return ok_n, fail_n
    print()
    print("=== 自动下载缺失依赖 ===")
    try:
        for item in groups:
            req: Requirement = item["req"]
            print(f"-> {req.name}")
            try:
                msg = try_install_requirement(req, env, dry_run)
                print(f"   {msg}")
                ok_n += 1
            except Exception as e:
                print(f"   失败: {e}")
                if req.url:
                    print(f"   请手动打开: {req.url}")
                log_failure(f"依赖安装失败: {req.name}", e, req.url)
                fail_n += 1
    finally:
        close_am_session()
    if fail_n:
        print(f"失败已写入: {LOG_FILE}")
    return ok_n, fail_n


def print_env_summary(env: LocalEnv) -> None:
    print("=== 本地基础环境 ===")
    for key, title, ok, where in env_checks(env):
        mark = "OK" if ok else "缺"
        print(f"  [{mark}] {title:16} {where}")
    print()


def env_checks(env: LocalEnv) -> list[tuple[str, str, bool, str]]:
    # 不含 Sourcemod-Plugins 可选插件（linux_auto_restart 等），避免菜单7误装
    return [
        ("metamod", "Metamod", env.has_metamod, "addons/metamod"),
        ("sourcemod", "SourceMod", env.has_sourcemod, "addons/sourcemod"),
        ("left4dhooks", "left4dhooks", bool(env.plugin("left4dhooks")), "plugins/left4dhooks.smx"),
        ("l4dtoolz", "l4dtoolz", _has_addon(env, "l4dtoolz", "l3rdtool"), "addons/l4dtoolz"),
        # 勿把单独的 colors.inc 当成已装 Multi Colors
        ("multicolors", "Multi Colors", _has_inc(env, "multicolors"), "scripting/include/multicolors"),
        ("private_require", "Private Require", _has_private_require(env), "L4D_插件/Require_檔案"),
        ("builtinvotes", "builtinvotes", _has_ext(env, "builtinvotes") or _has_inc(env, "builtinvotes"), "extensions/builtinvotes"),
        ("collisionhook", "CollisionHook", _has_ext(env, "collisionhook"), "extensions/collisionhook"),
        ("smlib", "smlib", _has_inc(env, "smlib"), "scripting/include/smlib"),
        ("dhooks", "DHooks", _has_ext(env, "dhooks"), "extensions/dhooks"),
        ("sourcescramble", "SourceScramble", _has_ext(env, "sourcescramble"), "extensions/sourcescramble"),
        ("actions", "Actions", _has_ext(env, "actions"), "extensions/actions"),
    ]


def http_bytes_any(urls: list[str]) -> tuple[str, bytes]:
    last_err: Exception | None = None
    for url in urls:
        try:
            return url, http_bytes(url)
        except Exception as e:
            last_err = e
    raise RuntimeError(last_err or "下载失败")


class InstallCancelled(Exception):
    pass


DROP_SERIES = ("1.12", "1.11", "1.10")


def sm_drop_indexes(series: str = "1.12") -> list[str]:
    return [
        f"https://www.sourcemod.net/smdrop/{series}/",
        f"https://sm.alliedmods.net/smdrop/{series}/",
    ]


def mm_drop_indexes(series: str = "1.12") -> list[str]:
    return [
        f"https://www.metamodsource.net/mmsdrop/{series}/",
        f"https://mms.alliedmods.net/mmsdrop/{series}/",
        f"https://www.sourcemm.net/mmsdrop/{series}/",
    ]


def drop_git_num(name: str) -> int:
    m = re.search(r"git(\d+)", name, re.I)
    return int(m.group(1)) if m else 0


def list_windows_drop_zips(index_urls: list[str], prefix: str) -> tuple[str, list[str]]:
    last_err: Exception | None = None
    pat = re.compile(rf"{re.escape(prefix)}-[\w.\-]+-windows\.zip", re.I)
    for base in index_urls:
        base = base.rstrip("/") + "/"
        html = ""
        try:
            html = http_text(base)
        except Exception as e:
            last_err = e
            continue
        names = sorted(set(pat.findall(html or "")), key=drop_git_num, reverse=True)
        if names:
            return base, names
        for pointer in (f"{prefix}-latest-windows", f"{prefix}-latest-windows.zip"):
            try:
                _url, ptr = http_bytes_any([base + pointer])
            except Exception as e:
                last_err = e
                continue
            if ptr[:2] == b"PK":
                return base, [pointer]
            text = ptr.decode("ascii", errors="replace").strip().split()[0]
            text = Path(text.replace("\\", "/")).name
            if text.lower().endswith(".zip"):
                return base, [text]
    raise RuntimeError(last_err or f"找不到 {prefix} Windows 包")


def latest_windows_drop(index_urls: list[str], prefix: str) -> tuple[str, bytes]:
    """从 AlliedModders drop 目录取最新 windows.zip。"""
    base, names = list_windows_drop_zips(index_urls, prefix)
    best = names[0]
    return best, http_bytes(base + best)


def list_stable_windows_drops(kind: str, per_series: int = 8) -> list[tuple[str, str, str]]:
    prefix = "sourcemod" if kind == "sourcemod" else "mmsource"
    out: list[tuple[str, str, str]] = []
    for series in DROP_SERIES:
        indexes = sm_drop_indexes(series) if kind == "sourcemod" else mm_drop_indexes(series)
        try:
            base, names = list_windows_drop_zips(indexes, prefix)
        except Exception:
            continue
        seen: set[str] = set()
        n = 0
        for name in names:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((series, name, base + name))
            n += 1
            if n >= per_series:
                break
    if not out:
        raise RuntimeError(f"找不到 {kind} 的 stable Windows 包")
    return out


def choose_windows_drop(kind: str, package: str = "") -> tuple[str, bytes]:
    items = list_stable_windows_drops(kind)
    title = "SourceMod" if kind == "sourcemod" else "MetaMod"
    if package:
        pack = Path(package).name.lower()
        for _series, name, url in items:
            if name.lower() == pack:
                print(f"   使用指定包: {name}")
                return name, http_bytes(url)
        raise RuntimeError(f"找不到指定的 {title} 包: {package}")
    interactive = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
    if not interactive:
        series, name, url = items[0]
        print(f"   非交互模式，使用 {series} 最新: {name}")
        return name, http_bytes(url)
    labels = []
    for i, (series, name, _url) in enumerate(items):
        tag = "  推荐" if i == 0 else ""
        labels.append(f"[{series}] {name}{tag}")
    idx = pick_multi_list(f"选择 {title} stable 版本（Windows）", labels, single=True)
    if idx is None:
        raise InstallCancelled("已返回")
    series, name, url = items[idx[0]]
    print(f"   已选 [{series}] {name}")
    return name, http_bytes(url)


def pick_release_zip(
    owner_repo: str,
    prefer: list[str],
    deny: list[str] | None = None,
    tag: str = "",
) -> tuple[str, bytes]:
    if tag:
        data = http_json(f"https://api.github.com/repos/{owner_repo}/releases/tags/{quote(tag)}")
    else:
        data = http_json(f"https://api.github.com/repos/{owner_repo}/releases/latest")
    assets = data.get("assets") or []

    def score(name: str) -> int:
        n = name.lower()
        if deny and any(d.lower() in n for d in deny):
            return -1
        if not n.endswith(".zip"):
            return -1
        s = 1
        for i, p in enumerate(prefer):
            if p.lower() in n:
                s += 80 - i
        if "sm1.12" in n:
            s += 30
        elif "smlatest" in n:
            s += 8
        return s

    ranked = sorted(assets, key=lambda a: score(a["name"]), reverse=True)
    if not ranked or score(ranked[0]["name"]) < 0:
        label = f"{owner_repo} {tag}" if tag else f"{owner_repo} 最新发行版"
        raise RuntimeError(f"{label} 没有合适的 zip")
    pick = ranked[0]
    return pick["name"], http_bytes(pick["browser_download_url"])


def extract_game_zip(
    data: bytes,
    game_dir: Path,
    skip_sm_dirs: set[str] | None = None,
) -> list[Path]:
    skip_sm_dirs = {s.lower() for s in (skip_sm_dirs or set())}
    copied: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist() if not n.endswith("/")]
        if not names:
            return copied

        def dest_for(rel: str) -> Path | None:
            parts = Path(rel).parts
            if not parts or parts[-1].lower() in SKIP_FILE_NAMES:
                return None
            low = [p.lower() for p in parts]
            if "addons" in low:
                i = low.index("addons")
                rest = parts[i:]
                if "sourcemod" in [p.lower() for p in rest] and skip_sm_dirs:
                    sm_i = [p.lower() for p in rest].index("sourcemod")
                    after = rest[sm_i + 1 :]
                    if after and after[0].lower() in skip_sm_dirs:
                        return None
                return game_dir.joinpath(*rest)
            if parts[0].lower() == "sourcemod":
                rest = parts[1:]
                if rest and rest[0].lower() in skip_sm_dirs:
                    return None
                return sm_root(game_dir).joinpath(*rest)
            if parts[0].lower() == "metamod":
                return game_dir / "addons" / "metamod" / Path(*parts[1:]) if len(parts) > 1 else game_dir / "addons" / "metamod"
            if parts[-1].lower().startswith("l4dtoolz") or parts[-1].lower().startswith("l3rdtool"):
                return game_dir / "addons" / parts[-1]
            return None

        mapped = [(n, dest_for(n)) for n in names]
        if not any(d for _, d in mapped):
            # 压缩包是单层目录包着 addons
            tops = {n.split("/")[0] for n in names}
            if len(tops) == 1:
                top = next(iter(tops))
                mapped = [(n, dest_for(n[len(top) + 1 :])) for n in names]

        for name, dest in mapped:
            if dest is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(name) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
            copied.append(dest)
    return copied


MM_DROP_INDEXES = mm_drop_indexes("1.12")
SM_DROP_INDEXES = sm_drop_indexes("1.12")


def install_env_metamod(game_dir: Path, package: str = "") -> str:
    name, blob = choose_windows_drop("metamod", package)
    copied = extract_game_zip(blob, game_dir)
    if not copied:
        raise RuntimeError("MetaMod 压缩包里没有可解压文件")
    return f"已更新 MetaMod（{name}，{len(copied)} 个文件）"


def backup_sm_dirs(game_dir: Path, dirs: list[str]) -> Path | None:
    sm = sm_root(game_dir)
    stamp = SCRIPT_DIR / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    copied = False
    for name in dirs:
        src = sm / name
        if not src.exists():
            continue
        dest = stamp / "addons" / "sourcemod" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dest)
        copied = True
    return stamp if copied else None


def install_env_sourcemod(
    game_dir: Path,
    overwrite_configs: bool = False,
    overwrite_plugins: bool = False,
    package: str = "",
) -> str:
    name, blob = choose_windows_drop("sourcemod", package)
    skip = {"logs", "disabled"}
    bak_dirs: list[str] = []
    if overwrite_plugins:
        bak_dirs.append("plugins")
    else:
        skip.add("plugins")
    if overwrite_configs:
        bak_dirs.extend(["configs", "data"])
    else:
        skip |= {"configs", "data"}
    if bak_dirs:
        bak = backup_sm_dirs(game_dir, bak_dirs)
        if bak:
            print(f"     已备份 {'/'.join(bak_dirs)} 到: {bak}")
    copied = extract_game_zip(blob, game_dir, skip_sm_dirs=skip)
    if not copied:
        raise RuntimeError("SourceMod 压缩包里没有可解压文件")
    parts = []
    if overwrite_configs:
        parts.append("已覆盖 configs/data")
    else:
        parts.append("跳过 configs")
    if overwrite_plugins:
        parts.append("已覆盖 plugins")
    else:
        parts.append("保留 plugins")
    return f"已更新 SourceMod（{name}，{'，'.join(parts)}，{len(copied)} 个文件）"


def install_env_dhooks(game_dir: Path) -> str:
    name, blob = latest_windows_drop(SM_DROP_INDEXES, "sourcemod")
    copied: list[Path] = []
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("\\", "/")
            if "dhooks" not in Path(rel).name.lower():
                continue
            parts = Path(rel).parts
            if "addons" in [p.lower() for p in parts]:
                i = [p.lower() for p in parts].index("addons")
                dest = game_dir.joinpath(*parts[i:])
            elif "sourcemod" in [p.lower() for p in parts]:
                i = [p.lower() for p in parts].index("sourcemod")
                dest = sm_root(game_dir).joinpath(*parts[i + 1 :])
            else:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
            copied.append(dest)
    if not copied:
        raise RuntimeError(f"{name} 里没有 dhooks 文件")
    return f"已更新 DHooks（来自 {name}，{len(copied)} 个文件）"


def install_env_left4dhooks(game_dir: Path) -> str:
    repo = cache_git_repo("SilvDev/Left4DHooks")
    src = repo / "sourcemod"
    copied = copy_sm_tree(src, game_dir)
    # data/ 也要更新（left4dhooks 签名表）
    data = src / "data"
    if data.is_dir():
        for file in data.rglob("*"):
            if file.is_file():
                dest = sm_root(game_dir) / "data" / file.relative_to(data)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, dest)
                copied.append(dest)
    if not copied:
        raise RuntimeError("Left4DHooks 仓库没有可复制的 SourceMod 文件")
    return f"已更新 left4dhooks（{len(copied)} 个文件）"


def install_env_l4dtoolz(game_dir: Path) -> str:
    name, blob = pick_release_zip("lakwsh/l4dtoolz", ["main", "windows", "win"], deny=["2155", "linux"])
    copied = extract_game_zip(blob, game_dir)
    return f"已更新 l4dtoolz（{name}，{len(copied)} 个文件）"


def install_env_multicolors(game_dir: Path) -> str:
    repo = cache_git_repo("Bara/Multi-Colors")
    inc = sm_root(game_dir) / "scripting" / "include"
    copied = 0
    for src_root in (
        repo / "addons" / "sourcemod" / "scripting" / "include",
        repo / "scripting" / "include",
        repo / "addons" / "sourcemod" / "scripting" / "include" / "multicolors",
    ):
        if not src_root.exists():
            continue
        if src_root.is_file():
            dest = inc / src_root.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_root, dest)
            copied += 1
            continue
        for file in src_root.rglob("*"):
            if file.is_file() and file.suffix.lower() == ".inc":
                dest = inc / file.relative_to(src_root)
                # 若源已经是 include 根
                if src_root.name.lower() == "include":
                    dest = inc / file.relative_to(src_root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, dest)
                copied += 1
        break
    # 常见结构: repo/addons/sourcemod/scripting/include/multicolors.inc
    for inc_file in repo.rglob("multicolors.inc"):
        dest = inc / "multicolors.inc"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inc_file, dest)
        folder = inc_file.parent / "multicolors"
        if folder.is_dir():
            out = inc / "multicolors"
            if out.exists():
                shutil.rmtree(out)
            shutil.copytree(folder, out)
        copied += 1
        break
    if not copied:
        raise RuntimeError("Multi-Colors 仓库里找不到 .inc")
    return f"已更新 Multi Colors（{copied} 个文件）"


def install_env_private_require(game_dir: Path) -> str:
    cache = SCRIPT_DIR / ".cache" / "deps" / "Game-Private_Plugin_Require"
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)
    n = download_github_dir(
        "fbef0102",
        "Game-Private_Plugin",
        "L4D_插件/Require_檔案",
        cache,
        "main",
    )
    copied = copy_sm_tree(cache, game_dir)
    if not copied:
        raise RuntimeError(f"Require_檔案 已下载 {n} 个文件，但没有可复制到 SourceMod 的内容")
    return f"已补充 L4D_插件/Require_檔案（{len(copied)} 个文件）"


def install_env_builtinvotes(game_dir: Path) -> str:
    last_err: Exception | None = None
    name = ""
    blob = b""
    try:
        name, blob = pick_release_zip(
            "fbef0102/builtinvotes",
            ["sm1.12-win", "-win.", "windows"],
            deny=["oldlinux", "-linux"],
        )
    except Exception as e:
        last_err = e
        try:
            url, blob = http_bytes_any(BUILTINVOTES_WIN_ZIPS)
            name = Path(urlparse(url).path).name
        except Exception as e2:
            raise RuntimeError(f"builtinvotes 下载失败（{BUILTINVOTES_URL}）: {last_err}; {e2}") from e2
    copied = unpack_plugin_archive(blob, game_dir, name)
    if not copied:
        raise RuntimeError(f"{name} 里没有可安装的 SourceMod 文件")
    return f"已安装 builtinvotes（{name}，Windows SM1.12，{len(copied)} 个文件）"


def install_env_collisionhook(game_dir: Path) -> str:
    name, blob = pick_release_zip("fbef0102/Collisionhook", ["win", "windows"], deny=["linux"])
    copied = extract_zip_to_sourcemod(blob, game_dir) or extract_game_zip(blob, game_dir)
    if not copied:
        raise RuntimeError(f"{name} 里没有可安装的 SourceMod 文件")
    return f"已更新 CollisionHook（{name}，{len(copied)} 个文件）"


def install_env_smlib(game_dir: Path) -> str:
    name, blob = pick_release_zip(
        "fbef0102/L4D1_2-Plugins",
        ["smlib", "win", "windows"],
        deny=["linux"],
        tag="smlib-Colors",
    )
    copied = extract_zip_to_sourcemod(blob, game_dir) or extract_game_zip(blob, game_dir)
    if not copied:
        raise RuntimeError(f"{name} 里没有可安装的 smlib 文件")
    return f"已更新 smlib（{name}，{len(copied)} 个文件）"


def install_env_sourcescramble(game_dir: Path) -> str:
    name, blob = pick_release_zip(
        "nosoop/SMExt-SourceScramble",
        ["package.zip"],
        deny=["api9", "api10", "linux", ".tar"],
    )
    copied = extract_game_zip(blob, game_dir)
    manager = sm_root(game_dir) / "scripting"
    # 发行包通常已含 extensions + include；manager 插件若在包内会被 skip? 不 skip plugins for this zip
    return f"已更新 SourceScramble（{name}，{len(copied)} 个文件）"


def install_env_actions(game_dir: Path) -> str:
    # v4+ 不支持 SM 1.12；固定 Vinillia 3.9.2
    name, blob = pick_release_zip(
        "Vinillia/actions.ext",
        ["actions.ext.zip", "win", "windows", "package"],
        deny=["linux", "src"],
        tag="v3.9.2",
    )
    copied = unpack_plugin_archive(blob, game_dir, name)
    if not copied:
        raise RuntimeError(f"Vinillia/actions.ext {name} 解压后没有扩展文件")
    return f"已安装 Actions 3.9.2（Vinillia/actions.ext {name}，兼容 SM 1.12，{len(copied)} 个文件）"


def copy_new_game_cfg(plugin_dir: Path, game_dir: Path) -> int:
    cfg = plugin_dir / "cfg"
    if not cfg.is_dir():
        return 0
    n = 0
    for file in cfg.rglob("*"):
        if not file.is_file():
            continue
        dest = game_dir / "cfg" / file.relative_to(cfg)
        if dest.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dest)
        n += 1
    return n


def install_sm_dep_plugin(game_dir: Path, key: str) -> str:
    url = REQUIRE_INSTALL_URLS[key]
    msg = install_from_github_url(url, game_dir, hint=key)
    m = GITHUB_REPO_RE.search(url)
    if not m:
        return msg
    owner, repo = normalize_github_slug(f"{m.group(1)}/{m.group(2)}").split("/", 1)
    parts = [unquote(p) for p in urlparse(url).path.split("/") if p]
    branch = parts[3] if len(parts) > 3 else ""
    rest = parts[4:] if len(parts) > 4 else []
    local = cache_git_repo(f"{owner}/{repo}", branch)
    extra = copy_new_game_cfg(local.joinpath(*rest) if rest else local, game_dir)
    if extra:
        return f"{msg}，并补了 {extra} 个 cfg（已有的不覆盖）"
    return msg


def install_env_linux_auto_restart(game_dir: Path) -> str:
    return install_sm_dep_plugin(game_dir, "linux_auto_restart")


def install_env_server_loader(game_dir: Path) -> str:
    return install_sm_dep_plugin(game_dir, "server_loader")


def install_env_smd_advertisements(game_dir: Path) -> str:
    return install_sm_dep_plugin(game_dir, "smd_advertisements")


def install_env_smd_dynamichostname(game_dir: Path) -> str:
    return install_sm_dep_plugin(game_dir, "smd_dynamichostname")


def install_env_cannounce(game_dir: Path) -> str:
    return install_sm_dep_plugin(game_dir, "cannounce")


ENV_INSTALLERS = {
    "metamod": install_env_metamod,
    "sourcemod": install_env_sourcemod,
    "left4dhooks": install_env_left4dhooks,
    "l4dtoolz": install_env_l4dtoolz,
    "multicolors": install_env_multicolors,
    "private_require": install_env_private_require,
    "builtinvotes": install_env_builtinvotes,
    "collisionhook": install_env_collisionhook,
    "smlib": install_env_smlib,
    "dhooks": install_env_dhooks,
    "sourcescramble": install_env_sourcescramble,
    "actions": install_env_actions,
}
# 以下可通过 Sourcemod-Plugins / Require 安装，但不列入菜单7基础环境
OPTIONAL_SM_PLUGIN_INSTALLERS = {
    "linux_auto_restart": install_env_linux_auto_restart,
    "server_loader": install_env_server_loader,
    "smd_advertisements": install_env_smd_advertisements,
    "smd_dynamichostname": install_env_smd_dynamichostname,
    "cannounce": install_env_cannounce,
}


def lookup_plugin_installer(key: str):
    k = (key or "").lower().replace("-", "_")
    return ENV_INSTALLERS.get(k) or OPTIONAL_SM_PLUGIN_INSTALLERS.get(k)


def update_env(
    game_dir: Path,
    missing_only: bool = False,
    dry_run: bool = False,
    only_keys: list[str] | None = None,
    skip_if_present: set[str] | None = None,
    overwrite_sm_configs: bool = False,
    overwrite_sm_plugins: bool = False,
    drop_package: str = "",
    present_only: bool = False,
) -> None:
    created = ensure_game_addons(
        game_dir, announce_full_install=not present_only and not missing_only
    )
    # 仅“补缺失/全量”模式在新建 addons 后改为可安装；present_only 绝不能因此去装未装项
    if created and not present_only:
        missing_only = False
    env = scan_local_env(game_dir)
    rows = env_checks(env)
    skip_if_present = set(skip_if_present or ())
    only = {k.lower() for k in only_keys} if only_keys else None
    print("=== 更新基础依赖环境 ===")
    if only:
        print("模式: 只处理 " + ", ".join(only_keys or []))
    elif present_only:
        print("模式: 只更新已安装项，不补缺失（SourceMod/MetaMod 请用独立菜单）")
    elif missing_only:
        print("模式: 只安装缺失项")
    else:
        print("模式: 已安装的也会拉取最新版（已装的 SourceMod/MetaMod 除外，请用独立菜单更新）")
    if only is None or "sourcemod" in only:
        if overwrite_sm_configs or overwrite_sm_plugins:
            bits = []
            if overwrite_sm_configs:
                bits.append("configs/data")
            if overwrite_sm_plugins:
                bits.append("plugins")
            print("SourceMod 将覆盖 " + "、".join(bits) + "（先备份）。")
        else:
            print("SourceMod 默认不覆盖 plugins/configs。")
    print()
    ok_n = fail_n = skip_n = 0
    done: set[str] = set()
    skipped_missing = 0
    for key, title, present, _where in rows:
        if only is not None and key not in only:
            continue
        if present_only and not present:
            skipped_missing += 1
            skip_n += 1
            continue
        if (missing_only or key in skip_if_present) and present:
            print(f"  [跳过] {title} 已安装")
            skip_n += 1
            continue
        if key in done:
            print(f"  [跳过] {title} 已随上一项更新")
            skip_n += 1
            continue
        print(f"  -> {title}")
        if dry_run:
            print("     预览: 将按所选 stable 版本安装")
            ok_n += 1
            continue
        try:
            package = drop_package or ""
            if key == "sourcemod":
                msg = install_env_sourcemod(
                    game_dir,
                    overwrite_configs=overwrite_sm_configs,
                    overwrite_plugins=overwrite_sm_plugins,
                    package=package,
                )
            elif key == "metamod":
                msg = install_env_metamod(game_dir, package=package)
            else:
                msg = ENV_INSTALLERS[key](game_dir)
            print(f"     {msg}")
            ok_n += 1
            if key == "sourcemod":
                done.add("dhooks")
            done.add(key)
        except InstallCancelled as e:
            print(f"     {e}")
            skip_n += 1
        except Exception as e:
            print(f"     失败: {e}")
            log_failure(f"环境更新失败: {title}", e)
            fail_n += 1
    if present_only and skipped_missing:
        print(f"  （已跳过 {skipped_missing} 项未安装依赖，不自动补全）")
    print()
    print(f"环境更新完成: 成功 {ok_n}, 失败 {fail_n}, 跳过 {skip_n}")
    if fail_n:
        print(f"失败已写入: {LOG_FILE}")
    print()
    print_env_summary(scan_local_env(game_dir))


def cmd_env(args: argparse.Namespace) -> None:
    print_env_summary(scan_local_env(args.game_dir))
    only = getattr(args, "env_only", None)
    with_core = getattr(args, "with_core", False)
    skip_if_present = None if (only or with_core) else {"metamod", "sourcemod"}
    update_env(
        args.game_dir,
        missing_only=args.missing_only,
        dry_run=args.dry_run,
        only_keys=only,
        skip_if_present=skip_if_present,
        overwrite_sm_configs=getattr(args, "overwrite_sm_configs", False),
        overwrite_sm_plugins=getattr(args, "overwrite_sm_plugins", False),
        drop_package=getattr(args, "drop_package", "") or "",
        present_only=getattr(args, "present_only", False),
    )


def _parse_fix_tag(tag: str) -> tuple[set[str], set[str]]:
    text = (tag or "").lower().replace(" ", "")
    games: set[str] = set()
    oses: set[str] = set()
    if "l4d1/2" in text or "l4d1/l4d2" in text:
        games.update({"l4d1", "l4d2"})
    elif "l4d2" in text:
        games.add("l4d2")
    elif "l4d1" in text:
        games.add("l4d1")
    if "windows" in text or re.search(r"\bwin\b", text):
        oses.add("windows")
    if "linux" in text:
        oses.add("linux")
    return games, oses


def _is_ac_category(text: str) -> bool:
    t = text.replace(" ", "")
    return any(s in t for s in ("防駭客", "防黑客", "反作弊", "與外掛", "和外挂", "和外掛"))


def resolve_catalog_url(url: str) -> str:
    url = (url or "").strip()
    if not url or url.startswith("#"):
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url.split("#")[0]
    path = unquote(url.split("#")[0]).lstrip("/")
    if not path:
        return ""
    return f"{PRIVATE_PLUGIN_TREE}/{path}"


def _section_has(section: str, needles: tuple[str, ...]) -> str | None:
    compact = section.replace(" ", "")
    for n in needles:
        if n.replace(" ", "") in compact:
            return n
    return None


def _fix_slug(name: str, url: str) -> str:
    slug = slug_from_url(url)
    if slug and "php" not in slug.lower() and slug.lower() not in {"english", "releases"}:
        lower = slug.lower()
        if lower.endswith((".sp", ".smx", ".inc", ".txt")):
            slug = Path(slug).stem
        return slug
    return re.sub(r"[^\w]+", "_", name).strip("_")


def parse_fix_readme(text: str) -> list[FixItem]:
    items: list[FixItem] = []
    section = ""
    category = ""
    current: FixItem | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        hm = MD_HEADING_RE.match(line)
        if hm:
            section = hm.group(1).strip()
            category = ""
            current = None
            continue
        struck = bool(re.search(r"</?s>", line, re.I))
        clean_line = re.sub(r"</?s>", "", line, flags=re.I).strip()
        m = MD_ITEM_LINK_RE.match(clean_line)
        if m:
            name = m.group("name").strip()
            url = resolve_catalog_url(m.group("url").strip())
            tag = (m.group("tag") or "").strip()
            rest = (m.group("rest") or "").strip(" :：-")
            if struck:
                rest = (rest + " 清单已划掉").strip()
            games, oses = _parse_fix_tag(tag)
            if not games:
                if re.search(r"l4d1/2|l4d", section, re.I):
                    games.update({"l4d1", "l4d2"})
                else:
                    games.add("source")
            item = FixItem(
                name=name,
                url=url,
                slug=_fix_slug(name, url),
                section=section,
                category=category,
                tag=tag,
                note=rest,
                games=games,
                oses=oses,
            )
            items.append(item)
            current = item
            continue
        bullet = re.match(r"^(?:\*|[-+]|\d+\.)\s+(.+)$", line)
        if bullet:
            body = bullet.group(1).strip()
            if "[" not in body and category_is_heading(body):
                category = re.sub(r"\s+", "", body)
                current = None
                continue
            if current is not None:
                extra = re.sub(r"<[^>]+>", "", body).strip()
                if extra:
                    current.note = (current.note + " " + extra).strip()
    return items


def category_is_heading(body: str) -> bool:
    if "](" in body:
        return False
    keys = ("插件", "指令", "遊戲優化", "游戏优化", "崩潰", "崩溃", "防駭", "防黑", "外掛", "外挂", "反作弊")
    return any(k in body for k in keys)


def classify_fix_item(item: FixItem) -> str | None:
    """返回跳过原因；None 表示应安装。"""
    blob = " ".join([item.name, item.slug, item.category, item.note, item.section, item.tag])
    if _is_ac_category(item.category) or _is_ac_category(item.section) or AC_NAME_RE.search(blob):
        return "反作弊/防黑客"
    if "不適用l4d" in item.note.lower().replace(" ", "") or "不适用于l4d" in item.note.lower().replace(" ", ""):
        return "不适用于 L4D1/2"
    note_l = item.note.lower()
    if "清单已划掉" in item.note or (
        "valve" in note_l and ("已於" in item.note or "已于" in item.note or "修復" in item.note or "修复" in item.note)
    ):
        return "Valve 已修复 / 清单已划掉"
    if item.oses == {"linux"}:
        return "仅 Linux"
    if item.games == {"l4d1"}:
        return "仅 L4D1"
    if "l4d2" not in item.games and "source" not in item.games and "l4d1" in item.games:
        return "仅 L4D1"
    return None


CUSTOM_PLUGIN_KEYS = {
    "acceptinput_crash_fix",
    "acceptinput crash fix",
}

CATALOG_URL_OVERRIDES = {
    "command_and_convar_buffer_overflow_fixer": COMMAND_BUFFER_SP_URL,
    "command_buffer": COMMAND_BUFFER_SP_URL,
    "ladder_server_crash_patch_fix": LADDER_PATCH_SP_URL,
    "l4d2_ladder_patch": LADDER_PATCH_SP_URL,
    "l4d_remove_item_collision": REMOVE_ITEM_COLLISION_SP_URL,
    "remove_weapons_carryables_collision": REMOVE_ITEM_COLLISION_SP_URL,
    "zombie_spawn_fix": ZOMBIE_SPAWN_FIX_URL,
    "spawn_infected_nolimit": SPAWN_INFECTED_NOLIMIT_URL,
    "l4d_unrestrict_panic_battlefield": UNRESTRICT_PANIC_URL,
    "l4d_late_model_precacher": "https://github.com/Psykotikism/Late_Model_Precacher",
    "late_model_precacher": "https://github.com/Psykotikism/Late_Model_Precacher",
    "l4d2_null_cusercmd_fix": (
        "https://github.com/SirPlease/L4D2-Competitive-Rework/blob/master/"
        "addons/sourcemod/scripting/l4d2_null_cusercmd_fix.sp"
    ),
    "l4d2_resolve_collision_fix": "https://github.com/Vinillia/resolve-collision-fix",
    "witch_pipebomb_exploit_fix": WITCH_PIPEBOMB_URL,
    "witch_pipebomb": WITCH_PIPEBOMB_URL,
    "l4d2_vscript_purifier": (
        "https://github.com/Mineralcr/L4D2_Public_Plugins/tree/main/l4d2_vscript_purifier"
    ),
    "l4d2_vscript_purifier_v2": (
        "https://github.com/Mineralcr/L4D2_Public_Plugins/tree/main/l4d2_vscript_purifier"
    ),
}


def apply_catalog_overrides(item: FixItem) -> None:
    forced = forced_am_sp_url(item.name, item.slug, item.url)
    if forced:
        item.url = forced
        return
    keys = [
        item.slug.lower(),
        item.slug.lower().replace("-", "_"),
        normalize_key(item.name).replace(" ", "_"),
    ]
    for k in keys:
        if k in CATALOG_URL_OVERRIDES:
            item.url = CATALOG_URL_OVERRIDES[k]
            return
    blob = " ".join(keys)
    for k, url in CATALOG_URL_OVERRIDES.items():
        if k in blob:
            item.url = url
            return


def classify_catalog_item(item: FixItem, spec: TutorialSpec) -> str | None:
    blob = normalize_key(item.name) + " " + item.slug.lower().replace("-", "_")
    if any(k.replace("_", " ") in blob or k in blob.replace(" ", "_") for k in CUSTOM_PLUGIN_KEYS):
        return "定制插件，需联系作者"
    if "清单已划掉" in item.note:
        return "划线/已废弃"
    hit = _section_has(item.section, spec.skip_sections)
    if hit:
        return hit
    if spec.keep_sections and not _section_has(item.section, spec.keep_sections):
        return f"非安装章节（{item.section or '未分类'}）"
    url = item.url.lower()
    if not url:
        return "无下载地址"
    if "steamcommunity.com" in url:
        return "创意工坊Mod"
    if "gamemaps.com" in url:
        return "非插件下载站"
    if "tutorial_" in url or "教學區" in item.url or "教学区" in item.url:
        blob = normalize_key(item.name) + " " + item.slug.lower()
        if "l4dtoolz" in blob:
            return None
        return "教学文档"
    if spec.use_fix_filters:
        return classify_fix_item(item)
    if item.games == {"l4d1"}:
        return "仅 L4D1"
    return None


def load_catalog(spec: TutorialSpec) -> tuple[list[FixItem], list[tuple[FixItem, str]]]:
    print(f"读取清单: {spec.page_url}")
    text = http_text(spec.raw_url)
    parsed = parse_fix_readme(text)
    keep: list[FixItem] = []
    skipped: list[tuple[FixItem, str]] = []
    seen: set[str] = set()
    for item in parsed:
        apply_catalog_overrides(item)
        reason = classify_catalog_item(item, spec)
        if reason:
            skipped.append((item, reason))
            continue
        key = (item.url.rstrip("/").lower(), item.slug.lower())
        if key in seen:
            continue
        seen.add(key)
        keep.append(item)
    return keep, skipped


FIX_NOTE_ZH = {
    "command_and_convar_buffer_overflow_fixer": "修复读不到 cfg 指令",
    "command_buffer": "修复读不到 cfg 指令",
    "firebulletsfix": "修复子弹命中慢 1 tick",
    "smd_spritetrail_fix": "修复拖尾特效一秒后消失",
    "lag_preventor_plus": "减少骨骼实体造成的卡顿",
    "map_lag_preventor": "减少骨骼实体造成的卡顿",
    "acceptinput_crash_fix": "修复实体非法参数崩溃",
    "l4d2_parseline_fix": "修复 cfg 中文导致卡顿崩溃",
    "l4d2_fix_changelevel": "修复强制换图后导演不同步",
    "l4d2_transition_info_fix": "修复换图残留过关数据",
    "inputkill_kick_prevention": "防止地图 NPC 踢人",
    "inputkill": "防止地图 NPC 踢人",
    "l4d2_script_cmd_swap": "减少 VScript 内存泄漏",
    "l4d_game_files_precacher": "预载模型声音，避免崩溃",
    "l4d_late_model_precacher": "检测晚载模型导致的崩溃",
    "tickratefixes": "修复高 tick 门慢和摔伤",
    "l4d_remove_item_collision": "去掉武器物品碰撞卡顿",
    "remove_weapons_carryables_collision": "去掉武器物品碰撞卡顿",
    "disable_cameras": "修复地图镜头卡住视角",
    "l4d_fix_deathfall_cam": "修复旁观镜头卡住",
    "remove_touch_links": "修复死亡区换队即死",
    "l4d2_sg552_zoom_fix": "修复高 tick 开镜卡住",
    "l4d_fix_linux_surface": "修复 Linux 冰面不滑",
    "l4d2_resolve_collision_fix": "修复僵尸 Witch 卡住反弹",
    "witch_pipebomb_exploit_fix": "修复爆炸后 Witch 消失",
    "witch_pipebomb": "修复爆炸后 Witch 消失",
    "l4d2_vscript_purifier": "阻止三方图脚本互相污染",
    "ladder_server_crash_patch_fix": "修复爬梯导致服务器崩溃",
    "l4d2_ladder_patch": "修复爬梯导致服务器崩溃",
    "triggermoved_detour": "修复触发器空指针崩溃",
    "enumentity_fix": "修复枚举实体空指针崩溃",
    "enumentity-fix": "修复枚举实体空指针崩溃",
    "l4d2_null_cusercmd_fix": "修复空用户指令崩溃",
    "code_patcher": "修复开火涉水掉 tick",
    "cutlrbtreefix": "修复 CUtlRBTree 溢出崩溃",
    "sv_solidmoved": "修复移动碰撞空指针崩溃",
    "sv_solidmoved-fix": "修复移动碰撞空指针崩溃",
    "getcollideabletriggertestbox_detour": "修复碰撞检测空指针崩溃",
    "tier_memscan_detour": "修复内存扫描崩溃",
    "server_sub_101d7cb0_detour": "修复 server.dll 空指针崩溃",
    "isreachable_detour": "修复 Bot 寻路空指针崩溃",
    "l4d2_chainsaw_fix": "修复电锯音效崩溃",
    "left4dhooks": "Left4DHooks 核心依赖",
    "left_4_dhooks": "Left4DHooks 核心依赖",
    "actions": "特感动作扩展",
    "l4dtoolz": "解锁服务器人数上限",
    "l4d_unreservelobby": "解除大厅人数锁定",
    "remove_lobby_reservation": "解除大厅人数锁定",
    "l4dmultislots": "给第五人以上生成 Bot",
    "defib_fix": "修复 5+ 电击器复活异常",
    "survivor_identity_fix": "修复 5+ 角色模型和尸体错乱",
    "survivor_afk_fix": "修复 5+ 闲置进错 Bot",
    "l4dafkfix_deadbot": "修复闲置后 Bot 死亡变旁观",
    "l4d_both_fixupgradepack": "修复重复角色捡不到升级包",
    "better_charger_collision": "修复 Charger 撞不到第五人",
    "witch_target_patch": "修复 Witch 追错第五人",
    "l4d2_trigger_flow_fix": "修复不同角色模组卡机关",
    "l4d2_vocalizebasedmodel": "按模组发语音并修对讲机剧情",
    "l4d2_maptankfix": "防止机关 Tank 因人数不够卡关",
    "l4d2_rescue_vehicle_multi": "修复第五人以上上不了救援载具",
    "l4d2_fix_character_mixed": "防止一代 NPC 地图误踢误传",
    "l4d_full_slot_bot_replace_fix": "修复人满时无法生成替补 Bot",
    "l4d_fix_target_replace": "修复玩家与 Bot 互相替换异常",
    "transition_restore_fix": "修复 5+ 过关武器不保存",
    "l4d_forcefinalestart_fix": "修复救援因人数不够无法开始",
    "l4d_afk_commands": "提供闲置和换队命令",
    "l4d2_ty_saveweapons": "战役过关保存武器和血量",
    "autotakeover": "死后自动接管空闲 Bot",
    "_autotakeover": "死后自动接管空闲 Bot",
    "l4d_h_csm": "游戏中更换角色外观语音",
    "survivor_rescue_closet": "救援房可救第五人以上",
    "friendly_fire_quote_fix": "修复 5+ 友伤没有语音",
    "hunter_pounced_warning": "同模组被扑时有语音提醒",
    "l4d2_team_kill_reactions": "TK 倒地死亡增加角色语音",
    "l4d2_survivor_mourn_fix": "修复一代角色见尸体无语音",
    "stripper": "Stripper:Source 地图修改",
    "smd_dynamichostname": "服务器房名可写中文",
    "smd_god": "全员无敌不受伤害",
    "smd_teleport_player": "传送玩家到队友或准心",
    "smd_restartmap_command": "管理员重开当前地图",
    "simple_chatprocessor": "控制聊天文字和颜色",
    "cannounce": "进出服提示 IP/国家/SteamID",
    "smd_texture_manager_block": "踢出试图开作弊指令的玩家",
    "sm_translator": "翻译聊天给其他玩家",
    "helpmenu": "帮助菜单说明服务器内容",
    "smd_advertisements": "定时在聊天框发公告",
    "bequiet": "屏蔽改指令改名等刷屏",
    "chat_responses": "特定聊天触发提示",
    "gagmutebanex": "封锁/禁音/禁言加强版",
    "lerptracker": "显示玩家 Lerp 值",
    "smd_noteamsay": "队内聊天全服可见",
    "linux_auto_restart": "最后一人离开后重启服务器",
    "map-decals": "管理员永久放置涂鸦",
    "map_decals": "管理员永久放置涂鸦",
    "match_vote": "投票更换模式或玩法",
    "server_loader": "开服执行一次 cfg",
    "sm_downloader": "进服下载自制文件",
    "smd_hackers_block": "阻止漏洞炸服",
    "familyshare_manager": "封锁家庭共享号",
    "vacbans": "封锁 VAC/社区/交易封禁号",
    "entity_limit_logger": "记录实体数量排查崩溃",
    "games": "决斗小游戏",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_PLUGIN_NAME_ZH = {
    "admin-flatfile": "文件管理员权限",
    "adminhelp": "管理员帮助命令",
    "adminmenu": "管理员菜单",
    "antiflood": "防刷屏",
    "basebans": "基础封禁",
    "basechat": "基础聊天命令",
    "basecomm": "禁言和禁音",
    "basecommands": "基础管理命令",
    "basetriggers": "聊天触发提示",
    "basevotes": "基础投票",
    "clientprefs": "客户端偏好存储",
    "funcommands": "娱乐命令",
    "funvotes": "娱乐投票",
    "nextmap": "下一张地图",
    "playercommands": "玩家管理命令",
    "reservedslots": "预留位",
    "sounds": "语音菜单",
    "css_drop_weapon": "可丢刀和手雷",
    "css_respawn_player": "准心处复活玩家",
    "css_savechat_command": "记录聊天和指令",
    "css_teleport_player": "传送存活玩家",
    "nmrih_giveweapons": "给予武器物品",
    "nmrih_hud": "HUD 显示状态弹药",
    "_[l4d2]survivor_legs": "一代风格第一人称腿",
    "can't defeat moyu": "管理员控制导演系统",
    "all4dead2": "管理员控制导演系统",
    "eq spechud": "对抗计分旁观 HUD",
    "nextmod spechud": "对抗计分系统",
    "spechud": "旁观 HUD 计分",
    "1v1": "1v1 对战",
    "1v1_skeetstats": "1v1 空中击杀统计",
    "8ball": "魔法问答球",
    "aitankgank": "AI Tank 抢人头",
    "autopause": "自动暂停",
    "bossspawningfix": "修复 Boss 生成",
    "caster_system": "解说员系统",
    "changelog": "更新日志",
    "christmas_surprise": "圣诞彩蛋",
    "coinflip": "抛硬币",
    "confoglcompmod": "Confogl 对抗核心",
    "holdout_bonus": "坚守奖励",
    "l4dhots": "药丸持续回血",
    "l4d2lib": "L4D2 函数库",
    "lerpmonitor": "监视 Lerp",
    "mapchooser": "投票选图",
    "nominations": "提名地图",
    "pill_passer": "传递止痛药",
    "randomcycle": "随机地图循环",
    "ratemonitor": "监视速率",
    "rockthevote": "投票换图",
    "slots_vote": "投票改人数位",
    "teamflip": "猜队伍正反",
    "server_namer": "服务器命名",
    "command_menu": "命令菜单",
    "find_convar_cmd_owner": "查参数和命令来源",
    "l4d2_nativevote": "原生投票接口",
    "l4d2_levelchanging": "过图处理",
    "sm_restarter": "自动重启服务器",
    "sm_hours_limiter": "限制游戏时长",
    "sm_mapcycle_generator": "生成地图循环",
    "nmrih_events_notice": "事件通知",
    "nmrih_hide": "隐藏模型",
    "nmrih_skins": "皮肤",
    "l4d_stats": "玩家统计",
    "l4d2_welcome_message": "进服欢迎信息",
    "l4d2_skill_detect": "检测高光操作",
    "l4d2_playstats": "对局统计",
    "l4d2_playermanagement": "玩家管理",
    "l4d2_nightvision": "夜视仪",
    "l4d2_hide": "隐藏其他玩家",
    "l4d2_hp_distributing": "分配血量",
    "l4d2_cs_style_reload": "CS 风格换弹",
    "l4d2_scav_dhooks_natives": "清道夫接口",
    "l4d2_scav_gascan_selfburn": "油桶自燃",
    "l4d2_scav_round_end_miscs": "清道夫回合结束处理",
    "l4d2_practice_with_dominators": "练习特感控制技",
    "vote_custom_campaigns": "投票自定义战役",
    "l4d_freely_round_end": "回合结束自由行动",
    "l4d_freely_use_action": "自由使用物品动作",
    "l4d_consistent_escaperoute": "固定逃生路线",
    "l4d_pellet_spread_customizer": "自定义霰弹散布",
    "l4d_prop_touching_rules": "接触物体规则",
    "l4d_return_thrown_items": "归还投掷物",
    "l4d_temphp_prior": "虚血优先计算",
    "l4d_vomit_impulse": "胆汁击退",
    "l4d2_antibaiter": "防止摸鱼拖延",
    "l4d2_horde_equaliser": "尸潮均衡",
    "l4d2_map_transitions": "过图衔接",
    "l4d2_no_m2_pulled_and_hunters": "禁止被拉时右键推",
    "l4d2_nobackjumps": "禁止 Hunter 后跳扑",
    "l4d2_nobhaps": "禁止连跳",
    "l4d2_tongue_timer": "舌头计时",
    "l4d_boss_vote": "投票选 Boss",
    "l4d_mapbased_cvars": "按地图执行参数",
    "l4d2_tank_support": "Tank 支援",
    "l4d_aggressive_coop_tank": "战役 Tank 更主动",
    "l4d_boomer_fall_explode": "Boomer 坠落爆炸",
    "l4d_change_witch_victim": "更换 Witch 目标",
    "l4d_lagcomp_skeet": "延迟补偿空中击杀",
    "l4d_predict_tank_glow": "预知 Tank 发光",
    "l4d2_horde": "尸潮控制",
    "l4d2_jockey_skeet": "Jockey 空中击杀",
    "l4d2_no_hunter_deadstops": "禁止推停 Hunter",
    "l4d2_tank_damage_cvars": "Tank 伤害参数",
    "l4d2_tank_horde_monitor": "Tank 尸潮监视",
    "l4d2_unsilent_jockey": "Jockey 落地有声",
    "l4d_tank_painfade": "Tank 受伤红屏",
    "map_changer": "投票换图",
    "map_modify": "地图武器和物资生成",
}

_EN_PHRASE = [
    (r"friendly fire", "友伤"),
    (r"ready[\s\-]?up", "准备就绪"),
    (r"special infected", "特感"),
    (r"common infected", "小僵尸"),
    (r"safe ?room", "安全室"),
    (r"health bonus", "血量奖励"),
    (r"fall damage", "坠落伤害"),
    (r"ai director", "导演系统"),
    (r"viewmodel legs", "第一人称腿"),
    (r"through (?:thin )?walls?", "穿墙"),
    (r"rate of fire", "射速"),
    (r"alarm(?:ed)? cars?", "警报车"),
]

_EN_WORD = {
    "fix": "修复", "fixes": "修复", "fixed": "修复", "patch": "修补", "prevent": "防止",
    "block": "阻止", "blocks": "阻止", "allow": "允许", "allows": "允许", "enable": "开启",
    "enables": "开启", "disable": "关闭", "announce": "提示", "display": "显示", "restore": "还原",
    "optimize": "优化", "control": "控制", "adjust": "调整", "remove": "移除", "unlock": "解锁",
    "spawn": "生成", "respawn": "复活", "teleport": "传送", "drop": "丢弃", "give": "给予",
    "tank": "Tank", "witch": "Witch", "charger": "Charger", "hunter": "Hunter", "jockey": "Jockey",
    "smoker": "Smoker", "spitter": "Spitter", "boomer": "Boomer", "spit": "口水", "survivor": "生还者",
    "survivors": "生还者", "infected": "感染者", "commons": "小僵尸", "common": "小僵尸",
    "spectator": "旁观", "spectators": "旁观", "spec": "旁观", "versus": "对抗", "coop": "战役",
    "scavenge": "清道夫", "finale": "结局", "melee": "近战", "weapon": "武器", "weapons": "武器",
    "ladder": "梯子", "punch": "拳头", "shove": "推开", "pounce": "扑", "rock": "石头",
    "ghost": "灵魂", "collision": "碰撞", "hitbox": "判定", "vocalize": "语音", "voice": "语音",
    "hostname": "房名", "director": "导演", "glow": "发光", "ammo": "弹药", "health": "血量",
    "incap": "倒地", "chat": "聊天", "hud": "HUD", "config": "配置", "unicode": "Unicode",
    "stagger": "硬直", "charge": "冲锋", "getup": "起身", "hint": "标记", "item": "物品",
    "legs": "腿部", "knife": "刀", "grenade": "手雷", "admin": "管理员", "admins": "管理员",
    "scoring": "计分", "score": "计分", "scoremod": "计分", "spechud": "旁观HUD", "readyup": "准备就绪",
    "saferoom": "安全室", "checkpoint": "安全室", "damage": "伤害", "firerate": "射速",
    "prefix": "前缀", "playtime": "游戏时长", "pickup": "拾取", "rambos": "梯子开枪",
    "antibreach": "防拆安全门", "breach": "破门",
    "support": "支援", "aggressive": "主动", "explode": "爆炸", "fall": "坠落",
    "change": "更换", "victim": "目标", "consistent": "固定", "escaperoute": "逃生路线",
    "freely": "自由", "round": "回合", "end": "结束", "action": "动作",
    "lagcomp": "延迟补偿", "skeet": "空中击杀", "pellet": "霰弹", "spread": "散布",
    "customizer": "自定义", "predict": "预知", "touching": "接触", "rules": "规则",
    "return": "归还", "thrown": "投掷", "items": "物品", "temphp": "虚血", "prior": "优先",
    "vomit": "胆汁", "impulse": "推力", "hots": "持续治疗", "vote": "投票",
    "custom": "自定义", "campaigns": "战役", "horde": "尸潮", "equaliser": "均衡",
    "transitions": "过图", "deadstops": "推停", "cvars": "参数", "monitor": "监视",
    "tongue": "舌头", "timer": "计时", "unsilent": "有声", "lib": "函数库",
    "boss": "Boss", "mapbased": "按地图", "painfade": "受伤红屏", "bonus": "奖励",
    "pause": "暂停", "stats": "统计", "skill": "技巧", "detect": "检测",
    "hide": "隐藏", "reload": "换弹", "nightvision": "夜视", "welcome": "欢迎",
    "message": "消息", "practice": "练习", "gascan": "油桶", "selfburn": "自燃",
    "hours": "时长", "limiter": "限制", "restarter": "重启", "skins": "皮肤",
    "notice": "通知", "events": "事件", "namer": "命名", "menu": "菜单",
    "no": "禁止", "m2": "右键", "pulled": "被拉", "and": "", "with": "",
    "nativevote": "原生投票", "levelchanging": "过图", "antibaiter": "防摸鱼",
    "nobackjumps": "禁止后跳扑", "nobhaps": "禁止连跳", "playstats": "对局统计",
    "playermanagement": "玩家管理", "distributing": "分配",
}


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def extract_cjk_brief(text: str) -> str:
    if not text or not _has_cjk(text):
        return ""
    text = text.translate(_TRAD2SIMP)
    for m in re.finditer(r"[*+\-]\s+([^\n]{0,10}[\u4e00-\u9fff][^\n]{0,40})", text):
        s = re.sub(r"\s+", " ", m.group(1)).strip(" -*|")
        if "http" in s.lower():
            continue
        return (s[:22].rstrip() + "…") if len(s) > 22 else s
    m = re.search(r"[\u4e00-\u9fff][^。；;\n]{0,30}", text)
    if not m:
        return ""
    s = re.sub(r"\s+", " ", m.group(0)).strip()
    return (s[:22].rstrip() + "…") if len(s) > 22 else s


def brief_from_english(name: str, desc: str = "") -> str:
    key = (name or "").lower().strip()
    if key in _PLUGIN_NAME_ZH:
        return _PLUGIN_NAME_ZH[key]
    blob = f"{name} {desc}".lower().replace("_", " ").replace("-", " ")
    blob = re.sub(r"\s+", " ", blob)
    for pat, zh in _EN_PHRASE:
        blob = re.sub(pat, zh, blob, flags=re.I)
    verb = ""
    if re.search(r"\bfix(?:es|ing|ed)?\b|\bpatch(?:es|ed)?\b|修复|修补", blob):
        verb = "修复"
    elif re.search(r"\bprevent|\bblock|\bstop\b|防止|阻止", blob):
        verb = "防止"
    elif re.search(r"\ballow|\benable|\bunlock|允许|开启|解锁", blob):
        verb = "允许"
    elif re.search(r"\bannounce|\bnotify|\bdisplay|\bhud\b|\bprint|提示|显示", blob):
        verb = "提示"
    elif re.search(r"\brestore|还原", blob):
        verb = "还原"
    elif re.search(r"\boptimize|\bimprove|优化", blob):
        verb = "优化"
    elif re.search(r"\bcontrol|\bmanage|\badjust|控制|调整", blob):
        verb = "调整"
    elif re.search(r"\bremove|\bstrip|移除", blob):
        verb = "移除"
    objs: list[str] = []
    for pat, zh in [
        (r"友伤", "友伤"),
        (r"准备就绪", "准备就绪"),
        (r"导演系统", "导演系统"),
        (r"第一人称腿", "第一人称腿"),
        (r"穿墙", "穿墙"),
        (r"安全室|checkpoint", "安全室"),
        (r"特感|\bsi\b", "特感"),
        (r"小僵尸|\bcommons?\b", "小僵尸"),
        (r"\btank\b", "Tank"),
        (r"\bwitch\b", "Witch"),
        (r"\bcharger\b", "Charger"),
        (r"\bhunter\b", "Hunter"),
        (r"\bjockey\b", "Jockey"),
        (r"口水|\bspit", "口水"),
        (r"\bsurvivor", "生还者"),
        (r"旁观|\bspec", "旁观"),
        (r"计分|score", "计分"),
        (r"近战|melee", "近战"),
        (r"武器|weapon", "武器"),
        (r"梯子|ladder", "梯子"),
        (r"拳头|punch", "拳头"),
        (r"石头|rock\b", "石头"),
        (r"灵魂|ghost", "灵魂"),
        (r"碰撞|hitbox", "碰撞"),
        (r"语音|vocal", "语音"),
        (r"房名|hostname", "房名"),
        (r"倒地|incap", "倒地"),
        (r"冲锋|charge", "冲锋"),
        (r"起身|getup|get up", "起身"),
        (r"标记|hint", "标记"),
        (r"坠落伤害", "坠落伤害"),
        (r"血量奖励|health bonus", "血量奖励"),
        (r"结局|finale", "结局"),
        (r"警报车", "警报车"),
        (r"传送|teleport", "传送"),
        (r"复活|respawn", "复活"),
        (r"聊天|chat", "聊天"),
    ]:
        if re.search(pat, blob) and zh not in objs:
            objs.append(zh)
        if len(objs) >= 3:
            break
    if verb and objs:
        text = verb + "".join(objs[:3])
    elif objs:
        text = "".join(objs[:3])
    elif verb:
        text = verb
    else:
        bits = []
        for part in re.split(r"[_\-\s]+", (name or "").lower()):
            if part in {"l4d", "l4d1", "l4d2", "sm", "plugin", "smd"} or not part:
                continue
            mapped = _EN_WORD.get(part, "")
            if mapped and mapped not in bits:
                bits.append(mapped)
            if len(bits) >= 4:
                break
        text = "".join(bits)
    text = re.sub(r"\s+", "", text).strip()
    if not _has_cjk(text):
        return _PLUGIN_NAME_ZH.get(key, "")
    if len(text) > 22:
        text = text[:22].rstrip() + "…"
    return text


_TRAD2SIMP = str.maketrans({
    "復": "复", "複": "复", "訊": "讯", "檔": "档", "運": "运", "遲": "迟", "實": "实",
    "體": "体", "潰": "溃", "讀": "读", "導": "导", "頓": "顿", "預": "预", "組": "组",
    "還": "还", "偵": "检", "測": "测", "載": "载", "發": "发", "開": "开", "關": "关",
    "過": "过", "擲": "掷", "鏡": "镜", "視": "视", "倖": "幸", "隊": "队", "獵": "猎",
    "彈": "弹", "裝": "装", "殭": "僵", "屍": "尸", "後": "后", "製": "制", "專": "专",
    "腳": "脚", "圖": "图", "裡": "里", "憶": "忆", "誤": "误", "執": "执", "洩": "泄",
    "參": "参", "數": "数", "創": "创", "網": "网", "資": "资", "戶": "户", "於": "于",
    "務": "务", "穩": "稳", "駭": "骇", "適": "适", "遊": "游", "優": "优", "擊": "击",
    "傳": "传", "為": "为", "與": "与", "從": "从", "臺": "台", "註": "注", "釋": "释",
    "塊": "块", "換": "换", "滅": "灭", "團": "团", "語": "语", "對": "对", "講": "讲",
    "機": "机", "應": "应", "統": "统", "顯": "显", "護": "护", "撿": "捡", "區": "区",
    "並": "并", "寫": "写", "進": "进", "時": "时", "會": "会", "這": "这", "個": "个",
    "經": "经", "長": "长", "問": "问", "題": "题", "處": "处", "當": "当", "將": "将",
    "爾": "尔", "麼": "么", "內": "内", "稱": "称", "類": "类", "們": "们", "點": "点",
    "東": "东", "車": "车", "門": "门", "閉": "闭", "啟": "启", "動": "动", "態": "态",
    "條": "条", "線": "线", "餘": "余", "讓": "让", "準": "准", "選": "选", "單": "单",
    "瞭": "了", "擋": "挡", "強": "强", "產": "产", "錄": "录", "協": "协", "尋": "寻",
    "頻": "频", "檢": "检", "嘗": "尝", "試": "试", "輸": "输", "國": "国", "來": "来",
    "離": "离", "戲": "戏", "結": "结", "構": "构", "設": "设", "計": "计", "畫": "画",
    "報": "报", "頁": "页", "瀏": "浏", "覽": "览", "係": "系", "請": "请", "衝": "冲",
    "據": "据", "則": "则", "確": "确", "認": "认", "證": "证", "權": "权", "帳": "账",
    "買": "买", "賣": "卖", "聯": "联", "繫": "系", "斷": "断", "續": "续", "際": "际",
    "電": "电", "腦": "脑", "燈": "灯", "無": "无", "敵": "敌", "傷": "伤", "損": "损",
    "壞": "坏", "殺": "杀", "鎖": "锁", "鍵": "键", "鈕": "钮", "幫": "帮", "廣": "广",
    "場": "场", "間": "间", "佈": "布", "義": "义", "繪": "绘", "塗": "涂", "鴉": "鸦",
    "見": "见", "沒": "没", "購": "购", "總": "总", "記": "记", "員": "员", "許": "许",
    "譯": "译", "給": "给", "妳": "你", "歡": "欢", "迎": "迎", "歲": "岁", "幣": "币",
    "願": "愿", "響": "响", "聲": "声", "變": "变", "壓": "压", "幣": "币", "鍵": "键",
})


# 词组优先替换（含「伺服器→服务器」等单字表无法覆盖的）
_TRAD2SIMP_PHRASES = (
    ("伺服器", "服务器"),
    ("訊息", "信息"),
    ("資訊", "信息"),
    ("選單", "菜单"),
    ("檔案", "文件"),
    ("帳戶", "账户"),
    ("預設", "默认"),
    ("設定", "设置"),
    ("管理員", "管理员"),
    ("遊戲", "游戏"),
    ("連線", "连接"),
    ("網路", "网络"),
    ("記憶體", "内存"),
    ("涵式", "函数"),
    ("函式", "函数"),
    ("資料", "数据"),
    ("顯示", "显示"),
    ("瀏覽", "浏览"),
    ("螢幕", "屏幕"),
    ("滑鼠", "鼠标"),
    ("廣告", "广告"),
    ("塗鴉", "涂鸦"),
    ("崩潰", "崩溃"),
    ("駭客", "黑客"),
    ("封鎖", "封锁"),
    ("強化", "强化"),
    ("對應", "对应"),
    ("翻譯", "翻译"),
    ("特地", "特定"),
    ("準心", "准心"),
    ("傳送", "传送"),
    ("無敵", "无敌"),
    ("傷害", "伤害"),
    ("客戶", "客户"),
    ("頻繁", "频繁"),
    ("檢測", "检测"),
    ("試圖", "试图"),
    ("瞭解", "了解"),
    ("內容", "内容"),
    ("支援", "支持"),
    ("多國", "多国"),
    ("阻擋", "阻挡"),
    ("離開", "离开"),
    ("之後", "之后"),
    ("關閉", "关闭"),
    ("重啟", "重启"),
    ("允許", "允许"),
    ("定義", "定义"),
    ("執行", "执行"),
    ("更換", "更换"),
    ("修復", "修复"),
    ("子彈", "子弹"),
    ("擊中", "击中"),
    ("運算", "运算"),
    ("延遲", "延迟"),
    ("下載", "下载"),
    ("自製", "自制"),
    ("發光", "发光"),
    ("物件", "对象"),
    ("社群", "社区"),
    ("進入", "进入"),
    ("產生", "产生"),
    ("記錄", "记录"),
    ("實體", "实体"),
    ("協助", "协助"),
    ("數量", "数量"),
    ("創造", "创建"),
    ("國家", "国家"),
    ("進來", "进来"),
    ("開啟", "开启"),
    ("自動", "自动"),
)


def to_simplified_zh(text: str) -> str:
    """繁体说明转简体（菜单展示用）。"""
    if not text:
        return ""
    out = text
    for trad, simp in sorted(_TRAD2SIMP_PHRASES, key=lambda kv: len(kv[0]), reverse=True):
        if trad in out:
            out = out.replace(trad, simp)
    out = out.translate(_TRAD2SIMP)
    return out.replace("涵式", "函数").replace("记忆体", "内存")


def catalog_plugin_name(item: FixItem) -> str:
    slug = (item.slug or "").strip()
    if slug and re.fullmatch(r"[\w.\-]+", slug) and not slug.isdigit() and "php" not in slug.lower():
        return slug
    return item.name.strip() or slug or "plugin"


def mapped_plugin_zh_note(name: str) -> str:
    """优先返回内置简体说明。"""
    key = (name or "").lower().strip().replace("-", "_")
    if not key:
        return ""
    for table in (FIX_NOTE_ZH, _PLUGIN_NAME_ZH):
        if key in table:
            return table[key]
        for cand, note in table.items():
            ck = cand.lower().replace("-", "_")
            if ck == key or ck.replace("_", "") == key.replace("_", ""):
                return note
    return ""


def catalog_plugin_note(item: FixItem) -> str:
    mapped = mapped_plugin_zh_note(item.slug or "") or mapped_plugin_zh_note(item.name or "")
    if mapped:
        return mapped
    blob = " ".join(
        [
            (item.slug or "").lower().replace("-", "_"),
            normalize_key(item.name).replace(" ", "_"),
            (item.name or "").lower(),
        ]
    )
    compact = blob.replace("_", "").replace("-", "").replace(" ", "")
    hits = sorted(FIX_NOTE_ZH.items(), key=lambda kv: len(kv[0]), reverse=True)
    for key, note in hits:
        k = key.lower().replace("-", "_")
        if k in blob.replace("-", "_") or k.replace("_", "") in compact:
            return note
    text = re.sub(r"`+", "", item.note or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip(" :：-")
    if not text:
        text = re.sub(r"\s+", " ", item.name).strip()
    text = to_simplified_zh(text)
    for sep in ("。", "；", ";", "，", ",", "："):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    if not _has_cjk(text):
        alt = brief_from_english(item.name or item.slug or "", text)
        if alt:
            text = alt
    if len(text) > 22:
        text = text[:22].rstrip() + "…"
    return text


def catalog_pick_label(item: FixItem) -> str:
    return f"{catalog_plugin_name(item)} | {catalog_plugin_note(item)}"


def plugin_zh_label(name: str, note: str = "", prefix: str = "") -> str:
    shown = f"{prefix}/{name}" if prefix else name
    mapped = mapped_plugin_zh_note(name)
    if mapped:
        return f"{shown} | {mapped}"
    text = to_simplified_zh((note or "").strip())
    # 豆瓣酱等完整中文目录名：不要再截断到 22 字
    if text and (
        DOUBAN_FOLDER_RE.match(text)
        or PLATFORM_FOLDER_RE.search(text)
        or (_has_cjk(text) and len(text) > 22 and text != name)
    ):
        return f"{shown} | {text}"
    fake = FixItem(
        name=name,
        url="",
        slug=name,
        section="",
        category="",
        tag="",
        note=text,
        games=set(),
        oses=set(),
    )
    brief = catalog_plugin_note(fake)
    if brief:
        return f"{shown} | {to_simplified_zh(brief)}"
    return shown


def _read_text_head(path: Path, limit: int = 200000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def extract_sp_note(raw: str) -> str:
    skip = ("作者", "翻译", "copyright", "http", "www.", "alliedmodders")
    best = ""
    for m in re.finditer(r'"([^"\n]{2,120})"', raw):
        s = m.group(1)
        if not _has_cjk(s):
            continue
        if re.search(r"\\x[0-9a-fA-F]{2}", s) or re.search(r"[\x00-\x1f]", s):
            continue
        low = s.lower()
        if any(x in low or x in s for x in skip):
            continue
        s = s.translate(_TRAD2SIMP)
        s = re.sub(r"\\[nt]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        if "。" in s:
            s = s.split("。", 1)[0].strip()
        if len(s) > 22:
            s = s[:22].rstrip() + "…"
        if 6 <= len(re.sub(r"\s+", "", s)) <= 22:
            return s
        if len(s) > len(best):
            best = s
    if best:
        return best
    m = re.search(r"\bdescription\s*=\s*\"([^\"]+)\"", raw, re.I)
    if m:
        mapped = brief_from_english("", m.group(1))
        if _has_cjk(mapped):
            return mapped
    return ""


def iter_plugin_note_files(path: Path):
    if path.is_file():
        stem = path.stem
        parent = path.parent
        seen: set[Path] = set()
        candidates = [
            path.with_suffix(".sp"),
            parent / f"{stem}.sp",
            parent.parent / "scripting" / f"{stem}.sp",
        ]
        cur = parent
        for _ in range(6):
            if (cur / "scripting").is_dir():
                candidates.append(cur / "scripting" / f"{stem}.sp")
                break
            if cur.parent == cur:
                break
            cur = cur.parent
        for cand in candidates:
            try:
                resolved = cand.resolve()
            except OSError:
                continue
            if resolved in seen or not cand.is_file():
                continue
            seen.add(resolved)
            yield cand
        return
    for pat in ("README*", "readme*", "*.md", "*说明*"):
        for cand in sorted(path.glob(pat)):
            if cand.is_file():
                yield cand
    script = path / "scripting"
    sp_iter = script.glob("*.sp") if script.is_dir() else path.glob("*.sp")
    for cand in sorted(sp_iter)[:12]:
        if cand.is_file():
            yield cand


def resolve_plugin_note(rp: RemotePlugin, extra: dict[str, str]) -> str:
    name = rp.name
    mapped = mapped_plugin_zh_note(name)
    if mapped:
        return mapped
    folder_name = rp.path.name if rp.path.is_dir() else ""
    # 豆瓣酱 JS-MODS：直接用完整目录名做说明（转简体）
    if folder_name and (
        DOUBAN_FOLDER_RE.match(folder_name) or PLATFORM_FOLDER_RE.search(folder_name)
    ):
        return to_simplified_zh(folder_name)
    folder_note = pack_folder_note(folder_name) if folder_name else ""
    for cand in (extra.get(name, ""), extra.get(folder_name, ""), folder_note):
        if _has_cjk(cand) and cand.strip() not in {name}:
            return to_simplified_zh(cand.strip())
    if folder_name and _has_cjk(folder_note):
        return to_simplified_zh(folder_note)
    for src in iter_plugin_note_files(rp.path):
        raw = _read_text_head(src)
        if not raw:
            continue
        if src.suffix.lower() == ".sp":
            note = extract_sp_note(raw)
        else:
            note = extract_cjk_brief(raw)
            if not note:
                para = re.split(r"\n\s*\n", raw.strip(), 1)[0]
                para = re.sub(r"^#+\s*", "", para)
                para = re.sub(r"<[^>]+>", "", para)
                note = brief_from_english(name, para)
        if _has_cjk(note):
            return to_simplified_zh(note)
    return to_simplified_zh(extra.get(name, ""))


def print_catalog(spec: TutorialSpec, keep: list[FixItem], skipped: list[tuple[FixItem, str]]) -> None:
    print()
    print(f"=== 将安装（{spec.keep_title}）===")
    last_section = None
    n = 0
    for item in keep:
        if item.section != last_section:
            print(f"  -- {item.section or '未分类'} --")
            last_section = item.section
        n += 1
        tag = f" ({item.tag})" if item.tag else ""
        print(f"  {n:2}. {item.name}{tag}")
        print(f"      {item.url}")
    if skipped:
        print()
        print("=== 已排除 ===")
        by: dict[str, list[str]] = {}
        for item, reason in skipped:
            by.setdefault(reason, []).append(item.name)
        for reason, names in by.items():
            print(f"  [{reason}] {', '.join(names)}")
    print()


CATALOG_FIXES = TutorialSpec(
    key="fixes",
    title="实用修复",
    keep_title="Windows + L4D2 修复，不含反作弊",
    raw_url=FIX_README_RAW,
    page_url=FIX_README_PAGE,
    use_fix_filters=True,
)
CATALOG_8COOP = TutorialSpec(
    key="8coop",
    title="8人战役",
    keep_title="8人战役：准备/必要/额外，不含娱乐、不建议、划线",
    raw_url=COOP8_README_RAW,
    page_url=COOP8_README_PAGE,
    keep_sections=("準備檔案", "准备档案", "必要檔案", "必要档案", "額外檔案", "额外档案"),
    skip_sections=("娛樂檔案", "娱乐档案", "不建議安裝", "不建议安装"),
)


def known_plugins_index(game_dir: Path) -> dict[str, RemotePlugin]:
    index: dict[str, RemotePlugin] = {}
    for repo in get_config().repos:
        try:
            sync_cache(repo)
        except Exception as e:
            print(f"更新仓库缓存失败 {repo.key}: {e}")
            if not cache_has_plugins(repo.cache):
                continue
        for rp in scan_remote_plugins(repo):
            index[rp.name.lower()] = rp
            for smx in rp.smx_names:
                index[Path(smx).stem.lower()] = rp
    return index


def catalog_item_keys(item: FixItem) -> set[str]:
    return {
        item.slug.lower(),
        item.slug.lower().replace("-", "_"),
        re.sub(r"[^\w]+", "_", item.name).lower(),
        normalize_key(item.name).replace(" ", "_"),
    }


def merge_require_index(known: dict[str, RemotePlugin]) -> dict[str, RemotePlugin]:
    index = dict(known)
    try:
        for rp in load_private_l4d_plugins():
            index.setdefault(rp.name.lower(), rp)
            for smx in rp.smx_names:
                index.setdefault(Path(smx).stem.lower(), rp)
    except Exception as e:
        print(f"读取 L4D_插件 Require 失败: {e}")
    return index


def catalog_require_targets(
    keep: list[FixItem],
    index: dict[str, RemotePlugin],
) -> tuple[list[RemotePlugin], set[str]]:
    selected: list[RemotePlugin] = []
    names: set[str] = set()
    seen: set[str] = set()
    for item in keep:
        keys = catalog_item_keys(item)
        names |= keys
        rp: RemotePlugin | None = None
        for k in keys:
            if k in index:
                rp = index[k]
                break
        slug = item.slug.lower().replace("-", "_")
        if rp is None:
            rp = RemotePlugin(
                name=item.slug,
                path=Path("."),
                repo=CATALOG_REPO,
                smx_names=[item.slug],
                requires=[],
            )
        requires = augment_plugin_requires(rp.name, list(rp.requires), rp.repo)
        requires = augment_plugin_requires(slug, requires, rp.repo)
        rp = RemotePlugin(
            name=rp.name,
            path=rp.path,
            repo=rp.repo,
            smx_names=rp.smx_names or [item.slug],
            requires=requires,
        )
        ident = rp.name.lower()
        if ident in seen:
            continue
        seen.add(ident)
        names.add(ident)
        names |= rp.keys
        selected.append(rp)
    return selected, names


def try_env_install_for_item(item: FixItem, env: LocalEnv, dry_run: bool) -> str | None:
    key = normalize_key(item.name)
    slug = item.slug.lower()
    mapping = (
        (("left4dhooks", "left 4 dhooks"), "left4dhooks"),
        (("l4dtoolz", "l4d toolz"), "l4dtoolz"),
        (("actions", "action"), "actions"),
        (("dhooks",), "dhooks"),
        (("sourcescramble", "source scramble"), "sourcescramble"),
        (("builtinvotes", "builtin votes"), "builtinvotes"),
        (("collisionhook", "collision hook"), "collisionhook"),
        (("smlib",), "smlib"),
        (("linux_auto_restart", "linux auto restart"), "linux_auto_restart"),
        (("server_loader", "server loader"), "server_loader"),
        (("smd_advertisements",), "smd_advertisements"),
        (("smd_dynamichostname", "dynamic hostname"), "smd_dynamichostname"),
        (("cannounce", "connect announce"), "cannounce"),
    )
    for needles, env_key in mapping:
        if any(n in key or n in slug for n in needles):
            fn = lookup_plugin_installer(env_key)
            if not fn:
                continue
            if dry_run:
                return f"预览: 更新依赖 {env_key}"
            return fn(env.game_dir)
    return None


def install_fix_item(
    item: FixItem,
    env: LocalEnv,
    known: dict[str, RemotePlugin],
    dry_run: bool,
    update_configs: bool,
) -> str:
    env_msg = try_env_install_for_item(item, env, dry_run)
    if env_msg is not None:
        return env_msg
    if forced_am_sp_url(item.name, item.slug, item.url):
        req = Requirement(name=item.name, url=item.url, slug=item.slug)
        return try_install_requirement(req, env, dry_run)
    keys = {item.slug.lower(), item.slug.lower().replace("-", "_"), re.sub(r"[^\w]+", "_", item.name).lower()}
    rp = None
    for k in keys:
        if k in known:
            rp = known[k]
            break
    if rp is None:
        for name, cand in known.items():
            if name in item.slug.lower() or item.slug.lower() in name:
                if len(name) >= 8:
                    rp = cand
                    break
    if rp is not None:
        if dry_run:
            return f"预览: 从已配置仓库 {rp.repo.key}/{rp.name} 安装"
        hits = []
        for lp in env.plugins:
            if lp.name.lower() in rp.keys:
                hits.append(lp)
        actions = plan_actions([(rp, hits)], env.game_dir, update_configs)
        counts = apply_actions(actions, env.game_dir, False)
        compiled = counts.get("compiled", 0)
        extra = f", 编译 {compiled}" if compiled else ""
        return with_plugin_extras(
            [item.slug, item.name, rp.name],
            env,
            dry_run,
            (
                f"来自 {rp.repo.key}/{rp.name}: "
                f"新增 {counts['new']}, 更新 {counts['update']}, 相同 {counts['skip_same']}{extra}"
            ),
        )
    req = Requirement(name=item.name, url=item.url, slug=item.slug)
    msg = try_install_requirement(req, env, dry_run)
    return with_plugin_extras(
        [item.slug, item.name, item.slug.lower().replace("-", "_")],
        env,
        dry_run,
        msg,
    )


def run_catalog(args: argparse.Namespace, spec: TutorialSpec, pick: bool = False) -> None:
    keep, skipped = load_catalog(spec)
    if pick:
        if not keep:
            print("清单里没有可安装项。")
            return
        idx = pick_multi_list(
            f"选择要安装的{spec.title}插件",
            [catalog_pick_label(it) for it in keep],
            empty_hint="至少选择一个插件。",
        )
        if idx is None:
            print("已返回。")
            return
        keep = [keep[i] for i in idx]
        print()
        print("将安装: " + "、".join(catalog_plugin_name(it) for it in keep))
        print()
    else:
        print_catalog(spec, keep, skipped)
        if not keep:
            print("清单里没有可安装项。")
            return
    env = scan_local_env(args.game_dir)
    print(f"本地已安装插件 {len(env.plugins)} 个")
    if args.dry_run:
        print("（预览模式，不会写入）")
        for item in keep:
            print(f"-> {item.name}")
            print(f"   预览: {item.url}")
        return
    print("正在准备已配置仓库缓存，优先从 l4d/sm 安装同名插件...")
    known = known_plugins_index(args.game_dir)
    ok_n = fail_n = 0
    print()
    print("=== 开始安装 ===")
    try:
        for item in keep:
            print(f"-> {item.name}")
            try:
                msg = install_fix_item(item, env, known, False, args.update_configs)
                print(f"   {msg}")
                ok_n += 1
            except Exception as e:
                print(f"   失败: {e}")
                if item.url:
                    print(f"   请手动打开: {item.url}")
                log_failure(f"{spec.title}安装失败: {item.name}", e, item.url)
                fail_n += 1
            env = scan_local_env(args.game_dir)
    finally:
        close_am_session()
    print()
    print(f"{spec.title}完成: 成功 {ok_n}, 失败 {fail_n}")
    if fail_n:
        print(f"失败已写入: {LOG_FILE}")
    env = scan_local_env(args.game_dir)
    print()
    print(f"=== Require 检测（本次{spec.title}清单插件） ===")
    selected, names = catalog_require_targets(keep, merge_require_index(known))
    groups = print_require_report(selected, env, missing_only=True, local_names=names)
    if not groups:
        print("清单插件的 Require 均已在本地找到。")
        return
    print(f"\n合计 {len(groups)} 项缺失依赖。")
    if getattr(args, "fetch_deps", True):
        fetch_missing_deps(groups, env, args.dry_run)
        env = scan_local_env(args.game_dir)
        leftover = collect_local_gamedata_gaps(
            selected,
            env,
            collect_missing(selected, env, local_names=names),
            local_names=names,
        )
        if leftover:
            print(f"\n仍缺 {len(leftover)} 项，需手动安装。")
            print_missing_groups(leftover)
        else:
            print("\n自动下载后，本次清单插件的 Require 均已满足。")
    else:
        print("未自动下载。安装时会一并拉取缺失 Require。")


def cmd_fixes(args: argparse.Namespace, pick: bool = False) -> None:
    if getattr(args, "remove_catalog", False):
        remove_catalog_plugins(args, CATALOG_FIXES)
        return
    run_catalog(args, CATALOG_FIXES, pick=pick)


def cmd_8coop(args: argparse.Namespace, pick: bool = False) -> None:
    if getattr(args, "remove_catalog", False):
        remove_catalog_plugins(args, CATALOG_8COOP)
        return
    run_catalog(args, CATALOG_8COOP, pick=pick)


def find_sourcemod_plugins_repo() -> RepoSpec | None:
    for r in get_config().listed_repos():
        url = (r.git_url or "").lower()
        if "sourcemod-plugins" in url:
            return r
        if r.key.lower() in {"sourcemod", "sm"}:
            return r
    return None


def parse_readme_table_notes(text: str) -> dict[str, str]:
    notes: dict[str, str] = {}
    for raw in text.splitlines():
        s = raw.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if re.fullmatch(r":?-{2,}:?", cells[0].replace(" ", "")):
            continue
        name_cell, desc = cells[0], cells[1]
        if re.search(r"插件名字|功能介绍|^name$|^plugin$", name_cell, re.I):
            continue
        m = re.search(r"\[([^\]]+)\]", name_cell)
        name = re.sub(r"[*`]", "", (m.group(1) if m else name_cell)).strip()
        if not name or "/" in name or " " in name:
            name = Path(name).stem if name else ""
        if not name or not re.fullmatch(r"[\w.\-]+", name):
            continue
        desc = re.sub(r"<br\s*/?>", "。", desc, flags=re.I)
        desc = re.sub(r"<[^>]+>", "", desc)
        desc = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", desc)
        desc = re.sub(r"\*\*|`", "", desc)
        desc = re.sub(r"\s+", " ", desc).strip()
        for sep in ("。", "；", ";"):
            if sep in desc:
                desc = desc.split(sep, 1)[0].strip()
                break
        if not _has_cjk(desc):
            continue
        if len(desc) > 22:
            desc = desc[:22].rstrip() + "…"
        notes[name] = desc
    return notes


def parse_sm_readme_notes(text: str) -> dict[str, str]:
    notes: dict[str, str] = {}
    current = ""
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("#") and re.search(r"\bCSS\b|\bNMRIH\b", s, re.I):
            break
        m = re.search(r"\[([^\]]+)\]\([^)]*\)", s)
        if m and s.lstrip().startswith("*"):
            current = m.group(1).strip()
            continue
        if current and s.startswith("*"):
            note = re.sub(r"<[^>]+>", "", s.lstrip("* ").strip())
            if note:
                notes[current] = note
            current = ""
    notes.update(parse_readme_table_notes(text))
    return notes


def load_repo_readme_notes(repo: RepoSpec) -> dict[str, str]:
    for name in ("readme.md", "README.md"):
        path = repo.cache / name
        if path.is_file():
            return parse_sm_readme_notes(path.read_text(encoding="utf-8", errors="replace"))
    return {}


def cmd_pick_repo_plugins(
    game_dir: Path,
    repos: list[RepoSpec],
    title: str,
    skip_prefixes: tuple[str, ...] = (),
    *,
    deep: bool = False,
    on_cancel: str = "cancel",
) -> str | None:
    if not repos:
        print("没有可用仓库。")
        return
    plugins: list[RemotePlugin] = []
    extra: dict[str, str] = {}
    for repo in repos:
        print(f"读取仓库: {repo.key}")
        try:
            sync_cache(repo)
        except Exception as e:
            print(f"更新仓库缓存失败 {repo.key}: {e}")
            if not cache_has_plugins(repo.cache):
                continue
        extra.update(load_repo_readme_notes(repo))
        for rp in scan_remote_plugins(repo, deep=deep or len(repos) == 1):
            if rp.name.lower().startswith(skip_prefixes):
                continue
            if rp.path.is_dir() and rp.path.name not in extra:
                extra.setdefault(rp.name, pack_folder_note(rp.path.name))
            plugins.append(rp)
    if not plugins:
        print("仓库里没有可安装插件。")
        return "empty"
    plugins.sort(
        key=lambda rp: (
            pack_category_rank(rp.path.name if rp.path.is_dir() else rp.name),
            rp.name.lower(),
        )
    )
    multi = len({rp.repo.key for rp in plugins}) > 1
    labels = [
        plugin_zh_label(
            rp.name,
            resolve_plugin_note(rp, extra),
            prefix=rp.repo.key if multi else "",
        )
        for rp in plugins
    ]
    idx = pick_multi_list(title, labels, empty_hint="至少选择一个插件。")
    if idx is None:
        if on_cancel != "back":
            print("已返回。")
        return on_cancel
    picked = [plugins[i] for i in idx]
    names = [rp.name for rp in picked]
    repo_key = picked[0].repo.key if len({rp.repo.key for rp in picked}) == 1 else "all"
    print()
    print("将安装: " + "、".join(names))
    print()
    cmd_install(make_cmd_args(game_dir, repo_key, names=names, fetch_deps=True))
    return "done"


def cmd_pick_specified_plugins(game_dir: Path) -> None:
    listed = get_config().listed_repos()
    if not listed:
        print("config.txt 中没有仓库行。")
        return
    while True:
        labels = [
            f"{r.key}  ({r.name})" + ("" if r.enabled else "  [未启用]")
            for r in listed
        ]
        idx = pick_multi_list(
            "选择仓库",
            labels,
            single=True,
        )
        if idx is None:
            print("已返回。")
            return
        repo = listed[idx[0]]
        result = cmd_pick_repo_plugins(
            game_dir,
            [repo],
            f"选择要安装的 {repo.key} 插件",
            deep=True,
            on_cancel="back",
        )
        if result == "empty":
            pause_menu()
            continue
        if result == "back":
            continue
        return


def cmd_pick_sourcemod_plugins(game_dir: Path) -> None:
    repo = find_sourcemod_plugins_repo()
    if repo is None:
        print("config.txt 中没有 Sourcemod-Plugins 仓库。")
        return
    cmd_pick_repo_plugins(
        game_dir,
        [repo],
        "选择要安装的 Sourcemod-Plugins 插件",
        skip_prefixes=("css_", "nmrih_"),
    )


def catalog_remove_stems(keep: list[FixItem], known: dict[str, RemotePlugin]) -> set[str]:
    stems: set[str] = set()
    am = load_am_installed()
    for item in keep:
        stems |= {k.lower() for k in catalog_item_keys(item) if k}
        slug = (item.slug or "").lower().replace("-", "_")
        if slug:
            stems.add(slug)
            stems.add(Path(slug).stem.lower())
        for k in catalog_item_keys(item):
            rp = known.get(k)
            if rp:
                for smx in rp.smx_names:
                    stems.add(Path(smx).stem.lower())
        url_key = (item.url or "").split("#")[0].rstrip("/").lower()
        for fname in am.get(url_key) or []:
            if str(fname).lower().endswith((".smx", ".sp")):
                stems.add(Path(fname).stem.lower())
        path_name = Path(unquote(urlparse(item.url or "").path)).name
        if path_name:
            stems.add(Path(path_name).stem.lower())
    return {s for s in stems if s}


def remove_catalog_plugins(args: argparse.Namespace, spec: TutorialSpec) -> None:
    keep, skipped = load_catalog(spec)
    print_catalog(spec, keep, skipped)
    if not keep:
        print("清单里没有可删除项。")
        return
    env = scan_local_env(args.game_dir)
    known = known_plugins_index(args.game_dir)
    stems = catalog_remove_stems(keep, known)
    protected = {k.lower() for k in ENV_INSTALLERS}
    hits = [
        p
        for p in env.plugins
        if p.name.lower() in stems and p.name.lower() not in protected
    ]
    if not hits:
        print(f"本地没有已安装的{spec.title}插件（配置未改）。")
        return
    print()
    print(f"=== 将删除以下{spec.title}插件（保留 configs/data/cfg）===")
    for p in hits:
        flag = " [disabled]" if p.disabled else ""
        print(f"  {p.path}{flag}")
    print(f"共 {len(hits)} 个。")
    if args.dry_run:
        print("（预览模式，不会删除）")
        return
    confirm = pick_multi_list(
        f"确认删除以上 {len(hits)} 个{spec.title}插件？",
        ["确认删除", "返回"],
        single=True,
    )
    if confirm is None or confirm[0] != 0:
        print("已返回。")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = SCRIPT_DIR / "backups" / f"{spec.key}_plugins_{stamp}"
    bak.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in hits:
        dest = bak / p.path.name
        if dest.exists():
            dest = bak / f"{p.path.stem}_{n}{p.path.suffix}"
        try:
            shutil.copy2(p.path, dest)
            p.path.unlink()
            n += 1
            print(f"   已删除 {p.path.name}")
        except OSError as e:
            print(f"   删除失败 {p.path.name}: {e}")
            log_failure(f"{spec.title}删除失败: {p.path.name}", e)
    print()
    print(f"{spec.title}插件已删除 {n} 个，配置保留。备份: {bak}")


def print_require_report(
    plugins: list[RemotePlugin],
    env: LocalEnv,
    missing_only: bool = False,
    local_names: set[str] | None = None,
) -> list[dict]:
    if not missing_only:
        for rp in plugins:
            if not rp.requires:
                print(f"{rp.repo.key}/{rp.name}: 仓库未列出 Require（或为 None）")
                continue
            print(f"{rp.repo.key}/{rp.name}:")
            for req in rp.requires:
                result = check_requirement(req, env)
                mark = "OK" if result.ok else "缺"
                extra = f"  -> {result.where}" if result.where else ""
                print(f"    [{mark}] {req.name}{extra}")
        print()
    groups = collect_local_gamedata_gaps(
        plugins,
        env,
        collect_missing(plugins, env, local_names=local_names),
        local_names=local_names,
    )
    print_missing_groups(groups)
    return groups


def cmd_list(args: argparse.Namespace) -> None:
    env = scan_local_env(args.game_dir)
    remote = load_remotes(selected_repos(args))
    matched, remote_only, _ = match_plugins(remote, env.plugins)

    print(f"远程插件: {len(remote)}    本地 .smx: {len(env.plugins)}    可同步: {len(matched)}")
    print()
    by_repo: dict[str, list[tuple[RemotePlugin, list[LocalPlugin]]]] = {}
    for rp, hits in matched:
        by_repo.setdefault(rp.repo.name, []).append((rp, hits))
    for repo_name, rows in by_repo.items():
        print(f"=== 已安装且可同步（{repo_name}，{len(rows)}） ===")
        for rp, hits in rows:
            places = ", ".join(
                ("[disabled] " if h.disabled else "") + h.path.name for h in hits
            )
            print(f"  {rp.name:40} <- {places}")
        print()

    if args.show_all:
        print("=== 仓库有、本地未安装 ===")
        for rp in remote_only:
            smx = ", ".join(rp.smx_names) or "(无 smx)"
            print(f"  [{rp.repo.key}] {rp.name:40} {smx}")


def cmd_search(args: argparse.Namespace) -> None:
    env = scan_local_env(args.game_dir)
    remote = load_remotes(selected_repos(args))
    q = args.keyword.lower()
    hits = [rp for rp in remote if q in rp.name.lower() or any(q in n.lower() for n in rp.smx_names)]
    if not hits:
        print(f"没有找到包含「{args.keyword}」的插件")
        return
    print(f"搜索「{args.keyword}」共 {len(hits)} 个:")
    for rp in hits:
        installed = "已安装" if rp.keys & env.plugin_names else "未安装"
        smx = ", ".join(rp.smx_names) or "-"
        print(f"  [{rp.repo.key}] [{installed}] {rp.name:40} {smx}")


def print_sync_by_plugin(
    matched: list[tuple[RemotePlugin, list[LocalPlugin]]],
    actions: list[FileAction],
) -> None:
    stats: dict[str, dict[str, int]] = {}
    for act in actions:
        row = stats.setdefault(act.plugin, {"new": 0, "update": 0, "skip_same": 0, "skip_config": 0})
        row[act.kind] += 1
    by_repo: dict[str, list[str]] = {}
    for rp, _hits in matched:
        by_repo.setdefault(rp.repo.key, []).append(rp.name)
    print()
    for repo_key, names in by_repo.items():
        print(f"=== {repo_key} 各插件 ===")
        for name in names:
            c = stats.get(name, {"new": 0, "update": 0, "skip_same": 0, "skip_config": 0})
            if c["update"] or c["new"]:
                print(
                    f"  [有更新] {name}: 更新 {c['update']}, 新增 {c['new']}, "
                    f"相同 {c['skip_same']}, 保留配置 {c['skip_config']}"
                )
            elif c["skip_config"]:
                print(f"  [已是最新/保留配置] {name}")
            else:
                print(f"  [已是最新] {name}")
        print()


def cmd_sync(args: argparse.Namespace) -> None:
    env = scan_local_env(args.game_dir)
    remote = load_remotes(selected_repos(args))
    matched, _, _ = match_plugins(remote, env.plugins)
    if args.plugins:
        want = {n.lower() for n in args.plugins}
        matched = [
            (rp, hits)
            for rp, hits in matched
            if rp.keys & want or rp.name.lower() in want
        ]
        if not matched:
            raise SystemExit("指定的插件本地未安装，或不在选定仓库中。可用 search/list 查看。")
    if not matched:
        print("本地没有与选定仓库对应的已安装插件。")
        return

    actions = plan_actions(matched, args.game_dir, args.update_configs)
    print(f"将同步 {len(matched)} 个插件, {len(actions)} 个文件")
    if args.dry_run:
        print("（预览模式，不会写入）")
    counts = apply_actions(actions, args.game_dir, args.dry_run)
    print()
    compiled = counts.get("compiled", 0)
    print(
        "完成: "
        f"新增 {counts['new']}, "
        f"更新 {counts['update']}, "
        f"相同跳过 {counts['skip_same']}, "
        f"保留本地配置 {counts['skip_config']}"
        + (f", 编译 {compiled}" if compiled else "")
    )
    print_sync_by_plugin(matched, actions)
    if counts["skip_config"] and not args.update_configs:
        print("提示: 已存在的 configs/data 默认不覆盖。如需覆盖请加 --update-configs")

    print()
    print("=== Require 检测（仅本次同步的插件，重复项已合并） ===")
    synced = [rp for rp, _ in matched]
    sync_names = {k for rp in synced for k in rp.keys}
    env = scan_local_env(args.game_dir)
    groups = print_require_report(
        synced, env, missing_only=True, local_names=sync_names
    )
    if not groups:
        print("已同步插件的 Require 项均已在本地找到。")
    else:
        print(f"\n合计 {len(groups)} 项缺失依赖。")
        if args.fetch_deps:
            fetch_missing_deps(groups, env, args.dry_run)
            env = scan_local_env(args.game_dir)
            leftover = collect_local_gamedata_gaps(
                synced,
                env,
                collect_missing(synced, env, local_names=sync_names),
                local_names=sync_names,
            )
            if leftover:
                print(f"\n仍缺 {len(leftover)} 项，需手动安装。")
                print_missing_groups(leftover)
            else:
                print("\n自动下载后，检测范围内的 Require 均已满足。")
        else:
            print("未自动下载。加上 --fetch-deps 或运行: python sync_plugins.py check --fetch-deps")


def cmd_install(args: argparse.Namespace) -> None:
    env = scan_local_env(args.game_dir)
    remote = load_remotes(selected_repos(args))
    selected = filter_by_names(remote, args.names)
    fake_hits = [(rp, []) for rp in selected]
    actions = plan_actions(fake_hits, args.game_dir, args.update_configs)
    print(f"将安装 {len(selected)} 个插件")
    if args.dry_run:
        print("（预览模式，不会写入）")
    counts = apply_actions(actions, args.game_dir, args.dry_run)
    compiled = counts.get("compiled", 0)
    print(
        "完成: "
        f"新增 {counts['new']}, "
        f"更新 {counts['update']}, "
        f"相同跳过 {counts['skip_same']}, "
        f"保留本地配置 {counts['skip_config']}"
        + (f", 编译 {compiled}" if compiled else "")
    )
    print()
    print("=== Require 检测 ===")
    install_names = {k for rp in selected for k in rp.keys}
    env = scan_local_env(args.game_dir)
    groups = print_require_report(
        selected, env, missing_only=False, local_names=install_names
    )
    if groups and args.fetch_deps:
        fetch_missing_deps(groups, env, args.dry_run)
        env = scan_local_env(args.game_dir)
        leftover = collect_local_gamedata_gaps(
            selected,
            env,
            collect_missing(selected, env, local_names=install_names),
            local_names=install_names,
        )
        if leftover:
            print(f"\n仍缺 {len(leftover)} 项，需手动安装。")
            print_missing_groups(leftover)
        else:
            print("\n自动下载后，检测范围内的 Require 均已满足。")


def cmd_check(args: argparse.Namespace) -> None:
    env = scan_local_env(args.game_dir)
    print_env_summary(env)
    remote = load_remotes(selected_repos(args))
    try:
        remote = remote + load_private_l4d_plugins()
    except Exception as e:
        print(f"读取 L4D_插件 Require 失败: {e}")
    if args.plugins:
        targets = filter_by_names(remote, args.plugins)
    elif args.all_remote:
        targets = remote
    else:
        matched, _, _ = match_plugins(remote, env.plugins)
        targets = [rp for rp, _ in matched]
        print(f"检测本地已安装且能对上仓库的 {len(targets)} 个插件\n")
    groups = print_require_report(targets, env, missing_only=args.missing_only)
    print()
    if not groups:
        print("检测范围内的 Require 均已满足（仓库未写 Require 的插件未计入）。")
        return
    print(f"合计缺失 {len(groups)} 项（重复已合并）。")
    if args.fetch_deps:
        fetch_missing_deps(groups, env, args.dry_run)
        env = scan_local_env(args.game_dir)
        leftover = collect_local_gamedata_gaps(targets, env, collect_missing(targets, env))
        if leftover:
            print(f"\n仍缺 {len(leftover)} 项。")
            print_missing_groups(leftover)
        else:
            print("\n自动下载后，检测范围内的 Require 均已满足。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 config.txt 读取游戏目录和仓库，同步插件并检测 Require。无参数时打开菜单。"
    )
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=None,
        help="覆盖 config.txt 中的游戏目录",
    )
    parser.add_argument(
        "--repo",
        default="all",
        help="仓库简称（config.txt 里的 key），或 all（默认）",
    )
    parser.add_argument(
        "--update-configs",
        action="store_true",
        help="覆盖已存在的 configs/data（默认保留你改过的配置）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示将要做的操作，不实际写入",
    )
    parser.add_argument(
        "--fetch-deps",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="发现缺失 Require 时自动下载/编译（默认开启，关闭: --no-fetch-deps）",
    )
    parser.add_argument(
        "--menu",
        action="store_true",
        help="打开交互菜单（双击 bat 默认进入）",
    )

    sub = parser.add_subparsers(dest="command", required=False)

    p_list = sub.add_parser("list", help="列出远程插件与本地已安装的对应关系")
    p_list.add_argument("--show-all", action="store_true", help="同时列出未安装的仓库插件")
    p_list.set_defaults(func=cmd_list)

    p_search = sub.add_parser("search", help="按名称搜索仓库插件")
    p_search.add_argument("keyword")
    p_search.set_defaults(func=cmd_search)

    p_sync = sub.add_parser("sync", help="更新本地已经安装、且仓库中存在的插件")
    p_sync.add_argument("plugins", nargs="*", help="只同步指定插件名（默认全部匹配项）")
    p_sync.set_defaults(func=cmd_sync)

    p_install = sub.add_parser("install", help="从仓库安装尚未本地安装的插件")
    p_install.add_argument("names", nargs="+", help="仓库中的插件文件夹名或 .smx 名")
    p_install.set_defaults(func=cmd_install)

    p_check = sub.add_parser("check", help="读取仓库 Require 并检测本地环境/插件是否已安装")
    p_check.add_argument("plugins", nargs="*", help="只检测指定插件；默认检测本地已安装且能对上仓库的插件")
    p_check.add_argument("--all-remote", action="store_true", help="检测选定仓库中的全部插件")
    p_check.add_argument("--missing-only", action="store_true", help="只显示缺失项")
    p_check.set_defaults(func=cmd_check)

    p_env = sub.add_parser("env", help="更新基础依赖环境（默认不升级已装的 MetaMod/SourceMod）")
    p_env.add_argument("--missing-only", action="store_true", help="只安装本地缺失的环境，不覆盖已有")
    p_env.add_argument(
        "--present-only",
        action="store_true",
        help="只更新本地已安装项，不补缺失（菜单 7）",
    )
    p_env.add_argument("--only", dest="env_only", nargs="+", metavar="KEY", help="只更新指定项，如 metamod sourcemod")
    p_env.add_argument("--with-core", action="store_true", help="连同已装的 MetaMod/SourceMod 一起更新到最新")
    p_env.add_argument("--overwrite-configs", dest="overwrite_sm_configs", action="store_true", help="SourceMod 覆盖 configs/data（先备份）")
    p_env.add_argument("--overwrite-plugins", dest="overwrite_sm_plugins", action="store_true", help="SourceMod 覆盖 plugins（先备份）")
    p_env.add_argument("--package", dest="drop_package", default="", help="指定 SourceMod/MetaMod Windows 包文件名，如 sourcemod-1.11.0-git6968-windows.zip")
    p_env.set_defaults(func=cmd_env)

    p_fixes = sub.add_parser("fixes", help="按教学区清单安装 Windows+L4D2 实用修复（不含反作弊）")
    p_fixes.add_argument("--remove", dest="remove_catalog", action="store_true", help="删除清单对应插件（保留配置）")
    p_fixes.set_defaults(func=cmd_fixes)

    p_8coop = sub.add_parser("8coop", help="按教学区清单安装 8 人战役模式插件（不含娱乐/不建议/划线）")
    p_8coop.add_argument("--remove", dest="remove_catalog", action="store_true", help="删除清单对应插件（保留配置）")
    p_8coop.set_defaults(func=cmd_8coop)

    return parser


def resolve_game_dir(override: Path | None) -> Path:
    if override:
        return normalize_game_dir(override)
    return default_game_dir()


def print_paths(game_dir: Path) -> None:
    print(f"游戏目录: {game_dir}")
    print(f"SourceMod: {sm_root(game_dir)}")
    print()


def make_cmd_args(
    game_dir: Path,
    repo: str = "all",
    *,
    show_all: bool = False,
    keyword: str = "",
    plugins: list[str] | None = None,
    names: list[str] | None = None,
    update_configs: bool = False,
    dry_run: bool = False,
    fetch_deps: bool = True,
    missing_only: bool = False,
    all_remote: bool = False,
    env_only: list[str] | None = None,
    with_core: bool = False,
    overwrite_sm_configs: bool = False,
    overwrite_sm_plugins: bool = False,
    remove_catalog: bool = False,
    drop_package: str = "",
    present_only: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        game_dir=game_dir,
        repo=repo,
        show_all=show_all,
        keyword=keyword,
        plugins=plugins or [],
        names=names or [],
        update_configs=update_configs,
        dry_run=dry_run,
        fetch_deps=fetch_deps,
        missing_only=missing_only,
        all_remote=all_remote,
        env_only=env_only,
        with_core=with_core,
        overwrite_sm_configs=overwrite_sm_configs,
        overwrite_sm_plugins=overwrite_sm_plugins,
        remove_catalog=remove_catalog,
        drop_package=drop_package,
        present_only=present_only,
    )


def open_config_file() -> None:
    ensure_config_file()
    if sys.platform == "win32":
        os.startfile(str(CONFIG_FILE))  # type: ignore[attr-defined]
    else:
        print(f"请编辑: {CONFIG_FILE}")


def ask_text(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _enable_vt_output() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


class _RawKeys:
    def __enter__(self):
        self._fd = None
        self._old = None
        if sys.platform != "win32" and sys.stdin.isatty():
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *_exc) -> None:
        if self._old is not None and self._fd is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def read(self) -> str:
        if sys.platform == "win32":
            import msvcrt

            ch = msvcrt.getwch()
            if ch in {"\x00", "\xe0"}:
                ch2 = msvcrt.getwch()
                return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(ch2, "")
            if ch in {"\r", "\n"}:
                return "enter"
            if ch == " ":
                return "space"
            if ch == "\x1b":
                return "esc"
            if ch == "\x03":
                raise KeyboardInterrupt
            return ch
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            nxt = sys.stdin.read(1)
            if nxt == "[":
                code = sys.stdin.read(1)
                return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(code, "")
            return "esc"
        if ch in {"\r", "\n"}:
            return "enter"
        if ch == " ":
            return "space"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch


def pick_multi_list(
    title: str,
    labels: list[str],
    *,
    initially: set[int] | None = None,
    empty_hint: str = "至少选择一项。",
    allow_empty: bool = False,
    single: bool = False,
) -> list[int] | None:
    if not labels:
        print("没有可选项。")
        return [] if allow_empty else None
    selected = set(initially or ())
    cursor = 0
    hint = ""
    offset = 0
    drawn = 0
    _enable_vt_output()
    sys.stdout.write("\n\033[?25l")
    sys.stdout.flush()

    def vis_count() -> int:
        try:
            rows = shutil.get_terminal_size().lines
        except OSError:
            rows = 25
        return max(8, rows - 8)

    def render() -> None:
        nonlocal drawn, offset
        vis = vis_count()
        if cursor < offset:
            offset = cursor
        if cursor >= offset + vis:
            offset = cursor - vis + 1
        try:
            cols = max(40, shutil.get_terminal_size().columns)
        except OSError:
            cols = 80
        if single:
            help_line = "方向键移动，回车进入，Esc 返回"
            status = " "
        else:
            help_line = "方向键移动，空格选择，回车确认，Esc 返回"
            status = hint or f"已选 {len(selected)}/{len(labels)}"
        lines = [
            title,
            help_line,
            "",
        ]
        end = min(len(labels), offset + vis)
        if offset > 0:
            lines.append("  ↑ 还有上面的项")
        for i in range(offset, end):
            mark = ">" if i == cursor else " "
            if single:
                prefix = f"{mark} {i + 1}. "
            else:
                box = "[*]" if i in selected else "[]"
                prefix = f"{mark} {i + 1}. {box} "
            body = labels[i]
            room = max(8, cols - 1 - len(prefix))
            if len(body) > room:
                body = body[: room - 1] + "…"
            row = prefix + body
            if i == cursor:
                row = f"\033[7m{row}\033[0m"
            lines.append(row)
        if end < len(labels):
            lines.append("  ↓ 还有下面的项")
        lines.append("")
        lines.append(status if single else (hint or f"已选 {len(selected)}/{len(labels)}"))
        buf: list[str] = []
        if drawn:
            buf.append(f"\033[{drawn}A")
        for line in lines:
            buf.append("\r" + line + "\033[K\r\n")
        extra = drawn - len(lines)
        if extra > 0:
            for _ in range(extra):
                buf.append("\r\033[K\r\n")
            buf.append(f"\033[{extra}A")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()
        drawn = len(lines)

    try:
        with _RawKeys() as keys:
            render()
            while True:
                action = keys.read()
                if action in {"up", "left"}:
                    cursor = (cursor - 1) % len(labels)
                    hint = ""
                    render()
                elif action in {"down", "right"}:
                    cursor = (cursor + 1) % len(labels)
                    hint = ""
                    render()
                elif action == "space":
                    if single:
                        return [cursor]
                    if cursor in selected:
                        selected.remove(cursor)
                    else:
                        selected.add(cursor)
                    hint = ""
                    render()
                elif action == "esc":
                    sys.stdout.write("\r\033[K\r\n")
                    sys.stdout.flush()
                    return None
                elif action == "enter":
                    if single:
                        return [cursor]
                    if not selected and not allow_empty:
                        hint = empty_hint
                        render()
                        continue
                    return sorted(selected)
    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def pick_enabled_repos(cfg: AppConfig) -> None:
    listed = cfg.listed_repos()
    if not listed:
        print("config.txt 中没有仓库行。")
        return
    labels = [f"{r.key}  ({r.name})" for r in listed]
    init = {i for i, r in enumerate(listed) if r.enabled}
    idx = pick_multi_list(
        "选择要启用的仓库（可多选，写入 config.txt）",
        labels,
        initially=init,
        empty_hint="至少启用一个仓库。",
    )
    if idx is None:
        print("已返回。")
        return
    keys = {listed[i].key for i in idx}
    save_enabled_repos(keys)
    get_config(reload=True)
    print("已启用: " + "、".join(listed[i].key for i in idx))


def pause_menu() -> None:
    print("\n按回车或 Esc 返回菜单...", end="", flush=True)
    if not (hasattr(sys.stdin, "isatty") and sys.stdin.isatty()):
        print()
        ask_text("")
        return
    try:
        with _RawKeys() as keys:
            while True:
                action = keys.read()
                if action in {"enter", "esc"}:
                    print()
                    return
    except Exception:
        print()
        ask_text("")


def ask_yes(prompt: str, default: bool = False) -> bool:
    title = re.sub(r"[？?]\s*[yY]/[nN]\s*:?\s*$", "？", (prompt or "").strip())
    title = title.rstrip(":： ") or "请选择"
    idx = pick_multi_list(title, ["是", "否"], single=True)
    if idx is None:
        raise InstallCancelled("已返回")
    return idx[0] == 0


def print_menu(game_dir: Path) -> None:
    sm = sm_root(game_dir)
    ok = sm.is_dir()
    print("=" * 52)
    print("  求生之路 2 插件同步菜单")
    print("=" * 52)
    print(f"  配置: {CONFIG_FILE}")
    if ok:
        tag = ""
    elif looks_like_l4d2_dir(game_dir):
        tag = "  [无 addons，可用 5-7 安装]"
    else:
        tag = "  [无效]"
    print(f"  游戏: {game_dir}{tag}")
    print()
    print("  --- 查询 ---")
    print("   1. 列出已安装、可同步")
    print("   2. 列出仓库全部插件")
    print()
    print("  --- 更新 / 安装 ---")
    print("   3. 更新已安装插件")
    print("   4. 安装指定插件")
    print()
    print("  --- 基础环境依赖 ---")
    print("   5. 更新 SourceMod（可选版本，可选覆盖配置）")
    print("   6. 更新 MetaMod（可选版本）")
    print("   7. 安装/更新基础环境")
    print("   8. 选择安装 Sourcemod 仓库插件")
    print()
    print("  --- 依赖检测 ---")
    print("   9. 检测 Require 并自动下载")
    print()
    print("  --- 实用修复 ---")
    print("  10. 选择安装")
    print("  11. 删除已安装项（保留配置）")
    print()
    print("  --- 8人战役 ---")
    print("  12. 选择安装")
    print("  13. 删除已安装项（保留配置）")
    print()
    print("  14. 选择启用仓库")
    print("  15. 打开 config.txt")
    print("   0. 退出")
    print("=" * 52)


def run_choice(choice: str, cfg: AppConfig, game_dir: Path, state: dict) -> str | None:
    repo = state["repo"]

    if choice == "1":
        print_paths(game_dir)
        cmd_list(make_cmd_args(game_dir, repo, show_all=False))
    elif choice == "2":
        print_paths(game_dir)
        cmd_list(make_cmd_args(game_dir, repo, show_all=True))
    elif choice == "3":
        overwrite = ask_yes("覆盖 configs/data？y/N: ", default=False)
        print_paths(game_dir)
        cmd_sync(make_cmd_args(game_dir, repo, update_configs=overwrite, fetch_deps=True))
    elif choice == "4":
        print_paths(game_dir)
        cmd_pick_specified_plugins(game_dir)
    elif choice == "5":
        overwrite = ask_yes("覆盖 configs/data 和 plugins？y/N: ", default=False)
        print_paths(game_dir)
        cmd_env(
            make_cmd_args(
                game_dir,
                repo,
                env_only=["sourcemod"],
                overwrite_sm_configs=overwrite,
                overwrite_sm_plugins=overwrite,
            )
        )
    elif choice == "6":
        print_paths(game_dir)
        cmd_env(make_cmd_args(game_dir, repo, env_only=["metamod"]))
    elif choice == "7":
        print_paths(game_dir)
        # 安装缺失 + 更新已装的基础环境；不含 SM/MM（用 5/6），也不含可选 SM 插件
        cmd_env(make_cmd_args(game_dir, repo, missing_only=False, present_only=False))
    elif choice == "8":
        print_paths(game_dir)
        cmd_pick_sourcemod_plugins(game_dir)
    elif choice == "9":
        idx = pick_multi_list(
            "选择 Require 检测范围",
            ["已安装插件", "仓库全部插件"],
            single=True,
        )
        if idx is None:
            return "continue"
        kwargs: dict = {"missing_only": True, "fetch_deps": True}
        if idx[0] == 1:
            kwargs["all_remote"] = True
        print_paths(game_dir)
        cmd_check(make_cmd_args(game_dir, repo, **kwargs))
    elif choice == "10":
        print_paths(game_dir)
        cmd_fixes(make_cmd_args(game_dir, repo, fetch_deps=True), pick=True)
    elif choice == "11":
        print_paths(game_dir)
        cmd_fixes(make_cmd_args(game_dir, repo, remove_catalog=True, fetch_deps=False))
    elif choice == "12":
        print_paths(game_dir)
        cmd_8coop(make_cmd_args(game_dir, repo, fetch_deps=True), pick=True)
    elif choice == "13":
        print_paths(game_dir)
        cmd_8coop(make_cmd_args(game_dir, repo, remove_catalog=True, fetch_deps=False))
    elif choice == "14":
        pick_enabled_repos(cfg)
        state["repo"] = "all"
        return "continue"
    elif choice == "15":
        print(f"保存后回到菜单会自动重新读取。\n{CONFIG_FILE}")
        open_config_file()
        return "continue"
    else:
        print("无效选项。")
        return "continue"
    return None


def run_menu() -> None:
    state = {"repo": "all"}
    while True:
        cfg = get_config(reload=True)
        game_dir = default_game_dir()
        if sys.platform == "win32":
            os.system("cls")
        print_menu(game_dir)
        if not sm_root(game_dir).is_dir():
            if looks_like_l4d2_dir(game_dir):
                print("尚未安装 addons。选 5 或 6 会自动创建并安装全部依赖。\n")
            else:
                print("游戏目录无效。请选「打开 config.txt」改 game_dir。\n")
        choice = ask_text("请输入数字: ")
        if choice in {"0", "q", "Q"}:
            print("已退出。")
            return
        if not choice:
            continue
        try:
            cont = run_choice(choice, cfg, game_dir, state)
            if cont == "continue":
                continue
        except InstallCancelled as e:
            print(str(e) or "已返回。")
            continue
        except SystemExit as e:
            if e.code not in (None, 0):
                print(e)
        except Exception as e:
            print(f"出错: {e}")
        pause_menu()


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ensure_config_file()
    parser = build_parser()
    args = parser.parse_args()
    if args.menu or not args.command:
        run_menu()
        return
    args.game_dir = resolve_game_dir(args.game_dir)
    sm = sm_root(args.game_dir)
    if not sm.is_dir() and args.command not in {"env"}:
        raise SystemExit(
            f"无效的游戏目录，找不到 {sm}\n"
            f"请把路径写进 {CONFIG_FILE}，或先用菜单 9-13 安装基础环境"
        )
    print_paths(args.game_dir)
    args.func(args)


if __name__ == "__main__":
    main()
