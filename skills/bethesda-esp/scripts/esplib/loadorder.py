"""Multi-plugin context: finds masters, resolves FormKeys/EditorIDs across
plugins, finds the winning override, and caches EditorID indexes of large
masters (Skyrim.esm) on disk."""

import hashlib
import json
import os
import re

from .core import Plugin, EspError
from .codec import parse_formid_text, format_formid
from .strings import StringTables, _ci_join

FORMKEY_RE = re.compile(r'^\s*([0-9A-Fa-f]{1,6}):(.+\.(?:esm|esp|esl))\s*$', re.I)
FORMKEY_RE2 = re.compile(r'^\s*(.+\.(?:esm|esp|esl)):([0-9A-Fa-f]{1,6})\s*$', re.I)
RAWFID_RE = re.compile(r'^\s*(?:0x)?([0-9A-Fa-f]{8})\s*$')

BIG_PLUGIN = 48 * 1024 * 1024


def cache_dir():
    d = os.environ.get('ESP_CACHE_DIR') or os.path.join(
        os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache'),
        'bethesda-esp')
    return d


def read_plugins_txt(path):
    """Read a plugins.txt / loadorder.txt (lines, optional leading '*')."""
    out = []
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            out.append(line.lstrip('*'))
    return out


class LoadOrder:
    def __init__(self, data_dir=None, encoding=None, language='english'):
        self.data_dirs = []
        if data_dir:
            self.data_dirs.append(os.path.abspath(data_dir))
        self.encoding = encoding
        self.language = language
        self.plugins = {}        # lower name -> Plugin
        self.order = []          # lower names in load order (as known)
        self._names = {}         # lower name -> {objid: (sig, edid)}
        self._strings = {}

    # -- loading -------------------------------------------------------------
    def add(self, path_or_plugin):
        if isinstance(path_or_plugin, Plugin):
            p = path_or_plugin
        else:
            p = Plugin.load(path_or_plugin, self.encoding)
        key = p.name.lower()
        self.plugins[key] = p
        if key not in self.order:
            self.order.append(key)
        if p.path:
            d = os.path.dirname(p.path)
            if d not in self.data_dirs:
                self.data_dirs.append(d)
        return p

    def find_file(self, name):
        if os.path.isfile(name):
            return os.path.abspath(name)
        for d in self.data_dirs:
            p = _ci_join(d, os.path.basename(name))
            if p and os.path.isfile(p):
                return p
        return None

    def get(self, name, required=True):
        key = os.path.basename(name).lower()
        if key in self.plugins:
            return self.plugins[key]
        path = self.find_file(name)
        if path is None:
            if required:
                raise EspError(f'cannot find {name} (searched: {", ".join(self.data_dirs) or "nothing"}); '
                               f'pass --data <Skyrim Data folder>')
            return None
        p = Plugin.load(path, self.encoding)
        self.plugins[key] = p
        return p

    def has_file(self, name):
        return os.path.basename(name).lower() in self.plugins or self.find_file(name) is not None

    def with_masters(self, plugin, required=False):
        """[masters in load order..., plugin] for the ones that can be found."""
        out = []
        seen = set()

        def visit(p):
            for m in p.masters:
                if m.lower() in seen:
                    continue
                mp = self.get(m, required=required)
                if mp is None:
                    seen.add(m.lower())
                    continue
                visit(mp)
                if m.lower() not in seen:
                    seen.add(m.lower())
                    out.append(mp)
        visit(plugin)
        out.append(plugin)
        return out

    # -- strings -------------------------------------------------------------
    def strings_for(self, plugin):
        if not plugin.is_localized:
            return None
        key = plugin.name.lower()
        if key not in self._strings:
            st = None
            if plugin.path:
                dirs = [os.path.dirname(plugin.path)] + self.data_dirs
                for d in dirs:
                    st = StringTables.find(os.path.join(d, plugin.name), self.language, d)
                    if st:
                        break
            self._strings[key] = st
            plugin.strings = st
        return self._strings[key]

    # -- names ---------------------------------------------------------------
    def names(self, plugin_name):
        """{objid: (sig, edid)} for records *defined* by plugin_name."""
        key = plugin_name.lower()
        if key in self._names:
            return self._names[key]
        if key in self.plugins:
            p = self.plugins[key]
            self._names[key] = self._build_names(p)
            return self._names[key]
        path = self.find_file(plugin_name)
        if path is None:
            self._names[key] = None
            return None
        st = os.stat(path)
        tag = hashlib.sha1(f'{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}'.encode()).hexdigest()[:16]
        cpath = os.path.join(cache_dir(), f'names-{key}-{tag}.json')
        if os.path.isfile(cpath):
            try:
                with open(cpath, encoding='utf-8') as f:
                    raw = json.load(f)
                self._names[key] = {int(k, 16): tuple(v) for k, v in raw.items()}
                return self._names[key]
            except (OSError, ValueError):
                pass
        p = self.get(plugin_name)
        table = self._build_names(p)
        self._names[key] = table
        if st.st_size >= BIG_PLUGIN // 8:
            try:
                os.makedirs(cache_dir(), exist_ok=True)
                with open(cpath, 'w', encoding='utf-8') as f:
                    json.dump({f'{k:06X}': list(v) for k, v in table.items()}, f)
            except OSError:
                pass
        return table

    @staticmethod
    def _build_names(p):
        own = p.self_index
        table = {}
        for r in p.records():
            if (r.formid >> 24) == own:
                table[r.formid & 0xFFFFFF] = (r.sig, r.edid or '')
        return table

    # -- FormKeys ------------------------------------------------------------
    @staticmethod
    def owner_of(plugin, fid):
        idx = fid >> 24
        ms = plugin.masters
        if idx < len(ms):
            return ms[idx]
        if idx == len(ms):
            return plugin.name
        return None

    def formkey(self, plugin, fid):
        o = self.owner_of(plugin, fid)
        return (fid & 0xFFFFFF, o) if o else None

    @staticmethod
    def local_fid(plugin, objid, owner):
        names = [m.lower() for m in plugin.masters]
        if owner.lower() == plugin.name.lower():
            return (len(names) << 24) | objid
        if owner.lower() in names:
            return (names.index(owner.lower()) << 24) | objid
        return None

    def describe(self, plugin, fid, with_type=True):
        """'IronSword [WEAP:012EB7:Skyrim.esm]' style label for display."""
        if fid == 0:
            return 'NULL'
        fk = self.formkey(plugin, fid)
        if fk is None:
            return f'<invalid 0x{fid:08X}>'
        objid, owner = fk
        info = None
        try:
            if owner.lower() == plugin.name.lower():
                r = plugin.find(fid)
                if r is not None:
                    info = (r.sig, r.edid or '')
            else:
                tbl = self.names(owner)
                if tbl is not None:
                    info = tbl.get(objid)
        except EspError:
            info = None
        key = f'{objid:06X}:{owner}'
        if info is None:
            return key
        sig, edid = info
        return f'{edid} [{sig}:{key}]' if edid else f'[{sig}:{key}]'

    def resolve(self, text, plugin, search=None, allow_add_master=False):
        """Parse a FormID given as text in the context of `plugin`.
        Accepts 0x0001A2B3 (file-local), 01A2B3:Skyrim.esm, Skyrim.esm:01A2B3,
        or an EditorID (searched in plugin, then its masters)."""
        s = str(text).strip()
        m = FORMKEY_RE.match(s) or FORMKEY_RE2.match(s)
        if m:
            a, b = m.groups()
            if FORMKEY_RE2.match(s) and not FORMKEY_RE.match(s):
                a, b = b, a
            objid, owner = int(a, 16), b.strip()
            fid = self.local_fid(plugin, objid, owner)
            if fid is None:
                if allow_add_master:
                    from . import ops
                    ops.add_masters(plugin, [owner], self)
                    fid = self.local_fid(plugin, objid, owner)
                else:
                    raise EspError(f'{owner} is not a master of {plugin.name} '
                                   f'(add it: esp.py masters {plugin.name} --add {owner})')
            return fid
        if RAWFID_RE.match(s):
            return int(RAWFID_RE.match(s).group(1), 16)
        if s.lower() in ('null', 'none', '0', ''):
            return 0
        # EditorID
        hit = self.find_edid(s, plugin, search)
        if hit is None:
            raise EspError(f'no record with EditorID {s!r} in {plugin.name} or its masters')
        src_plugin, rec = hit
        if isinstance(rec, _Ref):
            objid, owner = rec.objid, rec.owner
        else:
            objid, owner = rec.formid & 0xFFFFFF, self.owner_of(src_plugin, rec.formid)
        fid = self.local_fid(plugin, objid, owner)
        if fid is None:
            if allow_add_master:
                from . import ops
                ops.add_masters(plugin, [owner], self)
                fid = self.local_fid(plugin, objid, owner)
            else:
                raise EspError(f'{s} is defined in {owner}, which is not a master of {plugin.name}')
        return fid

    def find_edid(self, edid, plugin, search=None):
        """Return (plugin, Record) or (None, _Ref) for an EditorID, searching
        `plugin`, then `search` plugins, then plugin's masters (last first)."""
        r = plugin.find_edid(edid)
        if r is not None:
            return plugin, r
        for c in list(search or []):
            r = c.find_edid(edid)
            if r is not None:
                return c, r
        low = edid.lower()
        for m in reversed(plugin.masters):
            if m.lower() in self.plugins:
                r = self.plugins[m.lower()].find_edid(edid)
                if r is not None:
                    return self.plugins[m.lower()], r
                continue
            tbl = self.names(m)
            if not tbl:
                continue
            for objid, (sig, e) in tbl.items():
                if e.lower() == low:
                    return None, _Ref(objid, m)
        return None

    def parser_for(self, plugin, allow_add_master=False):
        return lambda v: self.resolve(v, plugin, allow_add_master=allow_add_master) if not isinstance(v, int) else v

    # -- override chain ------------------------------------------------------
    def chain(self, objid, owner, plugins):
        """[(plugin, record)] for every plugin in `plugins` (load order) that
        contains this FormKey."""
        out = []
        for p in plugins:
            fid = self.local_fid(p, objid, owner)
            if fid is None:
                continue
            r = p.find(fid)
            if r is not None:
                out.append((p, r))
        return out


class _Ref:
    """Stand-in for a record known only from a names table."""

    def __init__(self, objid, owner):
        self.objid = objid
        self.owner = owner
        self.formid = None


def lookup_record(lo, plugin, text):
    """Find a record in `plugin` from user text (FormID/FormKey/EditorID)."""
    s = str(text).strip()
    r = None
    try:
        fid = lo.resolve(s, plugin) if (FORMKEY_RE.match(s) or FORMKEY_RE2.match(s) or RAWFID_RE.match(s)) else None
    except EspError:
        fid = None
    if fid is not None:
        r = plugin.find(fid)
    if r is None and not RAWFID_RE.match(s):
        r = plugin.find_edid(s)
    if r is None:
        raise EspError(f'record {s!r} not found in {plugin.name}')
    return r
