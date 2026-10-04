-- Mobilya AR: Supabase kurulumu
-- Supabase panelinde SQL Editor'e yapıştırıp bir kez "Run" deyin.
-- Tekrar çalıştırmak güvenlidir.

-- ---------- Ürünler tablosu ----------
create table if not exists public.products (
  id            uuid primary key default gen_random_uuid(),
  name          text not null check (char_length(name) between 1 and 120),
  width         numeric not null check (width  > 0 and width  <= 2000), -- cm
  depth         numeric not null check (depth  > 0 and depth  <= 2000), -- cm
  height        numeric not null check (height > 0 and height <= 2000), -- cm
  note          text check (char_length(note) <= 1000),
  image_path    text,                -- images bucket içindeki dosya
  model_path    text,                -- models bucket içindeki ölçeklenmiş .glb
  status        text not null default 'pending'
                check (status in ('pending', 'processing', 'ready', 'failed')),
  progress      int  not null default 0 check (progress between 0 and 100),
  error         text,
  model_version int  not null default 0,
  created_at    timestamptz not null default now()
);

create index if not exists products_status_idx on public.products (status);
create index if not exists products_created_idx on public.products (created_at desc);

-- ---------- Güvenlik kuralları (RLS) ----------
-- Giriş sistemi olmayan kişisel proje: publishable anahtarla okuma/yazma serbest.
alter table public.products enable row level security;

drop policy if exists "products_select" on public.products;
drop policy if exists "products_insert" on public.products;
drop policy if exists "products_update" on public.products;
drop policy if exists "products_delete" on public.products;

create policy "products_select" on public.products for select to anon, authenticated using (true);
create policy "products_insert" on public.products for insert to anon, authenticated with check (true);
create policy "products_update" on public.products for update to anon, authenticated using (true) with check (true);
create policy "products_delete" on public.products for delete to anon, authenticated using (true);

-- Site, model hazır olunca sayfayı yenilemeden güncellensin.
do $$
begin
  alter publication supabase_realtime add table public.products;
exception when duplicate_object then null;
end $$;

-- ---------- Dosya depoları (Storage) ----------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('images', 'images', true, 15728640, array['image/png', 'image/jpeg', 'image/webp']),
  ('models', 'models', true, 52428800, array['model/gltf-binary', 'application/octet-stream'])
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "mobilya_files_select" on storage.objects;
drop policy if exists "mobilya_files_insert" on storage.objects;
drop policy if exists "mobilya_files_update" on storage.objects;
drop policy if exists "mobilya_files_delete" on storage.objects;

create policy "mobilya_files_select" on storage.objects for select to anon, authenticated
  using (bucket_id in ('images', 'models'));
create policy "mobilya_files_insert" on storage.objects for insert to anon, authenticated
  with check (bucket_id in ('images', 'models'));
create policy "mobilya_files_update" on storage.objects for update to anon, authenticated
  using (bucket_id in ('images', 'models')) with check (bucket_id in ('images', 'models'));
create policy "mobilya_files_delete" on storage.objects for delete to anon, authenticated
  using (bucket_id in ('images', 'models'));
