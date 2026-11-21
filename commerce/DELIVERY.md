# Commerce delivery — 2026-11-21

Current implementation is based on main c76a895, preserving the merged new
frontend cleanup. Product, atomic guest sales, staff UI and shared Member sales
are available as separate dependent change sets. No root templates/static
frontend or additional framework is introduced.

Executed on PostgreSQL16.16, Django5.2.19, Python3.13.7:
- Product stage:21 passed.
- Guest-backend stage:105 passed.
- Connected latest frontend:121 passed.
- Member integration focused:30 passed.
- Final full project suite:151 passed,0failures/errors/skips.
- Guest Edge browser audit:1passed, stock10->8->10, total25.00.
- Member Edge audit:1passed, shop subtotal25.00/discount2.50/total22.50;
  bar subtotal2.40/discount0.12/total2.28; stock10->8->10 andmobile390x844.
- System check and all-app migration consistency passed. Migration0003 depends
  on real club.0002_initial plus commerce.0002_guest_sales.

Member policy and exact form/routes are in MEMBER_SALES.md. Counter UI remains
Pratik-owned; this is a reviewable integration using his published design.
Pratik's dashboard still needs completed commerce totals and corrected booking
value labels; that reporting code was not modified here.

Original source/review/integration worktrees and patch artifacts are preserved.
No credentials are committed. Publication is user-authorized; no direct-main
push or automatic PR merge is performed. Local development DB migration0003
and server handoff are reported after execution below.
