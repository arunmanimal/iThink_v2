-- iThink: flexible brands (any brand can be "own" or a competitor)
-- Safe to run more than once. Run in the Supabase SQL editor.
--
-- 1. user_preferences  : each user's own-brand choice (a view setting; other users are unaffected)
-- 2. tenants.industry  : the industry the tenant entered when setting up brands
-- 3. brand_aliases.tenant_id : lets aliases be created per tenant by the ingestion/upload step
-- 4. brands.is_own_brand stays as the tenant-wide DEFAULT own brand (used until a user picks their own)

-- ---------------------------------------------------------------- 1. per-user own brand
create table if not exists public.user_preferences (
  tenant_id    uuid not null,
  user_id      uuid not null,
  own_brand_id uuid,
  updated_at   timestamptz not null default now(),
  primary key (tenant_id, user_id)
);

alter table public.user_preferences enable row level security;

drop policy if exists user_preferences_select on public.user_preferences;
drop policy if exists user_preferences_insert on public.user_preferences;
drop policy if exists user_preferences_update on public.user_preferences;

-- a user sees and changes only their own row, and only inside a tenant they belong to
create policy user_preferences_select on public.user_preferences
  for select to authenticated
  using (user_id = auth.uid() and tenant_id in (select public.current_tenant_ids()));

create policy user_preferences_insert on public.user_preferences
  for insert to authenticated
  with check (user_id = auth.uid() and tenant_id in (select public.current_tenant_ids()));

create policy user_preferences_update on public.user_preferences
  for update to authenticated
  using (user_id = auth.uid() and tenant_id in (select public.current_tenant_ids()))
  with check (user_id = auth.uid() and tenant_id in (select public.current_tenant_ids()));

revoke all on public.user_preferences from public, anon;
grant select, insert, update on public.user_preferences to authenticated;
grant all on public.user_preferences to service_role;

-- ---------------------------------------------------------------- 2. industry
do $$
begin
  if to_regclass('public.tenants') is not null then
    alter table public.tenants add column if not exists industry text;
  end if;
end $$;

-- ---------------------------------------------------------------- 3. alias ownership
do $$
begin
  if to_regclass('public.brand_aliases') is not null then
    alter table public.brand_aliases add column if not exists tenant_id uuid;
    update public.brand_aliases a
       set tenant_id = b.tenant_id
      from public.brands b
     where a.brand_id = b.id and a.tenant_id is null;
  end if;
end $$;

-- ---------------------------------------------------------------- 4. default own brand
do $$
begin
  alter table public.brands add column if not exists is_own_brand boolean not null default false;
end $$;

notify pgrst, 'reload schema';
