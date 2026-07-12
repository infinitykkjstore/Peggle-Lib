"""
levelreader.py - Parser/leitor para .dat levels do Peggle PS3

Mapeia 100% das propriedades binarias dos arquivos .dat de nivel
do Peggle (PS3). Suporta leitura completa e re-escrita byte-a-byte.

Baseado em:
  - PeggleEdit-master (editor PC) - formato canonico
  - EBOOT.ELF.c (decompilacao PS3) - confirmacao de campos
  - SexyAppFramework - formatos PopCap (strings, buffers)

Uso:
  python levelreader.py <arquivo.dat>         # Logar um nivel
  python levelreader.py --all                 # Logar todos do .pak
  python levelreader.py --test                # Testar round-trip em todos
"""

import struct
import sys
import os
import math
from enum import IntEnum


# ──────────────────────────────────────────────
# Constants / Enums
# ──────────────────────────────────────────────

ENTRY_TYPES = {
    2: "Rod",
    3: "Polygon",
    5: "Circle",
    6: "Brick",
    8: "Teleport",
    9: "Emitter",
    1001: "PegGenerator",
    1002: "BrickGenerator",
    1003: "PegCurveGenerator",
    1004: "BrickCurveGenerator",
}

ENTRY_NAMES = {v: k for k, v in ENTRY_TYPES.items()}

MOVEMENT_TYPES = [
    "NoMovement",          # 0
    "VerticalCycle",       # 1
    "HorizontalCycle",     # 2
    "Circle",              # 3
    "HorizontalInfinity",  # 4
    "VerticalInfinity",    # 5
    "HorizontalArc",       # 6
    "VerticalArc",         # 7
    "Rotate",              # 8
    "RotateBackAndForth",  # 9
    "Unused",              # 10
    "VerticalWrap",        # 11
    "HorizontalWrap",      # 12
    "RotateAroundCircle",  # 13
    "RetraceCircle",       # 14
    "WeirdShape",          # 15
]

# Generic flag indices (from LevelEntry.cs ReadGenericData)
FLAG_DESC = {
    0:  "Rolly",
    1:  "Bouncy",
    2:  "HasPegInfo",
    3:  "HasMovementInfo",
    4:  "Unknown4 (int32)",
    5:  "Collision",
    6:  "Visible",
    7:  "CanMove",
    8:  "SolidColour",
    9:  "OutlineColour",
    10: "ImageFilename",
    11: "ImageDX",
    12: "ImageDY",
    13: "ImageRotation",
    14: "Background",
    15: "BaseObject",
    16: "Unknown16 (int32)",
    17: "ID (string)",
    18: "Unknown18 (int32)",
    19: "Sound",
    20: "BallStopReset",
    21: "Logic (string)",
    22: "Foreground",
    23: "MaxBounceVelocity",
    24: "DrawSort",
    25: "Foreground2",
    26: "SubID",
    27: "FlipperFlags",
    28: "DrawFloat",
    30: "Shadow (v>=0x50)",
}


# ──────────────────────────────────────────────
# FlagGroup (bitfield)
# ──────────────────────────────────────────────

class FlagGroup:
    __slots__ = ('flags',)

    def __init__(self, value=0):
        self.flags = value

    @classmethod
    def from_int32(cls, v):
        return cls(v)

    @classmethod
    def from_int16(cls, v):
        return cls(v & 0xFFFF)

    @classmethod
    def from_byte(cls, v):
        return cls(v & 0xFF)

    @classmethod
    def from_uint24(cls, v):
        return cls(v & 0xFFFFFF)

    def __getitem__(self, i):
        return bool(self.flags & (1 << i))

    def __setitem__(self, i, value):
        if value:
            self.flags |= (1 << i)
        else:
            self.flags &= ~(1 << i)

    def __repr__(self):
        return f"FlagGroup(0x{self.flags:08x})"

    def get_active_flags(self):
        return [i for i in range(32) if self[i]]


# ──────────────────────────────────────────────
# Binary reader helper
# ──────────────────────────────────────────────

class BinaryReader:
    __slots__ = ('data', 'offset')

    def __init__(self, data):
        self.data = data
        self.offset = 0

    def tell(self):
        return self.offset

    def seek(self, pos):
        self.offset = pos

    def skip(self, n):
        self.offset += n

    def read(self, n):
        result = self.data[self.offset:self.offset + n]
        self.offset += n
        return result

    def read_int8(self):
        v = struct.unpack_from('<b', self.data, self.offset)[0]
        self.offset += 1
        return v

    def read_uint8(self):
        v = struct.unpack_from('<B', self.data, self.offset)[0]
        self.offset += 1
        return v

    def read_int16(self):
        v = struct.unpack_from('<h', self.data, self.offset)[0]
        self.offset += 2
        return v

    def read_uint16(self):
        v = struct.unpack_from('<H', self.data, self.offset)[0]
        self.offset += 2
        return v

    def read_int32(self):
        v = struct.unpack_from('<i', self.data, self.offset)[0]
        self.offset += 4
        return v

    def read_uint32(self):
        v = struct.unpack_from('<I', self.data, self.offset)[0]
        self.offset += 4
        return v

    def read_float(self):
        v = struct.unpack_from('<f', self.data, self.offset)[0]
        self.offset += 4
        return v

    def read_uint24(self):
        """Read unsigned 24-bit integer (used when version < 0x0F)."""
        ab = self.read_uint16()
        c = self.read_uint8()
        return ab | (c << 16)

    def read_int24(self):
        """Read signed 24-bit integer."""
        ab = self.read_uint16()
        c = self.read_uint8()
        result = ab | (c << 16)
        if c & 0x80:
            result |= (0xFF << 24)
        return result

    def read_popcap_string(self):
        """PopCap string: int16 length + UTF-8 bytes."""
        length = self.read_int16()
        if length <= 0:
            return ""
        return self.read(length).decode('utf-8')

    def read_color(self):
        """Color stored as ARGB int32."""
        argb = self.read_uint32()
        a = (argb >> 24) & 0xFF
        r = (argb >> 16) & 0xFF
        g = (argb >> 8) & 0xFF
        b = argb & 0xFF
        return f"ARGB({a},{r},{g},{b})", (a, r, g, b)

    def remaining(self):
        return len(self.data) - self.offset


class BinaryWriter:
    __slots__ = ('data',)

    def __init__(self):
        self.data = bytearray()

    def write(self, b):
        if isinstance(b, int):
            self.data.append(b)
        else:
            self.data.extend(b)

    def write_int8(self, v):
        self.data.extend(struct.pack('<b', v))

    def write_uint8(self, v):
        self.data.append(v & 0xFF)

    def write_int16(self, v):
        self.data.extend(struct.pack('<h', v))

    def write_uint16(self, v):
        self.data.extend(struct.pack('<H', v))

    def write_int32(self, v):
        self.data.extend(struct.pack('<i', v))

    def write_uint32(self, v):
        self.data.extend(struct.pack('<I', v))

    def write_float(self, v):
        self.data.extend(struct.pack('<f', v))

    def write_popcap_string(self, s):
        if not s:
            self.write_uint16(0)
        else:
            encoded = s.encode('utf-8')
            self.write_uint16(len(encoded))
            self.write(encoded)

    def write_color(self, a, r, g, b):
        argb = (a << 24) | (r << 16) | (g << 8) | b
        self.write_uint32(argb)

    def write_uint24(self, v):
        v = v & 0xFFFFFF
        self.data.extend(struct.pack('<H', v & 0xFFFF))
        self.data.append((v >> 16) & 0xFF)

    def to_bytes(self):
        return bytes(self.data)


# ──────────────────────────────────────────────
# PEG INFO
# ──────────────────────────────────────────────

class PegInfo:
    __slots__ = ('type', 'can_be_orange', 'crumble',
                 'unknown_int32_1', 'unknown_int32_2',
                 'unknown_byte_1', 'unknown_byte_2')

    def __init__(self):
        self.type = 1
        self.can_be_orange = False
        self.crumble = False
        self.unknown_int32_1 = None
        self.unknown_int32_2 = None
        self.unknown_byte_1 = None
        self.unknown_byte_2 = None

    @staticmethod
    def read(br, version, indent=""):
        pi = PegInfo()
        pi.type = br.read_uint8()
        f2 = FlagGroup(br.read_uint8())
        if f2[1]:
            pi.can_be_orange = True
        if f2[2]:
            pi.unknown_int32_1 = br.read_int32()
        if f2[3]:
            pi.crumble = True
        if f2[4]:
            pi.unknown_int32_2 = br.read_int32()
        if f2[5]:
            pi.unknown_byte_1 = br.read_uint8()
        if f2[7]:
            pi.unknown_byte_2 = br.read_uint8()
        return pi

    def write(self, bw, version):
        bw.write_uint8(1)  # Always 1
        f2 = FlagGroup()
        if self.can_be_orange:
            f2[1] = True
        if self.crumble:
            f2[3] = True
        bw.write_uint8(f2.flags & 0xFF)

    def log(self, indent=""):
        print(f"{indent}PegInfo:")
        print(f"{indent}  Type: {self.type}")
        print(f"{indent}  CanBeOrange: {self.can_be_orange}")
        print(f"{indent}  Crumble (QuickDisappear): {self.crumble}")
        if self.unknown_int32_1 is not None:
            print(f"{indent}  UnknownInt32_1: {self.unknown_int32_1}")
        if self.unknown_int32_2 is not None:
            print(f"{indent}  UnknownInt32_2: {self.unknown_int32_2}")
        if self.unknown_byte_1 is not None:
            print(f"{indent}  UnknownByte_1: {self.unknown_byte_1}")
        if self.unknown_byte_2 is not None:
            print(f"{indent}  UnknownByte_2: {self.unknown_byte_2}")


# ──────────────────────────────────────────────
# MOVEMENT
# ──────────────────────────────────────────────

class Movement:
    __slots__ = ('type', 'reverse', 'anchor_x', 'anchor_y',
                 'time_period', 'offset', 'radius1', 'start_phase',
                 'move_rotation', 'radius2', 'pause1', 'pause2',
                 'phase1', 'phase2', 'post_delay_phase', 'max_angle',
                 'unknown8', 'rotation',
                 'sub_offset_x', 'sub_offset_y', 'sub_movement',
                 'object_x', 'object_y')

    def __init__(self):
        self.type = 0
        self.reverse = False
        self.anchor_x = 0.0
        self.anchor_y = 0.0
        self.time_period = 0
        self.offset = 0
        self.radius1 = 0
        self.start_phase = 0.0
        self.move_rotation = 0.0
        self.radius2 = 0
        self.pause1 = 0
        self.pause2 = 0
        self.phase1 = 0
        self.phase2 = 0
        self.post_delay_phase = 0.0
        self.max_angle = 0.0
        self.unknown8 = 0.0
        self.rotation = 0.0
        self.sub_offset_x = 0.0
        self.sub_offset_y = 0.0
        self.sub_movement = None  # MovementLink
        self.object_x = 0.0
        self.object_y = 0.0

    @staticmethod
    def read(br, version, indent=""):
        m = Movement()
        movement_shape = br.read_int8()
        abs_type = abs(movement_shape)
        m.type = abs_type if abs_type < len(MOVEMENT_TYPES) else 0
        m.reverse = movement_shape < 0
        m.anchor_x = br.read_float()
        m.anchor_y = br.read_float()
        m.time_period = br.read_int16()

        fA = FlagGroup(br.read_int16())
        if fA[0]:
            m.offset = br.read_int16()
        if fA[1]:
            m.radius1 = br.read_int16()
        if fA[2]:
            m.start_phase = br.read_float()
        if fA[3]:
            m.move_rotation = br.read_float()  # stored in radians, convert to degrees
            m.move_rotation = math.degrees(m.move_rotation)
        if fA[4]:
            m.radius2 = br.read_int16()
        if fA[5]:
            m.pause1 = br.read_int16()
        if fA[6]:
            m.pause2 = br.read_int16()
        if fA[7]:
            m.phase1 = br.read_uint8()
        if fA[8]:
            m.phase2 = br.read_uint8()
        if fA[9]:
            m.post_delay_phase = br.read_float()
        if fA[10]:
            m.max_angle = br.read_float()
        if fA[11]:
            m.unknown8 = br.read_float()
        if fA[14]:
            m.rotation = math.degrees(br.read_float())
        if fA[12]:
            m.sub_offset_x = br.read_float()
            m.sub_offset_y = br.read_float()
            m.sub_movement = MovementLink.read(br, version, indent + "    ")
        if fA[13]:
            m.object_x = br.read_float()
            m.object_y = br.read_float()
        return m

    def write(self, bw, version):
        fA = FlagGroup()
        fA[0] = (self.offset != 0)
        fA[1] = (self.radius1 != 0)
        fA[2] = (self.start_phase != 0.0)
        fA[3] = (self.move_rotation != 0.0)
        fA[4] = (self.radius2 != 0)
        fA[5] = (self.pause1 != 0)
        fA[6] = (self.pause2 != 0)
        fA[7] = (self.phase1 != 0)
        fA[8] = (self.phase2 != 0)
        fA[9] = (self.post_delay_phase != 0.0)
        fA[10] = (self.max_angle != 0.0)
        fA[11] = (self.unknown8 != 0.0)
        fA[14] = (self.rotation != 0.0)
        fA[12] = (self.sub_offset_x != 0.0 or self.sub_offset_y != 0.0 or self.sub_movement is not None)
        fA[13] = (self.object_x != 0.0 or self.object_y != 0.0)

        if self.sub_movement is not None:
            fA[12] = True

        type_byte = self.type
        if self.reverse:
            type_byte = 256 - self.type
        bw.write_uint8(type_byte & 0xFF)

        bw.write_float(self.anchor_x)
        bw.write_float(self.anchor_y)
        bw.write_int16(self.time_period)
        bw.write_int16(fA.flags & 0xFFFF)

        if fA[0]:
            bw.write_int16(self.offset)
        if fA[1]:
            bw.write_int16(self.radius1)
        if fA[2]:
            bw.write_float(self.start_phase)
        if fA[3]:
            bw.write_float(math.radians(self.move_rotation))
        if fA[4]:
            bw.write_int16(self.radius2)
        if fA[5]:
            bw.write_int16(self.pause1)
        if fA[6]:
            bw.write_int16(self.pause2)
        if fA[7]:
            bw.write_uint8(self.phase1)
        if fA[8]:
            bw.write_uint8(self.phase2)
        if fA[9]:
            bw.write_float(self.post_delay_phase)
        if fA[10]:
            bw.write_float(self.max_angle)
        if fA[11]:
            bw.write_float(self.unknown8)
        if fA[14]:
            bw.write_float(math.radians(self.rotation))
        if fA[12]:
            bw.write_float(self.sub_offset_x)
            bw.write_float(self.sub_offset_y)
            ml = self.sub_movement if self.sub_movement else MovementLink()
            ml.write(bw, version)
        if fA[13]:
            bw.write_float(self.object_x)
            bw.write_float(self.object_y)

    def log(self, indent=""):
        type_name = MOVEMENT_TYPES[self.type] if self.type < len(MOVEMENT_TYPES) else f"Unknown({self.type})"
        print(f"{indent}Movement:")
        print(f"{indent}  Type: {type_name} {'(REVERSED)' if self.reverse else ''}")
        print(f"{indent}  Anchor: ({self.anchor_x:.4f}, {self.anchor_y:.4f})")
        print(f"{indent}  TimePeriod: {self.time_period} ds ({self.time_period/100:.3f}s)")
        if self.offset != 0:
            print(f"{indent}  Offset: {self.offset}")
        if self.radius1 != 0:
            print(f"{indent}  Radius1: {self.radius1}")
        if self.start_phase != 0.0:
            print(f"{indent}  StartPhase: {self.start_phase:.4f}")
        if self.move_rotation != 0.0:
            print(f"{indent}  MoveRotation: {self.move_rotation:.4f} deg")
        if self.radius2 != 0:
            print(f"{indent}  Radius2: {self.radius2}")
        if self.pause1 != 0:
            print(f"{indent}  Pause1: {self.pause1}")
        if self.pause2 != 0:
            print(f"{indent}  Pause2: {self.pause2}")
        if self.phase1 != 0:
            print(f"{indent}  Phase1: {self.phase1}")
        if self.phase2 != 0:
            print(f"{indent}  Phase2: {self.phase2}")
        if self.post_delay_phase != 0.0:
            print(f"{indent}  PostDelayPhase: {self.post_delay_phase:.4f}")
        if self.max_angle != 0.0:
            print(f"{indent}  MaxAngle: {self.max_angle:.4f}")
        if self.unknown8 != 0.0:
            print(f"{indent}  Unknown8: {self.unknown8:.4f}")
        if self.rotation != 0.0:
            print(f"{indent}  Rotation: {self.rotation:.4f} deg")
        if self.sub_movement is not None:
            print(f"{indent}  SubMovementOffset: ({self.sub_offset_x:.4f}, {self.sub_offset_y:.4f})")
            self.sub_movement.log(indent + "    ")
        if self.object_x != 0.0 or self.object_y != 0.0:
            print(f"{indent}  ObjectPos: ({self.object_x:.4f}, {self.object_y:.4f})")


class MovementLink:
    __slots__ = ('link_id', 'movement')

    def __init__(self):
        self.link_id = 0
        self.movement = None

    @staticmethod
    def read(br, version, indent=""):
        ml = MovementLink()
        ml.link_id = br.read_int32()
        if ml.link_id == 1:
            ml.movement = Movement.read(br, version, indent + "  ")
        return ml

    def write(self, bw, version):
        bw.write_int32(self.link_id)
        if self.link_id == 1 and self.movement:
            self.movement.write(bw, version)

    def log(self, indent=""):
        if self.link_id == 0:
            print(f"{indent}MovementLink: None")
        elif self.link_id == 1:
            print(f"{indent}MovementLink: Owns (ID=1)")
            if self.movement:
                self.movement.log(indent + "  ")
        else:
            print(f"{indent}MovementLink: References MUID={self.link_id}")
            if self.movement:
                self.movement.log(indent + "  ")


# ──────────────────────────────────────────────
# VARIABLE FLOAT
# ──────────────────────────────────────────────

class VariableFloat:
    __slots__ = ('is_variable', 'static_value', 'variable_value')

    def __init__(self, is_variable=False, static_value=0.0, variable_value=""):
        self.is_variable = is_variable
        self.static_value = static_value
        self.variable_value = variable_value

    @staticmethod
    def read(br):
        var_type = br.read_uint8()
        if var_type > 0:
            return VariableFloat(is_variable=False, static_value=br.read_float())
        else:
            return VariableFloat(is_variable=True, variable_value=br.read_popcap_string())

    def write(self, bw):
        if self.is_variable:
            bw.write_uint8(0)
            bw.write_popcap_string(self.variable_value)
        else:
            bw.write_uint8(1)
            bw.write_float(self.static_value)

    def log(self, indent=""):
        if self.is_variable:
            return f"{indent}\"{self.variable_value}\" (variable)"
        else:
            return f"{indent}{self.static_value:.6f}"

    def __repr__(self):
        if self.is_variable:
            return f"VF(var='{self.variable_value}')"
        return f"VF({self.static_value})"


# ──────────────────────────────────────────────
# LEVEL ENTRY (base)
# ──────────────────────────────────────────────

class LevelEntry:
    __slots__ = ('magic', 'type', 'entry_type_name',
                 'generic_flags_raw', 'generic_flags',
                 'x', 'y',
                 'rolly', 'bouncy', 'peg_info', 'movement_link',
                 'unknown_int32_1',  # flag 4
                 'collision', 'visible', 'can_move',
                 'solid_colour', 'outline_colour',
                 'image_filename', 'image_dx', 'image_dy', 'image_rotation',
                 'unknown_int32_2',  # flag 16
                 'id', 'unknown_int32_3',  # flag 18
                 'sound', 'logic',
                 'max_bounce_velocity', 'sub_id', 'flipper_flags',
                 'background', 'base_object', 'ball_stop_reset',
                 'foreground', 'draw_sort', 'foreground2',
                 'draw_float', 'shadow',
                 'specific_data')

    def __init__(self):
        self.magic = 0
        self.type = 0
        self.entry_type_name = "Unknown"
        self.generic_flags_raw = 0
        self.generic_flags = FlagGroup()

        self.x = 0.0
        self.y = 0.0
        self.rolly = 0.0
        self.bouncy = 0.0
        self.peg_info = None
        self.movement_link = None

        self.unknown_int32_1 = None  # flag 4
        self.collision = True
        self.visible = True
        self.can_move = True
        self.solid_colour = None  # (a,r,g,b) tuple
        self.outline_colour = None
        self.image_filename = None
        self.image_dx = 0.0
        self.image_dy = 0.0
        self.image_rotation = 0.0
        self.unknown_int32_2 = None  # flag 16
        self.id = None
        self.unknown_int32_3 = None  # flag 18
        self.sound = 0
        self.logic = None
        self.max_bounce_velocity = 0.0
        self.sub_id = 0
        self.flipper_flags = 0
        self.background = False
        self.base_object = False
        self.ball_stop_reset = False
        self.foreground = False
        self.draw_sort = False
        self.foreground2 = False
        self.draw_float = False
        self.shadow = True

        self.specific_data = None  # type-specific data store

    def read_generic(self, br, version):
        if version < 0x0F:
            self.generic_flags_raw = br.read_uint24()
        else:
            self.generic_flags_raw = br.read_uint32()
        self.generic_flags = FlagGroup(self.generic_flags_raw)
        f = self.generic_flags

        self.collision = f[5]
        self.visible = f[6]
        self.can_move = f[7]
        self.background = f[14]
        self.base_object = f[15]
        self.ball_stop_reset = f[20]
        self.foreground = f[22]
        self.draw_sort = f[24]
        self.foreground2 = f[25]
        self.draw_float = f[28]
        self.shadow = f[30] if version >= 0x50 else True

        if f[0]:
            self.rolly = br.read_float()
        if f[1]:
            self.bouncy = br.read_float()
        if f[4]:
            self.unknown_int32_1 = br.read_int32()
        if f[8]:
            s, col = br.read_color()
            self.solid_colour = col
        if f[9]:
            s, col = br.read_color()
            self.outline_colour = col
        if f[10]:
            self.image_filename = br.read_popcap_string()
        if f[11]:
            self.image_dx = br.read_float()
        if f[12]:
            self.image_dy = br.read_float()
        if f[13]:
            self.image_rotation = br.read_float()  # stored in radians
            self.image_rotation = math.degrees(self.image_rotation)
        if f[16]:
            self.unknown_int32_2 = br.read_int32()
        if f[17]:
            self.id = br.read_popcap_string()
        if f[18]:
            self.unknown_int32_3 = br.read_int32()
        if f[19]:
            self.sound = br.read_uint8()
        if f[21]:
            self.logic = br.read_popcap_string()
        if f[23]:
            self.max_bounce_velocity = br.read_float()
        if f[26]:
            self.sub_id = br.read_int32()
        if f[27]:
            self.flipper_flags = br.read_uint8()
        if f[2]:
            self.peg_info = PegInfo.read(br, version)
        if f[3]:
            self.movement_link = MovementLink.read(br, version)

    def write_generic(self, bw, version):
        f = FlagGroup()
        f[0] = (self.rolly != 0.0)
        f[1] = (self.bouncy != 0.0)
        f[2] = (self.peg_info is not None)
        f[3] = (self.movement_link is not None)
        f[5] = self.collision
        f[6] = self.visible
        f[7] = self.can_move
        f[8] = (self.solid_colour is not None)
        f[9] = (self.outline_colour is not None)
        f[10] = (self.image_filename is not None and self.image_filename != "")
        f[11] = (self.image_dx != 0.0)
        f[12] = (self.image_dy != 0.0)
        f[13] = (self.image_rotation != 0.0)
        f[14] = self.background
        f[15] = self.base_object
        f[17] = (self.id is not None and self.id != "")
        f[19] = (self.sound != 0)
        f[20] = self.ball_stop_reset
        f[21] = (self.logic is not None and self.logic != "")
        f[22] = self.foreground
        f[23] = (self.max_bounce_velocity != 0.0)
        f[24] = self.draw_sort
        f[25] = self.foreground2
        f[26] = (self.sub_id != 0)
        f[27] = (self.flipper_flags != 0)
        f[28] = self.draw_float
        f[30] = (self.shadow and version >= 0x50)

        if version < 0x0F:
            bw.write_uint24(f.flags & 0xFFFFFF)
        else:
            bw.write_uint32(f.flags)

        if f[0]:
            bw.write_float(self.rolly)
        if f[1]:
            bw.write_float(self.bouncy)
        if f[8]:
            if self.solid_colour:
                bw.write_color(*self.solid_colour)
        if f[9]:
            if self.outline_colour:
                bw.write_color(*self.outline_colour)
        if f[10]:
            bw.write_popcap_string(self.image_filename)
        if f[11]:
            bw.write_float(self.image_dx)
        if f[12]:
            bw.write_float(self.image_dy)
        if f[13]:
            bw.write_float(math.radians(self.image_rotation))
        if f[17]:
            bw.write_popcap_string(self.id)
        if f[19]:
            bw.write_uint8(self.sound)
        if f[21]:
            bw.write_popcap_string(self.logic)
        if f[23]:
            bw.write_float(self.max_bounce_velocity)
        if f[26]:
            bw.write_int32(self.sub_id)
        if f[27]:
            bw.write_uint8(self.flipper_flags)
        if f[2] and self.peg_info:
            self.peg_info.write(bw, version)
        if f[3] and self.movement_link:
            self.movement_link.write(bw, version)

    def log_generic(self, indent=""):
        f = self.generic_flags
        print(f"{indent}Generic Flags: 0x{self.generic_flags_raw:08x}")
        active = f.get_active_flags()
        if active:
            for i in active:
                desc = FLAG_DESC.get(i, f"Flag{i}")
                print(f"{indent}  [{i}] {desc} = True")

        if f[0] and self.rolly != 0.0:
            print(f"{indent}Rolly: {self.rolly}")
        if f[1] and self.bouncy != 0.0:
            print(f"{indent}Bouncy: {self.bouncy}")
        if f[4] and self.unknown_int32_1 is not None:
            print(f"{indent}Unknown4 (int32): {self.unknown_int32_1}")
        if f[8] and self.solid_colour:
            a, r, g, b = self.solid_colour
            print(f"{indent}SolidColour: ARGB({a},{r},{g},{b})")
            if a == 0 and r == 0 and g == 0 and b == 0:
                print(f"{indent}  -> Transparent Black")
        if f[9] and self.outline_colour:
            a, r, g, b = self.outline_colour
            print(f"{indent}OutlineColour: ARGB({a},{r},{g},{b})")
        if f[10] and self.image_filename:
            print(f"{indent}ImageFilename: \"{self.image_filename}\"")
        if f[11]:
            print(f"{indent}ImageDX: {self.image_dx}")
        if f[12]:
            print(f"{indent}ImageDY: {self.image_dy}")
        if f[13]:
            print(f"{indent}ImageRotation: {self.image_rotation:.4f} deg")
        if f[16] and self.unknown_int32_2 is not None:
            print(f"{indent}Unknown16 (int32): {self.unknown_int32_2}")
        if f[17] and self.id:
            print(f"{indent}ID: \"{self.id}\"")
        if f[18] and self.unknown_int32_3 is not None:
            print(f"{indent}Unknown18 (int32): {self.unknown_int32_3}")
        if f[19]:
            print(f"{indent}Sound: {self.sound}")
        if f[21] and self.logic:
            print(f"{indent}Logic: \"{self.logic}\"")
        if f[23]:
            print(f"{indent}MaxBounceVelocity: {self.max_bounce_velocity}")
        if f[26]:
            print(f"{indent}SubID: {self.sub_id}")
        if f[27]:
            print(f"{indent}FlipperFlags: {self.flipper_flags}")

        if self.peg_info:
            self.peg_info.log(indent)
        if self.movement_link:
            self.movement_link.log(indent)


# ──────────────────────────────────────────────
# ENTRY TYPE READERS / WRITERS
# ──────────────────────────────────────────────

def read_circle(br, version, entry):
    """Type 5 - Circle / Peg"""
    fA = FlagGroup(br.read_uint8())
    if version >= 0x52:
        fB = FlagGroup(br.read_uint8())
    if fA[1]:
        entry.x = br.read_float()
        entry.y = br.read_float()
    radius = br.read_float()
    return {"fA": fA.flags, "radius": radius}

def write_circle(bw, version, entry, data):
    fA = FlagGroup()
    fA[0] = True
    if entry.movement_link is None:
        fA[1] = True
    bw.write_uint8(fA.flags & 0xFF)
    if version >= 0x52:
        bw.write_uint8(0)
    if fA[1]:
        bw.write_float(entry.x)
        bw.write_float(entry.y)
    bw.write_float(data.get("radius", 10.0))


def read_rod(br, version, entry):
    """Type 2 - Rod"""
    fA = FlagGroup(br.read_uint8())
    ax = br.read_float()
    ay = br.read_float()
    bx = br.read_float()
    by = br.read_float()
    extra_data = {}
    if fA[0]:
        extra_data["extra_float_1"] = br.read_float()
    if fA[1]:
        extra_data["extra_float_2"] = br.read_float()
    return {"fA": fA.flags, "point_a": (ax, ay), "point_b": (bx, by), **extra_data}

def write_rod(bw, version, entry, data):
    fA = FlagGroup()
    bw.write_uint8(fA.flags & 0xFF)
    ax, ay = data.get("point_a", (0, 0))
    bx, by = data.get("point_b", (0, 0))
    bw.write_float(ax)
    bw.write_float(ay)
    bw.write_float(bx)
    bw.write_float(by)


def read_polygon(br, version, entry):
    """Type 3 - Polygon"""
    fA = FlagGroup(br.read_uint8())
    fB = FlagGroup()
    if version >= 0x23:
        fB = FlagGroup(br.read_uint8())
    extra = {}
    if fA[2]:
        extra["rotation"] = br.read_float()
    if fA[3]:
        extra["unknown_float"] = br.read_float()
    if fA[5]:
        extra["scale"] = br.read_float()
    if fA[1]:
        extra["normal_dir"] = br.read_uint8()
    if fA[4]:
        entry.x = br.read_float()
        entry.y = br.read_float()
    num_points = br.read_int32()
    points = []
    for _ in range(num_points):
        points.append((br.read_float(), br.read_float()))
    if fB[0]:
        extra["fb_unknown_byte"] = br.read_uint8()
    if fB[1]:
        extra["grow_type"] = br.read_int32()
    return {"fA": fA.flags, "fB": fB.flags, "points": points, **extra}

def write_polygon(bw, version, entry, data):
    fA = FlagGroup()
    fB = FlagGroup()
    if entry.movement_link is None:
        fA[4] = True
    bw.write_uint8(fA.flags & 0xFF)
    if version >= 0x23:
        bw.write_uint8(fB.flags & 0xFF)
    if fA[4]:
        bw.write_float(entry.x)
        bw.write_float(entry.y)
    points = data.get("points", [])
    bw.write_int32(len(points))
    for px, py in points:
        bw.write_float(px)
        bw.write_float(py)


def read_brick(br, version, entry):
    """Type 6 - Brick"""
    fA = FlagGroup(br.read_uint8())
    fB = FlagGroup()
    if version >= 0x23:
        fB = FlagGroup(br.read_uint8())
    extra = {}
    if fA[2]:
        extra["fa_float_2"] = br.read_float()
    if fA[3]:
        extra["fa_float_3"] = br.read_float()
    if fA[5]:
        extra["fa_float_5"] = br.read_float()
    if fA[1]:
        extra["fa_byte_1"] = br.read_uint8()
    if fA[4]:
        entry.x = br.read_float()
        entry.y = br.read_float()
    if fB[0]:
        extra["fb_byte_0"] = br.read_uint8()
    if fB[1]:
        extra["fb_int32_1"] = br.read_int32()
    if fB[2]:
        extra["fb_int16_2"] = br.read_int16()

    curved = True
    fC = FlagGroup(br.read_int16())
    extra["fC"] = fC.flags

    if fC[8]:
        extra["fc_float_8"] = br.read_float()
    if fC[9]:
        extra["fc_float_9"] = br.read_float()
    if fC[2]:
        brick_type = br.read_uint8()
        extra["brick_type"] = brick_type
        if brick_type == 5:
            curved = False
    if fC[3]:
        extra["curve_points"] = br.read_uint8() + 2

    if fC[5]:
        extra["left_angle"] = br.read_float()
    if fC[6]:
        extra["right_angle"] = br.read_float()
        extra["right_angle_2"] = br.read_float()
    if fC[4]:
        extra["sector_angle"] = br.read_float()
    if fC[7]:
        extra["width"] = br.read_float()
    extra["texture_flip"] = fC[10]
    extra["length"] = br.read_float()
    extra["angle"] = br.read_float()
    extra["unk_final"] = br.read_uint32()
    extra["curved"] = curved
    return extra

def write_brick(bw, version, entry, data):
    fA = FlagGroup()
    fB = FlagGroup()
    fC = FlagGroup()
    if entry.movement_link is None:
        fA[4] = True
    curved = data.get("curved", False)
    if curved:
        fC[4] = True
        curve_points = data.get("curve_points", 4)
        if curve_points != 4:
            fC[3] = True
    else:
        fC[2] = True
    fC[7] = True
    if data.get("texture_flip", False):
        fC[10] = True

    bw.write_uint8(fA.flags & 0xFF)
    if version >= 0x23:
        bw.write_uint8(fB.flags & 0xFF)
    if fA[4]:
        bw.write_float(entry.x)
        bw.write_float(entry.y)
    bw.write_int16(fC.flags & 0xFFFF)
    if fC[2]:
        bw.write_uint8(5)
    if fC[3]:
        bw.write_uint8(data.get("curve_points", 4) - 2)
    if fC[4]:
        bw.write_float(data.get("sector_angle", 0.0))
    if fC[7]:
        bw.write_float(data.get("width", 20.0))
    bw.write_float(data.get("length", 30.0))
    bw.write_float(data.get("angle", 0.0))
    bw.write_int32(0)  # unknown final


def read_teleport(br, version, entry):
    """Type 8 - Teleport"""
    fA = FlagGroup(br.read_uint8())
    data = {"fA": fA.flags}
    data["width"] = br.read_int32()
    data["height"] = br.read_int32()
    if fA[1]:
        data["legacy_int16"] = br.read_int16()
    if fA[3]:
        data["legacy_int32_1"] = br.read_int32()
    if fA[5]:
        data["legacy_int32_2"] = br.read_int32()
    if fA[4]:
        data["nested_entry"] = read_nested_entry(br, version)
    if fA[2]:
        entry.x = br.read_float()
        entry.y = br.read_float()
    if fA[6]:
        data["extra_float_1"] = br.read_float()
        data["extra_float_2"] = br.read_float()
    return data

def write_teleport(bw, version, entry, data):
    fA = FlagGroup()
    if entry.movement_link is None:
        fA[2] = True
    if data.get("nested_entry") is not None:
        fA[4] = True
    bw.write_uint8(fA.flags & 0xFF)
    bw.write_int32(data.get("width", 20))
    bw.write_int32(data.get("height", 20))
    if fA[4]:
        nested = data["nested_entry"]
        write_entry(bw, version, nested)
    if fA[2]:
        bw.write_float(entry.x)
        bw.write_float(entry.y)
    if fA[6]:
        bw.write_float(0.0)
        bw.write_float(0.0)


def read_emitter(br, version, entry):
    """Type 9 - Emitter"""
    data = {}
    data["main_var"] = br.read_int32()
    fA = FlagGroup(br.read_int16())
    data["fA"] = fA.flags
    data["change_colour"] = fA[8]
    data["transparancy"] = fA[2]
    data["random_start_position"] = fA[4]
    data["change_unknown"] = fA[6]
    data["change_scale"] = fA[7]
    data["change_opacity"] = fA[9]
    data["change_velocity"] = fA[10]
    data["change_direction"] = fA[11]
    data["change_rotation"] = fA[12]

    data["image"] = br.read_popcap_string()
    data["width"] = br.read_int32()
    data["height"] = br.read_int32()

    if data["main_var"] == 2:
        data["main_var_0"] = br.read_int32()
        data["main_var_1"] = br.read_float()
        data["main_var_2"] = br.read_popcap_string()
        data["main_var_3"] = br.read_uint8()
        if fA[13]:
            data["unknown_vf_0"] = VariableFloat.read(br)
            data["unknown_vf_1"] = VariableFloat.read(br)

    if fA[5]:
        entry.x = br.read_float()
        entry.y = br.read_float()

    data["emit_image"] = br.read_popcap_string()
    data["unknown_emit_rate"] = br.read_float()
    data["unknown_2"] = br.read_float()
    data["rotation"] = br.read_float()
    data["max_quantity"] = br.read_int32()
    data["time_before_fade_out"] = br.read_float()
    data["fade_in_time"] = br.read_float()
    data["life_duration"] = br.read_float()
    data["emit_rate"] = VariableFloat.read(br)
    data["emit_area_multiplier"] = VariableFloat.read(br)

    if fA[12]:
        data["initial_rotation"] = VariableFloat.read(br)
        data["rotation_velocity"] = VariableFloat.read(br)
        data["rotation_unknown"] = br.read_float()
    if fA[7]:
        data["min_scale"] = VariableFloat.read(br)
        data["scale_velocity"] = VariableFloat.read(br)
        data["max_rand_scale"] = br.read_float()
    if fA[8]:
        data["colour_red"] = VariableFloat.read(br)
        data["colour_green"] = VariableFloat.read(br)
        data["colour_blue"] = VariableFloat.read(br)
    if fA[9]:
        data["opacity"] = VariableFloat.read(br)
    if fA[10]:
        data["min_velocity_x"] = VariableFloat.read(br)
        data["min_velocity_y"] = VariableFloat.read(br)
        data["max_velocity_x"] = br.read_float()
        data["max_velocity_y"] = br.read_float()
        data["acceleration_x"] = br.read_float()
        data["acceleration_y"] = br.read_float()
    if fA[11]:
        data["direction_speed"] = br.read_float()
        data["direction_random_speed"] = br.read_float()
        data["direction_acceleration"] = br.read_float()
        data["direction_angle"] = br.read_float()
        data["direction_random_angle"] = br.read_float()
    if fA[6]:
        data["unknown_a"] = br.read_float()
        data["unknown_b"] = br.read_float()
    return data

def write_emitter(bw, version, entry, data):
    fA = FlagGroup()
    fA[2] = data.get("transparancy", False)
    fA[4] = data.get("random_start_position", False)
    if entry.movement_link is None:
        fA[5] = True
    fA[6] = data.get("change_unknown", False)
    fA[7] = data.get("change_scale", False)
    fA[8] = data.get("change_colour", False)
    fA[9] = data.get("change_opacity", False)
    fA[10] = data.get("change_velocity", False)
    fA[11] = data.get("change_direction", False)
    fA[12] = data.get("change_rotation", False)
    fA[14] = True

    bw.write_int32(data.get("main_var", 2))
    bw.write_int16(fA.flags & 0xFFFF)
    bw.write_popcap_string(data.get("image", ""))
    bw.write_int32(data.get("width", 100))
    bw.write_int32(data.get("height", 100))

    if data.get("main_var", 2) == 2:
        bw.write_int32(data.get("main_var_0", 0))
        bw.write_float(data.get("main_var_1", 1.0))
        bw.write_popcap_string(data.get("main_var_2", ""))
        bw.write_uint8(data.get("main_var_3", 1))
        if fA[13]:
            data.get("unknown_vf_0", VariableFloat()).write(bw)
            data.get("unknown_vf_1", VariableFloat()).write(bw)

    if fA[5]:
        bw.write_float(entry.x)
        bw.write_float(entry.y)

    bw.write_popcap_string(data.get("emit_image", ""))
    bw.write_float(data.get("unknown_emit_rate", 0.0))
    bw.write_float(data.get("unknown_2", 0.0))
    bw.write_float(data.get("rotation", 0.0))
    bw.write_int32(data.get("max_quantity", 100))
    bw.write_float(data.get("time_before_fade_out", 0.0))
    bw.write_float(data.get("fade_in_time", 0.0))
    bw.write_float(data.get("life_duration", 0.0))
    data.get("emit_rate", VariableFloat()).write(bw)
    data.get("emit_area_multiplier", VariableFloat()).write(bw)

    if fA[12]:
        data.get("initial_rotation", VariableFloat()).write(bw)
        data.get("rotation_velocity", VariableFloat()).write(bw)
        bw.write_float(data.get("rotation_unknown", 0.0))
    if fA[7]:
        data.get("min_scale", VariableFloat()).write(bw)
        data.get("scale_velocity", VariableFloat()).write(bw)
        bw.write_float(data.get("max_rand_scale", 0.0))
    if fA[8]:
        data.get("colour_red", VariableFloat()).write(bw)
        data.get("colour_green", VariableFloat()).write(bw)
        data.get("colour_blue", VariableFloat()).write(bw)
    if fA[9]:
        data.get("opacity", VariableFloat()).write(bw)
    if fA[10]:
        data.get("min_velocity_x", VariableFloat()).write(bw)
        data.get("min_velocity_y", VariableFloat()).write(bw)
        bw.write_float(data.get("max_velocity_x", 0.0))
        bw.write_float(data.get("max_velocity_y", 0.0))
        bw.write_float(data.get("acceleration_x", 0.0))
        bw.write_float(data.get("acceleration_y", 0.0))
    if fA[11]:
        bw.write_float(data.get("direction_speed", 0.0))
        bw.write_float(data.get("direction_random_speed", 0.0))
        bw.write_float(data.get("direction_acceleration", 0.0))
        bw.write_float(data.get("direction_angle", 0.0))
        bw.write_float(data.get("direction_random_angle", 0.0))
    if fA[6]:
        bw.write_float(data.get("unknown_a", 0.0))
        bw.write_float(data.get("unknown_b", 0.0))


# ──────────────────────────────────────────────
# READ / WRITE ENTRY DISPATCH
# ──────────────────────────────────────────────

ENTRY_READERS = {
    2: read_rod,
    3: read_polygon,
    5: read_circle,
    6: read_brick,
    8: read_teleport,
    9: read_emitter,
}

ENTRY_WRITERS = {
    2: write_rod,
    3: write_polygon,
    5: write_circle,
    6: write_brick,
    8: write_teleport,
    9: write_emitter,
}


def read_entry(br, version):
    """Read a top-level entry. Returns None if magic != 1 (C# CreateLevelEntry behavior)."""
    magic = br.read_int32()
    if magic != 1:
        return None
    entry = LevelEntry()
    entry.magic = magic
    entry.type = br.read_int32()
    entry.entry_type_name = ENTRY_TYPES.get(entry.type, f"Unknown({entry.type})")
    reader = ENTRY_READERS.get(entry.type)
    if reader:
        entry.read_generic(br, version)
        entry.specific_data = reader(br, version, entry)
    else:
        entry.read_generic(br, version)
        entry.specific_data = {"raw_bytes": br.read(br.remaining())}
    return entry

def read_nested_entry(br, version):
    """Mirrors C# LevelEntryFactory.CreateLevelEntry(BinaryReader, int).
    Used for teleport nested entries. Returns None if magic != 1."""
    return read_entry(br, version)

def write_entry(bw, version, entry):
    bw.write_int32(1)  # magic
    bw.write_int32(entry.type)
    writer = ENTRY_WRITERS.get(entry.type)
    if writer:
        entry.write_generic(bw, version)
        writer(bw, version, entry, entry.specific_data or {})
    else:
        entry.write_generic(bw, version)
        raw = (entry.specific_data or {}).get("raw_bytes", b"")
        bw.write(raw)


# ──────────────────────────────────────────────
# LEVEL
# ──────────────────────────────────────────────

class Level:
    __slots__ = ('version', 'unknown_byte', 'num_entries', 'entries')

    def __init__(self):
        self.version = 0
        self.unknown_byte = 0
        self.num_entries = 0
        self.entries = []

    @staticmethod
    def read(data):
        br = BinaryReader(data)
        level = Level()
        level.version = br.read_int32()
        level.unknown_byte = br.read_uint8()
        level.num_entries = br.read_int32()

        for i in range(level.num_entries):
            entry = read_entry(br, level.version)
            if entry is not None:
                level.entries.append(entry)

        return level

    def write(self):
        bw = BinaryWriter()
        bw.write_int32(self.version)
        bw.write_uint8(self.unknown_byte)
        bw.write_int32(len(self.entries))
        for entry in self.entries:
            write_entry(bw, self.version, entry)
        return bw.to_bytes()

    def log(self, title=None):
        if title:
            print(f"\n{'='*80}")
            print(f"  LEVEL: {title}")
            print(f"{'='*80}")
        else:
            print(f"\n{'='*80}")
            print(f"  LEVEL")
            print(f"{'='*80}")

        print(f"  Version: 0x{self.version:02x} ({self.version})")
        print(f"  Unknown byte: {self.unknown_byte}")
        print(f"  Num Entries: {self.num_entries}")
        print(f"{'='*80}")

        for i, entry in enumerate(self.entries):
            print(f"\n{'─'*70}")
            print(f"  ENTRY {i}: {entry.entry_type_name} (type={entry.type})")
            print(f"{'─'*70}")
            print(f"  Position: ({entry.x:.4f}, {entry.y:.4f})")
            entry.log_generic()

            sd = entry.specific_data
            if sd is None:
                continue

            if entry.type == 5:  # Circle
                print(f"  Circle Data:")
                print(f"    FlagA: 0x{sd['fA']:02x}")
                print(f"    Radius: {sd['radius']:.4f}")

            elif entry.type == 2:  # Rod
                ax, ay = sd.get("point_a", (0, 0))
                bx, by = sd.get("point_b", (0, 0))
                print(f"  Rod Data:")
                print(f"    FlagA: 0x{sd['fA']:02x}")
                print(f"    PointA: ({ax:.4f}, {ay:.4f})")
                print(f"    PointB: ({bx:.4f}, {by:.4f})")
                if "extra_float_1" in sd:
                    print(f"    ExtraFloat1: {sd['extra_float_1']:.4f}")
                if "extra_float_2" in sd:
                    print(f"    ExtraFloat2: {sd['extra_float_2']:.4f}")

            elif entry.type == 3:  # Polygon
                pts = sd.get("points", [])
                print(f"  Polygon Data:")
                print(f"    FlagA: 0x{sd.get('fA', 0):02x}, FlagB: 0x{sd.get('fB', 0):02x}")
                print(f"    NumPoints: {len(pts)}")
                for pi, (px, py) in enumerate(pts):
                    print(f"    Point[{pi}]: ({px:.4f}, {py:.4f})")
                if "rotation" in sd:
                    print(f"    Rotation: {sd['rotation']:.4f}")
                if "scale" in sd:
                    print(f"    Scale: {sd['scale']:.4f}")
                if "normal_dir" in sd:
                    print(f"    NormalDir: {sd['normal_dir']}")
                if "grow_type" in sd:
                    print(f"    GrowType: {sd['grow_type']}")

            elif entry.type == 6:  # Brick
                print(f"  Brick Data:")
                print(f"    Curved: {sd.get('curved', False)}")
                print(f"    Length: {sd.get('length', 0):.4f}")
                print(f"    Angle: {sd.get('angle', 0):.4f}")
                if "width" in sd:
                    print(f"    Width: {sd['width']:.4f}")
                if "sector_angle" in sd:
                    print(f"    SectorAngle: {sd['sector_angle']:.4f}")
                if "curve_points" in sd:
                    print(f"    CurvePoints: {sd['curve_points']}")
                if "brick_type" in sd:
                    print(f"    BrickType: {sd['brick_type']}")
                if "texture_flip" in sd:
                    print(f"    TextureFlip: {sd['texture_flip']}")
                if "fC" in sd:
                    print(f"    FlagC: 0x{sd['fC']:04x}")

            elif entry.type == 8:  # Teleport
                print(f"  Teleport Data:")
                print(f"    FlagA: 0x{sd.get('fA', 0):02x}")
                print(f"    Width: {sd.get('width', 0)}")
                print(f"    Height: {sd.get('height', 0)}")
                if "legacy_int16" in sd:
                    print(f"    LegacyInt16: {sd['legacy_int16']}")
                if "legacy_int32_1" in sd:
                    print(f"    LegacyInt32_1: {sd['legacy_int32_1']}")
                if "legacy_int32_2" in sd:
                    print(f"    LegacyInt32_2: {sd['legacy_int32_2']}")
                if "nested_entry" in sd:
                    print(f"    NestedEntry (destination):")
                    nest = sd["nested_entry"]
                    print(f"      Type: {nest.entry_type_name} (type={nest.type})")
                    print(f"      Position: ({nest.x:.4f}, {nest.y:.4f})")
                    if nest.specific_data:
                        npts = nest.specific_data.get("points", [])
                        print(f"      NumPoints: {len(npts)}")
                        for pi, (px, py) in enumerate(npts):
                            print(f"        Point[{pi}]: ({px:.4f}, {py:.4f})")

            elif entry.type == 9:  # Emitter
                print(f"  Emitter Data:")
                print(f"    MainVar: {sd.get('main_var', 0)}")
                print(f"    Image: \"{sd.get('image', '')}\"")
                print(f"    Size: {sd.get('width', 0)} x {sd.get('height', 0)}")
                print(f"    EmitImage: \"{sd.get('emit_image', '')}\"")
                print(f"    Rotation: {sd.get('rotation', 0):.4f}")
                print(f"    MaxQuantity: {sd.get('max_quantity', 0)}")
                print(f"    LifeDuration: {sd.get('life_duration', 0):.4f}")
                print(f"    EmitRate: {sd.get('emit_rate', VariableFloat()).log()}")
                print(f"    TimeBeforeFadeOut: {sd.get('time_before_fade_out', 0):.4f}")
                print(f"    FadeInTime: {sd.get('fade_in_time', 0):.4f}")
                print(f"    Transparancy: {sd.get('transparancy', False)}")
                print(f"    RandomStartPosition: {sd.get('random_start_position', False)}")
                print(f"    ChangeScale: {sd.get('change_scale', False)}")
                print(f"    ChangeColour: {sd.get('change_colour', False)}")
                print(f"    ChangeOpacity: {sd.get('change_opacity', False)}")
                print(f"    ChangeVelocity: {sd.get('change_velocity', False)}")
                print(f"    ChangeDirection: {sd.get('change_direction', False)}")
                print(f"    ChangeRotation: {sd.get('change_rotation', False)}")
                if "emit_area_multiplier" in sd:
                    print(f"    EmitAreaMultiplier: {sd['emit_area_multiplier'].log()}")

        print(f"\n{'='*80}")
        print(f"  END OF LEVEL")
        print(f"{'='*80}\n")


# ──────────────────────────────────────────────
# TEST / DUMP UTILITIES
# ──────────────────────────────────────────────

def load_dat(filepath):
    """Load a .dat file and return a Level object."""
    with open(filepath, 'rb') as f:
        data = f.read()
    return Level.read(data)


def test_roundtrip(level, verbose=False):
    """Test that writing matches original data byte-for-byte (where possible)."""
    original = level.write()
    level2 = Level.read(original)
    rewritten = level2.write()
    match = (original == rewritten)
    if verbose:
        if match:
            print(f"  OK: Round-trip match ({len(original)} bytes)")
        else:
            diff_count = sum(1 for a, b in zip(original, rewritten) if a != b)
            print(f"  FAIL: Round-trip mismatch ({diff_count} diffs, {len(original)} vs {len(rewritten)} bytes)")
    return match


def test_all_in_pak(pak_path="peggle.pak"):
    """Test all .dat level files from the PAK."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from extract import PakFile

    pak = PakFile(pak_path).parse()
    dat_records = [(i, rec) for i, rec in enumerate(pak.records)
                   if '.dat' in rec.name and 'levels' in rec.name and 'cached' not in rec.name]

    print(f"Encontrados {len(dat_records)} .dat levels no PAK")
    print()

    ok_count = 0
    fail_count = 0
    fail_details = []

    with open(pak_path, 'rb') as f:
        for idx, rec in dat_records:
            name = rec.name.replace('\\', '/')
            f.seek(rec.data_start)
            raw_data = f.read(rec.size)

            try:
                level = Level.read(raw_data)
                roundtrip_data = level.write()

                # Check if round-trip is bit-identical
                if raw_data == roundtrip_data:
                    ok_count += 1
                else:
                    diff_count = sum(1 for a, b in zip(raw_data, roundtrip_data) if a != b)
                    max_len = max(len(raw_data), len(roundtrip_data))
                    fail_count += 1
                    fail_details.append((name, diff_count, len(raw_data), len(roundtrip_data)))
                    print(f"  DIFERENCA: {name} - {diff_count} bytes diferem ({len(raw_data)} vs {len(roundtrip_data)})")
            except Exception as e:
                fail_count += 1
                fail_details.append((name, -1, 0, 0))
                print(f"  ERRO: {name} - {e}")

    print(f"\nResultado: {ok_count} OK, {fail_count} FALHA(S) de {len(dat_records)}")

    if fail_details:
        print(f"\nDetalhes das falhas:")
        for name, diffs, orig_size, new_size in fail_details:
            if diffs >= 0:
                print(f"  {name}: {diffs} bytes diferentes (original={orig_size}, reescrito={new_size})")
            else:
                print(f"  {name}: ERRO de parse")

    return ok_count, fail_count


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Peggle PS3 .dat Level Reader / Parser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python levelreader.py extracted/levels/level1.dat     # Ler e logar um nivel
  python levelreader.py --all                             # Testar todos os niveis do .pak
  python levelreader.py --test                            # Round-trip test em todos
  python levelreader.py test_levels/level1.dat            # Ler de diretorio extraido
        """)
    parser.add_argument('file', nargs='?', help="Caminho do arquivo .dat de level")
    parser.add_argument('--all', action='store_true',
                        help="Testar todos os .dat levels no peggle.pak")
    parser.add_argument('--test', action='store_true',
                        help="Executar round-trip test em todos os .dat")
    parser.add_argument('--pak', default='peggle.pak',
                        help="Caminho do .pak (padrao: peggle.pak)")

    args = parser.parse_args()

    if args.test:
        ok, fail = test_all_in_pak(args.pak)
        sys.exit(0 if fail == 0 else 1)

    if args.all:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from extract import PakFile

        pak = PakFile(args.pak).parse()
        dat_records = [(i, rec) for i, rec in enumerate(pak.records)
                       if '.dat' in rec.name and 'levels' in rec.name and 'cached' not in rec.name]

        print(f"Encontrados {len(dat_records)} .dat levels no PAK\n")

        with open(args.pak, 'rb') as f:
            for idx, rec in dat_records:
                name = rec.name.replace('\\', '/')
                f.seek(rec.data_start)
                raw_data = f.read(rec.size)
                try:
                    level = Level.read(raw_data)
                    level.log(title=name)
                except Exception as e:
                    print(f"ERRO ao parsear {name}: {e}")

        sys.exit(0)

    if args.file:
        filepath = os.path.expanduser(os.path.expandvars(args.file.strip()))
        if not os.path.exists(filepath):
            head, tail = os.path.split(filepath)
            alt_path = head + '\\' + tail
            if alt_path != filepath and os.path.exists(alt_path):
                filepath = alt_path
            else:
                print(f"Erro: arquivo '{args.file}' nao encontrado")
                sys.exit(1)
        try:
            level = load_dat(filepath)
            level.log(title=args.file)
        except Exception as e:
            import traceback
            print(f"Erro ao parsear '{args.file}': {e}")
            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)

    parser.print_help()


if __name__ == '__main__':
    main()
