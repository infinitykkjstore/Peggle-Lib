#!/usr/bin/env python3
"""
levelpreview.py - Renderizador/Pipeline de preview PNG de níveis Peggle (PS3/PC)

Gera uma imagem PNG 800x600 reproduzindo a renderização do Peegle.
Funciona de forma autônoma: assets próprios na pasta assets/, background
obtido do mesmo diretório do .dat.

Uso:
  python levelpreview.py fish.dat preview.png
  python levelpreview.py level1.dat preview.png --no-textures
  python levelpreview.py --test ./pasta_com_dats
  python levelpreview.py --test-one fish.dat
"""

import os
import sys
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from levelreader import Level


CANVAS_W, CANVAS_H = 800, 600
DRAW_ADJ_X, DRAW_ADJ_Y = 73, 43
BG_OFFSET_X, BG_OFFSET_Y = 73, 53
BG_STD_W, BG_STD_H = 646, 543

PEG_OUTER_BLUE = (83, 124, 217)
PEG_OUTER_ORANGE = (234, 140, 22)
PEG_INNER_BLUE = (13, 50, 167)
PEG_INNER_BLUE_CRUMBLE = (214, 254, 255)
PEG_INNER_ORANGE = (131, 35, 6)
PEG_INNER_ORANGE_CRUMBLE = (255, 250, 202)

SHADOW_COLOR = (0, 0, 0, 100)
SHADOW_OFFSET = (-4, 3)
GENERATOR_ORANGE = (234, 140, 22)

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ASSETS_DIR = os.path.join(LIB_DIR, 'assets')


def _load_image_safe(path, mode='RGBA'):
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path)
        if img.mode != mode:
            img = img.convert(mode)
        return img
    except Exception:
        return None


def _tint_image(img, color):
    img = img.convert('RGBA')
    r, g, b = color[0], color[1], color[2]
    pixels = img.load()
    for py in range(img.height):
        for px in range(img.width):
            pr, pg, pb, pa = pixels[px, py]
            pixels[px, py] = (
                min(255, pr * r // 255),
                min(255, pg * g // 255),
                min(255, pb * b // 255),
                pa,
            )
    return img


def _peg_outer_colour(peg_info, show_preview=False):
    if not peg_info:
        return PEG_OUTER_BLUE
    if peg_info.can_be_orange and not show_preview:
        return PEG_OUTER_ORANGE
    return PEG_OUTER_BLUE


def _peg_inner_colour(peg_info, show_preview=False):
    if not peg_info:
        return PEG_INNER_BLUE
    if peg_info.can_be_orange and not show_preview:
        return PEG_INNER_ORANGE_CRUMBLE if peg_info.crumble else PEG_INNER_ORANGE
    else:
        return PEG_INNER_BLUE_CRUMBLE if peg_info.crumble else PEG_INNER_BLUE


def get_entry_position(entry):
    x, y = entry.x, entry.y
    if entry.movement_link and entry.movement_link.movement:
        m = entry.movement_link.movement
        if m.object_x != 0.0 or m.object_y != 0.0:
            x, y = m.object_x, m.object_y
        elif m.anchor_x != 0.0 or m.anchor_y != 0.0:
            x, y = m.anchor_x, m.anchor_y
    return x, y


def _level_name_from_dat(dat_path):
    norm = dat_path.replace('\\', '/')
    return os.path.splitext(os.path.basename(norm))[0]


def load_background(dat_path, search_dir=None):
    if search_dir is None:
        search_dir = os.path.dirname(os.path.abspath(dat_path))
    name = _level_name_from_dat(dat_path)
    for ext in ('.jpg', '.png', '.jp2', '.jpeg'):
        for candidate in (
            os.path.join(search_dir, f'{name}{ext}'),
            os.path.join(search_dir, f'levels\\{name}{ext}'),
            os.path.join(search_dir, f'levels/{name}{ext}'),
        ):
            img = _load_image_safe(candidate)
            if img:
                return img
    return None


def load_entry_image(image_filename, search_dir=None, dat_dir=None):
    if not image_filename:
        return None
    search_dirs = []
    if search_dir:
        search_dirs.append(search_dir)
    if dat_dir and dat_dir != search_dir:
        search_dirs.append(dat_dir)

    key = image_filename.replace('/', '\\')
    for sd in search_dirs:
        for sep in ('\\', '/'):
            for ext in ('.jpg', '.png', '.jp2', '.jpeg'):
                path = os.path.join(sd, f'{key}{ext}')
                img = _load_image_safe(path)
                if img:
                    return img
    return None


class LevelPreview:
    def __init__(self, dat_path, search_dir=None, assets_dir=None,
                 use_textures=True, show_preview=False,
                 debug_labels=False):
        self.dat_path = os.path.abspath(dat_path)
        self.dat_dir = os.path.dirname(self.dat_path)
        self.search_dir = os.path.abspath(search_dir) if search_dir else self.dat_dir
        self.assets_dir = os.path.abspath(assets_dir) if assets_dir else DEFAULT_ASSETS_DIR
        self.use_textures = use_textures
        self.show_preview = show_preview
        self.debug_labels = debug_labels

        with open(dat_path, 'rb') as f:
            self.level = Level.read(f.read())

        self.background = load_background(dat_path, self.search_dir)

        self.peg_sheet = _load_image_safe(os.path.join(self.assets_dir, 'peg.png'))
        self.brick_sheet = _load_image_safe(os.path.join(self.assets_dir, 'brick.png'))
        self.interface_img = _load_image_safe(os.path.join(self.assets_dir, 'interface.png'))
        self.circle_outer = _load_image_safe(os.path.join(self.assets_dir, 'circle_outer.png'))
        self.circle_inner = _load_image_safe(os.path.join(self.assets_dir, 'circle_inner.png'))

    def render(self):
        canvas = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 255))
        self._draw_background(canvas)

        shadow_layer = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
        object_layer = Image.new('RGBA', (CANVAS_W, CANVAS_H), (0, 0, 0, 0))

        for entry in self.level.entries:
            if self.show_preview and not entry.visible:
                continue
            self._draw_entry_shadow(shadow_layer, entry)

        for entry in self.level.entries:
            if self.show_preview and not entry.visible:
                continue
            self._draw_entry(object_layer, entry)

        canvas.paste(shadow_layer, (0, 0), shadow_layer)
        canvas.paste(object_layer, (0, 0), object_layer)

        if self.interface_img:
            canvas.paste(self.interface_img, (0, 0), self.interface_img)

        if self.debug_labels:
            d = ImageDraw.Draw(canvas)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
            except (IOError, OSError):
                font = ImageFont.load_default()
            for idx, entry in enumerate(self.level.entries):
                if self.show_preview and not entry.visible:
                    continue
                x, y = get_entry_position(entry)
                cx, cy = DRAW_ADJ_X + x, DRAW_ADJ_Y + y
                d.text((cx + 5, cy - 20), str(idx), fill='lime', font=font)

        return canvas.convert('RGB')

    def _draw_background(self, canvas):
        if self.background is None:
            return
        bg = self.background
        if bg.size == (BG_STD_W, BG_STD_H):
            canvas.paste(bg, (BG_OFFSET_X, BG_OFFSET_Y))
        else:
            x = CANVAS_W // 2 - bg.width // 2
            y = CANVAS_H // 2 - bg.height // 2
            canvas.paste(bg, (x, y))

    def _draw_entry_shadow(self, canvas, entry):
        if not entry.shadow:
            return
        t = entry.type
        if t == 5:
            self._draw_circle_shape(canvas, entry, shadow=True)
        elif t == 6:
            self._draw_brick_shape(canvas, entry, shadow=True)

    def _draw_entry(self, canvas, entry):
        t = entry.type
        if t == 5:
            self._draw_circle_shape(canvas, entry, shadow=False)
        elif t == 6:
            self._draw_brick_shape(canvas, entry, shadow=False)
        elif t == 2:
            self._draw_rod(canvas, entry)
        elif t == 3:
            self._draw_polygon(canvas, entry)
        elif t == 8:
            self._draw_teleport(canvas, entry)
        elif t == 9:
            self._draw_emitter(canvas, entry)
        elif t in (1001, 1002, 1003, 1004):
            self._draw_generator(canvas, entry)

    def _get_peg_texture_region(self, entry):
        if self.peg_sheet is None:
            return None
        pi = entry.peg_info
        if pi is None:
            return None
        row = 0
        if pi.can_be_orange and not self.show_preview:
            row += 1
        if pi.crumble and not self.show_preview:
            row += 4
        return self.peg_sheet.crop((0, row * 20, 20, (row + 1) * 20))

    def _get_brick_texture_region(self, entry):
        if self.brick_sheet is None:
            return None
        pi = entry.peg_info
        if pi is None:
            return None
        row = 0
        if pi.can_be_orange and not self.show_preview:
            row += 1
        if pi.crumble and not self.show_preview:
            row += 4
        bw = self.brick_sheet.width
        bh = self.brick_sheet.height // 8
        return self.brick_sheet.crop((0, row * bh, bw, (row + 1) * bh))

    def _draw_circle_shape(self, canvas, entry, shadow=False):
        x, y = get_entry_position(entry)
        data = entry.specific_data or {}
        radius = data.get('radius', 10)
        cx = DRAW_ADJ_X + x
        cy = DRAW_ADJ_Y + y

        if shadow:
            d = ImageDraw.Draw(canvas)
            d.ellipse([cx + SHADOW_OFFSET[0] - radius,
                       cy + SHADOW_OFFSET[1] - radius,
                       cx + SHADOW_OFFSET[0] + radius,
                       cy + SHADOW_OFFSET[1] + radius], fill=SHADOW_COLOR)
            return

        d = ImageDraw.Draw(canvas)
        has_peg_info = entry.peg_info is not None

        if has_peg_info:
            if self.use_textures:
                region = self._get_peg_texture_region(entry)
                if region:
                    tex = region.resize((int(radius * 2), int(radius * 2)), Image.LANCZOS)
                    canvas.paste(tex, (int(cx - radius), int(cy - radius)), tex)
                    return

            outer = _peg_outer_colour(entry.peg_info, self.show_preview)
            inner = _peg_inner_colour(entry.peg_info, self.show_preview)
            d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=outer)
            ir = max(1, radius - 2)
            d.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], fill=inner)
        else:
            if entry.image_filename:
                img = load_entry_image(entry.image_filename, self.search_dir, self.dat_dir)
                if img:
                    img_rgba = img.convert('RGBA')
                    cxx = int(cx - img_rgba.width / 2)
                    cyy = int(cy - img_rgba.height / 2)
                    canvas.paste(img_rgba, (cxx, cyy), img_rgba)
                    return

            if self.circle_outer and self.circle_inner:
                col = entry.outline_colour
                if col:
                    tinted = _tint_image(self.circle_outer, col[:3])
                    canvas.paste(tinted, (int(cx - 50), int(cy - 50)), tinted)
                canvas.paste(self.circle_inner, (int(cx - 50), int(cy - 50)), self.circle_inner)

    def _calculate_brick_vertices_local(self, length, width, sector_angle):
        curve_points = 4
        offset = (-10, 0)
        location = [0 + offset[0], 0 + offset[1]]
        inner_radius = length
        outer_radius = inner_radius + width
        circle_centre = (location[0] - inner_radius, location[1])
        div_angle = sector_angle / (curve_points - 1)
        cur_angle = -(sector_angle / 2.0)
        o_pnts, i_pnts = [], []
        for i in range(curve_points):
            a_rad = math.radians(cur_angle)
            o_pnts.append((
                math.cos(a_rad) * outer_radius + circle_centre[0],
                math.sin(a_rad) * outer_radius + circle_centre[1]
            ))
            i_pnts.append((
                math.cos(a_rad) * inner_radius + circle_centre[0],
                math.sin(a_rad) * inner_radius + circle_centre[1]
            ))
            cur_angle += div_angle
        pnts = o_pnts + list(reversed(i_pnts))
        tri_indices = [(0,1,7), (1,6,7), (1,2,6), (2,5,6), (2,3,5), (3,4,5)]
        vertices = [pnts[i] for tri in tri_indices for i in tri]
        tex_coords = [
            (0,0), (1/3,0), (0,1),
            (1/3,0), (1/3,1), (0,1),
            (1/3,0), (2/3,0), (1/3,1),
            (2/3,0), (1/3,1), (1/3,1),
            (2/3,0), (1,0), (2/3,1),
            (1,0), (1,1), (2/3,1),
        ]
        return vertices, tex_coords

    def _render_curved_brick_texture(self, region, length, width, sector_angle, angle, texture_flip, cx, cy):
        supersample = True
        bmp_size = 200 if supersample else 100
        scale = 2 if supersample else 1

        tex = region
        if not texture_flip:
            tex = tex.transpose(Image.FLIP_TOP_BOTTOM)

        verts, uvs = self._calculate_brick_vertices_local(length, width, sector_angle)
        cverts = [(bmp_size / 2 + v[0] * scale, bmp_size / 2 + v[1] * scale) for v in verts]

        bmp = Image.new('RGBA', (bmp_size, bmp_size), (0, 0, 0, 0))
        bp = bmp.load()
        tw, th = tex.width, tex.height

        n_tri = len(verts) // 3
        for ti in range(n_tri):
            vi = ti * 3
            v = cverts[vi:vi+3]
            uv = uvs[vi:vi+3]

            min_x = max(0, int(min(v[0][0], v[1][0], v[2][0])))
            max_x = min(bmp_size - 1, int(max(v[0][0], v[1][0], v[2][0])))
            min_y = max(0, int(min(v[0][1], v[1][1], v[2][1])))
            max_y = min(bmp_size - 1, int(max(v[0][1], v[1][1], v[2][1])))

            denom = ((v[1][1] - v[2][1]) * (v[0][0] - v[2][0]) + (v[2][0] - v[1][0]) * (v[0][1] - v[2][1]))
            if denom == 0:
                continue

            for py in range(min_y, max_y + 1):
                for px in range(min_x, max_x + 1):
                    s0 = (v[0][0] - v[2][0]) * (py - v[2][1]) - (v[0][1] - v[2][1]) * (px - v[2][0])
                    s1 = (v[1][0] - v[0][0]) * (py - v[0][1]) - (v[1][1] - v[0][1]) * (px - v[0][0])
                    if (s0 < 0) != (s1 < 0) and s0 != 0 and s1 != 0:
                        continue
                    d0 = (v[2][0] - v[1][0]) * (py - v[1][1]) - (v[2][1] - v[1][1]) * (px - v[1][0])
                    if not (d0 == 0 or (d0 < 0) == (s0 + s1 <= 0)):
                        continue

                    alpha = ((v[1][1] - v[2][1]) * (px - v[2][0]) + (v[2][0] - v[1][0]) * (py - v[2][1])) / denom
                    beta = ((v[2][1] - v[0][1]) * (px - v[2][0]) + (v[0][0] - v[2][0]) * (py - v[2][1])) / denom
                    gamma = 1 - alpha - beta
                    u_val = alpha * uv[0][0] + beta * uv[1][0] + gamma * uv[2][0]
                    v_val = alpha * uv[0][1] + beta * uv[1][1] + gamma * uv[2][1]

                    u_val = max(0.0, min(1.0, u_val))
                    v_val = max(0.0, min(1.0, v_val))
                    tx = u_val * (tw - 1)
                    ty = v_val * (th - 1)
                    tx0, ty0 = int(math.floor(tx)), int(math.floor(ty))
                    tx1, ty1 = min(tx0 + 1, tw - 1), min(ty0 + 1, th - 1)
                    dx, dy = tx - tx0, ty - ty0
                    c00 = tex.getpixel((tx0, ty0))
                    c10 = tex.getpixel((tx1, ty0))
                    c01 = tex.getpixel((tx0, ty1))
                    c11 = tex.getpixel((tx1, ty1))
                    bp[px, py] = tuple(int(round(
                        (1-dx)*(1-dy)*ch[0] + dx*(1-dy)*ch[1] + (1-dx)*dy*ch[2] + dx*dy*ch[3]
                    )) for ch in zip(c00, c10, c01, c11))

        if supersample:
            bmp = bmp.resize((100, 100), Image.LANCZOS)

        bmp = bmp.rotate(angle, expand=False, center=(50, 50), fillcolor=(0, 0, 0, 0))
        return bmp

    def _get_curved_brick_poly(self, cx, cy, length, width, angle, sector_angle):
        rad = math.radians(angle)
        sr = math.radians(sector_angle)
        sa, ea = -sr / 2, sr / 2
        n = max(6, int(sector_angle / 3))
        ir = length
        o_r = length + width
        cc_x = -10 - length

        cos_a, sin_a = math.cos(rad), math.sin(rad)
        def rot(px, py):
            return (cx + px * cos_a - py * sin_a, cy + px * sin_a + py * cos_a)

        pts = []
        for i in range(n + 1):
            a = sa + (ea - sa) * i / n
            px = cc_x + o_r * math.cos(a)
            py = o_r * math.sin(a)
            pts.append(rot(px, py))
        for i in range(n, -1, -1):
            a = sa + (ea - sa) * i / n
            px = cc_x + ir * math.cos(a)
            py = ir * math.sin(a)
            pts.append(rot(px, py))
        return pts

    def _get_curved_inner_poly(self, cx, cy, length, width, angle, sector_angle):
        rad = math.radians(angle)
        sr = math.radians(sector_angle)
        sa, ea = -sr / 2, sr / 2
        n = max(6, int(sector_angle / 3))
        ir = length
        o_r = length + width
        cc_x = -10 - length
        iw = 2
        ii_r, io_r = ir + iw, o_r - iw
        if io_r <= ii_r:
            return None

        cos_a, sin_a = math.cos(rad), math.sin(rad)
        def rot(px, py):
            return (cx + px * cos_a - py * sin_a, cy + px * sin_a + py * cos_a)

        pts = []
        for i in range(n + 1):
            a = sa + (ea - sa) * i / n
            px = cc_x + io_r * math.cos(a)
            py = io_r * math.sin(a)
            pts.append(rot(px, py))
        for i in range(n, -1, -1):
            a = sa + (ea - sa) * i / n
            px = cc_x + ii_r * math.cos(a)
            py = ii_r * math.sin(a)
            pts.append(rot(px, py))
        return pts

    @staticmethod
    def _adjust_angle_for_movement(entry, angle):
        ml = entry.movement_link
        if ml and ml.movement:
            m = ml.movement
            if m.type == 13:  # RotateAroundCircle
                phase = m.start_phase
                if not m.reverse:
                    phase = 1.0 - phase
                angle = (angle + m.rotation) - (phase * 360.0)
        return angle

    def _draw_brick_shape(self, canvas, entry, shadow=False):
        data = entry.specific_data or {}
        x, y = get_entry_position(entry)
        length = max(1, data.get('length', 30))
        width = max(1, data.get('width', 20))
        angle = self._adjust_angle_for_movement(entry, data.get('angle', 0))
        curved = data.get('curved', False)
        texture_flip = data.get('texture_flip', False)
        cx = DRAW_ADJ_X + x
        cy = DRAW_ADJ_Y + y

        region = (None if shadow or not self.use_textures or not entry.peg_info
                  else self._get_brick_texture_region(entry))

        if region is not None:
            if region.mode != 'RGBA':
                region = region.convert('RGBA')

            if not curved:
                tex = region.resize((int(length), int(width)), Image.LANCZOS)
                if not texture_flip:
                    tex = tex.transpose(Image.FLIP_TOP_BOTTOM)
                tex = tex.rotate(angle - 90, expand=True)
                px = int(cx - tex.width / 2)
                py = int(cy - tex.height / 2)
                canvas.paste(tex, (px, py), tex)
                return

            sector_angle = data.get('sector_angle', 45)
            if sector_angle > 0:
                tex_final = self._render_curved_brick_texture(region, length, width, sector_angle, angle, texture_flip, cx, cy)
                if tex_final:
                    canvas.paste(tex_final, (int(cx - 50), int(cy - 50)), tex_final)
                else:
                    pts = self._get_curved_brick_poly(cx, cy, length, width, angle, sector_angle)
                    d = ImageDraw.Draw(canvas)
                    d.polygon(pts, fill=(255, 0, 255))
                return

        pi = entry.peg_info
        outer = _peg_outer_colour(pi, self.show_preview)
        inner = _peg_inner_colour(pi, self.show_preview)
        d = ImageDraw.Draw(canvas)

        if curved and data.get('sector_angle', 0) > 0:
            self._draw_curved_brick_poly(d, cx, cy, length, width, angle,
                                          data.get('sector_angle', 45), outer, inner, shadow)
        else:
            self._draw_straight_brick_poly(d, cx, cy, length, width, angle,
                                            outer, inner, shadow)

    def _draw_straight_brick_poly(self, d, cx, cy, length, width, angle,
                                   outer, inner, shadow):
        half_l, half_w = length / 2, width / 2
        rad = math.radians(angle - 90)
        cos_a, sin_a = math.cos(rad), math.sin(rad)

        def rot(px, py, ox, oy):
            return (ox + px * cos_a - py * sin_a, oy + px * sin_a + py * cos_a)

        corners = [(-half_l, -half_w), (half_l, -half_w),
                   (half_l, half_w), (-half_l, half_w)]
        pts = [rot(lx, ly, cx, cy) for lx, ly in corners]

        if shadow:
            d.polygon([(px + SHADOW_OFFSET[0], py + SHADOW_OFFSET[1]) for px, py in pts], fill=SHADOW_COLOR)
            return

        d.polygon(pts, fill=outer)
        ihw, ihl = max(1, half_w - 5), max(1, half_l - 2)
        ipts = [rot(lx, ly, cx, cy) for lx, ly in [(-ihl, -ihw), (ihl, -ihw), (ihl, ihw), (-ihl, ihw)]]
        d.polygon(ipts, fill=inner)

    def _draw_curved_brick_poly(self, d, cx, cy, length, width, angle,
                                 sector_angle, outer, inner, shadow):
        pts = self._get_curved_brick_poly(cx, cy, length, width, angle, sector_angle)
        if shadow:
            d.polygon([(px + SHADOW_OFFSET[0], py + SHADOW_OFFSET[1]) for px, py in pts], fill=SHADOW_COLOR)
            return
        d.polygon(pts, fill=outer)
        ipts = self._get_curved_inner_poly(cx, cy, length, width, angle, sector_angle)
        if ipts:
            d.polygon(ipts, fill=inner)

    def _draw_rod(self, canvas, entry):
        data = entry.specific_data or {}
        if 'point_a' not in data or 'point_b' not in data:
            return
        ax, ay = data['point_a']
        bx, by = data['point_b']
        d = ImageDraw.Draw(canvas)
        d.line([(DRAW_ADJ_X + ax, DRAW_ADJ_Y + ay),
                (DRAW_ADJ_X + bx, DRAW_ADJ_Y + by)], fill=(255, 255, 255), width=2)

    def _draw_polygon(self, canvas, entry):
        data = entry.specific_data or {}
        points = data.get('points', [])
        if len(points) < 2:
            return
        x, y = get_entry_position(entry)
        cx, cy = DRAW_ADJ_X + x, DRAW_ADJ_Y + y

        if entry.image_filename:
            img = load_entry_image(entry.image_filename, self.search_dir, self.dat_dir)
            if img:
                img_rgba = img.convert('RGBA')
                canvas.paste(img_rgba, (int(cx - img_rgba.width / 2), int(cy - img_rgba.height / 2)), img_rgba)
                return
            return

        d = ImageDraw.Draw(canvas)
        screen_pts = [(cx + px, cy + py) for px, py in points]
        if len(screen_pts) >= 3:
            flat = []
            for i in range(len(screen_pts)):
                flat.extend([screen_pts[i], screen_pts[(i + 1) % len(screen_pts)]])
            d.line(flat, fill=(255, 255, 255), width=2)
        else:
            d.line(screen_pts, fill=(255, 255, 255), width=2)

    def _draw_teleport(self, canvas, entry):
        data = entry.specific_data or {}
        x, y = get_entry_position(entry)
        cx, cy = DRAW_ADJ_X + x, DRAW_ADJ_Y + y
        d = ImageDraw.Draw(canvas)

        if entry.image_filename:
            img = load_entry_image(entry.image_filename, self.search_dir, self.dat_dir)
            if img:
                img_rgba = img.convert('RGBA')
                canvas.paste(img_rgba, (int(cx - img_rgba.width / 2), int(cy - img_rgba.height / 2)), img_rgba)
                return

        w, h = data.get('width', 20) / 2, data.get('height', 20) / 2
        d.rectangle([cx - w, cy - h, cx + w, cy + h], fill=(0, 0, 0))
        d.rectangle([cx - w + 2, cy - h + 2, cx + w - 2, cy + h - 2], fill=(255, 255, 255))
        d.rectangle([cx - w + 4, cy - h + 4, cx + w - 4, cy + h - 4], fill=(0, 0, 0))

    def _draw_emitter(self, canvas, entry):
        x, y = get_entry_position(entry)
        cx, cy = DRAW_ADJ_X + x, DRAW_ADJ_Y + y
        d = ImageDraw.Draw(canvas)
        d.rectangle([cx - 30, cy - 30, cx + 30, cy + 30], outline=(0, 100, 255), width=2)

    def _draw_generator(self, canvas, entry):
        x, y = get_entry_position(entry)
        cx, cy = DRAW_ADJ_X + x, DRAW_ADJ_Y + y
        d = ImageDraw.Draw(canvas)
        if entry.type in (1001, 1003):
            r = 30
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GENERATOR_ORANGE, width=2)
            for a_deg in range(0, 360, 30):
                a = math.radians(a_deg)
                dx, dy = r * 0.6 * math.cos(a), r * 0.6 * math.sin(a)
                d.ellipse([cx + dx - 3, cy + dy - 3, cx + dx + 3, cy + dy + 3], fill=GENERATOR_ORANGE)
        elif entry.type in (1002, 1004):
            r = 30
            d.arc([cx - r, cy - r, cx + r, cy + r], 0, 180, fill=GENERATOR_ORANGE, width=2)
            d.ellipse([cx - r - 3, cy - 3, cx - r + 3, cy + 3], fill=GENERATOR_ORANGE)
            d.ellipse([cx + r - 3, cy - 3, cx + r + 3, cy + 3], fill=GENERATOR_ORANGE)

    def save(self, path):
        self.render().save(path)
        return path


def generate_preview(dat_path, output_path, search_dir=None, assets_dir=None,
                     use_textures=True, show_preview=False, debug_labels=False):
    preview = LevelPreview(dat_path, search_dir=search_dir, assets_dir=assets_dir,
                           use_textures=use_textures, show_preview=show_preview,
                           debug_labels=debug_labels)
    preview.save(output_path)
    return output_path


def _discover_dats(search_dir):
    dats = []
    for f in sorted(os.listdir(search_dir)):
        if f.endswith('.dat') and 'cached' not in f and 'trailer' not in f:
            dats.append(os.path.join(search_dir, f))
    if not dats:
        for root, _, files in os.walk(search_dir):
            for f in sorted(files):
                if f.endswith('.dat') and 'cached' not in f and 'trailer' not in f:
                    dats.append(os.path.join(root, f))
    return dats


def test_all_levels(search_dir, assets_dir=None, output_dir='test_previews'):
    os.makedirs(output_dir, exist_ok=True)
    dats = _discover_dats(search_dir)
    ok = fail = 0
    results = []
    for fp in dats:
        try:
            name = _level_name_from_dat(fp)
            out = os.path.join(output_dir, f'{name}.png')
            generate_preview(fp, out, search_dir=os.path.dirname(fp), assets_dir=assets_dir)
            ok += 1
            results.append((fp, 'OK'))
        except Exception as e:
            fail += 1
            results.append((fp, str(e)))
    return results, ok, fail


def test_one_level(dat_path, assets_dir=None, output_dir='test_previews'):
    os.makedirs(output_dir, exist_ok=True)
    name = _level_name_from_dat(dat_path)
    out = os.path.join(output_dir, f'{name}.png')
    try:
        generate_preview(dat_path, out, search_dir=os.path.dirname(os.path.abspath(dat_path)),
                         assets_dir=assets_dir)
        img = Image.open(out)
        print(f"  Preview: {out} ({img.size[0]}x{img.size[1]})")
        print(f"  Tamanho: {os.path.getsize(out)} bytes")
        return True, out
    except Exception as e:
        print(f"  ERRO: {e}")
        return False, str(e)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Peggle Level Preview - Gera preview PNG de níveis .dat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python levelpreview.py fish.dat preview.png
  python levelpreview.py level1.dat preview.png --no-textures
  python levelpreview.py --test ./caminho/com/dats
  python levelpreview.py --test-one fish.dat
  python levelpreview.py fish.dat preview.png --assets ./meus_assets
        """)

    parser.add_argument('dat', nargs='?', help="Arquivo .dat de nível")
    parser.add_argument('output', nargs='?', help="Arquivo PNG de saída")
    parser.add_argument('--assets', default=None,
                        help="Diretório com assets (padrão: ./assets/)")
    parser.add_argument('--search-dir', default=None,
                        help="Diretório para buscar background e imagens (padrão: mesmo dir do .dat)")
    parser.add_argument('--no-textures', action='store_true',
                        help="Usar cores sólidas ao invés das texturas (peg.png)")
    parser.add_argument('--show-preview', action='store_true',
                        help="Renderizar no modo preview (todos azuis, sem laranja)")
    parser.add_argument('--debug-labels', action='store_true',
                        help="Exibir IDs numéricos das entradas sobre o preview")
    parser.add_argument('--test', metavar='DIR',
                        help="Testar renderização em todos os .dat do diretório")
    parser.add_argument('--test-one', metavar='DAT',
                        help="Testar renderização em um .dat específico")

    args = parser.parse_args()

    assets = args.assets if args.assets else DEFAULT_ASSETS_DIR

    if args.test:
        dats = _discover_dats(args.test)
        if not dats:
            print(f"Nenhum .dat encontrado em: {args.test}")
            sys.exit(1)
        print(f"Testando {len(dats)} nível(is) em {args.test}...")
        results, ok, fail = test_all_levels(args.test, assets_dir=assets)
        print(f"\nResultados: {ok} OK, {fail} FALHA(S) de {len(results)}")
        for fp, status in results:
            label = "OK" if status == "OK" else f"FALHA: {status}"
            print(f"  {os.path.basename(fp)}: {label}")
        sys.exit(0 if fail == 0 else 1)

    if args.test_one:
        success, out = test_one_level(args.test_one, assets_dir=assets)
        if success:
            print(f"  Preview salvo em: {out}")
        sys.exit(0 if success else 1)

    if not args.dat or not args.output:
        parser.print_help()
        sys.exit(1)

    print(f"Renderizando: {args.dat}")
    generate_preview(args.dat, args.output,
                     search_dir=args.search_dir,
                     assets_dir=assets,
                     use_textures=not args.no_textures,
                     show_preview=args.show_preview,
                     debug_labels=args.debug_labels)
    img = Image.open(args.output)
    print(f"  Preview salvo: {args.output} ({img.size[0]}x{img.size[1]})")


if __name__ == '__main__':
    main()
