#!/usr/bin/env python3
"""esp.py - inspect, edit and patch Bethesda plugins (.esp/.esm/.esl).

Built for Skyrim Special Edition / Anniversary Edition; reads Skyrim LE too.
No dependencies beyond Python 3.8+.

Run `esp.py <command> -h` for details. Record arguments accept an EditorID,
a FormKey (012EB7:Skyrim.esm), or a file-local FormID (0x00012EB7).
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from esplib import core, ops                                  # noqa: E402
from esplib.core import Plugin, EspError, Group, RECORD_FLAG_NAMES, record_context  # noqa: E402
from esplib.codec import FormID, LStr, format_formid, flags_to_names               # noqa: E402
from esplib.fields import (decode_record, record_to_json, json_items, encode_items,  # noqa: E402
                           to_jsonable, describe_spec, record_def, dumps)
from esplib.loadorder import LoadOrder, lookup_record, read_plugins_txt            # noqa: E402
from esplib import schema_sse as schema                                            # noqa: E402
from esplib import lorder, conflicts as conflicts_mod, eslify as eslify_mod, advice   # noqa: E402
from esplib import masterlist as masterlist_mod                                    # noqa: E402

OUT = sys.stdout


def say(*a):
    print(*a, file=OUT)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_lo(args):
    lo = LoadOrder(getattr(args, 'data', None), getattr(args, 'encoding', None),
                   getattr(args, 'lang', 'english'))
    return lo


def load(lo, path):
    if not os.path.isfile(path):
        found = lo.find_file(path)
        if found is None:
            raise EspError(f'file not found: {path}')
        path = found
    return lo.add(path)


def save(plugin, args, default_path=None):
    out = getattr(args, 'output', None) or default_path or plugin.path
    if getattr(args, 'dry_run', False):
        say(f'(dry run) would write {out}')
        return None
    backup = not getattr(args, 'no_backup', False)
    if out != plugin.path:
        backup = False
    if os.path.basename(out).lower() != plugin.name.lower():
        plugin.name = os.path.basename(out)
    path = plugin.save(out, backup=backup)
    say(f'wrote {path}' + (f' (backup: {path}.bak*)' if backup and os.path.exists(path + '.bak') else ''))
    return path


def text_of(lo, plugin, v, strings=None):
    if isinstance(v, LStr):
        st = strings if strings is not None else lo.strings_for(plugin)
        t = st.get(int(v)) if st else None
        return f'"{t}"' if t is not None else f'<lstring {int(v)}>'
    return v


def rec_name(lo, plugin, rec):
    """FULL name of a record as text (resolving localized strings)."""
    try:
        s = rec.get('FULL')
    except EspError:
        return None
    if s is None:
        return None
    if plugin.is_localized and len(s.data) == 4:
        st = lo.strings_for(plugin)
        sid = int.from_bytes(s.data, 'little')
        t = st.get(sid) if st else None
        return t if t is not None else f'<lstring {sid}>'
    return s.data.split(b'\0', 1)[0].decode(plugin.encoding, errors='replace')


def fmt_value(lo, plugin, v, indent=0, width=110):
    """Render a decoded value as compact text with FormIDs resolved."""
    pad = '    ' * indent
    if isinstance(v, FormID):
        return lo.describe(plugin, int(v))
    if isinstance(v, LStr):
        return text_of(lo, plugin, v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return '-'
    if isinstance(v, dict):
        if set(v) == {'$hex'}:
            h = v['$hex']
            n = len(h) // 2
            return f'<{n} bytes> {h[:96]}{"..." if len(h) > 96 else ""}'
        parts = [f'{k}={fmt_value(lo, plugin, x, indent + 1)}' for k, x in v.items()
                 if not (k.startswith('_') and _is_blank(x))]
        one = '{' + ', '.join(parts) + '}'
        if len(one) + len(pad) <= width and '\n' not in one:
            return one
        return '\n' + '\n'.join(f'{pad}    {p}' for p in parts)
    if isinstance(v, list):
        parts = [fmt_value(lo, plugin, x, indent + 1) for x in v]
        one = '[' + ', '.join(parts) + ']'
        if len(one) + len(pad) <= width and '\n' not in one:
            return one
        return '\n' + '\n'.join(f'{pad}    - {p}' for p in parts)
    return str(v)


def _is_blank(x):
    if x in (0, None, '', [], 0.0):
        return True
    if isinstance(x, dict) and set(x) == {'$hex'}:
        return not x['$hex'].strip('0')
    return False


def header_line(lo, plugin, rec):
    fk = format_formid(rec.formid, plugin) or f'{rec.formid:08X}'
    flags = flags_to_names(rec.flags, RECORD_FLAG_NAMES)
    name = rec_name(lo, plugin, rec)
    bits = [f'[{rec.sig}:{fk}]', rec.edid or '']
    if name:
        bits.append(f'"{name}"')
    status = 'override' if plugin.is_override(rec) else 'new'
    extra = [status]
    if flags:
        extra.append('flags=' + '|'.join(flags))
    return ' '.join(b for b in bits if b) + '  (' + ', '.join(extra) + ')'


def parse_types(tlist):
    if not tlist:
        return None
    out = set()
    for t in tlist:
        for x in t.split(','):
            x = x.strip().upper()
            if x:
                if len(x) == 3:
                    x += '_'
                out.add(x)
    return out


def get_records(lo, plugin, names):
    recs = []
    for n in names:
        recs.append(lookup_record(lo, plugin, n))
    return recs


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_info(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    counts = {}
    new = ovr = deleted = 0
    own = p.self_index
    for r in p.records():
        counts[r.sig] = counts.get(r.sig, 0) + 1
        if (r.formid >> 24) == own:
            new += 1
        else:
            ovr += 1
        if r.is_deleted:
            deleted += 1
    flags = flags_to_names(p.header.flags, {1: 'ESM', 0x80: 'Localized', 0x200: 'ESL(light)'})
    ext = os.path.splitext(p.name)[1].lower()
    info = {
        'file': p.path, 'size': os.path.getsize(p.path),
        'flags': flags, 'header_version': round(p.hedr_version, 2),
        'form_version': p.header.version, 'author': p.header_string('CNAM'),
        'description': p.header_string('SNAM'),
        'masters': [{'name': m, 'found': lo.has_file(m)} for m in p.masters],
        'records': new + ovr, 'new_records': new, 'overrides': ovr, 'deleted': deleted,
        'next_object_id': f'0x{p.next_object_id:06X}', 'by_type': dict(sorted(counts.items())),
    }
    if ext == '.esl' and not p.is_esl:
        info['note'] = '.esl extension: the game treats it as light regardless of the flag'
    if p.is_localized:
        st = lo.strings_for(p)
        info['strings'] = st.source if st else 'NOT FOUND (names show as <lstring N>; pass --data)'
    esl = ops.esl_report(p)
    info['esl'] = {'flagged': esl['flagged_esl'], 'eligible_as_is': esl['eligible_as_is'],
                   'problems': esl['problems'], 'warnings': esl['warnings']}
    if args.json:
        say(dumps(info))
        return
    say(f'{p.name}  ({info["size"]:,} bytes)  {" ".join(flags) or "plain plugin"}')
    say(f'  header version {info["header_version"]}, form version {info["form_version"]}, '
        f'next object id {info["next_object_id"]}')
    if info['author']:
        say(f'  author: {info["author"]}')
    if info['description']:
        say(f'  description: {info["description"]}')
    say(f'  masters ({len(p.masters)}):')
    for i, m in enumerate(info['masters']):
        say(f'    [{i:02X}] {m["name"]}' + ('' if m['found'] else '   (not found)'))
    say(f'  records: {info["records"]} ({new} new, {ovr} overrides, {deleted} deleted)')
    say('  by type: ' + ', '.join(f'{k} {v}' for k, v in info['by_type'].items()))
    if 'strings' in info:
        say(f'  strings: {info["strings"]}')
    e = info['esl']
    say(f'  ESL: {"flagged" if e["flagged"] else "not flagged"}; '
        f'{"can be flagged as-is" if e["eligible_as_is"] else "; ".join(e["problems"])}')
    for w in e['warnings']:
        say(f'       note: {w}')
    if 'note' in info:
        say(f'  note: {info["note"]}')


def cmd_list(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    types = parse_types(args.type)
    rx_e = re.compile(args.edid, re.I) if args.edid else None
    rx_n = re.compile(args.name, re.I) if args.name else None
    rows = []
    for r in p.records(types):
        if args.new and p.is_override(r):
            continue
        if args.overrides and not p.is_override(r):
            continue
        if args.deleted and not r.is_deleted:
            continue
        e = r.edid or ''
        if rx_e and not rx_e.search(e):
            continue
        n = rec_name(lo, p, r) if (rx_n or not args.no_names) else None
        if rx_n and not (n and rx_n.search(n)):
            continue
        rows.append((r, e, n))
        if args.limit and len(rows) >= args.limit:
            break
    if args.json:
        say(dumps([{'type': r.sig, 'formid': format_formid(r.formid, p), 'edid': e, 'name': n,
                    'override': p.is_override(r),
                    'flags': flags_to_names(r.flags, RECORD_FLAG_NAMES)} for r, e, n in rows]))
        return
    for r, e, n in rows:
        fk = format_formid(r.formid, p)
        fl = flags_to_names(r.flags & ~core.FLAG_COMPRESSED, RECORD_FLAG_NAMES)
        say(f'{r.sig}  {fk:<28} {e:<40} {("" if n is None else chr(34) + n + chr(34)):<32}'
            f'{"  [override]" if p.is_override(r) else ""}{("  " + "|".join(fl)) if fl else ""}')
    say(f'-- {len(rows)} record(s)' + (' (limit reached)' if args.limit and len(rows) >= args.limit else ''))


def show_record_text(lo, p, r, raw=False):
    say(header_line(lo, p, r))
    ctx = record_context(r)
    if ctx:
        bits = []
        if 'world' in ctx:
            bits.append('world ' + lo.describe(p, ctx['world']))
        if 'cell' in ctx:
            bits.append('cell ' + lo.describe(p, ctx['cell']))
        if 'child_type' in ctx:
            bits.append({8: 'persistent', 9: 'temporary', 10: 'visible distant'}[ctx['child_type']])
        if 'topic' in ctx:
            bits.append('topic ' + lo.describe(p, ctx['topic']))
        say('  in: ' + ', '.join(bits))
    if r.is_deleted and not r.subrecords:
        say('  (deleted, no data)')
    rdef = record_def(r.sig)
    for d in decode_record(r, p):
        if raw or not d.ok:
            h = d.raw.hex()
            note = '' if d.ok else ('  (raw' + (f': {d.error}' if d.error else ': no known layout') + ')')
            say(f'  {d.sig}  <{len(d.raw)} bytes> {h[:120]}{"..." if len(h) > 120 else ""}{note}')
        else:
            say(f'  {d.sig}  {fmt_value(lo, p, d.value, 1)}')
    if rdef and rdef.notes:
        say(f'  -- {rdef.notes}')


def cmd_show(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    recs = get_records(lo, p, args.records)
    if args.json:
        st = lo.strings_for(p)
        out = []
        for r in recs:
            j = record_to_json(r, p, st)
            ctx = record_context(r)
            if ctx:
                j['context'] = {k: (format_formid(v, p) if k in ('cell', 'world', 'topic') else v)
                                for k, v in ctx.items() if k in ('cell', 'world', 'topic', 'child_type')}
            out.append(j)
        say(dumps(out[0] if len(out) == 1 else out))
        return
    for i, r in enumerate(recs):
        if i:
            say('')
        show_record_text(lo, p, r, args.raw)


def _decoded_strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for x in v.values():
            yield from _decoded_strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _decoded_strings(x)


def cmd_find(args):
    lo = make_lo(args)
    plugins = [load(lo, x) for x in args.plugins]
    types = parse_types(args.type)
    rx_e = re.compile(args.edid, re.I) if args.edid else None
    rx_n = re.compile(args.name, re.I) if args.name else None
    rx_t = re.compile(args.text, re.I) if args.text else None
    ref = None
    if args.ref:
        p0 = plugins[0]
        fid = lo.resolve(args.ref, p0, search=plugins[1:])
        ref = lo.formkey(p0, fid)
    hits = 0
    for p in plugins:
        target = None
        if ref:
            target = lo.local_fid(p, ref[0], ref[1])
            if target is None:
                continue
        st = lo.strings_for(p)
        for r in p.records(types):
            if rx_e and not (r.edid and rx_e.search(r.edid)):
                continue
            if rx_n:
                n = rec_name(lo, p, r)
                if not (n and rx_n.search(n)):
                    continue
            why = []
            if rx_t or target is not None:
                dec = decode_record(r, p)
                for d in dec:
                    if rx_t and d.ok:
                        v = d.value
                        if st is not None:
                            try:
                                v = ops.delocalize_value(v, st, d.sig, [])
                            except EspError:
                                pass
                        if any(rx_t.search(s) for s in _decoded_strings(v)):
                            why.append(d.sig)
                    if target is not None:
                        if d.ok and any(int(f) == target for f in ops.iter_formids(d.value)):
                            why.append(d.sig)
                        elif not d.ok and ops.scan_raw_formids(d.raw, {target}):
                            why.append(d.sig + '?')
                if not why:
                    continue
            hits += 1
            say(f'{p.name}: {header_line(lo, p, r)}' + (f'  <- {", ".join(sorted(set(why)))}' if why else ''))
            if args.limit and hits >= args.limit:
                say(f'-- limit {args.limit} reached')
                return
    say(f'-- {hits} match(es)' + ('  ("?" = found inside undecoded data, verify)' if ref else ''))


def cmd_set(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    r = lookup_record(lo, p, args.record)
    edits = []
    for e in args.edits:
        m = re.match(r'^(@?[A-Za-z0-9_#\.\[\]]+?)\s*(\+=|-=|=)(.*)$', e, re.S)
        if not m:
            raise EspError(f'bad edit {e!r}; use PATH=VALUE, PATH+=VALUE or PATH-=VALUE')
        edits.append((m.group(1), m.group(2), m.group(3)))
    before = decode_record(r, p)
    ops.apply_edits(lo, p, r, edits, args.remove or [])
    after = decode_record(r, p)
    _print_change(lo, p, before, after)
    save(p, args)


def _print_change(lo, p, before, after):
    b = [(d.sig, fmt_value(lo, p, d.value)) for d in before]
    a = [(d.sig, fmt_value(lo, p, d.value)) for d in after]
    if b == a:
        say('(no field changes)')
        return
    import difflib
    for line in difflib.unified_diff([f'{s} {v}' for s, v in b], [f'{s} {v}' for s, v in a],
                                     'before', 'after', lineterm='', n=0):
        if line.startswith(('---', '+++', '@@')):
            continue
        say('  ' + line)


def cmd_put(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    with open(args.json_file, encoding='utf-8') as f:
        data = json.load(f)
    recs = data if isinstance(data, list) else [data]
    parser = lo.parser_for(p, allow_add_master=True)
    for j in recs:
        sig = j['type']
        fid = parser(j['formid']) if j.get('formid') not in (None, 'new', 'NEW') else None
        existing = p.find(fid) if fid is not None else None
        tmp = core.Record(sig, fid or 0, 0, [], j.get('form_version', 44))
        tmp.plugin = p
        edid = None
        for item in j['fields']:
            if 'EDID' in item:
                edid = item['EDID']
        if edid is not None:
            tmp._subs = [core.Subrecord('EDID', edid.encode(p.encoding) + b'\0')]
        subs = encode_items(sig, json_items(j['fields']), p, record=tmp, formid_parser=parser)
        flags = ops.names_to_flags(j.get('flags', []), RECORD_FLAG_NAMES)
        if existing is not None:
            existing._subs = subs
            existing.flags = flags | (existing.flags & core.FLAG_COMPRESSED)
            existing.version = j.get('form_version', existing.version)
            existing.touched()
            say(f'updated {header_line(lo, p, existing)}')
            continue
        if fid is None:
            fid = ops.allocate_formid(p)
        rec = core.Record(sig, fid, flags & ~core.FLAG_COMPRESSED, subs, j.get('form_version', 44))
        rec._raw = None
        ctx = {}
        if 'context' in j:
            c = j['context']
            for k in ('cell', 'world', 'topic'):
                if c.get(k):
                    ctx[k] = parser(c[k])
            if 'child_type' in c:
                ctx['child_type'] = c['child_type']
        ops.place_record(p, rec, ctx, lo)
        say(f'added {header_line(lo, p, rec)}')
    save(p, args)


def cmd_delete(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    recs = get_records(lo, p, args.records)
    if args.mark or args.disable:
        for r in recs:
            if args.disable:
                ops.undelete_and_disable(p, r)
                say(f'disabled {header_line(lo, p, r)}')
            else:
                if r.sig in core.CELL_CHILD_TYPES - {'NAVM', 'LAND'}:
                    say(f'warning: deleting placed references ({r.sig}) can crash the game when other '
                        f'mods touch them; consider --disable instead')
                ops.mark_deleted(p, r)
                say(f'marked deleted {header_line(lo, p, r)}')
        save(p, args)
        return
    targets = {r.formid for r in recs}
    refs = [(r, s) for r, s in ops.find_references(p, targets) if r.formid not in targets]
    if refs and not args.force:
        say('refusing: other records in this plugin reference what you are deleting:')
        for r, sigs in refs[:30]:
            say(f'  {header_line(lo, p, r)} <- {", ".join(sigs)}')
        say('use --force to delete anyway (those references will dangle)')
        sys.exit(2)
    for r in recs:
        kind = 'override' if p.is_override(r) else 'new record'
        p.remove(r)
        say(f'removed {r.sig}:{format_formid(r.formid, p)} {r.edid or ""} ({kind})')
    if any(not p.is_override(r) for r in recs):
        say('note: other plugins that depend on this one may reference removed records')
    save(p, args)


def cmd_new(args):
    if os.path.exists(args.plugin) and not args.force:
        raise EspError(f'{args.plugin} exists (use --force to overwrite)')
    p = Plugin.new(os.path.basename(args.plugin), args.master or [], esm=args.esm, esl=args.esl,
                   author=args.author or '', description=args.desc or '')
    p.path = os.path.abspath(args.plugin)
    p.save(args.plugin, backup=False)
    say(f'created {args.plugin} with masters: {", ".join(p.masters) or "(none)"}')


def cmd_add(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    sig = args.type.upper()
    if len(sig) == 3:
        sig += '_'
    rec = ops.new_record(p, sig, args.edid, [], lo)
    edits = []
    for e in args.edits or []:
        m = re.match(r'^(@?[A-Za-z0-9_#\.\[\]]+?)\s*(\+=|-=|=)(.*)$', e, re.S)
        if not m:
            raise EspError(f'bad edit {e!r}')
        edits.append((m.group(1), m.group(2), m.group(3)))
    if edits:
        ops.apply_edits(lo, p, rec, edits)
    show_record_text(lo, p, rec)
    save(p, args)


def cmd_copy(args):
    lo = make_lo(args)
    src = load(lo, args.source)
    if not os.path.exists(args.to):
        if not args.create:
            raise EspError(f'{args.to} does not exist (add --create to make it)')
        masters = src.masters + [src.name]
        dst = Plugin.new(os.path.basename(args.to), masters, esl=args.esl)
        dst.path = os.path.abspath(args.to)
        lo.add(dst)
        say(f'creating {args.to} (masters: {", ".join(masters)})')
    elif os.path.abspath(args.to) == src.path:
        dst = src
    else:
        dst = load(lo, args.to)
    recs = get_records(lo, src, args.records)
    if args.edid and len(recs) != 1:
        raise EspError('--edid needs exactly one record')
    for r in recs:
        new, warnings = ops.copy_record(lo, src, r, dst, as_new=args.as_new, new_edid=args.edid)
        say(('copied as new ' if args.as_new else 'copied override ') + header_line(lo, dst, new))
        for w in warnings:
            say(f'  note: {w}')
    save(dst, args, dst.path)


def cmd_masters(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    changed = False
    if args.add:
        added = ops.add_masters(p, args.add, lo)
        if added:
            say('added: ' + ', '.join(added))
            changed = True
    if args.clean:
        removed = ops.clean_masters(p)
        say('removed unused: ' + (', '.join(removed) if removed else '(none)'))
        changed = changed or bool(removed)
    if args.rename:
        old, new = args.rename.split('=', 1)
        ms = p.masters
        low = [m.lower() for m in ms]
        if old.lower() not in low:
            raise EspError(f'{old} is not a master')
        ms[low.index(old.lower())] = new
        p.set_masters(ms)
        say(f'renamed master {old} -> {new}')
        changed = True
    for i, m in enumerate(p.masters):
        say(f'[{i:02X}] {m}' + ('' if lo.has_file(m) else '   (not found)'))
    if changed:
        save(p, args)


def cmd_diff(args):
    lo = make_lo(args)
    a = load(lo, args.a)
    if os.path.basename(args.a).lower() == os.path.basename(args.b).lower():
        lo_b = make_lo(args)      # same file name: keep them apart
        b = load(lo_b, args.b)
        b.name = os.path.basename(args.b)
    else:
        b = load(lo, args.b)
    la, lb = (args.a, args.b) if a.name.lower() == b.name.lower() else (a.name, b.name)
    sa, sb = lo.strings_for(a), lo.strings_for(b)
    if args.records:
        pairs = []
        for t in args.records:
            ra = lookup_record(lo, a, t)
            fk = lo.formkey(a, ra.formid)
            fid_b = lo.local_fid(b, *fk)
            rb = b.find(fid_b) if fid_b is not None else None
            if rb is None:
                say(f'{t}: only in {a.name}')
                continue
            pairs.append((ra, rb))
    else:
        pairs = []
        keys_b = {}
        for r in b.records():
            fk = lo.formkey(b, r.formid)
            if fk:
                keys_b[fk] = r
        only_a = 0
        for r in a.records():
            fk = lo.formkey(a, r.formid)
            rb = keys_b.pop(fk, None)
            if rb is None:
                only_a += 1
                if args.verbose:
                    say(f'only in {a.name}: {header_line(lo, a, r)}')
                continue
            pairs.append((r, rb))
        for r in keys_b.values():
            if args.verbose:
                say(f'only in {b.name}: {header_line(lo, b, r)}')
        say(f'-- {only_a} only in {a.name}, {len(keys_b)} only in {b.name}, {len(pairs)} in both')
    ndiff = 0
    for ra, rb in pairs:
        d = ops.diff_records(ra, a, rb, b, sa, sb)
        if not d:
            continue
        ndiff += 1
        say(f'{header_line(lo, a, ra)}')
        for k, va, vb in d:
            say(f'  {k}:\n    {la}: {json.dumps(va, ensure_ascii=False)}\n    {lb}: {json.dumps(vb, ensure_ascii=False)}')
    say(f'-- {ndiff} record(s) differ')


def _plugins_from_args(lo, args):
    names = list(args.plugins or [])
    if args.load_order:
        names = read_plugins_txt(args.load_order) + names
    plugins = []
    for n in names:
        p = lo.get(n, required=False) if not os.path.isfile(n) else load(lo, n)
        if p is None:
            say(f'warning: {n} not found, skipped')
            continue
        if p not in plugins:
            plugins.append(p)
    return plugins


def cmd_conflicts(args):
    lo = make_lo(args)
    plugins = _plugins_from_args(lo, args)
    if len(plugins) < 1:
        raise EspError('give at least one plugin (or --load-order plugins.txt)')
    types = parse_types(args.type)
    by_key = {}
    for p in plugins:
        for r in p.records(types):
            fk = lo.formkey(p, r.formid)
            if fk is None:
                continue
            by_key.setdefault(fk, []).append((p, r))
    n = 0
    for fk, lst in by_key.items():
        overriders = [(p, r) for p, r in lst if p.name.lower() != fk[1].lower()]
        if len(overriders) < 2 and not (args.include_master and len(lst) >= 2):
            continue
        if args.only and not any(p.name.lower() in [o.lower() for o in args.only] for p, _ in overriders):
            continue
        # do they actually differ?
        p0, r0 = overriders[0]
        norm0 = ops.normalized(r0, p0, lo.strings_for(p0))
        differ = any(ops.normalized(r, p, lo.strings_for(p)) != norm0 for p, r in overriders[1:])
        if args.differ and not differ:
            continue
        n += 1
        win_p, win_r = lst[-1]
        say(f'{header_line(lo, win_p, win_r)}')
        say(f'  defined in {fk[1]}; overridden by: ' + ' > '.join(p.name for p, _ in overriders)
            + f'   winner: {win_p.name}' + ('' if differ else '   (identical)'))
        if args.details and differ:
            base = overriders[0]
            for p, r in overriders[1:]:
                for k, va, vb in ops.diff_records(base[1], base[0], r, p, lo.strings_for(base[0]),
                                                  lo.strings_for(p)):
                    say(f'    {k}: {base[0].name}={json.dumps(va, ensure_ascii=False)[:150]} | '
                        f'{p.name}={json.dumps(vb, ensure_ascii=False)[:150]}')
    say(f'-- {n} conflicting record(s)')


def cmd_itm(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    missing = [m for m in p.masters if not lo.has_file(m)]
    if missing:
        say(f'warning: masters not found (records from them are skipped): {", ".join(missing)}')
    itms = []
    for r in list(p.records()):
        if not p.is_override(r):
            continue
        prev = ops.previous_version(lo, p, r)
        if prev is None:
            continue
        mp, mr = prev
        if r.sig in ('NAVM', 'LAND') or (r.sig in ('CELL', 'WRLD', 'DIAL') and not args.include_parents):
            # parent records are often required carriers for child overrides
            if r.sig in ('CELL', 'WRLD', 'DIAL'):
                if ops.child_group_of(r) is not None:
                    continue
        if ops.is_itm(r, p, mr, mp, lo):
            itms.append(r)
            say(f'ITM: {header_line(lo, p, r)}  (same as {mp.name})')
    say(f'-- {len(itms)} identical-to-master record(s)')
    if args.clean and itms:
        for r in itms:
            p.remove(r)
        say(f'removed {len(itms)} ITM record(s)')
        save(p, args)


def cmd_esl(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    if args.header_171:
        p.set_hedr(version=1.71)
        say('header version set to 1.71 (light range 001-FFF; needs Skyrim SE 1.6.1130+ or BEES)')
        if not args.flag and not args.unflag:
            save(p, args)
            return
    rep = ops.esl_report(p)
    if args.flag:
        if not rep['eligible_as_is']:
            raise EspError('cannot flag as ESL: ' + '; '.join(rep['problems']))
        p.header.flags |= core.FLAG_ESL
        p.header.touched()
        say('ESL flag set')
        save(p, args)
        return
    if args.unflag:
        p.header.flags &= ~core.FLAG_ESL
        p.header.touched()
        say('ESL flag cleared')
        save(p, args)
        return
    say(dumps(rep) if args.json else
        f'{p.name}: {rep["new_records"]} new record(s)'
        + (f', object IDs {rep["min_id"]:06X}-{rep["max_id"]:06X}' if rep['new_records'] else '')
        + f'\n  flagged ESL: {rep["flagged_esl"]}\n  can flag as-is: {rep["eligible_as_is"]}'
        + ''.join(f'\n  problem: {x}' for x in rep['problems'])
        + ''.join(f'\n  note: {x}' for x in rep['warnings']))


def cmd_compact(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    start = int(args.start, 0) if args.start else None
    mapping = ops.compact(p, start)
    if not mapping:
        say('nothing to renumber')
        return
    for old, new in sorted(mapping.items()):
        say(f'  {old:08X} -> {new:08X}')
    say(f'renumbered {len(mapping)} record(s). Plugins that use this one as a master '
        f'must be updated too (they still point at the old FormIDs).')
    save(p, args)


def cmd_delocalize(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    if not p.is_localized:
        say('plugin is not localized')
        return
    st = lo.strings_for(p)
    if st is None:
        raise EspError('strings files not found (pass --data <Data folder> or put Strings/ next to the plugin)')
    n = ops.delocalize(p, st)
    say(f'delocalized {n} record(s) using {st.source}')
    save(p, args)


def cmd_merge(args):
    lo = make_lo(args)
    dst_path = args.into
    plugins = [load(lo, x) for x in args.sources]
    if os.path.exists(dst_path):
        dst = load(lo, dst_path)
    else:
        masters = []
        for p in plugins:
            for m in p.masters + [p.name]:
                if m.lower() not in [x.lower() for x in masters]:
                    masters.append(m)
        # masters load before plugins in game; keep .esm files first
        masters.sort(key=lambda m: 0 if m.lower().endswith('.esm') else 1)
        dst = Plugin.new(os.path.basename(dst_path), masters, esl=args.esl)
        dst.path = os.path.abspath(dst_path)
        lo.add(dst)
        say(f'creating {dst_path}')
    p0 = plugins[0]
    targets = []
    if args.records:
        for t in args.records:
            fid = lo.resolve(t, p0, search=plugins)
            targets.append(lo.formkey(p0, fid))
    else:
        # every record overridden by 2+ of the sources and of a mergeable type
        types = parse_types(args.type) or {'LVLI', 'LVLN', 'LVSP', 'CONT', 'NPC_', 'FLST', 'OTFT',
                                           'ARMO', 'WEAP', 'AMMO', 'ALCH', 'BOOK', 'MISC', 'INGR'}
        seen = {}
        for p in plugins:
            for r in p.records(types):
                if p.is_override(r):
                    fk = lo.formkey(p, r.formid)
                    seen.setdefault(fk, []).append(p)
        targets = [fk for fk, ps in seen.items() if len(ps) >= 2]
    for fk in targets:
        objid, owner = fk
        ovr = lo.chain(objid, owner, plugins)
        if not ovr:
            say(f'{objid:06X}:{owner}: not in any source')
            continue
        base_plugin = lo.get(owner)
        bfid = lo.local_fid(base_plugin, objid, owner)
        base = (base_plugin, base_plugin.find(bfid))
        if base[1] is None:
            say(f'{objid:06X}:{owner}: base record not found')
            continue
        fields, report = ops.merge_versions(lo, base, ovr)
        win_p, win_r = ovr[-1]
        # bring the winner over (masters, context), then replace its fields
        new, warnings = ops.copy_record(lo, win_p, win_r, dst)
        parser = lo.parser_for(dst, allow_add_master=True)
        new._subs = encode_items(new.sig, fields, dst, record=new, formid_parser=parser)
        new.touched()
        say(f'merged {header_line(lo, dst, new)} from {", ".join(p.name for p, _ in ovr)}')
        for line in report:
            say(f'  {line}')
        for w in warnings:
            say(f'  note: {w}')
    save(dst, args, dst.path)


def cmd_export(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    st = lo.strings_for(p)
    types = parse_types(args.type)
    recs = get_records(lo, p, args.records) if args.records else list(p.records(types))
    out = []
    for r in recs:
        j = record_to_json(r, p, st)
        ctx = record_context(r)
        if ctx:
            j['context'] = {k: (format_formid(v, p) if k in ('cell', 'world', 'topic') else v)
                            for k, v in ctx.items() if k in ('cell', 'world', 'topic', 'child_type')}
        out.append(j)
    text = dumps(out)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        say(f'exported {len(out)} record(s) to {args.output}')
    else:
        say(text)


def cmd_verify(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    raw_counts = {}
    errors = 0
    n = 0
    for r in p.records():
        n += 1
        try:
            dec = decode_record(r, p)
        except EspError as e:
            errors += 1
            say(f'ERROR {r.label()}: {e}')
            continue
        for d in dec:
            if not d.ok:
                key = f'{r.sig}.{d.sig}'
                raw_counts[key] = raw_counts.get(key, 0) + 1
    say(f'{n} records parsed, {errors} error(s)')
    if args.roundtrip:
        with open(p.path, 'rb') as f:
            orig = f.read()
        out = p.to_bytes()
        if out == orig:
            say('round trip: byte-identical')
        else:
            pos = next((i for i, (x, y) in enumerate(zip(orig, out)) if x != y), min(len(orig), len(out)))
            say(f'round trip: DIFFERS at byte {pos} (sizes {len(orig)} vs {len(out)}); '
                f'note the header record count is recomputed on save')
    if raw_counts:
        say('subrecords kept as raw bytes (no layout or unusual data):')
        for k, v in sorted(raw_counts.items(), key=lambda kv: -kv[1])[:args.top]:
            say(f'  {k}: {v}')


def cmd_schema(args):
    if not args.type:
        say('Decoded record types:')
        for sig, d in sorted(schema.RECORDS.items()):
            say(f'  {sig}  {d.name}')
        say('Other record types are shown as raw subrecords (still editable as hex).')
        return
    sig = args.type.upper()
    if len(sig) == 3:
        sig += '_'
    d = schema.RECORDS.get(sig)
    if d is None:
        raise EspError(f'no layout known for {sig}')
    say(f'{sig}  {d.name}')
    if d.notes:
        say(f'  {d.notes}')
    for s, spec in d.subs.items():
        if args.sig and s != args.sig.upper():
            continue
        say(f'  {s}: {describe_spec(spec, 1)}')
    for name, start, end, subs in d.sections:
        say(f'  section "{name}" ({"/".join(sorted(start))} ... {"/".join(sorted(end))}):')
        for s, spec in subs.items():
            say(f'    {s}: {describe_spec(spec, 2)}')
    counters = [f'{c} counts {i}' for c, (i, _, _) in schema.COUNTERS.items() if c in d.subs]
    if counters:
        say('  auto-synced counters: ' + ', '.join(counters))


def cmd_tree(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)

    def walk(g, depth):
        for c in g.children:
            if isinstance(c, Group):
                nrec, ngrp = c.count()
                say('  ' * depth + f'{c.describe()}  ({nrec} records)')
                if depth + 1 < args.depth:
                    walk(c, depth + 1)
            elif args.records:
                say('  ' * depth + f'{c.sig}:{format_formid(c.formid, p)} {c.edid or ""}')
    say(f'{p.name}')
    walk(p.root, 1)


def cmd_strings(args):
    lo = make_lo(args)
    p = load(lo, args.plugin)
    if not p.is_localized:
        say('plugin is not localized (names are stored in the plugin itself)')
        return
    st = lo.strings_for(p)
    if st is None:
        say('strings files not found')
        return
    say(f'source: {st.source}; {len(st)} strings')
    if args.search:
        rx = re.compile(args.search, re.I)
        n = 0
        for kind, t in st.tables.items():
            for sid, s in t.items():
                if rx.search(s):
                    say(f'  {kind} {sid}: {s[:200]}')
                    n += 1
                    if n >= args.limit:
                        return


def cmd_bsa(args):
    from esplib.strings import BSA
    b = BSA(args.archive)
    if args.extract:
        data = b.read(args.extract)
        out = args.output or os.path.basename(args.extract.replace('\\', '/'))
        with open(out, 'wb') as f:
            f.write(data)
        say(f'extracted {args.extract} -> {out} ({len(data)} bytes)')
        return
    rx = re.compile(args.filter, re.I) if args.filter else None
    n = 0
    for name in b.list():
        if rx and not rx.search(name):
            continue
        say(name)
        n += 1
    say(f'-- {n} file(s), BSA v{b.version}')


# ---------------------------------------------------------------------------
# load order / whole-load-order analysis
# ---------------------------------------------------------------------------

def load_model(args):
    ml = getattr(args, 'masterlist', None)
    return lorder.LoadOrderModel.from_sources(
        plugins=args.plugins or None, data=args.data, plugins_txt=args.plugins_txt,
        loadorder_txt=args.loadorder_txt, mo2_profile=args.mo2, mods_dir=args.mods, ccc=args.ccc,
        use_cache=not args.no_cache, masterlist=ml, userlist=getattr(args, 'userlist', None),
        use_metadata=not getattr(args, 'no_loot', False) and ml != 'none')


def _flags_str(e):
    s = e.scan
    if s is None:
        return 'missing' if not e.path else 'unreadable'
    bits = []
    if s.is_esm:
        bits.append('ESM')
    if s.is_esl_flag or s.ext == '.esl':
        bits.append('ESL')
    if s.is_localized:
        bits.append('L')
    return ','.join(bits) or 'ESP'


def _print_issues(issues, limit=200, include_info=True):
    order = {'error': 0, 'warning': 1, 'info': 2}
    issues = sorted(issues, key=lambda i: (order[i.level], i.code, i.plugin or ''))
    hidden = 0
    if not include_info:
        hidden = sum(1 for i in issues if i.level == 'info')
        issues = [i for i in issues if i.level != 'info']
    for i in issues[:limit]:
        say(f'  {i.level.upper():7} [{i.code}] {i.message}')
        if i.fix:
            say(f'          fix: {i.fix}')
    if len(issues) > limit:
        say(f'  ... {len(issues) - limit} more (use --json)')
    if hidden:
        say(f'  ({hidden} note(s) hidden; --all shows them)')


def _load_rules(path):
    if not path:
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_plugins_txt(path, model, order):
    """Write a Skyrim SE plugins.txt ('*' = active, Windows-1252, CRLF) for the
    given order. Base-game and Creation Club plugins are left out (the game
    adds them itself); inactive or missing entries stay next to the plugin
    they followed before. Returns names that could not be encoded."""
    placed = [e for e in order if not e.implicit]
    placed_low = {e.low for e in placed}
    anchored = {}                 # lower name of preceding placed plugin (or None) -> [entries]
    anchor = None
    for e in sorted((x for x in model.entries if not x.implicit and x.listed is not None),
                    key=lambda x: x.listed):
        if e.low in placed_low:
            anchor = e.low
        else:
            anchored.setdefault(anchor, []).append(e)
    lines = ['# This file is used by Skyrim to keep track of your downloaded content.',
             '# Written by esp.py loadorder --write']
    for e in anchored.get(None, []):
        lines.append(('*' if e.active else '') + e.name)
    for e in placed:
        lines.append('*' + e.name)
        for x in anchored.get(e.low, []):
            lines.append(('*' if x.active else '') + x.name)
    bad = []
    for n in lines:
        try:
            n.encode('cp1252')
        except UnicodeEncodeError:
            bad.append(n.lstrip('*'))
    with open(path, 'w', encoding='cp1252', errors='replace', newline='\r\n') as f:
        f.write('\n'.join(lines) + '\n')
    return bad


def _meta_desc(model):
    if model.meta is None:
        return model.meta_error or 'LOOT metadata off'
    return '; '.join(model.meta.sources)


def cmd_loadorder(args):
    model = load_model(args)
    issues = model.validate()
    order = model.effective_order()
    idx = model.load_indices(order)
    n_light = sum(1 for e in order if model.is_light(e))
    n_full = len(order) - n_light
    max_full = model.max_full(order)
    inactive = [e for e in model.entries if not e.active and not e.implicit]
    rules = _load_rules(args.rules)
    sorted_order, moves, notes = model.sort(rules=rules, use_overlap=not args.no_overlap,
                                            use_groups=not args.no_groups)
    bad_names = write_plugins_txt(args.write, model, sorted_order) if args.write else []
    groups = {e.low: model.group_of(e) for e in order} if model.meta else {}
    if args.json:
        say(dumps({
            'source': model.source_desc,
            'manager': model.manager,
            'game_version': '.'.join(map(str, model.game_version)) if model.game_version else None,
            'metadata': _meta_desc(model),
            'counts': {'active': len(order), 'full': n_full, 'full_limit': max_full, 'light': n_light,
                       'inactive': len(inactive), 'unlisted': len(model.unlisted)},
            'effective_order': [{'index': idx[e.low], 'name': e.name, 'flags': _flags_str(e),
                                 'implicit': e.implicit, 'listed': e.listed, 'source': e.source,
                                 'group': groups.get(e.low),
                                 'masters': e.scan.masters if e.scan else [],
                                 'new_records': e.scan.n_new() if e.scan else None,
                                 'overrides': e.scan.n_override() if e.scan else None,
                                 'header_version': round(e.scan.hedr_version, 2) if e.scan else None}
                                for e in order],
            'issues': [i.as_dict() for i in issues],
            'suggested_order': [e.name for e in sorted_order],
            'moves': [{'plugin': e.name, 'reasons': list(dict.fromkeys(r))} for e, r in moves],
            'notes': notes,
            'written': args.write,
        }))
        return
    say(f'Load order from {model.source_desc}' + (f' ({model.manager})' if model.manager else ''))
    if model.game_version:
        say(f'  game: SkyrimSE.exe {".".join(map(str, model.game_version))}')
    say(f'  LOOT metadata: {_meta_desc(model)}')
    say(f'  {len(order)} active plugins: {n_full} full (of {max_full} slots), {n_light} light (FE), '
        f'{len(inactive)} inactive')
    if not args.brief:
        say('')
        say('  idx    flags     new  ovrd  plugin')
        for e in order:
            s = e.scan
            tag = f'  [{e.implicit}]' if e.implicit else ''
            grp = f'  {{{groups[e.low]}}}' if args.groups and groups.get(e.low) not in (None, 'default') else ''
            src = f'  <{e.source}>' if args.sources and e.source else ''
            say(f'  {idx[e.low]:<6} {_flags_str(e):<8} {s.n_new() if s else "-":>5} {s.n_override() if s else "-":>5}  '
                f'{e.name}{tag}{grp}{src}')
    say('')
    errs = [i for i in issues if i.level == 'error']
    say(f'Problems: {len(errs)} error(s), {sum(1 for i in issues if i.level == "warning")} warning(s), '
        f'{sum(1 for i in issues if i.level == "info")} note(s)')
    _print_issues(issues, include_info=args.all)
    say('')
    if moves:
        say(f'Suggested changes ({len(moves)} plugin(s) move):')
        for e, reasons in moves:
            uniq = list(dict.fromkeys(reasons))
            say(f'  move {e.name}')
            for r in uniq[:3]:
                say(f'       because {r}')
        if args.full_order or args.write:
            say('Suggested order:')
            for i, e in enumerate(sorted_order):
                say(f'  {i:3} {e.name}')
    else:
        say('Order looks right: no plugin needs to move for the rules this tool checks.')
    for n in notes:
        say(f'  note: {n}')
    if args.write:
        say(f'wrote {args.write}: review it, then (with the game and mod manager closed) replace the plugins.txt '
            'it came from' + (', or apply the order in MO2/Vortex' if model.manager else ''))
        if bad_names:
            say(f'  warning: {len(bad_names)} name(s) are not Windows-1252 and were written with "?": '
                + ', '.join(bad_names[:5]))


def cmd_loot_update(args):
    try:
        out, data = masterlist_mod.update_snapshot(args.source)
    except RuntimeError as ex:
        raise EspError(str(ex))
    except OSError as ex:
        raise EspError(f'could not get the masterlist: {ex} (download it in a browser from '
                       f'{masterlist_mod.MASTERLIST_URL} and pass the file)')
    say(f'LOOT masterlist: {len(data["plugins"])} plugin entries, {len(data["groups"])} groups from {data["source"]}')
    say(f'saved to {out}; loadorder/scan use it from now on')


def cmd_scan(args):
    import time
    t0 = time.time()
    model = load_model(args)
    issues = model.validate()
    sc = conflicts_mod.Scanner(model)
    types = parse_types(args.type)
    confl = sc.conflicts(only=args.only, types=types)
    deep_done = 0
    if args.deep:
        lo = LoadOrder(model.data_dir, getattr(args, 'encoding', None), getattr(args, 'lang', 'english'))
        for d, _ in model.search_dirs:
            if d not in lo.data_dirs:
                lo.data_dirs.append(d)
        dc = conflicts_mod.DeepComparer(sc, lo)
        for c in confl[:args.max_deep]:
            try:
                c.deep = dc.compare(c)
            except (EspError, OSError) as ex:
                c.deep = {'status': 'unknown', 'error': str(ex), 'losers': []}
            deep_done += 1
    dirty = sc.dirty()
    navcells = sc.navmesh_cells()
    edids = sc.edid_duplicates()
    _inj, collisions = sc.injected()
    collided = {k for k, _n, _t in collisions}
    confl_adv = [c for c in confl if c.formkey not in collided]
    reverts = sc.official_reverts()
    if args.deep:
        for plugin, d in reverts.items():
            d['checked'] = True
            for k in d['keys'][:args.max_deep]:
                try:
                    fl = dc.reverted_fields(k, d['fixers'])
                except (EspError, OSError):
                    fl = []
                if fl:
                    d['fields'][sc.formkey(k)] = fl
    _sorted, moves, _notes = model.sort()
    order = model.effective_order()
    n_full = sum(1 for e in order if not model.is_light(e))
    esl = eslify_mod.analyse(model)
    over = sc.overridden_patches(confl)
    adv = advice.from_validation(issues) + advice.from_sort(moves) + advice.from_overridden_patches(over) + \
        advice.from_conflicts(confl_adv, deep=args.deep, scanner=sc) + \
        advice.from_checks(dirty, navcells, edids, collisions, reverts, sc) + advice.from_eslify(
            esl, n_full, model.max_full(order), eslify_mod.procedure(eslify_mod._game_supports_171(model)))
    adv = advice.sort_advice(adv)
    by_cat = {}
    for c in confl:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    statuses = {}
    for c in confl:
        if c.deep:
            statuses[c.deep['status']] = statuses.get(c.deep['status'], 0) + 1
    elapsed = time.time() - t0
    if args.json:
        say(dumps({
            'source': model.source_desc, 'plugins': len(order), 'seconds': round(elapsed, 1),
            'conflicts': {'total': len(confl), 'by_category': by_cat, 'deep_status': statuses,
                          'deep_compared': deep_done},
            'records': [{'record': f'{c.sig} {c.formkey}', 'category': c.category,
                         'plugins': [v.entry.name for v in c.overriders], 'winner': c.winner.entry.name,
                         'patched': c.patched, 'deep': c.deep} for c in confl[:args.limit_records]],
            'dirty': dirty,
            'navmesh_cells': [{'cell': k, 'plugins': [e.name for e in v]} for k, v in navcells],
            'editor_id_duplicates': [{'edid': k, 'where': v} for k, v in edids],
            'injected_collisions': [{'record': k, 'plugins': n, 'types': t} for k, n, t in collisions],
            'reverted_fixes': [{'plugin': p, 'fixes_from': d['fixers'], 'records': [sc.formkey(k) for k in d['keys']],
                                'reverted_fields': d['fields'] if args.deep else None} for p, d in reverts.items()],
            'overridden_patches': [{'patch': p, 'winner': w, 'records': [f'{c.sig} {c.formkey}' for c in cs]}
                                   for (p, w), cs in over.items()],
            'recommendations': [a.as_dict() for a in adv],
        }))
        return
    say(f'Scanned {len(order)} plugins from {model.source_desc} in {elapsed:.1f}s')
    errs = [i for i in issues if i.level == 'error']
    if errs:
        say(f'  {len(errs)} load-order error(s) - see recommendations / esp loadorder')
    say(f'Conflicts: {len(confl)} record(s) overridden by two or more mods')
    for cat, n in sorted(by_cat.items(), key=lambda kv: (conflicts_mod.SEVERITY_RANK[
            conflicts_mod.CATEGORY_INFO.get(kv[0], ('', 'low'))[1]], -kv[1])):
        label, sev = conflicts_mod.CATEGORY_INFO.get(cat, conflicts_mod.CATEGORY_INFO['other'])
        say(f'  {n:6}  {label} ({sev})')
    if args.deep:
        say(f'Deep comparison of {deep_done} record(s): ' +
            ', '.join(f'{v} {k}' for k, v in sorted(statuses.items())) +
            ('' if deep_done == len(confl) else f'  (limited by --max-deep {args.max_deep})'))
        say('  identical = all versions equal; resolved = winner keeps everyone\'s changes; lists = list entries '
            'lost; forwardable = fields silently reverted by the winner; clash = mods changed the same field '
            'differently')
    if dirty:
        say(f'Dirty edits: ' + ', '.join(f'{k} ({v["udr"]} deleted refs, {v["deleted_navmesh"]} deleted navmeshes)'
                                         for k, v in dirty.items()))
    if args.details:
        say('')
        say('Conflicting records:')
        for c in confl[:args.limit_records]:
            st = f' [{c.deep["status"]}]' if c.deep else (' [patched]' if c.patched else '')
            say(f'  {c.sig} {c.formkey}: {" > ".join(v.entry.name for v in c.overriders)}{st}')
            if c.deep:
                for l in c.deep.get('losers', []):
                    for sig, kind, det in l['lost'][:6]:
                        say(f'      {l["plugin"]} loses {sig} ({kind}): {det}')
    say('')
    say(f'Recommendations ({len(adv)}):')
    for n, a in enumerate(adv[:args.limit], 1):
        say(f'{n:3}. [{advice.PRIORITY_NAMES[a.priority]}] {a.title}')
        if a.why:
            say(f'       why: {a.why}')
        for h in a.how[:6]:
            say(f'       - {h}')
        if a.tools:
            say(f'       tools: {"; ".join(advice.TOOLS.get(t, t) for t in a.tools)}')
    if len(adv) > args.limit:
        say(f'... {len(adv) - args.limit} more (raise --limit or use --json)')
    if not args.deep and confl:
        say('Run with --deep to compare field by field and see exactly whose changes are lost.')


def cmd_eslify(args):
    model = load_model(args)
    cands = eslify_mod.analyse(model, configs=args.configs, deep_configs=args.deep_configs)
    order = model.effective_order()
    n_light = sum(1 for e in order if model.is_light(e))
    n_full = len(order) - n_light
    max_full = model.max_full(order)
    steps = eslify_mod.procedure(eslify_mod._game_supports_171(model))
    if args.json:
        say(dumps({'full_plugins': n_full, 'full_limit': max_full, 'light_plugins': n_light,
                   'candidates': [c.as_dict() for c in cands], 'procedure': steps}))
        return
    groups = {}
    for c in cands:
        groups.setdefault(c.verdict, []).append(c)
    say(f'{n_full} of {max_full} full plugin slots used; {n_light} light plugins')
    titles = {
        'flag': 'Can be ESL-flagged as they are (no FormIDs change): esp esl <plugin> --flag',
        'flag-171': 'Can be ESL-flagged after setting header 1.71 (no FormIDs change; game 1.6.1130+ or BEES): '
                    'esp esl <plugin> --header-171 --flag',
        'compact': 'Can become light after compacting FormIDs (nothing found that uses them; new game needed)',
        'compact-care': 'Compacting would break files that use their FormIDs: only with ESLifier, or leave as is',
        'no': 'Should stay full plugins',
        'already': 'Already light',
    }
    for v in ('flag', 'flag-171', 'compact', 'compact-care', 'no', 'already'):
        lst = groups.get(v, [])
        if not lst:
            continue
        say(f'\n{titles[v]}: {len(lst)}')
        for c in lst[:args.limit]:
            extra = f' ids {c.id_range}' if c.id_range else ' (only overrides)'
            deps = f', master of {len(c.dependents)}' if c.dependents else ''
            say(f'  {c.entry.name}: {c.n_new} new{extra}{deps}')
            for r in c.risks:
                say(f'      risk: {r}')
            if v == 'no':
                for r in c.reasons:
                    say(f'      {r}')
            for f in c.files[:5]:
                say(f'      file: {f}')
        if len(lst) > args.limit:
            say(f'  ... {len(lst) - args.limit} more')
    say('\nHow to do it safely:')
    for i, st in enumerate(steps, 1):
        say(f'  {i}. {st}')
    if not args.configs:
        say('Add --configs to also search SKSE/INI/JSON configs that reference each plugin\'s FormIDs.')


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        prog='esp.py', formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
        epilog='Examples:\n'
               '  esp.py info MyMod.esp\n'
               '  esp.py list MyMod.esp -t WEAP --name sword\n'
               '  esp.py show MyMod.esp IronSword\n'
               '  esp.py set MyMod.esp IronSword DATA.damage=12 "FULL=Sharp Iron Sword"\n'
               '  esp.py copy ModA.esp 012EB7:Skyrim.esm --to Patch.esp --create\n'
               '  esp.py conflicts ModA.esp ModB.esp --details\n')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--data', help='game Data folder (to find masters, strings, BSAs)')
    common.add_argument('--encoding', help='text encoding of plugin strings (default cp1252)')
    common.add_argument('--lang', default='english', help='strings language (default english)')
    write = argparse.ArgumentParser(add_help=False)
    write.add_argument('-o', '--output', help='write to this file instead of in place')
    write.add_argument('--no-backup', action='store_true', help='do not keep a .bak when writing in place')
    write.add_argument('--dry-run', action='store_true', help='show what would change, write nothing')
    sub = ap.add_subparsers(dest='cmd', metavar='command')

    def add(name, fn, help_, parents=(), **kw):
        sp = sub.add_parser(name, help=help_, description=help_, parents=[common, *parents],
                            formatter_class=argparse.RawDescriptionHelpFormatter, **kw)
        sp.set_defaults(fn=fn)
        return sp

    sp = add('info', cmd_info, 'summary: masters, flags, record counts, ESL status')
    sp.add_argument('plugin')
    sp.add_argument('--json', action='store_true')

    sp = add('list', cmd_list, 'list records (filter by type, EditorID, name)')
    sp.add_argument('plugin')
    sp.add_argument('-t', '--type', action='append', help='record type(s), e.g. WEAP or WEAP,ARMO')
    sp.add_argument('--edid', help='regex on EditorID')
    sp.add_argument('--name', help='regex on in-game name (FULL)')
    sp.add_argument('--new', action='store_true', help='only records new in this plugin')
    sp.add_argument('--overrides', action='store_true', help='only overrides of master records')
    sp.add_argument('--deleted', action='store_true', help='only records flagged deleted')
    sp.add_argument('--no-names', action='store_true', help='skip name lookup (faster)')
    sp.add_argument('--limit', type=int, default=0)
    sp.add_argument('--json', action='store_true')

    sp = add('show', cmd_show, 'show records with decoded fields')
    sp.add_argument('plugin')
    sp.add_argument('records', nargs='+', help='EditorID, FormKey (012EB7:Skyrim.esm) or 0xFormID')
    sp.add_argument('--json', action='store_true', help='editable JSON (feed back with `put`)')
    sp.add_argument('--raw', action='store_true', help='hex of every subrecord')

    sp = add('find', cmd_find, 'search records by EditorID, name, any text, or FormID reference')
    sp.add_argument('plugins', nargs='+')
    sp.add_argument('-t', '--type', action='append')
    sp.add_argument('--edid', help='regex on EditorID')
    sp.add_argument('--name', help='regex on in-game name')
    sp.add_argument('--text', help='regex on any decoded text field (names, descriptions, book text...)')
    sp.add_argument('--ref', help='records that reference this record (FormKey/EditorID)')
    sp.add_argument('--limit', type=int, default=0)

    sp = add('set', cmd_set, 'edit fields of one record', parents=[write],
             epilog='Edits:\n'
                    '  DATA.damage=20            set a struct field\n'
                    '  "FULL=Steel Sword"         set a string\n'
                    '  KWDA+=WeapMaterialSteel    append to a list (EditorID/FormKey ok)\n'
                    '  KWDA-=WeapMaterialIron     remove from a list\n'
                    '  CNTO+=\'{"item":"IronIngot","count":2}\'   add a repeated subrecord\n'
                    '  CNTO-=IronIngot            remove the entry whose item is IronIngot\n'
                    '  CNTO#1.count=5             2nd CNTO subrecord (0-based #n)\n'
                    '  DNAM.flags=\'["NonPlayable"]\'   flags as list (or A|B text)\n'
                    '  @flags+=InitiallyDisabled  record header flags\n'
                    'Values are parsed as JSON when possible, otherwise taken as text.')
    sp.add_argument('plugin')
    sp.add_argument('record')
    sp.add_argument('edits', nargs='*')
    sp.add_argument('--remove', action='append', help='delete subrecord SIG or SIG#n')

    sp = add('put', cmd_put, 'add or replace records from JSON (as produced by show --json/export)',
             parents=[write])
    sp.add_argument('plugin')
    sp.add_argument('json_file')

    sp = add('delete', cmd_delete, 'remove records (or mark deleted / disable references)',
             parents=[write])
    sp.add_argument('plugin')
    sp.add_argument('records', nargs='+')
    sp.add_argument('--force', action='store_true', help='delete even if other records reference them')
    sp.add_argument('--mark', action='store_true', help='keep the record but flag it Deleted (removes a master record in game)')
    sp.add_argument('--disable', action='store_true', help='for placed refs: undelete + initially disabled (safe xEdit-style)')

    sp = add('new', cmd_new, 'create an empty plugin')
    sp.add_argument('plugin')
    sp.add_argument('--master', action='append', help='master file name (repeat, in load order)')
    sp.add_argument('--esl', action='store_true')
    sp.add_argument('--esm', action='store_true')
    sp.add_argument('--author')
    sp.add_argument('--desc')
    sp.add_argument('--force', action='store_true')

    sp = add('add', cmd_add, 'create a new record (simple types: GLOB, KYWD, FLST, GMST, MISC, LVLI, COBJ, OTFT...)',
             parents=[write])
    sp.add_argument('plugin')
    sp.add_argument('type')
    sp.add_argument('--edid', required=True)
    sp.add_argument('edits', nargs='*', help='PATH=VALUE edits applied after creation')

    sp = add('copy', cmd_copy, 'copy records into another plugin as overrides (patching) or as new records',
             parents=[write])
    sp.add_argument('source')
    sp.add_argument('records', nargs='+')
    sp.add_argument('--to', required=True, help='destination plugin')
    sp.add_argument('--create', action='store_true', help='create destination if missing')
    sp.add_argument('--esl', action='store_true', help='with --create: flag the new plugin ESL')
    sp.add_argument('--as-new', action='store_true', help='copy as a new record with a new FormID')
    sp.add_argument('--edid', help='EditorID for --as-new')

    sp = add('masters', cmd_masters, 'show / add / clean / rename masters (FormIDs are kept valid)',
             parents=[write])
    sp.add_argument('plugin')
    sp.add_argument('--add', action='append', help='add master (repeat)')
    sp.add_argument('--clean', action='store_true', help='remove masters nothing references')
    sp.add_argument('--rename', help='OLD=NEW: rename a master (no FormID changes)')

    sp = add('diff', cmd_diff, 'compare two plugins (or two versions of records)')
    sp.add_argument('a')
    sp.add_argument('b')
    sp.add_argument('records', nargs='*')
    sp.add_argument('-v', '--verbose', action='store_true', help='list records only in one side')

    sp = add('conflicts', cmd_conflicts, 'records overridden by more than one of the given plugins')
    sp.add_argument('plugins', nargs='*')
    sp.add_argument('--load-order', help='plugins.txt / loadorder.txt (names resolved in --data)')
    sp.add_argument('-t', '--type', action='append')
    sp.add_argument('--details', action='store_true', help='show differing fields')
    sp.add_argument('--differ', action='store_true', help='hide conflicts where all versions are identical')
    sp.add_argument('--only', action='append', help='only conflicts involving this plugin')
    sp.add_argument('--include-master', action='store_true', help='also when only 1 plugin overrides')

    sp = add('itm', cmd_itm, 'find (and optionally remove) records identical to their master', parents=[write])
    sp.add_argument('plugin')
    sp.add_argument('--clean', action='store_true', help='remove the ITMs')
    sp.add_argument('--include-parents', action='store_true',
                    help='also report CELL/WRLD/DIAL that carry child overrides')

    sp = add('esl', cmd_esl, 'check / set / clear the light-plugin (ESL) flag', parents=[write])
    sp.add_argument('plugin')
    sp.add_argument('--flag', action='store_true')
    sp.add_argument('--unflag', action='store_true')
    sp.add_argument('--header-171', action='store_true',
                    help='set header version 1.71 first (allows object IDs 001-7FF; game 1.6.1130+ or BEES)')
    sp.add_argument('--json', action='store_true')

    sp = add('compact', cmd_compact, 'renumber new records into the ESL range (0x800-0xFFF)', parents=[write])
    sp.add_argument('plugin')
    sp.add_argument('--start', help='first object id (default 0x800)')

    sp = add('delocalize', cmd_delocalize, 'turn a localized plugin into one with inline strings', parents=[write])
    sp.add_argument('plugin')

    sp = add('merge', cmd_merge, 'build merged overrides (leveled lists, inventories, keywords...) into a patch',
             parents=[write])
    sp.add_argument('sources', nargs='+', help='plugins to merge, in load order')
    sp.add_argument('--into', required=True, help='patch plugin (created if missing)')
    sp.add_argument('--records', nargs='*', help='only these records (default: all conflicting mergeable ones)')
    sp.add_argument('-t', '--type', action='append')
    sp.add_argument('--esl', action='store_true')

    sp = add('export', cmd_export, 'export records as JSON')
    sp.add_argument('plugin')
    sp.add_argument('records', nargs='*')
    sp.add_argument('-t', '--type', action='append')
    sp.add_argument('-o', '--output')

    sp = add('verify', cmd_verify, 'parse every record; report errors and undecoded subrecords')
    sp.add_argument('plugin')
    sp.add_argument('--roundtrip', action='store_true', help='check that saving reproduces the file')
    sp.add_argument('--top', type=int, default=25)

    sp = add('schema', cmd_schema, 'show known field layouts (all types, or one type)')
    sp.add_argument('type', nargs='?')
    sp.add_argument('sig', nargs='?')

    sp = add('tree', cmd_tree, 'show the GRUP structure')
    sp.add_argument('plugin')
    sp.add_argument('--depth', type=int, default=3)
    sp.add_argument('--records', action='store_true')

    sp = add('strings', cmd_strings, 'show where localized strings come from; search them')
    sp.add_argument('plugin')
    sp.add_argument('--search')
    sp.add_argument('--limit', type=int, default=50)

    lo_src = argparse.ArgumentParser(add_help=False)
    lo_src.add_argument('plugins', nargs='*', help='plugin files/names in load order (instead of a plugins.txt)')
    lo_src.add_argument('--plugins-txt', help='plugins.txt (Steam: %%LOCALAPPDATA%%\\Skyrim Special Edition\\plugins.txt)')
    lo_src.add_argument('--loadorder-txt', help='loadorder.txt with the full order (LOOT / MO2 / Wrye Bash)')
    lo_src.add_argument('--mo2', help='Mod Organizer 2 profile folder (reads plugins.txt, loadorder.txt, modlist.txt)')
    lo_src.add_argument('--mods', help='MO2 mods folder (default: from ModOrganizer.ini)')
    lo_src.add_argument('--ccc', help='Skyrim.ccc (default: next to the Data folder)')
    lo_src.add_argument('--no-cache', action='store_true', help='rescan every plugin (ignore the scan cache)')
    lo_src.add_argument('--masterlist', help='LOOT masterlist (.yaml needs PyYAML, or a json(.gz) snapshot); '
                        '"none" to skip LOOT data. Default: bundled snapshot or the one from esp loot-update')
    lo_src.add_argument('--userlist', help='LOOT/Vortex userlist.yaml (default: found automatically)')
    lo_src.add_argument('--no-loot', action='store_true', help='ignore LOOT masterlist/userlist metadata')

    sp = add('loadorder', cmd_loadorder, 'check a load order (masters, flags, limits) and suggest a fixed order',
             parents=[lo_src],
             epilog='Examples:\n'
                    '  esp loadorder --data "D:/Skyrim Special Edition/Data" --plugins-txt "%LOCALAPPDATA%/Skyrim Special Edition/plugins.txt"\n'
                    '  esp loadorder --mo2 "D:/MO2/profiles/Default" --data "D:/Skyrim Special Edition/Data"\n'
                    '  esp loadorder ... --write plugins_sorted.txt\n'
                    'Rules file (--rules): {"Plugin.esp": {"after": ["Other.esp"], "before": ["X.esp"]}}')
    sp.add_argument('--rules', help='JSON file with extra "load after/before" rules')
    sp.add_argument('--write', help='write the suggested order as a plugins.txt to this path')
    sp.add_argument('--no-overlap', action='store_true', help='do not use LOOT\'s record-overlap rule when sorting')
    sp.add_argument('--no-groups', action='store_true', help='do not use LOOT groups when sorting')
    sp.add_argument('--groups', action='store_true', help='show each plugin\'s LOOT group')
    sp.add_argument('--all', action='store_true', help='also print notes (info-level findings)')
    sp.add_argument('--brief', action='store_true', help='do not print the whole order')
    sp.add_argument('--full-order', action='store_true', help='print the whole suggested order')
    sp.add_argument('--sources', action='store_true', help='show which MO2 mod / folder each plugin comes from')
    sp.add_argument('--json', action='store_true')

    sp = add('scan', cmd_scan, 'scan a whole load order for conflicts and get recommendations '
             '(patches, Bashed Patch, Mator Smash, Synthesis, EasyNPC, ESL)', parents=[lo_src])
    sp.add_argument('--deep', action='store_true', help='compare conflicting records field by field (slower)')
    sp.add_argument('--max-deep', type=int, default=20000, help='cap on records compared with --deep')
    sp.add_argument('--only', action='append', help='only conflicts involving this plugin (repeatable)')
    sp.add_argument('-t', '--type', action='append', help='only these record types')
    sp.add_argument('--details', action='store_true', help='list every conflicting record')
    sp.add_argument('--limit', type=int, default=40, help='max recommendations printed')
    sp.add_argument('--limit-records', type=int, default=500, help='max records listed with --details/--json')
    sp.add_argument('--json', action='store_true')

    sp = add('eslify', cmd_eslify, 'which plugins can become light (ESL) plugins, and what compacting would break',
             parents=[lo_src])
    sp.add_argument('--configs', action='store_true',
                    help='also look for INI/JSON configs (SPID, KID, BOS...) that mention each plugin')
    sp.add_argument('--deep-configs', action='store_true', help='with --configs: search whole mod folders, not just SKSE/')
    sp.add_argument('--limit', type=int, default=60)
    sp.add_argument('--json', action='store_true')

    sp = add('loot-update', cmd_loot_update, 'refresh the LOOT masterlist used by loadorder/scan (needs PyYAML)')
    sp.add_argument('source', nargs='?', help='masterlist.yaml file or URL (default: LOOT\'s Skyrim SE masterlist '
                    'on GitHub, branch v0.29)')

    sp = add('bsa', cmd_bsa, 'list or extract files from a BSA archive')
    sp.add_argument('archive')
    sp.add_argument('--filter', help='regex on file paths')
    sp.add_argument('--extract', help='inner path to extract')
    sp.add_argument('-o', '--output')
    return ap


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')   # Windows consoles
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    args, extra = ap.parse_known_args(argv)
    if extra:
        # older argparse cannot mix positionals after options (add ... --edid X FIELD=Y)
        if isinstance(getattr(args, 'edits', None), list) and not any(x.startswith('-') for x in extra):
            args.edits += extra
        elif isinstance(getattr(args, 'records', None), list) and not any(x.startswith('-') for x in extra):
            args.records += extra
        else:
            ap.error('unrecognized arguments: ' + ' '.join(extra))
    if not getattr(args, 'cmd', None):
        ap.print_help()
        return 1
    try:
        args.fn(args)
    except EspError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
