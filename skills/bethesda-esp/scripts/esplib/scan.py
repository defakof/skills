"""Fast header-only scanning of plugins for load-order and conflict analysis.

Walks the record/group headers of a plugin without creating Record objects,
collecting just what whole-load-order analysis needs (FormIDs, types, flags,
form versions, navmesh parent cells, EditorIDs of new records). Results are
cached on disk per file (path + size + mtime), so re-scanning a large load
order is close to instant.
"""

import hashlib
import os
import pickle
import struct
import zlib
from array import array

from .core import EspError, parse_subrecords, _find_sub, FLAG_COMPRESSED, FLAG_DELETED
from .loadorder import cache_dir

SCAN_VERSION = 5

_REC = struct.Struct('<4sIII')       # sig, size, flags, formid
_GRP = struct.Struct('<4sI4si')      # 'GRUP', size, label, type
_VER = struct.Struct('<H')

PLACED_TYPES = {'REFR', 'ACHR', 'PGRE', 'PMIS', 'PARW', 'PBAR', 'PBEA', 'PCON', 'PFLA', 'PHZD'}


class PluginScan:
    """Compact summary of one plugin file."""

    header_only = False                 # scan_header(): header fields only, no records

    def __init__(self):
        self.name = ''
        self.path = ''
        self.size = 0
        self.mtime = 0
        self.flags = 0
        self.masters = []
        self.hedr_version = 0.0
        self.hedr_records = 0
        self.next_object_id = 0
        self.author = ''
        self.description = ''
        self.form_version = 0           # TES4 record header form version
        self.formids = array('I')       # every record's file-local FormID
        self.sig_ids = array('H')       # index into self.sig_table
        self.rflags = array('I')
        self.sig_table = []
        self.old_form_records = 0       # records with form version < 44 (LE format)
        self.deleted_refs = []          # placed references flagged Deleted (UDR candidates)
        self.deleted_navmeshes = []     # NAVM flagged Deleted
        self.navm_cells = {}            # NAVM FormID -> parent CELL FormID (file-local)
        self.new_edids = {}             # object id -> EditorID, for records this plugin defines
        self.has_scripts = 0            # records with a VMAD subrecord (sampled on new records)
        self.crc = None                 # CRC-32 of the whole file (LOOT dirty/clean lookups)
        self.error = None

    # -- derived -----------------------------------------------------------
    @property
    def self_index(self):
        return len(self.masters)

    @property
    def is_esm(self):
        return bool(self.flags & 0x1)

    @property
    def is_esl_flag(self):
        return bool(self.flags & 0x200)

    @property
    def ext(self):
        return os.path.splitext(self.name)[1].lower()

    @property
    def is_light(self):
        """Loads in the FE light space (ESL flag, or .esl extension)."""
        return self.is_esl_flag or self.ext == '.esl'

    @property
    def is_master_like(self):
        """Loads in the master partition (ESM flag or .esm/.esl extension)."""
        return self.is_esm or self.ext in ('.esm', '.esl')

    @property
    def is_localized(self):
        return bool(self.flags & 0x80)

    def sig(self, i):
        return self.sig_table[self.sig_ids[i]]

    def records(self):
        """Yield (formid, sig, flags) for every record."""
        tbl = self.sig_table
        for fid, si, fl in zip(self.formids, self.sig_ids, self.rflags):
            yield fid, tbl[si], fl

    def counts(self):
        c = {}
        tbl = self.sig_table
        for si in self.sig_ids:
            s = tbl[si]
            c[s] = c.get(s, 0) + 1
        return c

    def new_ids(self):
        own = self.self_index
        return [fid & 0xFFFFFF for fid in self.formids if (fid >> 24) == own]

    def n_new(self):
        own = self.self_index
        return sum(1 for fid in self.formids if (fid >> 24) == own)

    def n_override(self):
        return len(self.formids) - self.n_new()

    def owner(self, fid):
        idx = fid >> 24
        if idx < len(self.masters):
            return self.masters[idx]
        if idx == len(self.masters):
            return self.name
        return None


def _edid_of(buf, dstart, size, flags):
    """EditorID of a record whose data starts at dstart (partial inflate)."""
    try:
        if flags & FLAG_COMPRESSED:
            head = zlib.decompressobj().decompress(buf[dstart + 4:dstart + size], 600)
        else:
            head = buf[dstart:dstart + min(size, 600)]
        if head[:4] != b'EDID':
            return None
        data = _find_sub(head, b'EDID')
        if data is None:
            return None
        return data.split(b'\0', 1)[0].decode('cp1252', errors='replace')
    except (zlib.error, struct.error):
        return None


def _has_vmad(buf, dstart, size, flags):
    try:
        if flags & FLAG_COMPRESSED:
            head = zlib.decompressobj().decompress(buf[dstart + 4:dstart + size], 2048)
        else:
            head = buf[dstart:dstart + min(size, 2048)]
        return b'VMAD' in head[:2048]
    except zlib.error:
        return False


def _read_header(s, buf, name):
    """Fill the header fields of s from buf (at least the TES4 record);
    returns the TES4 data size."""
    if len(buf) < 24 or buf[:4] != b'TES4':
        raise EspError(f'{name}: not a TES4-format plugin')
    _, hsize, hflags, _ = _REC.unpack_from(buf, 0)
    if 24 + hsize > len(buf):
        raise EspError(f'{name}: truncated file (the plugin header is cut off)')
    s.flags = hflags
    s.form_version = _VER.unpack_from(buf, 20)[0]
    for sub in parse_subrecords(bytes(buf[24:24 + hsize])):
        if sub.sig == 'HEDR' and len(sub.data) >= 12:
            s.hedr_version, s.hedr_records, s.next_object_id = struct.unpack_from('<fII', sub.data)
        elif sub.sig == 'MAST':
            s.masters.append(sub.data.split(b'\0', 1)[0].decode('cp1252', errors='replace'))
        elif sub.sig == 'CNAM':
            s.author = sub.data.split(b'\0', 1)[0].decode('cp1252', errors='replace')
        elif sub.sig == 'SNAM':
            s.description = sub.data.split(b'\0', 1)[0].decode('cp1252', errors='replace')
    return hsize


def scan_bytes(buf, name, path=''):
    s = PluginScan()
    s.name = name
    s.path = path
    s.size = len(buf)
    s.crc = zlib.crc32(buf) & 0xFFFFFFFF
    hsize = _read_header(s, buf, name)
    own = len(s.masters)
    sig_index = {}
    formids, sig_ids, rflags = s.formids, s.sig_ids, s.rflags
    pos = 24 + hsize
    end = len(buf)
    stack = []                 # (gtype, label_int, group_end)
    rec_unpack = _REC.unpack_from
    grp_unpack = _GRP.unpack_from
    ver_unpack = _VER.unpack_from
    while pos < end:
        while stack and pos >= stack[-1][2]:
            stack.pop()
        if pos + 24 > end:
            raise EspError(f'{name}: truncated header at offset {pos}')
        sig = buf[pos:pos + 4]
        if sig == b'GRUP':
            _, gsize, label, gtype = grp_unpack(buf, pos)
            if gsize < 24:
                raise EspError(f'{name}: bad group size at offset {pos}')
            if pos + gsize > end:
                raise EspError(f'{name}: truncated file (a record group at offset {pos} runs past the end)')
            stack.append((gtype, struct.unpack('<I', label)[0], pos + gsize))
            pos += 24
            continue
        _, size, flags, fid = rec_unpack(buf, pos)
        dstart = pos + 24
        if dstart + size > end:
            raise EspError(f'{name}: record at offset {pos} overruns the file')
        si = sig_index.get(sig)
        if si is None:
            si = sig_index[sig] = len(s.sig_table)
            s.sig_table.append(sig.decode('latin-1'))
        formids.append(fid)
        sig_ids.append(si)
        rflags.append(flags)
        if ver_unpack(buf, pos + 20)[0] < 44:
            s.old_form_records += 1
        ssig = s.sig_table[si]
        if flags & FLAG_DELETED:
            if ssig in PLACED_TYPES:
                s.deleted_refs.append(fid)
            elif ssig == 'NAVM':
                s.deleted_navmeshes.append(fid)
        if ssig == 'NAVM':
            for gtype, label, _gend in reversed(stack):
                if gtype in (6, 8, 9):
                    s.navm_cells[fid] = label
                    break
        if (fid >> 24) == own and size:
            e = _edid_of(buf, dstart, size, flags)
            if e:
                s.new_edids[fid & 0xFFFFFF] = e
            if ssig not in PLACED_TYPES and _has_vmad(buf, dstart, size, flags):
                s.has_scripts += 1
        pos = dstart + size
    return s


def scan_header(path):
    """Header-only scan (masters, flags, versions, author, description): reads
    the TES4 record and nothing else, so it costs one small read per plugin.
    Record lists stay empty and header_only is True. Never cached."""
    path = os.path.abspath(path)
    name = os.path.basename(path)
    if name.lower().endswith('.ghost'):
        name = name[:-6]
    s = PluginScan()
    s.name, s.path = name, path
    st = os.stat(path)
    s.size, s.mtime = st.st_size, st.st_mtime
    with open(path, 'rb') as f:
        head = f.read(24)
        if len(head) == 24 and head[:4] == b'TES4':
            head += f.read(_REC.unpack_from(head, 0)[1])
    _read_header(s, head, name)
    s.header_only = True
    return s


def scan_file(path, use_cache=True):
    """Scan a plugin file (cached by path/size/mtime)."""
    path = os.path.abspath(path)
    st = os.stat(path)
    name = os.path.basename(path)
    if name.lower().endswith('.ghost'):
        name = name[:-6]
    key = hashlib.sha1(f'{SCAN_VERSION}|{path}|{st.st_size}|{st.st_mtime_ns}'.encode()).hexdigest()
    cpath = os.path.join(cache_dir(), 'scan', key[:2], key + '.pkl')
    if use_cache and os.path.isfile(cpath):
        try:
            with open(cpath, 'rb') as f:
                s = pickle.load(f)
            if isinstance(s, PluginScan):
                s.name, s.path = name, path
                return s
        except Exception:  # noqa: BLE001 - corrupt cache entry: rescan
            pass
    with open(path, 'rb') as f:
        buf = f.read()
    s = scan_bytes(buf, name, path)
    s.mtime = st.st_mtime
    if use_cache and st.st_size > 8 * 1024:
        try:
            os.makedirs(os.path.dirname(cpath), exist_ok=True)
            tmp = cpath + '.tmp'
            with open(tmp, 'wb') as f:
                pickle.dump(s, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, cpath)
        except OSError:
            pass
    return s
