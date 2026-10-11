---
name: bethesda-esp
description: Read, inspect, edit and patch Bethesda plugin files (.esp, .esm, .esl) for Skyrim Special Edition / Anniversary Edition (Skyrim LE plugins also work), and analyse whole load orders. Use when the user wants to look inside a mod's plugin, list or search records (weapons, armor, NPCs, leveled lists, recipes, containers, cells, placed references, quests, dialogue), change fields, delete or disable records, check or sort a plugin load order (plugins.txt, MO2 profile, LOOT rules, masters, ESL limits), scan a load order for conflicts and decide how to fix them (compatibility patch, merged patch, Bashed Patch, Synthesis, Mator Smash, EasyNPC), find ESL-flag candidates (ESLify), clean ITMs and deleted references, add/clean masters, compact FormIDs, delocalize strings, or read BSA archives - xEdit/SSEEdit and LOOT-style work from the command line. Bundled zero-dependency Python CLI keeps unmodified data byte-identical; optional Spriggit (Mutagen) path for full-schema YAML editing.
license: MIT
compatibility: Needs Python 3.8+ (no packages). Optional - .NET 10 SDK for the Spriggit full-schema workflow.
---

# Bethesda plugin editor (Skyrim SE)

## The tool

`scripts/esp.py` in this skill's folder. Run it with Python 3:

- Claude Code: `python3 "${CLAUDE_SKILL_DIR}/scripts/esp.py" <command> ...`
- Antigravity / other agents: `python3 <absolute path of this skill folder>/scripts/esp.py ...`
  (usually `<workspace>/.agents/skills/bethesda-esp/` or `~/.gemini/config/skills/bethesda-esp/`).
- On Windows use `python` (or `py`) instead of `python3`.

Below, **`esp`** stands for that full command. `esp <command> -h` shows every option.

Records can be named by **EditorID** (`IronSword`), **FormKey** (`012EB7:Skyrim.esm` - object id +
the plugin that defines it; master-order independent, preferred) or **file-local FormID**
(`0x00012EB7` - top byte is the master index *in that file*). Output shows FormKeys and
`EditorID [TYPE:FormKey]` labels.

## Ground rules

1. **Never modify game masters** (`Skyrim.esm`, `Update.esm`, `Dawnguard.esm`, `HearthFires.esm`,
   `Dragonborn.esm`, `cc*.esm`) or another author's mod unless the user explicitly wants that.
   The normal way to change anything is an **override in a separate patch plugin** (`esp copy ... --to Patch.esp --create`, then `esp set` on the patch).
2. Write commands edit **in place and keep a `.bak`** (`-o out.esp` writes elsewhere, `--dry-run`
   previews). Tell the user which file changed and where the backup is.
3. Point `--data` at the game's `Data` folder (or work inside it) so masters, strings and BSAs are
   found. Masters next to the plugin are found automatically.
4. Before editing a record, `esp show` it. After writing, re-`show` it (or `esp verify file`) to confirm.
5. If the user's mod manager is MO2, plugins live in `mods/<ModName>/` and the load order in
   `profiles/<Profile>/plugins.txt`; pass the files you need (or `--data` to the real Data folder).
6. Placed references (REFR/ACHR) from masters must not be *deleted* (crash risk) - use
   `esp delete --disable` (undelete + initially disabled + moved below the world, as xEdit does).
7. New records in an ESL-flagged plugin need object IDs 0x800-0xFFF (0x001-0xFFF with header 1.71,
   game 1.6.1130+) (`esp esl`, `esp compact`).
8. Plugins that use the edited plugin as a master break if you delete/renumber records they use.

## Inspect

```bash
esp info MyMod.esp                       # masters, flags, counts by type, ESL eligibility
esp list MyMod.esp -t WEAP --name sword  # filter: -t TYPE, --edid REGEX, --name REGEX, --new, --overrides
esp show MyMod.esp IronSword             # decoded fields; FormIDs resolved to EditorID [TYPE:FormKey]
esp show MyMod.esp IronSword --json      # editable JSON (fields list in file order)
esp show MyMod.esp 0x0100ABCD --raw      # hex of every subrecord
esp find Skyrim.esm MyMod.esp --ref IronSword      # who references a record (any plugins)
esp find MyMod.esp --text "dragon" -t BOOK         # regex over names, descriptions, book text...
esp tree MyMod.esp --records             # GRUP structure (cells, worldspaces, topics)
esp schema WEAP                          # field names/types/flags for a record type
esp conflicts A.esp B.esp C.esp --details          # records several mods override, with diffs
esp diff A.esp B.esp [RECORD...]         # compare two plugins or two versions of records
```

Unknown or context-dependent subrecords are shown as `<N bytes> hex` - they are still preserved
exactly. `esp schema` lists the 100+ decoded record types; `references/records.md` explains common fields.

## Edit fields

```bash
esp set MyMod.esp IronSword DATA.damage=12 "FULL=Sharp Iron Sword" DNAM.speed=1.1
esp set MyMod.esp IronSword KWDA+=WeapMaterialSteel KWDA-=WeapMaterialIron
esp set MyMod.esp MyChest 'CNTO+={"item":"Gold001","count":100}'  CNTO-=IronDagger
esp set MyMod.esp LItemMyList 'LVLO+={"level":5,"reference":"SteelSword","count":1}'
esp set MyMod.esp MyNpc ACBS.level=30 "ACBS.flags=Essential|Unique" DNAM.health=200
esp set MyMod.esp MyArmor DNAM.armor_rating_x100=4500 "BOD2.slots=32_Body"
esp set MyMod.esp SomeRef @flags+=InitiallyDisabled --remove XESP
```

Path syntax: `SIG.field.sub[index]`; `SIG#n` = n-th (0-based) repeated subrecord. `=` sets,
`+=`/`-=` add/remove list items or repeated subrecords (`CNTO`, `LVLO`, `SPLO`, `PRKR`, `SNAM`, `CTDA`...).
Values are JSON when they parse (`5`, `1.5`, `[..]`, `{..}`), else text. FormID values accept
EditorIDs, FormKeys or `0x...`; flags accept `A|B` or a JSON list; enums accept names.
Counters (`KSIZ`, `COCT`, `LLCT`, `SPCT`, `PRKZ`) are kept in sync automatically.
Missing subrecords are created in the right position (`esp set X Y XSCL=1.5`).

For complex or bulk edits: `esp show F REC --json > rec.json`, edit the JSON, `esp put F rec.json`
(same format; `"formid": "new"` adds a new record). `esp export F -t WEAP -o all.json` dumps many.
For scripted bulk changes use the Python API (`references/python-api.md`).

## Make a patch (compatibility / tweak)

```bash
esp conflicts ModA.esp ModB.esp --details --data "<Skyrim>/Data"          # 1. what collides
esp copy ModB.esp IronSword LItemWeaponSwords --to MyPatch.esp --create   # 2. start from the winner
esp set MyPatch.esp IronSword DATA.damage=10 KWDA+=WeapMaterialSteel     # 3. carry over the other mod's changes
esp merge ModA.esp ModB.esp --into MyPatch.esp                            # or: auto-merge lists + changed fields
```

- `copy` adds the needed masters, remaps every FormID to the patch's master list, copies parent
  CELL/WRLD/DIAL records for references and dialogue, and converts localized names to text.
- `merge` = 3-way merge against the original master version for every record two or more of the
  sources override (or `--records ...`): leveled-list entries, inventories, keywords, spells,
  perks, factions, form lists merge additions *and* removals; other fields take the last plugin
  that changed them (struct fields merged one by one). Review its report and the result.
- The patch must load **after** the mods it patches. Tell the user to enable it and sort it last.
- `esp copy X REC --to Y --as-new --edid NewId` duplicates a record as a new one (new FormID).

## Whole load order: sort, scan conflicts, plan patches

Plugins only (not BSA/loose-file priority). Give the load order as an MO2 profile folder
(`--mo2 "<MO2>/profiles/<Profile>"`, finds the game, mod folders and priorities) or as
`--plugins-txt` + `--data "<Skyrim>/Data"` (Steam: `%LOCALAPPDATA%\Skyrim Special Edition\Plugins.txt`).

```bash
esp loadorder --mo2 "D:/MO2/profiles/Default" --groups     # errors, warnings, suggested moves (and why)
esp loadorder ... --write plugins_sorted.txt               # suggested order as a plugins.txt (review first)
esp scan ...                                               # every multi-mod conflict + prioritized fixes
esp scan ... --deep [--details]                            # field-level: whose changes are lost, clashes
esp eslify ... [--configs]                                 # which plugins can be ESL-flagged, what compaction breaks
```

- `loadorder` applies the game's rules (hardcoded + Creation Club first, masters before plugins,
  hoisting, 254 full / 4096 light slots, header 1.71 vs game version/BEES) and LOOT's: a bundled
  copy of the LOOT masterlist (groups, load-after/requirement/incompatibility rules, dirty CRCs,
  warnings) plus the user's LOOT/Vortex `userlist.yaml`, then the LOOT overlap rule. Fix every
  ERROR first. Moves keep the user's order wherever no rule demands a change.
- Apply orders through the user's tool when possible: LOOT inside MO2, Vortex rules; otherwise
  replace plugins.txt with the mod manager closed (MO2: the profile's plugins.txt **and**
  loadorder.txt - `--write ... --write-loadorder ...` - because MO2 reads the order from loadorder.txt). Manual moves are
  undone by the next LOOT sort - persist them as LOOT userlist rules (`--rules` uses the same idea).
- `scan` recommendations name the tool per conflict type: leveled lists/inventories -> Bashed
  Patch (Wrye Bash) or `esp merge`; keyword unions -> `esp merge`/Synthesis Fusion Patcher/KID;
  NPC appearance -> NPC Plugin Chooser 2 / EasyNPC; quests/scripts/perks -> hand-made patch;
  navmesh -> authors' patch or Creation Kit; broad merges -> Bashed Patch then Synthesis; Mator
  Smash only as a legacy last resort. Generated patches load last (Bashed -> Synthesis ->
  DynDOLOD) and must be rebuilt after changes.
- Flag-only ESL (`esp esl X.esp --flag`) changes no FormIDs; compaction breaks saves, FaceGen,
  voice, scripts and configs - use ESLifier for those.
- `esp loot-update` refreshes the masterlist copy (needs `pip install pyyaml`).

Full background, tool status and a decision table: `references/loadorder.md`.

## Create, delete, clean

```bash
esp new MyPatch.esp --master Skyrim.esm --master Update.esm [--esl]
esp add MyMod.esp KYWD --edid MyKeyword
esp add MyMod.esp GLOB --edid MyGlobal FNAM=f FLTV=2.5
esp add MyMod.esp MISC --edid MyGem "FULL=Shiny Gem" 'DATA={"value":250,"weight":0.1}'
esp delete MyMod.esp OldRecord            # refuses if other records in the file still use it (--force)
esp delete MyPatch.esp 0x00012345 --mark  # keep an override but flag it Deleted
esp delete MyMod.esp SomeRef --disable    # safe removal of placed references (also fixes deleted refs/UDRs)
esp itm MyMod.esp [--clean]               # identical-to-master records
esp masters MyMod.esp [--add X.esm] [--clean]   # FormIDs are remapped, never broken
esp esl MyMod.esp [--flag] [--header-171]  /  esp compact MyMod.esp
esp delocalize Localized.esp -o Inline.esp      # needs its Strings/*.STRINGS (loose or in BSA)
esp bsa "Skyrim - Interface.bsa" --filter strings   # list / --extract from BSAs (SE LZ4 + LE zlib)
```

For complex record types (complete records from scratch, races, quests with aliases, packages,
scenes, navmeshes, perks with entry points), prefer copying an existing record (`copy --as-new`)
and editing it, or use Spriggit (below).

## Full-schema editing with Spriggit (optional)

Spriggit (by Noggog, built on Mutagen) converts a plugin to YAML with every field named and back.
Use it when you need fields this tool keeps raw. Setup and commands: `references/spriggit.md`.
Short version: `dotnet tool install -g Spriggit.CLI`, then
`spriggit serialize -i Mod.esp -o ModYaml -g SkyrimSE -p Spriggit.Yaml -v 0.41.0`, edit YAML,
`spriggit deserialize -i ModYaml -o Mod.esp`.

## Reading the output

- `(override)` = record defined in a master and changed here; `(new)` = defined by this plugin.
- `<lstring 123>` = localized string not found: pass `--data` (strings are in `Strings/` or in
  `Skyrim - Interface.bsa` / the mod's BSA). The first name lookup into a big master indexes it
  (tens of seconds for Skyrim.esm); the index is cached in `~/.cache/bethesda-esp/`.
- Fields starting with `_` are padding/unknown and are hidden when zero in text output.
- Float values print as the shortest decimal that round-trips; ARMO `DNAM` is armor rating x100.
- `find --ref` marks hits inside undecoded data with `?` (verify those manually).

## When something fails

- `error: X is not a master of Y` -> `esp masters Y --add X` (or use `copy`, which does it).
- `cannot find X.esm` -> pass `--data <Data folder>`.
- A field shows as raw hex -> it has no layout; edit with `{"$hex": "..."}` in JSON, or use Spriggit.
- Check results: `esp verify Plugin.esp --roundtrip` parses everything and reports problems.

## More

- `references/commands.md` - every command and option with examples
- `references/records.md` - common record types, fields, flags, condition functions, biped slots
- `references/loadorder.md` - load order rules, LOOT, conflict types and which tool fixes them, ESLify
- `references/format.md` - how plugins are built (FormIDs, masters, groups, ESL, localization)
- `references/python-api.md` - scripting bulk edits with the `esplib` package
- `references/spriggit.md` - optional full-schema YAML workflow
