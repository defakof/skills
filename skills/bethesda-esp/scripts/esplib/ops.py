"""High-level plugin operations used by the CLI (and usable from Python)."""

import json
import struct

from .core import (Plugin, Record, Group, Subrecord, EspError, CELL_CHILD_TYPES,
                   TOPIC_CHILD_TYPES, FLAG_COMPRESSED, FLAG_DELETED, FLAG_ESL,
                   FLAG_INITIALLY_DISABLED, FLAG_LOCALIZED, RECORD_FLAG_NAMES,
                   child_group_of, prune_empty, record_context)
from .codec import (FormID, LStr, Struct, Arr, Custom, BySize, map_formids, iter_formids,
                    format_formid, flags_to_names, names_to_flags, decode_value)
from .fields import decode_record, encode_items, record_def, to_jsonable, sync_counter_subs
from . import schema_sse as schema


# ---------------------------------------------------------------------------
# FormID remapping
# ---------------------------------------------------------------------------

def mapper(src, dst):
    """fn(fid_in_src) -> fid_in_dst. Raises if an owner is not a dst master."""
    src_names = src.masters + [src.name]
    dst_low = [m.lower() for m in dst.masters] + [dst.name.lower()]
    table = {}
    for i, n in enumerate(src_names):
        if n.lower() in dst_low:
            table[i] = dst_low.index(n.lower())

    def fn(fid):
        if fid == 0:
            return 0
        idx = fid >> 24
        if idx >= len(src_names):
            return fid      # invalid in source; leave untouched
        if idx not in table:
            raise EspError(f'{src_names[idx]} is not a master of {dst.name}')
        return (table[idx] << 24) | (fid & 0xFFFFFF)
    fn.identity = all(table.get(i) == i for i in range(len(src_names)))
    fn.table = table
    return fn


def scan_raw_formids(data, valid):
    """Positions of 4-byte values in `data` that are in the set `valid`."""
    hits = []
    i = 0
    n = len(data) - 3
    while i < n:
        v = struct.unpack_from('<I', data, i)[0]
        if v in valid:
            hits.append((i, v))
            i += 4
        else:
            i += 1
    return hits


def rewrite_raw(data, hits, fn):
    b = bytearray(data)
    for pos, v in hits:
        struct.pack_into('<I', b, pos, fn(v))
    return bytes(b)


def remap_record_fields(rec, plugin, fn, raw_valid=None, strings=None, dst_plugin=None,
                        formid_parser=None):
    """Re-encode `rec` with every FormID passed through fn. Raw (undecoded)
    subrecords are scanned for values in `raw_valid` (a set of src-local
    FormIDs) when given. Returns (subrecords, changed, warnings)."""
    dst_plugin = dst_plugin or plugin
    warnings = []
    items = []
    changed = False
    for d in decode_record(rec, plugin):
        if d.ok:
            v = map_formids(d.value, fn)
            if strings is not None:
                v = delocalize_value(v, strings, d.sig, warnings)
            if v != d.value or (strings is not None):
                changed = True
            items.append((d.sig, v))
        else:
            data = d.raw
            if raw_valid:
                hits = scan_raw_formids(data, raw_valid)
                if hits:
                    new = rewrite_raw(data, hits, fn)
                    if new != data:
                        changed = True
                        data = new
                        warnings.append(f'{rec.sig}.{d.sig}: remapped {len(hits)} FormID-like value(s) '
                                        f'inside undecoded data (heuristic)')
            elif not getattr(fn, 'identity', True):
                if len(data) >= 4:
                    warnings.append(f'{rec.sig}.{d.sig}: undecoded subrecord copied verbatim; '
                                    f'FormIDs inside it (if any) were not remapped')
            items.append((d.sig, {'$hex': data.hex()}))
    if not changed:
        return rec.subrecords, False, warnings
    subs = encode_items(rec.sig, items, dst_plugin, record=rec, formid_parser=formid_parser,
                        sync_counters=False)
    return subs, True, warnings


def delocalize_value(v, strings, sig, warnings):
    if isinstance(v, LStr):
        if int(v) == 0:
            return ''
        t = strings.get(int(v)) if strings is not None else None
        if t is None:
            raise EspError(f'string id {int(v)} ({sig}) not found in the strings files')
        return t
    if isinstance(v, dict):
        return {k: delocalize_value(x, strings, sig, warnings) for k, x in v.items()}
    if isinstance(v, list):
        return [delocalize_value(x, strings, sig, warnings) for x in v]
    return v


def own_formids(plugin):
    own = plugin.self_index
    return {r.formid for r in plugin.records() if (r.formid >> 24) == own}


def remap_plugin(plugin, fn, raw_valid=None, header_too=True):
    """Apply fn to every FormID in the plugin (record headers, decoded fields,
    and heuristically in raw data for values in raw_valid). Returns warnings."""
    warnings = []
    for r in list(plugin.records()):
        subs, changed, w = remap_record_fields(r, plugin, fn, raw_valid)
        warnings += w
        newfid = fn(r.formid) if header_too else r.formid
        if changed:
            r._subs = subs
            r.touched()
        if newfid != r.formid:
            r.formid = newfid
    # group labels that hold FormIDs (CELL/WRLD/DIAL children)
    stack = [plugin.root]
    while stack:
        g = stack.pop()
        for c in g.children:
            if isinstance(c, Group):
                if c.gtype in (1, 6, 7, 8, 9, 10):
                    c.label = struct.pack('<I', fn(c.label_formid))
                stack.append(c)
    # TES4 ONAM (overridden temporary refs)
    hdr = plugin.header
    for s in hdr.subrecords:
        if s.sig == 'ONAM':
            n = len(s.data) // 4
            vals = struct.unpack(f'<{n}I', s.data[:n * 4])
            s.data = struct.pack(f'<{n}I', *[fn(v) for v in vals]) + s.data[n * 4:]
            hdr.touched()
    plugin.invalidate(structure=False)
    return warnings


def add_masters(plugin, names, lo=None):
    """Append masters, keeping every FormID valid (the plugin's own records
    move to the new self index). Returns the list of names actually added."""
    existing = [m.lower() for m in plugin.masters]
    new = []
    for n in names:
        if n.lower() == plugin.name.lower():
            continue
        if n.lower() not in existing and n.lower() not in [x.lower() for x in new]:
            new.append(n)
    if not new:
        return []
    old_self = plugin.self_index
    own = own_formids(plugin)
    for n in new:
        plugin.add_master(n)
    new_self = plugin.self_index
    if own or any(True for _ in plugin.records()):
        def fn(fid):
            if (fid >> 24) == old_self:
                return (new_self << 24) | (fid & 0xFFFFFF)
            return fid
        fn.identity = False
        remap_plugin(plugin, fn, raw_valid=own)
    return new


def clean_masters(plugin):
    """Remove masters that nothing references. Returns removed names."""
    used = set()
    for r in plugin.records():
        used.add(r.formid >> 24)
        for d in decode_record(r, plugin):
            if d.ok:
                for f in iter_formids(d.value):
                    if f:
                        used.add(int(f) >> 24)
    ms = plugin.masters
    keep = [i for i in range(len(ms)) if i in used]
    removed = [ms[i] for i in range(len(ms)) if i not in used]
    if not removed:
        return []
    # raw subrecords might still reference a master: refuse if any raw data
    # contains a value whose index is a removed master and looks like a FormID
    new_index = {old: new for new, old in enumerate(keep)}
    new_index[len(ms)] = len(keep)
    own = own_formids(plugin)

    def fn(fid):
        if fid == 0:
            return 0
        idx = fid >> 24
        if idx not in new_index:
            raise EspError(f'FormID {fid:08X} references removed master')
        return (new_index[idx] << 24) | (fid & 0xFFFFFF)
    fn.identity = False
    plugin.set_masters([ms[i] for i in keep])
    remap_plugin(plugin, fn, raw_valid=own)
    return removed


# ---------------------------------------------------------------------------
# placement in the group tree
# ---------------------------------------------------------------------------

def _find_child_group(parent, gtype, label):
    for c in parent.children:
        if isinstance(c, Group) and c.gtype == gtype and c.label == label:
            return c
    return None


def _ensure_child_group(container, rec, gtype):
    """The children group of CELL/WRLD/DIAL `rec`, created right after it."""
    g = child_group_of(rec)
    if g is not None:
        return g
    g = Group(struct.pack('<I', rec.formid), gtype)
    parent = rec.parent
    idx = parent.children.index(rec)
    parent.add(g, idx + 1)
    return g


def _sorted_insert(parent, group, key):
    """Insert sub-blocks in ascending label order."""
    for i, c in enumerate(parent.children):
        if isinstance(c, Group) and c.gtype == group.gtype and key(c) > key(group):
            parent.add(group, i)
            return group
    parent.add(group)
    return group


def _cell_grid(rec, plugin):
    for d in decode_record(rec, plugin):
        if d.sig == 'XCLC' and d.ok:
            return d.value['x'], d.value['y']
    return None


def place_record(dst, rec, src_ctx, lo=None, src_plugin=None):
    """Attach `rec` (already in dst's FormID space) to dst's group tree.
    src_ctx = record_context() of the source record, translated to dst ids:
    {'cell': fid, 'world': fid, 'child_type': 8|9, 'topic': fid,
     'persistent_world_cell': bool}."""
    existing = dst.find(rec.formid)
    if existing is not None and existing.parent is not None:
        g = existing.parent
        i = g.children.index(existing)
        g.children[i] = rec
        rec.parent = g
        rec.plugin = dst
        dst.invalidate(structure=False)
        return rec
    rec.plugin = dst
    if rec.sig in CELL_CHILD_TYPES:
        cell = dst.find(src_ctx['cell'])
        if cell is None:
            raise EspError('parent CELL must be copied first')
        cg = _ensure_child_group(dst, cell, 6)
        ctype = src_ctx.get('child_type', 9)
        sub = _find_child_group(cg, ctype, cg.label)
        if sub is None:
            sub = Group(cg.label, ctype)
            if ctype == 8:
                cg.add(sub, 0)
            else:
                cg.add(sub)
        sub.add(rec)
    elif rec.sig in TOPIC_CHILD_TYPES:
        dial = dst.find(src_ctx['topic'])
        if dial is None:
            raise EspError('parent DIAL must be copied first')
        _ensure_child_group(dst, dial, 7).add(rec)
    elif rec.sig == 'CELL' and src_ctx.get('world'):
        wrld = dst.find(src_ctx['world'])
        if wrld is None:
            raise EspError('parent WRLD must be copied first')
        wg = _ensure_child_group(dst, wrld, 1)
        grid = src_ctx.get('grid')
        if grid is None:   # persistent worldspace cell lives directly in the world group
            wg.add(rec, 0)
        else:
            x, y = grid
            blab = struct.pack('<hh', y // 32, x // 32)
            slab = struct.pack('<hh', y // 8, x // 8)
            blk = _find_child_group(wg, 4, blab) or wg.add(Group(blab, 4))
            sb = _find_child_group(blk, 5, slab) or blk.add(Group(slab, 5))
            sb.add(rec)
    elif rec.sig == 'CELL':
        top = dst.top_group('CELL', create=True)
        obj = rec.formid & 0xFFFFFF
        blab = struct.pack('<i', obj % 10)
        slab = struct.pack('<i', (obj // 10) % 10)
        blk = _find_child_group(top, 2, blab) or _sorted_insert(top, Group(blab, 2), lambda g: g.label_int)
        sb = _find_child_group(blk, 3, slab) or _sorted_insert(blk, Group(slab, 3), lambda g: g.label_int)
        sb.add(rec)
    else:
        dst.top_group(rec.sig, create=True).add(rec)
    dst.invalidate()
    return rec


# ---------------------------------------------------------------------------
# copying records between plugins
# ---------------------------------------------------------------------------

def referenced_owners(rec, plugin, include_self=True):
    owners = {plugin.formid_owner(rec.formid)} if include_self else set()
    for d in decode_record(rec, plugin):
        if d.ok:
            for f in iter_formids(d.value):
                if f:
                    o = plugin.formid_owner(int(f))
                    if o:
                        owners.add(o)
    owners.discard(None)
    return owners


def copy_record(lo, src, rec, dst, as_new=False, new_edid=None, with_parents=True):
    """Copy `rec` from plugin src into dst as an override (default) or as a
    brand-new record. Adds masters to dst as needed, copies the parent
    CELL/WRLD/DIAL when required. Returns (new_rec, warnings)."""
    warnings = []
    if src is dst and not as_new:
        raise EspError('source and destination are the same plugin')
    # 1. parents first, so later master additions cannot invalidate our mapping
    ctx = record_context(rec)
    parent_fids = []
    if rec.sig in CELL_CHILD_TYPES:
        if ctx.get('cell') is None:
            raise EspError(f'{rec.label()} has no parent CELL in {src.name}')
        parent_fids.append(ctx['cell'])
    elif rec.sig in TOPIC_CHILD_TYPES:
        parent_fids.append(ctx['topic'])
    elif rec.sig == 'CELL' and ctx.get('world') is not None:
        parent_fids.append(ctx['world'])
    if src is not dst:
        for pf in parent_fids:
            pr = src.find(pf)
            if pr is None:
                raise EspError(f'parent record {pf:08X} not found in {src.name}')
            fk = lo.formkey(src, pf) if lo is not None else None
            have = None
            if fk is not None:
                lf = lo.local_fid(dst, *fk)
                have = dst.find(lf) if lf is not None else None
            if have is None:
                if not with_parents:
                    raise EspError('parent record missing in destination')
                _, w2 = copy_record(lo, src, pr, dst)
                warnings += w2
    # 2. masters needed by the record itself
    if src is not dst:
        owners = referenced_owners(rec, src, include_self=not as_new)
        need = [o for o in owners if o.lower() != dst.name.lower()]
        ordered = [m for m in src.masters + [src.name] if m in need]
        ordered += [o for o in need if o not in ordered]
        added = add_masters(dst, ordered, lo)
        if added:
            warnings.append(f'added master(s) to {dst.name}: {", ".join(added)}')
        fn = mapper(src, dst)
    else:
        fn = lambda f: f        # noqa: E731
        fn.identity = True
    # 3. strings: localized source into a non-localized destination
    strings = None
    if src.is_localized and not dst.is_localized:
        strings = lo.strings_for(src) if lo is not None else None
        if strings is None:
            raise EspError(f'{src.name} is localized but its strings files were not found '
                           f'(looked for Strings/{src.name.rsplit(".", 1)[0]}_{lo.language if lo else "english"}.*STRINGS '
                           f'loose or in BSAs). Pass --data <Skyrim Data folder>.')
    raw_valid = None if getattr(fn, 'identity', False) else _valid_formids_for_scan(lo, src)
    subs, changed, w = remap_record_fields(rec, src, fn, raw_valid, strings, dst_plugin=dst)
    warnings += w
    target_fid = 0 if as_new else fn(rec.formid)
    if changed:
        new = Record(rec.sig, target_fid, rec.flags, [x.copy() for x in subs],
                     rec.version, rec.vc1, rec.vc2)
    else:
        new = rec.copy()
        new.formid = target_fid
    new.plugin = dst
    if as_new:
        new.formid = allocate_formid(dst)
        new.flags &= ~FLAG_DELETED
        if new_edid:
            set_edid(new, new_edid, dst)
        elif rec.edid:
            set_edid(new, rec.edid + 'Copy', dst)
            warnings.append(f'EditorID set to {rec.edid}Copy (pass --edid to choose one)')
    # 4. place
    dctx = {}
    if rec.sig in CELL_CHILD_TYPES:
        dctx['cell'] = fn(ctx['cell'])
        dctx['child_type'] = ctx.get('child_type', 9)
    elif rec.sig in TOPIC_CHILD_TYPES:
        dctx['topic'] = fn(ctx['topic'])
    elif rec.sig == 'CELL' and ctx.get('world') is not None:
        dctx['world'] = fn(ctx['world'])
        dctx['grid'] = _cell_grid(rec, src) if rec.parent.gtype == 5 else None
    place_record(dst, new, dctx, lo, src)
    return new, warnings


def _valid_formids_for_scan(lo, src):
    """Set of src-local FormIDs that are known to exist (for heuristic raw scan)."""
    valid = set()
    own = src.self_index
    for r in src.records():
        valid.add(r.formid)
    if lo is not None:
        for i, m in enumerate(src.masters):
            try:
                tbl = lo.names(m)
            except EspError:
                tbl = None
            if tbl:
                valid.update((i << 24) | obj for obj in tbl)
    valid.discard(0)
    return valid


def allocate_formid(plugin, count=1):
    own = plugin.self_index
    used = {r.formid & 0xFFFFFF for r in plugin.records() if (r.formid >> 24) == own}
    nxt = max(plugin.next_object_id, 0x800 if plugin.hedr_version < 1.71 or not plugin.is_esl else 0x001)
    if used:
        nxt = max(nxt, max(used) + 1)
    if nxt > 0xFFFFFF:
        raise EspError('out of FormIDs')
    plugin.set_hedr(next_object_id=nxt + count)
    return (own << 24) | nxt


def set_edid(rec, edid, plugin):
    data = edid.encode(plugin.encoding) + b'\0'
    subs = rec.subrecords
    for s in subs:
        if s.sig == 'EDID':
            s.data = data
            break
    else:
        subs.insert(0, Subrecord('EDID', data))
    rec.touched()


def new_record(plugin, sig, edid=None, fields=None, lo=None):
    """Create a brand new record of type sig in plugin."""
    if sig in CELL_CHILD_TYPES | TOPIC_CHILD_TYPES:
        raise EspError(f'creating new {sig} records needs a parent; copy an existing one with --as-new instead')
    items = []
    if edid:
        items.append(('EDID', edid))
    for item in fields or []:
        items.append(item)
    parser = lo.parser_for(plugin) if lo else None
    ctx_rec = Record(sig, 0, 0, [Subrecord('EDID', edid.encode(plugin.encoding) + b'\0')] if edid else [], 44)
    ctx_rec.plugin = plugin          # GMST values are typed by their EditorID
    subs = encode_items(sig, items, plugin, record=ctx_rec, formid_parser=parser)
    rec = Record(sig, allocate_formid(plugin), 0, subs, 44)
    rec._raw = None
    place_record(plugin, rec, {})
    return rec


# ---------------------------------------------------------------------------
# deletion
# ---------------------------------------------------------------------------

def find_references(plugin, targets):
    """Records in plugin whose decoded data references any FormID in targets.
    Returns [(record, [sig,...])]."""
    out = []
    for r in plugin.records():
        sigs = []
        try:
            dec = decode_record(r, plugin)
        except EspError:
            continue
        for d in dec:
            if d.ok:
                if any(int(f) in targets for f in iter_formids(d.value)):
                    sigs.append(d.sig)
            elif len(d.raw) >= 4 and scan_raw_formids(d.raw, targets):
                sigs.append(d.sig + '?')
        if sigs:
            out.append((r, sigs))
    return out


def remove_records(plugin, recs):
    for r in recs:
        plugin.remove(r)


def mark_deleted(plugin, rec):
    rec.flags |= FLAG_DELETED
    keep = [s for s in rec.subrecords if s.sig == 'EDID']
    rec._subs = keep
    rec.touched()


def restore_from_masters(lo, plugin, rec):
    """Give a stripped deleted override (only a header, as the Creation Kit
    writes deleted references) the fields of the latest version in the
    plugin's masters, so it can be undeleted."""
    idx = rec.formid >> 24
    if idx >= len(plugin.masters):
        raise EspError(f'{rec.label()} is not an override; nothing to restore it from')
    owner = plugin.masters[idx]
    objid = rec.formid & 0xFFFFFF
    for m in reversed(plugin.masters):
        mp = lo.get(m, required=False) if lo is not None else None
        if mp is None:
            continue
        lf = lo.local_fid(mp, objid, owner)
        src = mp.find(lf) if lf is not None else None
        if src is None or src.flags & FLAG_DELETED:
            continue
        subs, _changed, _w = remap_record_fields(src, mp, mapper(mp, plugin), None, None, dst_plugin=plugin)
        rec._subs = [x.copy() for x in subs]
        rec.touched()
        return m
    raise EspError(f'cannot find an undeleted version of {rec.label()} in the masters of {plugin.name} '
                   '(pass --data so they are found)')


def undelete_and_disable(plugin, rec):
    """xEdit-style fix for deleted references: undelete, initially disable,
    enable parent = player (opposite), move far below the world."""
    if rec.sig not in CELL_CHILD_TYPES - {'NAVM', 'LAND'}:
        raise EspError(f'{rec.sig} is not a placed reference')
    names = [m.lower() for m in plugin.masters]
    if 'skyrim.esm' not in names:
        add_masters(plugin, ['Skyrim.esm'])
        names = [m.lower() for m in plugin.masters]
    player = (names.index('skyrim.esm') << 24) | 0x14     # PlayerRef [REFR:00000014]
    rec.flags &= ~FLAG_DELETED
    rec.flags |= FLAG_INITIALLY_DISABLED
    subs = [s for s in rec.subrecords if s.sig != 'XESP']
    xesp = Subrecord('XESP', struct.pack('<IB3s', player, 1, b'\0\0\0'))
    # XESP goes before DATA (placement), after most other fields
    idx = next((i for i, s in enumerate(subs) if s.sig == 'DATA'), len(subs))
    subs.insert(idx, xesp)
    for s in subs:
        if s.sig == 'DATA' and len(s.data) >= 24:
            x, y, z, rx, ry, rz = struct.unpack_from('<6f', s.data)
            s.data = struct.pack('<6f', x, y, -30000.0, rx, ry, rz) + s.data[24:]
    rec._subs = subs
    rec.touched()


# ---------------------------------------------------------------------------
# comparison helpers
# ---------------------------------------------------------------------------

def _cmp_jsonable(v, plugin):
    """to_jsonable() with FormIDs as FormKeys whose plugin name is case-folded,
    so 'Skyrim.esm' in one master list equals 'skyrim.esm' in another."""
    if isinstance(v, FormID):
        fk = plugin.formkey(int(v))
        return f'{fk[0]:06X}:{fk[1].lower()}' if fk is not None else to_jsonable(v, plugin)
    if isinstance(v, dict):
        return {k: _cmp_jsonable(x, plugin) for k, x in v.items()}
    if isinstance(v, list):
        return [_cmp_jsonable(x, plugin) for x in v]
    return to_jsonable(v, plugin)


def normalized(rec, plugin, strings=None, fold_case=True):
    """Plugin-independent representation (FormKeys instead of local ids); with
    fold_case the plugin names in FormKeys are lower-cased (for comparing)."""
    conv = _cmp_jsonable if fold_case else to_jsonable
    out = []
    for d in decode_record(rec, plugin):
        v = d.value
        if d.ok and strings is not None:
            try:
                v = delocalize_value(v, strings, d.sig, [])
            except EspError:
                pass
        out.append((d.sig, json.dumps(conv(v, plugin), sort_keys=True, ensure_ascii=False)))
    return out


def record_flags_for_compare(rec):
    return rec.flags & ~FLAG_COMPRESSED


def _keyed(items):
    """{'SIG' / 'SIG#n': value} and the key order, for repeated subrecords."""
    seen = {}
    out = {}
    order = []
    for sig, v in items:
        n = seen.get(sig, 0)
        seen[sig] = n + 1
        k = f'{sig}#{n}' if n else sig
        out[k] = v
        order.append(k)
    return out, order


def diff_records(a, pa, b, pb, sa=None, sb=None):
    """Field-level differences between two versions of a record.
    Returns list of (sig#n, value_a, value_b)."""
    ka, oa = _keyed(normalized(a, pa, sa))
    kb, ob = _keyed(normalized(b, pb, sb))
    keys = oa + [k for k in ob if k not in ka]
    diffs = []
    if record_flags_for_compare(a) != record_flags_for_compare(b):
        diffs.append(('@flags', flags_to_names(a.flags & ~FLAG_COMPRESSED, RECORD_FLAG_NAMES),
                      flags_to_names(b.flags & ~FLAG_COMPRESSED, RECORD_FLAG_NAMES)))
    shown_a = shown_b = None
    for k in keys:
        if ka.get(k) != kb.get(k):
            if shown_a is None:      # show FormKeys as each plugin spells them
                shown_a = _keyed(normalized(a, pa, sa, fold_case=False))[0]
                shown_b = _keyed(normalized(b, pb, sb, fold_case=False))[0]
            va, vb = shown_a.get(k), shown_b.get(k)
            diffs.append((k, json.loads(va) if va else None, json.loads(vb) if vb else None))
    return diffs


def is_itm(rec, plugin, master_rec, master_plugin, lo=None):
    if record_flags_for_compare(rec) != record_flags_for_compare(master_rec):
        return False
    sa = lo.strings_for(plugin) if lo else None
    sb = lo.strings_for(master_plugin) if lo else None
    return normalized(rec, plugin, sa) == normalized(master_rec, master_plugin, sb)


def previous_version(lo, plugin, rec):
    """The version of rec this plugin overrides: the last of its masters (in
    master order) that contains it. Returns (master_plugin, record) or None."""
    fk = lo.formkey(plugin, rec.formid)
    if fk is None:
        return None
    objid, owner = fk
    best = None
    for m in plugin.masters:
        mp = lo.get(m, required=False)
        if mp is None:
            continue
        fid = lo.local_fid(mp, objid, owner)
        if fid is None:
            continue
        r = mp.find(fid)
        if r is not None:
            best = (mp, r)
    return best


# ---------------------------------------------------------------------------
# ESL
# ---------------------------------------------------------------------------

def esl_report(plugin):
    own = plugin.self_index
    new = [r for r in plugin.records() if (r.formid >> 24) == own]
    ids = sorted(r.formid & 0xFFFFFF for r in new)
    v171 = plugin.hedr_version >= 1.705
    lo_bound = 0x001 if v171 else 0x800
    out_of_range = [i for i in ids if i < lo_bound or i > 0xFFF]
    problems = []
    if len(new) > (0xFFF - lo_bound + 1):
        problems.append(f'{len(new)} new records; a light plugin can hold at most {0xFFF - lo_bound + 1}')
    if out_of_range:
        problems.append(f'{len(out_of_range)} new record(s) have object IDs outside '
                        f'{lo_bound:03X}-FFF (run: esp.py compact)')
    cells = [r for r in new if r.sig == 'CELL']
    worlds = [r for r in new if r.sig == 'WRLD']
    warn = []
    if cells:
        warn.append(f'{len(cells)} new CELL record(s): in a light plugin, new cells overridden by other plugins '
                    'lose temporary references and interior cells reload wrongly unless SSE Engine Fixes 7.0.14+ '
                    '(bESLCELLLoadBug) is installed')
    if worlds:
        warn.append(f'{len(worlds)} new WRLD record(s): light plugins can lose the landscape of new worldspaces '
                    '(no fix exists); keep it a full plugin')
    if v171:
        warn.append('header version 1.71: needs Skyrim SE 1.6.1130+ (or BEES on older games)')
    return {
        'new_records': len(new), 'min_id': ids[0] if ids else None, 'max_id': ids[-1] if ids else None,
        'eligible_as_is': not problems, 'problems': problems, 'warnings': warn,
        'flagged_esl': plugin.is_esl, 'compactable': len(new) <= (0xFFF - lo_bound + 1),
    }


def compact(plugin, start=None):
    """Renumber the plugin's own records into a contiguous range starting at
    `start` (default 0x800) and fix every reference inside the plugin."""
    own = plugin.self_index
    news = [r for r in plugin.records() if (r.formid >> 24) == own]
    if start is None:
        start = 0x800
    mapping = {}
    used_targets = set()
    nxt = start
    # keep records already in range where possible
    for r in sorted(news, key=lambda r: r.formid):
        oid = r.formid & 0xFFFFFF
        if start <= oid <= 0xFFF and oid not in used_targets:
            used_targets.add(oid)
    for r in sorted(news, key=lambda r: r.formid):
        oid = r.formid & 0xFFFFFF
        if start <= oid <= 0xFFF:
            continue
        while nxt in used_targets:
            nxt += 1
        if nxt > 0xFFF:
            raise EspError('too many records to compact into the ESL range')
        mapping[r.formid] = (own << 24) | nxt
        used_targets.add(nxt)
        nxt += 1
    if not mapping:
        return {}
    valid = set(r.formid for r in news)

    def fn(fid):
        return mapping.get(fid, fid)
    fn.identity = False
    remap_plugin(plugin, fn, raw_valid=valid)
    top = max(used_targets) + 1 if used_targets else start
    plugin.set_hedr(next_object_id=max(top, start))
    return mapping


# ---------------------------------------------------------------------------
# field paths: SIG[#n](.field|[i])*
# ---------------------------------------------------------------------------

def parse_path(path):
    import re
    m = re.match(r'^([A-Za-z0-9_]{4})(?:#(\d+))?(.*)$', path)
    if not m:
        raise EspError(f'bad field path {path!r} (examples: DATA.damage, CNTO#1.count, KWDA[0], FULL)')
    sig, occ, rest = m.group(1), m.group(2), m.group(3)
    steps = []
    for part in re.finditer(r'\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]', rest):
        steps.append(part.group(1) if part.group(1) is not None else int(part.group(2)))
    consumed = ''.join(p.group(0) for p in re.finditer(r'\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]', rest))
    if consumed != rest:
        raise EspError(f'bad field path {path!r}')
    return sig, (int(occ) if occ is not None else None), steps


def parse_value_text(text):
    """CLI value -> python: JSON if it parses, else the raw string."""
    t = text.strip()
    if t == '':
        return ''
    try:
        return json.loads(t)
    except ValueError:
        return text


def default_for(spec):
    if isinstance(spec, str):
        return {'zstr': '', 'lstr': '', 'char4': '\0\0\0\0', 'char': '\0', 'wstr': '', 'sstr': '',
                'bytes': {'$hex': ''}, 'empty': None, 'fid': None}.get(spec, 0)
    if isinstance(spec, tuple):
        return {'$hex': '00' * spec[1]}
    if isinstance(spec, Struct):
        return {f.name: _enum_default(f) for f in spec.fields}
    if isinstance(spec, Arr):
        return [default_for(spec.elem) for _ in range(spec.count or 0)]
    if isinstance(spec, BySize):
        return default_for(max(spec.variants.items())[1])
    if isinstance(spec, Custom):
        defaults = {'condition': {'function': 'GetIsID', 'param1': None, 'param2': 0, 'op': '==',
                                  'value': 1.0, 'flags': [], 'run_on': 'Subject', 'reference': None,
                                  'param3': -1},
                    'scripts': {'version': 5, 'object_format': 2, 'scripts': []},
                    'alternate_textures': []}
        if spec.name in defaults:
            return json.loads(json.dumps(defaults[spec.name]))
    raise EspError('cannot create a default value for this field; pass a full JSON value')


def _enum_default(f):
    if f.flags is not None:
        return []
    if f.enum:
        return next(iter(f.enum.values())) if 0 not in f.enum else f.enum[0]
    return default_for(f.spec)


def _spec_order(rec_sig):
    rdef = record_def(rec_sig)
    if rdef is None:
        return {}
    order = {s: i for i, s in enumerate(rdef.subs)}
    return order


def _insert_index(decoded_sigs, rec_sig, sig):
    order = _spec_order(rec_sig)
    if sig in decoded_sigs:
        return max(i for i, s in enumerate(decoded_sigs) if s == sig) + 1
    my = order.get(sig)
    if my is None:
        return len(decoded_sigs)
    idx = 0
    for i, s in enumerate(decoded_sigs):
        o = order.get(s)
        if o is not None and o <= my:
            idx = i + 1
    return idx


# subrecords that repeat together; `+=` appends at the end of the whole group
REPEAT_GROUPS = [
    {'EFID', 'EFIT', 'CTDA', 'CIS1', 'CIS2'},     # effects (+ their conditions) / conditions
    {'CNTO', 'COED'},                             # inventory entries
    {'LVLO', 'COED'},                             # leveled list entries
    {'ATKD', 'ATKE'},                             # NPC/race attacks
]


def apply_edits(lo, plugin, rec, edits, removes=(), allow_add_master=True):
    """edits: list of (path, op, value_text) with op in '=', '+=', '-='.
    removes: list of 'SIG' or 'SIG#n' subrecords to delete."""
    decoded = decode_record(rec, plugin)
    items = [[d.sig, d.value if d.ok else {'$hex': d.raw.hex()}, d.ok] for d in decoded]
    parser = lo.parser_for(plugin, allow_add_master=allow_add_master)
    rdef = record_def(rec.sig)

    def occ_indexes(sig):
        return [i for i, it in enumerate(items) if it[0] == sig]

    for path, op, text in edits:
        if path.startswith('@'):
            _edit_header(rec, path, op, text)
            continue
        sig, occ, steps = parse_path(path)
        value = parse_value_text(text)
        idxs = occ_indexes(sig)
        spec = rdef.subs.get(sig) if rdef else None
        if rdef:
            for sec in rdef.sections:
                if spec is None and sig in sec[3]:
                    spec = sec[3][sig]
        if not steps and op == '+=' and not isinstance(spec, Arr):
            # add another repeated subrecord (CNTO, LVLO, SPLO, EFID, CTDA, ...)
            if isinstance(spec, Struct) and not isinstance(value, dict):
                value = _struct_from_scalar(spec, value)
            group = set().union(*[g for g in REPEAT_GROUPS if sig in g]) if any(sig in g for g in REPEAT_GROUPS) else {sig}
            hits = [i for i, it in enumerate(items) if it[0] in group]
            pos = hits[-1] + 1 if hits else _insert_index([it[0] for it in items], rec.sig, sig)
            items.insert(pos, [sig, value, True])
            continue
        if not steps and op == '-=' and not isinstance(spec, Arr):
            target = _resolve_match(value, parser)
            hit = None
            for i in idxs:
                if _matches(items[i][1], target, parser):
                    hit = i
                    break
            if hit is None:
                raise EspError(f'no {sig} entry matching {text!r}')
            del items[hit]
            continue
        if not idxs:
            if op != '=' and not (op == '+=' and isinstance(spec, Arr)):
                raise EspError(f'{rec.sig} has no {sig} subrecord')
            if spec is None:
                raise EspError(f'{sig} is not a known field of {rec.sig}; give the full value as {{"$hex": ...}}')
            base = default_for(spec)
            pos = _insert_index([it[0] for it in items], rec.sig, sig)
            items.insert(pos, [sig, base, True])
            idxs = occ_indexes(sig)
        n = occ or 0
        if n >= len(idxs):
            raise EspError(f'{rec.sig} has only {len(idxs)} {sig} subrecord(s)')
        it = items[idxs[n]]
        if not it[2] and steps:
            raise EspError(f'{sig} is not decoded (raw); set the whole value as {{"$hex": "..."}}')
        it[1] = _set_in(it[1], steps, op, value, parser, path)
        it[2] = True
    for r in removes:
        sig, occ, steps = parse_path(r)
        idxs = occ_indexes(sig)
        if not idxs:
            raise EspError(f'{rec.sig} has no {sig}')
        targets = idxs if occ is None and len(idxs) == 1 else [idxs[occ or 0]] if (occ or 0) < len(idxs) else []
        if not targets:
            raise EspError(f'{sig}#{occ} does not exist')
        for i in sorted(targets, reverse=True):
            del items[i]
    subs = encode_items(rec.sig, [(s, v) for s, v, _ in items], plugin, record=rec,
                        formid_parser=parser)
    rec._subs = subs
    rec.touched()
    plugin.invalidate(structure=False)


def _struct_from_scalar(spec, value):
    """'IronIngot' for CNTO -> {'item': 'IronIngot', 'count': 1}."""
    out = default_for(spec)
    for f in spec.fields:
        if f.spec == 'fid':
            out[f.name] = value
            for g in spec.fields:
                if g.name == 'count':
                    out['count'] = 1
            return out
    raise EspError('give the full entry as JSON, e.g. {"item": "IronIngot", "count": 2}')


def _resolve_match(value, parser):
    if isinstance(value, str):
        try:
            return ('fid', parser(value))
        except EspError:
            return ('str', value)
    return ('val', value)


def _matches(v, target, parser):
    kind, t = target
    if kind == 'fid':
        if isinstance(v, FormID):
            return int(v) == t
        if isinstance(v, dict):
            for x in v.values():
                if isinstance(x, FormID):
                    return int(x) == t
        return False
    if kind == 'str':
        return v == t
    return v == t


def _set_in(v, steps, op, value, parser, path):
    if not steps:
        return _apply_op(v, op, value, parser, path)
    key = steps[0]
    if isinstance(key, int):
        if not isinstance(v, list):
            raise EspError(f'{path}: [{key}] used on a non-list')
        if key >= len(v):
            raise EspError(f'{path}: index {key} out of range (len {len(v)})')
        v = list(v)
        v[key] = _set_in(v[key], steps[1:], op, value, parser, path)
        return v
    if not isinstance(v, dict):
        raise EspError(f'{path}: .{key} used on a non-object')
    if key not in v and len(steps) > 1:
        raise EspError(f'{path}: no field {key!r}; available: {", ".join(v)}')
    v = dict(v)
    v[key] = _set_in(v.get(key), steps[1:], op, value, parser, path)
    return v


def _apply_op(cur, op, value, parser, path):
    if op == '=':
        return value
    if isinstance(cur, list):
        if op == '+=':
            vals = value if isinstance(value, list) else [value]
            return cur + vals
        if op == '-=':
            target = _resolve_match(value, parser)
            out = [x for x in cur if not _matches(x, target, parser)]
            if len(out) == len(cur):
                raise EspError(f'{path}: {value!r} not found')
            return out
    if isinstance(cur, (int, float)) and not isinstance(cur, FormID) and isinstance(value, (int, float)):
        return cur + value if op == '+=' else cur - value
    raise EspError(f'{path}: {op} needs a list or a number')


def _edit_header(rec, path, op, text):
    if path in ('@flags',):
        names = [x for x in text.replace(',', '|').split('|') if x.strip()]
        bits = names_to_flags(names, RECORD_FLAG_NAMES) if names else 0
        if op == '=':
            rec.flags = (rec.flags & FLAG_COMPRESSED) | bits
        elif op == '+=':
            rec.flags |= bits
        else:
            rec.flags &= ~bits
        rec.touched()
        return
    if path == '@form_version':
        rec.version = int(text, 0)
        rec.touched()
        return
    raise EspError(f'unknown header field {path} (use @flags or @form_version)')


# ---------------------------------------------------------------------------
# delocalize
# ---------------------------------------------------------------------------

def delocalize(plugin, strings):
    """Replace every localized string ID by its text and clear the flag."""
    if not plugin.is_localized:
        return 0
    count = 0
    warnings = []
    for r in list(plugin.records()):
        dec = decode_record(r, plugin)
        has = any(d.ok and _has_lstr(d.value) for d in dec)
        if not has:
            continue
        items = []
        for d in dec:
            if d.ok:
                items.append((d.sig, delocalize_value(d.value, strings, d.sig, warnings)))
            else:
                items.append((d.sig, {'$hex': d.raw.hex()}))
        r._subs = items
        count += 1
    plugin.header.flags &= ~FLAG_LOCALIZED
    plugin.header.touched()
    # encode after the flag flip so lstr fields are written as text
    for r in plugin.records():
        if r._subs and isinstance(r._subs[0], tuple):
            r._subs = encode_items(r.sig, r._subs, plugin, record=r, sync_counters=False)
            r.touched()
    return count


def _has_lstr(v):
    if isinstance(v, LStr):
        return True
    if isinstance(v, dict):
        return any(_has_lstr(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_lstr(x) for x in v)
    return False


# ---------------------------------------------------------------------------
# list merging (bashed-patch style)
# ---------------------------------------------------------------------------

# sig -> how to key entries for merging
MERGE_RULES = {
    'LVLO': 'entry',      # leveled list entries (level, reference, count)
    'CNTO': 'item',       # container/NPC inventory, keyed by item
    'SPLO': 'value',
    'PRKR': 'perk',
    'PKID': 'value',
    'LNAM': 'value',      # form list entries (FLST)
    'SNAM': 'faction',    # NPC factions
}
MERGE_ARRAYS = {'KWDA', 'INAM', 'XCLR'}   # array subrecords merged as sets


def _entry_key(sig, v):
    if MERGE_RULES.get(sig) == 'entry':
        return json.dumps(v, sort_keys=True)
    if MERGE_RULES.get(sig) == 'item':
        return v['item'] if isinstance(v, dict) else json.dumps(v)
    if MERGE_RULES.get(sig) == 'perk':
        return v['perk'] if isinstance(v, dict) else json.dumps(v)
    if MERGE_RULES.get(sig) == 'faction':
        return v['faction'] if isinstance(v, dict) else json.dumps(v)
    return json.dumps(v, sort_keys=True)


def _norm_fields(rec, plugin, strings):
    """[(sig, jsonable value)] with FormKeys, strings resolved."""
    out = []
    for d in decode_record(rec, plugin):
        v = d.value
        if d.ok and strings is not None:
            v = delocalize_value(v, strings, d.sig, [])
        out.append((d.sig, to_jsonable(v, plugin), d.ok))
    return out


def merge_versions(lo, base, overrides):
    """3-way merge of several overrides of one record against its base
    (master) version. base/overrides: (plugin, record), overrides in load
    order. Lists (leveled entries, inventory, keywords, spells, perks,
    factions, form list entries...) merge additions and removals from every
    plugin; every other field takes the value of the last plugin that changed
    it (struct fields are merged one by one). Returns (fields, report)."""
    bp, br = base
    st = lo.strings_for
    base_f = _norm_fields(br, bp, st(bp))
    ov_f = [(p, _norm_fields(r, p, st(p))) for p, r in overrides]
    win_p, win_f = ov_f[-1]
    out = [(s_, v, ok) for s_, v, ok in win_f]
    report = []
    lists = set(MERGE_RULES) | MERGE_ARRAYS
    rec_sig = br.sig

    def is_list(sig):
        if sig not in lists:
            return False
        if sig == 'SNAM' and rec_sig != 'NPC_':
            return False
        if sig == 'INAM' and rec_sig != 'OTFT':
            return False
        if sig == 'LNAM' and rec_sig != 'FLST':
            return False
        return True

    all_sigs = []
    for fields in [base_f] + [f for _, f in ov_f]:
        for s_, _, _ in fields:
            if s_ not in all_sigs:
                all_sigs.append(s_)

    for sig in all_sigs:
        if is_list(sig):
            out, line = _merge_list(sig, base_f, ov_f, out, rec_sig)
            if line:
                report.append(line)
            continue
        counts = [sum(1 for s_, _, _ in f if s_ == sig) for f in [base_f] + [f for _, f in ov_f]]
        if max(counts) > 1:
            continue        # repeated non-list subrecords (effects, conditions): winner's
        if sig in schema.COUNTERS:
            continue        # recomputed later
        bv = _single(base_f, sig)
        final = bv
        sources = {}
        for p, f in ov_f:
            v = _single(f, sig)
            if v == bv:
                continue
            if isinstance(bv, dict) and isinstance(v, dict) and isinstance(final, dict) and '$hex' not in bv:
                merged = dict(final)
                for k in set(v) | set(bv):
                    if v.get(k) != bv.get(k):
                        merged[k] = v.get(k)
                        sources[f'{sig}.{k}'] = p.name
                final = merged
            else:
                final = v
                sources[sig] = p.name
        wv = _single(win_f, sig)
        if final != wv:
            out = _replace_single(out, sig, final, rec_sig)
            took = sorted({n for n in sources.values() if n != win_p.name})
            report.append(f'{sig}: took changes from {", ".join(took) or "base"} '
                          f'({", ".join(k for k, n in sources.items() if n != win_p.name)})')
    return [(s_, v) for s_, v, _ in out], report


def _single(fields, sig):
    for s_, v, ok in fields:
        if s_ == sig:
            return v
    return None


def _replace_single(out, sig, value, rec_sig):
    if value is None:
        return [x for x in out if x[0] != sig]
    for i, x in enumerate(out):
        if x[0] == sig:
            out = list(out)
            out[i] = (sig, value, True)
            return out
    pos = _insert_index([x[0] for x in out], rec_sig, sig)
    return out[:pos] + [(sig, value, True)] + out[pos:]


def _merge_list(sig, base_f, ov_f, out, rec_sig):
    def entries(fields):
        if sig in MERGE_ARRAYS:
            vals = []
            for s_, v, ok in fields:
                if s_ == sig and ok:
                    vals += v
            return vals
        return [v for s_, v, ok in fields if s_ == sig and ok]
    b = entries(base_f)
    bkeys = [_entry_key(sig, x) for x in b]
    removed = set()
    added = []
    changed = {}
    for p, f in ov_f:
        fe = entries(f)
        fkeys = [_entry_key(sig, x) for x in fe]
        for k in bkeys:
            if k not in fkeys:
                removed.add(k)
        for k, x in zip(fkeys, fe):
            if k not in bkeys:
                if k not in [a[0] for a in added]:
                    added.append((k, x, p.name))
            elif MERGE_RULES.get(sig) in ('item', 'perk', 'faction'):
                if x != b[bkeys.index(k)]:
                    changed[k] = (x, p.name)
    result = [changed.get(k, (x, None))[0] for k, x in zip(bkeys, b) if k not in removed]
    result += [x for _, x, _ in added]
    line = None
    if removed or added or changed:
        line = (f'{sig}: base {len(b)}, +{len(added)} added, -{len(removed)} removed, '
                f'{len(changed)} changed -> {len(result)}')
    new_out = []
    done = False
    for s_, v, ok in out:
        if s_ == sig:
            if not done:
                if sig in MERGE_ARRAYS:
                    if result:
                        new_out.append((sig, result, True))
                else:
                    new_out += [(sig, x, True) for x in result]
                done = True
            continue
        new_out.append((s_, v, ok))
    if not done and result:
        pos = _insert_index([x[0] for x in new_out], rec_sig, sig)
        ins = [(sig, result, True)] if sig in MERGE_ARRAYS else [(sig, x, True) for x in result]
        new_out[pos:pos] = ins
    return new_out, line
