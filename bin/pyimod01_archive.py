# Source Generated with Decompyle++
# File: pyimod01_archive.pyc (Python 3.12)

import os
import struct
import marshal
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
    """
    Reader for PyInstaller's PYZ (ZlibArchive) archive. The archive is used to store collected byte-compiled Python
    modules, as individually-compressed entries.
    """
    _PYZ_MAGIC_PATTERN = b'PYZ\x00'
    
    def __init__(self, filename, start_offset, check_pymagic = (None, False)):
        self._filename = filename
        self._start_offset = start_offset
        self.toc = { }
    # WARNING: Decompyle incomplete

    _parse_offset_from_filename = (lambda filename: offset = 0idx = filename.rfind('?')if idx == -1:
(filename, offset)try:
offset = int(filename[idx + 1:])filename = filename[:idx](filename, offset)except ValueError:
(filename, offset))()
    
    def extract(self, name, raw = (False,)):
        '''
        Extract data from entry with the given name.

        If the entry belongs to a module or a package, the data is loaded (unmarshaled) into code object. To retrieve
        raw data, set `raw` flag to True.
        '''
        entry = self.toc.get(name)
    # WARNING: Decompyle incomplete


