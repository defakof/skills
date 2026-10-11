"""Turn load-order validation, conflict scan and ESLify results into
prioritised, concrete recommendations (which tool or command to use)."""

from .conflicts import CATEGORY_INFO, SEVERITY_RANK, UNOFFICIAL_PATCHES

# Tools we may recommend. Keep descriptions factual; see references/loadorder.md.
TOOLS = {
    'loot': 'LOOT (sorts plugins with its masterlist; run it from your mod manager)',
    'bashed': 'Wrye Bash Bashed Patch (merges leveled lists and tagged changes automatically)',
    'smash': 'Mator Smash (field-level "smashed patch" of all conflicts; older tool, review its output)',
    'synthesis': 'Synthesis (Mutagen) patchers, generated into Synthesis.esp',
    'easynpc': 'EasyNPC (choose the appearance mod per NPC, keeps other mods\' NPC changes)',
    'xedit': 'SSEEdit (xEdit) conflict view / manual patch',
    'qac': 'SSEEdit Quick Auto Clean (removes ITMs, undeletes and disables deleted references)',
    'ck': 'Creation Kit (navmesh edits must be made and finalized there)',
    'eslifier': 'ESLifier (compacts FormIDs and also fixes FaceGen, voice files, SKSE configs and dependent plugins)',
    'esp-merge': 'esp merge A.esp B.esp --into Patch.esp (this skill: 3-way merge of lists and changed fields)',
    'esp-copy': 'esp copy + esp set (this skill: hand-made override in a patch plugin)',
}

PRIORITY_NAMES = {1: 'critical', 2: 'high', 3: 'medium', 4: 'low'}


class Advice:
    def __init__(self, priority, kind, title, why, how=None, tools=None, plugins=None, records=None):
        self.priority = priority
        self.kind = kind
        self.title = title
        self.why = why
        self.how = how or []
        self.tools = tools or []
        self.plugins = plugins or []
        self.records = records or []

    def as_dict(self):
        return {'priority': PRIORITY_NAMES[self.priority], 'kind': self.kind, 'title': self.title, 'why': self.why,
                'how': self.how, 'tools': [TOOLS.get(t, t) for t in self.tools], 'plugins': self.plugins,
                'records': self.records[:50]}


def _q(name):
    return f'"{name}"' if ' ' in name else name


def from_validation(issues):
    out = []
    for i in issues:
        if i.level == 'error':
            out.append(Advice(1, 'load-order', i.message, 'The game crashes or misbehaves with this.',
                              [i.fix] if i.fix else [], ['loot'], [i.plugin] if i.plugin else []))
        elif i.code in ('le-header', 'le-records'):
            out.append(Advice(3, 'convert', i.message, 'Unconverted Skyrim LE plugins can break sounds and other '
                              'records in SE.', [i.fix], ['ck'], [i.plugin]))
        elif i.code in ('esl-new-cell', 'near-plugin-limit', 'not-found', 'duplicate-entry', 'no-plugins-txt'):
            out.append(Advice(3, 'load-order', i.message, '', [i.fix] if i.fix else [], [], [i.plugin] if i.plugin else []))
    return out


def from_sort(moves):
    if not moves:
        return []
    lines = []
    for e, reasons in moves[:25]:
        uniq = []
        for r in reasons:
            if r not in uniq:
                uniq.append(r)
        lines.append(f'move {e.name}: ' + '; '.join(uniq[:2]))
    return [Advice(2, 'sort', f'{len(moves)} plugin(s) are out of order',
                   'Masters must load before the plugins that use them, generated patches load last, and when two '
                   'plugins override the same records the more specific (smaller) one should usually win.',
                   lines + ['Write the fixed order with: esp loadorder ... --sort --write plugins_sorted.txt '
                            '(or let LOOT sort and compare).'], ['loot'], [e.name for e, _ in moves])]


def group_conflicts(conflicts):
    """{(category, plugin names tuple): [Conflict]} using overriders' names."""
    groups = {}
    for c in conflicts:
        names = tuple(v.entry.name for v in c.overriders)
        key = (c.category, names)
        groups.setdefault(key, []).append(c)
    return groups


def from_conflicts(conflicts, deep=False, scanner=None):
    out = []
    groups = group_conflicts(conflicts)
    smash_candidates = []
    for (cat, names), cs in sorted(groups.items(), key=lambda kv: (SEVERITY_RANK[CATEGORY_INFO.get(kv[0][0], ('', 'low'))[1]],
                                                                  -len(kv[1]))):
        label, sev = CATEGORY_INFO.get(cat, CATEGORY_INFO['other'])
        winner = cs[0].winner.entry.name
        patched = [c for c in cs if c.patched]
        recs = [f'{c.sig} {c.formkey}' for c in cs]
        if deep:
            statuses = {}
            for c in cs:
                st = (c.deep or {}).get('status', 'unknown')
                statuses[st] = statuses.get(st, 0) + 1
            todo = [c for c in cs if (c.deep or {}).get('status') in ('lists', 'forwardable', 'clash')]
            if not todo:
                continue            # identical / resolved: nothing lost
        else:
            todo = [c for c in cs if not c.patched]
            if not todo:
                continue
            statuses = None
        plugins = list(names)
        title = f'{label}: {len(todo)} record(s) changed by {", ".join(plugins[:4])}' \
                f'{" and others" if len(plugins) > 4 else ""} (winner: {winner})'
        prio = {'high': 2, 'medium': 3, 'low': 4}[sev]
        why_bits = []
        if statuses:
            why_bits.append(', '.join(f'{n} {k}' for k, n in sorted(statuses.items())))
        if patched and not deep:
            why_bits.append(f'{len(patched)} already handled by a patch that has the others as masters')
        if not deep:
            why_bits.append('only the winner\'s version is used; run "esp scan --deep" to see whose changes are lost')
        how, tools = _how(cat, todo, plugins, deep)
        if cat in ('items', 'magic', 'crafting', 'actors', 'npc', 'leveled', 'containers', 'cells') and len(plugins) >= 3:
            smash_candidates.append((cat, len(todo)))
        out.append(Advice(prio, f'conflict:{cat}', title, '; '.join(why_bits), how, tools, plugins,
                          [f'{c.sig} {c.formkey}' for c in todo]))
    total_mergeable = sum(n for _, n in smash_candidates)
    if total_mergeable >= 15:
        out.append(Advice(3, 'whole-load-order-patch',
                          f'{total_mergeable} records are changed by 3+ mods each',
                          'With this many overlapping list/stat edits, a generated patch is less work than hand-made '
                          'ones.',
                          ['Leveled lists / inventories: build a Bashed Patch in Wrye Bash (or esp merge ... --into '
                           'Merged.esp for a handful of records).',
                           'Stats, keywords and other fields across many mods: Mator Smash or Synthesis patchers; '
                           'review the result in SSEEdit.',
                           'Generated patches must load last and be rebuilt whenever the mod list changes.'],
                          ['bashed', 'smash', 'synthesis', 'esp-merge']))
    return out


def _how(cat, cs, plugins, deep):
    """Concrete steps for one conflict group."""
    pl = ' '.join(_q(p) for p in plugins)
    recs = ' '.join(c.formkey for c in cs[:6])
    kinds = set()
    npc_kind = set()
    for c in cs:
        d = c.deep or {}
        kinds.add(d.get('status'))
        if d.get('npc'):
            npc_kind.add(d['npc'])
    merge_cmd = f'esp merge {pl} --into "Patch.esp" --records {recs}'
    if cat == 'navmesh':
        return (['Navmeshes cannot be merged record-by-record. Use the compatibility patch from the mod pages if '
                 'one exists; otherwise decide which mod\'s navmesh wins (load it last) or rebuild the overlap in the '
                 'Creation Kit and finalize the navmesh.',
                 'Deleted navmeshes are a crash risk and must be fixed by hand (xEdit/CK), not by cleaning tools.'],
                ['ck', 'xedit'])
    if cat == 'quests':
        return (['Quest, dialogue, scene and package records carry scripts and conditions: look for an official '
                 'compatibility patch first.',
                 f'Otherwise compare in detail (esp diff / esp conflicts {pl} --details) and build a patch by hand: '
                 'esp copy <winner> <record> --to Patch.esp, then forward the other mod\'s changes with esp set.'],
                ['xedit', 'esp-copy'])
    if cat in ('leveled', 'containers'):
        return ([f'Merge the lists: {merge_cmd}',
                 'Or let Wrye Bash build a Bashed Patch (merges every leveled list in the load order).'],
                ['esp-merge', 'bashed'])
    if cat == 'npc':
        if npc_kind and npc_kind <= {'visual'}:
            return (['Appearance-only conflict: decide which mod\'s look you want and make sure that plugin wins '
                     'AND its FaceGen files win in the mod manager (otherwise: dark-face bug).',
                     'Many NPCs from several appearance mods: use EasyNPC.'], ['easynpc'])
        steps = [f'Forward the non-visual changes (stats, perks, factions, inventory, AI) with {merge_cmd}']
        if 'mixed' in npc_kind or not deep:
            steps.append('If an appearance mod is involved, keep its face data and FaceGen together: EasyNPC '
                         'handles appearance vs. stats per NPC.')
        return steps, ['esp-merge', 'easynpc', 'smash']
    if cat == 'settings':
        return (['Only one value can win: the last plugin decides. Reorder if you prefer the other value, or set '
                 'it in a patch (esp copy ... --to Patch.esp; esp set Patch.esp <GMST> DATA=<value>).'],
                ['esp-copy'])
    if cat == 'placed':
        return (['Usually fine to let load order decide (one mod moves/edits the object). If one mod deletes or '
                 'disables it and the other changes it, pick a winner by load order or patch by hand.'],
                ['xedit'])
    if cat == 'landscape':
        return (['Landscape edits from different mods do not merge well: choose the winner by load order or use a '
                 'compatibility patch; seams/floating objects mean a patch is needed.'], ['xedit', 'ck'])
    if cat == 'cells':
        return ([f'Forward the losing fields (lighting, water, name, location, music...): {merge_cmd}',
                 'Lighting/weather overhauls often ship compatibility patches; check the mod pages first.'],
                ['esp-merge', 'xedit'])
    steps = [f'Small set: {merge_cmd} (review the result with esp show).']
    if 'clash' in kinds:
        steps.append('Some fields were changed differently by each mod ("clash"): pick the value per field with '
                     'esp set on the patch.')
    steps.append('Many records across many mods: Mator Smash or Synthesis patchers, or Wrye Bash tags '
                 '(Names, Stats, Keywords...).')
    return steps, ['esp-merge', 'smash', 'synthesis', 'bashed']


def from_checks(dirty, navcells, edid_dups, collisions, reverts, scanner):
    out = []
    for name, d in sorted(dirty.items()):
        if d['deleted_navmesh']:
            out.append(Advice(1, 'dirty', f'{name} deletes {d["deleted_navmesh"]} navmesh(es)',
                              'Deleted navmeshes can crash the game when the area loads.',
                              ['Check the LOOT masterlist / mod page for a fixed version; otherwise fix in SSEEdit '
                               '(replace the deleted navmesh) or the Creation Kit. Cleaning tools do not fix this.'],
                              ['xedit', 'ck'], [name]))
        if d['udr']:
            out.append(Advice(2, 'dirty', f'{name} deletes {d["udr"]} placed reference(s)',
                              'Deleted references (UDRs) can crash the game when other mods or scripts touch them.',
                              [f'Undelete and disable them: esp delete {_q(name)} <ref> --disable for each, or run '
                               'SSEEdit Quick Auto Clean (only if LOOT says the plugin should be cleaned).'],
                              ['qac'], [name]))
    for cell, ents in navcells:
        names = [e.name for e in ents]
        out.append(Advice(2, 'navmesh-overlap', f'{len(names)} plugins edit navmeshes in cell {cell}',
                          'Overlapping navmesh edits in one cell (even different navmesh records) cause AI pathing '
                          'problems and can crash if edges reference removed triangles.',
                          ['Use a compatibility patch if available, or decide which mod\'s navmesh wins (load it '
                           'last); real fixes need the Creation Kit.'], ['ck'], names))
    for edid, where in edid_dups[:30]:
        plugins = [p for p, _ in where]
        out.append(Advice(4, 'editor-id', f'EditorID "{edid}" is used by different records in {", ".join(plugins)}',
                          'Duplicate EditorIDs confuse tools that look records up by EditorID (SPID/KID configs, '
                          'console, xEdit scripts); usually harmless in game.',
                          ['Rename the EditorID in the less important plugin (esp set <plugin> <record> EDID=NewName) '
                           'if a config refers to it.'], [], plugins))
    for key, names, sigs in collisions:
        out.append(Advice(1, 'injected-collision', f'{", ".join(names)} all inject record {key}',
                          f'They add a record ({"/".join(sigs)}) into a master\'s FormID space without depending on '
                          'each other, so they overwrite each other\'s new record.',
                          ['Only one can work: keep one mod or ask the authors; renumbering needs a new FormID in the '
                           'mod\'s own space (esp copy --as-new) and fixing every reference.'], ['xedit'], names))
    for (plugin, fixers), keys in sorted(reverts.items(), key=lambda kv: -len(kv[1])):
        fx = ', '.join(fixers)
        unofficial = any(f.lower() in UNOFFICIAL_PATCHES for f in fixers)
        out.append(Advice(3 if not unofficial else 2, 'reverts-fixes',
                          f'{plugin} overrides {len(keys)} record(s) also fixed by {fx} without using it as a master',
                          'Its versions are based on the original game data, so they can undo those bug fixes '
                          '(run esp scan --deep to see which fields).',
                          [f'Look for a "{fx.split(",")[0].replace(".esp", "").replace(".esm", "")} patch" for '
                           f'{plugin} on the mod page; otherwise forward the fixes with esp merge into a patch.'],
                          ['esp-merge', 'xedit'], [plugin]))
    return out


def from_eslify(cands, n_full):
    out = []
    flag = [c for c in cands if c.verdict == 'flag' and c.n_new > 0 or c.verdict == 'flag' and not c.n_new]
    compact = [c for c in cands if c.verdict == 'compact']
    care = [c for c in cands if c.verdict == 'compact-care']
    pressure = n_full > 200
    if flag:
        out.append(Advice(3 if pressure else 4, 'eslify-flag',
                          f'{len(flag)} plugin(s) can be ESL-flagged as they are',
                          f'Light plugins do not use one of the 254 full slots ({n_full} used). No FormIDs change.',
                          [f'esp esl {_q(c.entry.name)} --flag' for c in flag[:15]] +
                          (['... (esp eslify --json for all)'] if len(flag) > 15 else []) +
                          ['Back up first; ESL-flag mid-playthrough only if you accept some risk to existing saves.'],
                          ['eslifier'], [c.entry.name for c in flag]))
    if compact:
        out.append(Advice(4, 'eslify-compact', f'{len(compact)} plugin(s) can become light after compacting FormIDs',
                          'Nothing else in the load order depends on their FormIDs (no FaceGen, voice, scripts or '
                          'configs found).',
                          [f'esp compact {_q(c.entry.name)} && esp esl {_q(c.entry.name)} --flag' for c in compact[:10]] +
                          ['Only for new games: existing saves keep the old FormIDs.'], ['eslifier'],
                          [c.entry.name for c in compact]))
    if care:
        out.append(Advice(4, 'eslify-care', f'{len(care)} plugin(s) could become light but compacting would break '
                          'files that refer to their FormIDs',
                          '; '.join(f'{c.entry.name}: {"; ".join(c.risks)}' for c in care[:5]),
                          ['Use ESLifier (it renames FaceGen/voice files, updates SKSE configs and dependent '
                           'plugins), or leave them as full plugins.'], ['eslifier'],
                          [c.entry.name for c in care]))
    return out


def sort_advice(advice):
    return sorted(advice, key=lambda a: (a.priority, a.kind, a.title))
