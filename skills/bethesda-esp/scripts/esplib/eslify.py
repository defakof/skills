"""Which plugins of a load order can become light plugins (ESL flag), and
what would break if their FormIDs had to be compacted."""

import os

CONFIG_EXTS = ('.ini', '.json', '.toml', '.yaml', '.yml', '.txt', '.jslot', '.psc')
MAX_CONFIG_SIZE = 4 * 1024 * 1024


class EslCandidate:
    def __init__(self, entry):
        self.entry = entry
        self.verdict = None          # 'flag' | 'compact' | 'compact-care' | 'no' | 'already'
        self.reasons = []
        self.risks = []
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


def _config_mentions(dirs, plugin_name, deep=False, limit=50):
    """Text config files (SKSE plugin INIs, JSON...) that mention the plugin."""
    needle = plugin_name.lower().encode('utf-8')
    hits = []
    for base in dirs:
        roots = [base]
        if not deep:
            # quick: Data root files + SKSE folder only
            roots = []
            try:
                for n in os.listdir(base):
                    p = os.path.join(base, n)
                    if os.path.isfile(p) and n.lower().endswith(CONFIG_EXTS):
                        _check_file(p, needle, hits)
            except OSError:
                pass
            skse = _exists_ci(base, 'SKSE')
            if skse:
                roots.append(skse)
        for root in roots:
            for dp, dn, fn in os.walk(root):
                for n in fn:
                    if n.lower().endswith(CONFIG_EXTS):
                        _check_file(os.path.join(dp, n), needle, hits)
                        if len(hits) >= limit:
                            return hits
    return hits


def _check_file(path, needle, hits):
    try:
        if os.path.getsize(path) > MAX_CONFIG_SIZE:
            return
        with open(path, 'rb') as f:
            if needle in f.read().lower():
                hits.append(path)
    except OSError:
        pass


def _scripts_mention(dirs, plugin_name, limit=20):
    """Compiled scripts (.pex) containing the plugin's file name (typically
    Game.GetFormFromFile(0x..., "Plugin.esp") with hard-coded IDs)."""
    needle = plugin_name.lower().encode('utf-8')
    hits = []
    for base in dirs:
        sdir = _exists_ci(base, 'Scripts')
        if not sdir:
            continue
        try:
            names = os.listdir(sdir)
        except OSError:
            continue
        for n in names:
            if not n.lower().endswith('.pex'):
                continue
            p = os.path.join(sdir, n)
            try:
                with open(p, 'rb') as f:
                    if needle in f.read().lower():
                        hits.append(p)
            except OSError:
                pass
            if len(hits) >= limit:
                return hits
    return hits


def analyse(model, configs=False, deep_configs=False):
    """Return [EslCandidate] for active, non-official, full plugins (and
    already-light ones that are broken)."""
    order = model.effective_order()
    dependents = {}
    for e in order:
        if e.scan is None:
            continue
        for m in e.scan.masters:
            dependents.setdefault(m.lower(), []).append(e.name)
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
        c.dependents = dependents.get(e.low, [])
        if s.is_light:
            c.verdict = 'already'
            out.append(c)
            continue
        lo_bound = 0x800
        max_new = 0xFFF - lo_bound + 1          # 2048
        new_sigs = {}
        for fid, sig, _ in s.records():
            if (fid >> 24) == s.self_index:
                new_sigs[sig] = new_sigs.get(sig, 0) + 1
        if new_sigs.get('CELL') or new_sigs.get('WRLD'):
            c.verdict = 'no'
            c.reasons.append(f'adds {new_sigs.get("CELL", 0)} new cell(s) / {new_sigs.get("WRLD", 0)} worldspace(s): '
                             'new cells in light plugins can reset or lose changes; keep it a full plugin')
            out.append(c)
            continue
        if c.n_new > max_new:
            c.verdict = 'no'
            c.reasons.append(f'{c.n_new} new records; a light plugin can hold at most 2048 '
                             '(4096 with header 1.71 on Skyrim 1.6.1130+ or BEES)')
            out.append(c)
            continue
        if all(lo_bound <= i <= 0xFFF for i in ids):
            c.verdict = 'flag'
            c.reasons.append('all new records already use object IDs 800-FFF: set the ESL flag, no renumbering')
            if c.dependents:
                c.reasons.append(f'{len(c.dependents)} plugin(s) use it as a master; they keep working '
                                 '(FormIDs do not change)')
            out.append(c)
            continue
        # needs compaction: collect what references its FormIDs
        dirs = _plugin_dirs(model, e)
        if new_sigs.get('NPC_'):
            for d in dirs:
                fg = _exists_ci(d, 'meshes', 'actors', 'character', 'FaceGenData', 'FaceGeom', e.name)
                if fg:
                    c.files.append(fg)
            c.risks.append(f'{new_sigs["NPC_"]} new NPC(s): FaceGen meshes/tints are named after their FormIDs '
                           '(dark-face bug if not renamed)')
        if new_sigs.get('INFO'):
            for d in dirs:
                vo = _exists_ci(d, 'sound', 'voice', e.name)
                if vo:
                    c.files.append(vo)
            c.risks.append(f'{new_sigs["INFO"]} new dialogue response(s): voice files are named after INFO '
                           'FormIDs (silent dialogue if not renamed)')
        if c.dependents:
            c.risks.append(f'master of {len(c.dependents)} plugin(s) ({", ".join(c.dependents[:5])}'
                           f'{"..." if len(c.dependents) > 5 else ""}): they must be patched to the new FormIDs')
        if s.has_scripts:
            pex = _scripts_mention(dirs, e.name)
            if pex:
                c.files += pex
                c.risks.append(f'{len(pex)} compiled script(s) mention "{e.name}" (likely GetFormFromFile with '
                               'hard-coded FormIDs)')
        if configs:
            cfg = _config_mentions(dirs if not model.search_dirs else [d for d, _ in model.search_dirs],
                                   e.name, deep=deep_configs)
            if cfg:
                c.files += cfg
                c.risks.append(f'{len(cfg)} config file(s) mention it (SPID/KID/BOS/OAR... use FormIDs from it)')
        c.reasons.append(f'{c.n_new} new record(s) with object IDs {c.id_range}: needs FormID compaction first')
        c.verdict = 'compact-care' if c.risks else 'compact'
        out.append(c)
    return out
