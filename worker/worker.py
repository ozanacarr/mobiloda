"""
Mobilya AR işleyicisi.

Supabase'te "pending" durumundaki ürünleri bekler:
  - Ürünün hazır .glb modeli varsa (models/{id}/orig.glb) onu kullanır,
  - yoksa fotoğraftan TripoSR ile 3D model üretir.
Ardından modeli girilen ölçülere (cm) göre gerçek boyuta getirip yükler.

Çalıştırma:  .venv\\Scripts\\python worker.py
"""

import io
import os
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import requests
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "triposr"))


def load_env():
    env_file = ROOT.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
POLL_SECONDS = 3
TEXTURE_RES = 1024
MC_RESOLUTION = 256
CHUNK_SIZE = 4096  # 4 GB ekran kartı için küçük tutuldu

HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
REST = f"{SUPABASE_URL}/rest/v1/products"
STORAGE = f"{SUPABASE_URL}/storage/v1/object"


# ---------- Supabase ----------
def api(method, url, **kw):
    res = requests.request(method, url, headers={**HEADERS, **kw.pop("headers", {})}, timeout=60, **kw)
    if not res.ok:
        raise RuntimeError(f"Supabase {res.status_code}: {res.text[:300]}")
    return res


def update(pid, **fields):
    api("PATCH", f"{REST}?id=eq.{pid}", json=fields)


def claim_next():
    """Bekleyen en eski ürünü 'processing' yaparak sahiplenir."""
    rows = api("GET", f"{REST}?status=eq.pending&order=created_at.asc&limit=1&select=*").json()
    if not rows:
        return None
    pid = rows[0]["id"]
    claimed = api(
        "PATCH",
        f"{REST}?id=eq.{pid}&status=eq.pending",
        json={"status": "processing", "progress": 5, "error": None},
        headers={"Prefer": "return=representation"},
    ).json()
    return claimed[0] if claimed else None


def download(bucket, path):
    res = requests.get(f"{STORAGE}/{bucket}/{path}", headers=HEADERS, timeout=120)
    if res.status_code in (400, 404):
        return None
    if not res.ok:
        raise RuntimeError(f"İndirilemedi {bucket}/{path}: {res.status_code}")
    return res.content


def upload(bucket, path, data, content_type):
    api(
        "POST",
        f"{STORAGE}/{bucket}/{path}",
        data=data,
        headers={"Content-Type": content_type, "x-upsert": "true", "cache-control": "3600"},
    )


def remove(bucket, paths):
    if paths:
        requests.delete(f"{STORAGE}/{bucket}", headers=HEADERS, json={"prefixes": paths}, timeout=60)


# ---------- TripoSR ----------
_model = None
_rembg = None


def triposr():
    global _model, _rembg
    if _model is None:
        import rembg
        import torch
        from tsr.system import TSR

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        print(f"TripoSR yükleniyor ({device})...")
        _model = TSR.from_pretrained("stabilityai/TripoSR", config_name="config.yaml", weight_name="model.ckpt")
        _model.renderer.set_chunk_size(CHUNK_SIZE)
        _model.to(device)
        _model.device_name = device
        _rembg = rembg.new_session()
        print("TripoSR hazır.")
    return _model, _rembg


def image_to_glb(image_bytes, on_progress):
    import torch
    from tsr.utils import remove_background, resize_foreground

    model, session = triposr()
    on_progress(15)
    img = Image.open(io.BytesIO(image_bytes))
    img = remove_background(img, session)
    img = resize_foreground(img, 0.85)
    arr = np.array(img).astype(np.float32) / 255.0
    arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5
    img = Image.fromarray((arr * 255.0).astype(np.uint8))

    on_progress(30)
    with torch.no_grad():
        codes = model([img], device=model.device_name)
    on_progress(55)
    mesh = model.extract_mesh(codes, False, resolution=MC_RESOLUTION)[0]
    on_progress(70)

    # Vertex rengi yerine doku (texture) pişir: iPhone Quick Look vertex rengini göstermez.
    try:
        from tsr.bake_texture import bake_texture

        baked = bake_texture(mesh, model, codes[0], TEXTURE_RES)
        tex = Image.fromarray((baked["colors"] * 255.0).astype(np.uint8)).transpose(Image.FLIP_TOP_BOTTOM)
        mesh = trimesh.Trimesh(
            vertices=mesh.vertices[baked["vmapping"]],
            faces=baked["indices"].astype(np.int64),
            visual=trimesh.visual.TextureVisuals(
                uv=baked["uvs"],
                material=trimesh.visual.material.PBRMaterial(
                    baseColorTexture=tex, metallicFactor=0.0, roughnessFactor=0.8
                ),
            ),
            process=False,
        )
    except Exception as e:  # doku pişirme olmazsa renkli köşelere geri dön
        print("Doku pişirilemedi, köşe renkleri kullanılıyor:", e)
        mesh = model.extract_mesh(codes, True, resolution=MC_RESOLUTION)[0]

    # TripoSR Z-yukarı üretir; GLB standardı Y-yukarı. Ön yüz kameraya (+Z) baksın.
    mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [0, 1, 0]))
    if mesh.is_volume and mesh.volume < 0:
        mesh.invert()
    torch.cuda.empty_cache()
    return mesh.export(file_type="glb")


# ---------- Gerçek boyuta ölçekleme ----------
def scale_glb(glb_bytes, width_cm, height_cm, depth_cm):
    """genişlik = X, yükseklik = Y, derinlik = Z; zemine (y=0) oturur, X/Z'de ortalanır."""
    scene = trimesh.load(io.BytesIO(glb_bytes), file_type="glb", force="scene")
    lo, hi = scene.bounds
    size = hi - lo
    if not np.all(size > 0):
        raise RuntimeError("Modelin boyutu okunamadı")
    target = np.array([width_cm, height_cm, depth_cm], dtype=float) / 100.0
    s = target / size
    m = np.diag([s[0], s[1], s[2], 1.0])
    m[:3, 3] = [-(lo[0] + hi[0]) / 2 * s[0], -lo[1] * s[1], -(lo[2] + hi[2]) / 2 * s[2]]
    scene.apply_transform(m)
    return scene.export(file_type="glb")


# ---------- İş akışı ----------
def process(p):
    pid = p["id"]
    print(f"[{p['name']}] işleniyor")
    progress = lambda v: update(pid, progress=int(v))

    orig = download("models", f"{pid}/orig.glb")
    if orig is None:
        if not p.get("image_path"):
            raise RuntimeError("Fotoğraf veya model bulunamadı")
        image = download("images", p["image_path"])
        if image is None:
            raise RuntimeError("Fotoğraf indirilemedi")
        orig = image_to_glb(image, progress)
        upload("models", f"{pid}/orig.glb", orig, "model/gltf-binary")

    progress(85)
    scaled = scale_glb(orig, float(p["width"]), float(p["height"]), float(p["depth"]))
    version = int(p.get("model_version") or 0) + 1
    new_path = f"{pid}/v{version}.glb"
    upload("models", new_path, scaled, "model/gltf-binary")
    old = p.get("model_path")
    update(pid, status="ready", progress=100, model_path=new_path, model_version=version, error=None)
    if old and old != new_path:
        remove("models", [old])
    print(f"[{p['name']}] hazır")


def main():
    print("Mobilya AR işleyicisi çalışıyor. Durdurmak için Ctrl+C.")
    # Önceki çalışmada yarım kalanları tekrar kuyruğa al.
    try:
        api("PATCH", f"{REST}?status=eq.processing", json={"status": "pending", "progress": 0})
    except Exception as e:
        print("Uyarı:", e)
    while True:
        try:
            p = claim_next()
        except Exception as e:
            print("Supabase'e ulaşılamadı:", e)
            time.sleep(10)
            continue
        if not p:
            time.sleep(POLL_SECONDS)
            continue
        try:
            process(p)
        except Exception as e:
            traceback.print_exc()
            try:
                update(p["id"], status="failed", error=str(e)[:500])
            except Exception:
                pass


if __name__ == "__main__":
    main()
