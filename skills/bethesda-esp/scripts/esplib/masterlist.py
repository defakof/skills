"""LOOT metadata for Skyrim SE: groups, load-after / requirement rules,
incompatibilities, dirty-plugin CRCs, Bash Tags and messages, plus a small
evaluator for LOOT's condition language.

A compact snapshot of the LOOT Skyrim SE masterlist ships in data/ (the
masterlist is CC0 1.0: https://github.com/loot/skyrimse). `esp loot-update`
refreshes it; LOOT's own masterlist.yaml / userlist.yaml can be read too
(full YAML needs PyYAML; simple userlists are read without it).
"""

import gzip
import json
import mmap
import os
import re
import zlib

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SNAPSHOT = os.path.join(DATA_DIR, 'loot_skyrimse.json.gz')
MASTERLIST_URL = 'https://raw.githubusercontent.com/loot/skyrimse/v0.29/masterlist.yaml'
LOOT_GAME_FOLDER = 'Skyrim Special Edition'

_REGEX_CHARS = frozenset(':\\*?|')
_MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]*\)')


def is_regex_name(name):
    """LOOT treats a plugin name as a regex if it has one of : \\ * ? |"""
    return any(c in _REGEX_CHARS for c in name)


# ---------------------------------------------------------------------------
# masterlist / userlist YAML -> compact form
# ---------------------------------------------------------------------------

def _text(content, subs=None):
    if isinstance(content, list):          # [{lang, text}, ...]
        en = [c.get('text', '') for c in content if isinstance(c, dict) and c.get('lang') in ('en', None)]
        content = en[0] if en else (content[0].get('text', '') if content and isinstance(content[0], dict) else '')
    content = str(content or '')
    for i, s in enumerate(subs or []):
        content = content.replace('{%d}' % i, str(s))
    return content.strip()


def _file_item(x):
    if isinstance(x, str):
        return x
    if not isinstance(x, dict) or not x.get('name'):
        return None
    d = {'n': str(x['name'])}
    if x.get('display'):
        d['d'] = _text(x['display'])
    if x.get('detail'):
        d['t'] = _text(x['detail'])
    if x.get('condition'):
        d['c'] = str(x['condition'])
    if x.get('constraint'):
        d['k'] = str(x['constraint'])
    return d if len(d) > 1 else d['n']


def _msg_item(m):
    if not isinstance(m, dict):
        return None
    out = [str(m.get('type', 'say')), _text(m.get('content', ''), m.get('subs'))]
    if m.get('condition'):
        out.append(str(m['condition']))
    return out


def _clean_item(c, dirty):
    if not isinstance(c, dict) or 'crc' not in c:
        return None
    crc = c['crc']
    if isinstance(crc, str):
        crc = int(crc, 16)
    d = {'crc': int(crc) & 0xFFFFFFFF}
    if c.get('util'):
        d['u'] = _MD_LINK.sub(r'\1', _text(c['util']))
    if dirty:
        for src, dst in (('itm', 'i'), ('udr', 'r'), ('nav', 'v')):
            if c.get(src):
                d[dst] = int(c[src])
        det = _text(c.get('detail', ''))
        if det and not det.lower().startswith('a guide to cleaning'):
            d['t'] = det
    if c.get('condition'):
        d['c'] = str(c['condition'])
    return d


def compact_metadata(doc, source=''):
    """Turn a parsed LOOT masterlist/userlist (dict) into the compact form
    used by Metadata (and stored in the bundled snapshot)."""
    doc = doc or {}
    groups = []
    for g in doc.get('groups') or []:
        if isinstance(g, dict) and g.get('name'):
            groups.append([str(g['name']), [str(a) for a in (g.get('after') or [])]])
    plugins = []
    for p in doc.get('plugins') or []:
        if not isinstance(p, dict) or not p.get('name'):
            continue
        e = {'n': str(p['name'])}
        if p.get('group'):
            e['g'] = str(p['group'])
        for src, dst in (('after', 'a'), ('req', 'q'), ('inc', 'x')):
            items = [i for i in (_file_item(x) for x in (p.get(src) or [])) if i]
            if items:
                e[dst] = items
        msgs = [m for m in (_msg_item(x) for x in (p.get('msg') or [])) if m]
        if msgs:
            e['m'] = msgs
        tags = []
        for t in p.get('tag') or []:
            if isinstance(t, str):
                tags.append(t)
            elif isinstance(t, dict) and t.get('name'):
                tags.append([str(t['name']), str(t['condition'])] if t.get('condition') else str(t['name']))
        if tags:
            e['t'] = tags
        dirty = [d for d in (_clean_item(x, True) for x in (p.get('dirty') or [])) if d]
        if dirty:
            e['d'] = dirty
        clean = [d for d in (_clean_item(x, False) for x in (p.get('clean') or [])) if d]
        if clean:
            e['c'] = clean
        if len(e) > 1:
            plugins.append(e)
    glob = [m for m in (_msg_item(x) for x in (doc.get('globals') or [])) if m]
    return {'format': 1, 'source': source, 'groups': groups, 'plugins': plugins, 'globals': glob}


def parse_yaml_text(text):
    """Parse LOOT YAML. Uses PyYAML when installed (needed for the masterlist:
    anchors and merge keys); otherwise a small parser that handles typical
    userlist.yaml files."""
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        loader = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
        return yaml.load(text, Loader=loader)
    return MiniYaml(text).parse()


def load_yaml_metadata(path):
    with open(path, encoding='utf-8-sig') as f:
        text = f.read()
    return compact_metadata(parse_yaml_text(text), source=path)


def load_compact(path):
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


def write_compact(data, path):
    tmp = path + '.tmp'
    with gzip.open(tmp, 'wt', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# minimal YAML (block style) for userlists without PyYAML
# ---------------------------------------------------------------------------

class YamlError(ValueError):
    pass


class MiniYaml:
    """Block mappings/sequences, flow lists/maps on one line, plain and quoted
    scalars, comments and |/> block scalars. No anchors, aliases or tags."""

    def __init__(self, text):
        self.lines = []               # [indent, text without comment, index in self.raw]
        self.raw = text.splitlines()
        for i, line in enumerate(self.raw):
            stripped = line.strip()
            if not stripped or stripped.startswith('#') or stripped in ('---', '...'):
                continue
            if '\t' in line[:len(line) - len(line.lstrip())]:
                raise YamlError('tabs in indentation')
            self.lines.append([len(line) - len(line.lstrip(' ')), _strip_comment(line.strip()), i])
        self.pos = 0

    def parse(self):
        if not self.lines:
            return None
        return self._block(self.lines[0][0])

    def _peek(self):
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def _block(self, indent):
        cur = self._peek()
        if cur is None:
            return None
        if cur[1].startswith('- ') or cur[1] == '-':
            return self._seq(indent)
        if not _is_key(cur[1]):            # a value on its own line, e.g. "key:\n  []"
            self.pos += 1
            return self._scalar_or_flow(cur[1], indent - 1)
        return self._map(indent)

    def _seq(self, indent):
        out = []
        while True:
            cur = self._peek()
            if cur is None or cur[0] < indent:
                break
            if cur[0] > indent:
                raise YamlError(f'bad indentation: {cur[1]!r}')
            if not (cur[1].startswith('- ') or cur[1] == '-'):
                break
            rest = cur[1][1:].strip()
            if not rest:
                self.pos += 1
                nxt = self._peek()
                out.append(self._block(nxt[0]) if nxt and nxt[0] > indent else None)
                continue
            if _is_key(rest):
                # "- key: value" starts a mapping indented at the item text
                cur[0] = indent + (len(cur[1]) - len(rest))
                cur[1] = rest
                out.append(self._map(cur[0]))
                continue
            self.pos += 1
            out.append(self._scalar_or_flow(rest, indent))
        return out

    def _map(self, indent):
        out = {}
        while True:
            cur = self._peek()
            if cur is None or cur[0] < indent:
                break
            if cur[0] > indent:
                raise YamlError(f'bad indentation: {cur[1]!r}')
            if cur[1].startswith('- '):
                break
            key, rest = _split_key(cur[1])
            self.pos += 1
            if rest == '':
                nxt = self._peek()
                if nxt and (nxt[0] > indent or (nxt[0] == indent and nxt[1].startswith('- '))):
                    out[key] = self._block(nxt[0])
                else:
                    out[key] = None
            else:
                out[key] = self._scalar_or_flow(rest, indent)
        return out

    def _scalar_or_flow(self, text, indent):
        if text[:1] in '|>':
            return self._block_scalar(text, indent)
        if text[:1] in '&*!':
            raise YamlError('anchors/aliases/tags need PyYAML (pip install pyyaml)')
        if text[:1] in '[{':
            return _flow(text)
        if text[:1] in '\'"':
            val, end = _quoted(text, 0)
            if text[end:].strip():
                raise YamlError(f'unexpected text after value: {text!r}')
            return val
        return _plain(text)                 # block plain scalar: the rest of the line

    def _block_scalar(self, head, indent):
        """| or > block: raw lines (comments and blank lines kept) indented
        deeper than the key."""
        start = self.lines[self.pos - 1][2] + 1 if self.pos else 0
        body = []
        j = start
        while j < len(self.raw):
            line = self.raw[j]
            if line.strip() and len(line) - len(line.lstrip(' ')) <= indent:
                break
            body.append(line)
            j += 1
        while body and not body[-1].strip():
            body.pop()
        while self.pos < len(self.lines) and self.lines[self.pos][2] < j:
            self.pos += 1
        if not body:
            return ''
        cut = min(len(x) - len(x.lstrip(' ')) for x in body if x.strip())
        body = [x[cut:] for x in body]
        if head[0] == '|':
            text = '\n'.join(body)
        else:                               # folded: single newlines become spaces
            text = re.sub(r'(?<!\n)\n(?!\n)', ' ', '\n'.join(body))
        return text + ('' if head[1:2] == '-' else '\n')


def _strip_comment(s):
    q = None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
        elif ch in '\'"' and (i == 0 or s[i - 1] in ' \t[{,:'):
            q = ch                  # a quote only opens a string at the start of a value
        elif ch == '#' and (i == 0 or s[i - 1] in ' \t'):
            return s[:i].rstrip()
    return s


def _is_key(s):
    try:
        _split_key(s)
        return True
    except YamlError:
        return False


def _split_key(s):
    if s[:1] in '\'"':
        val, end = _quoted(s, 0)
        rest = s[end:].lstrip()
        if not rest.startswith(':'):
            raise YamlError(f'expected ":" in {s!r}')
        return val, rest[1:].strip()
    m = re.match(r'([^:#\[\]{},]+?)\s*:(\s|$)', s)
    if not m:
        raise YamlError(f'not a mapping entry: {s!r}')
    return m.group(1).strip(), s[m.end():].strip()


def _quoted(s, i):
    q = s[i]
    out = []
    i += 1
    while i < len(s):
        ch = s[i]
        if q == "'" and ch == "'":
            if s[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return ''.join(out), i + 1
        if q == '"' and ch == '\\' and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({'n': '\n', 't': '\t', '"': '"', '\\': '\\', '/': '/'}.get(nxt, '\\' + nxt))
            i += 2
            continue
        if q == '"' and ch == '"':
            return ''.join(out), i + 1
        out.append(ch)
        i += 1
    raise YamlError(f'unterminated string: {s!r}')


def _flow(s):
    s = s.strip()
    val, end = _flow_value(s, 0)
    if s[end:].strip():
        raise YamlError(f'unexpected text after value: {s!r}')
    return val


def _flow_value(s, i):
    while i < len(s) and s[i] == ' ':
        i += 1
    if i >= len(s):
        return None, i
    ch = s[i]
    if ch in '\'"':
        return _quoted(s, i)
    if ch == '[':
        out = []
        i += 1
        while True:
            while i < len(s) and s[i] in ' ,':
                i += 1
            if i >= len(s):
                raise YamlError(f'unterminated list: {s!r}')
            if s[i] == ']':
                return out, i + 1
            v, i = _flow_value(s, i)
            out.append(v)
    if ch == '{':
        out = {}
        i += 1
        while True:
            while i < len(s) and s[i] in ' ,':
                i += 1
            if i >= len(s):
                raise YamlError(f'unterminated map: {s!r}')
            if s[i] == '}':
                return out, i + 1
            k, i = _flow_value(s, i)
            while i < len(s) and s[i] == ' ':
                i += 1
            if i >= len(s) or s[i] != ':':
                raise YamlError(f'expected ":" in {s!r}')
            v, i = _flow_value(s, i + 1)
            out[k] = v
    # plain scalar: up to a flow delimiter (inside flow) or end
    j = i
    while j < len(s) and s[j] not in ',]}' and not (s[j] == ':' and (j + 1 == len(s) or s[j + 1] == ' ')):
        j += 1
    return _plain(s[i:j].strip()), j


def _plain(t):
    if t in ('', '~', 'null', 'Null', 'NULL'):
        return None
    if t in ('true', 'True', 'TRUE'):
        return True
    if t in ('false', 'False', 'FALSE'):
        return False
    if re.fullmatch(r'[-+]?\d+', t):
        return int(t)
    if re.fullmatch(r'0x[0-9A-Fa-f]+', t):
        return int(t, 16)
    return t


# ---------------------------------------------------------------------------
# executable version (for product_version() and the game version)
# ---------------------------------------------------------------------------

def pe_version(path):
    """(file_version, product_version) tuples from a Windows executable's
    VS_FIXEDFILEINFO, or None."""
    try:
        with open(path, 'rb') as f:
            if f.read(2) != b'MZ':
                return None
            f.seek(0)
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                i = mm.rfind(b'\xbd\x04\xef\xfe')
                if i < 0 or i + 24 > len(mm):
                    return None
                import struct
                _sig, _sv, fms, fls, pms, pls = struct.unpack_from('<6I', mm, i)
                return ((fms >> 16, fms & 0xFFFF, fls >> 16, fls & 0xFFFF),
                        (pms >> 16, pms & 0xFFFF, pls >> 16, pls & 0xFFFF))
    except (OSError, ValueError):
        return None


def parse_version(v):
    parts = re.split(r'[.\-_+ ]', str(v).strip().lstrip('vV'))
    out = []
    for p in parts:
        if p.isdigit():
            out.append((0, int(p), ''))
        elif p:
            m = re.match(r'(\d*)(.*)', p)
            out.append((0, int(m.group(1)) if m.group(1) else 0, m.group(2).lower()))
    while out and out[-1] == (0, 0, ''):
        out.pop()
    return out


def compare_versions(a, b):
    pa, pb = parse_version(a), parse_version(b)
    n = max(len(pa), len(pb))
    pa += [(0, 0, '')] * (n - len(pa))
    pb += [(0, 0, '')] * (n - len(pb))
    return (pa > pb) - (pa < pb)


_VERSION_IN_DESC = [
    re.compile(r'(?:^|\W)v(?:ersion)?\s*[:.]?\s*(\d+(?:\.\d+)+[a-z]?)', re.I),
    re.compile(r'(?:^|\W)version\s*[:]?\s*(\d+[a-z]?)\b', re.I),
    re.compile(r'(?:^|\s)(\d+\.\d+(?:\.\d+)*)(?:\s|$)'),
]


def version_from_description(desc):
    for rx in _VERSION_IN_DESC:
        m = rx.search(desc or '')
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# condition language
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<cmp>==|!=|<=|>=|<|>)|(?P<p>[(),])|'
                    r'(?P<word>[A-Za-z_][A-Za-z0-9_]*)|(?P<num>[0-9A-Fa-f]+))')


class ConditionError(ValueError):
    pass


def tokenize(cond):
    out = []
    pos = 0
    cond = cond.strip()
    while pos < len(cond):
        m = _TOKEN.match(cond, pos)
        if not m or m.end() == pos:
            raise ConditionError(f'cannot parse condition at {cond[pos:pos + 20]!r}')
        pos = m.end()
        kind = m.lastgroup
        val = m.group(kind)
        if kind == 'str':
            val = val[1:-1].replace('\\"', '"')
        out.append((kind, val))
    return out


def _and3(vals):
    if any(v is False for v in vals):
        return False
    return None if any(v is None for v in vals) else True


def _or3(vals):
    if any(v is True for v in vals):
        return True
    return None if any(v is None for v in vals) else False


class Evaluator:
    """Evaluates LOOT conditions against a load order. Returns True, False or
    None (cannot tell offline, e.g. a file in a folder we were not given)."""

    def __init__(self, model):
        self.model = model
        self._cache = {}
        self._dirlist = {}
        self._crc = {}
        names = model.by_name()
        self.installed = {k: e for k, e in names.items() if e.path}
        self.active = {k: e for k, e in self.installed.items() if e.active or e.implicit}
        self.data_dirs = [d for d, _ in model.search_dirs]
        self.game_dir = os.path.dirname(model.data_dir) if model.data_dir else None

    def eval(self, cond):
        if not cond:
            return True
        if cond in self._cache:
            return self._cache[cond]
        try:
            toks = tokenize(cond)
            self._toks, self._i = toks, 0
            val = self._expr()
            if self._i != len(toks):
                raise ConditionError('trailing tokens')
        except ConditionError:
            val = None
        self._cache[cond] = val
        return val

    # grammar: expr = term ('or' term)* ; term = factor ('and' factor)* ;
    # factor = 'not' factor | '(' expr ')' | call
    def _next(self):
        if self._i >= len(self._toks):
            raise ConditionError('unexpected end')
        t = self._toks[self._i]
        self._i += 1
        return t

    def _peek(self):
        return self._toks[self._i] if self._i < len(self._toks) else (None, None)

    def _expr(self):
        vals = [self._term()]
        while self._peek() == ('word', 'or'):
            self._i += 1
            vals.append(self._term())
        return vals[0] if len(vals) == 1 else _or3(vals)

    def _term(self):
        vals = [self._factor()]
        while self._peek() == ('word', 'and'):
            self._i += 1
            vals.append(self._factor())
        return vals[0] if len(vals) == 1 else _and3(vals)

    def _factor(self):
        kind, val = self._next()
        if (kind, val) == ('word', 'not'):
            v = self._factor()
            return None if v is None else not v
        if (kind, val) == ('p', '('):
            v = self._expr()
            if self._next() != ('p', ')'):
                raise ConditionError('missing )')
            return v
        if kind != 'word':
            raise ConditionError(f'unexpected {val!r}')
        if self._next() != ('p', '('):
            raise ConditionError('expected (')
        args = []
        while True:
            k, v = self._next()
            if (k, v) == ('p', ')'):
                break
            if (k, v) == ('p', ','):
                continue
            args.append((k, v))
        fn = getattr(self, 'f_' + val, None)
        if fn is None:
            return None
        try:
            return fn(*args)
        except (TypeError, ValueError, OSError, re.error):
            return None

    # -- file helpers -----------------------------------------------------------
    def _listdir(self, d):
        if d not in self._dirlist:
            try:
                self._dirlist[d] = {n.lower(): n for n in os.listdir(d)}
            except OSError:
                self._dirlist[d] = {}
        return self._dirlist[d]

    def _resolve_in(self, base, rel):
        cur = base
        for part in rel:
            hit = self._listdir(cur).get(part.lower())
            if hit is None:
                return None
            cur = os.path.join(cur, hit)
        return cur

    def _roots(self, path):
        """(roots to search, relative parts) or (None, parts) if unknown."""
        parts = [p for p in path.replace('\\', '/').split('/') if p not in ('', '.')]
        if parts and parts[0] == '..':
            return ([self.game_dir] if self.game_dir else None), parts[1:]
        return (self.data_dirs or None), parts

    @staticmethod
    def _is_plugin(path):
        return '/' not in path and '\\' not in path and path.lower().endswith(('.esp', '.esm', '.esl'))

    def find(self, path):
        """Absolute path, False if certainly absent, None if unknown."""
        if self._is_plugin(path):
            e = self.installed.get(path.lower())
            return e.path if e else False
        roots, parts = self._roots(path)
        if roots is None:
            return None
        for r in roots:
            hit = self._resolve_in(r, parts)
            if hit and not hit.lower().endswith('.mohidden'):
                return hit
        return False

    def _matches(self, regex_path, plugins_only=False, active_only=False):
        """Names matching a LOOT regex path (regex applies to the file name)."""
        path = regex_path.replace('\\\\', '\\')
        if '/' in path:
            d, rx = path.rsplit('/', 1)
        else:
            d, rx = '', path
        cre = re.compile(rx, re.I)
        if d == '' and (plugins_only or re.search(r'es[pml\[(]', rx.lower())):
            pool = self.active if active_only else self.installed
            return [n for n in pool if cre.fullmatch(n)]
        if active_only:
            return []
        roots, parts = self._roots(d)
        if roots is None:
            return None
        found = set()
        for r in roots:
            base = self._resolve_in(r, parts) if parts else r
            if base and os.path.isdir(base):
                found.update(n for n in self._listdir(base) if cre.fullmatch(n))
        return sorted(found)

    def crc(self, path):
        e = self.installed.get(path.lower()) if self._is_plugin(path) else None
        if e is not None and e.scan is not None and getattr(e.scan, 'crc', None) is not None:
            return e.scan.crc
        p = self.find(path)
        if not p:
            return p
        if p not in self._crc:
            c = 0
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''):
                    c = zlib.crc32(chunk, c)
            self._crc[p] = c & 0xFFFFFFFF
        return self._crc[p]

    # -- functions ----------------------------------------------------------------
    @staticmethod
    def _s(arg):
        return arg[1]

    def f_file(self, a):
        p = self._s(a)
        if is_regex_name(p.split('/')[-1]) or '\\' in p:
            m = self._matches(p)
            return None if m is None else bool(m)
        r = self.find(p)
        return None if r is None else bool(r)

    def f_readable(self, a):
        r = self.find(self._s(a))
        return None if r is None else bool(r) and os.access(r, os.R_OK)

    def f_is_executable(self, a):
        r = self.find(self._s(a))
        if not r:
            return r if r is None else False
        with open(r, 'rb') as f:
            return f.read(2) == b'MZ'

    def f_active(self, a):
        p = self._s(a)
        if is_regex_name(p):
            return bool(self._matches(p, plugins_only=True, active_only=True))
        return p.lower() in self.active

    def f_many(self, a):
        m = self._matches(self._s(a))
        return None if m is None else len(m) > 1

    def f_many_active(self, a):
        return len(self._matches(self._s(a), plugins_only=True, active_only=True)) > 1

    def f_is_master(self, a):
        e = self.installed.get(self._s(a).lower())
        if e is None:
            return False
        if e.scan is not None:
            return bool(e.scan.is_master_like)
        return e.name.lower().endswith(('.esm', '.esl'))

    def f_checksum(self, a, crc):
        c = self.crc(self._s(a))
        if c is None or c is False:
            return c
        return c == int(crc[1], 16)

    def f_file_size(self, a, size):
        r = self.find(self._s(a))
        if not r:
            return r if r is None else False
        return os.path.getsize(r) == int(size[1])

    def f_description_contains(self, a, rx):
        e = self.installed.get(self._s(a).lower())
        if e is None:
            return False
        if e.scan is None:
            return None
        return bool(re.search(rx[1], e.scan.description or '', re.I))

    def _version_args(self, args):
        path = args[0][1]
        cmp = next((v for k, v in args[1:] if k == 'cmp'), None)
        ver = next((v for k, v in args[1:] if k in ('str', 'num') and k != 'cmp'), None)
        if cmp is None or ver is None:
            raise ValueError('bad version() arguments')
        return path, ver, cmp

    @staticmethod
    def _compare(have, cmp, want):
        c = compare_versions(have, want)
        return {'==': c == 0, '!=': c != 0, '<': c < 0, '>': c > 0, '<=': c <= 0, '>=': c >= 0}[cmp]

    def f_version(self, *args):
        path, ver, cmp = self._version_args(args)
        have = None
        if self._is_plugin(path):
            e = self.installed.get(path.lower())
            if e is not None and e.scan is None:
                return None
            have = version_from_description(e.scan.description) if e is not None else None
        else:
            r = self.find(path)
            if r is None:
                return None
            pv = pe_version(r) if r else None
            have = '.'.join(map(str, pv[0])) if pv else None
        # LOOT: a missing file or one without a version counts as version 0
        return self._compare(have or '0', cmp, ver)

    def f_product_version(self, *args):
        path, ver, cmp = self._version_args(args)
        r = self.find(path)
        if r is None:
            return None
        pv = pe_version(r) if r else None
        return self._compare('.'.join(map(str, pv[1])) if pv else '0', cmp, ver)

    def f_filename_version(self, *args):
        return None


# ---------------------------------------------------------------------------
# merged metadata
# ---------------------------------------------------------------------------

class PluginMeta:
    __slots__ = ('group', 'group_source', 'after', 'req', 'inc', 'msgs', 'tags', 'dirty', 'clean')

    def __init__(self):
        self.group = None
        self.group_source = None
        self.after = []        # [(item, 'masterlist'|'userlist')]
        self.req = []
        self.inc = []
        self.msgs = []
        self.tags = []
        self.dirty = []
        self.clean = []


def _item_name(item):
    return item if isinstance(item, str) else item['n']


class Metadata:
    """Masterlist + userlist, merged the way LOOT does (exact entry, then every
    matching regex entry; userlist group wins; lists are unioned)."""

    def __init__(self, masterlist=None, userlist=None):
        self.sources = []
        self.group_after = {}       # group -> set(groups it loads after)
        self.group_source = {}
        self.globals = []
        self._exact = {}            # lower name -> [(entry, src)]
        self._regex = []            # [(compiled, entry, src)]
        for data, src in ((masterlist, 'masterlist'), (userlist, 'userlist')):
            if not data:
                continue
            self.sources.append(f'{src}: {data.get("source", "?")}')
            for name, after in data.get('groups', []):
                self.group_after.setdefault(name, set()).update(after)
                self.group_source.setdefault(name, src)
            self.globals += [(m, src) for m in data.get('globals', [])]
            for e in data.get('plugins', []):
                if is_regex_name(e['n']):
                    try:
                        self._regex.append((re.compile(e['n'], re.I), e, src))
                    except re.error:
                        continue
                else:
                    self._exact.setdefault(e['n'].lower(), []).append((e, src))
        self.group_after.setdefault('default', set())
        self._cache = {}
        self._preds = {}

    @classmethod
    def load(cls, masterlist=None, userlist=None):
        """masterlist: path (.yaml/.json/.json.gz), 'none', or None for the best
        available (updated cache, else bundled snapshot). userlist: path or None."""
        return cls(load_masterlist_data(masterlist), load_yaml_metadata(userlist) if userlist else None)

    # -- groups ---------------------------------------------------------------
    def group_exists(self, g):
        return g in self.group_after

    def group_preds(self, g):
        """All groups that group g loads after (transitively)."""
        if g in self._preds:
            return self._preds[g]
        out, stack = set(), list(self.group_after.get(g, ()))
        while stack:
            x = stack.pop()
            if x in out:
                continue
            out.add(x)
            stack.extend(self.group_after.get(x, ()))
        self._preds[g] = out
        return out

    def group_cycle(self):
        for g in self.group_after:
            if g in self.group_preds(g):
                return g
        return None

    # -- plugins ----------------------------------------------------------------
    def for_plugin(self, name):
        low = name.lower()
        if low in self._cache:
            return self._cache[low]
        m = PluginMeta()
        found = list(self._exact.get(low, []))
        found += [(e, src) for rx, e, src in self._regex if rx.fullmatch(name)]
        # userlist entries apply after (and override the group of) masterlist entries
        found.sort(key=lambda t: t[1] == 'userlist')
        for e, src in found:
            if e.get('g'):
                if m.group is None or (src == 'userlist' and m.group_source != 'userlist'):
                    m.group, m.group_source = e['g'], src
            m.after += [(x, src) for x in e.get('a', [])]
            m.req += [(x, src) for x in e.get('q', [])]
            m.inc += [(x, src) for x in e.get('x', [])]
            m.msgs += [(x, src) for x in e.get('m', [])]
            m.tags += e.get('t', [])
            m.dirty += e.get('d', [])
            m.clean += e.get('c', [])
        if m.group is None:
            m.group, m.group_source = 'default', None
        self._cache[low] = m
        return m

    def known(self, name):
        low = name.lower()
        return low in self._exact or any(rx.fullmatch(name) for rx, _e, _s in self._regex)


def load_masterlist_data(masterlist=None):
    """Compact masterlist data from a path (.yaml/.json/.json.gz), None for
    the best available copy, or 'none'."""
    if masterlist == 'none':
        return None
    path = masterlist or default_masterlist_path()
    if not path:
        return None
    return load_yaml_metadata(path) if path.lower().endswith(('.yaml', '.yml')) else load_compact(path)


def evaluate_items(items, ev):
    """[(name, item, src)] of file items whose condition holds."""
    out = []
    for item, src in items:
        cond = None if isinstance(item, str) else item.get('c')
        if cond and ev.eval(cond) is not True:
            continue
        out.append((_item_name(item), item, src))
    return out


def bash_tags(meta, ev, description='', tags_file=None):
    """Effective Bash Tags, in Wrye Bash's priority order: {{BASH:...}} in the
    plugin description, then LOOT masterlist/userlist tags, then the lines of
    Data/BashTags/<plugin>.txt. '-Tag' removes a tag set by an earlier source."""
    tags = set()

    def apply(names):
        for name in names:
            name = name.strip()
            if not name:
                continue
            if name.startswith('-'):
                tags.discard(name[1:].strip())
            else:
                tags.add(name)

    m = re.search(r'\{\{\s*BASH\s*:([^}]*)\}\}', description or '', re.I)
    if m:
        apply(m.group(1).split(','))
    loot = []
    for t in (meta.tags if meta is not None else []):
        if isinstance(t, list):
            name, cond = t
            if ev.eval(cond) is not True:
                continue
        else:
            name = t
        loot.append(name)
    apply(loot)
    for line in tags_file or []:
        apply(line.split('#', 1)[0].split(','))
    return sorted(tags)


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------

def _cache_root():
    from .loadorder import cache_dir
    return os.path.join(cache_dir(), 'loot')


def updated_snapshot_path():
    return os.path.join(_cache_root(), 'skyrimse.json.gz')


def default_masterlist_path():
    upd = updated_snapshot_path()
    if os.path.isfile(upd):
        if not os.path.isfile(SNAPSHOT) or os.path.getmtime(upd) >= os.path.getmtime(SNAPSHOT):
            return upd
    return SNAPSHOT if os.path.isfile(SNAPSHOT) else None


def loot_data_dirs():
    out = []
    la = os.environ.get('LOCALAPPDATA')
    if la:
        out.append(os.path.join(la, 'LOOT'))
    xdg = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    out.append(os.path.join(xdg, 'LOOT'))
    out.append(os.path.join(os.path.expanduser('~'), '.var', 'app', 'io.github.loot.loot', 'data', 'LOOT'))
    return out


def find_userlists():
    """[(path, 'LOOT'|'Vortex')] of userlist.yaml files that exist."""
    out = []
    for d in loot_data_dirs():
        p = os.path.join(d, 'games', LOOT_GAME_FOLDER, 'userlist.yaml')
        if os.path.isfile(p):
            out.append((p, 'LOOT'))
    ad = os.environ.get('APPDATA')
    if ad:
        p = os.path.join(ad, 'Vortex', 'skyrimse', 'userlist.yaml')
        if os.path.isfile(p):
            out.append((p, 'Vortex'))
    return out


def update_snapshot(src=None):
    """Download (or read) a LOOT masterlist.yaml and store it, compacted, in the
    cache; later runs use it instead of the bundled snapshot. Needs PyYAML."""
    try:
        import yaml  # noqa: F401
    except ImportError:
        raise RuntimeError('reading the full LOOT masterlist needs PyYAML: pip install pyyaml')
    if src and os.path.isfile(src):
        with open(src, encoding='utf-8-sig') as f:
            text = f.read()
        source = src
    else:
        import urllib.request
        url = src or MASTERLIST_URL
        with urllib.request.urlopen(url, timeout=60) as r:
            text = r.read().decode('utf-8')
        source = url
    data = compact_metadata(parse_yaml_text(text), source=source)
    os.makedirs(_cache_root(), exist_ok=True)
    out = updated_snapshot_path()
    write_compact(data, out)
    return out, data
