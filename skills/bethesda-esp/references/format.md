# How Skyrim plugins work (what you need to edit them safely)

## Files and load order

- `.esm` (master), `.esp` (plugin), `.esl` (light master). The ESM/ESL *flags* in the header
  (`esp info`) are what matter to the game; the extension `.esl` implies both.
- Load order: base game masters (Skyrim.esm, Update.esm, Dawnguard.esm, HearthFires.esm,
  Dragonborn.esm, Creation Club `cc*.esl/esm`), then mods. ESM-flagged files load before plain ESPs.
  For the *same* record, the plugin loaded last wins ("rule of one") - so a patch must load after
  everything it patches.
- Full plugins (ESM/ESP) take one of 254 load-order slots (`00`-`FD`). Light plugins (ESL flag) share
  slot `FE` (4096 of them), each limited to 4096 new records.
- Load order files: `%LOCALAPPDATA%\Skyrim Special Edition\plugins.txt` (vanilla/Vortex,
  `*` = enabled), MO2: `profiles/<name>/plugins.txt` and `loadorder.txt`.

## FormIDs and masters

Every record has a 32-bit FormID. **Inside a file** the top byte is an index into that file's
master list (`MAST` subrecords in the header); index == number of masters means "this file".

```
ModA.esp masters: [Skyrim.esm, Update.esm]
  0x00012EB7  -> Skyrim.esm   object 012EB7  (an override of Iron Sword)
  0x02000801  -> ModA.esp     object 000801  (new record)
```

The same record therefore has *different* raw FormIDs in different files. That is why this tool
prints **FormKeys** (`012EB7:Skyrim.esm`) and remaps every FormID when copying between plugins or
changing masters. The in-game console shows load-order FormIDs instead (`0A000801` = slot 0A;
light plugins `FExxx801`, where `xxx` is the light slot).

- **Override**: a record whose FormID belongs to a master - the plugin replaces that record
  entirely (all fields, not just the changed ones). Two mods overriding the same record conflict;
  only the last one's version is used unless a patch merges them.
- **New record**: FormID belongs to the plugin itself. Object IDs start at 0x800 (0x000-0x7FF are
  reserved for engine forms; header version 1.71 / game 1.6.1130+ allows 0x001+ for light plugins).
- **ITM** (identical to master): an override that changes nothing - harmless but it can undo other
  mods' changes. **UDR** (undeleted & disabled reference): the safe replacement for deleting
  placed references.

## File structure

```
TES4 header record        HEDR {version, num_records, next_object_id}, CNAM author,
                          SNAM description, MAST/DATA pairs (masters), ONAM, INTV
GRUP "GMST"               top group per record type (fixed order)
  GMST record ...
GRUP "CELL"
  GRUP interior block N   N = last decimal digit of the cell's object id
    GRUP sub-block M      M = second-to-last digit
      CELL record
      GRUP cell children (label = CELL FormID)
        GRUP persistent children   REFR/ACHR flagged persistent
        GRUP temporary children    other REFR/ACHR, NAVM, LAND
GRUP "WRLD"
  WRLD record
  GRUP world children
    CELL (persistent worldspace cell) + its children
    GRUP exterior block (x/32, y/32) > GRUP sub-block (x/8, y/8) > CELL + children
GRUP "DIAL"
  DIAL record
  GRUP topic children: INFO records
```

`esp tree` shows it. `copy`, `put` and `delete` maintain these groups for you (parent cells,
worldspaces and topics are copied along with their children).

## Records and subrecords

A record = 24-byte header (type, data size, flags, FormID, version-control info, form version
44 for SE / 43 for LE) + data. Data is a sequence of subrecords: 4-char type + 16-bit size + bytes
(an `XXXX` subrecord carries sizes over 65535). Records with the Compressed flag hold zlib data;
this tool decompresses on read and recompresses only records you change.

The meaning of a subrecord depends on the record type (WEAP `DNAM` is weapon data, NPC_ `DNAM` is
skills), and in complex records also on position (QUST, PACK, RACE, PERK). `esp schema TYPE` lists
what is decoded; anything else is shown and kept as hex.

Counters precede lists: `KSIZ` (keyword count) + `KWDA` (keywords), `COCT` + `CNTO` (items),
`LLCT` + `LVLO` (leveled entries), `SPCT` + `SPLO`, `PRKZ` + `PRKR`. `esp set` keeps them in sync.

## Strings and localization

Plugins with the **Localized** header flag (all official masters, many CC files) store 32-bit
string IDs instead of text in `FULL`, `DESC`, `NAM1`, ... The text lives in
`Strings/<Plugin>_<language>.STRINGS` (names), `.DLSTRINGS` (descriptions, book text) and
`.ILSTRINGS` (dialogue), usually packed in `Skyrim - Interface.bsa` (official) or the mod's BSA.
This tool finds them loose or inside BSAs (`--data`, `--lang`).

- Copying from a localized master into a normal patch converts IDs to text (needs the strings).
- To write text into a localized plugin, `esp delocalize` it first (or keep edits in a separate,
  non-localized patch - the usual choice).
- Non-localized text is stored in the system code page (cp1252 for English; use `--encoding`
  for other languages).

## ESL (light) plugins

- Eligible when all *new* records have object IDs 0x800-0xFFF (max 2048; 4096 with header 1.71 and
  game 1.6.1130+ or the BEES SKSE plugin). Overrides don't count.
- `esp esl` checks, `esp compact` renumbers, `esp esl --flag` sets the flag.
- Renumbering changes FormIDs: plugins depending on the file, saved games that reference its
  records, and FaceGen files named after NPC FormIDs
  (`meshes/actors/character/facegendata/facegeom/<Plugin>/<FormID>.nif`) must be updated too.
- New CELL / WRLD records in light plugins have known issues on older runtimes; keep those in a full plugin.

## Things to tell the user

- A patch only works if it loads after the plugins it patches (and the masters it lists exist).
- Changing a master's records can break plugins that depend on it; work on a patch instead.
- Removing a master from the header is only safe when nothing references it (`esp masters --clean`
  checks); renaming a plugin breaks every plugin that uses it as a master.
- Editing scripts (Papyrus `.psc/.pex`), meshes (`.nif`) or textures is outside plugin editing; the
  plugin only holds script *attachments and property values* (`VMAD`), which this tool can edit.
