"""esplib - read, edit and write Bethesda plugins (.esp/.esm/.esl), Skyrim SE.

Quick use from Python:

    import sys; sys.path.insert(0, '<skill>/scripts')
    from esplib import Plugin, LoadOrder, decode_record, ops

    lo = LoadOrder(data_dir='/path/to/Skyrim Special Edition/Data')
    p = lo.add('MyMod.esp')
    for rec in p.records('WEAP'):
        print(rec.edid, [ (d.sig, d.value) for d in decode_record(rec) ])
    ops.apply_edits(lo, p, p.find_edid('MySword'), [('DATA.damage', '=', '20')])
    p.save()          # writes MyMod.esp (MyMod.esp.bak keeps the original)

    h = Plugin.load_header('Some.esp')     # header only: .masters, .is_light, ... (fast)
    a, b = Plugin.load('A.esp'), Plugin.load('B.esp')
    both = {r.formkey for r in a.records('REFR')} & {r.formkey for r in b.records('REFR')}
"""

from .core import (Plugin, Record, Group, Subrecord, EspError, FormKey, record_context,
                   FLAG_ESM, FLAG_ESL, FLAG_LOCALIZED, FLAG_DELETED, FLAG_COMPRESSED,
                   FLAG_INITIALLY_DISABLED, FLAG_PERSISTENT)
from .codec import FormID, LStr, format_formid
from .fields import decode_record, encode_items, record_to_json, json_items
from .loadorder import LoadOrder, lookup_record
from .strings import StringTables, BSA
from . import ops

__all__ = ['Plugin', 'Record', 'Group', 'Subrecord', 'EspError', 'FormKey', 'record_context',
           'FormID', 'LStr', 'format_formid', 'decode_record', 'encode_items',
           'record_to_json', 'json_items', 'LoadOrder', 'lookup_record', 'StringTables',
           'BSA', 'ops', 'FLAG_ESM', 'FLAG_ESL', 'FLAG_LOCALIZED', 'FLAG_DELETED',
           'FLAG_COMPRESSED', 'FLAG_INITIALLY_DISABLED', 'FLAG_PERSISTENT']

__version__ = '1.0.0'
