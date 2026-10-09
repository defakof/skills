# Scripting with esplib (bulk edits)

For changes across many records, write a short Python script instead of calling `esp set`
hundreds of times. `esplib` is the package next to `esp.py` (stdlib only).

```python
import sys
sys.path.insert(0, r"<skill folder>/scripts")       # Claude Code: ${CLAUDE_SKILL_DIR}/scripts
from esplib import Plugin, LoadOrder, decode_record, ops, EspError
```

## Core objects

| object | what |
|---|---|
| `LoadOrder(data_dir=None, encoding=None, language='english')` | finds masters/strings; `lo.add(path)` loads a plugin; `lo.get(name)` loads a master by name |
| `Plugin` | `.name`, `.path`, `.masters`, `.is_esm/.is_esl/.is_localized`, `.records(types=None)`, `.find(fid)`, `.find_edid(edid)`, `.is_override(rec)`, `.save(path=None, backup=True)` |
| `Record` | `.sig` ('WEAP'), `.formid` (file-local int), `.flags`, `.edid`, `.subrecords` (list of `Subrecord(sig, data)`), `.get(sig)`, `.parent` (Group) |
| `decode_record(rec, plugin)` | list of `DecodedSub(sig, value, raw, ok)`; `value` is int/float/str/dict/list, FormIDs are `FormID` ints, raw ones are `{'$hex': ...}` |
| `ops.apply_edits(lo, plugin, rec, [(path, op, text)], removes=[])` | the `esp set` engine (op: `'='`, `'+='`, `'-='`; text parsed like on the command line) |
| `ops.copy_record(lo, src, rec, dst, as_new=False, new_edid=None)` | the `esp copy` engine; returns `(new_record, warnings)` |
| `ops.new_record(plugin, sig, edid, [(sig, value)], lo=lo)` | create a record |
| `ops.add_masters(plugin, names, lo)`, `ops.clean_masters(plugin)` | masters with FormID remapping |
| `ops.merge_versions(lo, (base_plugin, base_rec), [(plugin, rec), ...])` | the `esp merge` engine |
| `lo.resolve(text, plugin)` | EditorID / FormKey / `0x...` -> file-local FormID in `plugin` |
| `lo.describe(plugin, fid)` | `'IronSword [WEAP:012EB7:Skyrim.esm]'` |
| `format_formid(fid, plugin)` | `'012EB7:Skyrim.esm'` |

Changing `Subrecord.data` directly is allowed; call `rec.touched()` afterwards. Prefer
`ops.apply_edits`, which validates values and keeps counters in sync.

## Examples

Raise the damage of every weapon in a mod by 20% (in a separate patch):

```python
lo = LoadOrder(data_dir=r"D:\Steam\steamapps\common\Skyrim Special Edition\Data")
mod = lo.add(r"D:\...\Data\CoolWeapons.esp")
patch = Plugin.new("CoolWeapons - Rebalance.esp", mod.masters + [mod.name])
patch.path = r"D:\...\Data\CoolWeapons - Rebalance.esp"
lo.add(patch)
for rec in list(mod.records("WEAP")):
    data = next(d for d in decode_record(rec, mod) if d.sig == "DATA")
    new, _ = ops.copy_record(lo, mod, rec, patch)
    ops.apply_edits(lo, patch, new, [("DATA.damage", "=", str(round(data.value["damage"] * 1.2)))])
patch.save()
```

Add a keyword to all heavy armor (records from Skyrim.esm, so first copy them into the patch):

```python
sky = lo.get("Skyrim.esm")
patch = Plugin.new("MyPatch.esp", ["Skyrim.esm"])
patch.path = r"D:\...\Data\MyPatch.esp"
lo.add(patch)
for rec in sky.records("ARMO"):
    bod = next((d.value for d in decode_record(rec, sky) if d.sig == "BOD2" and d.ok), None)
    if bod and bod["armor_type"] == "HeavyArmor":
        new, _ = ops.copy_record(lo, sky, rec, patch)
        ops.apply_edits(lo, patch, new, [("KWDA", "+=", "MyHeavyKeyword")])
patch.save()
```

List every leveled list entry that points at a given item across a load order:

```python
target = lo.resolve("IronSword", sky)               # FormID in Skyrim.esm's numbering
key = lo.formkey(sky, target)                        # (objid, 'Skyrim.esm')
for p in [lo.add(x) for x in plugin_paths]:
    local = lo.local_fid(p, *key)
    for rec in p.records(["LVLI"]):
        for d in decode_record(rec, p):
            if d.sig == "LVLO" and d.ok and int(d.value["reference"]) == local:
                print(p.name, rec.edid, d.value)
```

Rules of thumb:
- Never call `save()` on official masters; build a new plugin with `Plugin.new(name, masters)`.
- `records()` iterates lazily; wrap in `list(...)` if you add/remove records while iterating.
- `decode_record` re-encodes each value to check it; on huge masters prefer filtering by
  `rec.sig` / `rec.edid` first.
- Big loops over Skyrim.esm take seconds to minutes in pure Python - print progress.
