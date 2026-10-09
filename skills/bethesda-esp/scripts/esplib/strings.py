"""Localized string tables (.STRINGS / .DLSTRINGS / .ILSTRINGS) and a small
read-only BSA reader (v104 Skyrim LE zlib, v105 Skyrim SE LZ4) so that names of
localized plugins (Skyrim.esm, DLCs, many CC plugins) can be resolved even when
the strings only exist inside "Skyrim - Interface.bsa"."""

import os
import struct
import zlib

from .core import EspError

KINDS = ('STRINGS', 'DLSTRINGS', 'ILSTRINGS')


# ---------------------------------------------------------------------------
# strings files
# ---------------------------------------------------------------------------

def parse_strings(data, kind, encoding=None):
    count, size = struct.unpack_from('<II', data, 0)
    base = 8 + count * 8
    block = data[base:base + size]
    enc = encoding
    if enc is None:
        try:
            block.decode('utf-8')
            enc = 'utf-8'
        except UnicodeDecodeError:
            enc = 'cp1252'
    out = {}
    for i in range(count):
        sid, off = struct.unpack_from('<II', data, 8 + i * 8)
        if kind == 'STRINGS':
            end = block.find(b'\0', off)
            raw = block[off:end if end >= 0 else len(block)]
        else:
            n = struct.unpack_from('<I', block, off)[0]
            raw = block[off + 4:off + 4 + n]
            if raw.endswith(b'\0'):
                raw = raw[:-1]
        out[sid] = raw.decode(enc, errors='replace')
    return out, enc


def build_strings(table, kind, encoding='cp1252'):
    """Serialize {id: text} into a strings file."""
    ids = sorted(table)
    block = bytearray()
    directory = bytearray()
    for sid in ids:
        directory += struct.pack('<II', sid, len(block))
        b = table[sid].encode(encoding) + b'\0'
        if kind == 'STRINGS':
            block += b
        else:
            block += struct.pack('<I', len(b)) + b
    return struct.pack('<II', len(ids), len(block)) + bytes(directory) + bytes(block)


class StringTables:
    """All three tables for one plugin; get(id) searches the expected file
    first and falls back to the others."""

    def __init__(self, tables=None, source=None, encoding=None):
        self.tables = tables or {k: {} for k in KINDS}
        self.source = source
        self.encoding = encoding

    def get(self, sid, kind=None):
        if sid == 0:
            return ''
        order = [kind] if kind else []
        order += [k for k in KINDS if k != kind]
        for k in order:
            t = self.tables.get(k)
            if t and sid in t:
                return t[sid]
        return None

    def __len__(self):
        return sum(len(t) for t in self.tables.values())

    @classmethod
    def find(cls, plugin_path, language='english', data_dir=None, encoding=None):
        """Locate strings for a plugin: loose Data/Strings/ first, then BSAs."""
        data_dir = data_dir or os.path.dirname(os.path.abspath(plugin_path))
        base = os.path.splitext(os.path.basename(plugin_path))[0]
        tables = {}
        src = []
        sdir = _ci_join(data_dir, 'strings')
        for kind in KINDS:
            fname = f'{base}_{language}.{kind}'
            p = _ci_join(sdir, fname) if sdir else None
            if p and os.path.isfile(p):
                with open(p, 'rb') as f:
                    tables[kind], enc = parse_strings(f.read(), kind, encoding)
                src.append(p)
        missing = [k for k in KINDS if k not in tables]
        if missing:
            for bsa_path in _candidate_bsas(data_dir, base):
                try:
                    bsa = BSA(bsa_path)
                except (EspError, OSError, struct.error):
                    continue
                for kind in list(missing):
                    inner = f'strings\\{base}_{language}.{kind}'.lower()
                    if bsa.has(inner):
                        tables[kind], enc = parse_strings(bsa.read(inner), kind, encoding)
                        src.append(f'{bsa_path}:{inner}')
                        missing.remove(kind)
                if not missing:
                    break
        if not tables:
            return None
        for k in KINDS:
            tables.setdefault(k, {})
        return cls(tables, ', '.join(src), encoding)


def _ci_join(directory, name):
    """Case-insensitive path join (Linux installs/Proton)."""
    if not directory or not os.path.isdir(directory):
        return None
    p = os.path.join(directory, name)
    if os.path.exists(p):
        return p
    low = name.lower()
    for n in os.listdir(directory):
        if n.lower() == low:
            return os.path.join(directory, n)
    return None


def _candidate_bsas(data_dir, base):
    if not os.path.isdir(data_dir):
        return []
    names = [n for n in os.listdir(data_dir) if n.lower().endswith('.bsa')]
    bl = base.lower()
    first = [n for n in names if n.lower().startswith(bl)]
    iface = [n for n in names if 'interface' in n.lower() and n not in first]
    rest = [n for n in names if n not in first and n not in iface]
    return [os.path.join(data_dir, n) for n in first + iface + rest]


# ---------------------------------------------------------------------------
# BSA
# ---------------------------------------------------------------------------

class BSA:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            head = f.read(36)
            if len(head) < 36 or head[:4] != b'BSA\0':
                raise EspError(f'{path}: not a BSA')
            (_, self.version, off, self.flags, nfolders, nfiles, _fnl, _fil,
             _ff, _pad) = struct.unpack('<4sIIIIIIIHH', head)
            if self.version not in (103, 104, 105):
                raise EspError(f'{path}: unsupported BSA version {self.version}')
            frec = 24 if self.version == 105 else 16
            f.seek(off)
            folders = []
            for _ in range(nfolders):
                rec = f.read(frec)
                if self.version == 105:
                    _h, count, _u, _o = struct.unpack('<QIIQ', rec)
                else:
                    _h, count, _o = struct.unpack('<QII', rec)
                folders.append(count)
            entries = []
            for count in folders:
                name = ''
                if self.flags & 0x1:
                    n = f.read(1)[0]
                    name = f.read(n).rstrip(b'\0').decode('cp1252')
                for _ in range(count):
                    _h, size, foff = struct.unpack('<QII', f.read(16))
                    entries.append([name, size, foff])
            names = []
            if self.flags & 0x2:
                blob = f.read(_fil)
                names = blob.split(b'\0')[:nfiles]
            self.files = {}
            for i, (folder, size, foff) in enumerate(entries):
                fn = names[i].decode('cp1252') if i < len(names) else f'#{i}'
                self.files[(folder + '\\' + fn).lower()] = (size, foff)

    def has(self, inner):
        return inner.lower().replace('/', '\\') in self.files

    def list(self):
        return sorted(self.files)

    def read(self, inner):
        size, off = self.files[inner.lower().replace('/', '\\')]
        compressed = bool(self.flags & 0x4)
        if size & 0x40000000:
            compressed = not compressed
        size &= 0x3FFFFFFF
        with open(self.path, 'rb') as f:
            f.seek(off)
            data = f.read(size)
        if self.flags & 0x100 and self.version in (104, 105):
            n = data[0]
            data = data[1 + n:]
        if not compressed:
            return data
        orig = struct.unpack_from('<I', data, 0)[0]
        body = data[4:]
        if self.version == 105:
            out = lz4_frame_decompress(body)
        else:
            out = zlib.decompress(body)
        if len(out) != orig:
            raise EspError(f'{inner}: decompressed {len(out)} bytes, expected {orig}')
        return out


# ---------------------------------------------------------------------------
# LZ4 (frame + block), pure Python
# ---------------------------------------------------------------------------

def lz4_frame_decompress(data):
    if data[:4] != b'\x04\x22\x4d\x18':
        # some tools store raw LZ4 blocks; try that
        return lz4_block_decompress(data)
    pos = 4
    flg = data[pos]
    pos += 2   # FLG, BD
    block_checksum = bool(flg & 0x10)
    if flg & 0x08:
        pos += 8
    if flg & 0x01:
        pos += 4
    pos += 1   # HC
    out = bytearray()
    while True:
        bsize = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if bsize == 0:
            break
        raw = bsize & 0x80000000
        bsize &= 0x7FFFFFFF
        block = data[pos:pos + bsize]
        pos += bsize
        if raw:
            out += block
        else:
            _lz4_block_into(block, out)
        if block_checksum:
            pos += 4
    return bytes(out)


def lz4_block_decompress(block):
    out = bytearray()
    _lz4_block_into(block, out)
    return bytes(out)


def _lz4_block_into(src, out):
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        if lit:
            out += src[i:i + lit]
            i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        if off == 0 or off > len(out):
            raise EspError('corrupt LZ4 data')
        start = len(out) - off
        if off >= ml:
            out += out[start:start + ml]
        else:
            chunk = out[start:]
            reps = ml // off + 1
            out += (bytes(chunk) * reps)[:ml]
