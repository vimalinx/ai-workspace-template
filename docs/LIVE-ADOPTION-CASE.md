# Adopting a dirty live workspace

A production-like practice target validated the adoption contract under realistic pressure: a dirty worktree, existing instructions, historical status, nested repositories, large runtime areas, sensitive-looking locations, and path references that could not be assumed safe to move.

The successful sequence was:

1. inspect without mutation;
2. map the native business layer instead of forcing generic topology;
3. protect exact runtime and secret-location boundaries;
4. apply additive governance through owned blocks and absent files;
5. preserve the first failing audit;
6. roll back by receipt;
7. narrow only the proven legacy scan boundaries;
8. replay and verify with a generated small fixture and the real large target.

No initial adoption step deleted, moved, committed, deployed, changed permissions, or edited external schedulers. The key lesson is that a dirty workspace needs stronger receipts and narrower authority—not a broader license to clean.

See the Skill reference [`live-adoption-case.md`](../.agents/skills/bootstrap-ai-workspace/references/live-adoption-case.md) for the reusable implementation details.
