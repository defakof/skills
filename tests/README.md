# Tests

```bash
python -m unittest discover tests -v
```

Stdlib only; each test copies `fixtures/` into a temp folder.

## Fixtures

All plugins were written by [Mutagen](https://github.com/Mutagen-Modding/Mutagen) 0.54 (an
independent C# implementation of the format), so the tests check this tool against another
implementation instead of against itself.

| file | contents |
|---|---|
| `TestMaster.esm` | keywords, globals, game settings (float/int/string), misc items, a weapon with a Papyrus script (object/int/float/bool/string/object-array properties), armor + armor addon, leveled list, container, recipe, race, class, faction, outfit, NPC, spell + magic effect with a condition, form list, static, an interior cell (object id 0x8A7 -> block 5 / sub-block 1) with persistent and temporary references and an NPC reference, a worldspace with a persistent cell and an exterior cell at (3, -2), a quest and a dialogue topic with a response |
| `OtherMaster.esm` | one keyword (shifts master indices for ModB) |
| `ModA.esp` | masters `[TestMaster]`: overrides the weapon (damage, extra keyword), leveled list (adds an entry), container (adds an item), the chest reference (moved), an identical copy of Gold001 (ITM), new weapon + global |
| `ModB.esp` | masters `[OtherMaster, TestMaster]`: overrides the weapon (value, keyword swapped), leveled list (removes and adds entries), the NPC (level); new weapon |
| `loc/LocMaster.esm` + `loc/Strings/` | localized master (STRINGS / DLSTRINGS / ILSTRINGS) with weapon, book, quest, topic + response, string game setting |
| `bsa/LocMaster.esm` + `bsa/Skyrim - Interface.bsa` | same master, strings only inside an SE (v105, LZ4) BSA built by `tools/make_test_bsa.py` and checked with Mutagen's archive reader |

`tools/make_test_bsa.py` needs `pip install lz4` (only to rebuild the BSA fixture).
