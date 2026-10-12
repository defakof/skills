"""Which plugins of a load order can become light plugins (ESL flag), and
what would break if their FormIDs had to be compacted.

Rules (see references/loadorder.md): only NEW records count. Header < 1.71:
object IDs 0x800-0xFFF (2048 records). Header 1.71 (game 1.6.1130+, or BEES on
older games): 0x001-0xFFF. Flagging alone changes no FormIDs, so it is the safe
first choice; compacting renumbers records and breaks FaceGen, voice files,
SEQ files, scripts, SKSE configs, dependent plugins and existing saves unless
a tool like ESLifier patches all of them.
"""

import os
import re
import struct

from . import masterlist as mlist

CONFIG_EXTS = ('.ini', '.json', '.toml', '.yaml', '.yml', '.txt', '.jslot', '.psc')
MAX_CONFIG_SIZE = 4 * 1024 * 1024
MAX_DLL_SIZE = 64 * 1024 * 1024
V_CREATIONS = (1, 6, 1130)
V_EF_CELL_FIX = (7, 0, 14)

VERDICTS = ('flag', 'flag-171', 'compact', 'compact-care', 'no', 'already')


class EslCandidate:
    def __init__(self, entry):
        self.entry = entry
        self.verdict = None          # one of VERDICTS
        self.reasons = []
        self.risks = []              # risks of the recommended action
        self.n_new = 0
        self.id_range = None
        self.dependents = []
        self.files = []              # asset/config files tied to FormIDs

    def as_dict(self):
        return {'plugin': self.entry.name, 'verdict': self.verdict, 'new_records': self.n_new,
                'id_range': self.id_range, 'reasons': self.reasons, 'risks': self.risks,
                'dependents': self.dependents, 'files': self.files[:20]}


def _plugin_dirs(model, entry):
    """Folders where this plugin's own assets would be (its MO2 mod folder or Data)."""
    dirs = []
    if entry.path:
        dirs.append(os.path.dirname(entry.path))
    if model.data_dir and model.data_dir not in dirs:
        dirs.append(model.data_dir)
    return dirs


def _exists_ci(base, *parts):
    """Case-insensitive path existence (Linux / Proton installs)."""
    cur = base
    for part in parts:
        if not os.path.isdir(cur):
            return None
        hit = None
        low = part.lower()
        try:
            for n in os.listdir(cur):
                if n.lower() == low:
                    hit = n
                    break
        except OSError:
            return None
        if hit is None:
            return None
        cur = os.path.join(cur, hit)
    return cur


_NAME_END = re.compile(rb'\.es[mpl](?![a-z0-9_])')
_WIDE_NAME = re.compile(rb'((?:[\x20-\xff]\x00){1,250}?)\.\x00e\x00s\x00[mpl]\x00')
_NOT_IN_NAME = set(b'\x00"~|=:<>*?/\\\t\r\n')


def _plugin_names_in(data, stray_prefix=False):
    """Lower-case plugin file names (bytes) mentioned in lower-cased data. Each
    candidate is also indexed from every separator on, so "a.esp,b.esp" and
    "Keyword = 0x800~My Mod.esp" both yield the plain names."""
    out = set()

    def add(raw):
        raw = raw.strip()
        if not raw:
            return
        out.add(raw)
        if stray_prefix:
            out.add(raw[1:].strip())      # a .pex string-length byte that looks printable
        for j, ch in enumerate(raw):
            if ch in b' ,;([{':
                t = raw[j + 1:].strip()
                if t:
                    out.add(t)
    for m in _NAME_END.finditer(data):
        i = m.start() - 1
        while i >= 0 and data[i] >= 0x20 and data[i] not in _NOT_IN_NAME and m.start() - i < 250:
            i -= 1
        add(data[i + 1:m.end()])
    for m in _WIDE_NAME.finditer(data):
        add(m.group(0)[::2])
    return out


class _Mentions:
    """Which scripts, configs and SKSE DLLs name a plugin. Every file is read
    once per run and reduced to the plugin names it contains."""

    def __init__(self, model):
        self.model = model
        self._dirs = {}               # (kind, folder) -> {name: [(path, flags)]}

    @staticmethod
    def _read(path, limit):
        try:
            if os.path.getsize(path) > limit:
                return None
            with open(path, 'rb') as f:
                return f.read().lower()
        except OSError:
            return None

    def _index(self, kind, folder, files, limit, pex=False):
        key = (kind, folder)
        if key not in self._dirs:
            idx = {}
            for path in files:
                data = self._read(path, limit)
                if data is None:
                    continue
                flags = (b'getformfromfile' in data, b'getmodbyname' in data) if pex else ()
                for n in _plugin_names_in(data, stray_prefix=pex):
                    idx.setdefault(n, []).append((path, flags))
            self._dirs[key] = idx
        return self._dirs[key]

    @staticmethod
    def _key(name):
        return name.lower().encode('cp1252', 'replace')

    def scripts(self, dirs, plugin_name):
        """[(path, uses GetFormFromFile, uses GetModByName)] of compiled scripts
        (.pex) naming the plugin. Hard-coded FormIDs break when the plugin is
        compacted; GetModByName returns 0x100+ for light plugins, which breaks
        scripts that compare it with 255 or build FormIDs from it."""
        out = []
        for base in dirs:
            sdir = _exists_ci(base, 'Scripts')
            if not sdir:
                continue
            try:
                files = [os.path.join(sdir, n) for n in os.listdir(sdir) if n.lower().endswith('.pex')]
            except OSError:
                continue
            idx = self._index('pex', sdir, files, MAX_CONFIG_SIZE, pex=True)
            out += [(p, g, m) for p, (g, m) in idx.get(self._key(plugin_name), [])]
        return out

    def configs(self, dirs, plugin_name, deep=False):
        """Text config files (SKSE plugin INIs, JSON, SPID/KID...) naming the plugin."""
        out = []
        for base in dirs:
            if deep:
                roots = [base]
            else:
                roots = []
                key = ('cfg-root', base)
                if key not in self._dirs:
                    try:
                        files = [os.path.join(base, n) for n in os.listdir(base)
                                 if n.lower().endswith(CONFIG_EXTS) and os.path.isfile(os.path.join(base, n))]
                    except OSError:
                        files = []
                    self._index('cfg-root', base, files, MAX_CONFIG_SIZE)
                out += [p for p, _f in self._dirs[key].get(self._key(plugin_name), [])]
                skse = _exists_ci(base, 'SKSE')
                if skse:
                    roots.append(skse)
            for root in roots:
                key = ('cfg-tree', root)
                if key not in self._dirs:
                    files = [os.path.join(dp, n) for dp, _dn, fn in os.walk(root) for n in fn
                             if n.lower().endswith(CONFIG_EXTS)]
                    self._index('cfg-tree', root, files, MAX_CONFIG_SIZE)
                out += [p for p, _f in self._dirs[key].get(self._key(plugin_name), [])]
        return list(dict.fromkeys(out))

    def dlls(self, plugin_name):
        """SKSE plugin DLLs that contain the plugin's name (narrow or UTF-16)."""
        out = []
        for d, _label in self.model.search_dirs:
            sp = _exists_ci(d, 'SKSE', 'Plugins')
            if not sp:
                continue
            try:
                files = [os.path.join(sp, n) for n in os.listdir(sp) if n.lower().endswith('.dll')]
            except OSError:
                continue
            idx = self._index('dll', sp, files, MAX_DLL_SIZE)
            out += [os.path.basename(p) for p, _f in idx.get(self._key(plugin_name), [])]
        return list(dict.fromkeys(out))


def _bsa_assets(model, entry, kinds):
    """Paths inside the plugin's own BSAs (<stem>.bsa, '<stem> - Textures.bsa')
    under FaceGenData/<plugin>, Sound/Voice/<plugin> or Seq/<plugin>.seq."""
    from .strings import BSA
    from .core import EspError
    stem = os.path.splitext(entry.name)[0]
    low = entry.name.lower()
    out = []
    for d in _plugin_dirs(model, entry):
        for bn in (stem + '.bsa', stem + ' - Textures.bsa'):
            p = _exists_ci(d, bn)
            if not p:
                continue
            try:
                names = BSA(p).list()
            except (EspError, OSError, ValueError, IndexError, struct.error):
                continue            # damaged archive: skip it (this check is advisory)
            for n in names:
                nl = n.lower().replace('/', '\\')
                if 'facegen' in kinds and ('facegendata\\facegeom\\' + low + '\\' in nl or
                                           'facegendata\\facetint\\' + low + '\\' in nl):
                    out.append(f'{os.path.basename(p)}: {n}')
                elif 'voice' in kinds and nl.startswith('sound\\voice\\' + low + '\\'):
                    out.append(f'{os.path.basename(p)}: {n}')
                elif 'seq' in kinds and nl == 'seq\\' + stem.lower() + '.seq':
                    out.append(f'{os.path.basename(p)}: {n}')
                if len(out) > 5:
                    return out
    return out


def _game_supports_171(model):
    """True / False / None (unknown): can the game load header 1.71 plugins?"""
    if model.is_vr:
        return False
    if model.game_version:
        if tuple(model.game_version[:3]) >= V_CREATIONS:
            return True
        bees = model.ev.find('SKSE/Plugins/BackportedESLSupport.dll') if model.search_dirs else None
        return True if bees else (False if bees is False else None)
    return None


def _engine_fixes_cell_fix(model):
    """True if SSE Engine Fixes 7.0.14+ (fixes the ESL cell bugs) is installed,
    False if it is not, None if unknown."""
    if not model.search_dirs:
        return None
    p = model.ev.find('SKSE/Plugins/EngineFixes.dll')
    if not p:
        return p
    v = mlist.pe_version(p)
    if not v:
        return None
    return tuple(v[0][:3]) >= V_EF_CELL_FIX


def analyse(model, configs=False, deep_configs=False):
    """Return [EslCandidate] for active, non-official plugins."""
    order = model.effective_order()
    names = model.by_name()
    dependents = {}
    for e in order:
        if e.scan is None:
            continue
        for m in e.scan.masters:
            dependents.setdefault(m.lower(), []).append(e)
    supports_171 = _game_supports_171(model)
    vr_esl = True
    if model.is_vr:
        supports_171 = False          # header 1.71 is a flat-game (1.6.1130+) feature
        vr_esl = bool(model.ev.find('SKSE/Plugins/skyrimvresl.dll')) if model.search_dirs else None
    ef_fix = None
    mentions = _Mentions(model)
    out = []
    for e in order:
        s = e.scan
        if s is None or e.implicit:
            continue
        c = EslCandidate(e)
        ids = s.new_ids()
        c.n_new = len(ids)
        if ids:
            c.id_range = f'{min(ids):06X}-{max(ids):06X}'
        deps = dependents.get(e.low, [])
        c.dependents = [d.name for d in deps]
        if s.is_light:
            c.verdict = 'already'
            lo_b = 0x000 if s.hedr_version >= 1.705 else 0x800
            bad = [i for i in ids if i < lo_b or i > 0xFFF]
            if bad:
                c.risks.append(f'INVALID: {len(bad)} new record(s) outside {lo_b:03X}-FFF; remove the flag or '
                               'compact it (breaks saves)')
            out.append(c)
            continue
        if model.is_generated(e):
            c.verdict = 'no'
            c.reasons.append('generated patch: it is rebuilt by its tool (set the ESL option there if it has one)')
            out.append(c)
            continue
        if vr_esl is not True:
            c.verdict = 'no'
            c.reasons.append('Skyrim VR loads light plugins only with Skyrim VR ESL Support (SKSE plugin, Nexus '
                             'SSE 106712)' + (', which was not found' if vr_esl is False else '') +
                             '; install it before ESL-flagging anything')
            out.append(c)
            continue
        new_sigs = {}
        for fid, sig, _ in s.records():
            if (fid >> 24) == s.self_index:
                new_sigs[sig] = new_sigs.get(sig, 0) + 1
        nonmaster_deps = [m for m in s.masters
                          if names.get(m.lower()) is not None and names[m.lower()].scan is not None
                          and not names[m.lower()].scan.is_master_like]
        if s.is_master_like and nonmaster_deps:
            c.verdict = 'no'
            c.reasons.append(f'it is a master that needs the regular plugin(s) {", ".join(nonmaster_deps[:3])}; a '
                             'light master may not depend on regular plugins')
            out.append(c)
            continue
        if new_sigs.get('WRLD'):
            c.verdict = 'no'
            c.reasons.append(f'adds {new_sigs["WRLD"]} new worldspace(s): light plugins can lose the landscape of '
                             'new worldspaces (not fixed by any engine fix); keep it a full plugin')
            out.append(c)
            continue
        if new_sigs.get('CELL'):
            if ef_fix is None:
                ef_fix = _engine_fixes_cell_fix(model)
            cell_note = (f'adds {new_sigs["CELL"]} new cell(s): light plugins lose temporary references in new cells '
                         'that other plugins override, and interior cells reload wrongly; SSE Engine Fixes '
                         '7.0.14+ (bESLCELLLoadBug) fixes this')
            if ef_fix is not True:
                c.verdict = 'no'
                c.reasons.append(cell_note + ('; Engine Fixes 7.0.14+ was not found' if ef_fix is False else
                                              '; could not check for Engine Fixes, so keep it a full plugin'))
                out.append(c)
                continue
            c.risks.append(cell_note + ' (installed; keep bESLCELLLoadBug enabled)')
        hedr171 = s.hedr_version >= 1.705
        lo_bound = 0x001 if hedr171 else 0x800
        max_new = 0xFFF - lo_bound + 1
        has_sky = 'skyrim.esm' in [m.lower() for m in s.masters]
        # IDs 001-7FF would read as hardcoded engine forms in any file where this
        # plugin is master index 00 (a dependent that lists it first)
        ok_deps = all(d.scan is not None and d.scan.hedr_version >= 1.705 and d.scan.masters
                      and d.scan.masters[0].lower() != e.low for d in deps)
        can_171 = supports_171 is not False and has_sky and ok_deps     # may use 001-7FF after header 1.71
        cap = 0xFFF if (hedr171 or can_171) else 0x800
        if c.n_new > cap:
            c.verdict = 'no'
            c.reasons.append(f'{c.n_new} new records; a light plugin holds at most 2048 (4095 with header 1.71 '
                             'on game 1.6.1130+ or BEES, when the plugin and its dependents qualify)')
            out.append(c)
            continue
        in_range = all(lo_bound <= i <= 0xFFF for i in ids)
        fits_171 = all(0x001 <= i <= 0xFFF for i in ids)
        # risks of flagging alone
        dirs = _plugin_dirs(model, e)
        flag_risks = []
        seq = None
        for d in dirs:
            seq = seq or _exists_ci(d, 'Seq', os.path.splitext(e.name)[0] + '.seq')
        if not seq and new_sigs.get('QUST'):
            seq = (_bsa_assets(model, e, ('seq',)) or [None])[0]
        if seq:
            flag_risks.append('has a SEQ file: its start-game dialogue may not work until you save and reload')
        pex = mentions.scripts(dirs, e.name) if (s.has_scripts or new_sigs.get('QUST')) else []
        if any(m for _p, _g, m in pex):
            flag_risks.append('a script calls GetModByName on it: for light plugins it returns 0x100 or more, so '
                              'scripts that compare the result with 255 or build FormIDs from it break')
        if in_range and c.n_new <= max_new:
            c.verdict = 'flag'
            c.reasons.append(f'all {c.n_new} new record(s) use object IDs {lo_bound:03X}-FFF: set the ESL flag, '
                             'no FormIDs change' if c.n_new else 'no new records (only overrides): set the ESL flag')
            if hedr171 and supports_171 is not True:
                c.risks.append('header 1.71: needs game 1.6.1130+ or BEES')
            if hedr171 and ids and min(ids) < 0x800 and not (has_sky and ok_deps):
                old = [d.name for d in deps if d.scan is not None and d.scan.hedr_version < 1.705]
                c.risks.append('uses object IDs below 0x800: valid only with Skyrim.esm as a master and with '
                               'header-1.71 dependents' + (f' ({", ".join(old[:4])} are not 1.71)' if old else ''))
            if deps:
                c.reasons.append(f'{len(deps)} plugin(s) use it as a master; they keep working (FormIDs do not change)')
            c.risks += flag_risks
            out.append(c)
            continue
        if fits_171 and not hedr171 and supports_171 is not False:
            # fits in 0x001-0xFFF, which is valid only with header 1.71
            if has_sky and ok_deps:
                c.verdict = 'flag-171'
                c.reasons.append(f'new records use object IDs {c.id_range}, valid for a light plugin only with '
                                 'header 1.71: set header 1.71 and the ESL flag (no FormIDs change)')
                c.risks.append('header 1.71 needs game 1.6.1130+ (or BEES on older games)'
                               if supports_171 is None else 'header 1.71: older game versions crash without BEES')
                c.risks += flag_risks
                out.append(c)
                continue
        # needs compaction
        c.reasons.append(f'{c.n_new} new record(s) with object IDs {c.id_range}: needs FormID compaction '
                         '(renumbering) first; existing saves will not work with it afterwards')
        if c.n_new > 0x800:
            c.reasons.append('more than 2048 new records: compaction must start at 0x001 and the plugin needs '
                             'header 1.71 (esp compact <plugin> --start 0x001, then esp esl <plugin> --header-171 '
                             '--flag; ESLifier does this by default)')
        hard = []
        if new_sigs.get('NPC_'):
            for d in dirs:
                fg = _exists_ci(d, 'meshes', 'actors', 'character', 'FaceGenData', 'FaceGeom', e.name)
                if fg:
                    c.files.append(fg)
            c.files += _bsa_assets(model, e, ('facegen',))
            c.risks.append(f'{new_sigs["NPC_"]} new NPC(s): FaceGen meshes/tints are named after their FormIDs '
                           '(dark-face bug if not renamed)')
        if new_sigs.get('INFO'):
            for d in dirs:
                vo = _exists_ci(d, 'sound', 'voice', e.name)
                if vo:
                    c.files.append(vo)
            c.files += _bsa_assets(model, e, ('voice',))
            c.risks.append(f'{new_sigs["INFO"]} new dialogue response(s): voice files are named after INFO '
                           'FormIDs (silent dialogue if not renamed)')
        if seq:
            c.risks.append('its SEQ file lists quest FormIDs and must be regenerated')
        if deps:
            c.risks.append(f'master of {len(deps)} plugin(s) ({", ".join(c.dependents[:5])}'
                           f'{"..." if len(deps) > 5 else ""}): they must be patched to the new FormIDs, and again '
                           'after every update')
        hard_pex = [p for p, g, _m in pex if g]
        if hard_pex:
            c.files += hard_pex
            c.risks.append(f'{len(hard_pex)} compiled script(s) call GetFormFromFile with "{e.name}" (hard-coded '
                           'FormIDs)')
        if configs:
            cfg = mentions.configs(dirs if not model.search_dirs else [d for d, _ in model.search_dirs],
                                   e.name, deep=deep_configs)
            if cfg:
                c.files += cfg
                c.risks.append(f'{len(cfg)} config file(s) mention it (SPID/KID/BOS/OAR... use its FormIDs)')
        dll = mentions.dlls(e.name)
        if dll:
            hard.append(f'SKSE plugin(s) {", ".join(dll[:3])} contain its name and may hard-code its FormIDs '
                        '(ESLifier does not patch DLLs; compacting would need an updated DLL)')
        if new_sigs.get('WTHR'):
            c.risks.append(f'{new_sigs["WTHR"]} new weather(s): ENB weather files refer to their FormIDs '
                           '(no tool patches them; fix the ENB weather list by hand)')
        if hard:
            c.verdict = 'no'
            c.reasons += hard
        else:
            c.verdict = 'compact-care' if c.risks else 'compact'
        out.append(c)
    return out


def procedure(game_supports_171=None):
    """Step list for turning plugins light (flag first, compact with ESLifier)."""
    steps = [
        'Back up the profile, the plugins and your saves; best done before starting a playthrough '
        '(flagging plugins used by an ongoing save is disputed; compacting needs a new game).',
        'Flag-only first (no FormIDs change): esp esl <plugin> --flag, Vortex "Mark light", or ESLifier\'s '
        'left list. Keep the .esp extension so the load-order position stays the same. Note: ESLifier also '
        'writes header 1.71 when flagging (its 1.71 option is on by default).',
        'Compact only when you need more slots, and only with ESLifier (it renames FaceGen/voice files and patches '
        'scripts, SEQ files, ~100 SKSE config formats and dependent plugins). Install its output as a mod that '
        'wins conflicts, and run its "Scan and Rebuild" after any mod change. (xEdit\'s "Compact FormIDs for '
        'ESL" only renumbers the plugin and plugins loaded with it, and is hidden once a plugin is light: '
        'compact first, then flag.)',
        'Re-sort (LOOT) and re-generate Bashed/Smashed/Synthesis/DynDOLOD output afterwards; test faces, '
        'dialogue and cells in game.',
    ]
    if game_supports_171 is not True:
        steps.append('Header 1.71 plugins (ESLifier\'s default, xEdit 4.1.5+) need game 1.6.1130+; on older '
                     'games install Backported Extended ESL Support (BEES) or turn the 1.71 option off.')
    return steps
