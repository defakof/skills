"""Build tests/fixtures/lo: a small but realistic Skyrim SE load order that
exercises the load-order and conflict analysis (stdlib + esplib only).

    python tests/tools/make_lo_fixture.py [out_dir]

The plugins are tiny and use the real file names of the base game so the
analysis treats them like the real thing.
"""

import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'skills', 'bethesda-esp', 'scripts'))

from esplib import Plugin, LoadOrder, ops                           # noqa: E402
from esplib.core import Record, Subrecord, FLAG_DELETED, FLAG_ESM   # noqa: E402
from esplib.fields import encode_items                              # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'fixtures', 'lo'))
DATA = os.path.join(OUT, 'Data')


def new_plugin(lo, name, masters, esm=False, esl=False, version=1.7):
    p = Plugin.new(name, masters, esm=esm, esl=esl, hedr_version=version)
    p.path = os.path.join(DATA, name)
    lo.add(p)
    return p


def rec(lo, p, sig, edid, fields=()):
    return ops.new_record(p, sig, edid, list(fields), lo=lo)


def edit(lo, p, r, *edits):
    ops.apply_edits(lo, p, r, [(a, op, b) for a, op, b in edits])


def copy(lo, src, edid, dst):
    r = src.find_edid(edid)
    new, _ = ops.copy_record(lo, src, r, dst)
    return new


def add_navmesh(p, cell, payload=b'\x01\x02\x03\x04', deleted=False, formid=None):
    """Attach a minimal NAVM record (opaque NVNM data) to a cell in plugin p."""
    nv = Record('NAVM', formid or ops.allocate_formid(p), FLAG_DELETED if deleted else 0,
                [Subrecord('NVNM', payload)] if not deleted else [], 44)
    nv._raw = None
    ops.place_record(p, nv, {'cell': cell.formid, 'child_type': 9})
    return nv


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(DATA)
    lo = LoadOrder(DATA)

    # ---- Skyrim.esm -------------------------------------------------------
    sky = new_plugin(lo, 'Skyrim.esm', [], esm=True)
    kw_iron = rec(lo, sky, 'KYWD', 'WeapMaterialIron')
    kw_steel = rec(lo, sky, 'KYWD', 'WeapMaterialSteel')
    rec(lo, sky, 'KYWD', 'VendorItemWeapon')
    iron = rec(lo, sky, 'WEAP', 'IronSword', [('FULL', 'Iron Sword'), ('KSIZ', 1), ('KWDA', [kw_iron.formid]),
                                              ('DATA', {'value': 25, 'weight': 9.0, 'damage': 7})])
    steel = rec(lo, sky, 'WEAP', 'SteelSword', [('FULL', 'Steel Sword'), ('KSIZ', 1), ('KWDA', [kw_steel.formid]),
                                                ('DATA', {'value': 45, 'weight': 10.0, 'damage': 8})])
    rec(lo, sky, 'MISC', 'Gold001', [('FULL', 'Gold'), ('DATA', {'value': 1, 'weight': 0.0})])
    lvli = rec(lo, sky, 'LVLI', 'LItemWeaponSwords', [('LVLD', 0), ('LVLF', {'flags': ['CalcFromAllLevels']}),
                                                      ('LVLO', {'level': 1, 'reference': iron.formid, 'count': 1}),
                                                      ('LVLO', {'level': 5, 'reference': steel.formid, 'count': 1})])
    race = rec(lo, sky, 'RACE', 'NordRace', [('FULL', 'Nord')])
    hair = rec(lo, sky, 'HDPT', 'HairMaleNord01')
    npc = rec(lo, sky, 'NPC_', 'Ulfric', [('FULL', 'Ulfric Stormcloak'), ('RNAM', race.formid),
                                         ('ACBS', {'flags': ['Essential', 'Unique'], 'level': 40}),
                                         ('PNAM', hair.formid), ('NAM6', 1.0), ('NAM7', 50.0)])
    rec(lo, sky, 'GMST', 'fJumpHeightMin', [('DATA', 76.0)])
    cell = rec(lo, sky, 'CELL', 'WhiterunBanneredMare', [('FULL', 'The Bannered Mare'), ('DATA', {'flags': ['Interior']})])
    stat = rec(lo, sky, 'STAT', 'BarrelStatic', [('MODL', 'Clutter\\Barrel.nif')])
    ref = Record('REFR', ops.allocate_formid(sky), 0, encode_items('REFR', [
        ('NAME', stat.formid), ('DATA', {'pos_x': 1.0, 'pos_y': 2.0, 'pos_z': 3.0, 'rot_x': 0.0, 'rot_y': 0.0, 'rot_z': 0.0})], sky), 44)
    ref._raw = None
    ops.place_record(sky, ref, {'cell': cell.formid, 'child_type': 9})
    set_edid = ops.set_edid
    set_edid(ref, 'BannedMareBarrelRef', sky)
    navm = add_navmesh(sky, cell)
    quest = rec(lo, sky, 'QUST', 'MQ101', [('FULL', 'Unbound')])
    sky.save(backup=False)

    # ---- Update.esm: fixes IronSword ------------------------------------------
    upd = new_plugin(lo, 'Update.esm', ['Skyrim.esm'], esm=True)
    u_iron = copy(lo, sky, 'IronSword', upd)
    edit(lo, upd, u_iron, ('DATA.weight', '=', '8.5'))
    upd.save(backup=False)

    # ---- USSEP (ESM-flagged .esp) ------------------------------------------------
    us = new_plugin(lo, 'Unofficial Skyrim Special Edition Patch.esp', ['Skyrim.esm', 'Update.esm'], esm=True)
    us_iron = copy(lo, upd, 'IronSword', us)
    edit(lo, us, us_iron, ('KWDA', '+=', 'VendorItemWeapon'))
    us_npc = copy(lo, sky, 'Ulfric', us)
    edit(lo, us, us_npc, ('ACBS.level', '=', '42'))
    copy(lo, sky, 'MQ101', us)
    us.save(backup=False)

    # ---- ModA.esp: weapons + leveled list + NPC stats + cell + navmesh ------
    a = new_plugin(lo, 'ModA.esp', ['Skyrim.esm'])
    a_iron = copy(lo, sky, 'IronSword', a)                         # no Update/USSEP master: reverts their fixes
    edit(lo, a, a_iron, ('DATA.damage', '=', '9'))
    a_sword = rec(lo, a, 'WEAP', 'ModASword', [('FULL', 'ModA Sword'), ('DATA', {'value': 99, 'weight': 5.0, 'damage': 11})])
    a_lvl = copy(lo, sky, 'LItemWeaponSwords', a)
    edit(lo, a, a_lvl, ('LVLO', '+=', '{"level": 3, "reference": "ModASword", "count": 1}'))
    a_npc = copy(lo, sky, 'Ulfric', a)
    edit(lo, a, a_npc, ('ACBS.level', '=', '50'))
    a_cell = copy(lo, sky, 'WhiterunBanneredMare', a)
    edit(lo, a, a_cell, ('XCLW', '=', '-200'))
    a_nav = copy(lo, sky, 'BannedMareBarrelRef', a)                 # parent cell copied along
    edit(lo, a, a_nav, ('DATA.pos_x', '=', '10'))
    nav_a = Record('NAVM', navm.formid, 0, [Subrecord('NVNM', b'\x0a\x0b')], 44)
    nav_a._raw = None
    ops.place_record(a, nav_a, {'cell': a_cell.formid, 'child_type': 9})
    rec(lo, a, 'GLOB', 'SharedName', [('FNAM', 'f'), ('FLTV', 1.0)])   # EditorID also used by EdidDupe.esp
    a_gmst = copy(lo, sky, 'fJumpHeightMin', a)
    edit(lo, a, a_gmst, ('DATA', '=', '100'))
    a.save(backup=False)

    # ---- ModB.esp: conflicts with ModA ------------------------------------------
    b = new_plugin(lo, 'ModB.esp', ['Skyrim.esm', 'Update.esm', 'Unofficial Skyrim Special Edition Patch.esp'])
    b_iron = copy(lo, us, 'IronSword', b)
    edit(lo, b, b_iron, ('DATA.value', '=', '60'))
    b_sword = rec(lo, b, 'WEAP', 'ModBSword', [('FULL', 'ModB Sword'), ('DATA', {'value': 77, 'weight': 6.0, 'damage': 12})])
    b_lvl = copy(lo, sky, 'LItemWeaponSwords', b)
    edit(lo, b, b_lvl, ('LVLO', '-=', 'SteelSword'), ('LVLO', '+=', '{"level": 4, "reference": "ModBSword", "count": 2}'))
    b_npc = copy(lo, us, 'Ulfric', b)
    hair2 = rec(lo, b, 'HDPT', 'ModBHair')
    edit(lo, b, b_npc, ('PNAM', '=', 'ModBHair'), ('NAM6', '=', '1.05'))       # visual change only
    b_cell = copy(lo, sky, 'WhiterunBanneredMare', b)
    edit(lo, b, b_cell, ('FULL', '=', 'The Bannered Mare Inn'))
    nav_b = Record('NAVM', navm.formid, 0, [Subrecord('NVNM', b'\x0c\x0d')], 44)
    nav_b._raw = None
    ops.place_record(b, nav_b, {'cell': b_cell.formid, 'child_type': 9})
    b_q = copy(lo, us, 'MQ101', b)
    edit(lo, b, b_q, ('FULL', '=', 'Unbound (ModB)'))
    b.save(backup=False)

    # ---- ModA + ModB patch -------------------------------------------------------------
    pt = new_plugin(lo, 'ModA - ModB Patch.esp', ['Skyrim.esm', 'Update.esm', 'Unofficial Skyrim Special Edition Patch.esp',
                                                 'ModA.esp', 'ModB.esp'])
    p_lvl = copy(lo, b, 'LItemWeaponSwords', pt)
    edit(lo, pt, p_lvl, ('LVLO', '+=', '{"level": 3, "reference": "ModASword", "count": 1}'))
    pt.save(backup=False)

    # ---- SmallTweak.esp: one record ModA also changes (overlap rule) ------------------
    st = new_plugin(lo, 'SmallTweak.esp', ['Skyrim.esm'])
    st_g = copy(lo, sky, 'fJumpHeightMin', st)
    edit(lo, st, st_g, ('DATA', '=', '120'))
    st.save(backup=False)

    # ---- light plugins ------------------------------------------------------------------
    light = new_plugin(lo, 'LightMod.esp', ['Skyrim.esm'], esl=True)
    rec(lo, light, 'MISC', 'LightGem', [('FULL', 'Light Gem'), ('DATA', {'value': 10, 'weight': 0.1})])
    light.save(backup=False)
    bad = new_plugin(lo, 'BadLight.esp', ['Skyrim.esm'], esl=True)
    bad.set_hedr(next_object_id=0x1000)
    rec(lo, bad, 'MISC', 'BadLightGem', [('FULL', 'Bad Gem')])
    bad.save(backup=False)

    # ---- ESLify candidates ----------------------------------------------------------------
    e1 = new_plugin(lo, 'Eslable.esp', ['Skyrim.esm'])
    rec(lo, e1, 'MISC', 'EslableGem', [('FULL', 'Gem')])
    rec(lo, e1, 'KYWD', 'EslableKeyword')
    e1.save(backup=False)
    e2 = new_plugin(lo, 'NeedsCompact.esp', ['Skyrim.esm'])
    e2.set_hedr(next_object_id=0x5000)
    rec(lo, e2, 'NPC_', 'CompactNpc', [('FULL', 'Compact Npc'), ('RNAM', race.formid)])
    rec(lo, e2, 'MISC', 'CompactGem', [('FULL', 'Gem 2')])
    e2.save(backup=False)
    dep = new_plugin(lo, 'NeedsCompact - Addon.esp', ['Skyrim.esm', 'NeedsCompact.esp'])
    dep_npc = copy(lo, e2, 'CompactNpc', dep)
    edit(lo, dep, dep_npc, ('FULL', '=', 'Renamed'))
    dep.save(backup=False)
    with open(os.path.join(DATA, 'NeedsCompact_DISTR.ini'), 'w') as f:
        f.write('Keyword = SomeKeyword|NPC|0x5001~NeedsCompact.esp\n')

    # ---- Skyrim LE plugin (header 0.94, form version 43) ------------------------------------
    le = new_plugin(lo, 'OldLE.esp', ['Skyrim.esm'], version=0.94)
    le_r = rec(lo, le, 'MISC', 'OldItem', [('FULL', 'Old Item')])
    le_r.version = 43
    le.header.version = 43
    le.save(backup=False)

    # ---- missing / inactive master, wrong order ---------------------------------------------
    mm = new_plugin(lo, 'MissingMaster.esp', ['Skyrim.esm', 'NotInstalled.esp'])
    mm.save(backup=False)
    im = new_plugin(lo, 'InactiveMaster.esm', ['Skyrim.esm'], esm=True)
    rec(lo, im, 'KYWD', 'InactiveKeyword')
    im.save(backup=False)
    ni = new_plugin(lo, 'NeedsInactive.esp', ['Skyrim.esm', 'InactiveMaster.esm'])
    ni.save(backup=False)
    wo = new_plugin(lo, 'WrongOrder.esp', ['Skyrim.esm', 'ModB.esp'])
    wo_s = copy(lo, b, 'ModBSword', wo)
    edit(lo, wo, wo_s, ('DATA.damage', '=', '13'))
    wo.save(backup=False)

    # ---- dirty plugin: ITM, deleted reference, deleted navmesh ----------------------------------
    d = new_plugin(lo, 'Dirty.esp', ['Skyrim.esm'])
    copy(lo, sky, 'Gold001', d)                                   # identical to master
    d_ref = copy(lo, sky, 'BannedMareBarrelRef', d)
    d_ref.flags |= FLAG_DELETED
    d_ref._subs = [s for s in d_ref.subrecords if s.sig == 'EDID']
    d_ref.touched()
    d_cell = d.find(cell.formid)
    dn = Record('NAVM', navm.formid, FLAG_DELETED, [], 44)
    dn._raw = None
    ops.place_record(d, dn, {'cell': d_cell.formid, 'child_type': 9})
    d.save(backup=False)

    # ---- duplicate EditorID, injected records --------------------------------------------------
    ed = new_plugin(lo, 'EdidDupe.esp', ['Skyrim.esm'])
    rec(lo, ed, 'GLOB', 'SharedName', [('FNAM', 'f'), ('FLTV', 2.0)])
    ed.save(backup=False)
    for nm in ('Injector1.esp', 'Injector2.esp'):
        inj = new_plugin(lo, nm, ['Skyrim.esm'])
        r = Record('MISC', 0x00ABCDEF, 0, encode_items('MISC', [('EDID', 'Injected' + nm[8]), ('FULL', 'Injected')], inj), 44)
        r._raw = None
        ops.place_record(inj, r, {})
        inj.save(backup=False)

    # ---- generated patch listed too early; ESM-flagged mod listed after ESPs; CC plugin ------
    bp = new_plugin(lo, 'Bashed Patch, 0.esp', ['Skyrim.esm', 'ModA.esp', 'ModB.esp'])
    bp_lvl = copy(lo, b, 'LItemWeaponSwords', bp)
    bp.save(backup=False)
    lm = new_plugin(lo, 'LateMaster.esm', ['Skyrim.esm'], esm=True)
    rec(lo, lm, 'KYWD', 'LateMasterKeyword')
    lm.save(backup=False)
    cc = new_plugin(lo, 'ccTestSSE001-Example.esl', ['Skyrim.esm'], esm=True, esl=True)
    rec(lo, cc, 'MISC', 'ccExampleItem', [('FULL', 'CC Item')])
    cc.save(backup=False)

    with open(os.path.join(OUT, 'Skyrim.ccc'), 'w') as f:
        f.write('ccTestSSE001-Example.esl\nccNotInstalled.esm\n')
    order = [
        ('Unofficial Skyrim Special Edition Patch.esp', True), ('InactiveMaster.esm', False),
        ('ModA.esp', True), ('SmallTweak.esp', True), ('Bashed Patch, 0.esp', True),
        ('WrongOrder.esp', True), ('ModB.esp', True), ('ModA - ModB Patch.esp', True),
        ('LightMod.esp', True), ('BadLight.esp', True), ('Eslable.esp', True), ('NeedsCompact.esp', True),
        ('NeedsCompact - Addon.esp', True), ('OldLE.esp', True), ('MissingMaster.esp', True),
        ('NeedsInactive.esp', True), ('Dirty.esp', True), ('EdidDupe.esp', True), ('Injector1.esp', True),
        ('Injector2.esp', True), ('LateMaster.esm', True), ('Removed.esp', True),
    ]
    with open(os.path.join(OUT, 'plugins.txt'), 'w') as f:
        f.write('# This file is used by Skyrim to keep track of your downloaded content.\n')
        for n, act in order:
            f.write(('*' if act else '') + n + '\n')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
