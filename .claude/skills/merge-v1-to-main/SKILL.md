---
name: merge-v1-to-main
description: Merge v1 branch changes into main, resolving the conflicts that arise from the v1/main code structure difference
trigger: When the user says "merge v1 to main", "port v1 to main", "forward port", or similar
---

## Background

This repository maintains two branches in parallel:

- `v1` — the legacy CLI (`launchable/` Python package, `launchable/jar/exe_deploy.jar`)
- `main` — the rebranded CLI (`smart_tests/` Python package, `smart_tests/jar/exe_deploy.jar`)

Features are usually developed on `v1` first, then ported to `main` via `git merge v1`.

## Procedure

### 1. Create a feature branch from main

```
git checkout -b feature/<ticket>-<description>-main origin/main
```

### 2. Find the merge base

```
export MERGE_BASE=$(git merge-base origin/v1 origin/main)
```

### 3. Merge v1

```
git merge origin/v1
```

This will typically produce conflicts in several categories. Handle each as described below.

---

## Conflict Resolution Patterns

### `deleted by us: launchable/commands/<file>.py`

v1 touched a file that was renamed/moved in main. Find where it lives in main:

```
git log --oneline ${MERGE_BASE}..origin/main -- smart_tests/commands/<file>.py
```

If those changes are already reflected in `smart_tests/`, just remove the leftover:

```
git rm launchable/commands/<file>.py
```

If the v1 changes are **not** yet in main, apply them as a patch:

```
git diff $MERGE_BASE origin/v1 -- launchable/commands/<file>.py > PATCH
patch -l smart_tests/commands/<file>.py < PATCH
git rm launchable/commands/<file>.py
```

### `both modified: tests/commands/test_<cmd>.py`

v1 uses `LAUNCHABLE_TOKEN` / `launchable_token`; main uses `SMART_TESTS_TOKEN` / `smart_tests_token`.
Both sides often add the same tests under different token names.

Resolution: keep the `SMART_TESTS_TOKEN` versions (main side) and discard the `LAUNCHABLE_TOKEN` duplicates.

If v1 adds a genuinely new test not present in main, port it by renaming the token constant.

### `both modified: smart_tests/jar/exe_deploy.jar`

Java source was modified on both sides. Resolve the Java source conflicts first (see below), then:

```
bash build-java.sh
git add smart_tests/jar/exe_deploy.jar
```

### Java source conflicts (`src/main/java/...`)

v1 and main share the same Java source tree. Common differences:

| Area | v1 style | main style |
|---|---|---|
| `GitFile` construction | `objectReader` (single reader) | `readers::get` (ThreadLocal) |
| `collectFiles` signature | `(RevCommit start, TreeWalk treeWalk, TreeReceiver, Consumer<VirtualFile>)` | `(Collection<ObjectId> advertised, TreeReceiver, FlushableConsumer<VirtualFile>)` |
| Static imports | `ImmutableList.*`, `Arrays.*` | `ImmutableList.toImmutableList`, `Arrays.stream` (specific) |

Resolution strategy:
- Keep HEAD (main) structural code (method signatures, `reportAllFiles` block, `readers::get`)
- Apply the logic change from v1 (the new feature/fix)
- If v1 uses wildcard static imports, narrow them back to the specific identifiers main uses

---

## After Resolving All Conflicts

```
bash build-java.sh          # rebuild jar and run tests
git add <all resolved files>
git commit                  # complete the merge commit
git push -u origin <branch>
```

Then create a PR targeting `main` following the `create-gh-pull-request` skill.

---

## Verifying Correct Resolution

After the merge commit, confirm:

1. No conflict markers remain: `git diff HEAD | grep -E '^[<=>]{7}'` should be empty
2. Tests pass: `build-java.sh` exits 0
3. `smart_tests/jar/exe_deploy.jar` is staged (CI will fail otherwise)
4. No `launchable/` paths leak into the commit unless they are legitimately v1-only files

---

## Big Reset

If you get hopelessly confused:

```
git commit --all                  # save current state
git tag rescue-$(date +%s)        # tag it for recovery
git reset --hard origin/main      # start over from main
```
