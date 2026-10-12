# shop

Cakezz shop: plain PHP + HTML + CSS, light theme. Built by Part 1. The dark monitor tab (`monitor/`) is Part 6.

Run: `docker compose up --build` from the repo root (http://localhost:8080), or `php -S localhost:8080 -t shop` with `shop/.env` filled. Test steps: `TESTING.md`. Setup: `../docs/SETUP.md`.

Layout: `includes/` (bootstrap, Supabase REST helper `db.php`, RuleLock client + mock `rulelock.php`, helpers `lib.php`, `layout.php`), `admin/` (admin pages), pages in the root, `assets/` (CSS, `products/` images).
