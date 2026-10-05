#!/usr/bin/env python3
"""
make_synthetic.py - synthetic-tier stimulus generator for
"Can't Tell, or Won't Say?"

Makes simple 2D scenes (like Fig. 1 of the proposal) for five feature categories:
  text     - "What code is printed on the ball?"
  colour   - "What colour is the triangle?"
  shape    - "What shape is the green object?"
  count    - "How many circles are in the image?"
  spatial  - "Where is the red star relative to the blue square?"

For every item it saves the image plus one metadata record with the question,
correct answer, 3 foils, the diagnostic-region bounding box, and the
"critical feature size" used later to normalize degradation.

Output (inside --out):
  images/<item_id>.png      clean (undegraded) image
  metadata.jsonl            one JSON record per line, one line per item
  preview.png               contact sheet with diagnostic boxes drawn in red

Usage:
  pip install pillow
  python make_synthetic.py --n_per_category 15 --out synthetic_tier --seed 1
"""
import argparse
import json
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- settings
W, H = 512, 384                      # image size in pixels
WALL, FLOOR = (205, 205, 205), (150, 156, 166)
FLOOR_Y = int(H * 0.62)              # where the floor band starts

PALETTE = {                          # 6 easily named colours
    "red": (214, 48, 49),
    "orange": (230, 140, 50),
    "yellow": (235, 200, 40),
    "green": (46, 160, 67),
    "blue": (36, 90, 200),
    "purple": (130, 60, 170),
}
DARK = ["red", "green", "blue", "purple"]   # white text is readable on these
SHAPES = ["circle", "square", "triangle", "star"]
# Code alphabet with look-alike characters removed (B/8, G/6, I/1, O/0/Q, S/5, Z/2)
CODE_CHARS = "ACDEFHJKLMNPRTUVWXY234679"
CATEGORIES = ["text", "colour", "shape", "count", "spatial"]


# ---------------------------------------------------------------- helpers
def load_font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def shape_points(shape, cx, cy, r):
    if shape == "square":
        s = r * 0.85
        return [(cx - s, cy - s), (cx + s, cy - s), (cx + s, cy + s), (cx - s, cy + s)]
    if shape == "triangle":
        return [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
                for a in (-90, 30, 150)]
    if shape == "star":
        pts = []
        for i in range(10):
            rad = r if i % 2 == 0 else r * 0.45
            a = math.radians(-90 + 36 * i)
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
        return pts
    return None   # circle


def obj_bbox(o):
    pts = shape_points(o["shape"], o["x"], o["y"], o["r"])
    if pts is None:
        pts = [(o["x"] - o["r"], o["y"] - o["r"]), (o["x"] + o["r"], o["y"] + o["r"])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [int(min(xs)), int(min(ys)), int(math.ceil(max(xs))), int(math.ceil(max(ys)))]


def union(boxes, pad=0):
    return [max(0, min(b[0] for b in boxes) - pad), max(0, min(b[1] for b in boxes) - pad),
            min(W, max(b[2] for b in boxes) + pad), min(H, max(b[3] for b in boxes) + pad)]


def draw_obj(d, o):
    col = PALETTE[o["colour"]]
    if o["shape"] == "circle":
        d.ellipse([o["x"] - o["r"], o["y"] - o["r"], o["x"] + o["r"], o["y"] + o["r"]], fill=col)
    else:
        d.polygon(shape_points(o["shape"], o["x"], o["y"], o["r"]), fill=col)


def place(rng, objs, gap=16, margin=10, top=0.18):
    """Give each object an (x, y) so that no two objects overlap."""
    for _ in range(500):
        placed = []
        for o in objs:
            for _ in range(300):
                x = rng.uniform(margin + o["r"], W - margin - o["r"])
                y = rng.uniform(max(H * top, margin + o["r"]), H - margin - o["r"])
                if all(math.hypot(x - p["x"], y - p["y"]) >= o["r"] + p["r"] + gap for p in placed):
                    placed.append({**o, "x": round(x, 1), "y": round(y, 1)})
                    break
            else:
                break
        if len(placed) == len(objs):
            return placed
    raise RuntimeError("Could not place objects; reduce object count or size.")


def distractors(rng, k, avoid_shape=None, avoid_colour=None):
    out = []
    for _ in range(k):
        shapes = [s for s in SHAPES if s != avoid_shape]
        colours = [c for c in PALETTE if c != avoid_colour]
        out.append({"shape": rng.choice(shapes), "colour": rng.choice(colours),
                    "r": rng.randint(26, 40), "role": "distractor"})
    return out


# ---------------------------------------------------------------- categories
def gen_text(rng):
    code = "".join(rng.choice(CODE_CHARS) for _ in range(3))
    # Foil rule: foil i differs from the answer in exactly one character, at position i.
    foils = []
    for pos in range(3):
        alt = rng.choice([c for c in CODE_CHARS if c != code[pos]])
        foils.append(code[:pos] + alt + code[pos + 1:])
    target = {"shape": "circle", "colour": rng.choice(DARK), "r": rng.randint(44, 54), "role": "target"}
    # distractors are never circles, so "the ball" is unique
    objs = place(rng, [target] + distractors(rng, rng.randint(1, 2), avoid_shape="circle"))
    return dict(question="What code is printed on the ball?", answer=code, foils=foils,
                objects=objs, code=code, feature_size_def="text height (px)")


def gen_colour(rng):
    shape = rng.choice(SHAPES)
    colour = rng.choice(list(PALETTE))
    target = {"shape": shape, "colour": colour, "r": rng.randint(32, 46), "role": "target"}
    objs = place(rng, [target] + distractors(rng, rng.randint(1, 3), avoid_shape=shape))
    foils = rng.sample([c for c in PALETTE if c != colour], 3)
    name = "ball" if shape == "circle" else shape
    return dict(question=f"What colour is the {name}?", answer=colour, foils=foils,
                objects=objs, feature_size_def="target diameter (px)")


def gen_shape(rng):
    shape = rng.choice(SHAPES)
    colour = rng.choice(list(PALETTE))
    target = {"shape": shape, "colour": colour, "r": rng.randint(32, 46), "role": "target"}
    objs = place(rng, [target] + distractors(rng, rng.randint(1, 3), avoid_colour=colour))
    foils = [s for s in SHAPES if s != shape]
    return dict(question=f"What shape is the {colour} object?", answer=shape, foils=foils,
                objects=objs, feature_size_def="target diameter (px)")


def gen_count(rng):
    n = rng.randint(2, 7)
    objs = [{"shape": "circle", "colour": rng.choice(list(PALETTE)), "r": rng.randint(18, 26),
             "role": "target"} for _ in range(n)]
    objs = place(rng, objs, gap=14)
    candidates = [m for m in (n - 2, n - 1, n + 1, n + 2) if 1 <= m <= 9]
    foils = [str(m) for m in rng.sample(candidates, 3)]
    return dict(question="How many circles are in the image?", answer=str(n), foils=foils,
                objects=objs, feature_size_def="mean nearest-neighbour centre distance (px)")


def gen_spatial(rng):
    relations = {"left of": (-1, 0), "right of": (1, 0), "above": (0, -1), "below": (0, 1)}
    rel = rng.choice(list(relations))
    sa, sb = rng.sample(SHAPES, 2)
    ca, cb = rng.sample(list(PALETTE), 2)
    ra, rb = rng.randint(28, 38), rng.randint(28, 38)
    for _ in range(2000):
        bx, by = rng.uniform(60, W - 60), rng.uniform(60, H - 60)
        dist = rng.uniform(ra + rb + 30, 170)
        dx, dy = relations[rel]
        jitter = rng.uniform(-0.25, 0.25) * dist      # small off-axis offset
        ax = bx + dx * dist + (jitter if dx == 0 else 0)
        ay = by + dy * dist + (jitter if dy == 0 else 0)
        if (10 + ra <= ax <= W - 10 - ra) and (10 + ra <= ay <= H - 10 - ra) \
                and (10 + rb <= bx <= W - 10 - rb) and (10 + rb <= by <= H - 10 - rb):
            break
    objs = [{"shape": sa, "colour": ca, "r": ra, "x": round(ax, 1), "y": round(ay, 1), "role": "target_a"},
            {"shape": sb, "colour": cb, "r": rb, "x": round(bx, 1), "y": round(by, 1), "role": "target_b"}]
    na = "ball" if sa == "circle" else sa
    nb = "ball" if sb == "circle" else sb
    return dict(question=f"In the image, where is the {ca} {na} relative to the {cb} {nb}?",
                answer=rel, foils=[r for r in relations if r != rel], objects=objs,
                feature_size_def="centre-to-centre distance (px)")


GENERATORS = {"text": gen_text, "colour": gen_colour, "shape": gen_shape,
              "count": gen_count, "spatial": gen_spatial}


# ---------------------------------------------------------------- rendering
def render(item):
    img = Image.new("RGB", (W, H), WALL)
    d = ImageDraw.Draw(img)
    d.rectangle([0, FLOOR_Y, W, H], fill=FLOOR)
    for o in item["objects"]:
        draw_obj(d, o)

    targets = [o for o in item["objects"] if o["role"].startswith("target")]
    if item["category"] == "text":
        t = targets[0]
        font = load_font(int(t["r"] * 0.55))
        tcol = (255, 255, 255)
        d.text((t["x"], t["y"]), item["code"], font=font, fill=tcol, anchor="mm")
        tb = d.textbbox((t["x"], t["y"]), item["code"], font=font, anchor="mm")
        bbox = [int(tb[0]) - 2, int(tb[1]) - 2, int(tb[2]) + 2, int(tb[3]) + 2]
        feature = tb[3] - tb[1]
    elif item["category"] == "count":
        bbox = union([obj_bbox(o) for o in targets], pad=4)
        dists = [min(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) for b in targets if b is not a)
                 for a in targets]
        feature = sum(dists) / len(dists)
    elif item["category"] == "spatial":
        bbox = union([obj_bbox(o) for o in targets], pad=4)
        a, b = targets
        feature = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
    else:   # colour, shape
        bbox = union([obj_bbox(targets[0])], pad=4)
        feature = 2 * targets[0]["r"]
    item["bbox_xyxy"] = bbox
    item["feature_size_px"] = round(float(feature), 1)
    return img


def make_preview(records, out_dir, per_cat=4):
    tw, th, cap = 256, 192, 40
    cats = [c for c in CATEGORIES if any(r["category"] == c for r in records)]
    sheet = Image.new("RGB", (tw * per_cat, (th + cap) * len(cats)), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    font = load_font(11)
    for row, cat in enumerate(cats):
        for col, rec in enumerate([r for r in records if r["category"] == cat][:per_cat]):
            img = Image.open(out_dir / rec["image_path"]).convert("RGB")
            ImageDraw.Draw(img).rectangle(rec["bbox_xyxy"], outline=(255, 0, 0), width=3)
            x0, y0 = col * tw, row * (th + cap)
            sheet.paste(img.resize((tw, th)), (x0, y0))
            q = rec["question"] if len(rec["question"]) < 46 else rec["question"][:44] + "..."
            d.text((x0 + 4, y0 + th + 3), q, font=font, fill=(0, 0, 0))
            d.text((x0 + 4, y0 + th + 19), f"answer: {rec['answer']}   foils: {', '.join(rec['foils'])}",
                   font=font, fill=(60, 60, 60))
    sheet.save(out_dir / "preview.png")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n_per_category", type=int, default=15)
    ap.add_argument("--out", default="synthetic_tier")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--categories", nargs="+", default=CATEGORIES, choices=CATEGORIES)
    args = ap.parse_args()

    out_dir = Path(args.out)
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    records = []
    for cat in args.categories:
        for i in range(args.n_per_category):
            item_seed = args.seed * 1_000_000 + CATEGORIES.index(cat) * 10_000 + i
            rng = random.Random(item_seed)          # same seed -> identical image
            item = GENERATORS[cat](rng)
            item.update(item_id=f"syn_{cat}_{i + 1:03d}", tier="synthetic", category=cat,
                        seed=item_seed, width=W, height=H, source="generated", license="own")
            img = render(item)
            item["image_path"] = f"images/{item['item_id']}.png"
            img.save(out_dir / item["image_path"])
            item.pop("code", None)
            assert item["answer"] not in item["foils"] and len(set(item["foils"])) == 3
            records.append(item)

    keys = ["item_id", "tier", "category", "question", "answer", "foils", "bbox_xyxy",
            "feature_size_px", "feature_size_def", "image_path", "width", "height",
            "seed", "source", "license", "objects"]
    with open(out_dir / "metadata.jsonl", "w") as f:
        for r in records:
            f.write(json.dumps({k: r[k] for k in keys}) + "\n")
    make_preview(records, out_dir)
    print(f"Wrote {len(records)} items to {out_dir}/ (see preview.png)")


if __name__ == "__main__":
    main()
