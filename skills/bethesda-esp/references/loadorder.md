# Load order, conflicts and patching strategy (Skyrim SE / AE)

Background for `esp loadorder`, `esp scan` and `esp eslify`. Plugins only; BSA archives and
loose-file priority (the mod manager's left pane) are a different topic. Facts checked October
2026 against libloadorder, libloot, the LOOT masterlist, xEdit, Wrye Bash, Synthesis and ESLifier.

## Contents

1. How the game builds the load order
2. Limits and light plugins
3. Where the load order lives (Steam/GOG/Epic, MO2, Vortex)
4. How sorting works (LOOT) and what this skill does
5. Conflicts: what "winning" means
6. Which tool for which conflict
7. Generated patches
8. Turning plugins light (ESLify)
9. Dirty plugins
10. Typical workflow for an agent

---

## 1. How the game builds the load order

1. **Hardcoded plugins** always load first, in this order, whatever plugins.txt says:
   `Skyrim.esm`, `Update.esm`, `Dawnguard.esm`, `HearthFires.esm`, `Dragonborn.esm`.
2. **Creation Club** plugins listed in `Skyrim.ccc` (next to `SkyrimSE.exe`, not in Data) load
   next, in that file's line order, if installed. Since 1.6.1130 the last line is
   `_ResourcePack.esl`. They are always active; the only way to stop one is to remove/hide the file.
3. Then the **plugins.txt** order, with **masters first**: a plugin is a master if it has the ESM
   flag (TES4 flag 0x1) or the `.esm`/`.esl` extension. Inside each block the plugins.txt order holds.
4. **Hoisting**: if a master-flagged plugin lists a later plugin as its master (even a regular
   `.esp`), the game moves that plugin to just before it. LOOT refuses to sort such a load order
   (`master-needs-nonmaster`). A light master must never depend on a regular plugin.
5. A regular plugin loaded before its own master: behaviour is undefined (lost overrides or a
   crash); always an error.
6. Missing or inactive masters: the game crashes on start. Exception: Bashed Patch "Filter"
   patches (Bash Tag `Filter`) may have missing masters.

Light plugins (`.esl` file, or ESL flag 0x200 on any plugin) all share load index `FE`
(`FE000`-`FEFFF`) but still **win or lose conflicts by their position** in the load order.
An ESL-flagged `.esp` stays in the regular block; an `.esl` file or ESM+ESL plugin loads with
the masters. So flagging an `.esp` does not change which overrides win; renaming it to `.esl`
does.

## 2. Limits and light plugins

| | limit |
|---|---|
| full (non-light) plugins | 254 (`00`-`FD`) when any light plugin is active - always on AE because of CC files - else 255 |
| light plugins | 4096 |
| new records in a light plugin, header < 1.71 | object IDs `0x800`-`0xFFF` (2048) |
| new records in a light plugin, header 1.71 | `0x001`-`0xFFF` (4095); needs game 1.6.1130+ (or BEES on 1.5.97-1.6.659) |

Header (HEDR) versions: 0.94 = Skyrim LE (needs conversion), 1.70 = SE (some LE files are 1.70
too: the record form version, 43 = LE / 44 = SE, is the better test), 1.71 = SE after the
Creations update (1.6.1130, Dec 2023; xEdit 4.1.5+, Mutagen/Synthesis and ESLifier write 1.71 by
default). With header 1.71 the object IDs 0x001-0x7FF become usable by **every** plugin that has
a master, full ones included; a plugin with an older header that overrides or references those
records of a 1.71 master breaks and must be saved as 1.71 too (`hedr-low-range`). A 1.71 plugin crashes 1.5.97/1.6.640/1.6.659 at start unless **Backported Extended ESL
Support** (BEES, `SKSE/Plugins/BackportedESLSupport.dll`) is installed. Game 1.7.x (2026) did not
change these rules. Form version 43 (LE) records mostly work; weapon critical data (WEAP CRDT) is
read wrongly - re-save in the SE Creation Kit (with CK Fixes).

A light plugin with new records outside its range breaks saves permanently (LOOT error).

## 3. Where the load order lives

- **Steam**: `%LOCALAPPDATA%\Skyrim Special Edition\Plugins.txt`. GOG: `... Edition GOG`
  (Galaxy64.dll in the game folder), Epic: `... Edition EPIC` (EOSSDK-Win64-Shipping.dll), Microsoft
  Store: `... Edition MS`. Proton: `steamapps/compatdata/489830/pfx/drive_c/users/steamuser/AppData/Local/...`.
- Format: Windows-1252, one plugin per line, `*` = active, lines starting with `#` ignored, every
  installed plugin listed (inactive without `*`), line order = load order. Hardcoded and CC
  plugins are not written. `loadorder.txt` is ignored by Skyrim SE (MO2/Vortex still write it).
- **MO2**: `<instance>/profiles/<profile>/plugins.txt` (+ `loadorder.txt`, `modlist.txt`). The
  game sees it through MO2's virtual file system - never edit the AppData copy for MO2 users.
  MO2 takes the **order from the profile's `loadorder.txt`** when it starts (only the `*` flags
  come from plugins.txt), so a hand-edited order must be written to both files
  (`esp loadorder --mo2 ... --write <profile>/plugins.txt --write-loadorder <profile>/loadorder.txt`
  with MO2 closed) - or applied in MO2 itself.
  `modlist.txt`: first line = highest priority, `+` enabled, `-` disabled; Overwrite beats
  everything. Plugin files live in `<mods>/<mod>/`. Close MO2 before editing its files.
- **Vortex**: writes `%LOCALAPPDATA%` plugins.txt directly; its rules/groups live in
  `%APPDATA%\Vortex\skyrimse\userlist.yaml`, and Vortex re-sorts automatically - change the order
  through Vortex rules, not by editing plugins.txt.
- **LOOT** data: `%LOCALAPPDATA%\LOOT\games\Skyrim Special Edition\` (`masterlist.yaml`,
  `userlist.yaml`).

`esp loadorder` takes `--plugins-txt`, `--mo2 <profile folder>` (reads ModOrganizer.ini, the
mod folders and modlist priority), or plugin files on the command line, plus `--data` for the
game Data folder (finds `Skyrim.ccc` and `SkyrimSE.exe` next to it).

## 4. How sorting works

LOOT (and this skill) sort **masters and regular plugins separately** and keep the hardcoded/CC
prefix. Rules by strength:

1. **Hard**: each plugin after its masters; LOOT masterlist/userlist `req` and `after` rules.
   Contradictions = "cyclic interaction" (sorting fails in LOOT).
2. **Groups** (soft): each plugin has a LOOT group (default `default`); a group loads after the
   groups it is declared after. The SE masterlist chain runs Main Plugins -> Creation Club ->
   Unofficial Patches -> Fixes -> Resources & Frameworks -> Early Loaders -> New Content ->
   Underrides -> **default** -> Low Priority Overrides -> ... -> Conflict Resolution Patches
   (Late) -> **Dynamic Patches** (Bashed/Smashed/zPatch) -> **Late Fixes & Changes** (Synthesis,
   ParallaxGen) -> **Dynamic LOD** (DynDOLOD, Occlusion). Edges from `default` plugins give way
   when they contradict other groups.
3. **Overlap** (soft): if two plugins override a common record and their total override counts
   differ, the one that overrides **more** records loads first (the more specific one wins).
4. Everything else keeps the current order.

This skill bundles a compact copy of the LOOT SE masterlist (CC0; `esp loot-update` refreshes it
from GitHub, needs PyYAML), reads the user's LOOT or Vortex `userlist.yaml` automatically
(`--userlist` to choose, `--no-loot` to disable), evaluates LOOT conditions (`active()`,
`file()`, `checksum()`, `version()`...), and reports LOOT's requirement, incompatibility, dirty
and message entries. It is **not** a byte-for-byte LOOT clone: LOOT also compares BSA contents,
sorts inactive plugins, and uses its own tie-break. Use the output to explain and fix problems;
let LOOT (through the mod manager) do the final sort when the user has it.

**Making an order stick**: LOOT re-sorts from rules, so a manual move is lost on the next sort.
Persist intent in the userlist: LOOT GUI (Edit metadata -> Load After / Group) or
```yaml
plugins:
  - name: 'My Patch.esp'
    after: [ 'Some Mod.esp' ]
```
in `userlist.yaml` (Vortex: plugin rules / groups in its UI). `esp loadorder --rules rules.json`
takes the same intent for this tool: `{"My Patch.esp": {"after": ["Some Mod.esp"]}}`.

## 5. Conflicts: what "winning" means

For any one record, only the version from the **last-loaded** plugin that contains it is used
(the rule of one). Load order can only pick the winner; it never combines two mods' changes. A
**patch** combines them: it loads after both and contains the merged record.

`esp scan` (quick) lists every record two or more mods override, by category and by the set of
plugins involved, and whether the winner already includes the others (it has them as masters:
"patched"). `esp scan --deep` loads those records and compares each loser with the version it
started from (its own masters) and with the winner:

| status | meaning | typical fix |
|---|---|---|
| identical | all versions equal | nothing |
| resolved | the winner contains everyone's changes | nothing |
| lists | list entries (leveled list, inventory, keywords, perks...) from a loser are missing | merge (Bashed Patch / `esp merge`) |
| forwardable | a loser changed fields the winner leaves at the old value | forward them (`esp merge`, Bashed tags) |
| clash | two mods changed the same field to different values | decide per field (`esp set` on a patch) |

Other checks: patches beaten by a later plugin (`patch-overridden`), winners that undo fixes
from Update.esm/DLC or USSEP because they do not use them as masters (`reverts-fixes`, field
list with `--deep`), navmesh edits to the same cell from several plugins, deleted navmeshes and
references, injected records colliding, duplicate EditorIDs.

## 6. Which tool for which conflict

| conflict | first choice | alternatives / notes |
|---|---|---|
| leveled lists (LVLI/LVLN/LVSP) | **Bashed Patch** (Wrye Bash 315+, Leveled Lists) | removals are kept only from plugins tagged `Delev` (LOOT supplies tags; add missing ones in Wrye Bash or `Data/BashTags/<plugin>.txt`); few records: `esp merge`; Synthesis Fusion Patcher or leveledlistresolver (not together with the Bashed Patch's lists) |
| container / NPC inventory, outfits | Bashed Patch Import Inventory / Outfits (`Invent.*`, `Outfits.*`) | `esp merge`; form lists (FLST) are not merged by the Bashed Patch |
| keyword lists (KWDA) | `esp merge` / hand-made patch (union) | Synthesis Fusion Patcher, Generic Synthesis Patcher, or KID at runtime. The Bashed Patch `Keywords` tag is last-wins, not a union |
| item stats, names, models, sounds | Bashed Patch Import Stats/Names/Graphics/Sounds with tags | `esp merge`, Fusion Patcher |
| NPC appearance | **NPC Plugin Chooser 2** (maintained) or EasyNPC (unmaintained) | FaceFixer/FacegenBaseline (Synthesis). The winning record and its FaceGen files must come from the same mod (dark-face bug). The Bashed Patch cannot import faces for Skyrim |
| NPC stats, AI, factions, perks | `esp merge` | Bashed Patch Import Actors (`Actors.*`, `NPC.*`); spells, perks and AI packages merge, but Import Factions is last-tagged-wins, so faction additions from two mods need `esp merge` or a hand-made patch |
| cells (lighting, water, music, owner...) | `esp merge` | Bashed Patch Import Cells (`C.Light`, `C.Water`, ...); LOOT has cell groups |
| races | Bashed Patch `R.*` tags | head data: hand-made patch |
| perks (entry points), magic effects, spells | hand-made patch | stats only: EffectStats/SpellStats/EnchantmentStats tags |
| quests, dialogue, scenes, packages, scripts (VMAD) | authors' compatibility patch | otherwise hand-made in SSEEdit; no tool merges scripts or conditions |
| navmesh | authors' navmesh patch | otherwise choose a winner, or rebuild in the Creation Kit; nothing merges navmeshes; deleted navmeshes need manual repair |
| landscape | choose a winner / authors' patch | mod-specific Synthesis forwarders (e.g. Northern Roads Patcher) |
| GMST / GLOB | load order (one value wins) | set the value in a patch |
| many records across many mods | Bashed Patch, then Synthesis (Fusion Patcher) | Mator Smash only as a last resort (below) |

Tool status (October 2026):

- **Wrye Bash** 315 (Sept 2026), maintained. SE: no plugin merging into the Bashed Patch;
  auto-splits at 255 masters; can ESL-flag the patch. Patch name `Bashed Patch, 0.esp`.
- **Synthesis** 0.36.x, maintained; needs the .NET SDK; run through MO2; each group writes one
  plugin (`Synthesis.esp`); Compaction = Small/Light makes the patch light; it writes header 1.71
  (set Master Version Override 1.70 on old games without BEES). CLI: `Synthesis.CLI run-pipeline`.
  Smash-like patchers: **Synthesis Fusion Patcher** (Bash-Tag driven), **Generic Synthesis
  Patcher** (rule driven). There is no Synthesis cleaning patcher.
- **Mator Smash**: legacy; STEP staff (2023) state the consensus is to avoid Smash and zMerge in
  favour of a Bashed Patch plus hand-made xEdit fixes. Official 1.0.2 (2018) removes `.esl`
  plugins from the load order and stops at 254 plugins - unusable on AE. The community fork
  "Unofficial Mator Smash Updated" (Nexus SSE 39378, 2.0.0-beta-5, last update 2021) handles ESLs
  and adds `Smash.OverrideAll` and sub-element script (VMAD) merging for 12 record types, but is
  beta and predates header 1.71. Use it only as a last resort with `Smash.All`, build it after
  the Bashed Patch, and check the result in SSEEdit - especially quest/script merges; it skips
  navmeshes.
- **xEdit (SSEEdit)** 4.1.5q (2026), maintained; `-vqsc` shows all conflicts. Its "Create Merged
  Patch" is obsolete - do not use it.
- **zMerge** (zEdit 0.6.7, 2022) and Merge Plugins (2016) are unmaintained; merging also breaks
  name-based references (SPID/KID/OAR configs, scripts). Prefer ESL flags to reduce plugin count.
- **SPID / KID / SkyPatcher** apply changes at runtime and avoid record conflicts for purely
  additive distribution.

## 7. Generated patches

Bashed/Smashed patches, Synthesis output, DynDOLOD/Occlusion are **generated from the current
load order** and must:

- load after every plugin they read, in the order Bashed/Smashed -> Synthesis -> DynDOLOD
  (`generated-order`); Synthesis split files (`Synthesis.esp`, `Synthesis_2.esp`) next to each other;
- be rebuilt after any change to the mod list or order (`stale-patch`: older than a plugin
  loading before it);
- never have regular plugins after them (`after-generated`), except their own outputs.

## 8. Turning plugins light (ESLify)

`esp eslify` sorts candidates into:

- **flag** - every new record already fits the light range: set the ESL flag
  (`esp esl X.esp --flag`). No FormIDs change, dependents keep working. Remaining risks: scripts
  that use `GetModByName` (it does not see light plugins), SEQ files (dialogue may need a save
  and reload), and changing plugins under an ongoing save is disputed - do it before a playthrough.
- **flag-171** - fits only the 1.71 range: `esp esl X.esp --header-171 --flag` (game 1.6.1130+
  or BEES; the plugin and its dependents need Skyrim.esm as a master and header 1.71).
- **compact / compact-care** - needs FormID compaction (renumbering). That breaks existing saves
  and everything that names the FormIDs: FaceGen files (dark faces), voice files (silent lines),
  SEQ files, `GetFormFromFile` in scripts, SKSE configs (SPID/KID/BOS/OAR/DAR...), dependent
  plugins. Use **ESLifier** (Nexus SSE 145168, maintained), which patches all of those into an
  output mod that must win conflicts, and re-run its "Scan and Rebuild" after mod changes.
  `esp compact` / xEdit's "Compact FormIDs for ESL" only renumber the plugin itself - only for
  `compact` plugins with nothing depending on them, and only for a new game.
- **no** - too many records, new worldspaces (lose landscape when light), new cells without SSE
  Engine Fixes 7.0.13+ (cells lose temporary references / reload wrongly), a master that needs a
  regular plugin, SKSE DLLs that hard-code its FormIDs, generated patches (use the tool's own
  ESL option).

ESLify Everything is discontinued (use ESLifier). Never rename `.esp` to `.esl` just to make it
light: that moves it into the master block and changes conflict winners.

## 9. Dirty plugins

- LOOT identifies dirty plugins by CRC32 from its masterlist (ITMs, deleted references,
  deleted navmeshes, and which xEdit version found them); `esp loadorder` reports these.
- `esp scan` also finds deleted references and navmeshes directly from record flags.
- Clean with **SSEEdit Quick Auto Clean** (`SSEEdit.exe -qac`), one plugin at a time with only
  its masters loaded; read LOOT's messages first - a few plugins must not be cleaned. QAC
  removes ITMs and undeletes+disables deleted references; deleted navmeshes need manual repair.
- This skill: `esp itm X.esp --clean` (ITMs), `esp delete X.esp <refs> --disable` (restores each
  deleted reference from its master and undeletes + disables it, as xEdit does).
- Official masters (Update.esm, DLC): the LOOT masterlist lists them as dirty and recommends
  QAC (Dawnguard.esm also needs manual cleaning of its wild edits); keep a backup of the originals.

## 10. Typical workflow for an agent

1. Find the load order: MO2 profile folder (`--mo2`), or plugins.txt + `--data`.
2. `esp loadorder ... --groups` - fix every **error** first (missing/inactive masters, master
   order, invalid light plugins, header 1.71 without BEES, LOOT incompatibilities).
3. Apply the suggested order: via LOOT in the mod manager when available; otherwise
   `esp loadorder ... --write plugins_sorted.txt` (MO2: also `--write-loadorder`), review, then
   replace the files with the mod manager closed. Persist custom rules in the userlist.
4. `esp scan ...` for a quick picture, `esp scan ... --deep` for whose changes are lost.
5. Fix in this order: crashes (deleted navmeshes, injected collisions) -> load order -> reverted
   official/USSEP fixes -> patches that are overridden -> conflicts (high -> low).
   Prefer authors' compatibility patches; then Bashed Patch for lists; `esp merge` for small
   targeted patches; Synthesis/Fusion for broad merges; hand-made patches for quests/scripts.
6. Over the plugin limit or close to it: `esp eslify` (flag first; compaction via ESLifier).
7. Rebuild generated patches last (Bashed -> Synthesis -> DynDOLOD), then re-run `esp scan`.
