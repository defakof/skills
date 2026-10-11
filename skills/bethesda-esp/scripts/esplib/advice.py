"""Turn load-order validation, conflict scan and ESLify results into
prioritised, concrete recommendations (which tool or command to use)."""

import re

from .conflicts import CATEGORY_INFO, SEVERITY_RANK, UNOFFICIAL_PATCHES, relevant_tags

# Tools we may recommend. Keep descriptions factual; see references/loadorder.md.
TOOLS = {
    'loot': 'LOOT (sorts plugins with its masterlist; run it from your mod manager)',
    'bashed': 'Wrye Bash Bashed Patch (merges leveled lists and tagged changes automatically)',
    'smash': 'Mator Smash (field-level "smashed patch" of all conflicts; older tool, review its output)',
    'synthesis': 'Synthesis (Mutagen) patchers, generated into Synthesis.esp',
    'easynpc': 'EasyNPC (choose the appearance mod per NPC, keeps other mods\' NPC changes)',
    'xedit': 'SSEEdit (xEdit) conflict view / manual patch',
    'qac': 'SSEEdit Quick Auto Clean (removes ITMs, undeletes and disables deleted references)',
    'ck': 'Creation Kit (Bethesda\'s editor: resave LE plugins; navmesh edits are made and finalized there)',
    'eslifier': 'ESLifier (flags or compacts plugins and patches FaceGen, voice, scripts, SEQ, SKSE configs and '
                'dependent plugins to match)',
    'esp-eslify': 'esp eslify (this skill: lists ESL candidates and blockers) and esp esl <plugin> --flag',
    'bees': 'Backported Extended ESL Support (BEES, SKSE plugin for game 1.5.97-1.6.659)',
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


# code -> (priority, why, tools); priority None = use the issue level
VALIDATION_ADVICE = {
    'missing-master': (1, 'The game crashes on start when a master is missing or inactive.', []),
    'inactive-master': (1, 'The game crashes on start when a master is missing or inactive.', []),
    'missing-base-master': (1, 'Without the base game masters nothing can load.', []),
    'unreadable': (1, 'A damaged plugin crashes the game or the tools that read it.', []),
    'self-master': (1, 'A plugin that lists itself as a master is broken.', []),
    'master-order': (1, 'A plugin that loads before its master can lose its changes or crash the game.', ['loot']),
    'master-needs-nonmaster': (1, 'The game moves the regular plugin into the master block, which changes which '
                                  'records win; LOOT refuses to sort such a load order.', ['xedit']),
    'esl-range': (1, 'A light plugin with FormIDs outside the light range breaks saves permanently.',
                  ['eslifier', 'xedit']),
    'too-many-plugins': (1, 'The game cannot load more full plugins; the extra ones are dropped or it crashes.',
                         ['eslifier', 'esp-eslify']),
    'too-many-light': (1, 'The game cannot load more than 4096 light plugins.', []),
    'needs-bees': (1, 'Header 1.71 plugins crash games older than 1.6.1130.', ['bees']),
    'loot-requires': (1, 'LOOT\'s masterlist says this plugin does not work without it.', []),
    'loot-incompatible': (1, 'LOOT\'s masterlist says these two do not work together.', []),
    'undefined-group': (2, 'LOOT cannot sort while a plugin uses an undefined group.', ['loot']),
    'after-generated': (2, 'Generated patches only contain what loaded before them when they were built.',
                        ['bashed', 'smash', 'synthesis', 'loot']),
    'stale-patch': (2, 'Generated patches must be rebuilt after the mod list or order changes.',
                    ['bashed', 'smash', 'synthesis']),
    'dirty': (3, 'Deleted references and navmeshes can crash the game; ITMs revert other mods\' changes.', ['qac']),
    'bad-filename': (2, 'plugins.txt is Windows-1252; the game cannot activate names it cannot store.', []),
    'lo-desync': (3, 'Mod managers can overwrite one file from the other.', []),
    'le-header': (3, 'Unconverted Skyrim LE plugins can misbehave in SE.', ['ck']),
    'le-records': (4, 'Form 43 records are mostly fine; weapon critical data is read wrongly.', ['ck']),
    'esl-new-cell': (3, 'New cells in light plugins are known to lose changes.', []),
    'near-plugin-limit': (3, 'Close to the full-plugin limit.', ['esp-eslify', 'eslifier']),
    'not-found': (3, '', []),
    'duplicate-entry': (3, '', []),
    'no-plugins-txt': (3, 'Without plugins.txt the real order is unknown.', []),
}
LOOT_MSG_PRIORITY = {'error': 2, 'warning': 3}


def from_validation(issues):
    out = []
    for i in issues:
        if i.code in ('loot-message', 'loot-global'):
            prio = LOOT_MSG_PRIORITY.get(i.level)
            if prio:
                out.append(Advice(prio, 'loot', i.message, 'From the LOOT masterlist.', [], ['loot'],
                                  [i.plugin] if i.plugin else []))
            continue
        spec = VALIDATION_ADVICE.get(i.code)
        if spec is None:
            if i.level != 'error':
                continue
            spec = (1, '', [])
        prio, why, tools = spec
        if i.code == 'dirty' and i.level == 'warning':
            prio = 2
        elif i.code == 'dirty':
            prio = 4
        out.append(Advice(prio, 'load-order' if i.level == 'error' else i.code, i.message, why,
                          [i.fix] if i.fix else [], tools, [i.plugin] if i.plugin else []))
    return out


def _yaml_q(name):
    return "'" + name.replace("'", "''") + "'"


def from_sort(moves, write_hint='esp loadorder <same options> --write plugins_sorted.txt'):
    if not moves:
        return []
    lines = []
    rules = []
    for e, reasons in moves[:25]:
        uniq = list(dict.fromkeys(reasons))
        lines.append(f'move {e.name}: ' + '; '.join(uniq[:2]))
        for r in uniq:
            m = re.match(r'rule: (.+) loads after (.+)$', r)
            if m:
                rules.append((m.group(1), m.group(2)))
    how = lines + [f'Write the fixed order with: {write_hint} (or sort with LOOT and compare).']
    if rules:
        snippet = 'plugins:\n' + ''.join(f'  - name: {_yaml_q(a)}\n    after: [ {_yaml_q(b)} ]\n' for a, b in rules)
        how.append('Your own rules are not known to LOOT; add them to the LOOT (or Vortex) userlist.yaml so the '
                   'next LOOT sort keeps them:\n' + snippet)
    return [Advice(2, 'sort', f'{len(moves)} plugin(s) are out of order',
                   'Masters load before the plugins that use them; LOOT\'s rules and groups put known mods '
                   '(and generated patches) in place; when two plugins override the same records, the one that '
                   'overrides fewer (the more specific) should usually win.',
                   how, ['loot'], [e.name for e, _ in moves])]


def from_overridden_patches(over):
    out = []
    for (patch, winner), cs in sorted(over.items(), key=lambda kv: -len(kv[1])):
        out.append(Advice(2, 'patch-overridden', f'{patch} loses {len(cs)} record(s) to {winner}',
                          'A compatibility patch only works where its records win; here a later plugin that does '
                          'not include the patch\'s changes overrides it.',
                          [f'If {winner} does not need to win those records, load {patch} after it.',
                           f'Otherwise make a small patch on top of both: esp merge {_q(patch)} {_q(winner)} --into '
                           f'"Patch.esp" --records {" ".join(c.formkey for c in cs[:6])}'],
                          ['esp-merge', 'xedit'], [patch, winner], [f'{c.sig} {c.formkey}' for c in cs]))
    return out


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
    model = getattr(scanner, 'model', None)
    tag_cache = {}

    def tags(name):
        if name not in tag_cache:
            e = scanner.by_low.get(name.lower()) if scanner is not None else None
            tag_cache[name] = model.tags_of(e) if (model is not None and e is not None) else []
        return tag_cache[name]

    for (cat, names), cs in sorted(groups.items(), key=lambda kv: (SEVERITY_RANK[CATEGORY_INFO.get(kv[0][0], ('', 'low'))[1]],
                                                                  -len(kv[1]))):
        label, sev = CATEGORY_INFO.get(cat, CATEGORY_INFO['other'])
        winner = cs[0].winner.entry.name
        patched = [c for c in cs if c.patched]
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
        tagged = [(p, relevant_tags(cat, tags(p))) for p in plugins if p != winner]
        tagged = [(p, t) for p, t in tagged if t]
        if tagged:
            how = how + ['Wrye Bash\'s Bashed Patch can carry these changes over automatically (Bash Tags from '
                         'LOOT): ' + '; '.join(f'{p} [{", ".join(t)}]' for p, t in tagged)]
            if 'bashed' not in tools:
                tools = tools + ['bashed']
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
    for plugin, d in sorted(reverts.items(), key=lambda kv: -len(kv[1]['keys'])):
        fixers = d['fixers']
        keys = d['keys']
        checked = d.get('checked')
        if checked is not None and not d['fields']:
            continue                    # deep check: nothing actually reverted
        unofficial = any(f.lower() in UNOFFICIAL_PATCHES for f in fixers)
        short = [UNOFFICIAL_PATCHES.get(f.lower(), f) for f in fixers]
        n = len(d['fields']) if checked is not None else len(keys)
        detail = ''
        if d['fields']:
            detail = ' Reverted: ' + '; '.join(f'{rk}: {", ".join(fl[:4])}' for rk, fl in list(d['fields'].items())[:5])
        out.append(Advice(2 if unofficial else 3, 'reverts-fixes',
                          f'{plugin} wins {n} record(s) that {", ".join(short)} fixed, without using '
                          f'{"it" if len(short) == 1 else "them"} as a master',
                          ('Its versions are based on the unfixed game data, so the bug fixes are undone.' +
                           detail) if checked is not None else
                          'Its versions are based on the unfixed game data, so they can undo those bug fixes '
                          '(esp scan --deep shows which fields).',
                          ([f'Look for a USSEP-compatible version or patch of {plugin} on its mod page.']
                           if unofficial else []) +
                          [f'Forward the fixes into a patch that loads after {plugin}: esp merge '
                           f'{" ".join(_q(f) for f in fixers)} {_q(plugin)} --into "Patch.esp" --records ' +
                           ' '.join(scanner.formkey(k) for k in keys[:6]) +
                           (' ...' if len(keys) > 6 else '')],
                          ['esp-merge', 'xedit'], [plugin] + list(fixers)))
    return out


def from_eslify(cands, n_full, max_full=254, steps=None):
    out = []
    flag = [c for c in cands if c.verdict == 'flag']
    flag171 = [c for c in cands if c.verdict == 'flag-171']
    compact = [c for c in cands if c.verdict == 'compact']
    care = [c for c in cands if c.verdict == 'compact-care']
    if n_full > max_full:
        prio = 1
    elif n_full > max_full - 14:
        prio = 2
    elif n_full > 200:
        prio = 3
    else:
        prio = 4
    need = max(0, n_full - max_full)
    room = f'{n_full} of {max_full} full slots used' + (f'; at least {need} must go' if need else '')
    steps = steps or []
    if flag or flag171:
        cmds = [f'esp esl {_q(c.entry.name)} --flag' for c in flag[:15]] + \
               [f'esp esl {_q(c.entry.name)} --header-171 --flag' for c in flag171[:10]]
        more = len(flag) + len(flag171) - len(cmds)
        out.append(Advice(prio, 'eslify-flag',
                          f'{len(flag) + len(flag171)} plugin(s) can be ESL-flagged without changing FormIDs',
                          f'Light plugins do not take one of the {max_full} full slots ({room}).'
                          + ('' if prio < 4 else ' Optional while you have free slots.'),
                          cmds + ([f'... {more} more (esp eslify --json lists all)'] if more > 0 else []) + steps[:2],
                          ['esp-eslify', 'eslifier'], [c.entry.name for c in flag + flag171]))
    if compact or care:
        out.append(Advice(min(prio + 1, 4), 'eslify-compact',
                          f'{len(compact) + len(care)} more plugin(s) could become light only by compacting their '
                          'FormIDs',
                          'Compacting renumbers records: existing saves break, and FaceGen, voice files, scripts, '
                          'SKSE configs and dependent plugins must be patched to match. '
                          + '; '.join(f'{c.entry.name}: {"; ".join(c.risks)}' for c in care[:4]),
                          ['Use ESLifier for these (it patches the dependent files); only on a new game.'] +
                          [f'Nothing found that depends on their FormIDs: {", ".join(c.entry.name for c in compact[:8])}'
                           f' (esp compact <plugin> then esp esl <plugin> --flag also works for these)'
                           if compact else ''] + steps[2:],
                          ['eslifier'], [c.entry.name for c in compact + care]))
        out[-1].how = [h for h in out[-1].how if h]
    return out


def sort_advice(advice):
    return sorted(advice, key=lambda a: (a.priority, a.kind, a.title))
