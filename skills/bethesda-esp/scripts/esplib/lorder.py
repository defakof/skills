"""Load-order model for Skyrim SE: where the order comes from (plugins.txt,
MO2 profiles, explicit lists), what the game actually does with it
(hardcoded plugins, Creation Club, master partition and hoisting, light
plugins), validation (hard rules, limits, LOOT masterlist checks), and a
LOOT-style sort that changes the current order as little as possible.

Only plugins (.esp/.esm/.esl) are considered here; BSA archives are not.
"""

import os
import re

from .core import EspError
from .scan import scan_file
from . import masterlist as mlist

# Always loaded first, in this order, when present (the game forces them).
HARDCODED = ['Skyrim.esm', 'Update.esm', 'Dawnguard.esm', 'HearthFires.esm', 'Dragonborn.esm']
HARDCODED_LOW = [h.lower() for h in HARDCODED]
# Present since game 1.6.1130 (Creations update); the last line of Skyrim.ccc.
RESOURCE_PACK = '_ResourcePack.esl'
# Skyrim.ccc as of 2024-04-30 (Wrye Bash's fallback copy), used only when the
# real file is missing.
CCC_FALLBACK = [
    'ccASVSSE001-ALMSIVI.esm', 'ccBGSSSE001-Fish.esm', 'ccBGSSSE002-ExoticArrows.esl', 'ccBGSSSE003-Zombies.esl',
    'ccBGSSSE004-RuinsEdge.esl', 'ccBGSSSE005-Goldbrand.esl', 'ccBGSSSE006-StendarsHammer.esl',
    'ccBGSSSE007-Chrysamere.esl', 'ccBGSSSE010-PetDwarvenArmoredMudcrab.esl', 'ccBGSSSE011-HrsArmrElvn.esl',
    'ccBGSSSE012-HrsArmrStl.esl', 'ccBGSSSE014-SpellPack01.esl', 'ccBGSSSE019-StaffofSheogorath.esl',
    'ccBGSSSE020-GrayCowl.esl', 'ccBGSSSE021-LordsMail.esl', 'ccMTYSSE001-KnightsoftheNine.esl',
    'ccQDRSSE001-SurvivalMode.esl', 'ccTWBSSE001-PuzzleDungeon.esm', 'ccEEJSSE001-Hstead.esm',
    'ccQDRSSE002-Firewood.esl', 'ccBGSSSE018-Shadowrend.esl', 'ccBGSSSE035-PetNHound.esl',
    'ccFSVSSE001-Backpacks.esl', 'ccEEJSSE002-Tower.esl', 'ccEDHSSE001-NorJewel.esl', 'ccVSVSSE002-Pets.esl',
    'ccBGSSSE037-Curios.esl', 'ccBGSSSE034-MntUni.esl', 'ccBGSSSE045-Hasedoki.esl', 'ccBGSSSE008-Wraithguard.esl',
    'ccBGSSSE036-PetBWolf.esl', 'ccFFBSSE001-ImperialDragon.esl', 'ccMTYSSE002-VE.esl',
    'ccBGSSSE043-CrossElv.esl', 'ccVSVSSE001-Winter.esl', 'ccEEJSSE003-Hollow.esl', 'ccBGSSSE016-Umbra.esm',
    'ccBGSSSE031-AdvCyrus.esm', 'ccBGSSSE038-BowofShadows.esl', 'ccBGSSSE040-AdvObGobs.esl',
    'ccBGSSSE050-BA_Daedric.esl', 'ccBGSSSE052-BA_Iron.esl', 'ccBGSSSE054-BA_Orcish.esl',
    'ccBGSSSE058-BA_Steel.esl', 'ccBGSSSE059-BA_Dragonplate.esl', 'ccBGSSSE061-BA_Dwarven.esl',
    'ccPEWSSE002-ArmsOfChaos.esl', 'ccBGSSSE041-NetchLeather.esl', 'ccEDHSSE002-SplKntSet.esl',
    'ccBGSSSE064-BA_Elven.esl', 'ccBGSSSE063-BA_Ebony.esl', 'ccBGSSSE062-BA_DwarvenMail.esl',
    'ccBGSSSE060-BA_Dragonscale.esl', 'ccBGSSSE056-BA_Silver.esl', 'ccBGSSSE055-BA_OrcishScaled.esl',
    'ccBGSSSE053-BA_Leather.esl', 'ccBGSSSE051-BA_DaedricMail.esl', 'ccBGSSSE057-BA_Stalhrim.esl',
    'ccBGSSSE066-Staves.esl', 'ccBGSSSE067-DaedInv.esm', 'ccBGSSSE068-Bloodfall.esl', 'ccBGSSSE069-Contest.esl',
    'ccVSVSSE003-NecroArts.esl', 'ccVSVSSE004-BeAFarmer.esl', 'ccBGSSSE025-AdvDSGS.esm',
    'ccFFBSSE002-CrossbowPack.esl', 'ccBGSSSE013-Dawnfang.esl', 'ccRMSSSE001-NecroHouse.esl',
    'ccEDHSSE003-Redguard.esl', 'ccEEJSSE004-Hall.esl', 'ccEEJSSE005-Cave.esm', 'ccKRTSSE001_Altar.esl',
    'ccCBHSSE001-Gaunt.esl', 'ccAFDSSE001-DweSanctuary.esm', RESOURCE_PACK,
]

PLUGIN_EXTS = ('.esp', '.esm', '.esl')

# Generated / "load last" plugins recognised by name (lowercase regex). Used
# for checks, and for sorting when no LOOT metadata is loaded.
LATE_LOADERS = [
    (r'^bashed patch.*\.esp$', 'Wrye Bash Bashed Patch'),
    (r'^smashed patch.*\.esp$', 'Mator Smash patch'),
    (r'^zpatch.*\.esp$', 'zEdit/zMerge generated patch'),
    (r'^sse ?merged\.esp$', 'generated merge'),
    (r'^synthesis.*\.esp$', 'Synthesis output'),
    (r'^(parallaxgen|pg_\d+)\.esp$', 'ParallaxGen output'),
    (r'^dyndolod.*\.es[mp]$', 'DynDOLOD output'),
    (r'^occlusion\.esp$', 'DynDOLOD/xLODGen occlusion'),
    (r'^npc appearances merged\.esp$', 'EasyNPC output'),
]
GENERATED_GROUPS = ('Dynamic Patches', 'Late Fixes & Changes', 'Dynamic LOD')
# Build/load order of generated patches: Bashed/Smashed, then Synthesis, then LOD.
GENERATED_RANK = [
    (r'^(bashed patch.*|smashed patch.*|zpatch.*|sse ?merged)\.esp$', 1, 'Bashed/Smashed patches'),
    (r'^(synthesis.*|parallaxgen|pg_\d+)\.esp$', 2, 'Synthesis / ParallaxGen output'),
    (r'^(dyndolod.*\.es[mp]|occlusion\.esp)$', 3, 'DynDOLOD / occlusion'),
]


def generated_rank(name):
    n = name.lower()
    for rx, rank, label in GENERATED_RANK:
        if re.match(rx, n):
            return rank, label
    return None, None

# Game versions: native support for header 1.71 / small ESL FormIDs.
V_CREATIONS = (1, 6, 1130)


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

def _read_text(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1')


def _read_lines(path):
    out = []
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        out.append(line)
    return out


def read_plugins_txt(path):
    """[(name, active)] from a Skyrim SE / MO2 / Vortex plugins.txt ('*' = active)."""
    out = []
    for line in _read_lines(path):
        active = line.startswith('*')
        name = (line[1:] if active else line).strip()
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


def appdata_folder(game_dir=None):
    """The %LOCALAPPDATA% folder name the game uses (Steam / GOG / Epic / MS Store)."""
    if game_dir and os.path.isdir(game_dir):
        names = {n.lower() for n in os.listdir(game_dir)}
        if 'skyrimvr.exe' in names:
            return 'Skyrim VR'
        if 'galaxy64.dll' in names:
            return 'Skyrim Special Edition GOG'
        if 'eossdk-win64-shipping.dll' in names:
            return 'Skyrim Special Edition EPIC'
        if 'appxmanifest.xml' in names:
            return 'Skyrim Special Edition MS'
    return 'Skyrim Special Edition'


def default_plugins_txt_candidates(game_dir=None):
    """Likely plugins.txt locations (Windows, or a Proton prefix on Linux)."""
    folders = [appdata_folder(game_dir)] + [n for n in ('Skyrim Special Edition', 'Skyrim Special Edition GOG',
                                                         'Skyrim Special Edition EPIC', 'Skyrim Special Edition MS')
                                            if n != appdata_folder(game_dir)]
    bases = []
    if os.environ.get('LOCALAPPDATA'):
        bases.append(os.environ['LOCALAPPDATA'])
    home = os.path.expanduser('~')
    for steam in ('.steam/steam', '.local/share/Steam', '.var/app/com.valvesoftware.Steam/.local/share/Steam'):
        bases.append(os.path.join(home, steam, 'steamapps/compatdata/489830/pfx/drive_c/users/steamuser/'
                                               'AppData/Local'))
    out = []
    for b in bases:
        for n in folders:
            for fn in ('Plugins.txt', 'plugins.txt'):
                out.append(os.path.join(b, n, fn))
    return out


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


def _ver_str(v):
    return '.'.join(str(x) for x in v) if v else '?'


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
        self.game_dir = None
        self.game_version = None   # SkyrimSE.exe file version tuple, if found
        self.is_vr = False         # SkyrimVR.exe next to the Data folder
        self.source_desc = ''
        self.manager = None        # 'MO2' | 'Vortex' | None
        self.issues = []
        self.ccc = []
        self.ccc_source = None
        self.unlisted = []         # plugin files found in the data folders but not in plugins.txt
        self.meta = None           # masterlist.Metadata (LOOT masterlist + userlist)
        self.meta_error = None
        self._ev = None

    # -- construction ------------------------------------------------------
    @classmethod
    def from_sources(cls, plugins=None, data=None, plugins_txt=None, loadorder_txt=None,
                     mo2_profile=None, mods_dir=None, ccc=None, scan=True, use_cache=True,
                     auto=True, masterlist=None, userlist=None, use_metadata=True):
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
            lo.manager = 'MO2'
        if data:
            lo.data_dir = os.path.abspath(data)
            lo.search_dirs.append((lo.data_dir, 'Data'))
            lo.game_dir = os.path.dirname(lo.data_dir)
            exe = os.path.join(lo.game_dir, 'SkyrimSE.exe')
            vr_exe = os.path.join(lo.game_dir, 'SkyrimVR.exe')
            if os.path.isfile(exe):
                pv = mlist.pe_version(exe)
                lo.game_version = pv[0] if pv else None
            elif os.path.isfile(vr_exe):
                lo.is_vr = True
        if plugins:
            # explicit list: files or names, in load order, all active
            for p in plugins:
                if os.path.isfile(p):
                    d = os.path.dirname(os.path.abspath(p))
                    if all(d != x for x, _ in lo.search_dirs):
                        lo.search_dirs.append((d, os.path.basename(d) or d))
                    listed.append((os.path.basename(p), True))
                else:
                    listed.append((p, True))
            lo.source_desc = lo.source_desc or 'command-line list'
        else:
            if not plugins_txt and auto and not (loadorder_txt and os.path.isfile(loadorder_txt)):
                cands = ([os.path.join(lo.data_dir, 'plugins.txt')] if lo.data_dir else []) + \
                    default_plugins_txt_candidates(lo.game_dir)
                for cand in cands:
                    if os.path.isfile(cand):
                        plugins_txt = cand
                        break
            if plugins_txt:
                listed = read_plugins_txt(plugins_txt)
                lo.source_desc = lo.source_desc or f'plugins.txt {plugins_txt}'
                if lo.manager is None and 'vortex' in _read_text(plugins_txt)[:300].lower():
                    lo.manager = 'Vortex'
                if loadorder_txt and os.path.isfile(loadorder_txt):
                    lo._check_desync(plugins_txt, loadorder_txt, listed)
            elif loadorder_txt and os.path.isfile(loadorder_txt):
                listed = [(n, True) for n in read_loadorder_txt(loadorder_txt)]
                lo.source_desc = f'loadorder.txt {loadorder_txt} (no plugins.txt: every plugin treated as active)'
                lo.issues.append(Issue('warning', 'no-plugins-txt', None,
                                       'Only loadorder.txt was given; Skyrim SE ignores it and reads plugins.txt. '
                                       'All listed plugins are treated as active.',
                                       'Pass --plugins-txt as well.'))
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
        # Creation Club list (Skyrim.ccc sits next to SkyrimSE.exe)
        if ccc is None and lo.game_dir:
            cand = os.path.join(lo.game_dir, 'Skyrim.ccc')
            ccc = cand if os.path.isfile(cand) else None
        if ccc and os.path.isfile(ccc):
            lo.ccc = read_ccc(ccc)
            lo.ccc_source = ccc
        elif lo.data_dir and not lo.is_vr:
            lo.ccc = list(CCC_FALLBACK)
            lo.ccc_source = 'built-in copy (Skyrim.ccc not found)'
        lo._build_entries(listed)
        if not plugins and (plugins_txt or lo.data_dir):
            lo._find_unlisted()
        if scan:
            lo.scan_all(use_cache)
        if use_metadata and not (masterlist == 'none' and not userlist):
            lo.load_metadata(masterlist, userlist)
        return lo

    def load_metadata(self, masterlist=None, userlist=None):
        """Attach LOOT metadata (bundled/updated masterlist + the user's userlist)."""
        if userlist is None:
            found = mlist.find_userlists()
            pick = [p for p, who in found if who == ('Vortex' if self.manager == 'Vortex' else 'LOOT')]
            userlist = (pick or [p for p, _ in found] or [None])[0]
        try:
            self.meta = mlist.Metadata.load(masterlist, userlist or None)
        except Exception as ex:  # noqa: BLE001 - metadata is optional; report and continue
            self.meta = None
            self.meta_error = f'could not load LOOT metadata: {ex}'
        self._ev = None

    @property
    def ev(self):
        if self._ev is None:
            self._ev = mlist.Evaluator(self)
        return self._ev

    def _check_desync(self, plugins_txt, loadorder_txt, listed):
        lo_names = [n.lower() for n in read_loadorder_txt(loadorder_txt)]
        pos = {n: i for i, n in enumerate(lo_names)}
        seq = [n.lower() for n, _a in listed if n.lower() in pos]
        bad = [(a, b) for a, b in zip(seq, seq[1:]) if pos[a] > pos[b]]
        if bad:
            newer = 'loadorder.txt' if os.path.getmtime(loadorder_txt) > os.path.getmtime(plugins_txt) \
                else 'plugins.txt'
            self.issues.append(Issue(
                'warning', 'lo-desync', None,
                f'plugins.txt and loadorder.txt disagree (e.g. {bad[0][0]} / {bad[0][1]}); the game uses plugins.txt'
                + ('; MO2 reloads the newer loadorder.txt on start and will overwrite plugins.txt'
                   if self.manager == 'MO2' and newer == 'loadorder.txt' else ''),
                'Re-sort or save the order in the mod manager so both files match.'))

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
        # implicit plugins: hardcoded, then CC plugins in Skyrim.ccc order (incl. _ResourcePack.esl)
        hard = HARDCODED + (['SkyrimVR.esm'] if self.is_vr else [])
        implicit = [(h, 'hardcoded') for h in hard] + [(c, 'cc') for c in self.ccc]
        for name, kind in implicit:
            if name.lower() in seen:
                continue
            path, label = self.find_path(name)
            if path is None and kind == 'cc':
                continue
            e = Entry(name, path, True, None, kind, label)
            seen[name.lower()] = e
            entries.append(e)
        dup = set()
        for i, (name, active) in enumerate(listed):
            low = name.lower()
            if low in seen:
                e = seen[low]
                if e.listed is not None:
                    dup.add(name)           # the game uses the last line
                e.listed = i
                if e.implicit is None:
                    e.active = active
                continue
            path, label = self.find_path(name)
            e = Entry(name, path, active, i, None, label)
            seen[low] = e
            entries.append(e)
        for name in sorted(dup):
            self.issues.append(Issue('warning', 'duplicate-entry', name,
                                     f'{name} is listed more than once in the load order file',
                                     'Remove the extra line (or let the mod manager rewrite the file).'))
        self.entries = entries

    def _find_unlisted(self):
        known = {e.low for e in self.entries}
        found = {}
        for d, label in self.search_dirs:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                if not is_plugin_name(n) or n.lower().endswith('.ghost'):
                    continue
                if n.lower() not in known and n.lower() not in found and os.path.isfile(os.path.join(d, n)):
                    found[n.lower()] = (n, label)
        self.unlisted = sorted(found.values(), key=lambda t: t[0].lower())

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
        """What the game loads, in order: hardcoded, Creation Club (Skyrim.ccc
        order), then the listed active plugins with masters (ESM flag or
        .esm/.esl) before regular plugins, and any plugin that a master
        depends on hoisted to just before it, as the game does."""
        act = self.active()
        hard = sorted([e for e in act if e.implicit == 'hardcoded'],
                      key=lambda e: HARDCODED_LOW.index(e.low) if e.low in HARDCODED_LOW else len(HARDCODED_LOW))
        cc = [e for e in act if e.implicit == 'cc']
        rest = [e for e in act if not e.implicit]
        rest.sort(key=lambda e: e.listed if e.listed is not None else 10 ** 6)
        masters = [e for e in rest if self.is_master_like(e)]
        regular = [e for e in rest if not self.is_master_like(e)]
        return self._hoist(hard + cc + masters + regular)

    def _hoist(self, order):
        order = list(order)
        i = 0
        guard = 0
        while i < len(order) and guard < 100000:
            guard += 1
            e = order[i]
            if self.is_master_like(e) and e.scan is not None:
                pos = {x.low: j for j, x in enumerate(order)}
                later = [order[pos[m.lower()]] for m in e.scan.masters if pos.get(m.lower(), -1) > i]
                if later:
                    for m in later:
                        order.remove(m)
                    order[i:i] = later
                    continue          # re-check the hoisted plugins' own masters
            i += 1
        return order

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

    def max_full(self, order=None):
        order = order or self.effective_order()
        return 254 if any(self.is_light(e) for e in order) else 255

    def group_of(self, e):
        """LOOT group; generated patches the masterlist does not know by name
        (Synthesis_2.esp, Bashed Patch, 1.esp...) get their tool's group."""
        if not self.meta:
            return None
        g = self.meta.for_plugin(e.name).group
        if g == 'default':
            rank, _label = generated_rank(e.name)
            if rank:
                g = GENERATED_GROUPS[rank - 1]
        return g

    def is_generated(self, e):
        if late_loader_reason(e.name):
            return True
        return bool(self.meta and self.group_of(e) in GENERATED_GROUPS)

    def tags_of(self, e):
        """Bash Tags (plugin description, LOOT metadata, Data/BashTags/<plugin>.txt)."""
        lines = None
        if self.search_dirs:
            p = self.ev.find('BashTags/' + os.path.splitext(e.name)[0] + '.txt')
            if p:
                try:
                    with open(p, encoding='utf-8-sig', errors='replace') as f:
                        lines = f.read().splitlines()
                except OSError:
                    lines = None
        return mlist.bash_tags(self.meta.for_plugin(e.name) if self.meta else None, self.ev,
                               e.scan.description if e.scan else '', lines)

    # -- validation -----------------------------------------------------------
    def validate(self):
        issues = list(self.issues)
        if self.meta_error:
            issues.append(Issue('info', 'no-metadata', None, self.meta_error))
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
            if e.active and not e.implicit:
                try:
                    e.name.encode('cp1252')
                except UnicodeEncodeError:
                    issues.append(Issue('warning', 'bad-filename', e.name,
                                        f'{e.name}: the name has characters plugins.txt (Windows-1252) cannot store, '
                                        'so the game cannot activate it',
                                        'Rename the plugin (and patches that use it as a master) to plain characters.'))
        for h in HARDCODED[:2]:
            if h.lower() not in names or not names[h.lower()].path:
                issues.append(Issue('error', 'missing-base-master', h, f'{h} was not found in the Data folder',
                                    'Point --data at the game Data folder (or verify game files).'))
        if self.data_dir and self.ccc_source and 'built-in' in self.ccc_source:
            issues.append(Issue('info', 'no-ccc', None,
                                'Skyrim.ccc was not found next to the Data folder; a built-in copy of the Creation '
                                'Club order (2024-04) was used', 'Pass --ccc <game folder>/Skyrim.ccc.'))
        for n, label in self.unlisted:
            issues.append(Issue('info', 'unlisted', n,
                                f'{n} ({label}) is installed but not in plugins.txt, so it is inactive and its '
                                'position is undefined (LOOT: "ambiguous load order")',
                                'Enable or disable it in the mod manager so it gets a position.'))
        n_full = n_light = 0
        hedr171 = []
        for e in order:
            s = e.scan
            if s is None:
                continue
            if self.is_light(e):
                n_light += 1
            else:
                n_full += 1
            pmeta = self.meta.for_plugin(e.name) if self.meta else None
            tags = self.tags_of(e) if pmeta else []
            filter_patch = 'Filter' in tags or re.search(r'\{\{\s*BASH\s*:[^}]*\bFilter\b', s.description or '', re.I)
            # masters
            if any(m.lower() == e.low for m in s.masters):
                issues.append(Issue('error', 'self-master', e.name, f'{e.name} lists itself as a master',
                                    'The plugin header is broken; get a fixed version.'))
            for m in s.masters:
                me = names.get(m.lower())
                if me is None or not me.path:
                    if filter_patch:
                        continue
                    issues.append(Issue('error', 'missing-master', e.name,
                                        f'{e.name} requires {m}, which is not installed (the game will crash on start)',
                                        f'Install {m} (check the mod page requirements) or disable {e.name}.',
                                        [m]))
                elif not (me.active or me.implicit):
                    if filter_patch:
                        continue
                    issues.append(Issue('error', 'inactive-master', e.name,
                                        f'{e.name} requires {m}, which is installed but not active (crash on start)',
                                        f'Activate {m} or disable {e.name}.', [m]))
                elif self.is_master_like(e) and not self.is_master_like(me):
                    light = ' light' if self.is_light(e) else ''
                    issues.append(Issue('error', 'master-needs-nonmaster', e.name,
                                        f'{e.name} is a{light} master (ESM flag or .esm/.esl) but requires the '
                                        f'regular plugin {m}; the game hoists {m} into the master block, which '
                                        'changes what wins conflicts, and LOOT refuses to sort',
                                        f'Use an ESM-flagged version of {m}, or remove the ESM flag from {e.name} '
                                        '(if it is an .esp).', [m]))
                elif pos.get(m.lower(), -1) > pos[e.low]:
                    issues.append(Issue('error', 'master-order', e.name,
                                        f'{e.name} loads before its master {m} (behaviour undefined: lost '
                                        'overrides or a crash)',
                                        f'Move {e.name} below {m} (see the suggested order).', [m]))
            # header / format
            if s.hedr_version < 1.695 and not e.implicit:
                issues.append(Issue('warning', 'le-header', e.name,
                                    f'{e.name} has header version {s.hedr_version:.2f}: a Skyrim LE (Oldrim) plugin '
                                    'that was not converted for Special Edition',
                                    'Get the SE version of the mod, or open and save it once in the SE Creation Kit '
                                    '(with SSE CreationKit Fixes).'))
            elif s.old_form_records and len(s.formids) and not e.implicit:
                frac = s.old_form_records / len(s.formids)
                if frac >= 0.5:
                    issues.append(Issue('info', 'le-records', e.name,
                                        f'{e.name}: {s.old_form_records} of {len(s.formids)} records have form '
                                        'version 43 (Skyrim LE format). Usually harmless; weapon critical-hit '
                                        'data (WEAP CRDT) is read wrongly',
                                        'Re-save it in the SE Creation Kit (with SSE CreationKit Fixes) if it adds '
                                        'or edits weapons.'))
            if s.hedr_version >= 1.705 and not e.implicit:
                hedr171.append(e.name)
            if s.is_light and not e.implicit:
                own_ids = s.new_ids()
                lo_bound = 0x000 if s.hedr_version >= 1.705 else 0x800
                bad = [i for i in own_ids if i < lo_bound or i > 0xFFF]
                if bad:
                    issues.append(Issue('error', 'esl-range', e.name,
                                        f'{e.name} is a light plugin but {len(bad)} new record(s) have object IDs '
                                        f'outside {lo_bound:03X}-FFF; using it damages saves irreversibly (LOOT)',
                                        f'Remove the ESL flag, or compact its FormIDs first (xEdit "Compact FormIDs '
                                        'for ESL", or ESLifier) - this breaks plugins/saves that use it.'))
                new_cells = sum(1 for fid, sig, _ in s.records() if sig == 'CELL' and (fid >> 24) == s.self_index)
                if new_cells:
                    issues.append(Issue('warning', 'esl-new-cell', e.name,
                                        f'{e.name} is a light plugin that adds {new_cells} new CELL record(s); '
                                        'new cells in light plugins can lose their changes (reset) in game',
                                        'Keep new cells in a full (non-ESL) plugin.'))
            if pmeta is not None:
                issues += self._meta_issues(e, pmeta)
                if self.is_master_like(e):
                    for name, _item, src in mlist.evaluate_items(pmeta.req + pmeta.after, self.ev):
                        te = names.get(name.lower())
                        if te is not None and te.scan is not None and not self.is_master_like(te):
                            issues.append(Issue('warning', 'loot-cannot-sort', e.name,
                                                f'{e.name} is a master but LOOT {src} metadata makes it load after '
                                                f'the regular plugin {te.name}; LOOT stops with a "cyclic '
                                                'interaction" error while both are installed',
                                                'Remove that load-after/requirement rule from the userlist, or '
                                                'disable one of the plugins.', [te.name]))
        # limits
        max_full = 254 if n_light else 255
        if n_full > max_full:
            issues.append(Issue('error', 'too-many-plugins', None,
                                f'{n_full} full (non-light) plugins are active; the game supports {max_full}'
                                + (' when light plugins are present' if n_light else ''),
                                'ESL-flag eligible plugins (esp eslify), merge small plugins, or remove some.'))
        elif n_full > max_full - 14:
            issues.append(Issue('warning', 'near-plugin-limit', None,
                                f'{n_full} of {max_full} full plugin slots used',
                                'ESL-flag eligible plugins (esp eslify) to free slots.'))
        if n_light > 4096:
            issues.append(Issue('error', 'too-many-light', None, f'{n_light} light plugins active; limit is 4096',
                                'Merge some light plugins.'))
        # Skyrim VR loads light plugins only with Skyrim VR ESL Support
        if self.is_vr and n_light and self.ev.find('SKSE/Plugins/skyrimvresl.dll') is False:
            issues.append(Issue('error', 'vr-no-esl', None,
                                f'{n_light} light plugin(s) are active but Skyrim VR needs the Skyrim VR ESL Support '
                                'SKSE plugin (Data/SKSE/Plugins/skyrimvresl.dll) to load them',
                                'Install Skyrim VR ESL Support (Nexus SSE 106712) or remove the ESL flags.'))
        # header 1.71 needs game 1.6.1130+ or BEES
        if hedr171 and not self.is_vr:
            names_s = ', '.join(hedr171[:5]) + (' ...' if len(hedr171) > 5 else '')
            if self.game_version and tuple(self.game_version[:3]) < V_CREATIONS:
                bees = self.ev.find('SKSE/Plugins/BackportedESLSupport.dll')
                if not bees:
                    issues.append(Issue('error' if bees is False else 'warning', 'needs-bees', None,
                                        f'{len(hedr171)} plugin(s) have header version 1.71 ({names_s}) but the game '
                                        f'is {_ver_str(self.game_version)}: older than 1.6.1130 it crashes on start',
                                        'Install Backported Extended ESL Support (BEES, SKSE plugin) or update the '
                                        'game.'))
            elif not self.game_version:
                issues.append(Issue('info', 'hedr-171', None,
                                    f'{len(hedr171)} plugin(s) use header version 1.71 ({names_s}): they need game '
                                    '1.6.1130 or newer, or Backported Extended ESL Support (BEES) on older games'))
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
        issues += self._generated_issues(order)
        if self.meta:
            issues += self._global_issues()
        self.validation = issues
        return issues

    def _generated_issues(self, order):
        out = []
        gen = [i for i, e in enumerate(order) if self.is_generated(e)]
        if not gen:
            return out
        ranked = [(order[i], generated_rank(order[i].name)) for i in gen
                  if generated_rank(order[i].name)[0] and not self.is_master_like(order[i])]
        for (a, (ra, la)), (b, (rb, lb)) in zip(ranked, ranked[1:]):
            if rb < ra:
                out.append(Issue('warning', 'generated-order', b.name,
                                 f'{b.name} ({lb}) loads after {a.name} ({la}); generated patches are built and '
                                 'loaded in the order Bashed/Smashed patch, Synthesis, DynDOLOD',
                                 f'Move {b.name} above {a.name} and rebuild the later ones.', [a.name]))
        syn = [i for i in gen if re.match(r'^synthesis(_\d+)?\.esp$', order[i].name.lower())]
        if len(syn) > 1 and syn[-1] - syn[0] != len(syn) - 1:
            out.append(Issue('warning', 'synthesis-split', order[syn[0]].name,
                             'Synthesis split files (Synthesis.esp, Synthesis_2.esp...) must load next to each '
                             'other', 'Move them together, in order.', [order[i].name for i in syn]))
        first = gen[0]
        late = [e for e in order[first + 1:] if not self.is_generated(e) and not e.implicit
                and not self.is_master_like(e)]
        if late and not self.is_master_like(order[first]):
            out.append(Issue('warning', 'after-generated', order[first].name,
                             f'{len(late)} plugin(s) load after the generated patch {order[first].name}: '
                             f'{", ".join(e.name for e in late[:5])}{" ..." if len(late) > 5 else ""}; their '
                             'changes are not in the patch and may undo it',
                             'Move generated patches (Bashed/Smashed/Synthesis/DynDOLOD) to the end, then '
                             're-generate them.', [e.name for e in late]))
        for i in gen:
            g = order[i]
            if not g.path:
                continue
            try:
                gt = os.path.getmtime(g.path)
            except OSError:
                continue
            newer = []
            for e in order[:i]:
                if e.implicit or not e.path or self.is_generated(e):
                    continue
                try:
                    if os.path.getmtime(e.path) > gt + 60:
                        newer.append(e.name)
                except OSError:
                    pass
            if newer:
                out.append(Issue('warning', 'stale-patch', g.name,
                                 f'{g.name} is older than {len(newer)} plugin(s) that load before it '
                                 f'({", ".join(newer[:4])}{" ..." if len(newer) > 4 else ""}); it was probably '
                                 'built for a different load order',
                                 f'Re-generate {g.name} with the tool that made it.', newer))
        return out

    def _meta_issues(self, e, pm):
        """LOOT masterlist/userlist checks for one active plugin."""
        out = []
        ev = self.ev
        if not self.meta.group_exists(pm.group):
            out.append(Issue('error', 'undefined-group', e.name,
                             f'{e.name} belongs to the LOOT group "{pm.group}", which does not exist',
                             'Fix the group in the LOOT/Vortex userlist.'))
        for name, item, src in mlist.evaluate_items(pm.req, ev):
            disp = item.get('d', name) if isinstance(item, dict) else name
            constraint = item.get('k') if isinstance(item, dict) else None
            present = ev.f_file(('str', name)) if not constraint else ev.eval(constraint)
            if present is False:
                det = item.get('t', '') if isinstance(item, dict) else ''
                out.append(Issue('error', 'loot-requires', e.name,
                                 f'{e.name} requires {disp}, which is missing ({src}). {det}'.strip(),
                                 f'Install {disp}, or disable {e.name}.', [name]))
        for name, item, src in mlist.evaluate_items(pm.inc, ev):
            disp = item.get('d', name) if isinstance(item, dict) else name
            if is_plugin_name(name) and '/' not in name:
                hit = name.lower() in ev.active
            else:
                hit = ev.f_file(('str', name)) is True
            if hit:
                det = item.get('t', '') if isinstance(item, dict) else ''
                out.append(Issue('error', 'loot-incompatible', e.name,
                                 f'{e.name} is incompatible with {disp}, but both are present ({src}). {det}'.strip(),
                                 f'Disable one of them (or find a compatibility patch).', [name]))
        crc = e.scan.crc if e.scan else None
        if crc is not None:
            for d in pm.dirty:
                if d['crc'] == crc and (not d.get('c') or ev.eval(d['c']) is True):
                    itm, udr, nav = d.get('i', 0), d.get('r', 0), d.get('v', 0)
                    serious = udr or nav
                    out.append(Issue('warning' if serious and not e.implicit else 'info', 'dirty', e.name,
                                     f'{e.name} is dirty: {d.get("u", "xEdit")} found {itm} ITM record(s), {udr} '
                                     f'deleted reference(s) and {nav} deleted navmesh(es) (LOOT masterlist)'
                                     + (f'. {d["t"]}' if d.get('t') else ''),
                                     ('Clean it with xEdit Quick Auto Clean (SSEEdit -qac). '
                                      + ('Deleted navmeshes need manual repair.' if nav else ''))
                                     .strip()))
        for m, src in pm.msgs:
            mtype, text = m[0], m[1]
            cond = m[2] if len(m) > 2 else None
            if cond and ev.eval(cond) is not True:
                continue
            level = {'error': 'error', 'warn': 'warning'}.get(mtype, 'info')
            out.append(Issue(level, 'loot-message', e.name, f'{e.name}: {text}'))
        return out

    def _global_issues(self):
        out = []
        for m, src in self.meta.globals:
            cond = m[2] if len(m) > 2 else None
            if not cond or self.ev.eval(cond) is not True:
                continue           # unconditional globals are LOOT forum links
            level = {'error': 'error', 'warn': 'warning'}.get(m[0], 'info')
            out.append(Issue(level, 'loot-global', None, m[1]))
        return out

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

    def sort(self, rules=None, use_overlap=True, use_groups=True):
        """Suggested order, LOOT-style: hard rules (masters, LOOT req/after,
        --rules), then LOOT groups, then LOOT's record-overlap rule; everything
        else keeps its current order. Returns (order, moves, notes) where
        moves = [(entry, [reasons])]."""
        cur = self.effective_order()
        hard = [e for e in cur if e.implicit]
        masters = [e for e in cur if not e.implicit and self.is_master_like(e)]
        regular = [e for e in cur if not e.implicit and not self.is_master_like(e)]
        rules = rules or {}
        notes = []
        names = {e.low: e for e in cur}
        meta = self.meta if use_groups else None
        if meta is not None and meta.group_cycle():
            notes.append(f'LOOT groups form a cycle around "{meta.group_cycle()}"; groups ignored')
            meta = None
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

            def hard_edge(u, v, why):
                if not topo.add(u, v, why):
                    notes.append(f'cyclic rule ignored: {why}')

            # 1. masters
            for e in part:
                for m in (e.scan.masters if e.scan else []):
                    ml = m.lower()
                    if ml in members and ml != e.low:
                        hard_edge(ml, e.low, f'{m} is a master of {e.name}')
            # 2. LOOT requirements and load-after rules (masterlist + userlist)
            if meta is not None:
                for e in sorted(part, key=lambda x: x.low):
                    pm = meta.for_plugin(e.name)
                    for kind, items in (('requires', pm.req), ('loads after', pm.after)):
                        for name, _item, src in mlist.evaluate_items(items, self.ev):
                            nl = name.lower()
                            if nl in members and nl != e.low:
                                hard_edge(nl, e.low, f'LOOT {src}: {e.name} {kind} {names[nl].name}')
            # 3. explicit rules: {"Plugin.esp": {"after": [...], "before": [...]}}
            for name, r in rules.items():
                nl = name.lower()
                if nl not in members:
                    continue
                for other in r.get('after', []) + r.get('req', []):
                    ol = other.lower()
                    if ol in members:
                        hard_edge(ol, nl, f'rule: {name} loads after {other}')
                for other in r.get('before', []):
                    ol = other.lower()
                    if ol in members:
                        hard_edge(nl, ol, f'rule: {name} loads before {other}')
            # 4. groups (soft). Edges from plugins in "default" are added last so
            #    that relationships between named groups win, as in LOOT.
            if meta is not None:
                grp = {e.low: self.group_of(e) for e in part}
                for g in grp.values():
                    if not meta.group_exists(g):
                        notes.append(f'group "{g}" does not exist; treated as default')
                grp = {k: (g if meta.group_exists(g) else 'default') for k, g in grp.items()}
                by_group = {}
                for n in topo.order:
                    by_group.setdefault(grp[n], []).append(n)
                for pass_default in (False, True):
                    for n in sorted(members):
                        g = grp[n]
                        for h in meta.group_preds(g):
                            if (h == 'default') != pass_default:
                                continue
                            for q in by_group.get(h, ()):
                                topo.add(q, n, f'LOOT group: {names[n].name} is in "{g}", which loads after '
                                               f'"{h}"')
            else:
                # no LOOT data: generated patches after everything else
                late = [e.low for e in part if late_loader_reason(e.name)]
                for ll in late:
                    why = late_loader_reason(names[ll].name)
                    for n in topo.order[:]:
                        if n != ll and n not in late:
                            topo.add(n, ll, f'{names[ll].name} is a {why} and should load last')
                for a in late:
                    for b in late:
                        ra, la = generated_rank(names[a].name)
                        rb, _lb = generated_rank(names[b].name)
                        if ra and rb and ra < rb:
                            topo.add(a, b, f'{la} load before {names[b].name}')
            # 5. overlap: the plugin that overrides more records loads first
            for (a, b), shared in sorted(pairs.items()):
                if a not in members or b not in members:
                    continue
                if b in topo.succ[a] or a in topo.succ[b]:
                    continue
                ca, cb = override_count[a], override_count[b]
                if ca == cb:
                    continue
                first, second = (a, b) if ca > cb else (b, a)
                topo.add(first, second,
                         f'overlap: both override {shared} record(s); {names[first].name} overrides more records '
                         f'({max(ca, cb)} vs {min(ca, cb)}), so the smaller {names[second].name} wins')
            new_order = [names[n] for n in topo.stable_order({e.low: i for i, e in enumerate(part)})]
            moves += _explain_moves(part, new_order, topo)
            result += new_order
        hoisted = self._hoist(result)
        if hoisted != result:
            notes.append('the game hoists some regular plugins into the master block because a master-flagged '
                         'plugin needs them (see master-needs-nonmaster); the suggested order shows that')
        return hoisted, moves, list(dict.fromkeys(notes))


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

    def stable_order(self, rank):
        """Topological order of the accepted edges that keeps the original
        order wherever the edges allow (Kahn's algorithm, lowest rank first)."""
        import heapq
        indeg = {n: len(self.pred[n]) for n in self.order}
        heap = [(rank[n], n) for n in self.order if not indeg[n]]
        heapq.heapify(heap)
        out = []
        while heap:
            _r, n = heapq.heappop(heap)
            out.append(n)
            for w in self.succ[n]:
                indeg[w] -= 1
                if not indeg[w]:
                    heapq.heappush(heap, (rank[w], w))
        if len(out) != len(self.order):        # cannot happen: edges are acyclic
            return list(self.order)
        return out


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
