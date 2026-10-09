"""Dev tool (needs `pip install lz4`): build a Skyrim SE v105 BSA with LZ4-compressed files.

Usage: python make_test_bsa.py out.bsa "inner\\path.txt=local/file" ...
Used to create tests/fixtures/bsa/Skyrim - Interface.bsa (verified with Mutagen's archive reader).
"""
import os, struct, sys
import lz4.frame

def bsa_hash(name, is_folder=False):
    name = name.lower().replace('/', '\\')
    if is_folder:
        root, ext = name, ''
    else:
        root, ext = os.path.splitext(name)
    c = root.encode('cp1252'); e = ext.encode('cp1252')
    h1 = 0
    if c:
        h1 = c[-1] | ((c[-2] if len(c) > 2 else 0) << 8) | (len(c) << 16) | (c[0] << 24)
    h1 |= {b'.kf': 0x80, b'.nif': 0x8000, b'.dds': 0x8080, b'.wav': 0x80000000}.get(e, 0)
    h2 = 0
    for ch in c[1:-2]:
        h2 = (h2 * 0x1003F + ch) & 0xFFFFFFFF
    h3 = 0
    for ch in e:
        h3 = (h3 * 0x1003F + ch) & 0xFFFFFFFF
    h2 = (h2 + h3) & 0xFFFFFFFF
    return (h2 << 32) | h1

def write_bsa(out, files):   # files: {inner path: bytes}
    folders = {}
    for p, data in files.items():
        p = p.lower().replace('/', '\\')
        d, n = p.rsplit('\\', 1)
        folders.setdefault(d, []).append((n, data))
    flist = sorted(folders.items(), key=lambda kv: bsa_hash(kv[0], True))
    for d, lst in flist:
        lst.sort(key=lambda x: bsa_hash(x[0]))
    nfiles = sum(len(v) for _, v in flist)
    total_folder_len = sum(len(d) + 1 for d, _ in flist)
    total_file_len = sum(len(n) + 1 for _, v in flist for n, _ in v)
    flags = 0x1 | 0x2 | 0x4
    header = struct.pack('<4sIIIIIIIHH', b'BSA\0', 105, 36, flags, len(flist), nfiles, total_folder_len, total_file_len, 0, 0)
    folder_rec_size = 24 * len(flist)
    file_block_size = sum(1 + len(d) + 1 + 16 * len(v) for d, v in flist)
    names_off = 36 + folder_rec_size + file_block_size
    data_off = names_off + total_file_len
    folder_recs = b''; file_blocks = b''; names = b''; blobs = b''
    pos_block = 36 + folder_rec_size
    cur_data = data_off
    for d, v in flist:
        folder_recs += struct.pack('<QIIQ', bsa_hash(d, True), len(v), 0, pos_block + total_file_len)
        blk = bytes([len(d) + 1]) + d.encode() + b'\0'
        for n, data in v:
            comp = struct.pack('<I', len(data)) + lz4.frame.compress(data)
            blk += struct.pack('<QII', bsa_hash(n), len(comp), cur_data)
            blobs += comp
            cur_data += len(comp)
            names += n.encode() + b'\0'
        file_blocks += blk
        pos_block += len(blk)
    with open(out, 'wb') as f:
        f.write(header + folder_recs + file_blocks + names + blobs)

if __name__ == '__main__':
    out = sys.argv[1]
    files = {}
    for src in sys.argv[2:]:
        inner, path = src.split('=', 1)
        files[inner] = open(path, 'rb').read()
    write_bsa(out, files)
