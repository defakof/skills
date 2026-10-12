# Skills

Agent skills for **Claude Code** and **Google Antigravity**.

| Skill | What it does |
|---|---|
| [`bethesda-esp`](skills/bethesda-esp/SKILL.md) | Read, edit and patch Skyrim Special Edition plugin files (`.esp` / `.esm` / `.esl`), check and sort load orders, scan them for conflicts and plan the fixes: an xEdit + LOOT style toolkit your agent can drive |

---

## bethesda-esp

Lets the agent open Skyrim SE / AE plugins, explain what a mod changes, and edit or patch it
safely. Ask things like:

- *"What does `Immersive Armors.esp` change? List the armor it adds with their ratings."*
- *"ModA and ModB both edit the same leveled lists and NPCs. Make me a compatibility patch."*
- *"In my mod, raise the damage of every dagger by 2 and add the `WeapTypeDagger` keyword where it's missing."*
- *"Which plugins override `IronSword`, and who wins?"*
- *"Make `MyPatch.esp` an ESL. Is it eligible?"*
- *"Clean the ITMs from this plugin."* / *"Remove this placed rock without breaking the game."*
- *"Add a recipe at the forge that turns 2 iron ingots into a steel dagger."*
- *"Check my MO2 profile's load order and fix what's wrong."* / *"Why does LOOT put this plugin there?"*
- *"Scan my load order for conflicts. What needs a patch, a Bashed Patch, Synthesis or EasyNPC?"*
- *"I'm at 250 plugins. Which ones can I ESL-flag safely?"*

### What's included

- `scripts/esp.py`: a zero-dependency Python 3.8+ CLI (works on Windows, macOS, Linux) with
  `info`, `list`, `show`, `find` (by name, EditorID, any text, or "what references X"), `set`
  (path-based field edits), `put`/`export` (JSON round trip), `add`, `copy` (as override or new
  record, with automatic master handling and FormID remapping), `delete` (remove / mark deleted /
  xEdit-style disable for references), `merge` (Bashed-patch-style 3-way merge of leveled lists,
  inventories, keywords and changed fields), `conflicts`, `diff`, `itm`, `masters`, `esl`,
  `compact`, `delocalize`, `verify`, `schema`, `tree`, `strings`, `bsa`.
- Whole-load-order analysis (plugins, not archives): `check-order` (instant check from plugin
  headers only: missing or inactive masters, plugins loading before their masters, 254/4096
  limits; exit code 1 on errors), `loadorder` (reads plugins.txt or an MO2
  profile; applies the game's rules - hardcoded and Creation Club plugins, masters first,
  hoisting, 254/4096 slots, header 1.71 vs game version - and LOOT's masterlist and userlist
  rules, groups, dirty-plugin CRCs and warnings; suggests the smallest set of moves and explains
  each), `scan` (every record several mods override, field-level with `--deep`; patches that
  lose, reverted official/USSEP fixes, navmesh overlaps, deleted references and navmeshes;
  prioritized fixes naming the right tool: compatibility patch, `esp merge`, Bashed Patch,
  Synthesis (Fusion Patcher), NPC Plugin Chooser 2 / EasyNPC, Creation Kit, Mator Smash as a
  last resort) and `eslify` (flag-only vs compaction candidates and what compaction would break).
  Header scans are cached, so a 1,000-plugin load order rescans in seconds.
- `scripts/esplib/`: the library behind it, usable from Python for bulk edits; header-only
  loading (`Plugin.load_header`) for fast audits and FormKeys to match records across plugins.
- Field layouts for 115 Skyrim SE record types (weapons, armor, NPCs, leveled lists, recipes,
  containers, spells, effects, perks, cells, references, worldspaces, dialogue, quests...), Papyrus
  script properties (VMAD), and conditions (CTDA) with all ~400 condition functions.
- Localized strings from loose `Strings/` files **or straight out of BSAs** (Skyrim SE LZ4 and LE
  zlib archives, read with a pure-Python LZ4 decoder).
- Docs the agent reads on demand: command reference, record field guide, file format primer,
  Python API, a load-order and conflict-resolution guide (which tool for which conflict, tool
  status as of 2026), and an optional [Spriggit](https://github.com/Mutagen-Modding/Spriggit)
  workflow for full-schema YAML editing of the record types kept as raw bytes.

### Safety

- Unmodified records are written back **byte for byte** (including compressed ones), so a
  load/save cycle reproduces the original file exactly. Only records you change are re-encoded.
- Every decoded value is re-encoded and compared with the original bytes. If they don't match,
  the subrecord stays raw hex, so a gap in the schema can never silently corrupt data.
- In-place writes keep a `.bak`. The skill tells the agent to work in separate patch plugins and
  never touch the official masters.

### How it was tested

- Byte-identical round trips on real plugins made by xEdit and the Creation Kit
  ([LOOT's testing-plugins](https://github.com/Ortham/testing-plugins), Skyrim LE and SE).
- An independent implementation as oracle: [Mutagen](https://github.com/Mutagen-Modding/Mutagen)
  generated randomized ("fuzzed") plugins for 106 record types. Every FormID Mutagen sees has to
  be found by this decoder. The only gaps are in data documented as kept raw (navmesh info,
  body part data, effect shader data, scenes, region data).
- End-to-end scenarios written by Mutagen (a master, two conflicting mods with different master
  orders, interior and exterior cells, dialogue, scripts, a localized master with strings files
  and a BSA). The results of `copy`, `merge`, `set`, `add`, `delete --disable`, `compact`,
  `delocalize` and master changes were read back with Mutagen to confirm every value and FormID.
- Spriggit serialize → edit → deserialize of plugins produced by the tool.
- Performance: a 48 MB / 400k-record plugin loads, lists or shows a record in 2-3 s.
- `tests/` holds a stdlib-only test suite (`python -m unittest discover tests`) run in CI on
  Linux, Windows and macOS with Python 3.8 and 3.13.

### Install

**Requirement:** Python 3.8 or newer on the PATH (`python3 --version`; on Windows
`winget install Python.Python.3.12` or python.org).

**Claude Code: plugin marketplace (recommended)**

```
/plugin marketplace add defakof/skills
/plugin install bethesda-esp@defakof-skills
```
(or from a shell: `claude plugin marketplace add defakof/skills` then
`claude plugin install bethesda-esp@defakof-skills`)

**Claude Code: copy the skill**

```bash
git clone https://github.com/defakof/skills && cd skills
python install.py                          # personal: ~/.claude/skills/bethesda-esp
python install.py claude --project /path/to/project   # that project's .claude/skills/
```

**Google Antigravity**

```bash
python install.py antigravity              # global: ~/.gemini/config/skills/bethesda-esp
python install.py antigravity --project /path/to/workspace   # <workspace>/.agents/skills/
python install.py antigravity-cli          # Antigravity CLI: ~/.gemini/antigravity-cli/skills/
```
Older Antigravity builds read `~/.gemini/antigravity/skills/` and `<workspace>/.agent/skills/`;
copying `skills/bethesda-esp` there works too.

**Any other agent** that supports `SKILL.md` skills: copy `skills/bethesda-esp` into its skills
folder. The CLI also works by hand: `python skills/bethesda-esp/scripts/esp.py --help`.

Tip: point the agent at your game's `Data` folder (e.g. *"my Skyrim is in
`D:\SteamLibrary\steamapps\common\Skyrim Special Edition`"*) so it can find masters, strings and
BSAs. With Mod Organizer 2, mention the mod's folder under `mods\` and your profile's `plugins.txt`.

### Quick CLI tour

```bash
esp=skills/bethesda-esp/scripts/esp.py
python $esp info MyMod.esp --data "D:/Skyrim Special Edition/Data"
python $esp list MyMod.esp -t WEAP,ARMO
python $esp show MyMod.esp IronSword
python $esp set MyMod.esp IronSword DATA.damage=12 KWDA+=WeapMaterialSteel
python $esp conflicts ModA.esp ModB.esp --details
python $esp merge ModA.esp ModB.esp --into "ModA - ModB Patch.esp"
python $esp esl MyPatch.esp --flag
python $esp check-order --mo2 "D:/MO2/profiles/Default"
python $esp loadorder --mo2 "D:/MO2/profiles/Default" --groups
python $esp scan --plugins-txt "%LOCALAPPDATA%/Skyrim Special Edition/Plugins.txt" --data "D:/Skyrim Special Edition/Data" --deep
python $esp eslify --mo2 "D:/MO2/profiles/Default" --configs
```

### Limits

- Skyrim SE/AE (and LE) only. Oblivion/Morrowind use a different format; Fallout 4 and
  Starfield share the container format but have different record layouts (not described).
- Navmeshes, terrain (LAND), and some fields of RACE, QUST aliases, PACK, SCEN, PERK entry points
  and weather colors are preserved but shown as raw bytes. Use the Spriggit workflow for those.
- It edits plugins, not assets: no FaceGen generation, script compilation, mesh or texture editing.
- Load order: the sort follows LOOT's rules and metadata but is not a byte-for-byte LOOT clone
  (no BSA-content overlap rule, inactive plugins are not sorted). It writes a suggested
  plugins.txt only when asked (`--write`); applying it through LOOT/MO2/Vortex is recommended.
- Loose-file and BSA asset conflicts (mod manager priority) are not analysed.

### Credits

- File format knowledge: the [UESP](https://en.uesp.net/wiki/Skyrim_Mod:Mod_File_Format) mod
  file format pages and the [xEdit](https://github.com/TES5Edit/TES5Edit) project, whose
  ITM / UDR cleaning conventions this tool follows.
- [Mutagen and Spriggit](https://github.com/Mutagen-Modding) by Noggog: used as the reference
  implementation to validate this tool, and recommended for full-schema edits. Condition-function
  and actor-value index tables were cross-checked against Mutagen's.
- [testing-plugins](https://github.com/Ortham/testing-plugins) by Oliver Hamlet (LOOT): test plugins.
- [LOOT](https://loot.github.io/) and its [Skyrim SE masterlist](https://github.com/loot/skyrimse)
  (CC0 1.0): a compact copy ships in `esplib/data/loot_skyrimse.json.gz`; the sorting rules follow
  libloot's documented behaviour and [libloadorder](https://github.com/Ortham/libloadorder)'s
  description of how the game reads plugins.txt.

### Development

```bash
python -m unittest discover tests -v       # stdlib only
```
`tests/fixtures/` were generated with Mutagen (see `tests/README.md`); the load-order scenario is
built at test time by `tests/tools/make_lo_fixture.py`. Refresh the bundled LOOT data with
`esp loot-update` (writes to the cache) or by converting a new masterlist with
`esplib.masterlist.compact_metadata`. Layouts live in
`skills/bethesda-esp/scripts/esplib/schema_sse.py`. Add a record type with `R('SIG', 'Name', {...})`;
`esp verify --roundtrip` and the decode self-check flag any mistake.

License: MIT.
