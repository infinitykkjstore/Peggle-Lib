"""
repack.py - Rebuild PS3 Peggle PAK archives from extracted assets.

Reverses the extraction process by reconstructing the exact PS3 PAK format:
  [HEADER] [INDEX] [0x80 terminator] [DATA SECTION]

The data section uses the PS3 sequential format: each file has a 2-byte
signed LE header (offset value), followed by 'header_val' bytes of padding,
then the actual file data. When no files are modified, the output is
byte-for-byte identical to the original.

Usage:
  python repack.py peggle.pak ./extracted rebuilt.pak
  python repack.py peggle.pak ./extracted rebuilt.pak --verify
"""

import struct
import os
import sys
from pathlib import Path


class RepackRecord:
    """Tracks original and modified state of one PAK entry."""
    __slots__ = ('flags', 'name', 'original_size', 'filetime_low', 'filetime_high',
                 'header_bytes', 'padding', 'original_data')

    def __init__(self, flags, name, original_size,
                 filetime_low, filetime_high,
                 header_bytes=b'', padding=b'', original_data=b''):
        self.flags = flags
        self.name = name
        self.original_size = original_size
        self.filetime_low = filetime_low
        self.filetime_high = filetime_high
        self.header_bytes = header_bytes
        self.padding = padding
        self.original_data = original_data


def parse_ps3_pak(pak_path):
    """
    Parse a PS3 PAK file, returning (records, index_size, total_data_size).

    records: list of RepackRecord with full original layout info.
    index_size: total bytes of header + index entries + terminator.
    total_data_size: total bytes of the data section.
    """
    records = []
    with open(pak_path, 'rb') as f:
        magic = struct.unpack('<I', f.read(4))[0]
        if magic != 0xBAC04AC0:
            raise ValueError(f"Bad magic: {magic:#010x}, expected 0xBAC04AC0")
        version = struct.unpack('<I', f.read(4))[0]
        if version != 0:
            raise ValueError(f"Bad version: {version}, expected 0")

        while True:
            flags_byte = f.read(1)
            if not flags_byte:
                raise EOFError("Unexpected EOF in index")
            flags = flags_byte[0]
            if flags & 0x80:
                break

            name_len = struct.unpack('B', f.read(1))[0]
            name = f.read(name_len).decode('ascii')
            size = struct.unpack('<I', f.read(4))[0]
            ft_low = struct.unpack('<I', f.read(4))[0]
            ft_high = struct.unpack('<I', f.read(4))[0]

            records.append(RepackRecord(
                flags=flags,
                name=name,
                original_size=size,
                filetime_low=ft_low,
                filetime_high=ft_high,
            ))

        index_end = f.tell()

        for rec in records:
            hdr = f.read(2)
            if len(hdr) < 2:
                raise EOFError(f"Unexpected EOF in data section at {rec.name}")
            header_val = struct.unpack('<h', hdr)[0]
            padding = b''
            if header_val > 0:
                padding = f.read(header_val)
            data = f.read(rec.original_size)
            rec.header_bytes = hdr
            rec.padding = padding
            rec.original_data = data

        total_data_size = f.tell() - index_end

    return records, index_end, total_data_size


def rebuild_pak(records, extract_dir, output_path):
    """
    Rebuild a PS3 PAK file.

    If modified files in extract_dir have different sizes from originals,
    the index is updated and the data section adjusts automatically
    (header_val=0, no padding for modified entries).
    """
    extract_dir = Path(extract_dir)
    file_count = 0
    file_count_modified = 0

    # Pre-read all modified files
    new_file_data = []
    for rec in records:
        norm_name = rec.name.replace('\\', '/')
        src = extract_dir / norm_name
        if src.exists():
            data = src.read_bytes()
            if len(data) != rec.original_size:
                file_count_modified += 1
        else:
            data = rec.original_data
            print(f"  aviso: {rec.name} nao encontrado, usando original")
        new_file_data.append(data)
        file_count += 1

    with open(output_path, 'wb') as f:
        # --- HEADER ---
        f.write(struct.pack('<II', 0xBAC04AC0, 0))

        # --- INDEX ---
        for rec, new_data in zip(records, new_file_data):
            new_size = len(new_data)
            f.write(struct.pack('B', rec.flags))
            name_bytes = rec.name.encode('ascii')
            f.write(struct.pack('B', len(name_bytes)))
            f.write(name_bytes)
            f.write(struct.pack('<I', new_size))
            f.write(struct.pack('<II', rec.filetime_low, rec.filetime_high))

        # --- TERMINATOR ---
        f.write(b'\x80')

        # --- DATA SECTION ---
        for rec, new_data in zip(records, new_file_data):
            new_size = len(new_data)
            if new_size == rec.original_size and new_data == rec.original_data:
                f.write(rec.header_bytes)
                if rec.padding:
                    f.write(rec.padding)
                f.write(new_data)
            else:
                f.write(struct.pack('<h', 0))
                f.write(new_data)

    return file_count, file_count_modified


def verify_identical(original_path, rebuilt_path):
    """Compare two files byte-by-byte and report differences."""
    orig = Path(original_path).read_bytes()
    rebuilt = Path(rebuilt_path).read_bytes()
    if orig == rebuilt:
        return True, "IDENTICO: mesmo tamanho e conteudo"
    diff_count = sum(1 for a, b in zip(orig, rebuilt) if a != b)
    size_info = f"original={len(orig)} bytes, rebuilt={len(rebuilt)} bytes, diferencas={diff_count}"
    return False, f"DIFERENTE: {size_info}"


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Peggle PAK - Reconstrutor de arquivos .pak (PS3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python repack.py peggle.pak ./extracted novo.pak
  python repack.py peggle.pak ./extracted novo.pak --verify
  python repack.py peggle.pak ./extracted novo.pak --verify-only
        """)
    parser.add_argument('pakfile', help="Arquivo .pak original (referencia)")
    parser.add_argument('extractdir', help="Diretorio com arquivos extraidos")
    parser.add_argument('output', help="Caminho do novo .pak a ser criado")
    parser.add_argument('--verify', action='store_true',
                        help="Comparar o novo .pak com o original apos rebuild")
    parser.add_argument('--verify-only', action='store_true',
                        help="Apenas comparar (sem rebuild)")
    args = parser.parse_args()

    if not os.path.exists(args.pakfile):
        print(f"Erro: {args.pakfile} nao encontrado")
        sys.exit(1)
    if not os.path.isdir(args.extractdir):
        print(f"Erro: diretorio {args.extractdir} nao encontrado")
        sys.exit(1)

    if args.verify_only:
        identical, msg = verify_identical(args.pakfile, args.output)
        print(msg)
        sys.exit(0 if identical else 1)

    print(f"Lendo referencia: {args.pakfile}")
    records, index_end, data_size = parse_ps3_pak(args.pakfile)
    print(f"  {len(records)} registros, "
          f"index={index_end} bytes, data_section={data_size} bytes")

    print(f"Reconstruindo PAK em: {args.output}")
    count, modified = rebuild_pak(records, args.extractdir, args.output)

    orig_size = os.path.getsize(args.pakfile)
    new_size = os.path.getsize(args.output)
    print(f"  {count} arquivos processados, {modified} com tamanho modificado")
    print(f"  Tamanho: original={orig_size}, novo={new_size}")

    if args.verify:
        identical, msg = verify_identical(args.pakfile, args.output)
        print(f"  Verificacao: {msg}")

    if modified == 0 and args.verify and identical:
        print("\n>>> PARABENS: rebuild 100% identico ao original! <<<")
    elif modified > 0:
        print(f"\n>>> {modified} arquivos modificados - PAK valido gerado <<<")


if __name__ == '__main__':
    main()
