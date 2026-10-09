# esp.py command reference

`esp` = `python3 <skill>/scripts/esp.py`. Every command accepts:

| option | meaning |
|---|---|
| `--data DIR` | game `Data` folder: where masters, `Strings/` and BSAs are looked up (the plugin's own folder is always searched) |
| `--encoding ENC` | code page of non-localized text (default `cp1252`; e.g. `cp1251` for Russian, `utf-8`). Env: `ESP_ENCODING` |
| `--lang NAME` | strings language for localized plugins (default `english` -> `Skyrim_english.STRINGS`) |

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
  PlayerRef (opposite state), Z = -30000. This is the safe way to remove placed objects.

### masters PLUGIN [--add NAME ...] [--clean] [--rename OLD=NEW]
Shows masters. `--add` appends (the plugin's own FormIDs move to the new index, references follow).
`--clean` drops masters nothing references. `--rename` only renames the entry (use when a master
file was renamed).

### itm PLUGIN [--clean] [--include-parents]
Reports overrides identical to the master version they override (flags + decoded data compared,
FormIDs as FormKeys). `--clean` removes them. CELL/WRLD/DIAL that carry child overrides are skipped
unless `--include-parents`.

### esl PLUGIN [--flag|--unflag] [--json]
Reports new-record count and object-ID range against the light-plugin limits
(0x800-0xFFF; 0x001-0xFFF with header 1.71 on 1.6.1130+), warns about new CELL/WRLD records.
`--flag` refuses if the plugin is not eligible.

### compact PLUGIN [--start 0x800]
Renumbers the plugin's own records into the ESL range and fixes every reference inside the plugin.
Plugins that have this one as a master are NOT updated (tell the user).

### delocalize PLUGIN
Replaces string IDs by the text from its `Strings/<Name>_<lang>.*STRINGS` (loose or inside BSAs)
and clears the Localized flag.

### export PLUGIN [RECORD...] [-t TYPE] [-o FILE]
JSON list of records (same format as `show --json`), to a file or stdout.

---

## Exit codes
`0` ok, `1` usage, `2` error (message on stderr starting with `error:`). `delete` exits 2 when it
refuses because of references.
