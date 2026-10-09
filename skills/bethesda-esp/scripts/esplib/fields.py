"""Record-level decoding/encoding: turns a Record's subrecords into a list of
named, typed values and back."""

import json

from .core import EspError, Subrecord
from .codec import (Ctx, FormID, LStr, Struct, Arr, Custom, BySize, decode_value,
                    encode_value, format_formid, iter_formids)
from . import schema_sse as schema


class DecodedSub:
    __slots__ = ('sig', 'value', 'raw', 'ok', 'error', 'section')

    def __init__(self, sig, value, raw, ok=True, error=None, section=None):
        self.sig = sig
        self.value = value
        self.raw = raw
        self.ok = ok
        self.error = error
        self.section = section

    def __repr__(self):
        return f'<{self.sig} {"ok" if self.ok else "raw"}>'


_GENERIC_DEFS = {}


def record_def(sig):
    d = schema.RECORDS.get(sig)
    if d is None:
        d = _GENERIC_DEFS.get(sig)
        if d is None:
            d = schema.RecordDef(sig, sig, schema.GENERIC, notes='(generic layout: only common fields decoded)')
            _GENERIC_DEFS[sig] = d
    return d


class _Walker:
    """Tracks section/state while walking subrecords in order."""

    def __init__(self, rdef, ctx):
        self.rdef = rdef
        self.ctx = ctx
        self.section = None   # (name, start, end, subs)

    def spec_for(self, sig):
        rdef = self.rdef
        if rdef is None:
            return None
        if self.section is None:
            for sec in rdef.sections:
                if sig in sec[1]:
                    self.section = sec
                    break
        if self.section is not None:
            name, start, end, subs = self.section
            if sig in subs:
                self.ctx.state['section'] = name
                return subs.get(sig)
            self.section = None
        self.ctx.state['section'] = None
        return rdef.subs.get(sig)

    def after(self, sig, raw):
        hook = schema.STATE_HOOKS.get(sig)
        if hook:
            hook(raw, self.ctx.state)
        if self.section is not None and sig in self.section[2]:
            self.section = None
            self.ctx.state['section'] = None


def make_ctx(plugin, record, formid_parser=None):
    ctx = Ctx(plugin, record)
    if formid_parser is not None:
        ctx.formid_parser = formid_parser
    return ctx


def decode_record(rec, plugin=None, formid_parser=None):
    """Decode all subrecords of `rec`. Unknown or non-matching data is kept as
    raw bytes (DecodedSub.ok False)."""
    plugin = plugin or rec.plugin
    ctx = make_ctx(plugin, rec, formid_parser)
    w = _Walker(record_def(rec.sig), ctx)
    out = []
    for s in rec.subrecords:
        spec = w.spec_for(s.sig)
        sec = ctx.state.get('section')
        if spec is None:
            out.append(DecodedSub(s.sig, {'$hex': s.data.hex()}, s.data, ok=False, section=sec))
        else:
            try:
                v = decode_value(spec, s.data, ctx)
                back = encode_value(spec, v, ctx)
                if back != s.data:
                    raise EspError('re-encoding mismatch')
                out.append(DecodedSub(s.sig, v, s.data, section=sec))
            except Exception as e:  # noqa: BLE001 - any decode problem -> raw
                out.append(DecodedSub(s.sig, {'$hex': s.data.hex()}, s.data, ok=False,
                                      error=str(e) or e.__class__.__name__, section=sec))
        w.after(s.sig, s.data)
    return out


def encode_items(rec_sig, items, plugin, record=None, formid_parser=None, sync_counters=True):
    """items: iterable of (sig, value). Returns list[Subrecord]."""
    ctx = make_ctx(plugin, record, formid_parser)
    if record is None:
        ctx.form_version = 44
    w = _Walker(record_def(rec_sig), ctx)
    subs = []
    for sig, value in items:
        if len(sig) != 4:
            raise EspError(f'bad subrecord signature {sig!r}')
        if isinstance(value, dict) and set(value) == {'$hex'}:
            data = bytes.fromhex(value['$hex'])
            w.spec_for(sig)
        elif isinstance(value, (bytes, bytearray)):
            data = bytes(value)
            w.spec_for(sig)
        else:
            spec = w.spec_for(sig)
            if spec is None:
                raise EspError(f'{rec_sig}.{sig} has no known layout; give it as {{"$hex": "..."}}')
            try:
                data = encode_value(spec, value, ctx)
            except EspError as e:
                raise EspError(f'{rec_sig}.{sig}: {e}')
            except (TypeError, ValueError, KeyError) as e:
                raise EspError(f'{rec_sig}.{sig}: bad value {value!r}: {e}')
        subs.append(Subrecord(sig, data))
        w.after(sig, data)
    if sync_counters:
        subs = sync_counter_subs(subs)
    return subs


def sync_counter_subs(subs):
    """Keep KSIZ/COCT/LLCT/SPCT/PRKZ equal to the number of their items."""
    import struct as _st
    for counter, (item, size, mode) in schema.COUNTERS.items():
        idx_items = [i for i, s in enumerate(subs) if s.sig == item]
        if mode == 'array':
            n = sum(len(subs[i].data) // 4 for i in idx_items)
        else:
            n = len(idx_items)
        fmt = {'u8': '<B', 'u32': '<I'}[size]
        idx_counter = [i for i, s in enumerate(subs) if s.sig == counter]
        if not idx_items:
            if idx_counter and mode == 'array':
                subs = [s for s in subs if s.sig != counter]
            elif idx_counter:
                for i in idx_counter:
                    subs[i] = Subrecord(counter, _st.pack(fmt, 0))
            continue
        data = _st.pack(fmt, min(n, 255) if size == 'u8' else n)
        if idx_counter:
            subs[idx_counter[0]] = Subrecord(counter, data)
        else:
            subs.insert(idx_items[0], Subrecord(counter, data))
    return subs


# ---------------------------------------------------------------------------
# JSON conversion
# ---------------------------------------------------------------------------

def to_jsonable(v, plugin, strings=None):
    if isinstance(v, FormID):
        return format_formid(int(v), plugin)
    if isinstance(v, LStr):
        out = {'lstring': int(v)}
        if strings is not None:
            t = strings.get(int(v))
            if t is not None:
                out['text'] = t
        return out
    if isinstance(v, dict):
        return {k: to_jsonable(x, plugin, strings) for k, x in v.items()}
    if isinstance(v, list):
        return [to_jsonable(x, plugin, strings) for x in v]
    if isinstance(v, bytes):
        return {'$hex': v.hex()}
    return v


def record_to_json(rec, plugin=None, strings=None, include_raw_errors=False):
    plugin = plugin or rec.plugin
    from .core import RECORD_FLAG_NAMES
    from .codec import flags_to_names
    fields = []
    for d in decode_record(rec, plugin):
        item = {d.sig: to_jsonable(d.value, plugin, strings)}
        if include_raw_errors and not d.ok and d.error:
            item['$error'] = d.error
        fields.append(item)
    out = {
        'type': rec.sig,
        'formid': format_formid(rec.formid, plugin) or '0x00000000',
        'flags': flags_to_names(rec.flags, RECORD_FLAG_NAMES),
        'form_version': rec.version,
    }
    if rec.vc1 or rec.vc2:
        out['vc'] = [rec.vc1, rec.vc2]
    out['fields'] = fields
    return out


def json_items(fields):
    """[{SIG: value}, ...] -> [(SIG, value)]"""
    items = []
    for f in fields:
        keys = [k for k in f if not k.startswith('$')]
        if len(keys) != 1:
            raise EspError(f'each field entry needs exactly one signature key: {f!r}')
        items.append((keys[0], f[keys[0]]))
    return items


def dumps(obj, indent=1):
    return json.dumps(obj, indent=indent, ensure_ascii=False)


def formids_in(decoded):
    """All FormIDs found in decoded subrecords: list of (sig, FormID)."""
    out = []
    for d in decoded:
        if d.ok:
            for f in iter_formids(d.value):
                out.append((d.sig, int(f)))
    return out


# ---------------------------------------------------------------------------
# schema description (for `esp.py schema`)
# ---------------------------------------------------------------------------

def describe_spec(spec, indent=0):
    pad = '  ' * indent
    if isinstance(spec, str):
        return spec
    if isinstance(spec, tuple):
        return f'{spec[1]} bytes'
    if isinstance(spec, Struct):
        lines = ['{']
        for f in spec.fields:
            meta = ''
            if f.enum:
                vals = list(f.enum.values())
                meta = ' one of: ' + ', '.join(map(str, vals[:12])) + (' ...' if len(vals) > 12 else '')
            if f.flags:
                vals = list(f.flags.values())
                meta = ' flags: ' + ', '.join(map(str, vals[:40])) + (' ...' if len(vals) > 40 else '')
            lines.append(f'{pad}  {f.name}: {describe_spec(f.spec, indent + 1)}{meta}')
        lines.append(pad + '}')
        return '\n'.join(lines)
    if isinstance(spec, Arr):
        inner = describe_spec(spec.elem, indent)
        return f'list of {inner}' + (f' (x{spec.count})' if spec.count else '')
    if isinstance(spec, Custom):
        return f'<{spec.name}> {spec.doc}'
    if isinstance(spec, BySize):
        return ' | '.join(f'[{n} bytes] {describe_spec(v, indent)}' for n, v in spec.variants.items())
    return repr(spec)
