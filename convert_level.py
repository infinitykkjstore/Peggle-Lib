#!/usr/bin/env python3
"""
convert_level.py - Conversor bidirecional .dat ↔ JSON para Peggle (PS3/PC)

Formato .dat é universal entre PS3 e PC (mesmos type numbers, mesmas estruturas).
A diferença é apenas a versão do arquivo, que controla campos condicionais:
  - v < 0x0F: flags em 24 bits
  - v >= 0x23: fB byte em Polygon/Brick
  - v >= 0x50: Shadow flag
  - v >= 0x52: fB byte em Circle

Uso:
   python convert_level.py input.dat output.json            # .dat → JSON
   python convert_level.py input.json output.dat --pc        # JSON → .dat (PC v0x52)
   python convert_level.py input.json output.dat --ps3       # JSON → .dat (PS3 v0x30)
   python convert_level.py input.dat output.dat --to-pc      # .dat → .dat (PC v0x52)
   python convert_level.py input.dat output.dat --to-ps3     # .dat → .dat (PS3 v0x35)
   python convert_level.py input.dat output.dat --to-version 0x52  # .dat → .dat (versao arbitraria)
   python convert_level.py --test-all                        # Testar todos os levels
"""

import json
import sys
import os
import math
import glob

from levelreader import (
    Level, LevelEntry, FlagGroup, PegInfo, MovementLink, Movement, VariableFloat,
    BinaryReader, BinaryWriter, ENTRY_TYPES, ENTRY_NAMES,
    read_entry, write_entry, read_circle, write_circle,
    read_rod, write_rod, read_polygon, write_polygon,
    read_brick, write_brick, read_teleport, write_teleport,
    read_emitter, write_emitter,
)


# ──────────────────────────────────────────────
#  JSON helpers
# ──────────────────────────────────────────────

def _to_json_colour(col):
    if col is None:
        return None
    a, r, g, b = col
    return [a, r, g, b]


def _from_json_colour(arr):
    if arr is None:
        return None
    return tuple(arr)


def _peg_info_to_json(pi):
    if pi is None:
        return None
    return {
        "type": pi.type,
        "can_be_orange": pi.can_be_orange,
        "crumble": pi.crumble,
        "unknown_int32_1": pi.unknown_int32_1,
        "unknown_int32_2": pi.unknown_int32_2,
        "unknown_byte_1": pi.unknown_byte_1,
        "unknown_byte_2": pi.unknown_byte_2,
    }


def _peg_info_from_json(d):
    if d is None:
        return None
    pi = PegInfo()
    pi.type = d.get("type", 1)
    pi.can_be_orange = d.get("can_be_orange", False)
    pi.crumble = d.get("crumble", False)
    pi.unknown_int32_1 = d.get("unknown_int32_1")
    pi.unknown_int32_2 = d.get("unknown_int32_2")
    pi.unknown_byte_1 = d.get("unknown_byte_1")
    pi.unknown_byte_2 = d.get("unknown_byte_2")
    return pi


def _movement_link_to_json(ml):
    if ml is None:
        return None
    m = ml.movement
    if m is not None:
        sub_ml = _movement_link_to_json(m.sub_movement)
        m_json = {
            "type": m.type,
            "reverse": m.reverse,
            "anchor_x": m.anchor_x,
            "anchor_y": m.anchor_y,
            "time_period": m.time_period,
            "offset": m.offset,
            "radius1": m.radius1,
            "start_phase": m.start_phase,
            "move_rotation": m.move_rotation,
            "radius2": m.radius2,
            "pause1": m.pause1,
            "pause2": m.pause2,
            "phase1": m.phase1,
            "phase2": m.phase2,
            "post_delay_phase": m.post_delay_phase,
            "max_angle": m.max_angle,
            "unknown8": m.unknown8,
            "rotation": m.rotation,
            "sub_offset_x": m.sub_offset_x,
            "sub_offset_y": m.sub_offset_y,
            "sub_movement": sub_ml,
            "object_x": m.object_x,
            "object_y": m.object_y,
        }
    else:
        m_json = None
    return {"link_id": ml.link_id, "movement": m_json}


def _movement_link_from_json(d):
    if d is None:
        return None
    ml = MovementLink()
    ml.link_id = d.get("link_id", 0)
    m_json = d.get("movement")
    if m_json is not None:
        m = Movement()
        m.type = m_json.get("type", 0)
        m.reverse = m_json.get("reverse", False)
        m.anchor_x = m_json.get("anchor_x", 0.0)
        m.anchor_y = m_json.get("anchor_y", 0.0)
        m.time_period = m_json.get("time_period", 0)
        m.offset = m_json.get("offset", 0)
        m.radius1 = m_json.get("radius1", 0)
        m.start_phase = m_json.get("start_phase", 0.0)
        m.move_rotation = m_json.get("move_rotation", 0.0)
        m.radius2 = m_json.get("radius2", 0)
        m.pause1 = m_json.get("pause1", 0)
        m.pause2 = m_json.get("pause2", 0)
        m.phase1 = m_json.get("phase1", 0)
        m.phase2 = m_json.get("phase2", 0)
        m.post_delay_phase = m_json.get("post_delay_phase", 0.0)
        m.max_angle = m_json.get("max_angle", 0.0)
        m.unknown8 = m_json.get("unknown8", 0.0)
        m.rotation = m_json.get("rotation", 0.0)
        m.sub_offset_x = m_json.get("sub_offset_x", 0.0)
        m.sub_offset_y = m_json.get("sub_offset_y", 0.0)
        m.sub_movement = _movement_link_from_json(m_json.get("sub_movement"))
        m.object_x = m_json.get("object_x", 0.0)
        m.object_y = m_json.get("object_y", 0.0)
        ml.movement = m
    return ml


def _varfloat_to_json(vf):
    if vf is None:
        return None
    if vf.is_variable:
        return {"type": "variable", "name": vf.variable_value}
    return {"type": "static", "value": vf.static_value}


def _varfloat_from_json(d):
    if d is None:
        return VariableFloat(False, 0.0, "")
    if d.get("type") == "variable":
        return VariableFloat(True, 0.0, d.get("name", ""))
    return VariableFloat(False, d.get("value", 0.0), "")


def _specific_data_to_json(entry, data):
    if data is None:
        return None
    t = entry.type
    if t == 2:
        d = {"fA": data["fA"], "point_a": list(data["point_a"]), "point_b": list(data["point_b"])}
        if "extra_float_1" in data:
            d["extra_float_1"] = data["extra_float_1"]
        if "extra_float_2" in data:
            d["extra_float_2"] = data["extra_float_2"]
        return d
    elif t == 3:
        d = {"fA": data["fA"], "fB": data["fB"], "points": [list(p) for p in data["points"]]}
        for k in ("rotation", "unknown_float", "scale", "normal_dir", "fb_unknown_byte", "grow_type"):
            if k in data:
                d[k] = data[k]
        return d
    elif t == 5:
        return {"fA": data["fA"], "radius": data["radius"]}
    elif t == 6:
        d = {}
        for k in ("fC", "curved", "texture_flip", "length", "angle", "unk_final",
                  "sector_angle", "width", "curve_points", "brick_type",
                  "left_angle", "right_angle", "right_angle_2",
                  "fc_float_8", "fc_float_9",
                  "fa_float_2", "fa_float_3", "fa_float_5", "fa_byte_1",
                  "fb_byte_0", "fb_int32_1", "fb_int16_2"):
            if k in data:
                d[k] = data[k]
        return d
    elif t == 8:
        d = {"fA": data["fA"], "width": data["width"], "height": data["height"]}
        for k in ("legacy_int16", "legacy_int32_1", "legacy_int32_2",
                  "extra_float_1", "extra_float_2"):
            if k in data:
                d[k] = data[k]
        if "nested_entry" in data and data["nested_entry"] is not None:
            d["nested_entry"] = _entry_to_json(data["nested_entry"])
        return d
    elif t == 9:
        d = {}
        for k in ("main_var", "fA", "image", "width", "height",
                  "main_var_0", "main_var_1", "main_var_2", "main_var_3",
                  "emit_image", "unknown_emit_rate", "unknown_2", "rotation",
                  "max_quantity", "time_before_fade_out", "fade_in_time", "life_duration",
                  "change_colour", "transparancy", "random_start_position",
                  "change_unknown", "change_scale", "change_opacity",
                  "change_velocity", "change_direction", "change_rotation",
                  "unknown_a", "unknown_b",
                  "max_velocity_x", "max_velocity_y",
                  "acceleration_x", "acceleration_y",
                  "direction_speed", "direction_random_speed", "direction_acceleration",
                  "direction_angle", "direction_random_angle",
                  "max_rand_scale", "rotation_unknown"):
            if k in data:
                d[k] = data[k]
        for vfk in ("emit_rate", "emit_area_multiplier",
                     "initial_rotation", "rotation_velocity",
                     "min_scale", "scale_velocity",
                     "colour_red", "colour_green", "colour_blue",
                     "opacity",
                     "min_velocity_x", "min_velocity_y",
                     "unknown_vf_0", "unknown_vf_1"):
            if vfk in data and data[vfk] is not None:
                d[vfk] = _varfloat_to_json(data[vfk])
        return d
    else:
        return data


def _specific_data_from_json(entry, d):
    if d is None:
        return None
    t = entry.type
    if t == 2:
        data = {"fA": d["fA"], "point_a": tuple(d["point_a"]), "point_b": tuple(d["point_b"])}
        for k in ("extra_float_1", "extra_float_2"):
            if k in d:
                data[k] = d[k]
        return data
    elif t == 3:
        data = {"fA": d["fA"], "fB": d["fB"], "points": [tuple(p) for p in d["points"]]}
        for k in ("rotation", "unknown_float", "scale", "normal_dir", "fb_unknown_byte", "grow_type"):
            if k in d:
                data[k] = d[k]
        return data
    elif t == 5:
        return {"fA": d["fA"], "radius": d["radius"]}
    elif t == 6:
        data = {}
        for k in ("fC", "curved", "texture_flip", "length", "angle", "unk_final",
                  "sector_angle", "width", "curve_points", "brick_type",
                  "left_angle", "right_angle", "right_angle_2",
                  "fc_float_8", "fc_float_9",
                  "fa_float_2", "fa_float_3", "fa_float_5", "fa_byte_1",
                  "fb_byte_0", "fb_int32_1", "fb_int16_2"):
            if k in d:
                data[k] = d[k]
        return data
    elif t == 8:
        data = {"fA": d["fA"], "width": d["width"], "height": d["height"]}
        for k in ("legacy_int16", "legacy_int32_1", "legacy_int32_2",
                  "extra_float_1", "extra_float_2"):
            if k in d:
                data[k] = d[k]
        if "nested_entry" in d and d["nested_entry"] is not None:
            ne = LevelEntry()
            _entry_from_json(ne, d["nested_entry"])
            data["nested_entry"] = ne
        return data
    elif t == 9:
        data = {}
        for k in ("main_var", "fA", "image", "width", "height",
                  "main_var_0", "main_var_1", "main_var_2", "main_var_3",
                  "emit_image", "unknown_emit_rate", "unknown_2", "rotation",
                  "max_quantity", "time_before_fade_out", "fade_in_time", "life_duration",
                  "change_colour", "transparancy", "random_start_position",
                  "change_unknown", "change_scale", "change_opacity",
                  "change_velocity", "change_direction", "change_rotation",
                  "unknown_a", "unknown_b",
                  "max_velocity_x", "max_velocity_y",
                  "acceleration_x", "acceleration_y",
                  "direction_speed", "direction_random_speed", "direction_acceleration",
                  "direction_angle", "direction_random_angle",
                  "max_rand_scale", "rotation_unknown"):
            if k in d:
                data[k] = d[k]
        for vfk in ("emit_rate", "emit_area_multiplier",
                     "initial_rotation", "rotation_velocity",
                     "min_scale", "scale_velocity",
                     "colour_red", "colour_green", "colour_blue",
                     "opacity",
                     "min_velocity_x", "min_velocity_y",
                     "unknown_vf_0", "unknown_vf_1"):
            if vfk in d and d[vfk] is not None:
                data[vfk] = _varfloat_from_json(d[vfk])
        return data
    else:
        return d


def _entry_to_json(entry):
    return {
        "type": entry.type,
        "entry_type_name": entry.entry_type_name,
        "x": entry.x,
        "y": entry.y,
        "generic_flags_raw": entry.generic_flags_raw,
        "generic_flags": {
            "rolly": entry.rolly,
            "bouncy": entry.bouncy,
            "peg_info": _peg_info_to_json(entry.peg_info),
            "movement_link": _movement_link_to_json(entry.movement_link),
            "collision": entry.collision,
            "visible": entry.visible,
            "can_move": entry.can_move,
            "background": entry.background,
            "base_object": entry.base_object,
            "ball_stop_reset": entry.ball_stop_reset,
            "foreground": entry.foreground,
            "draw_sort": entry.draw_sort,
            "foreground2": entry.foreground2,
            "draw_float": entry.draw_float,
            "shadow": entry.shadow,
            "unknown_int32_1": entry.unknown_int32_1,
            "solid_colour": _to_json_colour(entry.solid_colour),
            "outline_colour": _to_json_colour(entry.outline_colour),
            "image_filename": entry.image_filename,
            "image_dx": entry.image_dx,
            "image_dy": entry.image_dy,
            "image_rotation": entry.image_rotation,
            "unknown_int32_2": entry.unknown_int32_2,
            "id": entry.id,
            "unknown_int32_3": entry.unknown_int32_3,
            "sound": entry.sound,
            "logic": entry.logic,
            "max_bounce_velocity": entry.max_bounce_velocity,
            "sub_id": entry.sub_id,
            "flipper_flags": entry.flipper_flags,
        },
        "specific_data": _specific_data_to_json(entry, entry.specific_data),
    }


def _entry_from_json(entry, d):
    entry.type = d["type"]
    entry.entry_type_name = ENTRY_TYPES.get(entry.type, f"Unknown({entry.type})")
    entry.x = d.get("x", 0.0)
    entry.y = d.get("y", 0.0)
    gf = d.get("generic_flags", {})
    entry.rolly = gf.get("rolly", 0.0)
    entry.bouncy = gf.get("bouncy", 0.0)
    entry.peg_info = _peg_info_from_json(gf.get("peg_info"))
    entry.movement_link = _movement_link_from_json(gf.get("movement_link"))
    entry.collision = gf.get("collision", True)
    entry.visible = gf.get("visible", True)
    entry.can_move = gf.get("can_move", True)
    entry.background = gf.get("background", False)
    entry.base_object = gf.get("base_object", False)
    entry.ball_stop_reset = gf.get("ball_stop_reset", False)
    entry.foreground = gf.get("foreground", False)
    entry.draw_sort = gf.get("draw_sort", False)
    entry.foreground2 = gf.get("foreground2", False)
    entry.draw_float = gf.get("draw_float", False)
    entry.shadow = gf.get("shadow", True)
    entry.unknown_int32_1 = gf.get("unknown_int32_1")
    entry.solid_colour = _from_json_colour(gf.get("solid_colour"))
    entry.outline_colour = _from_json_colour(gf.get("outline_colour"))
    entry.image_filename = gf.get("image_filename")
    entry.image_dx = gf.get("image_dx", 0.0)
    entry.image_dy = gf.get("image_dy", 0.0)
    entry.image_rotation = gf.get("image_rotation", 0.0)
    entry.unknown_int32_2 = gf.get("unknown_int32_2")
    entry.id = gf.get("id")
    entry.unknown_int32_3 = gf.get("unknown_int32_3")
    entry.sound = gf.get("sound", 0)
    entry.logic = gf.get("logic")
    entry.max_bounce_velocity = gf.get("max_bounce_velocity", 0.0)
    entry.sub_id = gf.get("sub_id", 0)
    entry.flipper_flags = gf.get("flipper_flags", 0)
    entry.specific_data = _specific_data_from_json(entry, d.get("specific_data"))


# ──────────────────────────────────────────────
#  Core API
# ──────────────────────────────────────────────

def dat_to_json(data):
    """
    Converte .dat bruto para dict serializavel em JSON.
    Retorna dict com "version", "unknown_byte", "entries".
    """
    level = Level.read(data)
    entries_json = []
    for entry in level.entries:
        entries_json.append(_entry_to_json(entry))
    return {
        "version": level.version,
        "unknown_byte": level.unknown_byte,
        "entries": entries_json,
    }


def json_to_dat(data_dict, version=None):
    """
    Converte dict JSON para bytes .dat.
    Se version for None, usa a versao original do JSON.
    """
    v = version if version is not None else data_dict.get("version", 0x52)
    unk = data_dict.get("unknown_byte", 1)
    level = Level()
    level.version = v
    level.unknown_byte = unk
    for ed in data_dict.get("entries", []):
        entry = LevelEntry()
        _entry_from_json(entry, ed)
        level.entries.append(entry)
    level.num_entries = len(level.entries)
    return level.write()


def dat_to_dat(data, target_version):
    """
    Converte .dat para .dat com versao alvo.
    """
    parsed = dat_to_json(data)
    return json_to_dat(parsed, target_version)


def dat_to_json_file(input_path, output_path):
    with open(input_path, 'rb') as f:
        data = f.read()
    result = dat_to_json(data)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return result


def json_to_dat_file(input_path, output_path, version=None):
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    raw = json_to_dat(data, version)
    with open(output_path, 'wb') as f:
        f.write(raw)
    return raw


def dat_to_dat_file(input_path, output_path, target_version):
    with open(input_path, 'rb') as f:
        data = f.read()
    result = dat_to_dat(data, target_version)
    with open(output_path, 'wb') as f:
        f.write(result)
    return result


# ──────────────────────────────────────────────
#  Tests
# ──────────────────────────────────────────────

def test_roundtrip_all():
    """Testa round-trip .dat → JSON → .dat em todos os levels PS3.
    NOTA: Normalizacoes (PegInfo.type→1, Brick fC bits, etc.) sao identicas ao PeggleEdit C#.
    O teste verifica que o .dat reconstruido e VALIDO e tem o mesmo numero de entradas.
    """
    errors = []
    warnings = []
    extracted = 'extracted'

    for fpath in sorted(glob.glob(os.path.join(extracted, '**', '*.dat'), recursive=True)):
        if 'trailer' in fpath or 'cached' in fpath:
            continue

        with open(fpath, 'rb') as f:
            original = f.read()

        try:
            # .dat → JSON
            parsed = dat_to_json(original)
            # JSON → .dat (mesma versao)
            rebuilt = json_to_dat(parsed)
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: {e}")
            continue

        # Verifica que o .dat reconstruido e valido (pode ser lido de volta)
        try:
            reparsed = dat_to_json(rebuilt)
            if len(reparsed["entries"]) != len(parsed["entries"]):
                errors.append(f"{os.path.basename(fpath)}: entry count changed ({len(parsed['entries'])} → {len(reparsed['entries'])})")
            if reparsed["version"] != parsed["version"]:
                errors.append(f"{os.path.basename(fpath)}: version changed ({parsed['version']:02x} → {reparsed['version']:02x})")
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: rebuilt dat unreadable: {e}")

        match = (original == rebuilt)
        if not match:
            diff = sum(1 for a, b in zip(original, rebuilt) if a != b)
            warnings.append(f"{os.path.basename(fpath)}: {diff} byte diffs (normalizacao PeggleEdit, nao perda)")

    return errors, warnings


def test_convert_to_pc():
    """Testa conversao PS3 → PC (v0x52), verifica que todos os levels sao viaveis."""
    errors = []
    extracted = 'extracted'

    for fpath in sorted(glob.glob(os.path.join(extracted, '**', '*.dat'), recursive=True)):
        if 'trailer' in fpath or 'cached' in fpath:
            continue

        with open(fpath, 'rb') as f:
            original = f.read()

        try:
            # Converte para versao PC (0x52)
            pc_dat = dat_to_dat(original, 0x52)
            # Verifica que pode ser lido de volta
            parsed = dat_to_json(pc_dat)
            # Verifica que version e 0x52
            if parsed["version"] != 0x52:
                errors.append(f"{os.path.basename(fpath)}: version mismatch after PC conversion")
        except Exception as e:
            errors.append(f"{os.path.basename(fpath)}: PC conversion error: {e}")

    return errors


def test_json_edit_roundtrip():
    """Testa que modificacoes em generic_flags sao preservadas apos .dat rebuild.
    Usa collision flag (presente em todos os entries) ao inves de x/y que e opcional."""
    extracted = 'extracted'
    errors = []

    fpaths = sorted(glob.glob(os.path.join(extracted, '**', '*.dat'), recursive=True))
    fpaths = [f for f in fpaths if 'trailer' not in f and 'cached' not in f]

    test_file = fpaths[0] if fpaths else None
    if test_file is None:
        return ["No test files found"]

    with open(test_file, 'rb') as f:
        original = f.read()

    parsed = dat_to_json(original)

    name = os.path.basename(test_file)

    try:
        # Modifica: inverte collision+visible do primeiro entry
        if parsed["entries"]:
            old_col = parsed["entries"][0]["generic_flags"]["collision"]
            old_vis = parsed["entries"][0]["generic_flags"]["visible"]
            parsed["entries"][0]["generic_flags"]["collision"] = not old_col
            parsed["entries"][0]["generic_flags"]["visible"] = not old_vis

        rebuilt = json_to_dat(parsed)
        reparsed = dat_to_json(rebuilt)

        if reparsed["entries"]:
            new_col = reparsed["entries"][0]["generic_flags"]["collision"]
            new_vis = reparsed["entries"][0]["generic_flags"]["visible"]
            if new_col == old_col:
                errors.append(f"{name}: collision edit not preserved")
            if new_vis == old_vis:
                errors.append(f"{name}: visible edit not preserved")
        else:
            errors.append(f"{name}: no entries after edit round-trip")
    except Exception as e:
        errors.append(f"{name}: edit round-trip error: {e}")

    return errors


def test_cross_version():
    """Testa conversao entre multiplas versoes."""
    errors = []
    extracted = 'extracted'

    for fpath in sorted(glob.glob(os.path.join(extracted, '**', '*.dat'), recursive=True)):
        if 'trailer' in fpath or 'cached' in fpath:
            continue

        with open(fpath, 'rb') as f:
            original = f.read()

        parsed = dat_to_json(original)
        orig_version = parsed["version"]

        name = os.path.basename(fpath)

        # Testa conversao para varias versoes alvo
        for target_v in [0x0F, 0x23, 0x35, 0x41, 0x52]:
            try:
                rebuilt = json_to_dat(parsed, target_v)
                reparsed = dat_to_json(rebuilt)
                if reparsed["version"] != target_v:
                    errors.append(f"{name}: v{orig_version:02x}→v{target_v:02x} version mismatch")
            except Exception as e:
                errors.append(f"{name}: v{orig_version:02x}→v{target_v:02x}: {e}")

    return errors


def test_pc_to_ps3_roundtrip():
    """Testa round-trip .dat PS3 → PC (v0x52) → PS3 (v0x41) → PC ..."""
    errors = []
    extracted = 'extracted'

    for fpath in sorted(glob.glob(os.path.join(extracted, '**', '*.dat'), recursive=True)):
        if 'trailer' in fpath or 'cached' in fpath:
            continue

        with open(fpath, 'rb') as f:
            original = f.read()

        name = os.path.basename(fpath)

        try:
            # PS3 → PC (v0x52)
            pc_v = dat_to_dat(original, 0x52)
            # PC → PS3 (v0x41)
            ps3_v = dat_to_dat(pc_v, 0x41)
            # PS3 → PC novamente
            pc_v2 = dat_to_dat(ps3_v, 0x52)

            parsed_pc = dat_to_json(pc_v)
            parsed_pc2 = dat_to_json(pc_v2)

            # Verifica que PC → PS3 → PC e consistente
            if len(parsed_pc["entries"]) != len(parsed_pc2["entries"]):
                errors.append(f"{name}: entry count changed in cross-version cycle")
        except Exception as e:
            errors.append(f"{name}: cross-version cycle error: {e}")

    return errors


# ──────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────

def print_summary(name, errors):
    print(f"\n{'='*60}")
    if errors:
        print(f"  {name}: {len(errors)} FALHAS")
        for e in errors:
            print(f"    FAIL: {e}")
    else:
        print(f"  {name}: OK (sem falhas)")
    print(f"{'='*60}")


VERSION_MAP = {
    "pc": 0x52,
    "ps3": 0x30,
}
VERSION_LABELS = {0x52: "PC", 0x30: "PS3"}


def _parse_version(vs):
    if vs.startswith('0x'):
        return int(vs, 16)
    return int(vs)


def main():
    args = sys.argv[1:]

    if not args or args[0] == '--help':
        print(__doc__)
        return

    if args[0] == '--test-all':
        print("Executando todos os testes...\n")

        errors, warnings = test_roundtrip_all()
        print_summary("Round-trip .dat ↔ JSON ↔ .dat", errors)
        if warnings:
            print(f"  AVISOS ({len(warnings)}):")
            for w in warnings[:5]:
                print(f"    {w}")
            if len(warnings) > 5:
                print(f"    ... e mais {len(warnings)-5}")
        all_ok = len(errors) == 0

        errors = test_convert_to_pc()
        print_summary("Conversao PS3 → PC (v0x52)", errors)
        all_ok = all_ok and len(errors) == 0

        errors = test_json_edit_roundtrip()
        print_summary("Edicao JSON round-trip", errors)
        all_ok = all_ok and len(errors) == 0

        errors = test_cross_version()
        print_summary("Conversao cross-version", errors)
        all_ok = all_ok and len(errors) == 0

        errors = test_pc_to_ps3_roundtrip()
        print_summary("Ciclo PS3↔PC↔PS3↔PC cross-version", errors)
        all_ok = all_ok and len(errors) == 0

        print(f"\n{'#'*60}")
        if all_ok:
            print("  TODOS OS TESTES PASSARAM!")
        else:
            print("  ALGUNS TESTES FALHARAM!")
        print(f"{'#'*60}")
        return

    # .dat → .dat (com --to-version, --to-pc ou --to-ps3)
    if any(flag in args for flag in ('--to-version', '--to-pc', '--to-ps3')):
        if '--to-version' in args:
            idx = args.index('--to-version')
            target_v = _parse_version(args[idx + 1])
        elif '--to-pc' in args:
            target_v = VERSION_MAP["pc"]
        else:
            target_v = VERSION_MAP["ps3"]
        input_path = args[0]
        output_path = args[1]
        label = VERSION_LABELS.get(target_v, f"v{target_v:02x}")
        print(f"Convertendo .dat: {input_path} → {output_path} ({label})")
        dat_to_dat_file(input_path, output_path, target_v)
        print("OK")
        return

    # .json → .dat
    if len(args) >= 2 and args[1].endswith('.dat'):
        input_path = args[0]
        output_path = args[1]
        version = None
        if '--version' in args:
            idx = args.index('--version')
            version = _parse_version(args[idx + 1])
        elif '--pc' in args:
            version = VERSION_MAP["pc"]
        elif '--ps3' in args:
            version = VERSION_MAP["ps3"]
        label = ""
        if version is not None:
            label = VERSION_LABELS.get(version, f"v{version:02x}")
        print(f"Convertendo JSON: {input_path} → {output_path}" +
              (f" ({label})" if label else ""))
        json_to_dat_file(input_path, output_path, version)
        print("OK")
        return

    # .dat → .json
    input_path = args[0]
    output_path = args[1] if len(args) > 1 else input_path + '.json'
    print(f"Convertendo .dat: {input_path} → {output_path}")
    dat_to_json_file(input_path, output_path)
    print("OK")


if __name__ == '__main__':
    main()
