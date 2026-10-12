"""Tests for the bethesda-esp skill (stdlib only: python -m unittest discover tests).

Fixtures in tests/fixtures were written by Mutagen (an independent C#
implementation of the plugin format), see tests/README.md.
"""

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, '..', 'skills', 'bethesda-esp', 'scripts')
FIX = os.path.join(HERE, 'fixtures')
sys.path.insert(0, SCRIPTS)

from esplib import Plugin, LoadOrder, decode_record, ops, EspError  # noqa: E402
from esplib.codec import format_formid, iter_formids                 # noqa: E402
from esplib.fields import record_def                                 # noqa: E402
from esplib.strings import BSA, StringTables                         # noqa: E402

ESP = os.path.join(SCRIPTS, 'esp.py')


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def fields(rec, plugin):
    """{sig: [values...]} with FormIDs turned into FormKey strings."""
    from esplib.fields import to_jsonable
    out = {}
    for d in decode_record(rec, plugin):
        out.setdefault(d.sig, []).append(to_jsonable(d.value, plugin))
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='esptest-')
        for name in os.listdir(FIX):
            src = os.path.join(FIX, name)
            dst = os.path.join(self.tmp, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy(src, dst)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def p(self, *parts):
        return os.path.join(self.tmp, *parts)

    def lo(self, sub=''):
        return LoadOrder(self.p(sub) if sub else self.tmp)

    def cli(self, *args, ok=True):
        r = subprocess.run([sys.executable, ESP, *args], cwd=self.tmp, capture_output=True,
                           encoding='utf-8', errors='replace')
        if ok and r.returncode != 0:
            self.fail(f'esp.py {" ".join(args)} failed:\n{r.stdout}\n{r.stderr}')
        return r


class TestFormat(Base):
    def test_roundtrip_byte_identical(self):
        for root, _, files in os.walk(self.tmp):
            for f in files:
                if f.lower().endswith(('.esp', '.esm', '.esl')):
                    path = os.path.join(root, f)
                    with open(path, 'rb') as fh:
                        orig = fh.read()
                    self.assertEqual(Plugin.load(path).to_bytes(), orig, f)

    def test_known_subrecords_decode(self):
        for name in ('TestMaster.esm', 'ModA.esp', 'ModB.esp'):
            p = Plugin.load(self.p(name))
            for r in p.records():
                rdef = record_def(r.sig)
                for d in decode_record(r, p):
                    if d.sig in rdef.subs:
                        self.assertTrue(d.ok, f'{name} {r.sig}.{d.sig}: {d.error}')

    def test_values(self):
        lo = self.lo()
        p = lo.add(self.p('TestMaster.esm'))
        w = fields(p.find_edid('IronSword'), p)
        self.assertEqual(w['DATA'][0], {'value': 25, 'weight': 9.0, 'damage': 7})
        self.assertEqual(w['KWDA'][0], ['000800:TestMaster.esm', '000802:TestMaster.esm'])
        self.assertEqual(w['FULL'][0], 'Iron Sword')
        props = {x['name']: x['value'] for x in w['VMAD'][0]['scripts'][0]['properties']}
        self.assertEqual(props['Count'], 3)
        self.assertEqual(props['Gold']['form'], '000809:TestMaster.esm')
        gm = {r.edid: fields(r, p)['DATA'][0] for r in p.records('GMST')}
        self.assertEqual(gm, {'fTestSetting': 1.5, 'iTestSetting': 7, 'sTestSetting': 'Hello'})
        cell = p.find_edid('TestCell')
        self.assertEqual(cell.parent.label_int, 1)              # sub-block 1
        self.assertEqual(cell.parent.parent.label_int, 5)       # block 5 (0x8A7 = 2215)

    def test_header_and_masters(self):
        p = Plugin.load(self.p('ModB.esp'))
        self.assertEqual(p.masters, ['OtherMaster.esm', 'TestMaster.esm'])
        self.assertFalse(p.is_esm)
        self.assertTrue(Plugin.load(self.p('TestMaster.esm')).is_esm)


class TestPatching(Base):
    def test_copy_override_remaps_formids(self):
        lo = self.lo()
        b = lo.add(self.p('ModB.esp'))
        a = lo.add(self.p('ModA.esp'))
        patch = Plugin.new('Patch.esp', b.masters + [b.name])
        patch.path = self.p('Patch.esp')
        lo.add(patch)
        ops.copy_record(lo, b, b.find_edid('IronSword'), patch)
        ops.copy_record(lo, a, a.find_edid('LItemWeaponSwords'), patch)    # ModA has other masters
        ops.copy_record(lo, a, a.find_edid('TestChestRef'), patch)         # needs parent CELL
        patch.save(backup=False)
        p = Plugin.load(self.p('Patch.esp'))
        self.assertEqual(p.masters, ['OtherMaster.esm', 'TestMaster.esm', 'ModB.esp', 'ModA.esp'])
        w = fields(p.find_edid('IronSword'), p)
        self.assertEqual(w['KWDA'][0], ['000800:TestMaster.esm', '000800:OtherMaster.esm'])
        self.assertEqual(w['DATA'][0]['value'], 50)
        lv = fields(p.find_edid('LItemWeaponSwords'), p)
        self.assertEqual([e['reference'] for e in lv['LVLO']],
                         ['00080E:TestMaster.esm', '00080F:TestMaster.esm', '000800:ModA.esp'])
        ref = p.find_edid('TestChestRef')
        self.assertEqual(ref.parent.gtype, 8)                       # persistent children
        self.assertEqual(p.find(ref.parent.label_formid).edid, 'TestCell')
        self.assertEqual(fields(ref, p)['DATA'][0]['pos_x'], 11.0)

    def test_merge(self):
        r = self.cli('merge', 'ModA.esp', 'ModB.esp', '--into', 'Merged.esp')
        self.assertIn('LVLO', r.stdout)
        p = Plugin.load(self.p('Merged.esp'))
        lv = fields(p.find_edid('LItemWeaponSwords'), p)
        self.assertEqual(sorted(e['reference'] for e in lv['LVLO']),
                         sorted(['00080E:TestMaster.esm', '000800:ModA.esp', '000800:ModB.esp']))
        self.assertEqual(lv['LLCT'][0], 3)
        w = fields(p.find_edid('IronSword'), p)
        self.assertEqual(sorted(w['KWDA'][0]), sorted(['000800:TestMaster.esm', '000801:TestMaster.esm',
                                                       '000800:OtherMaster.esm']))
        self.assertEqual(w['DATA'][0], {'value': 50, 'weight': 9.0, 'damage': 10})   # field-level merge
        self.assertEqual(w['KSIZ'][0], 3)

    def test_conflicts_and_itm(self):
        r = self.cli('conflicts', 'ModA.esp', 'ModB.esp', '--details')
        self.assertIn('IronSword', r.stdout)
        self.assertIn('-- 2 conflicting record(s)', r.stdout)
        r = self.cli('itm', 'ModA.esp')
        self.assertIn('Gold001', r.stdout)
        self.cli('itm', 'ModA.esp', '--clean')
        self.assertIsNone(Plugin.load(self.p('ModA.esp')).find_edid('Gold001'))
        self.assertTrue(os.path.exists(self.p('ModA.esp.bak')))

    def test_add_master_keeps_own_formids(self):
        lo = self.lo()
        a = lo.add(self.p('ModA.esp'))
        ops.add_masters(a, ['OtherMaster.esm'], lo)
        a.save(backup=False)
        p = Plugin.load(self.p('ModA.esp'))
        self.assertEqual(p.masters, ['TestMaster.esm', 'OtherMaster.esm'])
        sword = p.find_edid('ModASword')
        self.assertEqual(sword.formid >> 24, 2)
        lv = fields(p.find_edid('LItemWeaponSwords'), p)
        self.assertIn('000800:ModA.esp', [e['reference'] for e in lv['LVLO']])

    def test_clean_masters(self):
        lo = self.lo()
        a = lo.add(self.p('ModA.esp'))
        ops.add_masters(a, ['OtherMaster.esm'], lo)
        self.assertEqual(ops.clean_masters(a), ['OtherMaster.esm'])
        self.assertEqual(a.masters, ['TestMaster.esm'])
        self.assertEqual(a.find_edid('ModASword').formid >> 24, 1)


class TestEditing(Base):
    def test_set(self):
        self.cli('set', 'ModA.esp', 'IronSword', 'DATA.damage=15', 'FULL=Sharp Iron Sword',
                 'KWDA-=VendorItemWeapon', 'DNAM.flags=NonPlayable|CantDrop', 'DNAM.speed=1.25',
                 '@flags+=Ignored')
        self.cli('set', 'ModA.esp', 'TestChest', 'CNTO+=Gold001', 'CNTO#0.count=50', '--remove', 'CNTO#1')
        self.cli('set', 'ModA.esp', 'LItemWeaponSwords',
                 'LVLO+={"level": 9, "reference": "SteelSword", "count": 3}', 'LVLO-=ModASword', 'LVLD=25')
        p = Plugin.load(self.p('ModA.esp'))
        sword = p.find_edid('IronSword')
        w = fields(sword, p)
        self.assertEqual(w['DATA'][0]['damage'], 15)
        self.assertEqual(w['FULL'][0], 'Sharp Iron Sword')
        self.assertEqual(w['KWDA'][0], ['000800:TestMaster.esm', '000801:TestMaster.esm'])
        self.assertEqual(w['KSIZ'][0], 2)
        self.assertEqual(sorted(w['DNAM'][0]['flags']), ['CantDrop', 'NonPlayable'])
        self.assertEqual(w['DNAM'][0]['speed'], 1.25)
        self.assertTrue(sword.flags & 0x1000)
        c = fields(p.find_edid('TestChest'), p)
        self.assertEqual([(e['item'], e['count']) for e in c['CNTO']],
                         [('00080A:TestMaster.esm', 50), ('00080B:TestMaster.esm', 3), ('000809:TestMaster.esm', 1)])
        self.assertEqual(c['COCT'][0], 3)
        lv = fields(p.find_edid('LItemWeaponSwords'), p)
        self.assertEqual(lv['LVLD'][0], 25)
        self.assertEqual([(e['level'], e['reference'], e['count']) for e in lv['LVLO']],
                         [(1, '00080E:TestMaster.esm', 1), (5, '00080F:TestMaster.esm', 1),
                          (9, '00080F:TestMaster.esm', 3)])
        self.assertEqual(lv['LLCT'][0], 3)

    def test_bad_edit_is_rejected(self):
        r = self.cli('set', 'ModA.esp', 'IronSword', 'DATA.nonsense=1', ok=False)
        self.assertNotEqual(r.returncode, 0)
        r = self.cli('set', 'ModA.esp', 'IronSword', 'KWDA+=NoSuchKeyword', ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_add_new_records(self):
        self.cli('add', 'ModA.esp', 'KYWD', '--edid', 'MyKeyword')
        self.cli('add', 'ModA.esp', 'MISC', '--edid', 'MyGem', 'FULL=Shiny Gem',
                 'DATA={"value": 250, "weight": 0.5}', 'KWDA+=MyKeyword')
        self.cli('add', 'ModA.esp', 'COBJ', '--edid', 'RecipeMyGem',
                 'CNTO+={"item":"IngotIron","count":2}', 'CNAM=MyGem', 'BNAM=CraftingSmithingForge', 'NAM1=1')
        p = Plugin.load(self.p('ModA.esp'))
        gem = p.find_edid('MyGem')
        self.assertEqual(gem.formid >> 24, 1)
        g = fields(gem, p)
        self.assertEqual(g['DATA'][0], {'value': 250, 'weight': 0.5})
        self.assertEqual(g['KWDA'][0], [format_formid(p.find_edid('MyKeyword').formid, p)])
        c = fields(p.find_edid('RecipeMyGem'), p)
        self.assertEqual(c['CNAM'][0], format_formid(gem.formid, p))
        self.assertEqual(c['COCT'][0], 1)
        self.assertGreater(p.next_object_id, max(r.formid & 0xFFFFFF for r in p.records() if not p.is_override(r)))

    def test_delete(self):
        r = self.cli('delete', 'ModA.esp', 'ModASword', ok=False)
        self.assertEqual(r.returncode, 2)                    # referenced by the leveled list
        self.cli('delete', 'ModA.esp', 'ModASword', '--force')
        self.assertIsNone(Plugin.load(self.p('ModA.esp')).find_edid('ModASword'))
        self.cli('delete', 'ModA.esp', 'TestChestRef', '--disable')
        p = Plugin.load(self.p('ModA.esp'))
        ref = p.find_edid('TestChestRef')
        self.assertTrue(ref.flags & 0x800)
        f = fields(ref, p)
        self.assertEqual(f['XESP'][0]['reference'], '000014:Skyrim.esm')
        self.assertEqual(f['DATA'][0]['pos_z'], -30000.0)

    def test_export_put_roundtrip(self):
        out = self.cli('show', 'ModA.esp', 'IronSword', '--json').stdout
        j = json.loads(out)
        for f in j['fields']:
            if 'DATA' in f:
                f['DATA']['damage'] = 33
        j['formid'] = 'new'
        for f in j['fields']:
            if 'EDID' in f:
                f['EDID'] = 'IronSwordClone'
        with open(self.p('rec.json'), 'w') as fh:
            json.dump(j, fh)
        self.cli('put', 'ModA.esp', 'rec.json')
        p = Plugin.load(self.p('ModA.esp'))
        clone = p.find_edid('IronSwordClone')
        self.assertFalse(p.is_override(clone))
        self.assertEqual(fields(clone, p)['DATA'][0]['damage'], 33)
        self.assertEqual(fields(clone, p)['VMAD'][0], fields(p.find_edid('IronSword'), p)['VMAD'][0])

    def test_compact_and_esl(self):
        lo = self.lo()
        p = Plugin.new('Big.esp', ['TestMaster.esm'])
        p.path = self.p('Big.esp')
        lo.add(p)
        p.set_hedr(version=1.7, next_object_id=0x12340)
        kw = ops.new_record(p, 'KYWD', 'BigKeyword', lo=lo)
        ops.new_record(p, 'MISC', 'BigItem', [('KSIZ', 1), ('KWDA', [kw.formid])], lo=lo)
        p.save(backup=False)
        self.assertIn('outside 800-FFF', self.cli('esl', 'Big.esp').stdout)
        self.cli('compact', 'Big.esp')
        self.cli('esl', 'Big.esp', '--flag')
        q = Plugin.load(self.p('Big.esp'))
        self.assertTrue(q.is_esl)
        item = q.find_edid('BigItem')
        self.assertTrue(0x800 <= (item.formid & 0xFFFFFF) <= 0xFFF)
        self.assertEqual(fields(item, q)['KWDA'][0], [format_formid(q.find_edid('BigKeyword').formid, q)])


class TestStrings(Base):
    def test_localized_loose(self):
        lo = self.lo('loc')
        p = lo.add(self.p('loc', 'LocMaster.esm'))
        self.assertTrue(p.is_localized)
        st = lo.strings_for(p)
        names = {r.edid: st.get(int.from_bytes(r.get('FULL').data, 'little')) for r in p.records() if r.get('FULL')}
        self.assertEqual(names['LocSword'], 'Localized Sword')
        r = self.cli('find', 'loc/LocMaster.esm', '--text', 'upon a time')
        self.assertIn('LocBook', r.stdout)

    def test_strings_from_bsa(self):
        b = BSA(self.p('bsa', 'Skyrim - Interface.bsa'))
        self.assertEqual(b.version, 105)
        self.assertTrue(b.read('interface\\readme.txt').startswith(b'Test file stored LZ4'))
        st = StringTables.find(self.p('bsa', 'LocMaster.esm'))
        self.assertIsNotNone(st)
        r = self.cli('list', 'bsa/LocMaster.esm')
        self.assertIn('"Localized Sword"', r.stdout)

    def test_copy_from_localized_and_delocalize(self):
        self.cli('copy', 'loc/LocMaster.esm', 'LocSword', 'LocBook', '--to', 'loc/LocPatch.esp', '--create')
        p = Plugin.load(self.p('loc', 'LocPatch.esp'))
        self.assertFalse(p.is_localized)
        self.assertEqual(fields(p.find_edid('LocBook'), p)['DESC'][0], 'Once upon a time... été')
        self.cli('delocalize', 'loc/LocMaster.esm', '-o', 'loc/Deloc.esm')
        d = Plugin.load(self.p('loc', 'Deloc.esm'))
        self.assertFalse(d.is_localized)
        infos = [fields(r, d) for r in d.records('INFO')]
        self.assertEqual(infos[0]['NAM1'][0], 'Localized response text.')


class TestCli(Base):
    def test_read_commands(self):
        for args in (['info', 'ModB.esp'], ['info', 'ModB.esp', '--json'], ['list', 'TestMaster.esm', '-t', 'WEAP'],
                     ['show', 'TestMaster.esm', 'IronSword', 'TestNpc', 'TestChestRef'],
                     ['show', 'TestMaster.esm', '00080E:TestMaster.esm', '--raw'],
                     ['find', 'TestMaster.esm', 'ModA.esp', '--ref', 'IngotIron'],
                     ['schema'], ['schema', 'NPC_'], ['tree', 'TestMaster.esm', '--records'],
                     ['verify', 'TestMaster.esm', '--roundtrip'], ['diff', 'ModA.esp', 'ModB.esp'],
                     ['masters', 'ModB.esp'], ['strings', 'loc/LocMaster.esm', '--search', 'Sword'],
                     ['bsa', 'bsa/Skyrim - Interface.bsa'], ['export', 'ModA.esp', '-t', 'WEAP']):
            self.cli(*args)
        r = self.cli('find', 'TestMaster.esm', 'ModA.esp', '--ref', 'IngotIron')
        self.assertIn('RecipeIronSword', r.stdout)
        self.assertIn('IronSword', r.stdout)     # script property


class TestApiHelpers(Base):
    """Header-only loading, the Plugin() guard and FormKeys (cross-plugin identity)."""

    def test_load_header_matches_full_load(self):
        for name in ('TestMaster.esm', 'OtherMaster.esm', 'ModA.esp', 'ModB.esp', 'loc/LocMaster.esm'):
            full, head = Plugin.load(self.p(name)), Plugin.load_header(self.p(name))
            self.assertTrue(head.header_only)
            self.assertFalse(full.header_only)
            for attr in ('name', 'path', 'masters', 'is_esm', 'is_esl', 'is_light', 'is_master_like',
                         'is_localized', 'hedr_version', 'next_object_id'):
                self.assertEqual(getattr(head, attr), getattr(full, attr), (name, attr))
            self.assertEqual(head.header_string('CNAM'), full.header_string('CNAM'))
            self.assertEqual(head.header.version, full.header.version)

    def test_header_only_refuses_records_and_save(self):
        path = self.p('ModA.esp')
        before = read_bytes(path)
        h = Plugin.load_header(path)
        for fn in (lambda: list(h.records()), lambda: h.find(0x800), lambda: h.find_edid('IronSword'),
                   lambda: h.save(), lambda: h.to_bytes()):
            with self.assertRaises(EspError) as cm:
                fn()
            self.assertIn('Plugin.load(path)', str(cm.exception))
        self.assertEqual(read_bytes(path), before)                 # nothing written
        self.assertFalse(os.path.exists(path + '.bak'))

    def test_load_header_rejects_bad_files(self):
        with open(self.p('junk.esp'), 'wb') as f:
            f.write(b'not a plugin at all, just text')
        with self.assertRaises(EspError):
            Plugin.load_header(self.p('junk.esp'))
        data = read_bytes(self.p('ModA.esp'))
        with open(self.p('cut.esp'), 'wb') as f:
            f.write(data[:40])                                      # TES4 header cut off
        with self.assertRaises(EspError):
            Plugin.load_header(self.p('cut.esp'))

    def test_plugin_constructor_guard(self):
        for bad in (self.p('ModA.esp'), 'Data/ModA.esp', 'Data\\ModA.esp'):
            with self.assertRaises(ValueError) as cm:
                Plugin(bad)
            self.assertIn('Plugin.load(path)', str(cm.exception))
        p = Plugin('ModA.esp')                                      # a name is fine: nothing read yet
        for fn in (lambda: p.masters, lambda: p.is_esl, lambda: p.is_esm, lambda: p.hedr_version):
            with self.assertRaises(EspError) as cm:
                fn()
            self.assertIn('Plugin.load(path)', str(cm.exception))
        old = os.getcwd()
        os.chdir(self.tmp)                                          # a same-named file in the cwd
        try:
            n = Plugin.new('ModA.esp', ['TestMaster.esm'])
            self.assertEqual(n.masters, ['TestMaster.esm'])
            self.assertEqual(Plugin.load('ModA.esp').name, 'ModA.esp')
        finally:
            os.chdir(old)

    def test_formkeys_across_master_lists(self):
        from esplib import FormKey
        a, b = Plugin.load(self.p('ModA.esp')), Plugin.load(self.p('ModB.esp'))
        self.assertEqual(a.masters, ['TestMaster.esm'])
        self.assertEqual(b.masters, ['OtherMaster.esm', 'TestMaster.esm'])
        wa = next(r for r in a.records('WEAP') if a.is_override(r))
        wb = b.find_edid(wa.edid)
        self.assertNotEqual(wa.formid, wb.formid)                  # 00xxxxxx vs 01xxxxxx
        self.assertEqual(wa.formid >> 24, 0)
        self.assertEqual(wb.formid >> 24, 1)
        self.assertEqual(wa.local_id, wb.local_id)
        self.assertEqual(wa.object_id, wa.formid & 0xFFFFFF)
        self.assertEqual(wa.master_name(), 'TestMaster.esm')
        self.assertEqual(wb.master_name(b), 'TestMaster.esm')
        self.assertTrue(wa.is_override)
        self.assertEqual(wa.formkey, wb.formkey)
        self.assertEqual(hash(wa.formkey), hash(wb.formkey))
        self.assertIs(b.find(wa.formkey), wb)                      # look up another plugin's record
        self.assertIs(b.find(str(wa.formkey)), wb)
        self.assertEqual(b.local_formid(wa.formkey), wb.formid)
        # new records: defined by the plugin itself
        new_a = [r for r in a.records() if not r.is_override]
        self.assertTrue(new_a)
        self.assertTrue(all(r.formkey.plugin == 'ModA.esp' for r in new_a))
        self.assertIsNone(b.find(new_a[0].formkey))
        self.assertIsNone(b.local_formid(new_a[0].formkey))         # ModA is not a master of ModB
        # shared references between the two plugins
        both = {r.formkey for r in a.records()} & {r.formkey for r in b.records()}
        self.assertIn(wa.formkey, both)
        # FormIDs inside fields
        kw = next(d for d in decode_record(wb, b) if d.sig == 'KWDA').value
        self.assertTrue(all(b.formkey(k).plugin in ('TestMaster.esm', 'OtherMaster.esm') for k in kw))
        self.assertIsNone(b.formkey(0))
        self.assertIsNone(b.formkey(0x05000800))                    # past the master list
        # FormKey value semantics
        fk = FormKey(0x12EB7, 'Skyrim.esm')
        self.assertEqual(str(fk), '012EB7:Skyrim.esm')
        self.assertEqual(fk, FormKey.parse('012EB7:skyrim.ESM'))
        self.assertEqual(fk, FormKey.parse('Skyrim.esm:012EB7'))
        self.assertEqual(fk, (0x12EB7, 'SKYRIM.ESM'))
        self.assertEqual(len({fk, FormKey(0x12EB7, 'skyrim.esm')}), 1)
        import copy
        import pickle
        self.assertEqual(pickle.loads(pickle.dumps(fk)), fk)
        self.assertEqual(copy.deepcopy(fk), fk)
        objid, owner = fk                                          # still a plain pair
        self.assertEqual((objid, owner), (0x12EB7, 'Skyrim.esm'))
        with self.assertRaises(EspError):
            FormKey.parse('IronSword')

    def test_master_cache_follows_master_edits(self):
        b = Plugin.load(self.p('ModB.esp'))
        w = next(r for r in b.records('WEAP') if b.is_override(r))
        self.assertEqual(w.master_name(), 'TestMaster.esm')
        b.set_masters(['OtherMaster.esm', 'Renamed.esm'])           # same length, no FormID remap
        self.assertEqual(w.master_name(), 'Renamed.esm')
        self.assertEqual(w.formkey.plugin, 'Renamed.esm')
        b.add_master('Third.esm')
        self.assertEqual(b.formid_owner(2 << 24 | 0x800), 'Third.esm')
        self.assertEqual(b.formid_owner(3 << 24 | 0x800), 'ModB.esp')

    def test_conflicts_match_master_names_case_insensitively(self):
        lo = self.lo()
        tm = lo.add(self.p('TestMaster.esm'))
        low = Plugin.new('Lower.esp', ['testmaster.esm'])           # master written in lower case
        low.path = self.p('Lower.esp')
        lo.add(low)
        a = lo.add(self.p('ModA.esp'))
        wa = next(r for r in a.records('WEAP') if a.is_override(r))
        new, _ = ops.copy_record(lo, tm, tm.find(lo.local_fid(tm, *lo.formkey(a, wa.formid))), low)
        low.save(backup=False)
        self.assertEqual(lo.formkey(low, new.formid), lo.formkey(a, wa.formid))
        r = self.cli('conflicts', 'ModA.esp', 'Lower.esp')
        self.assertIn(wa.edid, r.stdout)


class TestCliArgumentOrder(Base):
    def test_file_before_command(self):
        want = self.cli('info', 'ModA.esp').stdout
        self.assertIn('ModA.esp', want)
        self.assertEqual(self.cli('ModA.esp', 'info').stdout, want)
        self.assertEqual(self.cli('ModA.esp').stdout, want)                      # lone file: info
        self.assertEqual(self.cli('--data', self.tmp, 'info', 'ModA.esp').stdout,
                         self.cli('info', 'ModA.esp', '--data', self.tmp).stdout)
        self.assertEqual(self.cli('ModB.esp', 'list', '-t', 'WEAP').stdout,
                         self.cli('list', 'ModB.esp', '-t', 'WEAP').stdout)
        r = self.cli('ModA.esp', 'nosuchcommand', ok=False)
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
