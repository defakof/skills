"""Turn load-order validation, conflict scan and ESLify results into
prioritised, concrete recommendations (which tool or command to use)."""

import re

from .conflicts import CATEGORY_INFO, SEVERITY_RANK, UNOFFICIAL_PATCHES, relevant_tags

# Tools we may recommend (status checked 2026-10; see references/loadorder.md).
TOOLS = {
    'loot': 'LOOT 0.29+ (sorts by its masterlist; run it through MO2 / use Vortex\'s built-in sort)',
    'bashed': 'Wrye Bash 315+ Bashed Patch ("Bashed Patch, 0.esp"): Leveled Lists, Import Inventory/Outfits/'
              'Actors/Cells/Stats/Names... driven by LOOT Bash Tags',
    'synthesis': 'Synthesis 0.36+ (needs the .NET SDK; run through MO2; Synthesis.esp loads after the Bashed '
                 'Patch, before DynDOLOD)',
    'fusion': 'Synthesis Fusion Patcher (Nexus SSE 96297): Bash-Tag driven merge of lists, keywords, stats, '
              'names... - the maintained alternative to Mator Smash',
    'gsp': 'Generic Synthesis Patcher (Nexus SSE 130978): rule-based Fill / Forward / Merge',
    'smash': 'Mator Smash - legacy: official 1.0.2 (2018) drops .esl plugins; only "Unofficial Mator Smash '
             'Updated" (Nexus SSE 39378, 2021, predates header 1.71) works on SE; last resort, check in SSEEdit',
    'easynpc': 'NPC Plugin Chooser 2 (Nexus SSE 157055, maintained) or EasyNPC (Nexus SSE 52313, unmaintained '
               'since 2022): choose each NPC\'s appearance mod, keep the other mods\' NPC changes',
    'facefixer': 'FaceFixer / FacegenBaseline (Synthesis patchers that forward face data; FaceGen files must '
                 'come from the same mod)',
    'kid': 'Keyword Item Distributor / Spell Perk Item Distributor (SKSE: add keywords/items/spells at '
           'runtime, no plugin conflict)',
    'xedit': 'SSEEdit 4.1.5+ (see every conflict with -vqsc through MO2; build a manual patch)',
    'qac': 'SSEEdit Quick Auto Clean (SSEEdit -qac; one plugin at a time with only its masters loaded)',
    'ck': 'Creation Kit (Bethesda\'s editor: resave LE plugins; navmesh edits are made and finalized there)',
    'eslifier': 'ESLifier (Nexus SSE 145168, maintained): flags or compacts plugins and patches FaceGen, voice, '
                'scripts, SEQ, SKSE configs and dependent plugins to match',
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


def _records_arg(keys, sigs, limit=8):
    """(merge-command record selection, trailing note). Few records are listed;
    for many, select by record type (merge then takes every record of those
    types that two or more of the sources change)."""
    keys = list(dict.fromkeys(keys))
    if len(keys) <= limit:
        return '--records ' + ' '.join(keys), ''
    return ('-t ' + ','.join(sorted(sigs)),
            f' ({len(keys)} records: this merges every {"/".join(sorted(sigs))} record that two or more of the '
            'sources change; esp scan --json lists the exact records)')


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
                        ['bashed', 'synthesis', 'loot']),
    'stale-patch': (2, 'Generated patches must be rebuilt after the mod list or order changes.',
                    ['bashed', 'synthesis']),
    'generated-order': (2, 'Each generator only sees what loads before it.', ['bashed', 'synthesis', 'loot']),
    'synthesis-split': (2, 'Synthesis expects its split files to be adjacent.', ['synthesis']),
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
                           'Otherwise make a small patch on top of both: esp merge {} {} --into "Patch.esp" {}{}'
                           .format(_q(patch), _q(winner), *_records_arg([c.formkey for c in cs],
                                                                         {c.sig for c in cs}))],
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
            # not compared (beyond --max-deep): fall back to the quick rule
            todo = [c for c in cs if (c.deep or {}).get('status') in ('lists', 'forwardable', 'clash')
                    or (c.deep is None and not c.patched)]
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
        gen = {p for p in plugins if model is not None and scanner.by_low.get(p.lower()) is not None
               and model.is_generated(scanner.by_low[p.lower()])}
        merge_plugins = [p for p in plugins if p not in gen]
        how, tools = _how(cat, todo, merge_plugins if len(merge_plugins) >= 2 else plugins, deep, tags)
        if deep and any(c.deep is None for c in todo):
            why_bits.append(f'{sum(1 for c in todo if c.deep is None)} not compared (raise --max-deep)')
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
                          'With this many overlapping list and field edits, generated patches are less work than '
                          'hand-made ones.',
                          ['Build a Bashed Patch first (Wrye Bash 315+): leveled lists, inventories, outfits, '
                           'actor spells/perks/factions, and tagged stats, names and cell data.',
                           'Then run Synthesis with Synthesis Fusion Patcher (unions keyword and item lists, uses '
                           'the same Bash Tags) or Generic Synthesis Patcher for what the Bashed Patch does not '
                           'cover. Synthesis.esp loads after the Bashed Patch.',
                           'Mator Smash only as a last resort (see tools); never xEdit "Create Merged Patch" '
                           '(obsolete).',
                           'Important records (quests, scripts, perks, navmesh): hand-made patch '
                           '(esp merge / esp copy, or SSEEdit).',
                           'Generated patches load last (Bashed/Smashed, then Synthesis, then DynDOLOD) and must be '
                           'rebuilt after any change to the mod list or order.'],
                          ['bashed', 'synthesis', 'fusion', 'smash']))
    return out


def _lost_entries(cs):
    """[(plugin, sig, kind, detail)] from deep results."""
    out = []
    for c in cs:
        for l in (c.deep or {}).get('losers', []):
            for sig, kind, det in l['lost']:
                out.append((l['plugin'], sig, kind, det))
    return out


def _how(cat, cs, plugins, deep, tags=None):
    """Concrete steps (and tools) for one conflict group."""
    tags = tags or (lambda name: [])
    pl = ' '.join(_q(p) for p in plugins)
    recs, recs_note = _records_arg([c.formkey for c in cs], {c.sig for c in cs})
    kinds = set()
    npc_kind = set()
    for c in cs:
        d = c.deep or {}
        kinds.add(d.get('status'))
        if d.get('npc'):
            npc_kind.add(d['npc'])
    lost = _lost_entries(cs)
    merge_cmd = f'esp merge {pl} --into "Patch.esp" {recs}{recs_note}'
    if cat == 'navmesh':
        return (['Not auto-mergeable (the Bashed Patch, Smash and Synthesis mergers all skip navmeshes). Use the '
                 'navmesh patch from the mod pages if one exists; otherwise choose the winner by load order or '
                 'build a navmesh patch in the Creation Kit.',
                 'Deleted navmeshes are a crash risk and are not fixed by cleaning tools.'],
                ['ck', 'xedit'])
    if cat == 'quests':
        return (['Quests, dialogue, scenes and AI packages carry scripts (VMAD) and conditions that no automatic '
                 'tool merges: use the authors\' compatibility patch if there is one.',
                 f'Otherwise compare (esp conflicts {pl} --details) and patch by hand: esp copy <winner> <record> '
                 '--to Patch.esp --create, then forward the other mod\'s changes with esp set (or in SSEEdit).'],
                ['xedit', 'esp-copy'])
    if cat == 'leveled':
        steps = ['Build a Bashed Patch (Wrye Bash 315+, Leveled Lists): the standard merge for leveled lists; LOOT '
                 'supplies the Delev/Relev tags.']
        removers = sorted({p for p, sig, kind, det in lost if kind == 'list' and re.search(r' -[1-9]', det)})
        untagged = [p for p in removers if 'Delev' not in tags(p)]
        if untagged:
            steps.append(f'{", ".join(untagged)} remove(s) entries but have no Delev tag: the Bashed Patch keeps '
                         'removals only from Delev-tagged plugins (add the tag in Wrye Bash or in '
                         'Data/BashTags/<plugin>.txt), or merge with esp merge, which keeps removals.')
        steps.append(f'For a few records without Wrye Bash: {merge_cmd}')
        steps.append('Alternatives: Synthesis Fusion Patcher or leveledlistresolver (not together with the Bashed '
                     'Patch\'s leveled lists).')
        return steps, ['bashed', 'esp-merge', 'fusion']
    if cat == 'containers':
        sigs = {c.sig for c in cs}
        steps = []
        if sigs & {'CONT', 'OTFT'}:
            steps.append('Bashed Patch Import Inventory / Import Outfits (tags Invent.Add/Change/Remove, '
                         'Outfits.Add/Remove) merges container and outfit contents.')
        steps.append(f'Or merge directly: {merge_cmd} (form lists too, which the Bashed Patch does not merge)')
        return steps, ['bashed', 'esp-merge', 'fusion']
    if cat == 'npc':
        if npc_kind and npc_kind <= {'visual'}:
            return (['Appearance-only conflict: choose which mod\'s look each NPC gets with NPC Plugin Chooser 2 or '
                     'EasyNPC. The winning record and its FaceGen files must come from the same mod, or the NPC '
                     'gets the dark-face bug.',
                     'One appearance mod should simply win: FaceFixer (Synthesis) forwards its face data onto '
                     'the winning record; its FaceGen files must win in the mod manager too.'],
                    ['easynpc', 'facefixer'])
        steps = [f'Forward the non-appearance changes (stats, AI, factions, perks, inventory): {merge_cmd}',
                 'Or Bashed Patch Import Actors / Factions / Perks / Spells / Inventory (Actors.*, NPC.*, '
                 'Invent.* tags).']
        if 'mixed' in npc_kind or not deep:
            steps.append('If an appearance mod is involved, keep its face data and FaceGen together (NPC Plugin '
                         'Chooser 2 / EasyNPC); the Bashed Patch cannot import faces for Skyrim.')
        return steps, ['esp-merge', 'bashed', 'easynpc']
    if cat in ('items', 'crafting'):
        steps = []
        if any(sig == 'KWDA' for _p, sig, _k, _d in lost):
            steps.append('Keyword lists differ: union them with esp merge (keeps every mod\'s additions and '
                         'removals) or Synthesis Fusion Patcher, or add keywords at runtime with KID. The Bashed '
                         'Patch Keywords tag only lets the last tagged plugin win.')
        steps.append(f'{"Fields" if steps else "Stats, names, models, sounds"}: {merge_cmd} (review with esp show)')
        steps.append('Many records: Bashed Patch Import Stats / Names / Graphics / Sounds / Keywords with LOOT tags, '
                     'or Synthesis Fusion Patcher.')
        if 'clash' in kinds:
            steps.append('Some fields were changed differently by each mod ("clash"): choose the value per field '
                         'with esp set on the patch.')
        return steps, ['esp-merge', 'bashed', 'fusion', 'kid']
    if cat == 'magic':
        return (['Perk entry points, conditions and magic effect scripts need a hand-made patch (esp copy + esp '
                 'set, or SSEEdit).',
                 f'Plain list/field changes: {merge_cmd}',
                 'Stat-only changes: Bashed Patch EffectStats / SpellStats / EnchantmentStats tags.'],
                ['esp-merge', 'xedit', 'bashed'])
    if cat == 'actors':
        return ([f'Forward the changes: {merge_cmd}',
                 'Races: the Bashed Patch R.* tags cover spells, stats, skills, voices and body size; head data '
                 'needs a hand-made patch. Factions: Relations.* tags.'],
                ['esp-merge', 'bashed', 'xedit'])
    if cat == 'settings':
        return (['Only one value can win: the last plugin decides. Reorder if you prefer the other value, or set '
                 'it in a patch (esp copy <winner> <record> --to Patch.esp --create; esp set Patch.esp <record> '
                 'DATA=<value>).'],
                ['esp-copy'])
    if cat == 'placed':
        return (['Usually fine to let load order decide (one mod moves or edits the object). If one mod deletes '
                 'or disables it and the other changes it, pick the winner by load order or patch by hand.'],
                ['xedit'])
    if cat == 'landscape':
        return (['Landscape edits do not merge: choose the winner by load order, use the authors\' patch, or a '
                 'mod-specific Synthesis forwarder (e.g. Northern Roads Patcher); seams or floating objects mean '
                 'a patch is needed.'], ['xedit', 'ck', 'synthesis'])
    if cat == 'cells':
        return ([f'Forward the losing fields (lighting, water, music, location, owner, name...): {merge_cmd}',
                 'Or Bashed Patch Import Cells with C.* tags (C.Light, C.Water, C.Music, C.Location, C.Owner, '
                 'C.Name...). Lighting/weather overhauls often ship compatibility patches; check the mod pages.'],
                ['esp-merge', 'bashed'])
    if cat == 'keywords':
        return (['Keyword and action records rarely conflict meaningfully; the last plugin wins. Patch only if a '
                 'mod needs its own version.'], ['esp-copy'])
    steps = [f'Small set: {merge_cmd} (review the result with esp show).']
    if 'clash' in kinds:
        steps.append('Some fields were changed differently by each mod ("clash"): choose the value per field with '
                     'esp set on the patch.')
    steps.append('Many records across many mods: Synthesis Fusion Patcher / Generic Synthesis Patcher, or a '
                 'hand-made patch in SSEEdit.')
    return steps, ['esp-merge', 'fusion', 'gsp', 'xedit']


def from_checks(dirty, navcells, edid_dups, collisions, reverts, scanner):
    out = []
    for name, d in sorted(dirty.items()):
        if d['deleted_navmesh']:
            out.append(Advice(1, 'dirty', f'{name} deletes {d["deleted_navmesh"]} navmesh(es)',
                              'Deleted navmeshes can crash the game when the area loads.',
                              ['Check LOOT\'s messages and the mod page for a fixed version; otherwise repair it '
                               'by hand (SSEEdit or the Creation Kit). Quick Auto Clean does not fix deleted '
                               f'navmeshes. Records: {", ".join(d.get("navmeshes", [])[:8])}'],
                              ['xedit', 'ck'], [name]))
        if d['udr']:
            out.append(Advice(2, 'dirty', f'{name} deletes {d["udr"]} placed reference(s)',
                              'Deleted references (UDRs) can crash the game when other mods or scripts touch them.',
                              [f'Run SSEEdit Quick Auto Clean on {name} alone (only its masters loaded); first '
                               'check LOOT\'s messages for it - a few plugins must not be cleaned.',
                               f'Or fix them here: esp delete {_q(name)} {" ".join(d.get("refs", [])[:8])} --disable '
                               '(restores each reference from its master, then undeletes and disables it the way '
                               'xEdit does).'],
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
                          ['Forward the fixes into a patch that loads after {}: esp merge {} {} --into "Patch.esp" '
                           '{}{}'.format(plugin, ' '.join(_q(f) for f in fixers), _q(plugin),
                                         *_records_arg([scanner.formkey(k) for k in keys],
                                                       {scanner.versions[k][0].sig for k in keys}))],
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
                          [f'No FaceGen, voice files, scripts, SKSE/INI configs or dependent plugins found for: '
                           f'{", ".join(c.entry.name for c in compact[:8])} (esp compact <plugin>, then esp esl '
                           '<plugin> --flag, also works for these; check esp eslify --configs --deep-configs first '
                           'if configs live in other mod folders)'
                           if compact else ''] + steps[2:],
                          ['eslifier'], [c.entry.name for c in compact + care]))
        out[-1].how = [h for h in out[-1].how if h]
    return out


def sort_advice(advice):
    return sorted(advice, key=lambda a: (a.priority, a.kind, a.title))
