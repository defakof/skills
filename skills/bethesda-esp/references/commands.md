# esp.py command reference

`esp` = `python3 <skill>/scripts/esp.py`. Every command accepts:

| option | meaning |
|---|---|
| `--data DIR` | game `Data` folder: where masters, `Strings/` and BSAs are looked up (the plugin's own folder is always searched) |
| `--encoding ENC` | code page of non-localized text (default `cp1252`; e.g. `cp1251` for Russian, `utf-8`). Env: `ESP_ENCODING` |
| `--lang NAME` | strings language for localized plugins (default `english` -> `Skyrim_english.STRINGS`) |
| `--mo2 PROFILE_DIR` (alias `--profile`) | Mod Organizer 2 profile folder: plugins, masters, strings and BSAs are found in its enabled mods by priority (Overwrite first), then the game's Data folder from ModOrganizer.ini - like the game sees them through MO2 |

The command may also come after the plugin or the options: `esp MyMod.esp info` and
`esp --mo2 P check-order` work like `esp info MyMod.esp` / `esp check-order --mo2 P`;
`esp MyMod.esp` alone runs `info`.

Commands that write also accept `-o OUT` (write a new file instead of in place),
`--no-backup` (no `.bak` when writing in place) and `--dry-run`.

Record arguments: EditorID (`IronSword`), FormKey (`012EB7:Skyrim.esm` or `Skyrim.esm:012EB7`),
or file-local FormID (`0x00012EB7`, `00012EB7`). EditorIDs are looked up in the plugin first,
then in its masters.

---

## Reading

### info PLUGIN [--json]
Masters (and whether they were found), ESM/ESL/Localized flags, header version, next object id,
record counts by type, new vs override counts, where localized strings come from, ESL eligibility.

### list PLUGIN [-t TYPE ...] [--edid RE] [--name RE] [--new|--overrides|--deleted] [--limit N] [--no-names] [--json]
One line per record: `TYPE FormKey EditorID "Name" [override] flags`. `-t` takes `WEAP`,
`WEAP,ARMO` or repeats; 3-letter types are padded (`NPC` -> `NPC_`). `--no-names` is faster
on huge files.

### show PLUGIN RECORD... [--json] [--raw]
Decoded fields in file order. Placed references and INFOs show their parent cell/world/topic.
`--json` prints the editable form used by `put` (one object, or a list for several records):

```json
{"type": "WEAP", "formid": "012EB7:Skyrim.esm", "flags": [], "form_version": 44,
 "fields": [{"EDID": "IronSword"}, {"FULL": "Iron Sword"},
            {"KWDA": ["01E718:Skyrim.esm", "08F958:Skyrim.esm"]},
            {"DATA": {"value": 25, "weight": 9.0, "damage": 7}},
            {"NNAM": {"$hex": "00000000"}}],
 "context": {"cell": "...", "child_type": 9}}
```
Localized strings appear as `{"lstring": 1234, "text": "Iron Sword"}`.

### find PLUGIN... [-t TYPE] [--edid RE] [--name RE] [--text RE] [--ref RECORD] [--limit N]
Searches several plugins at once. `--text` matches any decoded string (names, descriptions, book
text, dialogue). `--ref X` lists records whose data points at X (the subrecords that do are shown
after `<-`; `?` = found inside undecoded bytes, worth double-checking).

### diff A B [RECORD...] [-v]
Without records: counts of records only in A / only in B / in both, then field diffs for every
shared record that differs (FormIDs compared as FormKeys, so different master orders are fine).
With records: just those. `-v` also lists one-sided records.

### conflicts PLUGIN... [--load-order plugins.txt] [-t TYPE] [--details] [--differ] [--only NAME] [--include-master]
Records overridden by two or more of the given plugins (in the order given = load order), the
winner (last), and `--details` field differences. `--differ` hides conflicts where every version is
identical. `--load-order` reads an MO2/Vortex `plugins.txt` (names resolved via `--data`).

### schema [TYPE [SIG]]
Without arguments: every record type with a known layout. With a type: each subrecord, its field
names, value types, enum values and flag names, plus notes and auto-synced counters.

### tree PLUGIN [--depth N] [--records]
GRUP hierarchy: top groups, interior cell blocks/sub-blocks, worldspace blocks, cell
persistent/temporary children, topic children.

### verify PLUGIN [--roundtrip] [--top N]
Parses and decodes every record; reports errors and the most common subrecords kept as raw.
`--roundtrip` re-serializes and checks the output is byte-identical to the file.

### strings PLUGIN [--search RE] [--limit N]
For localized plugins: where the string tables were found, how many strings, regex search.

### bsa ARCHIVE [--filter RE] [--extract INNER -o OUT]
Lists or extracts files from BSA archives (v104 Skyrim LE/zlib, v105 Skyrim SE/LZ4).

---

## Writing

### set PLUGIN RECORD EDIT... [--remove SIG[#n] ...]
| edit | effect |
|---|---|
| `DATA.damage=20` | set a struct field |
| `"FULL=Steel Sword"` | set a whole subrecord (string) |
| `DNAM={"speed": 1.2, ...}` | set a whole struct (omitted padding is zero-filled) |
| `KWDA+=WeapMaterialSteel` / `KWDA-=...` | add/remove array items (FormIDs by EditorID/FormKey) |
| `CNTO+={"item":"Gold001","count":5}` | add a repeated subrecord (CNTO, LVLO, SPLO, PRKR, SNAM, EFID...) |
| `SPLO+=Fireball` | scalar repeated subrecords accept a bare value |
| `CNTO-=Gold001` / `LVLO-=IronSword` | remove the entry whose (first) FormID matches |
| `CNTO#2.count=3` | n-th occurrence (0-based) of a repeated subrecord |
| `XCLL.ambient.x_plus.r=255` | nested fields |
| `KWDA[0]=ArmorHeavy` | list index |
| `ACBS.level+=5` | numeric add/subtract |
| `"DNAM.flags=NonPlayable|CantDrop"` / `'DNAM.flags=["NonPlayable"]'` | flags by name (or int) |
| `@flags+=InitiallyDisabled` / `@flags-=Persistent` / `@flags=` | record header flags |
| `@form_version=44` | record header form version |
| `--remove XESP` / `--remove CNTO#1` | delete a subrecord |

Missing subrecords are created (with zero defaults) in schema order. Counters
(`KSIZ`, `COCT`, `LLCT`, `SPCT`, `PRKZ`) follow their lists. EditorIDs are looked up in the plugin
and its masters; a FormKey from a plugin that is not a master yet adds that master automatically.
Shell quoting: wrap edits containing spaces, `|`, `{}` or `"` in single quotes (PowerShell: double
the inner quotes or use a JSON file with `put`).

### put PLUGIN FILE.json
Adds or replaces records from `show --json` / `export` output (a single object or a list).
`"formid"` that exists -> replaced; `"formid": "new"` -> new record with the next free FormID.
New placed references/INFOs need a `"context"` (as produced by `show --json`).

### new PLUGIN [--master NAME ...] [--esm] [--esl] [--author A] [--desc D] [--force]
Empty plugin (header version 1.7, next object id 0x800). List masters in load order.

### add PLUGIN TYPE --edid EDID [EDIT...]
New record of a simple type (`GLOB`, `KYWD`, `FLST`, `GMST`, `MISC`, `LVLI`, `COBJ`, `OTFT`, `FACT`,
`SPEL`...) with the given edits applied. For types with many required fields (WEAP, ARMO, NPC_),
prefer `copy --as-new` of an existing record.

### copy SOURCE RECORD... --to DEST [--create] [--esl] [--as-new] [--edid NEW]
Copies records into DEST as overrides (default). Adds missing masters, remaps all FormIDs,
copies the parent CELL (and WRLD) of references or the DIAL of INFOs, delocalizes strings when
the source is localized and the destination is not. `--create` makes DEST with SOURCE's masters +
SOURCE. `--as-new` gives the copy a new FormID in DEST (and `--edid`, default `<EditorID>Copy`).
Undecoded subrecords are copied verbatim; when the master order differs a heuristic remaps
FormID-looking values in them and the command prints a note.

### merge SOURCE... --into PATCH [--records R ...] [-t TYPE] [--esl]
Bashed/Smashed-patch style merge into PATCH (created if missing, masters = all sources and their
masters, ESMs first). Default targets: records of mergeable types (LVLI, LVLN, LVSP, CONT, NPC_,
FLST, OTFT, ARMO, WEAP, AMMO, ALCH, BOOK, MISC, INGR) overridden by 2+ sources. For each:
lists (LVLO, CNTO, SPLO, PRKR, PKID, NPC_ SNAM factions, FLST LNAM, OTFT INAM, KWDA, XCLR) get
every addition and removal relative to the base master version; other single subrecords take the
value from the last source that changed it (struct fields individually). Repeated non-list
subrecords (effects, conditions) come from the winner.

### delete PLUGIN RECORD... [--force] [--mark] [--disable]
- default: remove the records from the file (child groups of CELL/WRLD/DIAL go too). Refuses if
  other records in the same plugin reference them unless `--force`.
- `--mark`: keep the record, set the Deleted flag and strip its data (deletes a master record in game).
- `--disable`: for REFR/ACHR/... from masters: undelete, set Initially Disabled, enable parent =
  PlayerRef (opposite state), Z = -30000. This is the safe way to remove placed objects, and it also
  fixes deleted references (UDRs): a stripped deleted override first gets its fields back from the
  latest master version (as xEdit's undelete does).

### masters PLUGIN [--add NAME ...] [--clean] [--rename OLD=NEW]
Shows masters. `--add` appends (the plugin's own FormIDs move to the new index, references follow).
`--clean` drops masters nothing references. `--rename` only renames the entry (use when a master
file was renamed).

### itm PLUGIN [--clean] [--include-parents]
Reports overrides identical to the master version they override (flags + decoded data compared,
FormIDs as FormKeys). `--clean` removes them. CELL/WRLD/DIAL that carry child overrides are skipped
unless `--include-parents`.

### esl PLUGIN [--flag|--unflag] [--header-171] [--json]
Reports new-record count and object-ID range against the light-plugin limits
(0x800-0xFFF; 0x001-0xFFF with header 1.71 on 1.6.1130+), warns about new CELL/WRLD records.
`--flag` refuses if the plugin is not eligible. `--header-171` sets header version 1.71 first
(needed when new records use 001-7FF; game 1.6.1130+ or BEES). For a whole load order use `eslify`.

### compact PLUGIN [--start 0x800]
Renumbers the plugin's own records into the ESL range and fixes every reference inside the plugin.
Plugins that have this one as a master are NOT updated (tell the user).

### delocalize PLUGIN
Replaces string IDs by the text from its `Strings/<Name>_<lang>.*STRINGS` (loose or inside BSAs)
and clears the Localized flag.

### export PLUGIN [RECORD...] [-t TYPE] [-o FILE]
JSON list of records (same format as `show --json`), to a file or stdout.

---

## Whole load order

These commands share the load-order options:

| option | meaning |
|---|---|
| `PLUGIN...` | plugin files or names in load order (instead of a plugins.txt; all treated as active) |
| `--plugins-txt FILE` (alias `--plugins`) | the game's or a profile's plugins.txt (`*` = active); one inside an MO2 profile folder (`<MO2>/profiles/<name>/plugins.txt`) works like `--mo2` on that folder |
| `--mo2 PROFILE_DIR` (alias `--profile`) | MO2 profile folder: reads its plugins.txt/loadorder.txt/modlist.txt and ModOrganizer.ini (game path, mods folder); plugin files are found by mod priority |
| `--data DIR` | game Data folder (also locates `Skyrim.ccc` and `SkyrimSE.exe` next to it). A plugins.txt only names plugins: without `--data` or `--mo2` the files cannot be found (error) |
| `--loadorder-txt FILE` (alias `--loadorder`) | compared with plugins.txt (desync warning); used alone only if there is no plugins.txt |
| `--mods DIR` / `--ccc FILE` | override the MO2 mods folder / Skyrim.ccc location |
| `--masterlist FILE` / `--userlist FILE` / `--no-loot` | not for `check-order`. LOOT metadata: masterlist (`.yaml` needs PyYAML, or a `.json(.gz)` snapshot; default: the bundled or updated snapshot), userlist (default: LOOT's or Vortex's, found automatically), or none |
| `--no-cache` | not for `check-order`. Rescan every plugin (record-header scans are cached per file in `~/.cache/bethesda-esp/scan`) |

Without `--plugins-txt`/`--mo2`, plugins.txt is looked for in `%LOCALAPPDATA%` (Steam/GOG/Epic/MS
folder chosen from the game folder) and the Proton prefix.

### check-order [options] [--list] [--sources] [--all] [--json]
Fast check from plugin headers only (a few hundred bytes per plugin, well under a second for
1000+ plugins, nothing cached): missing/ghosted/inactive masters, plugins loading before their
masters, masters that need a regular plugin, master cycles, the 254/4096 limits, ESM/ESL flags
and header versions (LE header, 1.71 vs game version/BEES), generated-patch placement, missing or
duplicate entries. Exit code `1` when there are errors (`0` otherwise), so scripts can use it as a
gate. Not checked (needs whole files): ESL object-ID ranges, new CELLs in light plugins, LE record
formats, LOOT rules, sorting, conflicts - the output ends with the matching `esp loadorder`
command. `--list` prints the effective order (index, flags, master count); `--json` gives
`ok`, `counts`, `effective_order` (with each plugin's masters), `issues`, `full_check`.

### loadorder [options] [--rules FILE] [--write FILE] [--write-loadorder FILE] [--groups] [--sources] [--all] [--brief] [--full-order] [--no-overlap] [--no-groups] [--json]
Effective order with load indices (`00`, `FE:001`), flags, new/override counts, then problems and
suggested moves with reasons. Codes (level):

| code | level | meaning |
|---|---|---|
| `missing-master`, `inactive-master` | error | game crashes on start; a ghosted master counts as missing (Bash `Filter` patches also get a `filter-patch` note: deactivate them) |
| `master-cycle` | error | plugins list each other as masters |
| `master-order` | error | plugin loads before its master |
| `master-needs-nonmaster` | error | master-flagged plugin depends on a regular plugin (game hoists it; LOOT cannot sort) |
| `esl-range` | error | light plugin with new records outside its range (breaks saves) |
| `too-many-plugins`, `too-many-light` | error | above 254 (255 without lights) full / 4096 light plugins |
| `needs-bees` | error | header 1.71 plugins on a game older than 1.6.1130 without BEES |
| `vr-no-esl` | error | Skyrim VR with light plugins but without Skyrim VR ESL Support |
| `hedr-low-range` | warning | a pre-1.71 plugin overrides object IDs below 0x800 of a header-1.71 master |
| `loot-cannot-sort` | warning | LOOT req/after metadata makes a master load after a regular plugin (LOOT stops sorting) |
| `loot-metadata` | warning | the masterlist or userlist could not be read (the other one is still used) |
| `ghosted` | warning | active in plugins.txt but only `Name.esp.ghost` exists (the game does not load it) |
| `loot-requires`, `loot-incompatible`, `undefined-group` | error | LOOT masterlist/userlist rules |
| `loot-message`, `loot-global` | per message | LOOT masterlist messages whose conditions hold |
| `dirty` | warning | CRC matches a LOOT dirty entry (ITM/UDR/deleted navmesh counts) |
| `after-generated`, `generated-order`, `synthesis-split`, `stale-patch` | warning | generated patch placement / out of date |
| `le-header`, `le-records` | warning/info | Skyrim LE plugin not converted |
| `esl-new-cell`, `near-plugin-limit`, `not-found`, `duplicate-entry`, `bad-filename`, `lo-desync` | warning | |
| `master-partition`, `unlisted`, `hedr-171`, `no-ccc` | info (shown with `--all`) | |

`--rules` JSON: `{"Plugin.esp": {"after": ["Other.esp"], "before": ["X.esp"]}}` (hard rules, like
LOOT userlist `after`). `--write` writes the suggested order as a Windows-1252 plugins.txt
(hardcoded/CC plugins left out, inactive and missing entries kept next to their neighbours);
`--write-loadorder` also writes it as a loadorder.txt (every plugin, UTF-8). MO2 takes its order
from the profile's loadorder.txt, so write both for an MO2 profile (with MO2 closed). For MO2
profiles the shown order is read from loadorder.txt (with plugins.txt's active flags), as MO2
does. Installed plugins missing from plugins.txt are treated as inactive. `--no-groups` drops only
LOOT groups; LOOT load-after/requirement rules still apply.
`--groups` shows LOOT groups, `--sources` the MO2 mod each plugin comes from.

### scan [options] [--deep] [--max-deep N] [--only PLUGIN] [-t TYPE] [--details] [--limit N] [--limit-records N] [--json]
Conflict scan of the whole load order plus all `loadorder` checks, ending in a prioritized list
of recommendations (critical/high/medium/low) with concrete commands and tools. Quick mode reads
record headers only (seconds, cached); `--deep` compares conflicting records field by field
(statuses identical/resolved/lists/forwardable/clash; reverted official fixes per field).
`--details` lists each conflicting record (and with `--deep`, what each loser loses).
JSON keys: `conflicts`, `records`, `dirty`, `navmesh_cells`, `editor_id_duplicates`,
`injected_collisions`, `reverted_fixes`, `overridden_patches`, `recommendations`.

### eslify [options] [--configs] [--deep-configs] [--limit N] [--json]
Light-plugin candidates: `flag` (as is), `flag-171` (needs header 1.71), `compact` /
`compact-care` (needs FormID renumbering; risks listed: FaceGen, voice, SEQ, scripts, configs,
dependents), `no` (worldspaces, cells without Engine Fixes 7.0.14+, too many records, master
needing a regular plugin, SKSE DLL references, generated patches), `already` (flags invalid
light plugins). `--configs` searches SKSE/INI/JSON configs that mention each plugin
(`--deep-configs`: whole mod folders). Ends with a safe step-by-step procedure.

### loot-update [SOURCE]
Downloads LOOT's Skyrim SE masterlist (branch v0.29) or reads a local `masterlist.yaml`, and
stores a compact copy in the cache; `loadorder`/`scan` use it instead of the bundled one. Needs
PyYAML (`pip install pyyaml`).

---

## Exit codes
`0` ok; `1` no command given, or `check-order` found errors; `2` error or bad arguments (message on
stderr, starting with `error:` for errors). `delete` exits 2 when it refuses because of references.
