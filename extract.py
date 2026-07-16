import struct
import os
import sys
from pathlib import Path

PAK_MAGIC = 0xBAC04AC0
FILEFLAGS_END = 0x80

# Content start/end markers for overlap-aware extraction.
# Maps extension -> (start_magic, end_marker, end_search_mode)
# end_search_mode:
#   "record"   -> rfind end marker in rec_data only; fallback to find in combined
#   "combined" -> rfind end marker in combined (rec_data + next_data)
#   None       -> no end marker, just strip prefix
EXTENSION_MARKERS = {
    ".jpg":  (b"\xff\xd8",        b"\xff\xd9",                  "combined"),
    ".jpeg": (b"\xff\xd8",        b"\xff\xd9",                  "combined"),
    ".gif":  (b"GIF89a",          b"\x00\x3b",                  "record"),
    ".png":  (b"\x89PNG",         b"IEND\xae\x42\x60\x82",      "combined"),
    ".jp2":  (b"\x00\x00\x00\x0c\x6a\x50\x20\x20", None,        None),
    ".tif":  (b"II*\x00",         None,                         None),
    ".tiff": (b"MM\x00*",         None,                         None),
}


class PakRecord:
    __slots__ = ('name', 'size', 'filetime', 'start_pos', 'header_val', 'data_start')

    def __init__(self, name: str, size: int, filetime: int,
                 start_pos: int = 0, header_val: int = 0, data_start: int = 0):
        self.name = name
        self.size = size
        self.filetime = filetime
        self.start_pos = start_pos
        self.header_val = header_val
        self.data_start = data_start

    def __repr__(self):
        return (f"PakRecord(name={self.name!r}, size={self.size}, "
                f"header_val={self.header_val}, data_start={self.data_start})")


class PakFile:
    def __init__(self, path: str):
        self.path = Path(path)
        self.records: list[PakRecord] = []
        self.data_offset = 0

    def parse(self):
        with open(self.path, 'rb') as f:
            magic = struct.unpack('<I', f.read(4))[0]
            if magic != PAK_MAGIC:
                raise ValueError(
                    f"Assinatura invalida: 0x{magic:08X}, esperado 0x{PAK_MAGIC:08X}"
                )
            version = struct.unpack('<I', f.read(4))[0]
            if version != 0:
                raise ValueError(f"Versao invalida: {version}, esperado 0")

            while True:
                flags_byte = f.read(1)
                if not flags_byte:
                    break
                flags = flags_byte[0]
                if flags & FILEFLAGS_END:
                    break
                name_len = struct.unpack('B', f.read(1))[0]
                name = f.read(name_len).decode('ascii')
                size = struct.unpack('<i', f.read(4))[0]
                filetime = struct.unpack('<Q', f.read(8))[0]
                self.records.append(PakRecord(name, size, filetime))

            # Parse 2-byte per-record headers from the data section (PS3 sequential format)
            self.data_offset = f.tell()
            pos = self.data_offset
            for rec in self.records:
                rec.start_pos = pos  # position of the 2-byte header (sequential offset)
                f.seek(pos)
                hdr = f.read(2)
                if len(hdr) == 2:
                    rec.header_val = struct.unpack('<H', hdr)[0]
                    if rec.header_val > 32767:
                        rec.header_val -= 65536
                else:
                    rec.header_val = 0
                rec.data_start = pos + 2 + rec.header_val  # where actual file data begins
                pos += 2 + rec.header_val + rec.size
            self.sequential_end = pos
        return self

    OVERLAP_LIMIT = 256

    def _extract_content(self, rec_data: bytes, next_data: bytes, ext: str) -> bytes:
        """Extract clean file content from a record's data, using next_data for overlap."""
        info = EXTENSION_MARKERS.get(ext)
        if info is None:
            return rec_data

        start_magic, end_marker, mode = info
        start_pos = rec_data.find(start_magic)
        if start_pos < 0:
            return rec_data

        if end_marker is None:
            return rec_data[start_pos:]

        search_data = rec_data + next_data[:self.OVERLAP_LIMIT]

        end_pos = search_data.rfind(end_marker, start_pos)
        if end_pos < 0:
            return rec_data[start_pos:]

        return search_data[start_pos:end_pos + len(end_marker)]

    def extract_raw(self, output_dir: str):
        """Extract raw data from the PS3 sequential PAK format."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'rb') as f:
            for rec in self.records:
                # Read the full sequential payload (2-byte header + padding + actual data)
                raw_size = 2 + rec.header_val + rec.size
                f.seek(rec.start_pos)
                data = f.read(raw_size)
                norm_name = rec.name.replace('\\', '/')
                filepath = out / norm_name
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'wb') as out_f:
                    out_f.write(data)
                print(f"  extraido: {rec.name} ({raw_size} bytes)")
        total = sum(r.size for r in self.records)
        print(f"\nExtracao concluida: {len(self.records)} arquivos, {total} bytes")

    def extract(self, output_dir: str):
        """Extract actual files as the PS3 game sees them (PS3-correct extraction).

        The PS3 reads the PAK sequentially: each record has a 2-byte LE header
        (offset value), followed by padding bytes, then the actual file data
        of 'declared_size' bytes. This method reads only the actual file data.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'rb') as f:
            for rec in self.records:
                f.seek(rec.data_start)
                data = f.read(rec.size)
                norm_name = rec.name.replace('\\', '/')
                filepath = out / norm_name
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'wb') as out_f:
                    out_f.write(data)
                print(f"  extraido: {rec.name} ({rec.size} bytes)")
        total = sum(r.size for r in self.records)
        print(f"\nExtracao concluida: {len(self.records)} arquivos, {total} bytes")

    def extract_smart(self, output_dir: str):
        """Extract using content markers (legacy fallback, use extract() for PS3-correct output)."""
        return self.extract(output_dir)

    def list_files(self):
        print(f"\n{'ID':<5} {'Tamanho':<10} {'Hdr':<5} {'DataStart':<10} {'Nome'}")
        print("-" * 90)
        for i, rec in enumerate(self.records):
            print(f"{i:<5} {rec.size:<10} {rec.header_val:<5} {rec.data_start:<10} {rec.name}")
        total = sum(r.size for r in self.records)
        print(f"\nTotal: {len(self.records)} arquivos, {total} bytes"
              f" ({total / 1024 / 1024:.2f} MB)")
        print(f"Offset dos dados: {self.data_offset} ({self.data_offset - 8} bytes de records)")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Peggle PAK - Extrator de arquivos .pak do Peggle (PS3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py peggle.pak -l                     # Listar
  python main.py peggle.pak -x ./extracted         # Extrair (PS3-correct)
  python main.py peggle.pak --raw -x ./extracted   # Extrair raw (com headers)
        """)
    parser.add_argument('pakfile', help="Caminho do .pak")
    parser.add_argument('-l', '--list', action='store_true',
                        help="Listar conteudo")
    parser.add_argument('-x', '--extract', metavar='DIR',
                        help="Extrair arquivos para DIR")
    parser.add_argument('--raw', action='store_true',
                        help="Extracao raw (inclui header de 2 bytes e padding)")
    args = parser.parse_args()

    if not os.path.exists(args.pakfile):
        print(f"Erro: arquivo '{args.pakfile}' nao encontrado")
        sys.exit(1)

    print(f"Abrindo: {args.pakfile}...")
    pak = PakFile(args.pakfile)
    try:
        pak.parse()
    except Exception as e:
        print(f"Erro ao parsear: {e}")
        sys.exit(1)

    print(f"PAK valido! {len(pak.records)} arquivos encontrados.")

    if args.list:
        pak.list_files()

    if args.extract:
        print(f"\nExtraindo para: {args.extract}")
        if args.raw:
            pak.extract_raw(args.extract)
        else:
            pak.extract(args.extract)

    if not any([args.list, args.extract]):
        parser.print_help()


if __name__ == '__main__':
    main()
