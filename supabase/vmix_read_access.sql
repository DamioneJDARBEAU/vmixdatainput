-- Run this in the Supabase dashboard > SQL Editor ONLY IF check_sources.bat
-- says daily_results / lotto_results "returned no rows" although they hold data.
--
-- It lets the public (anon / publishable) key READ results that are already
-- published. Unpublished results (published_at is null) stay hidden, so
-- results awaiting approval can never leak through this key. Nothing can be
-- written, changed or deleted with it.

create policy "vMix reads published daily results"
  on public.daily_results for select to anon
  using (published_at is not null);

create policy "vMix reads published lotto results"
  on public.lotto_results for select to anon
  using (published_at is not null);

-- To undo:
-- drop policy "vMix reads published daily results" on public.daily_results;
-- drop policy "vMix reads published lotto results" on public.lotto_results;
