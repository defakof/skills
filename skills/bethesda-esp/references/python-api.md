# Scripting with esplib (bulk edits)

For changes across many records, write a short Python script instead of calling `esp set`
hundreds of times. `esplib` is the package next to `esp.py` (stdlib only).

```python
import sys
sys.path.insert(0, r"<skill folder>/scripts")       # Claude Code: ${CLAUDE_SKILL_DIR}/scripts
from esplib import Plugin, LoadOrder, FormKey, decode_record, ops, EspError
```

## Core objects

| object | what |
|---|---|
| `Plugin.load(path)` | read a whole plugin (records are parsed lazily; a 250 MB master takes seconds) |
| `Plugin.load_header(path)` | read only the header: `.masters`, flags, `.hedr_version`, `.next_object_id`, `.header_string('CNAM')` (author) / `'SNAM'` (description). A few hundred bytes per file, so 1000 plugins take milliseconds. `.records()`, `.find()` and `.save()` raise `EspError` on it |
| `Plugin.new(name, masters=(), esm=False, esl=False)` | a new empty plugin (set `.path` before `save()`). `Plugin(name)` itself reads nothing: given a path it raises `ValueError`, and its header properties raise `EspError` |
| `LoadOrder(data_dir=None, encoding=None, language='english')` | finds masters/strings; `lo.add(path)` loads a plugin; `lo.get(name)` loads a master by name |
| `Plugin` | `.name`, `.path`, `.masters`, `.is_esm/.is_esl` (flags), `.is_light` (ESL flag or .esl), `.is_master_like` (ESM flag or .esm/.esl), `.is_localized`, `.header_only`, `.records(types=None)`, `.find(fid or FormKey)`, `.find_edid(edid)`, `.is_override(rec)`, `.formkey(fid)`, `.local_formid(key)`, `.save(path=None, backup=True)` |
| `Record` | `.sig` ('WEAP'), `.formid` (file-local int), `.object_id` / `.local_id` (`formid & 0xFFFFFF`), `.formkey`, `.master_name()` (plugin that defines it), `.is_override`, `.flags`, `.edid`, `.subrecords` (list of `Subrecord(sig, data)`), `.get(sig)`, `.parent` (Group) |
| `FormKey(object_id, plugin)` | record identity independent of master lists: `str()` -> `'012EB7:Skyrim.esm'`, `FormKey.parse(text)` (6-digit object ID, no load-order byte); equal (and same hash) for the same record in any plugin, plugin names compared case-insensitively. Equal only to other FormKeys: wrap a plain pair with `FormKey(*pair)` before comparing or using it as a key. Unpacks as `(object_id, plugin)` |
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
`ops.apply_edits`, which validates values and keeps counters in sync. After editing `MAST`
subrecords by hand, also call `plugin.invalidate()`.

## FormIDs across plugins

A FormID in a plugin file is **file-local**: its top byte indexes *that plugin's* master list, so the
same record is `0x01012EB7` in one patch and `0x05012EB7` in another. Never compare `rec.formid`
values from different plugins; compare `rec.formkey` (or `plugin.formkey(fid)` for a FormID stored
in a field), and turn a FormKey back into a plugin's own numbering with `plugin.local_formid(fk)` or
look the record up directly with `plugin.find(fk)`.

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

Audit masters and light plugins across a whole load order (headers only, no record parsing):

```python
import glob, os
heads = {os.path.basename(p).lower(): Plugin.load_header(p)
         for p in glob.glob(r"D:\...\Data\*.es[pml]")}
for name, h in heads.items():
    missing = [m for m in h.masters if m.lower() not in heads]
    if missing:
        print(name, "is missing", missing)
print(sum(h.is_light for h in heads.values()), "light,",
      sum(not h.is_light for h in heads.values()), "full plugins")
```

(For a real load order - plugins.txt order, active flags, MO2 mod folders, master order, limits -
use `esp check-order` or, from Python, `from esplib import lorder` and
`lorder.LoadOrderModel.from_sources(mo2_profile=..., header_only=True, use_metadata=False).validate()`.)

Which placed references do two mods both change?

```python
a, b = Plugin.load(r"...\Lux.esp"), Plugin.load(r"...\Shadows Patch.esp")
types = ["REFR", "ACHR"]
shared = {r.formkey for r in a.records(types)} & {r.formkey for r in b.records(types)}
for fk in sorted(shared):
    ra, rb = a.find(fk), b.find(fk)
    print(fk, ra.edid or "", "differs" if ra.data() != rb.data() else "identical bytes")
```

(`ra.data() != rb.data()` compares raw bytes, and FormIDs inside differ when the master lists do;
`esp conflicts A.esp B.esp --details` compares decoded fields.)

Rules of thumb:
- Never call `save()` on official masters; build a new plugin with `Plugin.new(name, masters)`.
- `records()` iterates lazily; wrap in `list(...)` if you add/remove records while iterating.
- `decode_record` re-encodes each value to check it; on huge masters prefer filtering by
  `rec.sig` / `rec.edid` first.
- Big loops over Skyrim.esm take seconds to minutes in pure Python - print progress.
