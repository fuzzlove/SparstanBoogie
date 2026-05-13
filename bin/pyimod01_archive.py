"""Minimal PyInstaller PYZ reader used by sparse.py bootstrap."""

import marshal
import os
import struct
import zlib
import _frozen_importlib

PYTHON_MAGIC_NUMBER = _frozen_importlib._bootstrap_external.MAGIC_NUMBER

PYZ_ITEM_MODULE = 0
PYZ_ITEM_PKG = 1
PYZ_ITEM_DATA = 2
PYZ_ITEM_NSPKG = 3


class ArchiveReadError(RuntimeError):
    pass


class ZlibArchiveReader:
    """Reader for PyInstaller's PYZ archive."""

    _PYZ_MAGIC_PATTERN = b"PYZ\x00"

    def __init__(self, filename, start_offset=0, check_pymagic=False):
        filename, parsed_offset = self._parse_offset_from_filename(filename)
        self._filename = filename
        self._start_offset = parsed_offset if parsed_offset else int(start_offset or 0)
        self.toc = {}

        try:
            with open(self._filename, "rb") as fp:
                fp.seek(self._start_offset, os.SEEK_SET)
                magic = fp.read(4)
                if magic != self._PYZ_MAGIC_PATTERN:
                    raise ArchiveReadError("Not a PYZ archive")

                py_magic = fp.read(4)
                if self._should_check_pymagic(check_pymagic) and py_magic != PYTHON_MAGIC_NUMBER:
                    raise ArchiveReadError("Python bytecode magic mismatch")

                toc_offset = struct.unpack("!i", fp.read(4))[0]
                fp.seek(self._start_offset + toc_offset, os.SEEK_SET)
                self.toc = marshal.load(fp)
        except Exception as exc:
            raise ArchiveReadError(str(exc)) from exc

    @staticmethod
    def _should_check_pymagic(check_pymagic):
        if isinstance(check_pymagic, tuple):
            # Some historical call sites used (magic, enabled).
            return bool(check_pymagic[1]) if len(check_pymagic) > 1 else bool(check_pymagic[0])
        return bool(check_pymagic)

    @staticmethod
    def _parse_offset_from_filename(filename):
        idx = filename.rfind("?")
        if idx == -1:
            return filename, 0
        try:
            return filename[:idx], int(filename[idx + 1 :])
        except ValueError:
            return filename, 0

    def extract(self, name, raw=False):
        entry = self.toc.get(name)
        if entry is None:
            return None

        if not isinstance(entry, (tuple, list)) or len(entry) < 2:
            raise ArchiveReadError(f"Invalid TOC entry for {name!r}")

        typecode = entry[0]
        entry_offset = entry[1]

        with open(self._filename, "rb") as fp:
            fp.seek(self._start_offset + entry_offset, os.SEEK_SET)

            if len(entry) >= 3:
                entry_length = entry[2]
                obj = fp.read(entry_length)
            else:
                obj = fp.read()

        try:
            obj = zlib.decompress(obj)
        except Exception as exc:
            raise ArchiveReadError(f"Failed to decompress {name!r}: {exc}") from exc

        if raw:
            return obj

        if typecode in (PYZ_ITEM_MODULE, PYZ_ITEM_PKG, PYZ_ITEM_NSPKG):
            try:
                return marshal.loads(obj)
            except Exception as exc:
                raise ArchiveReadError(f"Failed to unmarshal {name!r}: {exc}") from exc

        return obj
