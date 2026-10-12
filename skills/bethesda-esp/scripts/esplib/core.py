"""Binary layer for Bethesda plugin files (.esp/.esm/.esl), Skyrim SE layout.

The reader keeps every unmodified record as the exact bytes it was read from
(compressed data stays compressed), so a load/save cycle reproduces the file
byte for byte. Only records you touch are re-encoded.

File layout (TES5/SSE, also Fallout 4 at this level):

    TES4 record (file header)
    GRUP (top group, label = record type)
        records ...
        GRUP (nested groups for CELL/WRLD/DIAL children)

Record header (24 bytes): type[4] dataSize u32 flags u32 formID u32
                          vcInfo u32 formVersion u16 vcInfo2 u16
Group header  (24 bytes): 'GRUP' groupSize u32 label[4] groupType i32
                          stamp u16 vcInfo u16 unknown u32
Subrecord     (6 bytes) : type[4] size u16 data  (XXXX u32 size prefix for >64K)
"""

import os
import struct
import zlib

REC_HDR = struct.Struct('<4sIIIIHH')
GRP_HDR = struct.Struct('<4sI4siHHI')
SUB_HDR = struct.Struct('<4sH')
HEADER_SIZE = 24

# Record header flags (meaning depends on record type for some bits)
FLAG_ESM = 0x00000001          # TES4 only
FLAG_DELETED = 0x00000020
FLAG_LOCALIZED = 0x00000080    # TES4 only
FLAG_ESL = 0x00000200          # TES4 only (light plugin)
FLAG_PERSISTENT = 0x00000400   # REFR/ACHR/... "persistent"
FLAG_INITIALLY_DISABLED = 0x00000800
FLAG_IGNORED = 0x00001000
FLAG_VISIBLE_WHEN_DISTANT = 0x00008000
FLAG_COMPRESSED = 0x00040000

RECORD_FLAG_NAMES = {
    0x00000001: 'ESM',
    0x00000020: 'Deleted',
    0x00000080: 'Localized',
    0x00000200: 'ESL',
    0x00000400: 'Persistent',
    0x00000800: 'InitiallyDisabled',
    0x00001000: 'Ignored',
    0x00008000: 'VisibleWhenDistant',
    0x00010000: 'RandomAnimStart/OffLimits',
    0x00020000: 'Dangerous/OffLimits',
    0x00040000: 'Compressed',
    0x00080000: 'CantWait',
    0x00100000: 'IgnoreObjectInteraction',
    0x00800000: 'IsMarker',
    0x02000000: 'Obstacle/NoAIAcquire',
    0x04000000: 'NavMeshFilter',
    0x08000000: 'NavMeshBoundingBox',
    0x10000000: 'MustExitToTalk/ReflectedByAutoWater',
    0x20000000: 'ChildCanUse/DontHavokSettle',
    0x40000000: 'NavMeshGround/NoRespawn',
    0x80000000: 'MultiBound',
}

GROUP_TYPE_NAMES = {
    0: 'Top',
    1: 'World Children',
    2: 'Interior Cell Block',
    3: 'Interior Cell Sub-Block',
    4: 'Exterior Cell Block',
    5: 'Exterior Cell Sub-Block',
    6: 'Cell Children',
    7: 'Topic Children',
    8: 'Cell Persistent Children',
    9: 'Cell Temporary Children',
    10: 'Cell Visible Distant Children',
}

# Order in which the Creation Kit / xEdit write top-level groups for Skyrim SE.
TOP_GROUP_ORDER = (
    'GMST KYWD LCRT AACT TXST GLOB CLAS FACT HDPT EYES RACE SOUN ASPC MGEF LTEX '
    'ENCH SPEL SCRL ACTI TACT ARMO BOOK CONT DOOR INGR LIGH MISC APPA STAT SCOL '
    'MSTT PWAT GRAS TREE CLDC FLOR FURN WEAP AMMO NPC_ LVLN KEYM ALCH IDLM COBJ '
    'PROJ HAZD SLGM LVLI WTHR CLMT SPGD RFCT REGN NAVI CELL WRLD DIAL QUST IDLE '
    'PACK CSTY LSCR LVSP ANIO WATR EFSH EXPL DEBR IMGS IMAD FLST PERK BPTD ADDN '
    'AVIF CAMS CPTH VTYP MATT IPCT IPDS ARMA ECZN LCTN MESG RGDL DOBJ LGTM MUSC '
    'FSTP FSTS SMBN SMQN SMEN DLBR MUST DLVW WOOP SHOU EQUP RELA SCEN ASTP OTFT '
    'ARTO MATO MOVT SNDR DUAL SNCT SOPM COLL CLFM REVB LENS VOLI'
).split()

# Record types that live inside nested groups rather than their own top group.
CELL_CHILD_TYPES = {'REFR', 'ACHR', 'PGRE', 'PMIS', 'PARW', 'PBAR', 'PBEA',
                    'PCON', 'PFLA', 'PHZD', 'NAVM', 'LAND'}
TOPIC_CHILD_TYPES = {'INFO'}


class EspError(Exception):
    pass


class FormKey(tuple):
    """Record identity that does not depend on a plugin's master list:
    (object ID, name of the plugin that defines the record).

    FormIDs in a plugin file are file-local - the top byte indexes that
    plugin's own master list - so the same record is 0x01012EB7 in one patch
    and 0x05012EB7 in another. FormKeys compare equal across plugins (plugin
    names case-insensitively) and work as dict/set keys. They compare equal
    only to other FormKeys: wrap a plain (id, name) pair with FormKey(*pair).
    str() gives the CLI notation '012EB7:Skyrim.esm'; FormKey.parse() reads it back."""

    __slots__ = ()

    def __new__(cls, object_id, plugin):
        return tuple.__new__(cls, (int(object_id) & 0xFFFFFF, str(plugin)))

    @classmethod
    def parse(cls, text):
        """'012EB7:Skyrim.esm' or 'Skyrim.esm:012EB7'."""
        s = str(text).strip()
        a, sep, b = s.partition(':')
        for oid, name in ((a.strip(), b), (b.strip(), a)):
            if sep and oid and '.' in name and all(c in '0123456789abcdefABCDEF' for c in oid):
                if int(oid, 16) > 0xFFFFFF:
                    raise EspError(f'object ID too large in {s!r}: a FormKey has 6 hex digits (012EB7:Skyrim.esm), '
                                   'without the load-order byte')
                return cls(int(oid, 16), name.strip())
        raise EspError(f'not a FormKey: {s!r} (expected 012EB7:Skyrim.esm)')

    @property
    def object_id(self):
        return self[0]

    @property
    def plugin(self):
        return self[1]

    def _key(self):
        return self[0], self[1].lower()

    def __eq__(self, other):
        if isinstance(other, FormKey):
            return self._key() == other._key()
        return False if isinstance(other, tuple) else NotImplemented

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    def __lt__(self, other):
        return self._key() < other._key() if isinstance(other, FormKey) else NotImplemented

    def __le__(self, other):
        return self._key() <= other._key() if isinstance(other, FormKey) else NotImplemented

    def __gt__(self, other):
        return self._key() > other._key() if isinstance(other, FormKey) else NotImplemented

    def __ge__(self, other):
        return self._key() >= other._key() if isinstance(other, FormKey) else NotImplemented

    def __hash__(self):
        return hash(self._key())

    def __getnewargs__(self):          # pickle / copy
        return (self[0], self[1])

    def __str__(self):
        return f'{self[0]:06X}:{self[1]}'

    def __repr__(self):
        return f"FormKey('{self}')"


def sig_str(b):
    return b.decode('latin-1')


def sig_bytes(s):
    b = s.encode('latin-1') if isinstance(s, str) else bytes(s)
    if len(b) != 4:
        raise EspError(f'record/subrecord type must be 4 characters: {s!r}')
    return b


# ---------------------------------------------------------------------------
# Subrecords
# ---------------------------------------------------------------------------

class Subrecord:
    __slots__ = ('sig', 'data')

    def __init__(self, sig, data=b''):
        self.sig = sig if isinstance(sig, str) else sig_str(sig)
        self.data = bytes(data)

    def __repr__(self):
        return f'<{self.sig} {len(self.data)}b>'

    def copy(self):
        return Subrecord(self.sig, self.data)


def parse_subrecords(data):
    subs = []
    pos = 0
    end = len(data)
    pending_size = None
    while pos < end:
        if pos + 6 > end:
            raise EspError(f'truncated subrecord header at offset {pos}')
        sig, size = SUB_HDR.unpack_from(data, pos)
        pos += 6
        if sig == b'XXXX':
            if pos + 4 > end:
                raise EspError(f'truncated XXXX size at offset {pos}')
            pending_size = struct.unpack_from('<I', data, pos)[0]
            pos += size
            continue
        if pending_size is not None:
            size = pending_size
            pending_size = None
        if pos + size > end:
            raise EspError(f'subrecord {sig_str(sig)} overruns record data (size {size} at {pos})')
        subs.append(Subrecord(sig_str(sig), data[pos:pos + size]))
        pos += size
    return subs


def _find_sub(data, sig):
    """Return the data of the first subrecord `sig` without building objects."""
    pos, end, pending = 0, len(data), None
    while pos + 6 <= end:
        s, size = SUB_HDR.unpack_from(data, pos)
        pos += 6
        if s == b'XXXX':
            pending = struct.unpack_from('<I', data, pos)[0]
            pos += size
            continue
        if pending is not None:
            size, pending = pending, None
        if s == sig:
            return bytes(data[pos:pos + size])
        pos += size
    return None


def encode_subrecords(subs):
    out = bytearray()
    for s in subs:
        n = len(s.data)
        if n > 0xFFFF:
            out += SUB_HDR.pack(b'XXXX', 4) + struct.pack('<I', n)
            out += SUB_HDR.pack(sig_bytes(s.sig), 0)
        else:
            out += SUB_HDR.pack(sig_bytes(s.sig), n)
        out += s.data
    return bytes(out)


# ---------------------------------------------------------------------------
# Records and groups
# ---------------------------------------------------------------------------

class Record:
    """A major record. Subrecords are parsed lazily on first access."""

    __slots__ = ('sig', 'flags', 'formid', 'vc1', 'version', 'vc2',
                 '_raw', '_subs', '_edid', 'parent', 'plugin')

    def __init__(self, sig, formid=0, flags=0, subrecords=None, version=44, vc1=0, vc2=0):
        self.sig = sig if isinstance(sig, str) else sig_str(sig)
        self.formid = formid
        self.flags = flags
        self.vc1 = vc1
        self.version = version
        self.vc2 = vc2
        self._raw = None          # stored data bytes as in file (maybe compressed)
        self._subs = list(subrecords) if subrecords is not None else []
        self._edid = False        # cache; False = not computed
        self.parent = None        # Group
        self.plugin = None

    # -- lazy access -------------------------------------------------------
    @property
    def compressed(self):
        return bool(self.flags & FLAG_COMPRESSED)

    def data(self):
        """Uncompressed subrecord data bytes."""
        if self._subs is None:
            raw = bytes(self._raw)
            if self.compressed:
                if len(raw) < 4:
                    raise EspError(f'{self.label()}: compressed record too short')
                expected = struct.unpack_from('<I', raw, 0)[0]
                try:
                    out = zlib.decompress(raw[4:])
                except zlib.error as e:
                    raise EspError(f'{self.label()}: zlib error: {e}')
                if len(out) != expected:
                    raise EspError(f'{self.label()}: decompressed size {len(out)} != {expected}')
                return out
            return raw
        return encode_subrecords(self._subs)

    @property
    def subrecords(self):
        if self._subs is None:
            try:
                self._subs = parse_subrecords(self.data())
            except EspError as e:
                raise EspError(f'{self.label()}: {e}')
            # keep _raw so an untouched record can still be written verbatim;
            # touched() drops it.
        return self._subs

    def touched(self):
        """Mark as modified: it will be re-encoded on save."""
        if self._subs is None:
            self.subrecords  # noqa: B018 - force parse
        self._raw = None
        self._edid = False
        if self.sig == 'TES4' and self.plugin is not None:
            self.plugin._mcache = None          # the master list may have changed

    @property
    def is_modified(self):
        if self._raw is None:
            return True
        if self._subs is None:
            return False
        return encode_subrecords(self._subs) != self.data_from_raw()

    def data_from_raw(self):
        subs, self._subs = self._subs, None
        try:
            return self.data()
        finally:
            self._subs = subs

    # -- convenience -------------------------------------------------------
    def get(self, sig, index=0):
        n = 0
        for s in self.subrecords:
            if s.sig == sig:
                if n == index:
                    return s
                n += 1
        return None

    def get_all(self, sig):
        return [s for s in self.subrecords if s.sig == sig]

    @property
    def edid(self):
        if self._edid is not False:
            return self._edid
        val = None
        if self.sig != 'TES4':
            try:
                if self._subs is not None:
                    s = self.get('EDID')
                    data = s.data if s is not None else None
                elif self.compressed:
                    # EDID is (almost always) first: inflate only the head
                    raw = bytes(self._raw)
                    head = zlib.decompressobj().decompress(raw[4:], 600)
                    data = _find_sub(head, b'EDID') if head[:4] == b'EDID' else None
                    if data is None:
                        data = _find_sub(self.data(), b'EDID')
                else:
                    data = _find_sub(self.data(), b'EDID')
            except (EspError, struct.error):
                data = None
            if data is not None:
                enc = self.plugin.encoding if self.plugin is not None else 'cp1252'
                val = data.split(b'\0', 1)[0].decode(enc, errors='replace')
        self._edid = val
        return val

    @property
    def is_deleted(self):
        return bool(self.flags & FLAG_DELETED)

    # -- identity across plugins -------------------------------------------
    @property
    def object_id(self):
        """The FormID without its master-index byte (formid & 0xFFFFFF)."""
        return self.formid & 0xFFFFFF

    local_id = object_id

    def _owning_plugin(self, plugin):
        plugin = plugin if plugin is not None else self.plugin
        if plugin is None:
            raise EspError(f'{self.label()} belongs to no plugin: pass the plugin it was read from')
        return plugin

    def master_name(self, plugin=None):
        """Name of the plugin that defines this record: a master of the plugin
        it was read from (an override), or that plugin itself (a new record).
        None when the FormID's master index is past the master list."""
        return self._owning_plugin(plugin).formid_owner(self.formid)

    @property
    def formkey(self):
        """FormKey (object ID, defining plugin): equal for the same record in
        any plugin, whatever the master lists. None for an invalid master index."""
        return self._owning_plugin(None).formkey(self.formid)

    @property
    def is_override(self):
        """True when the record comes from a master (it overrides it)."""
        return (self.formid >> 24) < len(self._owning_plugin(None)._master_list())

    def label(self):
        e = None
        try:
            e = self.edid
        except Exception:
            pass
        return f'[{self.sig}:{self.formid:08X}]' + (f' {e}' if e else '')

    def __repr__(self):
        return f'<Record {self.label()}>'

    def copy(self):
        r = Record(self.sig, self.formid, self.flags, None, self.version, self.vc1, self.vc2)
        r.plugin = self.plugin
        if self._raw is not None and self._subs is None:
            r._raw = self._raw
            r._subs = None
        else:
            r._subs = [s.copy() for s in self.subrecords]
            r._raw = self._raw
        return r

    def encode(self):
        if self._raw is not None and self._subs is not None and self.is_modified:
            self._raw = None
        if self._raw is not None:
            raw = bytes(self._raw)
        else:
            data = encode_subrecords(self._subs)
            if self.compressed:
                raw = struct.pack('<I', len(data)) + zlib.compress(data, 6)
            else:
                raw = data
        return REC_HDR.pack(sig_bytes(self.sig), len(raw), self.flags, self.formid,
                            self.vc1, self.version, self.vc2) + raw


class Group:
    __slots__ = ('label', 'gtype', 'stamp', 'vc', 'unknown', 'children', 'parent')

    def __init__(self, label, gtype=0, stamp=0, vc=0, unknown=0):
        if isinstance(label, str):
            label = sig_bytes(label)
        elif isinstance(label, int):
            label = struct.pack('<I', label & 0xFFFFFFFF)
        self.label = bytes(label)
        self.gtype = gtype
        self.stamp = stamp
        self.vc = vc
        self.unknown = unknown
        self.children = []
        self.parent = None

    # label interpretations
    @property
    def label_sig(self):
        return sig_str(self.label)

    @property
    def label_formid(self):
        return struct.unpack('<I', self.label)[0]

    @property
    def label_int(self):
        return struct.unpack('<i', self.label)[0]

    @property
    def label_yx(self):
        return struct.unpack('<hh', self.label)

    def describe(self):
        t = self.gtype
        if t == 0:
            lab = self.label_sig
        elif t in (1, 6, 7, 8, 9, 10):
            lab = f'{self.label_formid:08X}'
        elif t in (2, 3):
            lab = str(self.label_int)
        elif t in (4, 5):
            y, x = self.label_yx
            lab = f'X={x} Y={y}'
        else:
            lab = self.label.hex()
        return f'GRUP {GROUP_TYPE_NAMES.get(t, t)} [{lab}]'

    def __repr__(self):
        return f'<{self.describe()} {len(self.children)} children>'

    def add(self, child, index=None):
        child.parent = self
        if index is None:
            self.children.append(child)
        else:
            self.children.insert(index, child)
        return child

    def records(self):
        """All records in this group, recursively."""
        stack = [iter(self.children)]
        while stack:
            for c in stack[-1]:
                if isinstance(c, Group):
                    stack.append(iter(c.children))
                    break
                yield c
            else:
                stack.pop()

    def count(self):
        n_rec = n_grp = 0
        for c in self.children:
            if isinstance(c, Group):
                r, g = c.count()
                n_rec += r
                n_grp += g + 1
            else:
                n_rec += 1
        return n_rec, n_grp


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _read_items(buf, start, end, parent, plugin):
    """Iteratively parse records/groups in buf[start:end] into parent group."""
    stack = [(parent, end)]
    pos = start
    mv = memoryview(buf)
    while stack:
        grp, gend = stack[-1]
        if pos >= gend:
            if pos > gend:
                raise EspError(f'group {grp.describe()} overruns its declared size')
            stack.pop()
            continue
        if pos + HEADER_SIZE > len(buf):
            raise EspError(f'truncated header at offset {pos}')
        sig = buf[pos:pos + 4]
        if sig == b'GRUP':
            _, size, label, gtype, stamp, vc, unk = GRP_HDR.unpack_from(buf, pos)
            if size < HEADER_SIZE:
                raise EspError(f'bad group size {size} at offset {pos}')
            g = Group(label, gtype, stamp, vc, unk)
            grp.add(g)
            stack.append((g, pos + size))
            pos += HEADER_SIZE
        else:
            _, size, flags, formid, vc1, version, vc2 = REC_HDR.unpack_from(buf, pos)
            dstart = pos + HEADER_SIZE
            if dstart + size > gend:
                raise EspError(f'record {sig_str(sig)}:{formid:08X} at offset {pos} overruns its group')
            r = Record(sig_str(sig), formid, flags, None, version, vc1, vc2)
            r._raw = mv[dstart:dstart + size]
            r._subs = None
            r.plugin = plugin
            grp.add(r)
            pos = dstart + size


class Plugin:
    """An in-memory plugin. Plugin.load(path) reads a file, Plugin.load_header(path)
    only its header (masters, flags, versions), Plugin.new(name) starts an empty one.
    Plugin(name) itself reads nothing."""

    def __init__(self, name='New.esp'):
        name = os.fspath(name)
        if '/' in name or '\\' in name or os.path.basename(name) != name:
            raise ValueError(f'Plugin() takes a plugin name, not a path ({name!r}): use Plugin.load(path) to '
                             'read a plugin file, Plugin.load_header(path) for just its masters and flags, '
                             'or Plugin.new(name) for a new plugin')
        self.path = None
        self.name = name
        self._header = None
        self.header_only = False          # True after load_header(): no records were read
        self.root = Group(b'\0\0\0\0', -1)   # pseudo group holding top groups
        self.encoding = os.environ.get('ESP_ENCODING', 'cp1252')
        self._index = None
        self._edid_index = None
        self._mcache = None
        self.strings = None    # StringTables when localized and found
        self.structure_changed = True   # False after load; set by add/remove

    @property
    def header(self):
        """The TES4 header record."""
        h = self._header
        if h is None:
            raise EspError(f'{self.name}: this Plugin has no header - Plugin(name) does not read files. Use '
                           'Plugin.load(path) to read a plugin, Plugin.load_header(path) for its header only, '
                           'or Plugin.new(name) to start a new one')
        return h

    @header.setter
    def header(self, rec):
        self._header = rec
        self._mcache = None

    def _no_records(self, what):
        self.header              # noqa: B018 - raises for Plugin(name) without a header
        if self.header_only:
            raise EspError(f'{self.name} was loaded with Plugin.load_header(), which reads only the header: '
                           f'use Plugin.load(path) to {what}')

    # -- construction --------------------------------------------------------
    @classmethod
    def load(cls, path, encoding=None):
        with open(path, 'rb') as f:
            buf = f.read()
        p = cls(os.path.basename(path))
        p.path = os.path.abspath(path)
        if encoding:
            p.encoding = encoding
        if len(buf) < HEADER_SIZE or buf[:4] != b'TES4':
            raise EspError(f'{path}: not a TES4-format plugin (Skyrim/Fallout 4 family)')
        _, size, flags, formid, vc1, version, vc2 = REC_HDR.unpack_from(buf, 0)
        hdr = Record('TES4', formid, flags, None, version, vc1, vc2)
        hdr._raw = memoryview(buf)[HEADER_SIZE:HEADER_SIZE + size]
        hdr._subs = None
        hdr.plugin = p
        p.header = hdr
        hedr = hdr.get('HEDR')
        if hedr is None or len(hedr.data) < 12:
            raise EspError(f'{path}: TES4 header has no HEDR (Oblivion/Morrowind plugins are not supported)')
        _read_items(buf, HEADER_SIZE + size, len(buf), p.root, p)
        p.structure_changed = False
        return p

    @classmethod
    def load_header(cls, path, encoding=None):
        """Read only the plugin header (TES4 record): masters, ESM/ESL/localized
        flags, header version, next object ID, author, description. Reads a few
        hundred bytes instead of the whole file, so checking the masters and flags
        of a 1000-plugin load order takes well under a second. The result cannot
        list records or be saved; use Plugin.load(path) for that."""
        with open(path, 'rb') as f:
            head = f.read(HEADER_SIZE)
            if len(head) < HEADER_SIZE or head[:4] != b'TES4':
                raise EspError(f'{path}: not a TES4-format plugin (Skyrim/Fallout 4 family)')
            _, size, flags, formid, vc1, version, vc2 = REC_HDR.unpack_from(head, 0)
            data = f.read(size)
        if len(data) < size:
            raise EspError(f'{path}: truncated file (the plugin header is cut off)')
        p = cls(os.path.basename(path))
        p.path = os.path.abspath(path)
        if encoding:
            p.encoding = encoding
        hdr = Record('TES4', formid, flags, None, version, vc1, vc2)
        hdr._raw = data
        hdr._subs = None
        hdr.plugin = p
        p.header = hdr
        hedr = hdr.get('HEDR')
        if hedr is None or len(hedr.data) < 12:
            raise EspError(f'{path}: TES4 header has no HEDR (Oblivion/Morrowind plugins are not supported)')
        p.header_only = True
        p.structure_changed = False
        return p

    @classmethod
    def new(cls, name, masters=(), esm=False, esl=False, author='', description='',
            hedr_version=1.7, next_object_id=0x800):
        p = cls(os.path.basename(name))
        flags = (FLAG_ESM if esm else 0) | (FLAG_ESL if esl else 0)
        subs = [Subrecord('HEDR', struct.pack('<fII', hedr_version, 0, next_object_id)),
                Subrecord('CNAM', (author or 'DEFAULT').encode(p.encoding) + b'\0')]
        if description:
            subs.append(Subrecord('SNAM', description.encode(p.encoding) + b'\0'))
        for m in masters:
            subs.append(Subrecord('MAST', m.encode(p.encoding) + b'\0'))
            subs.append(Subrecord('DATA', b'\0' * 8))
        subs.append(Subrecord('INTV', struct.pack('<I', 1)))
        hdr = Record('TES4', 0, flags, subs, version=44)
        hdr.plugin = p
        p.header = hdr
        return p

    # -- header helpers ------------------------------------------------------
    @property
    def masters(self):
        return [s.data.split(b'\0', 1)[0].decode(self.encoding, errors='replace')
                for s in self.header.subrecords if s.sig == 'MAST']

    def _master_list(self):
        """self.masters, cached for per-record FormID lookups (a plugin with 250
        masters takes ~0.2 ms per .masters call). Reset by add_master(),
        set_masters() and invalidate(); call invalidate() after editing MAST
        subrecords by hand."""
        subs = self.header.subrecords
        c = self._mcache
        if c is None or c[0] is not subs or c[1] != len(subs):
            c = self._mcache = (subs, len(subs), self.masters)
        return c[2]

    @property
    def self_index(self):
        return len(self.masters)

    def _hedr(self):
        h = self.header.get('HEDR')
        return struct.unpack_from('<fII', h.data, 0)

    @property
    def hedr_version(self):
        return self._hedr()[0]

    @property
    def next_object_id(self):
        return self._hedr()[2]

    def set_hedr(self, version=None, num_records=None, next_object_id=None):
        h = self.header.get('HEDR')
        v, n, nx = struct.unpack_from('<fII', h.data, 0)
        if version is not None:
            v = version
        if num_records is not None:
            n = num_records
        if next_object_id is not None:
            nx = next_object_id
        new = struct.pack('<fII', v, n, nx) + h.data[12:]
        if new != h.data:
            h.data = new
            self.header.touched()

    def header_string(self, sig):
        s = self.header.get(sig)
        if s is None:
            return ''
        return s.data.split(b'\0', 1)[0].decode(self.encoding, errors='replace')

    def set_header_string(self, sig, value):
        subs = self.header.subrecords
        data = value.encode(self.encoding) + b'\0'
        for s in subs:
            if s.sig == sig:
                s.data = data
                break
        else:
            # CNAM after HEDR, SNAM after CNAM
            idx = 1
            for i, s in enumerate(subs):
                if s.sig in ('HEDR', 'CNAM', 'OFST', 'DELE'):
                    idx = i + 1
            subs.insert(idx, Subrecord(sig, data))
        self.header.touched()

    @property
    def is_esm(self):
        return bool(self.header.flags & FLAG_ESM)

    @property
    def is_esl(self):
        """The ESL flag is set (see is_light for what the game does)."""
        return bool(self.header.flags & FLAG_ESL)

    @property
    def is_light(self):
        """Loads as a light plugin (FE slot): ESL flag or .esl extension."""
        return self.is_esl or self.name.lower().endswith('.esl')

    @property
    def is_master_like(self):
        """Loads in the master block: ESM flag, or .esm/.esl extension."""
        return self.is_esm or self.name.lower().endswith(('.esm', '.esl'))

    @property
    def is_localized(self):
        return bool(self.header.flags & FLAG_LOCALIZED)

    def add_master(self, name):
        """Append a master. Returns its index. Does NOT remap existing FormIDs;
        use ops.add_master() for the safe version."""
        if name.lower() in (m.lower() for m in self.masters):
            return [m.lower() for m in self.masters].index(name.lower())
        subs = self.header.subrecords
        idx = None
        for i, s in enumerate(subs):
            if s.sig in ('MAST', 'DATA') and (s.sig == 'MAST' or (i and subs[i - 1].sig == 'MAST')):
                idx = i + 1
        if idx is None:
            idx = 1
            for i, s in enumerate(subs):
                if s.sig in ('HEDR', 'OFST', 'DELE', 'CNAM', 'SNAM'):
                    idx = i + 1
        subs[idx:idx] = [Subrecord('MAST', name.encode(self.encoding) + b'\0'),
                         Subrecord('DATA', b'\0' * 8)]
        self.header.touched()
        self._mcache = None
        return len(self.masters) - 1

    def set_masters(self, names):
        """Replace the master list verbatim (no FormID remapping)."""
        subs = [s for s in self.header.subrecords if s.sig != 'MAST' and not
                (s.sig == 'DATA')]
        idx = 1
        for i, s in enumerate(subs):
            if s.sig in ('HEDR', 'OFST', 'DELE', 'CNAM', 'SNAM'):
                idx = i + 1
        block = []
        for n in names:
            block += [Subrecord('MAST', n.encode(self.encoding) + b'\0'), Subrecord('DATA', b'\0' * 8)]
        subs[idx:idx] = block
        self.header._subs = subs
        self.header.touched()
        self._mcache = None

    # -- FormID helpers -------------------------------------------------------
    def formid_owner(self, formid):
        """Name of the plugin that defines this (file-local) FormID."""
        idx = formid >> 24
        ms = self._master_list()
        if idx < len(ms):
            return ms[idx]
        if idx == len(ms):
            return self.name
        return None

    def is_override(self, rec):
        return (rec.formid >> 24) < len(self._master_list())

    def formkey(self, formid):
        """FormKey (object ID, defining plugin) of a FormID as stored in this
        plugin - a record's .formid or a FormID value inside a field. Equal for
        the same record in any plugin. None for 0 or an invalid master index."""
        if not formid:
            return None
        owner = self.formid_owner(formid)
        return FormKey(formid, owner) if owner is not None else None

    def local_formid(self, key):
        """The FormID this plugin uses for a record: key is a FormKey, an
        (object ID, plugin name) pair or text like '012EB7:Skyrim.esm'.
        None when the defining plugin is neither this one nor one of its masters."""
        if isinstance(key, str):
            key = FormKey.parse(key)
        objid, owner = key
        if not 0 <= objid <= 0xFFFFFF:
            raise EspError(f'object ID {objid:#x} is out of range: a FormKey has a 6-digit object ID')
        owner = owner.lower()
        if owner == self.name.lower():
            return (len(self._master_list()) << 24) | (objid & 0xFFFFFF)
        for i, m in enumerate(self._master_list()):
            if m.lower() == owner:
                return (i << 24) | (objid & 0xFFFFFF)
        return None

    # -- traversal -------------------------------------------------------------
    @property
    def groups(self):
        return self.root.children

    def records(self, types=None):
        """Iterate all major records (not TES4), optionally filtered by type(s)."""
        if isinstance(types, str):
            types = {types}
        elif types is not None:
            types = set(types)
        self._no_records('list its records')
        for r in self.root.records():
            if types is None or r.sig in types:
                yield r

    def top_group(self, sig, create=False):
        sb = sig_bytes(sig)
        for g in self.root.children:
            if isinstance(g, Group) and g.gtype == 0 and g.label == sb:
                return g
        if not create:
            return None
        self.structure_changed = True
        g = Group(sb, 0)
        order = {s: i for i, s in enumerate(TOP_GROUP_ORDER)}
        my = order.get(sig, len(order))
        pos = len(self.root.children)
        for i, c in enumerate(self.root.children):
            if order.get(c.label_sig, len(order)) > my:
                pos = i
                break
        self.root.add(g, pos)
        return g

    def index(self):
        if self._index is None:
            idx = {}
            for r in self.records():
                idx.setdefault(r.formid, r)
            self._index = idx
        return self._index

    def edid_index(self):
        if self._edid_index is None:
            idx = {}
            for r in self.records():
                e = r.edid
                if e:
                    idx.setdefault(e.lower(), r)
            self._edid_index = idx
        return self._edid_index

    def invalidate(self, structure=True):
        self._index = None
        self._edid_index = None
        self._mcache = None
        if structure:
            self.structure_changed = True

    def find(self, formid):
        """Record by FormID as stored in this plugin, or by FormKey (a record
        from another plugin: plugin.find(other_record.formkey))."""
        self._no_records('look up its records')
        if isinstance(formid, (tuple, str)):
            formid = self.local_formid(formid)
            if formid is None:
                return None
        return self.index().get(formid)

    def find_edid(self, edid):
        self._no_records('look up its records')
        return self.edid_index().get(edid.lower())

    # -- structure edits ---------------------------------------------------
    def remove(self, rec, prune=True):
        """Remove a record (plus its child group for CELL/WRLD/DIAL)."""
        g = rec.parent
        if g is None:
            raise EspError('record is not attached to a group')
        i = g.children.index(rec)
        del g.children[i]
        child = child_group_of(rec, g, i)
        if child is not None:
            g.children.remove(child)
        rec.parent = None
        if prune:
            prune_empty(g)
        self.invalidate()

    # -- writing -----------------------------------------------------------
    def update_header_counts(self):
        n_rec, n_grp = self.root.count()
        self.set_hedr(num_records=n_rec + n_grp)

    def to_bytes(self):
        self._no_records('write it (saving a header-only plugin would drop every record)')
        if self.structure_changed:
            self.update_header_counts()
        out = bytearray()
        out += self.header.encode()
        for g in self.root.children:
            _write(out, g)
        return bytes(out)

    def save(self, path=None, backup=True):
        path = path or self.path
        if path is None:
            raise EspError('no output path')
        data = self.to_bytes()
        if backup and os.path.exists(path):
            bak = path + '.bak'
            i = 1
            while os.path.exists(bak):
                bak = f'{path}.bak{i}'
                i += 1
            os.replace(path, bak)
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
        return path


def _write(out, node):
    if isinstance(node, Record):
        out += node.encode()
        return
    start = len(out)
    out += b'\0' * HEADER_SIZE
    for c in node.children:
        _write(out, c)
    size = len(out) - start
    GRP_HDR.pack_into(out, start, b'GRUP', size, node.label, node.gtype,
                      node.stamp, node.vc, node.unknown)


def child_group_of(rec, group=None, index=None):
    """The children GRUP that follows a CELL/WRLD/DIAL record, if any."""
    g = group or rec.parent
    if g is None:
        return None
    if index is None:
        try:
            index = g.children.index(rec)
        except ValueError:
            return None
    want = {'CELL': 6, 'WRLD': 1, 'DIAL': 7}.get(rec.sig)
    if want is None:
        return None
    for c in g.children[index:index + 3]:
        if isinstance(c, Group) and c.gtype == want and c.label_formid == rec.formid:
            return c
    return None


def prune_empty(g):
    while g is not None and g.gtype != -1 and not g.children:
        parent = g.parent
        if parent is None:
            break
        parent.children.remove(g)
        g = parent


def record_context(rec):
    """Describe where a record lives: returns dict with cell/world/topic ids
    and the group type (persistent/temporary) for CELL children."""
    ctx = {}
    g = rec.parent
    while g is not None and g.gtype != -1:
        if g.gtype in (8, 9, 10) and 'child_type' not in ctx:
            ctx['child_type'] = g.gtype
            ctx['cell'] = g.label_formid
        elif g.gtype == 6 and 'cell' not in ctx:
            ctx['cell'] = g.label_formid
        elif g.gtype == 1:
            ctx['world'] = g.label_formid
        elif g.gtype == 7:
            ctx['topic'] = g.label_formid
        elif g.gtype in (4, 5) and 'block' not in ctx:
            ctx['ext_subblock' if g.gtype == 5 else 'ext_block'] = g.label_yx
        g = g.parent
    return ctx
