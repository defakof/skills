"""Schema-driven decoding/encoding of subrecord data.

A schema maps subrecord signatures to *specs*:

    'u8' 'u16' 'u32' 'u64' 'i8' 'i16' 'i32' 'f32'   numbers
    'fid'                                            FormID (4 bytes)
    'zstr'   null-terminated string                 'lstr' localized string
    'char4'  4-char code                             'char'  1 char
    'wstr'   u16-length-prefixed string              'sstr'  u32-length-prefixed
    'bytes'  rest of data (hex)                      ('bytes', N) fixed size
    Struct([...]), Arr(spec), Custom(...), BySize({...})

Every decoded value is re-encoded and compared with the original bytes; on any
mismatch the subrecord is shown as raw hex instead, so an imperfect schema can
never silently corrupt data on save.
"""

import math
import struct

from .core import EspError


class FormID(int):
    """A file-local FormID (top byte = master index)."""
    __slots__ = ()


class LStr(int):
    """A localized-string ID (plugin has the Localized flag)."""
    __slots__ = ()


_NUM = {
    'u8': struct.Struct('<B'), 'u16': struct.Struct('<H'), 'u32': struct.Struct('<I'),
    'u64': struct.Struct('<Q'), 'i8': struct.Struct('<b'), 'i16': struct.Struct('<h'),
    'i32': struct.Struct('<i'), 'i64': struct.Struct('<q'), 'f32': struct.Struct('<f'),
    'fid': struct.Struct('<I'),
}


class Field:
    __slots__ = ('name', 'spec', 'enum', 'flags', 'doc')

    def __init__(self, name, spec, enum=None, flags=None, doc=None):
        self.name = name
        self.spec = spec
        self.enum = enum
        self.flags = flags
        self.doc = doc


def F(name, spec, enum=None, flags=None, doc=None):
    return Field(name, spec, enum, flags, doc)


class Struct:
    """Fixed sequence of fields. Trailing fields may be absent (older form
    versions); bytes left over are kept as `_extra`."""

    def __init__(self, fields, name=None):
        self.fields = [f if isinstance(f, Field) else Field(*f) for f in fields]
        self.name = name


class Arr:
    """Repeated element until end of data (count=None), or a fixed count."""

    def __init__(self, elem, count=None, enum=None, flags=None):
        self.elem = elem
        self.count = count
        self.enum = enum
        self.flags = flags


class Custom:
    def __init__(self, name, decode, encode, doc=''):
        self.name = name
        self.decode = decode
        self.encode = encode
        self.doc = doc


class BySize:
    """Pick a layout by data length (e.g. CRDT is 16 bytes in LE, 24 in SE)."""

    def __init__(self, variants, default=None):
        self.variants = variants
        self.default = default


class Ctx:
    """Decoding context: plugin (for masters/localization/encoding), current
    record, and per-record sequential state used by context-dependent codecs."""

    def __init__(self, plugin=None, record=None, localized=None, encoding=None):
        self.plugin = plugin
        self.record = record
        self.localized = plugin.is_localized if (localized is None and plugin is not None) else bool(localized)
        self.encoding = encoding or (plugin.encoding if plugin is not None else 'cp1252')
        self.state = {}
        self.form_version = record.version if record is not None else 44


# ---------------------------------------------------------------------------
# float helpers
# ---------------------------------------------------------------------------

_F32 = struct.Struct('<f')


def f32_value(raw4):
    """Decode 4 bytes as float32 with the shortest decimal that round-trips."""
    v = _F32.unpack(raw4)[0]
    if math.isnan(v) or math.isinf(v):
        if _F32.pack(v) == raw4 and not math.isnan(v):
            return v
        return 'f32:' + raw4[::-1].hex()      # exact bits, big-endian hex
    if v == 0:
        return v
    for p in range(6, 10):
        s = float(f'{v:.{p}g}')
        if _F32.pack(s) == raw4:
            return s
    return v


def f32_pack(v):
    if isinstance(v, str):
        if v.startswith('f32:'):
            return bytes.fromhex(v[4:])[::-1]
        v = float(v)
    return _F32.pack(v)


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------

class _Reader:
    __slots__ = ('data', 'pos')

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def remaining(self):
        return len(self.data) - self.pos

    def take(self, n):
        if self.pos + n > len(self.data):
            raise EspError('not enough data')
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b


def _decode_scalar(code, r, ctx, whole):
    """Decode one scalar. `whole` = the scalar spans the entire subrecord."""
    if isinstance(code, tuple):
        kind, n = code
        if kind == 'bytes':
            return {'$hex': r.take(n).hex()}
        raise EspError(f'bad spec {code}')
    if code in _NUM:
        st = _NUM[code]
        b = r.take(st.size)
        if code == 'f32':
            return f32_value(b)
        v = st.unpack(b)[0]
        if code == 'fid':
            return FormID(v)
        return v
    if code == 'zstr' or (code == 'lstr' and not ctx.localized):
        if whole:
            b = r.take(r.remaining())
            if not b.endswith(b'\0') or b'\0' in b[:-1]:
                raise EspError('string not cleanly null-terminated')
            return b[:-1].decode(ctx.encoding)
        d = r.data
        end = d.index(b'\0', r.pos)
        s = d[r.pos:end].decode(ctx.encoding)
        r.pos = end + 1
        return s
    if code == 'lstr':
        return LStr(struct.unpack('<I', r.take(4))[0])
    if code == 'char4':
        return r.take(4).decode('latin-1')
    if code == 'char':
        return r.take(1).decode('latin-1')
    if code == 'wstr':
        n = struct.unpack('<H', r.take(2))[0]
        return r.take(n).decode(ctx.encoding)
    if code == 'sstr':
        n = struct.unpack('<I', r.take(4))[0]
        return r.take(n).decode(ctx.encoding)
    if code == 'bytes':
        return {'$hex': r.take(r.remaining()).hex()}
    if code == 'empty':
        if r.remaining():
            raise EspError('expected empty subrecord')
        return None
    raise EspError(f'unknown spec code {code!r}')


def _decode(spec, r, ctx, whole=False):
    if isinstance(spec, (str, tuple)):
        return _decode_scalar(spec, r, ctx, whole)
    if isinstance(spec, Struct):
        out = {}
        if not whole:
            for f in spec.fields:
                out[f.name] = _decode_field(f, r, ctx)
            return out
        for f in spec.fields:
            if r.remaining() == 0:
                break
            start = r.pos
            try:
                out[f.name] = _decode_field(f, r, ctx)
            except (EspError, ValueError, struct.error):
                r.pos = start
                break
        if r.remaining():
            out['_extra'] = r.take(r.remaining()).hex()
        return out
    if isinstance(spec, Arr):
        out = []
        if spec.count is None:
            while r.remaining():
                out.append(_decode_value(spec.elem, r, ctx, spec))
        else:
            for _ in range(spec.count):
                out.append(_decode_value(spec.elem, r, ctx, spec))
        return out
    if isinstance(spec, Custom):
        val, used = spec.decode(r.data[r.pos:], ctx)
        r.pos += used
        return val
    if isinstance(spec, BySize):
        sub = spec.variants.get(r.remaining(), spec.default)
        if sub is None:
            raise EspError(f'no layout for size {r.remaining()}')
        return _decode(sub, r, ctx, whole)
    raise EspError(f'bad spec {spec!r}')


def _decode_value(spec, r, ctx, meta):
    v = _decode(spec, r, ctx)
    return _symbolic(v, getattr(meta, 'enum', None), getattr(meta, 'flags', None))


def _decode_field(f, r, ctx):
    v = _decode(f.spec, r, ctx)
    return _symbolic(v, f.enum, f.flags)


def _symbolic(v, enum, flags):
    if enum and isinstance(v, int) and not isinstance(v, FormID):
        return enum.get(v, v)
    if flags is not None and isinstance(v, int):
        return flags_to_names(v, flags)
    return v


def flags_to_names(v, names):
    out = []
    rest = v
    for bit, name in sorted(names.items()):
        if v & bit == bit and bit:
            out.append(name)
            rest &= ~bit
    if rest:
        out.append(f'0x{rest:X}')
    return out


def names_to_flags(val, names):
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        val = [x for x in val.replace(',', '|').split('|') if x.strip()]
    rev = {n.lower(): b for b, n in names.items()}
    out = 0
    for item in val:
        if isinstance(item, int):
            out |= item
            continue
        s = str(item).strip()
        if s.lower() in rev:
            out |= rev[s.lower()]
        elif s.lower().startswith('0x'):
            out |= int(s, 16)
        elif s.isdigit():
            out |= int(s)
        else:
            raise EspError(f'unknown flag {s!r}; valid: {", ".join(names.values())}')
    return out


def enum_value(val, enum):
    if isinstance(val, int):
        return val
    s = str(val).strip()
    for k, n in enum.items():
        if n.lower() == s.lower():
            return k
    try:
        return int(s, 0)
    except ValueError:
        raise EspError(f'unknown value {s!r}; valid: {", ".join(map(str, enum.values()))}')


def decode_value(spec, data, ctx):
    """Decode a whole subrecord's data. Raises EspError if it doesn't fit."""
    r = _Reader(data)
    v = _decode(spec, r, ctx, whole=True)
    if r.remaining():
        raise EspError(f'{r.remaining()} trailing bytes')
    return v


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------

def _encode_scalar(code, v, ctx, whole, out):
    if isinstance(code, tuple):
        kind, n = code
        b = _hexval(v)
        if len(b) != n:
            raise EspError(f'expected {n} bytes, got {len(b)}')
        out += b
        return
    if code == 'f32':
        out += f32_pack(v)
        return
    if code == 'fid':
        out += struct.pack('<I', ctx_formid(ctx, v))
        return
    if code in _NUM:
        if isinstance(v, bool):
            v = int(v)
        if isinstance(v, str):
            v = int(v, 0)
        out += _NUM[code].pack(v)
        return
    if code == 'zstr' or (code == 'lstr' and not ctx.localized):
        if isinstance(v, (LStr,)) or isinstance(v, dict):
            raise EspError('plugin is not localized: give plain text for this string')
        out += str(v).encode(ctx.encoding) + b'\0'
        return
    if code == 'lstr':
        if isinstance(v, dict) and 'lstring' in v:
            v = v['lstring']
        if isinstance(v, str):
            raise EspError('plugin is localized: string fields hold string IDs; '
                           'delocalize the plugin first (esp.py delocalize) to write text')
        out += struct.pack('<I', int(v))
        return
    if code == 'char4':
        b = str(v).encode('latin-1')
        if len(b) != 4:
            raise EspError('need exactly 4 characters')
        out += b
        return
    if code == 'char':
        out += str(v).encode('latin-1')[:1]
        return
    if code == 'wstr':
        b = str(v).encode(ctx.encoding)
        out += struct.pack('<H', len(b)) + b
        return
    if code == 'sstr':
        b = str(v).encode(ctx.encoding)
        out += struct.pack('<I', len(b)) + b
        return
    if code == 'bytes':
        out += _hexval(v)
        return
    if code == 'empty':
        return
    raise EspError(f'unknown spec code {code!r}')


def _hexval(v):
    if isinstance(v, dict):
        v = v.get('$hex', '')
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    return bytes.fromhex(str(v).replace(' ', ''))


def _encode(spec, v, ctx, out, whole=False):
    if isinstance(spec, (str, tuple)):
        _encode_scalar(spec, v, ctx, whole, out)
        return
    if isinstance(spec, Struct):
        if not isinstance(v, dict):
            raise EspError(f'expected an object with fields {[f.name for f in spec.fields]}')
        unknown = set(v) - {f.name for f in spec.fields} - {'_extra'}
        if unknown:
            raise EspError(f'unknown field(s) {sorted(unknown)}; valid: {[f.name for f in spec.fields]}')
        names = [f.name for f in spec.fields]
        present = [i for i, n in enumerate(names) if n in v]
        last = max(present) if present else -1
        # A value written by hand usually omits the _unused/_unknown padding;
        # then pad trailing padding fields too (decoded values always carry them).
        if not any(k.startswith('_') for k in v):
            while last + 1 < len(names) and names[last + 1].startswith('_'):
                last += 1
        for i, f in enumerate(spec.fields):
            if i > last:
                break
            if f.name in v:
                _encode_field(f, v[f.name], ctx, out)
            else:
                _encode(f.spec, _zero(f.spec), ctx, out)
        if v.get('_extra'):
            out += bytes.fromhex(v['_extra'])
        return
    if isinstance(spec, Arr):
        if not isinstance(v, list):
            raise EspError('expected a list')
        if spec.count is not None and len(v) != spec.count:
            raise EspError(f'expected {spec.count} items')
        for item in v:
            _encode(spec.elem, _unsymbolic(item, spec.enum, spec.flags), ctx, out)
        return
    if isinstance(spec, Custom):
        out += spec.encode(v, ctx)
        return
    if isinstance(spec, BySize):
        # choose the variant whose fields match the given keys best
        cands = list(spec.variants.items())
        if v is None and any(x == 'empty' for _, x in cands):
            return
        if isinstance(v, dict):
            keys = set(v) - {'_extra'}
            fits = [(size, sub) for size, sub in cands
                    if isinstance(sub, Struct) and keys <= {f.name for f in sub.fields}]
            if fits:
                if any(k.startswith('_') for k in keys):
                    # decoded value: the variant with exactly these fields
                    fits.sort(key=lambda x: len(x[1].fields) - len(keys))
                    pick = fits[0][1]
                else:
                    # hand-written value: newest layout for SE records
                    fits.sort(key=lambda x: x[0], reverse=getattr(ctx, 'form_version', 44) >= 44)
                    pick = fits[0][1]
                _encode(pick, v, ctx, out, whole)
                return
        last_err = None
        for size, sub in cands:
            try:
                tmp = bytearray()
                _encode(sub, v, ctx, tmp, whole)
                out += tmp
                return
            except (EspError, ValueError, TypeError, KeyError, struct.error) as e:
                last_err = e
        if spec.default is not None:
            _encode(spec.default, v, ctx, out, whole)
            return
        raise EspError(str(last_err))
    raise EspError(f'bad spec {spec!r}')


def _zero(spec):
    """Default (all-zero) value for a spec, used for omitted struct fields."""
    if isinstance(spec, tuple):
        return {'$hex': '00' * spec[1]}
    if isinstance(spec, str):
        return {'zstr': '', 'lstr': 0, 'wstr': '', 'sstr': '', 'char4': '\0\0\0\0', 'char': '\0',
                'bytes': {'$hex': ''}, 'empty': None}.get(spec, 0)
    if isinstance(spec, Struct):
        return {f.name: _zero(f.spec) for f in spec.fields}
    if isinstance(spec, Arr):
        return [_zero(spec.elem) for _ in range(spec.count or 0)]
    raise EspError('a required field is missing')


def _unsymbolic(v, enum, flags):
    if flags is not None:
        return names_to_flags(v, flags)
    if enum and isinstance(v, str):
        return enum_value(v, enum)
    return v


def _encode_field(f, v, ctx, out):
    _encode(f.spec, _unsymbolic(v, f.enum, f.flags), ctx, out)


def encode_value(spec, v, ctx):
    out = bytearray()
    _encode(spec, v, ctx, out, whole=True)
    return bytes(out)


# ---------------------------------------------------------------------------
# FormID text forms
# ---------------------------------------------------------------------------

def ctx_formid(ctx, v):
    """Turn a user/JSON value into a file-local FormID int for ctx.plugin."""
    if v is None:
        return 0
    if isinstance(v, int):
        return int(v)
    if isinstance(v, dict) and 'formid' in v:
        v = v['formid']
    resolver = getattr(ctx, 'formid_parser', None)
    if resolver is not None:
        return resolver(v)
    return parse_formid_text(v, ctx.plugin)


def parse_formid_text(text, plugin):
    """'0x0001A2B3' / '0001A2B3' (raw file-local) or '01A2B3:Skyrim.esm'."""
    s = str(text).strip()
    if s.lower() in ('', 'null', 'none', '0'):
        return 0
    if ':' in s:
        a, b = s.split(':', 1)
        if all(c in '0123456789abcdefABCDEF' for c in a) and '.' in b:
            obj, name = int(a, 16), b
        elif all(c in '0123456789abcdefABCDEF' for c in b) and '.' in a:
            obj, name = int(b, 16), a
        else:
            raise EspError(f'cannot parse FormID {s!r}')
        if obj > 0xFFFFFF:
            raise EspError(f'object id too large in {s!r}')
        if plugin is None:
            raise EspError('no plugin context for FormKey')
        names = [m.lower() for m in plugin.masters]
        if name.lower() == plugin.name.lower():
            return (len(names) << 24) | obj
        if name.lower() in names:
            return (names.index(name.lower()) << 24) | obj
        raise EspError(f'{name} is not a master of {plugin.name}; add it first '
                       f'(esp.py masters {plugin.name} --add {name})')
    h = s[2:] if s.lower().startswith('0x') else s
    if len(h) <= 8 and all(c in '0123456789abcdefABCDEF' for c in h):
        return int(h, 16)
    raise EspError(f'cannot parse FormID {s!r} (use 0x0001A2B3, 01A2B3:Skyrim.esm or an EditorID)')


def format_formid(fid, plugin):
    if fid == 0:
        return None
    if plugin is None:
        return f'0x{fid:08X}'
    idx = fid >> 24
    ms = plugin.masters
    if idx < len(ms):
        return f'{fid & 0xFFFFFF:06X}:{ms[idx]}'
    if idx == len(ms):
        return f'{fid & 0xFFFFFF:06X}:{plugin.name}'
    return f'0x{fid:08X}'


# ---------------------------------------------------------------------------
# FormID enumeration (for remapping, reference search)
# ---------------------------------------------------------------------------

def iter_formids(v):
    """Yield every FormID inside a decoded value."""
    if isinstance(v, FormID):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from iter_formids(x)
    elif isinstance(v, list):
        for x in v:
            yield from iter_formids(x)


def map_formids(v, fn):
    """Return a copy of v with every FormID replaced by fn(FormID)."""
    if isinstance(v, FormID):
        return FormID(fn(int(v)))
    if isinstance(v, dict):
        return {k: map_formids(x, fn) for k, x in v.items()}
    if isinstance(v, list):
        return [map_formids(x, fn) for x in v]
    return v
