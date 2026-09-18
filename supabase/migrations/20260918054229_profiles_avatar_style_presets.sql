-- Public presentation preference only. Authorization continues to be enforced by
-- profiles_update_self, while activity collaborators can read the preset key via
-- the existing authenticated profiles_select policy.
alter table public.profiles
  add column if not exists avatar_style text;

update public.profiles
set avatar_style = 'sage'
where avatar_style is null
   or avatar_style not in (
     'sage', 'terracotta', 'honey', 'olive', 'slate', 'mist', 'lotus', 'cocoa',
     'moss', 'apricot', 'berry', 'teal', 'coral', 'steel', 'wheat', 'rose'
   );

alter table public.profiles
  alter column avatar_style set default 'sage',
  alter column avatar_style set not null;

alter table public.profiles
  drop constraint if exists profiles_avatar_style_check;

alter table public.profiles
  add constraint profiles_avatar_style_check
  check (avatar_style in (
    'sage', 'terracotta', 'honey', 'olive', 'slate', 'mist', 'lotus', 'cocoa',
    'moss', 'apricot', 'berry', 'teal', 'coral', 'steel', 'wheat', 'rose'
  ));

grant update (avatar_style) on public.profiles to authenticated;
