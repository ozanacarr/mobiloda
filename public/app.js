import { createClient } from 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm';
import { SUPABASE_URL, SUPABASE_KEY } from '/config.js';

export const sb = createClient(SUPABASE_URL, SUPABASE_KEY);

export const fileUrl = (bucket, path) =>
  path ? sb.storage.from(bucket).getPublicUrl(path).data.publicUrl : null;

export const modelUrl = (p) => fileUrl('models', p.model_path);
export const imageUrl = (p) => fileUrl('images', p.image_path);

export async function listProducts() {
  const { data, error } = await sb.from('products').select('*').order('created_at', { ascending: false });
  if (error) throw error;
  return data;
}

export async function getProduct(id) {
  const { data, error } = await sb.from('products').select('*').eq('id', id).maybeSingle();
  if (error) throw error;
  return data;
}

/** Fotoğrafı en fazla 1024 px'e küçültüp JPEG yapar (yükleme hızlansın, TripoSR 512 px kullanıyor). */
export async function shrinkImage(file, max = 1024) {
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement('canvas');
  c.width = Math.round(bmp.width * k);
  c.height = Math.round(bmp.height * k);
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, c.width, c.height);
  ctx.drawImage(bmp, 0, 0, c.width, c.height);
  return new Promise((r) => c.toBlob(r, 'image/jpeg', 0.9));
}

// crypto.randomUUID sadece HTTPS'te var; telefondan http://192.168.x.x ile girilince bu kullanılır.
function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export async function createProduct({ name, width, depth, height, note, photo, glb }) {
  const id = uuid();
  let image_path = null;
  if (photo) {
    image_path = `${id}/photo.jpg`;
    const { error } = await sb.storage.from('images').upload(image_path, await shrinkImage(photo), { contentType: 'image/jpeg' });
    if (error) throw error;
  }
  if (glb) {
    const { error } = await sb.storage.from('models').upload(`${id}/orig.glb`, glb, { contentType: 'model/gltf-binary' });
    if (error) throw error;
  }
  const { error } = await sb.from('products').insert({ id, name, width, depth, height, note: note || null, image_path, status: 'pending' });
  if (error) throw error;
  return id;
}

export async function updateDims(id, dims) {
  // Ölçü değişince işleyici modeli yeni boyuta göre tekrar ölçekler.
  const { error } = await sb.from('products').update({ ...dims, status: 'pending', progress: 0 }).eq('id', id);
  if (error) throw error;
}

export async function retry(id) {
  const { error } = await sb.from('products').update({ status: 'pending', progress: 0, error: null }).eq('id', id);
  if (error) throw error;
}

export async function deleteProduct(p) {
  const files = { models: [], images: [] };
  for (const bucket of Object.keys(files)) {
    const { data } = await sb.storage.from(bucket).list(p.id);
    files[bucket] = (data || []).map((f) => `${p.id}/${f.name}`);
    if (files[bucket].length) await sb.storage.from(bucket).remove(files[bucket]);
  }
  const { error } = await sb.from('products').delete().eq('id', p.id);
  if (error) throw error;
}

export const STATUS = {
  pending: 'Sırada',
  processing: '3D model üretiliyor',
  ready: 'Hazır',
  failed: 'Hata',
};

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const dimsText = (p) => `${+p.width} × ${+p.depth} × ${+p.height} cm`;
