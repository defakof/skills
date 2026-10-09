"""Field layouts for Skyrim Special Edition records (form version 44).

Each record type maps subrecord signatures to a spec (see codec.py). Anything
not listed is shown as raw hex and preserved byte for byte. Layouts that differ
between Skyrim LE (form version 43) and SE are handled with BySize().

Record types with heavily context-dependent subrecords (QUST, PACK, SCEN, RACE,
NAVM...) are only partially described; the rest stays raw.
"""

import struct

from .codec import (F, Struct, Arr, Custom, BySize, FormID, LStr, EspError,
                    f32_value, f32_pack, ctx_formid, flags_to_names, names_to_flags,
                    enum_value)
from .tables import CONDITION_FUNCTIONS, ACTOR_VALUES

# ---------------------------------------------------------------------------
# enums and flags
# ---------------------------------------------------------------------------

AV = dict(ACTOR_VALUES)
SKILLS = ['OneHanded', 'TwoHanded', 'Archery', 'Block', 'Smithing', 'HeavyArmor',
          'LightArmor', 'Pickpocket', 'Lockpicking', 'Sneak', 'Alchemy', 'Speech',
          'Alteration', 'Conjuration', 'Destruction', 'Illusion', 'Restoration',
          'Enchanting']

BIPED_SLOTS = {1 << i: f'{30 + i}' for i in range(32)}
for _i, _n in enumerate(['Head', 'Hair', 'Body', 'Hands', 'Forearms', 'Amulet', 'Ring',
                         'Feet', 'Calves', 'Shield', 'Tail', 'LongHair', 'Circlet', 'Ears']):
    BIPED_SLOTS[1 << _i] = f'{30 + _i}_{_n}'
BIPED_SLOTS[1 << 20] = '50_DecapitateHead'
BIPED_SLOTS[1 << 21] = '51_Decapitate'
BIPED_SLOTS[1 << 31] = '61_FX01'

ARMOR_TYPE = {0: 'LightArmor', 1: 'HeavyArmor', 2: 'Clothing'}
SOUND_LEVEL = {0: 'Loud', 1: 'Normal', 2: 'Silent', 3: 'VeryLoud'}
CAST_TYPE = {0: 'ConstantEffect', 1: 'FireAndForget', 2: 'Concentration', 3: 'Scroll'}
TARGET_TYPE = {0: 'Self', 1: 'Touch', 2: 'Aimed', 3: 'TargetActor', 4: 'TargetLocation'}
SPELL_TYPE = {0: 'Spell', 1: 'Disease', 2: 'Power', 3: 'LesserPower', 4: 'Ability',
              5: 'Poison', 6: 'Enchantment', 7: 'Potion', 8: 'Wortcraft', 9: 'LeveledSpell',
              10: 'Addiction', 11: 'Voice', 12: 'StaffEnchantment', 13: 'Scroll'}
SPELL_FLAGS = {0x1: 'ManualCostCalc', 0x20000: 'PCStartSpell', 0x80000: 'AreaEffectIgnoresLOS',
               0x100000: 'IgnoreResistance', 0x200000: 'NoAbsorbOrReflect',
               0x800000: 'NoDualCastModification'}
WEAP_ANIM = {0: 'HandToHand', 1: 'OneHandSword', 2: 'OneHandDagger', 3: 'OneHandAxe',
             4: 'OneHandMace', 5: 'TwoHandSword', 6: 'TwoHandAxe', 7: 'Bow', 8: 'Staff',
             9: 'Crossbow'}
WEAP_FLAGS1 = {0x1: 'IgnoresNormalWeaponResistance', 0x2: 'Automatic', 0x4: 'HasScope',
               0x8: 'CantDrop', 0x10: 'HideBackpack', 0x20: 'EmbeddedWeapon',
               0x40: 'DontUseFirstPersonISAnim', 0x80: 'NonPlayable'}
WEAP_FLAGS2 = {0x1: 'PlayerOnly', 0x2: 'NPCsUseAmmo', 0x4: 'NoJamAfterReload',
               0x10: 'MinorCrime', 0x20: 'RangeFixed', 0x40: 'NotUsedInNormalCombat',
               0x100: 'DontUseThirdPersonISAnim', 0x200: 'BurstShot', 0x400: 'RumbleAlternate',
               0x800: 'LongBursts', 0x1000: 'NonHostile', 0x2000: 'BoundWeapon'}
WEAP_ON_HIT = {0: 'NoFormulaBehavior', 1: 'DismemberOnly', 2: 'ExplodeOnly', 3: 'NoDismemberOrExplode'}
ATTACK_ANIM = {255: 'Default'}
CRDT_FLAGS = {0x1: 'OnDeath'}
AMMO_FLAGS = {0x1: 'IgnoresNormalWeaponResistance', 0x2: 'NonPlayable', 0x4: 'NonBolt'}
ALCH_FLAGS = {0x1: 'NoAutoCalc', 0x2: 'FoodItem', 0x10000: 'Medicine', 0x20000: 'Poison'}
INGR_FLAGS = {0x1: 'NoAutoCalc', 0x2: 'FoodItem', 0x100: 'ReferencesPersist'}
ENCH_FLAGS = {0x1: 'NoAutoCalc', 0x4: 'ExtendDurationOnRecast'}
ENCH_TYPE = {6: 'Enchantment', 12: 'StaffEnchantment'}
BOOK_FLAGS = {0x1: 'TeachesSkill', 0x2: 'CantBeTaken', 0x4: 'TeachesSpell', 0x8: 'Read'}
BOOK_TYPE = {0: 'BookOrTome', 255: 'NoteOrScroll'}
CONT_FLAGS = {0x1: 'AllowSoundsWhenAnimation', 0x2: 'Respawns', 0x4: 'ShowOwner'}
LVLI_FLAGS = {0x1: 'CalcFromAllLevels', 0x2: 'CalcForEachItem', 0x4: 'UseAll', 0x8: 'SpecialLoot'}
LVLN_FLAGS = {0x1: 'CalcFromAllLevels', 0x2: 'CalcForEachItem'}
LVSP_FLAGS = {0x1: 'CalcFromAllLevels', 0x2: 'CalcForEachItem', 0x4: 'UseAllSpells'}
NPC_FLAGS = {0x1: 'Female', 0x2: 'Essential', 0x4: 'IsCharGenFacePreset', 0x8: 'Respawn',
             0x10: 'AutoCalcStats', 0x20: 'Unique', 0x40: 'DoesntAffectStealthMeter',
             0x80: 'PCLevelMult', 0x100: 'UseTemplate', 0x800: 'Protected', 0x4000: 'Summonable',
             0x10000: 'DoesNotBleed', 0x40000: 'BleedoutOverride', 0x80000: 'OppositeGenderAnims',
             0x100000: 'SimpleActor', 0x200000: 'LoopedScript', 0x10000000: 'LoopedAudio',
             0x20000000: 'IsGhost', 0x80000000: 'Invulnerable'}
NPC_TEMPLATE_FLAGS = {0x1: 'Traits', 0x2: 'Stats', 0x4: 'Factions', 0x8: 'SpellList',
                      0x10: 'AIData', 0x20: 'AIPackages', 0x40: 'ModelAnimation',
                      0x80: 'BaseData', 0x100: 'Inventory', 0x200: 'Script',
                      0x400: 'DefPackList', 0x800: 'AttackData', 0x1000: 'Keywords'}
AGGRESSION = {0: 'Unaggressive', 1: 'Aggressive', 2: 'VeryAggressive', 3: 'Frenzied'}
CONFIDENCE = {0: 'Cowardly', 1: 'Cautious', 2: 'Average', 3: 'Brave', 4: 'Foolhardy'}
MOOD = {0: 'Neutral', 1: 'Angry', 2: 'Fear', 3: 'Happy', 4: 'Sad', 5: 'Surprised',
        6: 'Puzzled', 7: 'Disgusted'}
ASSISTANCE = {0: 'HelpsNobody', 1: 'HelpsAllies', 2: 'HelpsFriendsAndAllies'}
RESPONSIBILITY = {0: 'AnyCrime', 1: 'ViolenceAgainstEnemies', 2: 'PropertyCrimeOnly', 3: 'NoCrime'}
ATTACK_FLAGS = {0x1: 'IgnoreWeapon', 0x2: 'BashAttack', 0x4: 'PowerAttack', 0x8: 'LeftAttack',
                0x10: 'RotatingAttack', 0x80000000: 'OverrideData'}
CELL_FLAGS = {0x1: 'Interior', 0x2: 'HasWater', 0x4: 'CantTravelFromHere', 0x8: 'NoLODWater',
              0x20: 'PublicArea', 0x40: 'HandChanged', 0x80: 'ShowSky', 0x100: 'UseSkyLighting'}
LIGH_FLAGS = {0x1: 'Dynamic', 0x2: 'CanBeCarried', 0x4: 'Negative', 0x8: 'Flicker',
              0x20: 'OffByDefault', 0x40: 'FlickerSlow', 0x80: 'Pulse', 0x100: 'PulseSlow',
              0x200: 'SpotLight', 0x400: 'ShadowSpotlight', 0x800: 'ShadowHemisphere',
              0x1000: 'ShadowOmnidirectional', 0x2000: 'PortalStrict'}
MGEF_FLAGS = {0x1: 'Hostile', 0x2: 'Recover', 0x4: 'Detrimental', 0x8: 'SnapToNavmesh',
              0x10: 'NoHitEvent', 0x100: 'DispelWithKeywords', 0x200: 'NoDuration',
              0x400: 'NoMagnitude', 0x800: 'NoArea', 0x1000: 'FXPersist', 0x4000: 'GoryVisuals',
              0x8000: 'HideInUI', 0x20000: 'NoRecast', 0x200000: 'PowerAffectsMagnitude',
              0x400000: 'PowerAffectsDuration', 0x4000000: 'Painless', 0x8000000: 'NoHitEffect',
              0x10000000: 'NoDeathDispel'}
MGEF_ARCHETYPE = {0: 'ValueModifier', 1: 'Script', 2: 'Dispel', 3: 'CureDisease', 4: 'Absorb',
                  5: 'DualValueModifier', 6: 'Calm', 7: 'Demoralize', 8: 'Frenzy', 9: 'Disarm',
                  10: 'CommandSummoned', 11: 'Invisibility', 12: 'Light', 15: 'Lock', 16: 'Open',
                  17: 'BoundWeapon', 18: 'SummonCreature', 19: 'DetectLife', 20: 'Telekinesis',
                  21: 'Paralysis', 22: 'Reanimate', 23: 'SoulTrap', 24: 'TurnUndead', 25: 'Guide',
                  26: 'WerewolfFeed', 27: 'CureParalysis', 28: 'CureAddiction', 29: 'CurePoison',
                  30: 'Concussion', 31: 'ValueAndParts', 32: 'AccumulateMagnitude', 33: 'Stagger',
                  34: 'PeakValueModifier', 35: 'Cloak', 36: 'Werewolf', 37: 'SlowTime', 38: 'Rally',
                  39: 'EnhanceWeapon', 40: 'SpawnHazard', 41: 'Etherealize', 42: 'Banish',
                  43: 'SpawnScriptedRef', 44: 'Disguise', 45: 'GrabActor', 46: 'VampireLord'}
FACT_FLAGS = {0x1: 'HiddenFromPC', 0x2: 'SpecialCombat', 0x40: 'TrackCrime', 0x80: 'IgnoreMurder',
              0x100: 'IgnoreAssault', 0x200: 'IgnoreStealing', 0x400: 'IgnoreTrespass',
              0x800: 'DoNotReportCrimesAgainstMembers', 0x1000: 'CrimeGoldUseDefaults',
              0x2000: 'IgnorePickpocket', 0x4000: 'Vendor', 0x8000: 'CanBeOwner',
              0x10000: 'IgnoreWerewolf'}
COMBAT_REACTION = {0: 'Neutral', 1: 'Enemy', 2: 'Ally', 3: 'Friend'}
QUST_FLAGS = {0x1: 'StartGameEnabled', 0x4: 'WildernessEncounter', 0x8: 'AllowRepeatedStages',
              0x100: 'RunOnce', 0x200: 'ExcludeFromDialogExport', 0x400: 'WarnOnAliasFillFailure'}
QUST_TYPE = {0: 'None', 1: 'MainQuest', 2: 'MagesGuild', 3: 'ThievesGuild', 4: 'DarkBrotherhood',
             5: 'CompanionQuests', 6: 'Misc', 7: 'Daedric', 8: 'SideQuest', 9: 'CivilWar',
             10: 'Vampire', 11: 'Dragonborn'}
LOCK_LEVEL = {0: 'None', 1: 'Novice', 25: 'Apprentice', 50: 'Adept', 75: 'Expert', 100: 'Master',
              255: 'RequiresKey'}
ENABLE_PARENT_FLAGS = {0x1: 'OppositeOfParent', 0x2: 'PopIn'}
DOOR_FLAGS = {0x2: 'Automatic', 0x4: 'Hidden', 0x8: 'MinimalUse', 0x10: 'Sliding',
              0x20: 'DoNotOpenInCombatSearch'}
ACTI_FLAGS = {0x1: 'NoDisplacement', 0x2: 'IgnoredBySandbox'}
PROJ_FLAGS = {0x1: 'Hitscan', 0x2: 'Explosion', 0x4: 'AltTrigger', 0x8: 'MuzzleFlash',
              0x20: 'CanBeDisabled', 0x40: 'CanBePickedUp', 0x80: 'Supersonic', 0x100: 'PinsLimbs',
              0x200: 'PassThroughSmallTransparent', 0x400: 'DisableCombatAimCorrection',
              0x8000: 'Rotation'}
PROJ_TYPE = {0x1: 'Missile', 0x2: 'Lobber', 0x4: 'Beam', 0x8: 'Flame', 0x10: 'Cone',
             0x20: 'Barrier', 0x40: 'Arrow'}
SOUL_LEVEL = {0: 'None', 1: 'Petty', 2: 'Lesser', 3: 'Common', 4: 'Greater', 5: 'Grand'}
MESG_FLAGS = {0x1: 'MessageBox', 0x2: 'AutoDisplay'}
GLOB_TYPES = {'s': 'short', 'l': 'long', 'f': 'float'}
BOD2_FLAGS_OLD = {0x1: 'ModulatesVoice', 0x10: 'NonPlayable'}

COLOR = Struct([F('r', 'u8'), F('g', 'u8'), F('b', 'u8'), F('a', 'u8')], 'color')
VEC3 = Struct([F('x', 'f32'), F('y', 'f32'), F('z', 'f32')])

# ---------------------------------------------------------------------------
# custom codecs
# ---------------------------------------------------------------------------

_U32 = struct.Struct('<I')


def _fid_out(v, ctx):
    return FormID(v)


# --- CTDA (conditions) ------------------------------------------------------

COND_OPS = {0: '==', 1: '!=', 2: '>', 3: '>=', 4: '<', 5: '<='}
COND_FLAGS = {0x01: 'OR', 0x02: 'UseAliases', 0x04: 'UseGlobal', 0x08: 'UsePackData',
              0x10: 'SwapSubjectAndTarget'}
RUN_ON = {0: 'Subject', 1: 'Target', 2: 'Reference', 3: 'CombatTarget', 4: 'LinkedReference',
          5: 'QuestAlias', 6: 'PackageData', 7: 'EventData'}
FORM_PARAMS = {'Actor', 'ActorBase', 'Cell', 'Class', 'EncounterZone', 'EquipType', 'Faction',
               'FormList', 'Furniture', 'Global', 'IdleForm', 'InventoryObject', 'Keyword',
               'Knowable', 'Location', 'MagicEffect', 'MagicItem', 'ObjectReference', 'Owner',
               'Package', 'Perk', 'Quest', 'Race', 'ReferencableObject', 'RefType', 'Region',
               'Scene', 'Shout', 'VoiceType', 'Weather', 'Worldspace', 'EventData'}
_FUNC_BY_NAME = {v[0].lower(): k for k, v in CONDITION_FUNCTIONS.items()}


def _ctda_param(ptype, raw, flags):
    if ptype in FORM_PARAMS and not (flags & 0x0A):
        return FormID(raw)
    if ptype == 'ActorValue':
        sv = struct.unpack('<i', _U32.pack(raw))[0]
        return AV.get(sv, sv)
    if ptype == 'Float':
        return f32_value(_U32.pack(raw))
    return struct.unpack('<i', _U32.pack(raw))[0]


def _ctda_param_enc(ptype, v, flags, ctx):
    if ptype in FORM_PARAMS and not (flags & 0x0A):
        return ctx_formid(ctx, v)
    if ptype == 'ActorValue' and isinstance(v, str):
        v = enum_value(v, AV)
    if ptype == 'Float':
        return _U32.unpack(f32_pack(v))[0]
    if isinstance(v, str):
        v = int(v, 0)
    return v & 0xFFFFFFFF


def ctda_decode(d, ctx):
    if len(d) not in (24, 28, 32):
        raise EspError('unexpected CTDA size')
    opf = d[0]
    op, flags = opf >> 5, opf & 0x1F
    func = struct.unpack_from('<H', d, 8)[0]
    name, p1t, p2t = CONDITION_FUNCTIONS.get(func, (func, 'Integer', 'Integer'))
    p1, p2, run_on = struct.unpack_from('<III', d, 12)
    out = {'function': name}
    out['param1'] = _ctda_param(p1t, p1, flags)
    out['param2'] = _ctda_param(p2t, p2, flags)
    out['op'] = COND_OPS.get(op, op)
    out['value'] = FormID(_U32.unpack_from(d, 4)[0]) if flags & 0x04 else f32_value(d[4:8])
    out['flags'] = flags_to_names(flags, COND_FLAGS)
    out['run_on'] = RUN_ON.get(run_on, run_on)
    if len(d) >= 28:
        out['reference'] = FormID(_U32.unpack_from(d, 24)[0])
    if len(d) >= 32:
        out['param3'] = struct.unpack_from('<i', d, 28)[0]
    if d[1:4] != b'\0\0\0':
        out['_pad1'] = d[1:4].hex()
    pad2 = struct.unpack_from('<H', d, 10)[0]
    if pad2:
        out['_pad2'] = pad2
    if len(d) != 32:
        out['_size'] = len(d)
    return out, len(d)


def ctda_encode(v, ctx):
    func = v.get('function', 0)
    if isinstance(func, str):
        key = func.lower()
        if key not in _FUNC_BY_NAME:
            raise EspError(f'unknown condition function {func!r}')
        func = _FUNC_BY_NAME[key]
    _, p1t, p2t = CONDITION_FUNCTIONS.get(func, (func, 'Integer', 'Integer'))
    flags = names_to_flags(v.get('flags', 0), COND_FLAGS)
    op = v.get('op', '==')
    if isinstance(op, str):
        rev = {n: k for k, n in COND_OPS.items()}
        if op not in rev:
            raise EspError(f'bad condition operator {op!r}; use one of {list(rev)}')
        op = rev[op]
    out = bytearray()
    out.append(((op & 7) << 5) | (flags & 0x1F))
    out += bytes.fromhex(v.get('_pad1', '000000'))
    if flags & 0x04:
        out += _U32.pack(ctx_formid(ctx, v.get('value')))
    else:
        out += f32_pack(v.get('value', 0.0))
    out += struct.pack('<HH', func, v.get('_pad2', 0))
    out += _U32.pack(_ctda_param_enc(p1t, v.get('param1', 0), flags, ctx))
    out += _U32.pack(_ctda_param_enc(p2t, v.get('param2', 0), flags, ctx))
    run_on = v.get('run_on', 0)
    if isinstance(run_on, str):
        run_on = enum_value(run_on, RUN_ON)
    out += _U32.pack(run_on)
    size = v.get('_size', 32)
    if size >= 28:
        out += _U32.pack(ctx_formid(ctx, v.get('reference')))
    if size >= 32:
        out += struct.pack('<i', v.get('param3', -1))
    return bytes(out)


CTDA = Custom('condition', ctda_decode, ctda_encode,
              'Condition: function, param1/param2, op, value, flags, run_on, reference')

# --- VMAD (Papyrus scripts) -----------------------------------------------------

VMAD_TYPES = {0: 'None', 1: 'Object', 2: 'String', 3: 'Int', 4: 'Float', 5: 'Bool',
              11: 'ObjectArray', 12: 'StringArray', 13: 'IntArray', 14: 'FloatArray',
              15: 'BoolArray'}
_VMAD_TYPE_IDS = {v.lower(): k for k, v in VMAD_TYPES.items()}


class _R:
    def __init__(self, d):
        self.d, self.p = d, 0

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u(self, fmt):
        st = struct.Struct('<' + fmt)
        v = st.unpack_from(self.d, self.p)
        self.p += st.size
        return v[0] if len(v) == 1 else v

    def raw(self, n):
        if self.p + n > len(self.d):
            raise EspError('VMAD truncated')
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def wstr(self, enc):
        n = self.u('H')
        return self.raw(n).decode(enc)


def _vmad_obj(r, fmt):
    if fmt == 1:
        fid, alias, unused = r.u('I'), r.u('h'), r.u('H')
    else:
        unused, alias, fid = r.u('H'), r.u('h'), r.u('I')
    o = {'form': FormID(fid), 'alias': alias}
    if unused:
        o['_unused'] = unused
    return o


def _vmad_obj_enc(o, fmt, ctx):
    if not isinstance(o, dict):
        o = {'form': o, 'alias': -1}
    fid = ctx_formid(ctx, o.get('form'))
    alias = o.get('alias', -1)
    unused = o.get('_unused', 0)
    if fmt == 1:
        return struct.pack('<IhH', fid, alias, unused)
    return struct.pack('<HhI', unused, alias, fid)


def _vmad_value(r, t, fmt, enc):
    if t == 0:
        return None
    if t == 1:
        return _vmad_obj(r, fmt)
    if t == 2:
        return r.wstr(enc)
    if t == 3:
        return r.u('i')
    if t == 4:
        return f32_value(r.raw(4))
    if t == 5:
        return bool(r.u8()) if r.d[r.p] in (0, 1) else r.u8()
    if t in (11, 12, 13, 14, 15):
        n = r.u('I')
        return [_vmad_value(r, t - 10, fmt, enc) for _ in range(n)]
    raise EspError(f'unknown VMAD property type {t}')


def _vmad_value_enc(v, t, fmt, ctx):
    if t == 0:
        return b''
    if t == 1:
        return _vmad_obj_enc(v, fmt, ctx)
    if t == 2:
        b = str(v).encode(ctx.encoding)
        return struct.pack('<H', len(b)) + b
    if t == 3:
        return struct.pack('<i', int(v))
    if t == 4:
        return f32_pack(v)
    if t == 5:
        return bytes([int(v)])
    if t in (11, 12, 13, 14, 15):
        return struct.pack('<I', len(v)) + b''.join(_vmad_value_enc(x, t - 10, fmt, ctx) for x in v)
    raise EspError(f'unknown VMAD property type {t}')


def _vmad_scripts(r, ver, fmt, enc, count=None):
    scripts = []
    n = r.u('H') if count is None else count
    for _ in range(n):
        s = {'name': r.wstr(enc)}
        if ver >= 4:
            s['flags'] = r.u8()
        props = []
        for _ in range(r.u('H')):
            p = {'name': r.wstr(enc)}
            t = r.u8()
            p['type'] = VMAD_TYPES.get(t, t)
            if ver >= 4:
                p['flags'] = r.u8()
            p['value'] = _vmad_value(r, t, fmt, enc)
            props.append(p)
        s['properties'] = props
        scripts.append(s)
    return scripts


def _vmad_scripts_enc(scripts, ver, fmt, ctx):
    out = bytearray(struct.pack('<H', len(scripts)))
    for s in scripts:
        nb = s['name'].encode(ctx.encoding)
        out += struct.pack('<H', len(nb)) + nb
        if ver >= 4:
            out.append(s.get('flags', 0))
        props = s.get('properties', [])
        out += struct.pack('<H', len(props))
        for p in props:
            nb = p['name'].encode(ctx.encoding)
            out += struct.pack('<H', len(nb)) + nb
            t = p['type']
            if isinstance(t, str):
                t = _VMAD_TYPE_IDS[t.lower()]
            out.append(t)
            if ver >= 4:
                out.append(p.get('flags', 1))
            out += _vmad_value_enc(p['value'], t, fmt, ctx)
    return bytes(out)


def vmad_decode(d, ctx):
    r = _R(d)
    ver, fmt = r.u('h'), r.u('h')
    out = {'version': ver, 'object_format': fmt, 'scripts': _vmad_scripts(r, ver, fmt, ctx.encoding)}
    if r.p < len(d):
        out['fragments'] = {'$hex': d[r.p:].hex()}
    return out, len(d)


def vmad_encode(v, ctx):
    ver, fmt = v.get('version', 5), v.get('object_format', 2)
    out = struct.pack('<hh', ver, fmt) + _vmad_scripts_enc(v.get('scripts', []), ver, fmt, ctx)
    frag = v.get('fragments')
    if frag:
        out += bytes.fromhex(frag['$hex'] if isinstance(frag, dict) else frag)
    return out


VMAD = Custom('scripts', vmad_decode, vmad_encode,
              'Papyrus scripts: {version, object_format, scripts:[{name, flags, properties:[{name,type,flags,value}]}], fragments}')

# --- MODS alternate textures -----------------------------------------------------


def mods_decode(d, ctx):
    r = _R(d)
    n = r.u('I')
    out = []
    for _ in range(n):
        ln = r.u('I')
        name = r.raw(ln).decode(ctx.encoding)
        out.append({'name': name, 'texture_set': FormID(r.u('I')), 'index': r.u('i')})
    return out, r.p


def mods_encode(v, ctx):
    out = bytearray(struct.pack('<I', len(v)))
    for e in v:
        nb = e['name'].encode(ctx.encoding)
        out += struct.pack('<I', len(nb)) + nb
        out += struct.pack('<Ii', ctx_formid(ctx, e.get('texture_set')), e.get('index', 0))
    return bytes(out)


MODS = Custom('alternate_textures', mods_decode, mods_encode,
              'Alternate textures: [{name, texture_set, index}]')

# --- GMST DATA (type from EditorID prefix) -----------------------------------------


def _gmst_kind(ctx):
    e = (ctx.record.edid or '') if ctx.record is not None else ''
    return e[:1].lower()


def gmst_decode(d, ctx):
    k = _gmst_kind(ctx)
    if k == 'f' and len(d) == 4:
        return f32_value(d), 4
    if k == 'i' and len(d) == 4:
        return struct.unpack('<i', d)[0], 4
    if k in ('b', 'u') and len(d) == 4:
        return _U32.unpack(d)[0], 4
    if k == 's':
        if ctx.localized and len(d) == 4:
            return LStr(_U32.unpack(d)[0]), 4
        if d.endswith(b'\0') and b'\0' not in d[:-1]:
            return d[:-1].decode(ctx.encoding), len(d)
    raise EspError('GMST type unknown')


def gmst_encode(v, ctx):
    k = _gmst_kind(ctx)
    if k == 'f':
        return f32_pack(v)
    if k == 'i':
        return struct.pack('<i', int(v))
    if k in ('b', 'u'):
        return _U32.pack(int(v))
    if k == 's':
        if ctx.localized:
            if isinstance(v, str):
                raise EspError('plugin is localized; cannot write text')
            return _U32.pack(int(v))
        return str(v).encode(ctx.encoding) + b'\0'
    raise EspError('GMST EditorID must start with f/i/b/s/u')


GMST_DATA = Custom('gmst_value', gmst_decode, gmst_encode,
                   'Value; type from EditorID prefix (f float, i int, b bool, s string)')

# --- BOOK DATA (teaches skill or spell) ---------------------------------------------


def book_decode(d, ctx):
    if len(d) != 16:
        raise EspError('BOOK DATA size')
    flags, typ, unused, teach, value = struct.unpack_from('<BBHII', d, 0)
    out = {'flags': flags_to_names(flags, BOOK_FLAGS), 'type': BOOK_TYPE.get(typ, typ)}
    if unused:
        out['_unused'] = unused
    if flags & 0x4:
        out['teaches'] = FormID(teach)
    else:
        sv = struct.unpack('<i', _U32.pack(teach))[0]
        out['teaches'] = AV.get(sv, sv) if flags & 0x1 else sv
    out['value'] = value
    out['weight'] = f32_value(d[12:16])
    return out, 16


def book_encode(v, ctx):
    flags = names_to_flags(v.get('flags', 0), BOOK_FLAGS)
    typ = v.get('type', 0)
    if isinstance(typ, str):
        typ = enum_value(typ, BOOK_TYPE)
    t = v.get('teaches', -1)
    if flags & 0x4:
        t = ctx_formid(ctx, t)
    else:
        if isinstance(t, str):
            t = enum_value(t, AV)
        t &= 0xFFFFFFFF
    return struct.pack('<BBHII', flags, typ, v.get('_unused', 0), t, v.get('value', 0)) + f32_pack(v.get('weight', 0.0))


BOOK_DATA = Custom('book_data', book_decode, book_encode,
                   '{flags, type, teaches (skill name or spell FormID), value, weight}')

# --- PLVD / location target ----------------------------------------------------------

LOC_TARGET_TYPES = {0: 'NearReference', 1: 'InCell', 2: 'NearPackageStart', 3: 'NearEditorLocation',
                    4: 'ObjectID', 5: 'ObjectType', 6: 'LinkedReference', 7: 'AtPackageLocation',
                    8: 'AliasForReference', 9: 'AliasForLocation', 12: 'NearSelf'}


def loct_decode(d, ctx):
    if len(d) != 12:
        raise EspError('location target size')
    t, val, radius = struct.unpack('<iII', d)
    out = {'type': LOC_TARGET_TYPES.get(t, t)}
    out['target'] = FormID(val) if t in (0, 1, 4, 6) else struct.unpack('<i', _U32.pack(val))[0]
    out['radius'] = radius
    return out, 12


def loct_encode(v, ctx):
    t = v.get('type', 0)
    if isinstance(t, str):
        t = enum_value(t, LOC_TARGET_TYPES)
    tgt = v.get('target', 0)
    tgt = ctx_formid(ctx, tgt) if t in (0, 1, 4, 6) else int(tgt) & 0xFFFFFFFF
    return struct.pack('<iII', t, tgt, v.get('radius', 0))


LOC_TARGET = Custom('location_target', loct_decode, loct_encode, '{type, target, radius}')

# --- PERK effect DATA / EPFD (depend on preceding PRKE / EPFT) ------------------------------


def perk_data_decode(d, ctx):
    if ctx.state.get('section') != 'effect':
        if len(d) != 5:
            raise EspError('perk DATA size')
        keys = ('trait', 'level', 'num_ranks', 'playable', 'hidden')
        return dict(zip(keys, d)), 5
    t = ctx.state.get('prke_type')
    if t == 0 and len(d) == 8:
        return {'quest': FormID(_U32.unpack_from(d)[0]), 'stage': d[4], '_unused': d[5:].hex()}, 8
    if t == 1 and len(d) == 4:
        return {'ability': FormID(_U32.unpack(d)[0])}, 4
    if t == 2 and len(d) == 3:
        return {'entry_point': d[0], 'function': d[1], 'condition_tabs': d[2]}, 3
    raise EspError('perk effect DATA')


def perk_data_encode(v, ctx):
    if ctx.state.get('section') != 'effect':
        return bytes(v.get(k, 0) for k in ('trait', 'level', 'num_ranks', 'playable', 'hidden'))
    if 'quest' in v:
        return _U32.pack(ctx_formid(ctx, v['quest'])) + bytes([v.get('stage', 0)]) + bytes.fromhex(v.get('_unused', '000000'))
    if 'ability' in v:
        return _U32.pack(ctx_formid(ctx, v['ability']))
    return bytes([v.get('entry_point', 0), v.get('function', 0), v.get('condition_tabs', 0)])


PERK_DATA = Custom('perk_data', perk_data_decode, perk_data_encode,
                   'Header: {trait, level, num_ranks, playable, hidden}; inside an effect: '
                   '{quest, stage} | {ability} | {entry_point, function, condition_tabs}')


def epfd_decode(d, ctx):
    t = ctx.state.get('epft')
    if t == 1 and len(d) == 4:
        return f32_value(d), 4
    if t == 2 and len(d) == 8:
        return [f32_value(d[:4]), f32_value(d[4:])], 8
    if t in (3, 4, 5) and len(d) == 4:
        return FormID(_U32.unpack(d)[0]), 4
    if t == 6 and d.endswith(b'\0') and b'\0' not in d[:-1]:
        return d[:-1].decode(ctx.encoding), len(d)
    if t == 7 and len(d) == 4 and ctx.localized:
        return LStr(_U32.unpack(d)[0]), 4
    if t == 7 and d.endswith(b'\0') and b'\0' not in d[:-1]:
        return d[:-1].decode(ctx.encoding), len(d)
    raise EspError('EPFD')


def epfd_encode(v, ctx):
    t = ctx.state.get('epft')
    if t == 1:
        return f32_pack(v)
    if t == 2:
        return f32_pack(v[0]) + f32_pack(v[1])
    if t in (3, 4, 5):
        return _U32.pack(ctx_formid(ctx, v))
    if t == 7 and ctx.localized:
        return _U32.pack(int(v))
    return str(v).encode(ctx.encoding) + b'\0'


EPFD = Custom('entry_point_data', epfd_decode, epfd_encode,
              'Entry point parameter (float, [float,float], FormID or text, per EPFT)')

def pdto_decode(d, ctx):
    if len(d) != 8:
        raise EspError('PDTO size')
    t = _U32.unpack_from(d)[0]
    if t == 0:
        return {'type': 'Topic', 'topic': FormID(_U32.unpack_from(d, 4)[0])}, 8
    return {'type': t, 'subtype': d[4:8].decode('latin-1')}, 8


def pdto_encode(v, ctx):
    if v.get('type') in ('Topic', 0):
        return _U32.pack(0) + _U32.pack(ctx_formid(ctx, v.get('topic')))
    return _U32.pack(int(v['type'])) + v['subtype'].encode('latin-1')


PDTO = Custom('topic_ref', pdto_decode, pdto_encode, '{type: Topic, topic} or {type, subtype}')

def coed_decode(d, ctx):
    if len(d) != 12:
        raise EspError('COED size')
    owner, second = struct.unpack_from('<II', d, 0)
    out = {'owner': FormID(owner)}
    # NPC owner -> global variable FormID; faction owner -> required rank
    out['global_or_rank'] = FormID(second) if second >= 0x800 else second
    out['condition'] = f32_value(d[8:12])
    return out, 12


def coed_encode(v, ctx):
    second = v.get('global_or_rank', 0)
    second = ctx_formid(ctx, second) if not isinstance(second, int) or isinstance(second, FormID) else second
    return struct.pack('<II', ctx_formid(ctx, v.get('owner')), second & 0xFFFFFFFF) + f32_pack(v.get('condition', 1.0))


COED_SPEC = Custom('extra_data', coed_decode, coed_encode,
                   '{owner, global_or_rank (Global FormID for NPC owners, rank number for factions), condition}')

# ---------------------------------------------------------------------------
# shared building blocks
# ---------------------------------------------------------------------------

OBND = Struct([F('x1', 'i16'), F('y1', 'i16'), F('z1', 'i16'),
               F('x2', 'i16'), F('y2', 'i16'), F('z2', 'i16')])
DEST = Struct([F('health', 'i32'), F('stage_count', 'u8'), F('vats_targetable', 'u8'),
               F('unknown', 'i16')])
DSTD = Struct([F('health_percent', 'u8'), F('index', 'u8'), F('model_damage_stage', 'u8'),
               F('flags', 'u8', flags={1: 'CapDamage', 2: 'Disable', 4: 'Destroy', 8: 'IgnoreExternalDamage'}),
               F('self_damage_per_second', 'i32'), F('explosion', 'fid'), F('debris', 'fid'),
               F('debris_count', 'i32')])
EFIT = Struct([F('magnitude', 'f32'), F('area', 'u32'), F('duration', 'u32')])
CNTO = Struct([F('item', 'fid'), F('count', 'i32')])
COED = COED_SPEC
LVLO = Struct([F('level', 'u16'), F('_unused1', 'u16'), F('reference', 'fid'),
               F('count', 'u16'), F('_unused2', 'u16')])
SPIT = Struct([F('base_cost', 'u32'), F('flags', 'u32', flags=SPELL_FLAGS),
               F('type', 'u32', enum=SPELL_TYPE), F('charge_time', 'f32'),
               F('cast_type', 'u32', enum=CAST_TYPE), F('target_type', 'u32', enum=TARGET_TYPE),
               F('cast_duration', 'f32'), F('range', 'f32'), F('half_cost_perk', 'fid')])
VALUE_WEIGHT = Struct([F('value', 'u32'), F('weight', 'f32')])
BOD2 = Struct([F('slots', 'u32', flags=BIPED_SLOTS), F('armor_type', 'u32', enum=ARMOR_TYPE)])
BODT = Struct([F('slots', 'u32', flags=BIPED_SLOTS), F('flags', 'u8', flags=BOD2_FLAGS_OLD),
               F('_unused', ('bytes', 3)), F('armor_type', 'u32', enum=ARMOR_TYPE)])
XESP = Struct([F('reference', 'fid'), F('flags', 'u8', flags=ENABLE_PARENT_FLAGS),
               F('_unused', ('bytes', 3))])
XLKR = Struct([F('keyword', 'fid'), F('reference', 'fid')])
XAPR = Struct([F('reference', 'fid'), F('delay', 'f32')])
PLACEMENT = Struct([F('pos_x', 'f32'), F('pos_y', 'f32'), F('pos_z', 'f32'),
                    F('rot_x', 'f32'), F('rot_y', 'f32'), F('rot_z', 'f32')])


def model(prefix_m, t, s):
    return {prefix_m: 'zstr', t: 'bytes', s: MODS}


MODEL = model('MODL', 'MODT', 'MODS')
DESTRUCTIBLE = {'DEST': DEST, 'DSTD': DSTD, 'DMDL': 'zstr', 'DMDT': 'bytes', 'DMDS': MODS,
                'DSTF': 'empty'}
KEYWORDS = {'KSIZ': 'u32', 'KWDA': Arr('fid')}
ICONS = {'ICON': 'zstr', 'MICO': 'zstr'}
EFFECTS = {'EFID': 'fid', 'EFIT': EFIT, 'CTDA': CTDA, 'CIS1': 'zstr', 'CIS2': 'zstr'}
CONDITIONS = {'CTDA': CTDA, 'CIS1': 'zstr', 'CIS2': 'zstr'}
SOUNDS_PICKUP = {'YNAM': 'fid', 'ZNAM': 'fid'}
ITEMS = {'COCT': 'u32', 'CNTO': CNTO, 'COED': COED}


def rec(*parts, **extra):
    out = {}
    for p in parts:
        out.update(p)
    out.update(extra)
    return out


class RecordDef:
    def __init__(self, sig, name, subs, sections=None, notes=''):
        self.sig = sig
        self.name = name
        self.subs = subs
        self.sections = sections or []   # list of (name, start_sigs, end_sigs, subs)
        self.notes = notes


RECORDS = {}


def R(sig, name, subs, sections=None, notes=''):
    RECORDS[sig] = RecordDef(sig, name, subs, sections, notes)


# ---------------------------------------------------------------------------
# record definitions
# ---------------------------------------------------------------------------

R('TES4', 'File Header', {
    'HEDR': Struct([F('version', 'f32'), F('num_records', 'u32'), F('next_object_id', 'u32')]),
    'OFST': 'bytes', 'DELE': 'bytes',
    'CNAM': 'zstr', 'SNAM': 'zstr', 'MAST': 'zstr', 'DATA': 'u64',
    'ONAM': Arr('fid'), 'INTV': 'u32', 'INCC': 'u32',
})

R('GMST', 'Game Setting', {'EDID': 'zstr', 'DATA': GMST_DATA})
R('GLOB', 'Global Variable', {'EDID': 'zstr', 'FNAM': 'char', 'FLTV': 'f32'},
  notes='FNAM: s=short, l=long, f=float. The value is always stored as a float in FLTV.')
R('KYWD', 'Keyword', {'EDID': 'zstr', 'CNAM': COLOR})
R('LCRT', 'Location Reference Type', {'EDID': 'zstr', 'CNAM': COLOR})
R('AACT', 'Action', {'EDID': 'zstr', 'CNAM': COLOR})
R('FLST', 'Form List', {'EDID': 'zstr', 'LNAM': 'fid'})
R('OTFT', 'Outfit', {'EDID': 'zstr', 'INAM': Arr('fid')})
R('EQUP', 'Equip Type', {'EDID': 'zstr', 'PNAM': Arr('fid'), 'DATA': 'u32'})
R('VTYP', 'Voice Type', {'EDID': 'zstr', 'DNAM': 'u8'})
R('CLFM', 'Color', {'EDID': 'zstr', 'FULL': 'lstr', 'CNAM': COLOR, 'FNAM': 'u32'})
R('WOOP', 'Word of Power', {'EDID': 'zstr', 'FULL': 'lstr', 'TNAM': 'lstr'})
R('SHOU', 'Shout', {'EDID': 'zstr', 'FULL': 'lstr', 'MDOB': 'fid', 'DESC': 'lstr',
                    'SNAM': Struct([F('word', 'fid'), F('spell', 'fid'), F('recovery_time', 'f32')])})
R('RELA', 'Relationship', {'EDID': 'zstr', 'DATA': Struct([
    F('parent', 'fid'), F('child', 'fid'), F('rank', 'u16', enum={
        0: 'Lover', 1: 'Ally', 2: 'Confidant', 3: 'Friend', 4: 'Acquaintance', 5: 'Rival',
        6: 'Foe', 7: 'Enemy', 8: 'Archnemesis'}),
    F('unknown', 'u8'), F('flags', 'u8', flags={0x80: 'Secret'}), F('association_type', 'fid')])})
R('ASTP', 'Association Type', {'EDID': 'zstr', 'MPRT': 'zstr', 'FPRT': 'zstr', 'MCHT': 'zstr',
                               'FCHT': 'zstr', 'DATA': 'u32'})
R('TXST', 'Texture Set', rec({'EDID': 'zstr', 'OBND': OBND},
                             {f'TX0{i}': 'zstr' for i in range(8)},
                             {'DODT': 'bytes', 'DNAM': 'u16'}))
R('EYES', 'Eyes', {'EDID': 'zstr', 'FULL': 'lstr', 'ICON': 'zstr', 'DATA': 'u8'})
R('HDPT', 'Head Part', rec({'EDID': 'zstr', 'FULL': 'lstr'}, MODEL, {
    'DATA': 'u8', 'PNAM': 'u32', 'HNAM': 'fid', 'NAM0': 'u32', 'NAM1': 'zstr',
    'TNAM': 'fid', 'CNAM': 'fid', 'RNAM': 'fid'}))
R('ARTO', 'Art Object', rec({'EDID': 'zstr', 'OBND': OBND}, MODEL, {'DNAM': 'u32'}))
R('ANIO', 'Animated Object', rec({'EDID': 'zstr'}, MODEL, {'BNAM': 'zstr'}))
R('FSTP', 'Footstep', {'EDID': 'zstr', 'DATA': 'fid', 'ANAM': 'zstr'})
R('FSTS', 'Footstep Set', {'EDID': 'zstr', 'XCNT': Arr('u32', 5), 'DATA': Arr('fid')})
R('MATT', 'Material Type', {'EDID': 'zstr', 'PNAM': 'fid', 'MNAM': 'zstr', 'CNAM': VEC3,
                            'BNAM': 'f32', 'FNAM': 'u32', 'HNAM': 'fid'})
R('IPDS', 'Impact Data Set', {'EDID': 'zstr', 'PNAM': Struct([F('material', 'fid'), F('impact', 'fid')])})
R('DUAL', 'Dual Cast Data', {'EDID': 'zstr', 'OBND': OBND, 'DATA': Struct([
    F('projectile', 'fid'), F('explosion', 'fid'), F('effect_shader', 'fid'),
    F('hit_effect_art', 'fid'), F('impact_data_set', 'fid'), F('inherit_scale', 'u32')])})
R('DOBJ', 'Default Object Manager', {'EDID': 'zstr', 'DNAM': Arr(Struct([F('use', 'char4'), F('object', 'fid')]))})
R('LSCR', 'Load Screen', rec({'EDID': 'zstr', 'ICON': 'zstr', 'DESC': 'lstr'}, CONDITIONS, {
    'NNAM': 'fid', 'SNAM': 'f32',
    'RNAM': Struct([F('x', 'i16'), F('y', 'i16'), F('z', 'i16')]),
    'ONAM': Struct([F('min', 'i16'), F('max', 'i16')]), 'XNAM': VEC3, 'MOD2': 'zstr'}))
R('ECZN', 'Encounter Zone', {'EDID': 'zstr', 'DATA': Struct([
    F('owner', 'fid'), F('location', 'fid'), F('rank', 'i8'), F('min_level', 'i8'),
    F('flags', 'u8', flags={1: 'NeverResets', 2: 'MatchPCBelowMinLevel', 4: 'DisableCombatBoundary'}),
    F('max_level', 'i8')])})
R('MESG', 'Message', rec({'EDID': 'zstr', 'DESC': 'lstr', 'FULL': 'lstr',
                          'INAM': BySize({4: 'fid', 0: 'empty'}),
                          'QNAM': 'fid', 'DNAM': ('u32'), 'TNAM': 'u32', 'ITXT': 'lstr'}, CONDITIONS))
RECORDS['MESG'].subs['DNAM'] = Struct([F('flags', 'u32', flags=MESG_FLAGS)])

# --- items ------------------------------------------------------------------------

WEAP_DNAM = Struct([
    F('animation_type', 'u8', enum=WEAP_ANIM), F('_unused1', ('bytes', 3)),
    F('speed', 'f32'), F('reach', 'f32'), F('flags', 'u16', flags=WEAP_FLAGS1),
    F('_unused2', 'u16'), F('sight_fov', 'f32'), F('_unknown1', 'u32'),
    F('base_vats_to_hit', 'u8'), F('attack_animation', 'u8', enum=ATTACK_ANIM),
    F('num_projectiles', 'u8'), F('embedded_weapon_av', 'u8'),
    F('range_min', 'f32'), F('range_max', 'f32'), F('on_hit', 'u32', enum=WEAP_ON_HIT),
    F('flags2', 'u32', flags=WEAP_FLAGS2), F('animation_attack_mult', 'f32'),
    F('_unknown2', 'u32'), F('rumble_left', 'f32'), F('rumble_right', 'f32'),
    F('rumble_duration', 'f32'), F('_unknown3', ('bytes', 12)),
    F('skill', 'i32', enum=AV), F('_unknown4', ('bytes', 8)), F('resist', 'i32', enum=AV),
    F('_unknown5', 'u32'), F('stagger', 'f32')])
CRDT = BySize({
    24: Struct([F('damage', 'u16'), F('_unused1', 'u16'), F('percent_mult', 'f32'),
                F('flags', 'u8', flags=CRDT_FLAGS), F('_unused2', ('bytes', 3)),
                F('_unused3', 'u32'), F('effect', 'fid'), F('_unused4', 'u32')]),
    16: Struct([F('damage', 'u16'), F('_unused1', 'u16'), F('percent_mult', 'f32'),
                F('flags', 'u8', flags=CRDT_FLAGS), F('_unused2', ('bytes', 3)),
                F('effect', 'fid')]),
})

R('WEAP', 'Weapon', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL, ICONS,
    {'EITM': 'fid', 'EAMT': 'u16'}, DESTRUCTIBLE,
    {'ETYP': 'fid', 'BIDS': 'fid', 'BAMT': 'fid'}, SOUNDS_PICKUP, KEYWORDS,
    {'DESC': 'lstr'}, model('MOD3', 'MO3T', 'MO3S'),
    {'NNAM': 'bytes', 'INAM': 'fid', 'WNAM': 'fid', 'SNAM': 'fid', 'XNAM': 'fid', 'NAM7': 'fid',
     'TNAM': 'fid', 'UNAM': 'fid', 'NAM9': 'fid', 'NAM8': 'fid',
     'DATA': Struct([F('value', 'u32'), F('weight', 'f32'), F('damage', 'u16')]),
     'DNAM': WEAP_DNAM, 'CRDT': CRDT, 'VNAM': Struct([F('detection_sound', 'u32', enum=SOUND_LEVEL)]),
     'CNAM': 'fid'}),
  notes='DATA = value/weight/base damage. DNAM = speed, reach, stagger, flags... CRDT = critical. '
        'CNAM = template weapon. EITM/EAMT = enchantment and charge.')

R('ARMO', 'Armor', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr', 'EITM': 'fid', 'EAMT': 'u16'},
    model('MOD2', 'MO2T', 'MO2S'), {'ICON': 'zstr', 'MICO': 'zstr'},
    model('MOD4', 'MO4T', 'MO4S'), {'ICO2': 'zstr', 'MIC2': 'zstr'},
    {'BODT': BODT, 'BOD2': BOD2}, DESTRUCTIBLE, SOUNDS_PICKUP,
    {'BMCT': 'zstr', 'ETYP': 'fid', 'BIDS': 'fid', 'BAMT': 'fid', 'RNAM': 'fid'}, KEYWORDS,
    {'DESC': 'lstr', 'MODL': 'fid',
     'DATA': Struct([F('value', 'i32'), F('weight', 'f32')]),
     'DNAM': Struct([F('armor_rating_x100', 'i32')]), 'TNAM': 'fid'}),
  notes='DNAM is armor rating x100 (e.g. 2500 = 25). MODL entries are Armor Addon (ARMA) FormIDs. '
        'BOD2 = biped slots + armor type.')

R('ARMA', 'Armor Addon', rec(
    {'EDID': 'zstr', 'BODT': BODT, 'BOD2': BOD2, 'RNAM': 'fid',
     'DNAM': Struct([F('male_priority', 'u8'), F('female_priority', 'u8'),
                     F('male_weight_slider', 'u8', flags={2: 'Enabled'}),
                     F('female_weight_slider', 'u8', flags={2: 'Enabled'}),
                     F('_unknown1', 'u16'), F('detection_sound_value', 'u8'),
                     F('_unknown2', 'u8'), F('weapon_adjust', 'f32')])},
    model('MOD2', 'MO2T', 'MO2S'), model('MOD3', 'MO3T', 'MO3S'),
    model('MOD4', 'MO4T', 'MO4S'), model('MOD5', 'MO5T', 'MO5S'),
    {'NAM0': 'fid', 'NAM1': 'fid', 'NAM2': 'fid', 'NAM3': 'fid', 'MODL': 'fid',
     'SNDD': 'fid', 'ONAM': 'fid'}),
  notes='MOD2/MOD3 male/female world model, MOD4/MOD5 male/female 1st person. '
        'MODL entries are additional Race FormIDs.')

R('AMMO', 'Ammunition', rec(
    {'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, MODEL, ICONS, DESTRUCTIBLE, SOUNDS_PICKUP,
    {'DESC': 'lstr'}, KEYWORDS,
    {'DATA': Struct([F('projectile', 'fid'), F('flags', 'u32', flags=AMMO_FLAGS),
                     F('damage', 'f32'), F('value', 'u32'), F('weight', 'f32')]),
     'ONAM': 'zstr'}))

R('MISC', 'Misc Item', rec({'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'},
                           MODEL, ICONS, DESTRUCTIBLE, SOUNDS_PICKUP, KEYWORDS,
                           {'DATA': VALUE_WEIGHT}))
R('KEYM', 'Key', rec({'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'},
                     MODEL, ICONS, DESTRUCTIBLE, SOUNDS_PICKUP, KEYWORDS, {'DATA': VALUE_WEIGHT}))
R('SLGM', 'Soul Gem', rec({'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, MODEL, ICONS,
                          DESTRUCTIBLE, SOUNDS_PICKUP, KEYWORDS,
                          {'DATA': VALUE_WEIGHT,
                           'SOUL': Struct([F('contained_soul', 'u8', enum=SOUL_LEVEL)]),
                           'SLCP': Struct([F('capacity', 'u8', enum=SOUL_LEVEL)]),
                           'NAM0': 'fid'}))
R('APPA', 'Alchemical Apparatus', rec({'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'},
                                      MODEL, ICONS, DESTRUCTIBLE, SOUNDS_PICKUP,
                                      {'QUAL': 'u32', 'DESC': 'lstr', 'DATA': VALUE_WEIGHT}))
R('BOOK', 'Book', rec({'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL, ICONS,
                      {'DESC': 'lstr'}, DESTRUCTIBLE, SOUNDS_PICKUP, KEYWORDS,
                      {'DATA': BOOK_DATA, 'INAM': 'fid', 'CNAM': 'lstr'}),
  notes='DESC is the book text. DATA.teaches is a skill name (TeachesSkill flag) or a spell FormID (TeachesSpell).')
R('INGR', 'Ingredient', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, KEYWORDS, MODEL, ICONS,
    DESTRUCTIBLE, {'ETYP': 'fid'}, SOUNDS_PICKUP,
    {'DATA': VALUE_WEIGHT,
     'ENIT': Struct([F('ingredient_value', 'i32'), F('flags', 'u32', flags=INGR_FLAGS)])},
    EFFECTS))
R('ALCH', 'Potion / Food', rec(
    {'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, KEYWORDS, {'DESC': 'lstr'}, MODEL,
    DESTRUCTIBLE, ICONS, SOUNDS_PICKUP, {'ETYP': 'fid', 'DATA': 'f32'},
    {'ENIT': Struct([F('value', 'u32'), F('flags', 'u32', flags=ALCH_FLAGS), F('addiction', 'fid'),
                     F('addiction_chance', 'f32'), F('consume_sound', 'fid')])},
    EFFECTS),
  notes='DATA = weight. ENIT.value is used only with the NoAutoCalc flag.')
R('SCRL', 'Scroll', rec(
    {'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, KEYWORDS,
    {'MDOB': 'fid', 'ETYP': 'fid', 'DESC': 'lstr'}, MODEL, DESTRUCTIBLE, SOUNDS_PICKUP,
    {'DATA': VALUE_WEIGHT, 'SPIT': SPIT}, EFFECTS))
R('LIGH', 'Light', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND}, MODEL, DESTRUCTIBLE, {'FULL': 'lstr'}, ICONS,
    {'DATA': Struct([F('time', 'i32'), F('radius', 'u32'), F('color', COLOR),
                     F('flags', 'u32', flags=LIGH_FLAGS), F('falloff_exponent', 'f32'),
                     F('fov', 'f32'), F('near_clip', 'f32'), F('flicker_period', 'f32'),
                     F('flicker_intensity_amplitude', 'f32'), F('flicker_movement_amplitude', 'f32'),
                     F('value', 'u32'), F('weight', 'f32')]),
     'FNAM': 'f32', 'SNAM': 'fid', 'LNAM': 'fid'}))

# --- magic --------------------------------------------------------------------------

R('SPEL', 'Spell', rec({'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, KEYWORDS,
                       {'MDOB': 'fid', 'ETYP': 'fid', 'DESC': 'lstr', 'SPIT': SPIT}, EFFECTS),
  notes='Effects are EFID (magic effect) + EFIT (magnitude/area/duration) + optional CTDA conditions.')
R('ENCH', 'Object Effect (Enchantment)', rec(
    {'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr',
     'ENIT': Struct([F('enchantment_cost', 'i32'), F('flags', 'u32', flags=ENCH_FLAGS),
                     F('cast_type', 'u32', enum=CAST_TYPE), F('enchantment_amount', 'i32'),
                     F('target_type', 'u32', enum=TARGET_TYPE),
                     F('enchant_type', 'u32', enum=ENCH_TYPE), F('charge_time', 'f32'),
                     F('base_enchantment', 'fid'), F('worn_restrictions', 'fid')])},
    EFFECTS))
R('MGEF', 'Magic Effect', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'FULL': 'lstr', 'MDOB': 'fid'}, KEYWORDS,
    {'DATA': Struct([
        F('flags', 'u32', flags=MGEF_FLAGS), F('base_cost', 'f32'), F('associated_item', 'fid'),
        F('magic_skill', 'i32', enum=AV), F('resist_value', 'i32', enum=AV),
        F('counter_effect_count', 'u16'), F('_unknown1', 'u16'), F('casting_light', 'fid'),
        F('taper_weight', 'f32'), F('hit_shader', 'fid'), F('enchant_shader', 'fid'),
        F('minimum_skill_level', 'u32'), F('spellmaking_area', 'u32'),
        F('spellmaking_casting_time', 'f32'), F('taper_curve', 'f32'), F('taper_duration', 'f32'),
        F('second_av_weight', 'f32'), F('archetype', 'u32', enum=MGEF_ARCHETYPE),
        F('actor_value', 'i32', enum=AV), F('projectile', 'fid'), F('explosion', 'fid'),
        F('cast_type', 'u32', enum=CAST_TYPE), F('target_type', 'u32', enum=TARGET_TYPE),
        F('second_actor_value', 'i32', enum=AV), F('casting_art', 'fid'),
        F('hit_effect_art', 'fid'), F('impact_data', 'fid'), F('skill_usage_mult', 'f32'),
        F('dual_cast_art', 'fid'), F('dual_cast_scale', 'f32'), F('enchant_art', 'fid'),
        F('hit_visuals', 'fid'), F('enchant_visuals', 'fid'), F('equip_ability', 'fid'),
        F('image_space_modifier', 'fid'), F('perk_to_apply', 'fid'),
        F('casting_sound_level', 'u32', enum=SOUND_LEVEL), F('script_ai_score', 'f32'),
        F('script_ai_delay_time', 'f32')]),
     'ESCE': 'fid', 'SNDD': Arr(Struct([F('type', 'u32', enum={
         0: 'SheatheDraw', 1: 'Charge', 2: 'Ready', 3: 'Release', 4: 'ConcentrationCastLoop',
         5: 'OnHit'}), F('sound', 'fid')])),
     'DNAM': 'lstr'}, CONDITIONS))

R('PERK', 'Perk', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'FULL': 'lstr', 'DESC': 'lstr', 'ICON': 'zstr', 'MICO': 'zstr'},
    CONDITIONS, {'DATA': PERK_DATA, 'NNAM': 'fid'}),
  sections=[('effect', {'PRKE'}, {'PRKF'}, rec(
      {'PRKE': Struct([F('type', 'u8', enum={0: 'Quest', 1: 'Ability', 2: 'EntryPoint'}),
                       F('rank', 'u8'), F('priority', 'u8')]),
       'DATA': PERK_DATA, 'PRKC': 'i8'}, CONDITIONS,
      {'EPFT': 'u8', 'EPF2': 'lstr', 'EPF3': 'u32', 'EPFD': EPFD, 'PRKF': 'empty'}))],
  notes='Perk effects sit between PRKE and PRKF; DATA there depends on PRKE.type.')

# --- actors ---------------------------------------------------------------------------

ACBS = Struct([F('flags', 'u32', flags=NPC_FLAGS), F('magicka_offset', 'i16'),
               F('stamina_offset', 'i16'), F('level', 'i16'), F('calc_min_level', 'i16'),
               F('calc_max_level', 'i16'), F('speed_mult', 'i16'), F('disposition_base', 'i16'),
               F('template_flags', 'u16', flags=NPC_TEMPLATE_FLAGS), F('health_offset', 'i16'),
               F('bleedout_override', 'i16')])
AIDT = Struct([F('aggression', 'u8', enum=AGGRESSION), F('confidence', 'u8', enum=CONFIDENCE),
               F('energy', 'u8'), F('responsibility', 'u8', enum=RESPONSIBILITY),
               F('mood', 'u8', enum=MOOD), F('assistance', 'u8', enum=ASSISTANCE),
               F('aggro_radius_behavior', 'u8'), F('_unused', 'u8'), F('warn', 'u32'),
               F('warn_or_attack', 'u32'), F('attack', 'u32')])
NPC_DNAM = Struct([F('skill_values', Struct([F(s, 'u8') for s in SKILLS])),
                   F('skill_offsets', Struct([F(s, 'u8') for s in SKILLS])),
                   F('health', 'u16'), F('magicka', 'u16'), F('stamina', 'u16'),
                   F('_unused1', 'u16'), F('far_away_model_distance', 'f32'),
                   F('geared_up_weapons', 'u8'), F('_unused2', ('bytes', 3))])
ATKD = Struct([F('damage_mult', 'f32'), F('chance', 'f32'), F('spell', 'fid'),
               F('flags', 'u32', flags=ATTACK_FLAGS), F('attack_angle', 'f32'),
               F('strike_angle', 'f32'), F('stagger', 'f32'), F('attack_type', 'fid'),
               F('knockdown', 'f32'), F('recovery_time', 'f32'), F('stamina_mult', 'f32')])

R('NPC_', 'Non-Player Character', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'ACBS': ACBS,
     'SNAM': Struct([F('faction', 'fid'), F('rank', 'i8'), F('_unused', ('bytes', 3))]),
     'INAM': 'fid', 'VTCK': 'fid', 'TPLT': 'fid', 'RNAM': 'fid', 'SPCT': 'u32', 'SPLO': 'fid'},
    DESTRUCTIBLE,
    {'WNAM': 'fid', 'ANAM': 'fid', 'ATKR': 'fid', 'ATKD': ATKD, 'ATKE': 'zstr',
     'SPOR': 'fid', 'OCOR': 'fid', 'GWOR': 'fid', 'ECOR': 'fid', 'PRKZ': 'u32',
     'PRKR': Struct([F('perk', 'fid'), F('rank', 'u8'), F('_unused', ('bytes', 3))])},
    ITEMS, {'AIDT': AIDT, 'PKID': 'fid'}, KEYWORDS,
    {'CNAM': 'fid', 'FULL': 'lstr', 'SHRT': 'lstr', 'DATA': 'empty', 'DNAM': NPC_DNAM,
     'PNAM': 'fid', 'HCLF': 'fid', 'ZNAM': 'fid', 'GNAM': 'fid', 'NAM5': 'u16', 'NAM6': 'f32',
     'NAM7': 'f32', 'NAM8': Struct([F('sound_level', 'u32', enum=SOUND_LEVEL)]),
     'CSDT': 'u32', 'CSDI': 'fid', 'CSDC': 'u8', 'CSCR': 'fid', 'DOFT': 'fid', 'SOFT': 'fid',
     'DPLT': 'fid', 'CRIF': 'fid', 'FTST': 'fid', 'QNAM': VEC3,
     'NAM9': Arr('f32'), 'NAMA': Struct([F('nose', 'u32'), F('unknown', 'u32'), F('eyes', 'u32'),
                                         F('mouth', 'u32')]),
     'TINI': 'u16', 'TINC': COLOR, 'TINV': 'i32', 'TIAS': 'i16'}),
  notes='ACBS = level/flags/template flags; DNAM = skills/health/magicka/stamina; AIDT = AI; '
        'SNAM = faction+rank; SPLO spells; PRKR perks; CNTO inventory; PKID packages; '
        'TPLT template; DOFT default outfit; NAM6 height; NAM7 weight.')

R('LVLI', 'Leveled Item', {'EDID': 'zstr', 'OBND': OBND, 'LVLD': 'u8',
                           'LVLF': Struct([F('flags', 'u8', flags=LVLI_FLAGS)]),
                           'LVLG': 'fid', 'LLCT': 'u8', 'LVLO': LVLO, 'COED': COED},
  notes='LVLD = chance none (%). Entries are LVLO {level, reference, count}; LLCT is kept in sync.')
R('LVLN', 'Leveled NPC', rec({'EDID': 'zstr', 'OBND': OBND, 'LVLD': 'u8',
                             'LVLF': Struct([F('flags', 'u8', flags=LVLN_FLAGS)]),
                             'LVLG': 'fid', 'LLCT': 'u8', 'LVLO': LVLO, 'COED': COED}, MODEL))
R('LVSP', 'Leveled Spell', {'EDID': 'zstr', 'OBND': OBND, 'LVLD': 'u8',
                            'LVLF': Struct([F('flags', 'u8', flags=LVSP_FLAGS)]),
                            'LLCT': 'u8', 'LVLO': LVLO, 'COED': COED})

R('FACT', 'Faction', rec(
    {'EDID': 'zstr', 'FULL': 'lstr',
     'XNAM': Struct([F('faction', 'fid'), F('modifier', 'i32'),
                     F('reaction', 'u32', enum=COMBAT_REACTION)]),
     'DATA': Struct([F('flags', 'u32', flags=FACT_FLAGS)]),
     'JAIL': 'fid', 'WAIT': 'fid', 'STOL': 'fid', 'PLCN': 'fid', 'CRGR': 'fid', 'JOUT': 'fid',
     'CRVA': Struct([F('arrest', 'u8'), F('attack_on_sight', 'u8'), F('murder', 'u16'),
                     F('assault', 'u16'), F('trespass', 'u16'), F('pickpocket', 'u16'),
                     F('_unknown', 'u16'), F('steal_mult', 'f32'), F('escape', 'u16'),
                     F('werewolf', 'u16')]),
     'RNAM': 'u32', 'MNAM': 'lstr', 'FNAM': 'lstr', 'INAM': 'zstr',
     'VEND': 'fid', 'VENC': 'fid',
     'VENV': Struct([F('start_hour', 'u16'), F('end_hour', 'u16'), F('radius', 'u16'),
                     F('_unknown', 'u16'), F('only_buys_stolen', 'u8'), F('not_sell_buy', 'u8'),
                     F('_unknown2', 'u16')]),
     'PLVD': LOC_TARGET, 'CITC': 'u32'}, CONDITIONS))

R('CLAS', 'Class', {'EDID': 'zstr', 'FULL': 'lstr', 'DESC': 'lstr', 'ICON': 'zstr',
                    'DATA': Struct([F('_unknown', 'i32'), F('teaches', 'i8'),
                                    F('max_training_level', 'u8'),
                                    F('skill_weights', Struct([F(s, 'u8') for s in SKILLS])),
                                    F('bleedout_default', 'f32'), F('voice_points', 'u32'),
                                    F('health_weight', 'u8'), F('magicka_weight', 'u8'),
                                    F('stamina_weight', 'u8'), F('_unknown2', 'u8')])})

R('RACE', 'Race', rec({'EDID': 'zstr', 'FULL': 'lstr', 'DESC': 'lstr', 'SPCT': 'u32',
                       'SPLO': 'fid', 'WNAM': 'fid', 'BODT': BODT, 'BOD2': BOD2}, KEYWORDS),
  notes='Only the simple RACE fields are decoded; use Spriggit for the rest.')

# --- objects ----------------------------------------------------------------------------

R('STAT', 'Static', rec({'EDID': 'zstr', 'OBND': OBND}, MODEL,
                        {'DNAM': Struct([F('max_angle', 'f32'), F('material', 'fid'),
                                         F('flags', 'u8', flags={1: 'ConsideredSnow'}),
                                         F('_unused', ('bytes', 3))]),
                         'MNAM': 'bytes'}))
R('MSTT', 'Moveable Static', rec({'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, MODEL,
                                 DESTRUCTIBLE, {'DATA': 'u8', 'SNAM': 'fid'}))
R('SCOL', 'Static Collection', rec({'EDID': 'zstr', 'OBND': OBND}, MODEL, {'ONAM': 'fid', 'DATA': Arr('f32')}))
R('ACTI', 'Activator', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL, DESTRUCTIBLE, KEYWORDS,
    {'PNAM': COLOR, 'SNAM': 'fid', 'VNAM': 'fid', 'WNAM': 'fid', 'RNAM': 'lstr',
     'FNAM': Struct([F('flags', 'u16', flags=ACTI_FLAGS)]), 'KNAM': 'fid'}))
R('TACT', 'Talking Activator', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL, DESTRUCTIBLE, KEYWORDS,
    {'PNAM': 'u32', 'SNAM': 'fid', 'FNAM': 'u16', 'VNAM': 'fid'}))
R('CONT', 'Container', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL, ITEMS, DESTRUCTIBLE,
    {'DATA': Struct([F('flags', 'u8', flags=CONT_FLAGS), F('weight', 'f32')]),
     'SNAM': 'fid', 'QNAM': 'fid'}),
  notes='Inventory = CNTO {item, count} entries; COCT is kept in sync.')
R('DOOR', 'Door', rec({'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL,
                      DESTRUCTIBLE, {'SNAM': 'fid', 'ANAM': 'fid', 'BNAM': 'fid',
                                     'FNAM': Struct([F('flags', 'u8', flags=DOOR_FLAGS)])}))
R('FLOR', 'Flora', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL, DESTRUCTIBLE, KEYWORDS,
    {'PNAM': COLOR, 'RNAM': 'lstr', 'FNAM': 'u16', 'PFIG': 'fid', 'SNAM': 'fid',
     'PFPC': Struct([F('spring', 'u8'), F('summer', 'u8'), F('fall', 'u8'), F('winter', 'u8')])}))
R('TREE', 'Tree', rec({'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND}, MODEL,
                      {'PFIG': 'fid', 'SNAM': 'fid',
                       'PFPC': Struct([F('spring', 'u8'), F('summer', 'u8'), F('fall', 'u8'), F('winter', 'u8')]),
                       'FULL': 'lstr', 'CNAM': 'bytes'}))
R('FURN', 'Furniture', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL, DESTRUCTIBLE, KEYWORDS,
    {'PNAM': COLOR, 'FNAM': 'u16', 'KNAM': 'fid', 'MNAM': 'u32',
     'WBDT': Struct([F('bench_type', 'u8'), F('uses_skill', 'i8')]), 'NAM1': 'fid',
     'ENAM': 'i32', 'NAM0': Struct([F('_unknown', 'u16'), F('disabled_entry_points', 'u16')]),
     'FNMK': 'fid', 'FNPR': Struct([F('type', 'u16'), F('entry_points', 'u16')]),
     'XMRK': 'zstr'}))
R('COBJ', 'Constructible Object (Recipe)', rec(
    ITEMS, CONDITIONS, {'EDID': 'zstr', 'CNAM': 'fid', 'BNAM': 'fid', 'NAM1': 'u16'}),
  notes='CNTO = required items, CNAM = created object, BNAM = workbench keyword, NAM1 = count created.')
RECORDS['COBJ'].subs = {k: RECORDS['COBJ'].subs[k] for k in
                        ('EDID', 'COCT', 'CNTO', 'COED', 'CTDA', 'CIS1', 'CIS2', 'CNAM', 'BNAM', 'NAM1')}

R('PROJ', 'Projectile', rec(
    {'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, MODEL, DESTRUCTIBLE,
    {'DATA': Struct([
        F('flags', 'u16', flags=PROJ_FLAGS), F('type', 'u16', enum=PROJ_TYPE), F('gravity', 'f32'),
        F('speed', 'f32'), F('range', 'f32'), F('light', 'fid'), F('muzzle_flash', 'fid'),
        F('tracer_chance', 'f32'), F('explosion_alt_trigger_proximity', 'f32'),
        F('explosion_alt_trigger_timer', 'f32'), F('explosion', 'fid'), F('sound', 'fid'),
        F('muzzle_flash_duration', 'f32'), F('fade_duration', 'f32'), F('impact_force', 'f32'),
        F('countdown_sound', 'fid'), F('disable_sound', 'fid'), F('default_weapon_source', 'fid'),
        F('cone_spread', 'f32'), F('collision_radius', 'f32'), F('lifetime', 'f32'),
        F('relaunch_interval', 'f32'), F('decal_data', 'fid'), F('collision_layer', 'fid')]),
     'NAM1': 'zstr', 'NAM2': 'bytes', 'VNAM': 'u32'}))
R('EXPL', 'Explosion', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr'}, MODEL,
    {'EITM': 'fid', 'MNAM': 'fid',
     'DATA': Struct([F('light', 'fid'), F('sound1', 'fid'), F('sound2', 'fid'),
                     F('impact_data_set', 'fid'), F('placed_object', 'fid'),
                     F('spawn_projectile', 'fid'), F('force', 'f32'), F('damage', 'f32'),
                     F('radius', 'f32'), F('is_radius', 'f32'), F('vertical_offset_mult', 'f32'),
                     F('flags', 'u32'), F('sound_level', 'u32', enum=SOUND_LEVEL)])}))
R('HAZD', 'Hazard', rec(
    {'EDID': 'zstr', 'OBND': OBND, 'FULL': 'lstr'}, MODEL,
    {'MNAM': 'fid',
     'DATA': Struct([F('limit', 'u32'), F('radius', 'f32'), F('lifetime', 'f32'),
                     F('image_space_radius', 'f32'), F('target_interval', 'f32'),
                     F('flags', 'u32'), F('spell', 'fid'), F('light', 'fid'),
                     F('impact_data_set', 'fid'), F('sound', 'fid')])}))
R('IPCT', 'Impact', rec({'EDID': 'zstr'}, MODEL, {'DATA': 'bytes', 'DODT': 'bytes', 'DNAM': 'fid',
                                                  'ENAM': 'fid', 'SNAM': 'fid', 'NAM1': 'fid',
                                                  'NAM2': 'fid'}))
R('MUSC', 'Music Type', {'EDID': 'zstr', 'FNAM': 'u32', 'PNAM': Struct([F('priority', 'u16'), F('ducking', 'u16')]),
                         'WNAM': 'f32', 'TNAM': Arr('fid')})
R('LGTM', 'Lighting Template', {'EDID': 'zstr', 'DATA': 'bytes', 'DALC': 'bytes'})

# --- world -------------------------------------------------------------------------------

AMBIENT = Struct([F('x_plus', COLOR), F('x_minus', COLOR), F('y_plus', COLOR),
                  F('y_minus', COLOR), F('z_plus', COLOR), F('z_minus', COLOR),
                  F('specular', COLOR), F('scale', 'f32')])
XCLL = Struct([F('ambient_color', COLOR), F('directional_color', COLOR), F('fog_near_color', COLOR),
               F('fog_near', 'f32'), F('fog_far', 'f32'), F('directional_rotation_xy', 'i32'),
               F('directional_rotation_z', 'i32'), F('directional_fade', 'f32'),
               F('fog_clip_distance', 'f32'), F('fog_power', 'f32'), F('ambient', AMBIENT),
               F('fog_far_color', COLOR), F('fog_max', 'f32'), F('light_fade_begin', 'f32'),
               F('light_fade_end', 'f32'), F('inherits', 'u32')])

R('CELL', 'Cell', {
    'EDID': 'zstr', 'FULL': 'lstr', 'DATA': BySize({2: Struct([F('flags', 'u16', flags=CELL_FLAGS)]),
                                                    1: Struct([F('flags', 'u8', flags=CELL_FLAGS)])}),
    'XCLC': Struct([F('x', 'i32'), F('y', 'i32'), F('flags', 'u32')]), 'XCLL': XCLL,
    'TVDT': 'bytes', 'MHDT': 'bytes', 'LTMP': 'fid', 'LNAM': 'bytes', 'XCLW': 'f32',
    'XNAM': 'zstr', 'XCLR': Arr('fid'), 'XLCN': 'fid', 'XWCN': 'bytes', 'XWCS': 'bytes',
    'XWCU': 'bytes', 'XCWT': 'fid', 'XOWN': 'fid', 'XRNK': 'i32', 'XILL': 'fid', 'XWEM': 'zstr',
    'XCCM': 'fid', 'XCAS': 'fid', 'XEZN': 'fid', 'XCMO': 'fid', 'XCIM': 'fid'},
  notes='XCLC = exterior grid; XCLL = interior lighting; LTMP = lighting template; '
        'XCLW = water height; XLCN = location; XEZN = encounter zone; XOWN = owner.')

REF_COMMON = {
    'EDID': 'zstr', 'VMAD': VMAD, 'NAME': 'fid', 'XMBO': VEC3, 'XPRM': 'bytes', 'XORD': 'bytes',
    'XOCP': 'bytes', 'XPOD': Arr(Struct([F('origin', 'fid'), F('destination', 'fid')])),
    'XPTL': 'bytes', 'XRMR': 'bytes', 'LNAM': 'fid', 'INAM': 'fid', 'XLRM': 'fid',
    'XMBP': 'empty', 'XRGD': 'bytes', 'XRGB': 'bytes', 'XRDS': 'f32', 'XLTW': 'fid',
    'XEMI': 'fid', 'XLIG': 'bytes', 'XALP': 'bytes',
    'XTEL': Struct([F('door', 'fid'), F('pos_x', 'f32'), F('pos_y', 'f32'), F('pos_z', 'f32'),
                    F('rot_x', 'f32'), F('rot_y', 'f32'), F('rot_z', 'f32'),
                    F('flags', 'u32', flags={1: 'NoAlarm'})]),
    'XTNM': 'fid', 'XMBR': 'fid', 'XWCN': 'bytes', 'XWCS': 'bytes', 'XWCU': 'bytes',
    'XCVL': 'bytes', 'XCZR': 'fid', 'XCZA': 'bytes', 'XCZC': 'fid', 'XSCL': 'f32',
    'XSPC': 'fid', 'XAPD': 'u8', 'XAPR': XAPR, 'XLIB': 'fid', 'XLCM': 'i32', 'XLCN': 'fid',
    'XTRI': 'u32',
    'XLOC': Struct([F('level', 'u8', enum=LOCK_LEVEL), F('_unused1', ('bytes', 3)), F('key', 'fid'),
                    F('flags', 'u8', flags={1: 'LeveledLock'}), F('_unused2', ('bytes', 3)),
                    F('_unused3', ('bytes', 8))]),
    'XEZN': 'fid',
    'XNDP': Struct([F('navmesh', 'fid'), F('triangle', 'i16'), F('_unused', 'u16')]),
    'XLRT': Arr('fid'), 'XIS2': 'empty', 'XOWN': 'fid', 'XRNK': 'i32', 'XCNT': 'i32',
    'XCHG': 'f32', 'XLRL': 'fid', 'XESP': XESP, 'XLKR': XLKR,
    'XPRD': 'f32', 'XPPA': 'empty', 'SCHR': 'bytes', 'SCDA': 'bytes', 'SCTX': 'zstr',
    'QNAM': 'fid', 'SCRO': 'fid', 'PDTO': PDTO,
    'XACT': 'u32', 'XHTW': 'f32', 'XFVC': 'f32', 'ONAM': 'empty', 'XMRK': 'empty',
    'FNAM': Struct([F('flags', 'u8', flags={1: 'Visible', 2: 'CanTravelTo', 4: 'ShowAllHidden'})]),
    'FULL': 'lstr', 'TNAM': Struct([F('marker_type', 'u8'), F('_unused', 'u8')]),
    'XATR': 'fid', 'XLOD': 'bytes', 'XHLP': 'f32', 'XMRC': 'fid', 'XHOR': 'fid',
    'XCLP': 'bytes', 'XIBS': 'empty', 'DATA': PLACEMENT,
}
_REF_NOTES = ('NAME = base object; DATA = position/rotation (rotation in radians); '
              'XSCL scale; XESP enable parent; XLKR linked ref; XOWN owner; XTEL door teleport.')
for _s, _n in [('REFR', 'Placed Object'), ('ACHR', 'Placed NPC'), ('PGRE', 'Placed Grenade'),
               ('PMIS', 'Placed Missile'), ('PARW', 'Placed Arrow'), ('PBAR', 'Placed Barrier'),
               ('PBEA', 'Placed Beam'), ('PCON', 'Placed Cone/Voice'), ('PFLA', 'Placed Flame'),
               ('PHZD', 'Placed Hazard')]:
    R(_s, _n, dict(REF_COMMON), notes=_REF_NOTES)

R('WRLD', 'Worldspace', {
    'EDID': 'zstr', 'RNAM': 'bytes', 'MHDT': 'bytes', 'FULL': 'lstr',
    'WCTR': Struct([F('x', 'i16'), F('y', 'i16')]), 'LTMP': 'fid', 'XEZN': 'fid', 'XLCN': 'fid',
    'WNAM': 'fid', 'PNAM': 'u16', 'CNAM': 'fid', 'NAM2': 'fid', 'NAM3': 'fid', 'NAM4': 'f32',
    'DNAM': Struct([F('default_land_height', 'f32'), F('default_water_height', 'f32')]),
    'ICON': 'zstr', 'MNAM': 'bytes', 'ONAM': Struct([F('scale', 'f32'), F('cell_x_offset', 'f32'),
                                                     F('cell_y_offset', 'f32'), F('cell_z_offset', 'f32')]),
    'NAMA': 'f32', 'DATA': 'u8', 'NAM0': Struct([F('x', 'f32'), F('y', 'f32')]),
    'NAM9': Struct([F('x', 'f32'), F('y', 'f32')]), 'ZNAM': 'fid', 'NNAM': 'zstr',
    'XNAM': 'zstr', 'TNAM': 'zstr', 'UNAM': 'zstr', 'XWEM': 'zstr', 'OFST': 'bytes',
    'CLSZ': 'bytes'})
R('LAND', 'Landscape', {
    'DATA': 'u32', 'VNML': 'bytes', 'VHGT': 'bytes', 'VCLR': 'bytes',
    'BTXT': Struct([F('texture', 'fid'), F('quadrant', 'u8'), F('_unknown', 'u8'), F('layer', 'i16')]),
    'ATXT': Struct([F('texture', 'fid'), F('quadrant', 'u8'), F('_unknown', 'u8'), F('layer', 'u16')]),
    'VTXT': 'bytes', 'VTEX': Arr('fid')})
R('LCTN', 'Location', rec(
    {'EDID': 'zstr',
     'ACPR': Arr(Struct([F('actor', 'fid'), F('location', 'fid'), F('grid_x', 'i16'), F('grid_y', 'i16')])),
     'LCPR': Arr(Struct([F('actor', 'fid'), F('location', 'fid'), F('grid_x', 'i16'), F('grid_y', 'i16')])),
     'RCPR': Arr('fid'),
     'ACUN': Arr(Struct([F('npc', 'fid'), F('ref', 'fid'), F('location', 'fid')])),
     'LCUN': Arr(Struct([F('npc', 'fid'), F('ref', 'fid'), F('location', 'fid')])),
     'RCUN': Arr('fid'),
     'ACSR': Arr(Struct([F('loc_ref_type', 'fid'), F('ref', 'fid'), F('location', 'fid'),
                         F('grid_x', 'i16'), F('grid_y', 'i16')])),
     'LCSR': Arr(Struct([F('loc_ref_type', 'fid'), F('ref', 'fid'), F('location', 'fid'),
                         F('grid_x', 'i16'), F('grid_y', 'i16')])),
     'RCSR': Arr('fid'),
     'ACEC': Struct([F('location', 'fid'), F('cells', Arr(Struct([F('x', 'i16'), F('y', 'i16')])))]),
     'LCEC': Struct([F('location', 'fid'), F('cells', Arr(Struct([F('x', 'i16'), F('y', 'i16')])))]),
     'RCEC': Struct([F('location', 'fid'), F('cells', Arr(Struct([F('x', 'i16'), F('y', 'i16')])))]),
     'ACID': Arr('fid'), 'LCID': Arr('fid'),
     'ACEP': Arr(Struct([F('actor', 'fid'), F('ref', 'fid'), F('grid_x', 'i16'), F('grid_y', 'i16')])),
     'LCEP': Arr(Struct([F('actor', 'fid'), F('ref', 'fid'), F('grid_x', 'i16'), F('grid_y', 'i16')])),
     'FULL': 'lstr'}, KEYWORDS,
    {'PNAM': 'fid', 'NAM1': 'fid', 'FNAM': 'fid', 'MNAM': 'fid', 'RNAM': 'f32', 'NAM0': 'fid',
     'CNAM': COLOR}))
R('NAVM', 'Navigation Mesh', {'NVNM': 'bytes', 'ONAM': 'bytes', 'PNAM': 'bytes', 'NNAM': 'bytes'},
  notes='Navmesh geometry is not decoded. Edit navmeshes in the Creation Kit.')

# --- dialogue / quests -----------------------------------------------------------------------

R('DIAL', 'Dialog Topic', {
    'EDID': 'zstr', 'FULL': 'lstr', 'PNAM': 'f32', 'BNAM': 'fid', 'QNAM': 'fid',
    'DATA': Struct([F('flags', 'u8', flags={1: 'DoAllBeforeRepeating'}), F('category', 'u8'),
                    F('subtype', 'u16')]),
    'SNAM': 'char4', 'TIFC': 'u32'})
R('INFO', 'Dialog Response', rec(
    {'VMAD': VMAD, 'DATA': 'bytes',
     'ENAM': Struct([F('flags', 'u16'), F('reset_hours', 'u16')]),
     'TPIC': 'fid', 'PNAM': 'fid', 'CNAM': 'u8', 'TCLT': 'fid', 'DNAM': 'fid',
     'TRDT': Struct([F('emotion_type', 'u32', enum=MOOD), F('emotion_value', 'u32'),
                     F('_unused1', 'i32'), F('response_number', 'u8'), F('_unused2', ('bytes', 3)),
                     F('sound', 'fid'), F('use_emotion_animation', 'u8'), F('_unused3', ('bytes', 3))]),
     'NAM1': 'lstr', 'NAM2': 'zstr', 'NAM3': 'zstr', 'SNAM': 'fid', 'LNAM': 'fid'},
    CONDITIONS, {'RNAM': 'lstr', 'ANAM': 'fid', 'TWAT': 'fid', 'ONAM': 'fid'}),
  notes='NAM1 = response text (lives in .ILSTRINGS when localized); RNAM = player prompt.')
R('QUST', 'Quest', rec(
    {'EDID': 'zstr', 'VMAD': VMAD, 'FULL': 'lstr',
     'DNAM': Struct([F('flags', 'u16', flags=QUST_FLAGS), F('priority', 'u8'),
                     F('form_version', 'u8'), F('_unknown', 'u32'), F('type', 'u32', enum=QUST_TYPE)]),
     'ENAM': 'char4', 'QTGL': 'fid', 'FLTR': 'zstr', 'NEXT': 'empty',
     'INDX': Struct([F('stage', 'u16'), F('flags', 'u8', flags={2: 'StartUpStage', 4: 'ShutDownStage',
                                                               8: 'KeepInstanceDataFromHereOn'}),
                     F('_unknown', 'u8')]),
     'QSDT': Struct([F('flags', 'u8', flags={1: 'CompleteQuest', 2: 'FailQuest'})]),
     'CNAM': 'lstr', 'NAM0': 'fid', 'QOBJ': 'i16', 'NNAM': 'lstr',
     'QSTA': Struct([F('alias', 'i32'), F('flags', 'u32')]),
     'ANAM': 'u32', 'ALST': 'u32', 'ALLS': 'u32', 'ALID': 'zstr', 'ALFI': 'i32', 'ALFL': 'fid',
     'ALFR': 'fid', 'ALUA': 'fid', 'ALCO': 'fid', 'ALCA': 'i32', 'ALCL': 'u32', 'ALEQ': 'fid',
     'ALEA': 'u32', 'ALNA': 'u32', 'ALNT': 'u32', 'KNAM': 'fid', 'ALDN': 'fid', 'ALSP': 'fid',
     'ALFC': 'fid', 'ALPC': 'fid', 'VTCK': 'fid', 'ALED': 'empty', 'SPOR': 'fid', 'OCOR': 'fid',
     'GWOR': 'fid', 'ECOR': 'fid'}, CONDITIONS, KEYWORDS, ITEMS),
  notes='Quest stages: INDX + QSDT + CNAM (log text). Objectives: QOBJ + NNAM + QSTA. '
        'Aliases: ALST/ALLS ... ALED. Script fragments live in VMAD.fragments (raw).')
R('PACK', 'Package', rec(
    {'EDID': 'zstr', 'VMAD': VMAD,
     'PKDT': Struct([F('flags', 'u32'), F('type', 'u8'), F('interrupt_override', 'u8'),
                     F('preferred_speed', 'u8'), F('_unknown', 'u8'), F('interrupt_flags', 'u16'),
                     F('_unknown2', 'u16')]),
     'PSDT': Struct([F('month', 'i8'), F('day_of_week', 'i8'), F('date', 'u8'), F('hour', 'i8'),
                     F('minute', 'i8'), F('_unused', ('bytes', 3)), F('duration_minutes', 'i32')]),
     'PKCU': Struct([F('data_input_count', 'u32'), F('package_template', 'fid'),
                     F('version_counter', 'u32')]),
     'QNAM': 'fid', 'IDLF': 'u8', 'IDLC': 'u8', 'IDLT': 'f32', 'IDLA': Arr('fid')},
    CONDITIONS),
  notes='Package data inputs/procedure trees are context dependent and kept raw.')
R('SCEN', 'Scene', rec({'EDID': 'zstr', 'VMAD': VMAD, 'FNAM': 'u32', 'PNAM': 'fid'}, CONDITIONS),
  notes='Only the scene header is decoded.')


# --- misc / audio-visual ------------------------------------------------------------

R('LTEX', 'Landscape Texture', {'EDID': 'zstr', 'TNAM': 'fid', 'MNAM': 'fid',
                                'HNAM': Struct([F('friction', 'u8'), F('restitution', 'u8')]),
                                'SNAM': 'u8', 'GNAM': 'fid', 'INAM': 'u32'})
R('CLMT', 'Climate', rec({'EDID': 'zstr',
                          'WLST': Arr(Struct([F('weather', 'fid'), F('chance', 'i32'), F('global', 'fid')])),
                          'FNAM': 'zstr', 'GNAM': 'zstr'}, MODEL, {'TNAM': 'bytes'}),
  notes='WLST = weathers with chance (%) and optional global.')
R('SNDR', 'Sound Descriptor', rec({'EDID': 'zstr', 'CNAM': 'u32', 'GNAM': 'fid', 'SNAM': 'fid',
                                   'ANAM': 'zstr', 'ONAM': 'fid', 'FNAM': 'lstr'}, CONDITIONS,
                                  {'LNAM': 'bytes', 'BNAM': 'bytes'}))
R('SOUN', 'Sound Marker', {'EDID': 'zstr', 'OBND': OBND, 'FNAM': 'bytes', 'SNDD': 'bytes', 'SDSC': 'fid'})
R('ASPC', 'Acoustic Space', {'EDID': 'zstr', 'OBND': OBND, 'SNAM': 'fid', 'RDAT': 'fid', 'BNAM': 'fid'})
R('IDLM', 'Idle Marker', rec({'EDID': 'zstr', 'OBND': OBND, 'IDLF': 'u8',
                              'IDLC': BySize({1: 'u8', 4: 'u32'}), 'IDLT': 'f32', 'IDLA': Arr('fid')}, MODEL))
R('ADDN', 'Addon Node', rec({'EDID': 'zstr', 'OBND': OBND}, MODEL,
                            {'DATA': 'u32', 'SNAM': 'fid',
                             'DNAM': Struct([F('particle_cap', 'u16'), F('flags', 'u16')])}))
R('GRAS', 'Grass', rec({'EDID': 'zstr', 'OBND': OBND}, MODEL, {'DATA': 'bytes'}))
R('MATO', 'Material Object', rec({'EDID': 'zstr'}, MODEL, {'DNAM': 'bytes', 'DATA': 'bytes'}))
R('COLL', 'Collision Layer', {'EDID': 'zstr', 'DESC': 'lstr', 'BNAM': 'u32', 'FNAM': COLOR,
                              'GNAM': 'u32', 'MNAM': 'zstr', 'INTV': 'u32', 'CNAM': Arr('fid')})
R('DLBR', 'Dialog Branch', {'EDID': 'zstr', 'QNAM': 'fid', 'TNAM': 'u32', 'DNAM': 'u32', 'SNAM': 'fid'})
R('DLVW', 'Dialog View', {'EDID': 'zstr', 'QNAM': 'fid', 'BNAM': 'fid', 'TNAM': 'bytes',
                          'ENAM': 'bytes', 'DNAM': 'bytes'})
R('CAMS', 'Camera Shot', rec({'EDID': 'zstr'}, MODEL, {'DATA': 'bytes', 'MNAM': 'fid'}))
R('CPTH', 'Camera Path', rec({'EDID': 'zstr'}, CONDITIONS, {'ANAM': Arr('fid'), 'DATA': 'u8', 'SNAM': 'fid'}))
R('IDLE', 'Idle Animation', rec({'EDID': 'zstr'}, CONDITIONS,
                                {'DNAM': 'zstr', 'ENAM': 'zstr', 'ANAM': Arr('fid'), 'DATA': 'bytes'}),
  notes='ANAM = parent and previous idle.')
R('WATR', 'Water', {'EDID': 'zstr', 'FULL': 'lstr', 'NNAM': 'zstr', 'ANAM': 'u8', 'FNAM': 'u8',
                    'MNAM': 'bytes', 'TNAM': 'fid', 'SNAM': 'fid', 'XNAM': 'fid', 'INAM': 'fid',
                    'DATA': 'u16', 'DNAM': 'bytes', 'GNAM': 'bytes', 'NAM0': VEC3, 'NAM1': VEC3,
                    'NAM2': 'zstr', 'NAM3': 'zstr', 'NAM4': 'zstr', 'NAM5': 'zstr'})
R('MUST', 'Music Track', rec({'EDID': 'zstr', 'CNAM': 'u32', 'FLTV': 'f32', 'DNAM': 'f32',
                             'ANAM': 'zstr', 'BNAM': 'zstr', 'LNAM': 'bytes', 'FNAM': Arr('f32'),
                             'CITC': 'u32'}, CONDITIONS, {'SNAM': Arr('fid')}))
R('RFCT', 'Visual Effect', {'EDID': 'zstr', 'DATA': Struct([F('effect_art', 'fid'), F('shader', 'fid'),
                                                            F('flags', 'u32')])})
_SM = rec({'EDID': 'zstr', 'VMAD': VMAD, 'PNAM': 'fid', 'SNAM': 'fid', 'CITC': 'u32'}, CONDITIONS,
          {'DNAM': 'bytes', 'XNAM': 'u32'})
R('SMBN', 'Story Manager Branch Node', rec(_SM, {'DNAM': 'u32'}))
R('SMEN', 'Story Manager Event Node', rec(_SM, {'DNAM': 'u32', 'ENAM': 'char4'}))
R('SMQN', 'Story Manager Quest Node', rec(_SM, {'DNAM': Struct([F('flags', 'u16'), F('quest_flags', 'u16')]),
                                                 'MNAM': 'u32', 'QNAM': 'u32', 'NNAM': 'fid',
                                                 'FNAM': 'u32', 'RNAM': 'f32'}),
  notes='Quests: QNAM (count) then NNAM quest + FNAM flags + RNAM hours until reset per quest.')
R('AVIF', 'Actor Value Information', {'EDID': 'zstr', 'FULL': 'lstr', 'DESC': 'lstr', 'ANAM': 'zstr',
                                      'CNAM': 'bytes', 'AVSK': 'bytes'},
  sections=[('perk_node', {'PNAM'}, {'INAM'}, {
      'PNAM': 'fid', 'FNAM': 'bytes', 'XNAM': 'u32', 'YNAM': 'u32', 'HNAM': 'f32', 'VNAM': 'f32',
      'SNAM': 'fid', 'CNAM': 'u32', 'INAM': 'u32'})],
  notes='Perk tree nodes: PNAM perk, XNAM/YNAM grid, CNAM connections, INAM index.')
R('EFSH', 'Effect Shader', {'EDID': 'zstr', 'ICON': 'zstr', 'ICO2': 'zstr', 'NAM7': 'zstr',
                            'NAM8': 'zstr', 'NAM9': 'zstr', 'DATA': 'bytes'})
R('WTHR', 'Weather', {'EDID': 'zstr', 'MNAM': 'fid', 'NNAM': 'fid', 'TNAM': 'fid',
                      'SNAM': Struct([F('sound', 'fid'), F('type', 'u32')]),
                      'IMSP': Arr('fid'), 'HNAM': Arr('fid')},
  notes='MNAM precipitation, NNAM visual effect, SNAM sounds, TNAM sky statics, IMSP image spaces, '
        'HNAM volumetric lighting. Cloud/color data is kept raw.')
R('REGN', 'Region', {'EDID': 'zstr', 'RCLR': COLOR, 'WNAM': 'fid', 'RDMO': 'fid', 'ICON': 'zstr'},
  notes='Region data entries (RDAT + RDOT/RDGS/RDSA/RDWT...) are kept raw.')

RACE_SUBS = rec(
    {'EDID': 'zstr', 'FULL': 'lstr', 'DESC': 'lstr', 'SPCT': 'u32', 'SPLO': 'fid', 'WNAM': 'fid',
     'BODT': BODT, 'BOD2': BOD2}, KEYWORDS,
    {'DATA': 'bytes', 'MNAM': 'empty', 'FNAM': 'empty', 'NAM0': 'empty', 'NAM1': 'empty',
     'NAM3': 'empty', 'ANAM': 'zstr', 'MODL': 'zstr', 'MODT': 'bytes', 'MODS': MODS, 'INDX': 'u32',
     'MTNM': 'char4', 'VTCK': Arr('fid'), 'DNAM': Arr('fid'), 'HCLF': Arr('fid'), 'TINL': 'u16',
     'PNAM': 'f32', 'UNAM': 'f32', 'ATKR': 'fid', 'ATKD': ATKD if 'ATKD' in dir() else 'bytes',
     'ATKE': 'zstr', 'GNAM': 'fid', 'NAM4': 'fid', 'NAM5': 'fid', 'NAM7': 'fid', 'ONAM': 'fid',
     'LNAM': 'fid', 'NAME': 'zstr', 'MTYP': 'fid', 'SPED': 'bytes', 'VNAM': 'u32', 'QNAM': 'fid',
     'UNES': 'fid', 'PHTN': 'zstr', 'PHWT': 'bytes', 'WKMV': 'fid', 'RNMV': 'fid', 'SWMV': 'fid',
     'FLMV': 'fid', 'SNMV': 'fid', 'SPMV': 'fid', 'HNAM': Arr('fid'), 'ENAM': Arr('fid'),
     'FTSM': 'fid', 'FTSF': 'fid', 'DFTM': 'fid', 'DFTF': 'fid', 'TINI': 'u16', 'TINT': 'zstr',
     'TINP': 'u16', 'TIND': 'fid', 'TINC': 'fid', 'TINV': 'f32', 'TIRS': 'u16', 'MPAI': 'u32',
     'MPAV': 'bytes', 'RPRM': 'fid', 'RPRF': 'fid', 'AHCM': 'fid', 'AHCF': 'fid', 'NAM8': 'fid',
     'RNAM': 'fid'})
RECORDS['RACE'].subs = RACE_SUBS
RECORDS['RACE'].notes = ('VTCK voice types (male, female); DNAM default hair; HNAM hairs; ENAM eyes; '
                         'DATA (stats, heights, weights) is kept raw.')


# Sequential state needed by context-dependent codecs (fed raw bytes).
STATE_HOOKS = {
    'PRKE': lambda b, st: st.__setitem__('prke_type', b[0] if b else None),
    'EPFT': lambda b, st: st.__setitem__('epft', b[0] if b else None),
}

# Subrecords that mean the same thing in (almost) every record type; used for
# record types that have no definition above.
GENERIC = rec({'EDID': 'zstr', 'VMAD': VMAD, 'OBND': OBND, 'FULL': 'lstr', 'DESC': 'lstr'},
              MODEL, KEYWORDS, CONDITIONS)

# ---------------------------------------------------------------------------
# counters kept in sync automatically: counter sig -> (item sig, size, mode)
#   mode 'array' = number of elements of the (single) item subrecord array
#   mode 'subs'  = number of item subrecords
COUNTERS = {
    'KSIZ': ('KWDA', 'u32', 'array'),
    'COCT': ('CNTO', 'u32', 'subs'),
    'LLCT': ('LVLO', 'u8', 'subs'),
    'SPCT': ('SPLO', 'u32', 'subs'),
    'PRKZ': ('PRKR', 'u32', 'subs'),
}
