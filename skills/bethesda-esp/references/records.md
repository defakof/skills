# Common Skyrim SE records and fields

Field names below are what `esp show` prints and what `esp set` paths use. `esp schema TYPE`
prints the full layout of any type (115 types are decoded; the rest show as raw hex).

Notation: `SIG` subrecord; `SIG.field` struct field; *(list)* repeated subrecord or array;
`fid` = FormID (give an EditorID or FormKey when editing).

## Items

| Type | Key fields |
|---|---|
| **WEAP** weapon | `FULL` name, `DATA {value, weight, damage}`, `DNAM {animation_type, speed, reach, flags, sight_fov, range_min, range_max, flags2, skill, resist, stagger, num_projectiles}`, `CRDT {damage, percent_mult, flags, effect}` critical, `EITM` enchantment + `EAMT` charge, `KWDA` keywords, `ETYP` equip slot, `CNAM` template, `MODL` model, `INAM` impact set, `NAM9`/`NAM8` equip/unequip sounds, `VMAD` scripts |
| **ARMO** armor | `FULL`, `DATA {value, weight}`, `DNAM.armor_rating_x100` (25 armor = 2500), `BOD2 {slots, armor_type}`, `MODL` *(list)* armor addons (ARMA), `KWDA`, `EITM`/`EAMT`, `RNAM` race, `TNAM` template, `MOD2`/`MOD4` male/female ground models |
| **ARMA** armor addon | `BOD2`, `RNAM` race, `MODL` *(list)* extra races, `DNAM {male_priority, female_priority, male_weight_slider, female_weight_slider, weapon_adjust}`, `MOD2`/`MOD3` male/female world model, `MOD4`/`MOD5` 1st person, `NAM0`-`NAM3` skin/swap lists |
| **AMMO** | `DATA {projectile, flags, damage, value, weight}`, `KWDA`, `ONAM` short name |
| **MISC / KEYM / SLGM** | `FULL`, `DATA {value, weight}`, `KWDA`; SLGM `SOUL.contained_soul`, `SLCP.capacity` |
| **ALCH** potion/food | `DATA` weight, `ENIT {value, flags (NoAutoCalc, FoodItem, Medicine, Poison), addiction, addiction_chance, consume_sound}`, effects (below) |
| **INGR** ingredient | `DATA {value, weight}`, `ENIT {ingredient_value, flags}`, effects |
| **BOOK** | `FULL`, `DESC` book text, `DATA {flags, type, teaches, value, weight}` (`teaches` = skill name with flag TeachesSkill, or a spell with TeachesSpell), `INAM` inventory art, `CNAM` description |
| **SCRL** scroll | `DATA {value, weight}`, `SPIT` (like SPEL), effects |
| **LIGH** | `DATA {time, radius, color{r,g,b,a}, flags, falloff_exponent, fov, near_clip, ..., value, weight}`, `FNAM` fade |

Effects (ALCH, INGR, SPEL, SCRL, ENCH): repeated groups of `EFID` magic effect, `EFIT {magnitude, area, duration}` and optional `CTDA` conditions. Add an effect at the end with
`EFID+=SomeEffect 'EFIT+={"magnitude":10,"area":0,"duration":30}'` (a following `CTDA+=` attaches to that new effect). Change one with `EFIT#1.magnitude=25` (0-based). To reorder or remove whole effects edit `show --json` output and `put` it back.

## Lists and crafting

| Type | Key fields |
|---|---|
| **LVLI / LVLN / LVSP** leveled lists | `LVLD` chance none (0-100), `LVLF.flags` (CalcFromAllLevels, CalcForEachItem, UseAll, SpecialLoot), `LVLG` chance-none global, `LVLO {level, reference, count}` *(list)*, `LLCT` auto, `COED` per-entry owner/condition |
| **COBJ** recipe | `CNTO {item, count}` *(list)* ingredients, `CTDA` conditions, `CNAM` created object, `BNAM` workbench keyword (CraftingSmithingForge, CraftingSmithingArmorTable, CraftingSmithingSharpeningWheel, CraftingCookpot...), `NAM1` count created |
| **CONT** container | `CNTO {item, count}` *(list)*, `DATA {flags (Respawns...), weight}`, `SNAM`/`QNAM` open/close sound |
| **FLST** form list | `LNAM` *(list)* one FormID each |
| **OTFT** outfit | `INAM` list of armor/leveled items |

## Actors

**NPC_**
- `ACBS {flags, level, calc_min_level, calc_max_level, speed_mult, disposition_base, template_flags, health_offset, magicka_offset, stamina_offset, bleedout_override}`
  - flags: Female, Essential, Protected, Unique, Respawn, AutoCalcStats, PCLevelMult (then `level` = multiplier x1000), SimpleActor, Invulnerable, IsGhost...
  - template_flags: which parts come from `TPLT` (Traits, Stats, Factions, SpellList, AIData, AIPackages, Inventory, Script, Keywords...)
- `DNAM {skill_values{OneHanded..Enchanting}, skill_offsets{...}, health, magicka, stamina, far_away_model_distance, geared_up_weapons}`
- `AIDT {aggression, confidence, energy, responsibility, mood, assistance, aggro_radius_behavior, warn, warn_or_attack, attack}`
- `SNAM {faction, rank}` *(list)* factions · `SPLO` *(list)* spells/shouts (`SPCT` auto) · `PRKR {perk, rank}` *(list)* (`PRKZ` auto) · `CNTO {item, count}` inventory · `PKID` *(list)* AI packages
- `RNAM` race · `CNAM` class · `VTCK` voice · `TPLT` template · `DOFT`/`SOFT` default/sleep outfit · `INAM` death item · `ZNAM` combat style · `CRIF` crime faction · `WNAM` skin · `NAM6` height · `NAM7` weight · `PNAM` *(list)* head parts · `HCLF` hair color · `FTST` face texture
- Face data (`NAM9`, `NAMA`, tint layers `TINI/TINC/TINV/TIAS`) must match the FaceGen files in
  `meshes\actors\character\FaceGenData\` - changing race/head parts without regenerating FaceGen
  causes the dark-face bug.

**FACT** faction: `XNAM {faction, modifier, reaction}` *(list)* relations, `DATA.flags`, `CRVA` crime values, `RNAM`/`MNAM`/`FNAM` ranks, `VEND`/`VENC`/`VENV` vendor setup, jail markers `JAIL`, `WAIT`, `STOL`, `PLCN`.

**RACE**: simple fields only (`FULL`, `DESC`, `SPLO`, `WNAM` skin, `KWDA`, `VTCK`, `DNAM` default hair, `HNAM` hairs, `ENAM` eyes...). `DATA` (stats/heights) is raw - use Spriggit to edit it.

## Magic

- **SPEL**: `SPIT {base_cost, flags, type, charge_time, cast_type, target_type, cast_duration, range, half_cost_perk}` + effects. type: Spell, Disease, Power, LesserPower, Ability, Poison, Addiction, Voice.
- **ENCH**: `ENIT {enchantment_cost, flags, cast_type, enchantment_amount, target_type, enchant_type, charge_time, base_enchantment, worn_restrictions}` + effects.
- **MGEF**: `DATA {flags, base_cost, associated_item, magic_skill, resist_value, archetype, actor_value, projectile, explosion, cast_type, target_type, casting_art, hit_effect_art, ...}`, `DNAM` description, `KWDA`, `CTDA`.
- **PERK**: `DATA {trait, level, num_ranks, playable, hidden}`, `NNAM` next perk, conditions, then effects between `PRKE` and `PRKF` (`PRKE {type, rank, priority}`, `DATA` per type, `EPFT`/`EPFD` entry-point value).

## World

- **CELL**: `DATA.flags` (Interior, HasWater, PublicArea, ShowSky...), `XCLC {x, y}` exterior grid, `XCLL` interior lighting (`ambient_color`, `directional_color`, `fog_near/far`, `fog_*_color`, ...), `LTMP` lighting template, `XCLW` water height, `XCWT` water, `XLCN` location, `XEZN` encounter zone, `XOWN` owner, `XCAS` acoustic space, `XCMO` music, `XCIM` image space, `XCLR` regions.
- **REFR / ACHR** (placed object / NPC): `NAME` base object, `DATA {pos_x, pos_y, pos_z, rot_x, rot_y, rot_z}` (rotation in radians), `XSCL` scale, `XESP {reference, flags}` enable parent, `XLKR {keyword, reference}` linked refs, `XOWN`/`XRNK` ownership, `XLOC {level, key, flags}` lock, `XTEL {door, pos_*, rot_*}` teleport, `XCNT` count, `XEZN`, `XLCN`, `XLRT` location ref types, `XPRD`/`PDTO` patrol, `VMAD` scripts. Header flags: Persistent, InitiallyDisabled.
- **WRLD**: `WNAM` parent world, `CNAM` climate, `NAM2` water, `DNAM {default_land_height, default_water_height}`, `XLCN`, `ZNAM` music. Exterior cells live in blocks of 32x32 cells / sub-blocks of 8x8.
- **LCTN** location: `PNAM` parent, `KWDA`, `MNAM` map marker ref, persistent/unique ref lists (`ACPR`, `LCUN`...).
- **LAND / NAVM**: terrain and navmesh are kept raw - edit them in the Creation Kit.

## Quests and dialogue

- **QUST**: `DNAM {flags (StartGameEnabled, RunOnce, AllowRepeatedStages...), priority, type}`, stages `INDX {stage, flags}` + `QSDT` + `CNAM` log text, objectives `QOBJ`/`NNAM`/`QSTA`, aliases `ALST`/`ALLS`/`ALID`... `ALED` (partially decoded), `VMAD` (scripts decoded; fragments raw).
- **DIAL** topic: `FULL` topic text, `QNAM` quest, `BNAM` branch, `DATA {flags, category, subtype}`, `SNAM` subtype code, `PNAM` priority.
- **INFO** response (child of a DIAL): `TRDT {emotion_type, emotion_value, response_number, sound, ...}` + `NAM1` response text *(list)*, `RNAM` player prompt, `CTDA` conditions, `ENAM {flags, reset_hours}`, `TCLT` link-to topics, `ANAM` speaker, `PNAM` previous INFO.
- **MESG**: `DESC` text, `FULL` title, `DNAM.flags` (MessageBox, AutoDisplay), `ITXT` *(list)* button texts with `CTDA`.

## Misc

- **GLOB**: `FNAM` type char (`s` short, `l` long, `f` float), `FLTV` value (always stored as float).
- **GMST**: `DATA`, typed by the EditorID prefix (`f`loat, `i`nt, `b`ool, `s`tring). E.g. `esp set Patch.esp fJumpHeightMin DATA=150` (after `copy Skyrim.esm fJumpHeightMin --to Patch.esp`).
- **KYWD**: `CNAM` color. **TXST**: `TX00`-`TX07` texture paths. **STAT**: `MODL`, `DNAM {max_angle, material}`.

## Conditions (CTDA)

Decoded as `{function, param1, param2, op, value, flags, run_on, reference, param3}`:
- `op`: `==`, `!=`, `>`, `>=`, `<`, `<=`
- `value`: a number, or a GLOB when `flags` contains `UseGlobal`
- `flags`: `OR` (OR with the *next* condition; default AND), `UseGlobal`, `UseAliases`, `UsePackData`, `SwapSubjectAndTarget`
- `run_on`: `Subject`, `Target`, `Reference` (+ `reference`), `CombatTarget`, `LinkedReference`, `QuestAlias`, `PackageData`, `EventData`
- `CIS1`/`CIS2` follow a CTDA when a parameter is a string (e.g. GetVMQuestVariable).

Common functions (index): GetIsID (72), GetActorValue (14), GetBaseActorValue (277), GetItemCount (47),
GetEquipped (182), GetStage (58), GetStageDone (59), GetQuestRunning (56), GetQuestCompleted (543),
GetIsRace (69), GetIsSex (70), GetPCIsRace (130), GetPCIsSex (131), GetInFaction (71),
GetFactionRank (73), GetGlobalValue (74), GetLevel (80), GetRandomPercent (77), HasPerk (448),
HasKeyword (560), WornHasKeyword (682), HasMagicEffect (214), HasMagicEffectKeyword (699),
HasSpell (264), GetInCurrentLoc (359), LocationHasKeyword (562), GetInCell (67), IsInInterior (300),
GetIsClass (68), GetIsVoiceType (426), GetIsReference (136), GetDead (46), IsSneaking (286),
IsWeaponOut (263), GetPlayerTeammate (453), GetRelationshipRank (403), GetVMQuestVariable (629),
IsChild (365), GetIsPlayableRace (254), GetCurrentTime (18), GetDayOfWeek (170). All ~400 are in
`scripts/esplib/tables.py`.

Example: only for the player, at Smithing >= 50:
```json
{"CTDA": {"function": "GetActorValue", "param1": "Smithing", "param2": 0, "op": ">=", "value": 50.0,
          "flags": [], "run_on": "Subject", "reference": null, "param3": -1}}
```
(In recipes the subject is the player.)

## Biped slots (BOD2.slots)

`30_Head 31_Hair 32_Body 33_Hands 34_Forearms 35_Amulet 36_Ring 37_Feet 38_Calves 39_Shield 40_Tail
41_LongHair 42_Circlet 43_Ears 44..49 50_DecapitateHead 51_Decapitate 52..60 61_FX01`
(44-49 and 52-60 are unnamed; mods conventionally use 44 face, 45 neck, 46 chest, 47 back,
48 misc, 49 pelvis, 52 pelvis secondary, 53 leg R, 54 leg L, 55 face alt, 56 chest secondary,
57 shoulder, 58 arm L, 59 arm R, 60 misc).

## Record header flags (@flags)

`ESM` (TES4), `Localized` (TES4), `ESL` (TES4), `Deleted`, `Persistent` (refs), `InitiallyDisabled`
(refs), `Ignored`, `VisibleWhenDistant`, `Compressed` (handled automatically), `IsMarker`,
`NavMeshFilter`, `NavMeshBoundingBox`, `NavMeshGround/NoRespawn`, `MultiBound`, plus a few
record-specific bits (see `scripts/esplib/core.py` `RECORD_FLAG_NAMES`).

## Well-known Skyrim.esm FormIDs

`000007:Skyrim.esm` Player (NPC_), `000014:Skyrim.esm` PlayerRef, `00000F:Skyrim.esm` Gold001,
`00000A:Skyrim.esm` Lockpick. Look others up instead of guessing:
`esp find Skyrim.esm --edid '^WeapMaterial' -t KYWD --data <Data>`.

## Actor values (for GetActorValue, MGEF, WEAP skill)

Skills: OneHanded, TwoHanded, Archery, Block, Smithing, HeavyArmor, LightArmor, Pickpocket,
Lockpicking, Sneak, Alchemy, Speech, Alteration, Conjuration, Destruction, Illusion, Restoration,
Enchanting. Attributes: Health, Magicka, Stamina, HealRate, MagickaRate, StaminaRate, SpeedMult,
CarryWeight, DamageResist, PoisonResist, ResistFire, ResistShock, ResistFrost, ResistMagic,
ResistDisease, CriticalChance, UnarmedDamage... (full list: `scripts/esplib/tables.py`).
