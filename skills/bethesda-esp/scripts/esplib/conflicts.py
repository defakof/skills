"""Whole-load-order conflict scanning.

Quick mode works from header scans only (seconds for hundreds of plugins):
which records are overridden by two or more mods, grouped by category and by
the set of plugins involved, plus dirty-edit, navmesh, EditorID and
injected-record checks. Deep mode loads the conflicting records and compares
every version with the master version to find out whose changes actually get
lost (and whether they are list entries, single fields, or real clashes).
"""

import json

from .core import Plugin, EspError, record_context
from .fields import decode_record, to_jsonable
from . import ops

# ---------------------------------------------------------------------------
# categories
# ---------------------------------------------------------------------------

CATEGORY_SIGS = [
    ('navmesh', {'NAVM', 'NAVI'}),
    ('leveled', {'LVLI', 'LVLN', 'LVSP'}),
    ('containers', {'CONT', 'OTFT', 'FLST'}),
    ('npc', {'NPC_'}),
    ('items', {'ARMO', 'WEAP', 'AMMO', 'ALCH', 'INGR', 'BOOK', 'MISC', 'KEYM', 'SLGM', 'SCRL', 'LIGH',
               'APPA', 'ARMA'}),
    ('crafting', {'COBJ'}),
    ('magic', {'SPEL', 'MGEF', 'ENCH', 'PERK', 'SHOU', 'WOOP'}),
    ('actors', {'RACE', 'CLAS', 'FACT', 'CSTY', 'VTYP', 'EQUP', 'HDPT', 'EYES', 'AVIF', 'RELA', 'ASTP'}),
    ('quests', {'QUST', 'DIAL', 'INFO', 'SCEN', 'PACK', 'SMQN', 'SMBN', 'SMEN', 'DLBR', 'DLVW', 'MESG',
                'IDLE', 'IDLM'}),
    ('cells', {'CELL', 'WRLD', 'LCTN', 'REGN', 'LGTM', 'IMGS', 'WTHR', 'CLMT', 'WATR', 'ECZN', 'LCRT',
               'ASPC', 'MUSC'}),
    ('landscape', {'LAND', 'LTEX', 'GRAS', 'TREE'}),
    ('placed', {'REFR', 'ACHR', 'PGRE', 'PMIS', 'PARW', 'PBAR', 'PBEA', 'PCON', 'PFLA', 'PHZD'}),
    ('settings', {'GMST', 'GLOB'}),
    ('keywords', {'KYWD', 'AACT'}),
]
SIG_CATEGORY = {s: cat for cat, sigs in CATEGORY_SIGS for s in sigs}

CATEGORY_INFO = {
    # label, severity of an unresolved conflict
    'navmesh': ('Navmeshes', 'high'),
    'quests': ('Quests / dialogue / AI packages', 'high'),
    'actors': ('Races, classes, factions, combat styles', 'high'),
    'npc': ('NPCs', 'medium'),
    'leveled': ('Leveled lists', 'medium'),
    'containers': ('Containers, outfits, form lists', 'medium'),
    'cells': ('Cells, worldspaces, locations, weather', 'medium'),
    'landscape': ('Landscape', 'medium'),
    'magic': ('Spells, effects, perks', 'medium'),
    'items': ('Weapons, armor and other items', 'low'),
    'crafting': ('Recipes', 'low'),
    'placed': ('Placed objects', 'low'),
    'settings': ('Game settings / globals', 'low'),
    'keywords': ('Keywords', 'low'),
    'other': ('Other records', 'low'),
}
SEVERITY_RANK = {'high': 0, 'medium': 1, 'low': 2}

# NPC subrecords that make up the face/appearance (must match FaceGen files)
NPC_VISUAL = {'PNAM', 'HCLF', 'FTST', 'QNAM', 'NAM9', 'NAMA', 'TINI', 'TINC', 'TINV', 'TIAS', 'WNAM',
              'ANAM', 'NAM6', 'NAM7'}

COUNTER_SIGS = {'KSIZ', 'COCT', 'LLCT', 'SPCT', 'PRKZ', 'CITC'}

UNOFFICIAL_PATCHES = {'unofficial skyrim special edition patch.esp': 'USSEP'}


def category_of(sig):
    return SIG_CATEGORY.get(sig, 'other')


# ---------------------------------------------------------------------------
# index
# ---------------------------------------------------------------------------

class RecordVersion:
    __slots__ = ('entry', 'fid', 'sig', 'flags')

    def __init__(self, entry, fid, sig, flags):
        self.entry = entry
        self.fid = fid
        self.sig = sig
        self.flags = flags


class Conflict:
    """One record that two or more non-official plugins override."""
    __slots__ = ('key', 'owner', 'objid', 'sig', 'versions', 'overriders', 'winner', 'patched', 'deep')

    def __init__(self, key, owner, objid, sig, versions):
        self.key = key
        self.owner = owner
        self.objid = objid
        self.sig = sig
        self.versions = versions              # every version, load order
        self.overriders = []                  # non-official versions that override (not the defining plugin)
        self.winner = versions[-1]
        self.patched = False                  # winner lists all other overriders as (transitive) masters
        self.deep = None

    @property
    def formkey(self):
        return f'{self.objid:06X}:{self.owner}'

    @property
    def category(self):
        return category_of(self.sig)


class Scanner:
    def __init__(self, model):
        self.model = model
        self.order = model.effective_order()
        self.pos = {e.low: i for i, e in enumerate(self.order)}
        self.by_low = {e.low: e for e in self.order}
        self.owner_names = []               # global owner id -> name
        self._owner_id = {}
        self.versions = {}                  # key -> [RecordVersion]
        self.defined = {}                   # owner low -> set(objid) (from scans of that owner)
        self._masters_closure = {}
        self._build()

    def owner_id(self, name):
        low = name.lower()
        i = self._owner_id.get(low)
        if i is None:
            i = self._owner_id[low] = len(self.owner_names)
            self.owner_names.append(name)
        return i

    def _build(self):
        for e in self.order:
            s = e.scan
            if s is None:
                continue
            ids = [self.owner_id(m) for m in s.masters] + [self.owner_id(s.name)]
            own = s.self_index
            defined = set()
            tbl = s.sig_table
            for fid, si, fl in zip(s.formids, s.sig_ids, s.rflags):
                idx = fid >> 24
                if idx > own:
                    continue
                obj = fid & 0xFFFFFF
                if idx == own:
                    defined.add(obj)
                key = (ids[idx] << 24) | obj
                lst = self.versions.get(key)
                v = RecordVersion(e, fid, tbl[si], fl)
                if lst is None:
                    self.versions[key] = [v]
                elif lst[-1].entry is not e:
                    lst.append(v)
            self.defined[e.low] = defined

    def key_owner(self, key):
        return self.owner_names[key >> 24], key & 0xFFFFFF

    def masters_closure(self, e):
        """All (transitive) masters of an entry, lowercase."""
        c = self._masters_closure.get(e.low)
        if c is not None:
            return c
        c = set()
        stack = list(e.scan.masters) if e.scan else []
        while stack:
            m = stack.pop().lower()
            if m in c:
                continue
            c.add(m)
            me = self.by_low.get(m)
            if me is not None and me.scan is not None:
                stack.extend(me.scan.masters)
        self._masters_closure[e.low] = c
        return c

    # -- record conflicts -------------------------------------------------------
    def conflicts(self, only=None, types=None):
        out = []
        only = {o.lower() for o in only} if only else None
        for key, vers in self.versions.items():
            if len(vers) < 2:
                continue
            owner, obj = self.key_owner(key)
            ol = owner.lower()
            overriders = [v for v in vers if not v.entry.implicit and v.entry.low != ol]
            if len(overriders) < 2:
                continue
            sig = vers[0].sig
            if types and sig not in types:
                continue
            if only and not any(v.entry.low in only for v in vers):
                continue
            c = Conflict(key, owner, obj, sig, vers)
            c.overriders = overriders
            w = c.winner.entry
            mc = self.masters_closure(w)
            c.patched = all(v.entry is w or v.entry.low in mc for v in overriders)
            out.append(c)
        out.sort(key=lambda c: (SEVERITY_RANK[CATEGORY_INFO.get(c.category, ('', 'low'))[1]], c.sig, c.key))
        return out

    # -- other checks --------------------------------------------------------------
    def dirty(self):
        """{plugin: {'udr': n, 'deleted_navmesh': n}} from header flags."""
        out = {}
        for e in self.order:
            s = e.scan
            if s is None or e.implicit:
                continue
            udr = len(s.deleted_refs)
            dnav = len(s.deleted_navmeshes)
            if udr or dnav:
                out[e.name] = {'udr': udr, 'deleted_navmesh': dnav}
        return out

    def navmesh_cells(self):
        """Cells that receive NAVM records from two or more non-official plugins
        (even when the NAVM FormIDs differ)."""
        cells = {}
        for e in self.order:
            s = e.scan
            if s is None or e.implicit or not s.navm_cells:
                continue
            ids = [self.owner_id(m) for m in s.masters] + [self.owner_id(s.name)]
            for navm, cell in s.navm_cells.items():
                idx = cell >> 24
                if idx >= len(ids):
                    continue
                key = (ids[idx] << 24) | (cell & 0xFFFFFF)
                cells.setdefault(key, []).append(e)
        out = []
        for key, ents in cells.items():
            uniq = []
            for e in ents:
                if e not in uniq:
                    uniq.append(e)
            if len(uniq) >= 2:
                owner, obj = self.key_owner(key)
                out.append((f'{obj:06X}:{owner}', uniq))
        return out

    def edid_duplicates(self, include_official=True):
        seen = {}
        for e in self.order:
            s = e.scan
            if s is None:
                continue
            if e.implicit and not include_official:
                continue
            for obj, edid in s.new_edids.items():
                seen.setdefault(edid.lower(), []).append((e, obj, edid))
        out = []
        for low, lst in seen.items():
            if len(lst) < 2:
                continue
            if all(x[0].implicit for x in lst):
                continue
            out.append((lst[0][2], [(x[0].name, x[1]) for x in lst]))
        return out

    def injected(self):
        """Records that use a master's FormID space without existing in that
        master. Returns (injections, collisions)."""
        inj = {}
        for key, vers in self.versions.items():
            owner, obj = self.key_owner(key)
            oe = self.by_low.get(owner.lower())
            if oe is None or oe.scan is None:
                continue
            if obj in self.defined.get(oe.low, ()):
                continue
            for v in vers:
                if v.entry is not oe:
                    inj.setdefault(key, []).append(v)
        injections = []
        collisions = []
        for key, vers in inj.items():
            owner, obj = self.key_owner(key)
            ents = []
            for v in vers:
                if v.entry not in [x.entry for x in ents]:
                    ents.append(v)
            injections.append((f'{obj:06X}:{owner}', ents))
            # several plugins injecting the same id without depending on each other
            for i, a in enumerate(ents):
                for b in ents[i + 1:]:
                    if a.entry.low not in self.masters_closure(b.entry) and \
                            b.entry.low not in self.masters_closure(a.entry):
                        collisions.append((f'{obj:06X}:{owner}', [x.entry.name for x in ents],
                                           sorted({x.sig for x in ents})))
                        break
                else:
                    continue
                break
        return injections, collisions

    def official_reverts(self, conflicts_only=False):
        """Overrides that probably undo fixes from Update.esm/DLC or the
        Unofficial Patch: the mod overrides a record that such a plugin also
        changed, loads after it, but doesn't have it as a master."""
        out = {}
        for key, vers in self.versions.items():
            fixers = [v for v in vers if v.entry.implicit and v.entry.low != vers[0].entry.low] + \
                     [v for v in vers if v.entry.low in UNOFFICIAL_PATCHES]
            if not fixers:
                continue
            for v in vers:
                e = v.entry
                if e.implicit or e.low in UNOFFICIAL_PATCHES:
                    continue
                mc = self.masters_closure(e)
                missed = [f.entry.name for f in fixers
                          if f.entry.low not in mc and self.pos[f.entry.low] < self.pos[e.low]]
                if missed:
                    d = out.setdefault((e.name, tuple(missed)), [])
                    d.append(key)
        return out


# ---------------------------------------------------------------------------
# deep comparison
# ---------------------------------------------------------------------------

class DeepComparer:
    """Loads plugins on demand and compares record versions field by field."""

    def __init__(self, scanner, lo_resolver):
        self.scanner = scanner
        self.lo = lo_resolver               # esplib.loadorder.LoadOrder (strings, names)
        self.plugins = {}

    def plugin(self, entry):
        p = self.plugins.get(entry.low)
        if p is None:
            p = Plugin.load(entry.path)
            p.name = entry.name
            self.plugins[entry.low] = p
            self.lo.plugins[entry.low] = p
        return p

    def fields(self, v):
        p = self.plugin(v.entry)
        r = p.find(v.fid)
        if r is None:
            return None, None
        st = self.lo.strings_for(p) if p.is_localized else None
        out = {}
        for d in decode_record(r, p):
            val = d.value
            if d.ok and st is not None:
                try:
                    val = ops.delocalize_value(val, st, d.sig, [])
                except EspError:
                    pass
            out.setdefault(d.sig, []).append(json.dumps(to_jsonable(val, p), sort_keys=True, ensure_ascii=False))
        return out, r.flags & ~0x40000

    def base_for(self, c, v):
        """The version plugin v started from: the last earlier version that v
        can see through its masters (else the defining plugin's version)."""
        mc = self.scanner.masters_closure(v.entry)
        base = None
        for x in c.versions:
            if x is v:
                break
            if x.entry.low in mc:
                base = x
        if base is None:
            for x in c.versions:
                if x.entry.low == c.owner.lower():
                    base = x
        return base

    def compare(self, c):
        win, wflags = self.fields(c.winner)
        if win is None:
            return {'status': 'unknown', 'losers': [], 'npc': None}
        losers = []
        all_same = True
        for v in c.overriders:
            if v is c.winner:
                continue
            f, fl = self.fields(v)
            if f is None:
                continue
            if f != win or fl != wflags:
                all_same = False
            bver = self.base_for(c, v)
            base, bflags = self.fields(bver) if bver is not None else ({}, fl)
            if base is None:
                base, bflags = {}, fl
            lost = []      # (sig, kind, detail)
            for sig in sorted(set(f) | set(base)):
                if sig in COUNTER_SIGS:
                    continue        # derived from the lists they count
                pv, bv, wv = f.get(sig, []), base.get(sig, []), win.get(sig, [])
                if pv == bv:
                    continue
                if sig in ops.MERGE_RULES or sig in ops.MERGE_ARRAYS:
                    pe, be, we = _entries(sig, pv), _entries(sig, bv), _entries(sig, wv)
                    added = [x for x in pe if x not in be and x not in we]
                    removed = [x for x in be if x not in pe and x in we]
                    if added or removed:
                        lost.append((sig, 'list', f'+{len(added)} -{len(removed)} entries not in the winner'))
                    continue
                if wv == pv:
                    continue
                structs = _single_dicts(pv, bv, wv)
                if structs is not None:
                    p, b, w = structs
                    for k in p:
                        if k.startswith('_') or p.get(k) == b.get(k) or w.get(k) == p.get(k):
                            continue
                        kind = 'reverted' if w.get(k) == b.get(k) else 'clash'
                        lost.append((f'{sig}.{k}', kind, f'{b.get(k)!r} -> {p.get(k)!r}, winner has {w.get(k)!r}'))
                    continue
                kind = 'reverted' if wv == bv else 'clash'
                lost.append((sig, kind, _value_detail(pv, bv, wv)))
            if fl != bflags and wflags == bflags:
                lost.append(('@flags', 'reverted', 'record header flags'))
            if lost:
                losers.append({'plugin': v.entry.name, 'lost': lost})
        if all_same:
            status = 'identical'
        elif not losers:
            status = 'resolved'
        else:
            kinds = {k for l in losers for _, k, _ in l['lost']}
            status = 'clash' if 'clash' in kinds else ('lists' if kinds == {'list'} else 'forwardable')
        npc_visual = None
        if c.sig == 'NPC_' and losers:
            sigs = {s.split('.')[0] for l in losers for s, _, _ in l['lost']}
            npc_visual = 'visual' if sigs <= NPC_VISUAL else ('mixed' if sigs & NPC_VISUAL else 'stats')
        return {'status': status, 'losers': losers, 'npc': npc_visual}


def _single_dicts(pv, bv, wv):
    try:
        if len(pv) == 1 and len(bv) == 1 and len(wv) == 1:
            p, b, w = json.loads(pv[0]), json.loads(bv[0]), json.loads(wv[0])
            if isinstance(p, dict) and isinstance(b, dict) and isinstance(w, dict) and '$hex' not in p:
                return p, b, w
    except ValueError:
        pass
    return None


def _value_detail(pv, bv, wv):
    def short(vals):
        if not vals:
            return 'absent'
        t = ', '.join(vals)
        return t if len(t) <= 60 else t[:57] + '...'
    return f'{short(bv)} -> {short(pv)}, winner has {short(wv)}'


def _entries(sig, vals):
    """List-like subrecord values -> list of entry keys."""
    out = []
    for v in vals:
        x = json.loads(v)
        if sig in ops.MERGE_ARRAYS and isinstance(x, list):
            out += [json.dumps(i, sort_keys=True) for i in x]
        else:
            out.append(ops._entry_key(sig, x) if isinstance(x, dict) else json.dumps(x, sort_keys=True))
    return out


