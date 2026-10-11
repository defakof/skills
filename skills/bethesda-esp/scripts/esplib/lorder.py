"""Load-order model for Skyrim SE: where the order comes from (plugins.txt,
MO2 profiles, explicit lists), what the game actually does with it
(hardcoded plugins, Creation Club, master partition, light plugins), hard-rule
validation, and a LOOT-style sort that changes the current order as little as
possible.

Only plugins (.esp/.esm/.esl) are considered here; BSA archives are not.
"""

import os
import re

from .core import EspError
from .scan import scan_file

# Always loaded first, in this order, when present (the game forces them).
HARDCODED = ['Skyrim.esm', 'Update.esm', 'Dawnguard.esm', 'HearthFires.esm', 'Dragonborn.esm']
HARDCODED_LOW = [h.lower() for h in HARDCODED]
# Present since game 1.6.1130 (Creations update); implicitly active like CC plugins.
RESOURCE_PACK = '_ResourcePack.esl'

PLUGIN_EXTS = ('.esp', '.esm', '.esl')

# Generated / "load last" plugins recognised by name (lowercase regex).
LATE_LOADERS = [
    (r'^bashed patch(, ?\d+)?\.esp$', 'Wrye Bash Bashed Patch'),
    (r'^smashed patch.*\.esp$', 'Mator Smash patch'),
    (r'^synthesis.*\.esp$', 'Synthesis output'),
    (r'^zpatch.*\.esp$', 'generated patch'),
    (r'^dyndolod\.esp$', 'DynDOLOD output'),
    (r'^dyndolod\.esm$', 'DynDOLOD output'),
    (r'^occlusion\.esp$', 'DynDOLOD/xLODGen occlusion'),
    (r'^grass ?cache.*\.esp$', 'grass cache helper'),
]


def is_plugin_name(name):
    n = name.lower()
    if n.endswith('.ghost'):
        n = n[:-6]
    return n.endswith(PLUGIN_EXTS)


def late_loader_reason(name):
    n = name.lower()
    for rx, why in LATE_LOADERS:
        if re.match(rx, n):
            return why
    return None


# ---------------------------------------------------------------------------
# reading load-order files
# ---------------------------------------------------------------------------

def _read_lines(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        out.append(line)
    return out


def read_plugins_txt(path):
    """[(name, active)] from a Skyrim SE / MO2 plugins.txt ('*' = active)."""
    out = []
    for line in _read_lines(path):
        active = line.startswith('*')
        name = line.lstrip('*').strip()
        if is_plugin_name(name):
            out.append((name, active))
    return out


def read_loadorder_txt(path):
    return [line for line in _read_lines(path) if is_plugin_name(line)]


def read_ccc(path):
    return [line for line in _read_lines(path) if is_plugin_name(line)]


def read_mo2_modlist(path):
    """[(mod name, enabled)] from MO2 modlist.txt, LOWEST priority first.
    (The file lists the highest priority mod first; separators end in _separator.)"""
    mods = []
    for line in _read_lines(path):
        if line[0] in '+-*':
            name = line[1:].strip()
            if name.endswith('_separator'):
                continue
            mods.append((name, line[0] in '+*'))
    mods.reverse()
    return mods


def default_plugins_txt_candidates():
    """Likely plugins.txt locations for Steam / GOG / Epic installs (Windows)."""
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        return []
    names = ['Skyrim Special Edition', 'Skyrim Special Edition GOG', 'Skyrim Special Edition EPIC',
             'Skyrim Special Edition MS', 'Skyrim VR']
    return [os.path.join(base, n, 'plugins.txt') for n in names]


def _mo2_ini_paths(profile_dir):
    """(game Data dir, mods dir, overwrite dir) from ModOrganizer.ini, if found."""
    inst = os.path.abspath(os.path.join(profile_dir, '..', '..'))
    ini = os.path.join(inst, 'ModOrganizer.ini')
    game = mods = overwrite = None
    base = inst
    if os.path.isfile(ini):
        for line in _read_lines(ini):
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip().lower()
            v = v.strip()
            m = re.match(r'@ByteArray\((.*)\)', v)
            if m:
                v = m.group(1)
            v = v.replace('\\\\', '\\')
            if k == 'gamepath':
                game = os.path.join(v, 'Data')
            elif k in ('settings\\base_directory', 'base_directory'):
                base = v
            elif k in ('settings\\mod_directory', 'mod_directory'):
                mods = v
            elif k in ('settings\\overwrite_directory', 'overwrite_directory'):
                overwrite = v
    mods = mods or os.path.join(base, 'mods')
    overwrite = overwrite or os.path.join(base, 'overwrite')
    for tok in ('%BASE_DIR%', '%base_dir%'):
        mods = mods.replace(tok, base)
        overwrite = overwrite.replace(tok, base)
    return game, mods, overwrite


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------

class Entry:
    __slots__ = ('name', 'path', 'active', 'listed', 'implicit', 'source', 'scan', 'scan_error')

    def __init__(self, name, path=None, active=True, listed=None, implicit=None, source=None):
        self.name = name
        self.path = path
        self.active = active
        self.listed = listed          # position in the user's list (None = not listed)
        self.implicit = implicit      # 'hardcoded' | 'cc' | None
        self.source = source          # MO2 mod name, folder...
        self.scan = None
        self.scan_error = None

    @property
    def low(self):
        return self.name.lower()

    def __repr__(self):
        return f'<Entry {self.name} {"on" if self.active else "off"}>'


class Issue:
    LEVELS = ('error', 'warning', 'info')

    def __init__(self, level, code, plugin, message, fix=None, related=None):
        self.level = level
        self.code = code
        self.plugin = plugin
        self.message = message
        self.fix = fix
        self.related = related or []

    def as_dict(self):
        d = {'level': self.level, 'code': self.code, 'plugin': self.plugin, 'message': self.message}
        if self.fix:
            d['fix'] = self.fix
        if self.related:
            d['related'] = self.related
        return d


class LoadOrderModel:
    """Everything about one load order. Build with from_sources()."""

    def __init__(self):
        self.entries = []          # in the order the user's files list them (implicit first)
        self.search_dirs = []      # (dir, label) highest priority first
        self.data_dir = None
        self.source_desc = ''
        self.issues = []
        self.ccc = []

    # -- construction ------------------------------------------------------
    @classmethod
    def from_sources(cls, plugins=None, data=None, plugins_txt=None, loadorder_txt=None,
                     mo2_profile=None, mods_dir=None, ccc=None, scan=True, use_cache=True,
                     auto=True):
        lo = cls()
        listed = []          # [(name, active)]
        if mo2_profile:
            prof = os.path.abspath(mo2_profile)
            game, mods, overwrite = _mo2_ini_paths(prof)
            data = data or game
            mods_dir = mods_dir or mods
            modlist = os.path.join(prof, 'modlist.txt')
            if os.path.isfile(modlist) and mods_dir and os.path.isdir(mods_dir):
                if overwrite and os.path.isdir(overwrite):
                    lo.search_dirs.append((overwrite, 'Overwrite'))
                for mod, enabled in reversed(read_mo2_modlist(modlist)):
                    if enabled:
                        d = os.path.join(mods_dir, mod)
                        if os.path.isdir(d):
                            lo.search_dirs.append((d, mod))
            pt = os.path.join(prof, 'plugins.txt')
            lt = os.path.join(prof, 'loadorder.txt')
            plugins_txt = plugins_txt or (pt if os.path.isfile(pt) else None)
            loadorder_txt = loadorder_txt or (lt if os.path.isfile(lt) else None)
            lo.source_desc = f'MO2 profile {prof}'
        if data:
            lo.data_dir = os.path.abspath(data)
            lo.search_dirs.append((lo.data_dir, 'Data'))
        if plugins:
            # explicit list: files or names, in load order, all active
            for p in plugins:
                if os.path.isfile(p):
                    d = os.path.dirname(os.path.abspath(p))
                    if (d, 'Data') not in lo.search_dirs and all(d != x for x, _ in lo.search_dirs):
                        lo.search_dirs.append((d, os.path.basename(d) or d))
                    listed.append((os.path.basename(p), True))
                else:
                    listed.append((p, True))
            lo.source_desc = lo.source_desc or 'command-line list'
        else:
            if not plugins_txt and auto:
                for cand in ([os.path.join(lo.data_dir, 'plugins.txt')] if lo.data_dir else []) + \
                        default_plugins_txt_candidates():
                    if os.path.isfile(cand):
                        plugins_txt = cand
                        break
            if plugins_txt:
                listed = read_plugins_txt(plugins_txt)
                lo.source_desc = lo.source_desc or f'plugins.txt {plugins_txt}'
                if loadorder_txt and os.path.isfile(loadorder_txt):
                    # loadorder.txt has the full order (inactive too); plugins.txt the active set
                    active = {n.lower() for n, a in listed if a}
                    listed = [(n, n.lower() in active) for n in read_loadorder_txt(loadorder_txt)]
            elif lo.data_dir:
                names = sorted(n for n in os.listdir(lo.data_dir) if is_plugin_name(n))
                listed = [(n[:-6] if n.lower().endswith('.ghost') else n, not n.lower().endswith('.ghost'))
                          for n in names]
                lo.source_desc = f'all plugins in {lo.data_dir} (no plugins.txt found: order unknown)'
                lo.issues.append(Issue('warning', 'no-plugins-txt', None,
                                       'No plugins.txt given or found, so the real load order is unknown; '
                                       'plugins are listed alphabetically.',
                                       'Pass --plugins-txt (Steam: %LOCALAPPDATA%\\Skyrim Special Edition\\plugins.txt) '
                                       'or --mo2 <profile folder>.'))
            else:
                raise EspError('no load order given: pass plugin files, --data, --plugins-txt or --mo2')
        # Creation Club list
        if ccc is None and lo.data_dir:
            cand = os.path.join(os.path.dirname(lo.data_dir), 'Skyrim.ccc')
            ccc = cand if os.path.isfile(cand) else None
        lo.ccc = read_ccc(ccc) if ccc and os.path.isfile(ccc) else []
        lo._build_entries(listed)
        if scan:
            lo.scan_all(use_cache)
        return lo

    def find_path(self, name):
        low = name.lower()
        for d, label in self.search_dirs:
            for cand in (name, name + '.ghost'):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    return p, label
            try:
                for n in os.listdir(d):
                    nl = n.lower()
                    if nl == low or nl == low + '.ghost':
                        return os.path.join(d, n), label
            except OSError:
                pass
        return None, None

    def _build_entries(self, listed):
        seen = {}
        entries = []
        # implicit plugins: hardcoded, then _ResourcePack.esl / CC in Skyrim.ccc order
        implicit = [(h, 'hardcoded') for h in HARDCODED] + [(RESOURCE_PACK, 'cc')] + \
                   [(c, 'cc') for c in self.ccc if c.lower() != RESOURCE_PACK.lower()]
        for name, kind in implicit:
            path, label = self.find_path(name)
            if path is None and kind == 'cc':
                continue
            if name.lower() in seen:
                continue
            e = Entry(name, path, True, None, kind, label)
            seen[name.lower()] = e
            entries.append(e)
        dup = set()
        for i, (name, active) in enumerate(listed):
            low = name.lower()
            if low in seen:
                e = seen[low]
                if e.listed is None:
                    e.listed = i
                    if e.implicit is None:
                        e.active = active
                else:
                    dup.add(name)
                continue
            path, label = self.find_path(name)
            e = Entry(name, path, active, i, None, label)
            seen[low] = e
            entries.append(e)
        for name in sorted(dup):
            self.issues.append(Issue('warning', 'duplicate-entry', name,
                                     f'{name} is listed more than once in the load order file'))
        self.entries = entries

    def scan_all(self, use_cache=True):
        for e in self.entries:
            if e.path and (e.active or e.implicit):
                try:
                    e.scan = scan_file(e.path, use_cache)
                except (EspError, OSError) as ex:
                    e.scan_error = str(ex)

    # -- views ---------------------------------------------------------------
    def by_name(self):
        return {e.low: e for e in self.entries}

    def active(self):
        return [e for e in self.entries if (e.active or e.implicit) and e.path]

    def effective_order(self):
        """What the game loads, in order: hardcoded, CC/_ResourcePack, then the
        listed active plugins with the master partition (ESM-flagged or
        .esm/.esl) moved before regular plugins."""
        act = self.active()
        hard = sorted([e for e in act if e.implicit == 'hardcoded'], key=lambda e: HARDCODED_LOW.index(e.low))
        cc = [e for e in act if e.implicit == 'cc']
        rest = [e for e in act if not e.implicit]
        rest.sort(key=lambda e: e.listed if e.listed is not None else 10 ** 6)
        masters = [e for e in rest if self.is_master_like(e)]
        regular = [e for e in rest if not self.is_master_like(e)]
        return hard + cc + masters + regular

    @staticmethod
    def is_master_like(e):
        if e.scan is not None:
            return e.scan.is_master_like
        return e.name.lower().endswith(('.esm', '.esl'))

    @staticmethod
    def is_light(e):
        if e.scan is not None:
            return e.scan.is_light
        return e.name.lower().endswith('.esl')

    def load_indices(self, order=None):
        """{lower name: 'NN' or 'FE:xxx'} for the given (effective) order."""
        out = {}
        full = light = 0
        for e in order or self.effective_order():
            if self.is_light(e):
                out[e.low] = f'FE:{light:03X}'
                light += 1
            else:
                out[e.low] = f'{full:02X}'
                full += 1
        return out

    def official(self, e):
        return e.implicit is not None

    # -- validation -----------------------------------------------------------
    def validate(self):
        issues = list(self.issues)
        order = self.effective_order()
        pos = {e.low: i for i, e in enumerate(order)}
        names = self.by_name()
        # files listed but missing
        for e in self.entries:
            if e.active and not e.path and not e.implicit:
                issues.append(Issue('warning', 'not-found', e.name,
                                    f'{e.name} is active in the load order file but the file was not found',
                                    'Install it, or untick it if it was removed.'))
            if e.scan_error:
                issues.append(Issue('error', 'unreadable', e.name, f'{e.name} could not be read: {e.scan_error}',
                                    'Re-download the mod; the plugin file is damaged or not a Skyrim plugin.'))
        for h in HARDCODED[:2]:
            if h.lower() not in names or not names[h.lower()].path:
                issues.append(Issue('error', 'missing-base-master', h, f'{h} was not found in the Data folder',
                                    'Point --data at the game Data folder (or verify game files).'))
        n_full = n_light = 0
        for e in order:
            s = e.scan
            if s is None:
                continue
            if self.is_light(e):
                n_light += 1
            else:
                n_full += 1
            # masters
            for m in s.masters:
                me = names.get(m.lower())
                if me is None or not me.path:
                    issues.append(Issue('error', 'missing-master', e.name,
                                        f'{e.name} requires {m}, which is not installed (the game will crash on start)',
                                        f'Install {m} (check the mod page requirements) or disable {e.name}.',
                                        [m]))
                elif not (me.active or me.implicit):
                    issues.append(Issue('error', 'inactive-master', e.name,
                                        f'{e.name} requires {m}, which is installed but not active (crash on start)',
                                        f'Activate {m} or disable {e.name}.', [m]))
                elif pos.get(m.lower(), -1) > pos[e.low]:
                    if self.is_master_like(e) and not self.is_master_like(me):
                        msg = (f'{e.name} is a master-flagged plugin but depends on the regular plugin {m}; '
                               f'the game always loads it before {m}')
                        fix = f'Ask the author / remove the ESM flag from {e.name}, or ESM-flag {m}.'
                    else:
                        msg = f'{e.name} loads before its master {m}'
                        fix = f'Move {e.name} below {m} (see the suggested order).'
                    issues.append(Issue('error', 'master-order', e.name, msg, fix, [m]))
            # header / format
            if s.hedr_version < 1.69 and not e.implicit:
                issues.append(Issue('warning', 'le-header', e.name,
                                    f'{e.name} has header version {s.hedr_version:.2f}: a Skyrim LE (Oldrim) plugin '
                                    'that was not re-saved for Special Edition',
                                    'Open and save it once in the SE Creation Kit (or check for an SE version of the mod).'))
            elif s.old_form_records and len(s.formids) and not e.implicit:
                frac = s.old_form_records / len(s.formids)
                if frac >= 0.5:
                    issues.append(Issue('warning', 'le-records', e.name,
                                        f'{e.name}: {s.old_form_records} of {len(s.formids)} records have form '
                                        'version < 44 (Skyrim LE format, not converted)',
                                        'Re-save it in the SE Creation Kit; LE sound/record data can misbehave in SE.'))
            if s.is_light and not e.implicit:
                own_ids = s.new_ids()
                lo_bound = 0x001 if s.hedr_version >= 1.705 else 0x800
                bad = [i for i in own_ids if i < lo_bound or i > 0xFFF]
                if bad:
                    issues.append(Issue('error', 'esl-range', e.name,
                                        f'{e.name} is a light plugin but {len(bad)} new record(s) have object IDs '
                                        f'outside {lo_bound:03X}-FFF (records will collide or break)',
                                        f'Compact it (esp compact {e.name}) or remove the ESL flag.'))
                if s.hedr_version >= 1.705 and own_ids and min(own_ids) < 0x800:
                    issues.append(Issue('info', 'esl-171', e.name,
                                        f'{e.name} uses object IDs below 0x800 (header 1.71): needs Skyrim 1.6.1130+ '
                                        'or Backported Extended ESL Support (BEES)'))
                new_cells = sum(1 for fid, sig, _ in s.records() if sig == 'CELL' and (fid >> 24) == s.self_index)
                if new_cells:
                    issues.append(Issue('warning', 'esl-new-cell', e.name,
                                        f'{e.name} is a light plugin that adds {new_cells} new CELL record(s); '
                                        'new cells in light plugins can lose their changes (reset) in game',
                                        'Keep new cells in a full (non-ESL) plugin.'))
        if n_full > 254:
            issues.append(Issue('error', 'too-many-plugins', None,
                                f'{n_full} full (non-light) plugins are active; the game supports 254',
                                'ESL-flag eligible plugins (esp eslify), merge small plugins, or remove some.'))
        elif n_full > 240:
            issues.append(Issue('warning', 'near-plugin-limit', None,
                                f'{n_full} of 254 full plugin slots used',
                                'ESL-flag eligible plugins (esp eslify) to free slots.'))
        if n_light > 4096:
            issues.append(Issue('error', 'too-many-light', None, f'{n_light} light plugins active; limit is 4096'))
        # partition: ESM-flagged listed after regular plugins
        listed_rest = sorted((e for e in order if not e.implicit and e.listed is not None), key=lambda e: e.listed)
        seen_regular = None
        for e in listed_rest:
            if not self.is_master_like(e):
                seen_regular = seen_regular or e
            elif seen_regular is not None:
                issues.append(Issue('info', 'master-partition', e.name,
                                    f'{e.name} is master-flagged (ESM/.esl) but listed after regular plugins such as '
                                    f'{seen_regular.name}; the game loads it earlier than listed',
                                    'Harmless, but sort it with the other masters to keep the list honest.'))
        self.validation = issues
        return issues

    # -- sorting ---------------------------------------------------------------
    def overlap_index(self):
        """{global record key: [entry, ...]} for overridden records (active, scanned)."""
        idx = {}
        gid = {}
        for e in self.effective_order():
            s = e.scan
            if s is None:
                continue
            own = s.self_index
            ms = [m.lower() for m in s.masters]
            mids = [gid.setdefault(m, len(gid)) for m in ms]
            for fid in s.formids:
                i = fid >> 24
                if i >= own:
                    continue
                key = (mids[i] << 24) | (fid & 0xFFFFFF)
                lst = idx.get(key)
                if lst is None:
                    idx[key] = [e]
                elif lst[-1] is not e:
                    lst.append(e)
        return idx

    def sort(self, rules=None, use_overlap=True):
        """Suggested order: hard rules first, then rules/groups, then LOOT's
        overlap rule, everything else as currently ordered. Returns
        (order, moves, notes) where moves = [(entry, [reasons])]."""
        cur = self.effective_order()
        hard = [e for e in cur if e.implicit]
        masters = [e for e in cur if not e.implicit and self.is_master_like(e)]
        regular = [e for e in cur if not e.implicit and not self.is_master_like(e)]
        rules = rules or {}
        notes = []
        names = {e.low: e for e in cur}
        override_count = {e.low: (e.scan.n_override() if e.scan else 0) for e in cur}
        pairs = {}
        if use_overlap:
            for key, lst in self.overlap_index().items():
                nonhard = [e for e in lst if not e.implicit]
                if len(nonhard) < 2:
                    continue
                for i in range(len(nonhard)):
                    for j in range(i + 1, len(nonhard)):
                        a, b = nonhard[i].low, nonhard[j].low
                        k = (a, b) if a < b else (b, a)
                        pairs[k] = pairs.get(k, 0) + 1
        result = list(hard)
        moves = []
        for part in (masters, regular):
            if not part:
                continue
            topo = DynTopo([e.low for e in part])
            members = set(topo.order)
            # 1. masters
            for e in part:
                for m in (e.scan.masters if e.scan else []):
                    ml = m.lower()
                    if ml in members and ml != e.low:
                        topo.add(ml, e.low, f'{m} is a master of {e.name}')
            # 2. explicit rules: {"Plugin.esp": {"after": [...], "before": [...]}}
            for name, r in rules.items():
                nl = name.lower()
                if nl not in members:
                    continue
                for other in r.get('after', []) + r.get('req', []):
                    ol = other.lower()
                    if ol in members and not topo.add(ol, nl, f'rule: {name} loads after {other}'):
                        notes.append(f'rule "{name} after {other}" conflicts with harder rules; ignored')
                for other in r.get('before', []):
                    ol = other.lower()
                    if ol in members and not topo.add(nl, ol, f'rule: {name} loads before {other}'):
                        notes.append(f'rule "{name} before {other}" conflicts with harder rules; ignored')
            # 3. late loaders (generated patches) after everything else in the partition
            late = [e.low for e in part if late_loader_reason(e.name)]
            for ll in late:
                why = late_loader_reason(names[ll].name)
                for n in topo.order[:]:
                    if n != ll and n not in late:
                        topo.add(n, ll, f'{names[ll].name} is a {why} and should load last')
            # 4. overlap: the plugin that overrides more records loads first
            for (a, b), shared in sorted(pairs.items()):
                if a not in members or b not in members:
                    continue
                ca, cb = override_count[a], override_count[b]
                if ca == cb:
                    continue
                first, second = (a, b) if ca > cb else (b, a)
                topo.add(first, second,
                         f'overlap: both override {shared} record(s); {names[first].name} overrides more records '
                         f'({max(ca, cb)} vs {min(ca, cb)}), so the smaller {names[second].name} wins')
            new_order = [names[n] for n in topo.order]
            moves += _explain_moves(part, new_order, topo)
            result += new_order
        return result, moves, notes


class DynTopo:
    """Dynamic topological order (Pearce & Kelly 2006). Adding an edge that is
    already consistent with the current order costs nothing; otherwise only
    the affected region is reordered, so the original order is preserved as
    much as possible. Edges that would create a cycle are rejected."""

    def __init__(self, nodes):
        self.order = list(nodes)
        self.pos = {n: i for i, n in enumerate(self.order)}
        self.succ = {n: set() for n in self.order}
        self.pred = {n: set() for n in self.order}
        self.reasons = {}

    def add(self, u, v, reason=''):
        if u == v:
            return False
        if v in self.succ[u]:
            return True
        pu, pv = self.pos[u], self.pos[v]
        if pu > pv:
            fwd, seen, stack = [], {v}, [v]
            while stack:
                n = stack.pop()
                fwd.append(n)
                for w in self.succ[n]:
                    if w == u:
                        return False
                    if w not in seen and self.pos[w] <= pu:
                        seen.add(w)
                        stack.append(w)
            bwd, seenb, stack = [], {u}, [u]
            while stack:
                n = stack.pop()
                bwd.append(n)
                for w in self.pred[n]:
                    if w not in seenb and self.pos[w] >= pv:
                        seenb.add(w)
                        stack.append(w)
            bwd.sort(key=self.pos.__getitem__)
            fwd.sort(key=self.pos.__getitem__)
            nodes = bwd + fwd
            slots = sorted(self.pos[n] for n in nodes)
            for n, p in zip(nodes, slots):
                self.pos[n] = p
                self.order[p] = n
        self.succ[u].add(v)
        self.pred[v].add(u)
        self.reasons[(u, v)] = reason
        return True


def _lcs_keep(a, b):
    """Set of items of b that are part of a longest common subsequence of a and b."""
    n, m = len(a), len(b)
    if n * m > 4_000_000:          # very long lists: keep items whose relative order is unchanged
        pos = {x: i for i, x in enumerate(a)}
        keep, last = set(), -1
        for x in b:
            if pos[x] > last:
                keep.add(x)
                last = pos[x]
        return keep
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        ai = a[i]
        row, nxt = dp[i], dp[i + 1]
        for j in range(m - 1, -1, -1):
            row[j] = nxt[j + 1] + 1 if ai == b[j] else max(nxt[j], row[j + 1])
    keep = set()
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            keep.add(a[i])
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return keep


def _explain_moves(before, after, topo):
    a = [e.low for e in before]
    b = [e.low for e in after]
    keep = _lcs_keep(a, b)
    pos_before = {x: i for i, x in enumerate(a)}
    moves = []
    moved = {e.low for e in after if e.low not in keep}
    for e in after:
        if e.low in keep:
            continue
        primary, secondary = [], []
        for (u, v), why in topo.reasons.items():
            if e.low in (u, v) and pos_before[u] > pos_before[v]:
                other = v if u == e.low else u
                (secondary if other in moved else primary).append(why)
        reasons = list(dict.fromkeys(primary or secondary))
        moves.append((e, reasons or ['follows a plugin that had to move']))
    return moves
