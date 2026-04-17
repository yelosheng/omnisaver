#!/usr/bin/env python3
"""Generate OmniSaver favicon PNG at 512x512 (scales to 16/32/48/64 cleanly)."""
from PIL import Image, ImageDraw, ImageFilter
import math, os

SIZE = 512
S = SIZE / 64.0   # 1 viewBox unit = 8px

def px(v):  return int(round(v * S))
def pf(v):  return v * S

# ── Card factories ──────────────────────────────────────────────

def make_x_card():
    w, h, r = px(18), px(28), px(4)
    c = Image.new('RGBA', (w, h), (0,0,0,0))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([0,0,w-1,h-1], radius=r, fill=(27,27,30))
    d.rounded_rectangle([0,0,w-1,r*2], radius=r, fill=(50,50,56))  # top shine
    lw = max(3, px(2.2))
    m = px(4)
    d.line([(m,px(8)),(w-m,px(18))], fill=(255,255,255), width=lw)
    d.line([(w-m,px(8)),(m,px(18))], fill=(255,255,255), width=lw)
    return c

def make_video_card():
    w, h, r = px(18), px(28), px(4)
    c = Image.new('RGBA', (w, h), (0,0,0,0))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([0,0,w-1,h-1], radius=r, fill=(248,250,252))
    d.rounded_rectangle([0,0,w-1,h-1], radius=r, fill=None,
                        outline=(226,232,240), width=max(1,px(0.5)))
    # blue pill
    d.rounded_rectangle([px(2),px(9),px(16),px(19)], radius=px(3), fill=(14,165,233))
    # play triangle
    d.polygon([(px(7),px(11.5)),(px(12),px(14)),(px(7),px(16.5))], fill=(255,255,255))
    return c

def make_pink_card():
    w, h, r = px(22), px(34), px(5)
    c = Image.new('RGBA', (w, h), (0,0,0,0))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle([0,0,w-1,h-1], radius=r, fill=(244,114,182))
    d.rounded_rectangle([0,0,w-1,h//2], radius=r, fill=(249,141,200,120))
    # image frame
    d.rounded_rectangle([px(4),px(10),px(18),px(22)], radius=px(2),
                        fill=None, outline=(255,255,255), width=max(2,px(2)))
    cr = px(1.5)
    cx,cy = px(13.5), px(13.5)
    d.ellipse([cx-cr,cy-cr,cx+cr,cy+cr], fill=(255,255,255))
    pts = [(px(4),px(20)),(px(8.5),px(15)),(px(12.5),px(19)),
           (px(15),px(16.5)),(px(18),px(19.5))]
    d.line(pts, fill=(255,255,255), width=max(2,px(2)))
    return c

# ── Shadow & paste helpers ──────────────────────────────────────

def add_shadow(card, blur=8, opacity=0.32, oy=6):
    """Return new image = shadow + card composited."""
    out = Image.new('RGBA', card.size, (0,0,0,0))
    _,_,_,a = card.split()
    shd = Image.new('RGBA', card.size, (0,0,0,0))
    mask = a.point(lambda x: int(x * opacity))
    shd_solid = Image.new('RGBA', card.size, (0,0,0,255))
    shd.paste(shd_solid, (0, oy), mask)
    shd = shd.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(Image.alpha_composite(out, shd), card)

def paste_rotated(base, card, tx, ty, angle, rcx, rcy):
    """Paste card at (tx,ty), rotated by angle° around card-local (rcx,rcy)."""
    tmp = Image.new('RGBA', base.size, (0,0,0,0))
    tmp.paste(card, (int(tx), int(ty)), card)
    abs_cx = tx + rcx
    abs_cy = ty + rcy
    rot = tmp.rotate(-angle, center=(abs_cx, abs_cy),
                     resample=Image.BICUBIC, expand=False)
    return Image.alpha_composite(base, rot)

# ── Realistic archive box ───────────────────────────────────────

def draw_box(img):
    """Draw a realistic metal filing-cabinet box."""
    d = ImageDraw.Draw(img)

    # ── dimensions (in 64-unit space, then scaled) ──
    # Front face
    bx1, by1, bx2, by2 = pf(3), pf(37), pf(61), pf(62)
    # Top surface (perspective: right side rises 5 units)
    top_rise = pf(5)
    # Rim/lid strip
    rim_y1, rim_y2 = pf(33), pf(38)

    # ── right side panel (darkest) ──
    side_pts = [
        (bx2, by1),
        (bx2+pf(4), by1-top_rise),
        (bx2+pf(4), by2-top_rise*0.6),
        (bx2, by2),
    ]
    d.polygon(side_pts, fill=(20,30,45))
    # side edge highlight
    d.line([side_pts[0], side_pts[1]], fill=(55,70,90), width=max(1,px(0.5)))

    # ── top surface (light; shows depth) ──
    top_pts = [
        (bx1, pf(37)),
        (bx2, pf(37)),
        (bx2+pf(4), pf(37)-top_rise),
        (bx1+pf(4), pf(37)-top_rise),
    ]
    d.polygon(top_pts, fill=(85,105,130))
    # top surface front edge highlight
    d.line([top_pts[0], top_pts[1]], fill=(110,135,165), width=max(2,px(0.8)))
    # top surface left edge
    d.line([top_pts[0], top_pts[3]], fill=(70,90,110), width=max(1,px(0.5)))

    # ── front face (steel gradient via horizontal bands) ──
    face_colors = [
        (52, 70, 95),   # top
        (44, 62, 85),
        (38, 55, 78),
        (34, 50, 72),
        (30, 46, 68),
        (28, 42, 64),
        (26, 40, 60),   # bottom
    ]
    face_h = by2 - by1
    band_h = face_h / len(face_colors)
    for i, col in enumerate(face_colors):
        y_start = by1 + i * band_h
        y_end   = by1 + (i+1) * band_h
        d.rectangle([bx1, y_start, bx2, y_end], fill=col)

    # front face rounded corners (redraw over band seams)
    face_img = Image.new('RGBA', img.size, (0,0,0,0))
    fd = ImageDraw.Draw(face_img)
    # top-left and top-right corners are square (abut rim); round bottom
    fd.rounded_rectangle([bx1, by1, bx2, by2], radius=px(5), fill=(38,55,78))
    # overwrite with gradient bands clipped to rounded rect mask
    # (simpler: just draw gradient over the rounded rect)
    for i, col in enumerate(face_colors):
        y_start = by1 + i * band_h
        y_end   = by1 + (i+1) * band_h
        band = Image.new('RGBA', img.size, (0,0,0,0))
        bd = ImageDraw.Draw(band)
        bd.rectangle([bx1, y_start, bx2, y_end], fill=col+(255,))
        face_img = Image.composite(band, face_img, band)
    # re-apply rounded mask
    mask_img = Image.new('L', img.size, 0)
    md = ImageDraw.Draw(mask_img)
    md.rounded_rectangle([bx1, by1, bx2, by2], radius=px(5), fill=255)
    face_img.putalpha(mask_img)
    img.paste(face_img, (0,0), face_img)

    d = ImageDraw.Draw(img)

    # ── front face: horizontal seam line (drawer separation) ──
    seam_y = by1 + face_h * 0.38
    d.line([(bx1+px(2), seam_y), (bx2-px(2), seam_y)],
           fill=(20,35,55), width=max(1,px(0.6)))

    # ── rim / lid (dark strip across top of front face) ──
    rim_img = Image.new('RGBA', img.size, (0,0,0,0))
    rd = ImageDraw.Draw(rim_img)
    rd.rectangle([bx1, rim_y1, bx2, rim_y2], fill=(22, 32, 48))
    # rim top highlight
    rd.line([(bx1, rim_y1+px(0.5)), (bx2, rim_y1+px(0.5))],
            fill=(80,100,125), width=max(2, px(1)))
    # rim bottom shadow
    rd.line([(bx1, rim_y2-px(0.5)), (bx2, rim_y2-px(0.5))],
            fill=(15,22,35), width=max(1, px(0.5)))
    img.paste(rim_img, (0,0), rim_img)

    d = ImageDraw.Draw(img)

    # ── recessed handle panel ──
    hpx1, hpy1 = pf(17), pf(47)
    hpx2, hpy2 = pf(47), pf(57)
    hpr = px(4)
    # outer shadow ring
    d.rounded_rectangle([hpx1-px(1),hpy1-px(1),hpx2+px(1),hpy2+px(1)],
                        radius=hpr+px(1), fill=(15,22,35))
    # recessed cavity (very dark)
    d.rounded_rectangle([hpx1,hpy1,hpx2,hpy2], radius=hpr, fill=(10,15,25))
    # cavity top shadow (light blocked by top edge)
    d.rounded_rectangle([hpx1,hpy1,hpx2,hpy1+px(2)], radius=hpr, fill=(5,8,14))
    # cavity bottom highlight (light hits bottom edge)
    d.rounded_rectangle([hpx1,hpy2-px(1.5),hpx2,hpy2], radius=hpr, fill=(28,40,58))

    # metal handle bar
    hbx1, hby1 = pf(21), pf(50)
    hbx2, hby2 = pf(43), pf(54.5)
    hbr = px(2.5)
    # bar shadow
    d.rounded_rectangle([hbx1, hby1+px(1), hbx2, hby2+px(1)],
                        radius=hbr, fill=(5,8,14,180))
    # bar body (medium steel)
    d.rounded_rectangle([hbx1, hby1, hbx2, hby2], radius=hbr, fill=(72,92,115))
    # bar top highlight (bright shine)
    d.rounded_rectangle([hbx1, hby1, hbx2, hby1+px(1.5)],
                        radius=hbr, fill=(140,165,195))
    # bar mid sheen
    d.rounded_rectangle([hbx1+px(1), hby1+px(1.5), hbx2-px(1), hby1+px(2.5)],
                        radius=px(1), fill=(100,125,150,180))

    # ── front face: vertical edge reflections (metal sheen) ──
    d.line([(bx1+px(1.5), by1+px(3)), (bx1+px(1.5), by2-px(5))],
           fill=(55,75,100,120), width=max(1,px(0.8)))
    d.line([(bx2-px(1.5), by1+px(3)), (bx2-px(1.5), by2-px(5))],
           fill=(25,38,55,100), width=max(1,px(0.8)))

    return img

# ── Main composition ────────────────────────────────────────────

img = Image.new('RGBA', (SIZE, SIZE), (0,0,0,0))
d = ImageDraw.Draw(img)

# 1. Folder tabs (behind cards)
tabs = [
    (12,24,22,30, (139,92,246)),
    (27,24,37,30, (14,165,233)),
    (42,24,52,30, (16,185,129)),
]
for x1,y1,x2,y2,col in tabs:
    d.rounded_rectangle([pf(x1),pf(y1),pf(x2),pf(y2)], radius=px(2), fill=col)

# Folder body (white strip behind tabs)
d.rounded_rectangle([pf(6),pf(27),pf(58),pf(42)], radius=px(2), fill=(241,245,249))

# 2. X card – translate(8,12) rotate(-12, 9,14)
xc = add_shadow(make_x_card(), blur=px(1.5), opacity=0.28, oy=px(2))
img = paste_rotated(img, xc, pf(8), pf(12), -12, pf(9), pf(14))

# 3. Video card – translate(38,14) rotate(12, 9,14)
vc = add_shadow(make_video_card(), blur=px(1.5), opacity=0.28, oy=px(2))
img = paste_rotated(img, vc, pf(38), pf(14), 12, pf(9), pf(14))

# 4. Pink center card – translate(21,5) no rotation
pc = add_shadow(make_pink_card(), blur=px(1.5), opacity=0.28, oy=px(2))
img.paste(pc, (px(21), px(5)), pc)

# 5. Realistic archive box
img = draw_box(img)

# ── Export ─────────────────────────────────────────────────────
out_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'favicon-v8.png')
img.save(out_path, 'PNG')
print(f"Saved: {os.path.abspath(out_path)}  ({SIZE}x{SIZE})")

# Also save small preview sizes
for sz in (64, 32, 16):
    small = img.resize((sz,sz), Image.LANCZOS)
    sp = out_path.replace('v8.png', f'v8-{sz}.png')
    small.save(sp)
    print(f"       {sp}  ({sz}x{sz})")
