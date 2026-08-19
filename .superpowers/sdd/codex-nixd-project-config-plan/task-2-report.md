# Task 2 report: invalid-file warnings and child working directories

## Status

Implemented and verified on branch `project-config` from Task 1 HEAD
`ca9002952d078fd06b616a586cada3669042c8d8`.

## Implementation

- Captured the launch directory separately from the effective workspace root.
- Preserved Task 1 root precedence: a non-empty `rootUri` wins over `rootPath`.
- Validated supplied roots as existing, searchable directories. An unusable
  selected root logs the supplied path and reason, skips project-file loading,
  and uses the launch directory without falling through to `rootPath`.
- Bound `window/showMessage` and retained one pending startup warning. Project
  I/O, JSON, schema, and unusable-root errors are discovered and logged during
  `initialize`, then sent and cleared only from `onInitialized`.
- Kept missing `.nixd.json` silent and kept explicit invalid `--config=` fatal.
- Threaded the effective root through retained evaluator-worker launch APIs and
  changed directory only inside the forked evaluator child before `exec`.
- Changed directory only inside the forked formatter child. A child `chdir`
  race returns a coherent formatting error; a dedicated signal distinguishes
  it from ordinary formatter exit status 125.
- Replaced the Task 1 inaccessible-root I/O fixture with an accessible root and
  unreadable `.nixd.json`, driven by a Python `try/finally` runner that restores
  file/root permissions and removes only the exact LIT temp root on every path.

## Files

Production:

- `nixd/include/nixd/Controller/Controller.h`
- `nixd/include/nixd/Eval/Launch.h`
- `nixd/lib/Controller/Configuration.cpp`
- `nixd/lib/Controller/Format.cpp`
- `nixd/lib/Controller/LifeTime.cpp`
- `nixd/lib/Controller/Support.cpp`
- `nixd/lib/Eval/Launch.cpp`

Tests:

- `nixd/tools/nixd/test/project-config/lsp_test_client.py`
- `startup-warnings.{md,py}`
- `evaluator-cwd.{md,py}`
- `formatter-cwd.{md,py}`
- `unusable-root.{md,py}`
- `two-server-isolation.{md,py}`
- `project-config-io-error.{md,py}`

No documentation or `nixd-schema.json` was changed.

## RED/GREEN record

All commands used `XDG_CACHE_HOME=/private/tmp/codex-nixd-cache` for Nix.
Focused direct-lit commands also set `MESON_BUILD_ROOT`, `NIXD_ATTRSET_EVAL`,
and prepended `build/nixd/tools` to `PATH`.

### Startup warning lifecycle

RED command:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command lit -vv nixd/tools/nixd/test/project-config/startup-warnings.md
```

Literal RED result:

```text
FAIL: nixd :: project-config/startup-warnings.md
startup warning case passed: missing
TimeoutError: stderr predicate not met
stderr='... <-- initialize(0) ... workspace/configuration: client does not support workspace configuration ...'
Total Discovered Tests: 1
  Failed: 1 (100.00%)
```

Separate malformed and schema invocations failed at the same predicate because
neither path/reason was logged. The explicit-empty CLI case was corrected to
assert the binding contract—nonzero fatal exit and no warning—rather than the
unrequired absence of an already-sent initialize reply.

GREEN result:

```text
PASS: nixd :: project-config/startup-warnings.md
Total Discovered Tests: 1
  Passed: 1 (100.00%)
```

### Evaluator cwd

RED command used the same environment with `evaluator-cwd.md`.

```text
FAIL: nixd :: project-config/evaluator-cwd.md
TimeoutError: timed out while reading LSP headers
```

Both selected-root cases failed because `import ./nixpkgs.nix` ran from the
launch directory; the launch-directory control passed. GREEN:

```text
PASS: nixd :: project-config/evaluator-cwd.md
Testing Time: 2.50s
```

### Formatter cwd

RED selected-root cases returned an error object rather than the literal
formatter result:

```text
KeyError: 'result'
```

The launch-directory control passed. GREEN:

```text
PASS: nixd :: project-config/formatter-cwd.md
Testing Time: 2.86s
```

Self-review later added an ordinary formatter exit-125 preservation case.
Its RED result was:

```text
AssertionError: {'error': {'message': 'failed to change formatter working directory to ...'}}
```

After replacing the ambiguous exit-code sentinel, the case printed:

```text
formatter cwd case passed: exit-125
```

### Unusable supplied root

RED nonexistent `rootUri` and `rootPath` cases:

```text
FAIL: nixd :: project-config/unusable-root.md
TimeoutError: stderr predicate not met
```

The inaccessible-directory self-review case produced a second genuine RED:

```text
TimeoutError: stderr predicate not met
stderr='... failed to load project configuration at .../.nixd.json: Permission denied ...'
```

This proved file-type validation alone accepted a `chmod 000` directory. The
`access(X_OK)` check made the inaccessible case print:

```text
unusable root case passed: root-path-inaccessible
```

All unusable-root cases then passed as part of the focused suite.

### Two-server isolation

The interleaved two-process integration test was intentionally added after the
evaluator/formatter fixes. It did not invent a separate RED; its failure
sensitivity is the already-observed inherited-cwd defect above. Result:

```text
PASS: nixd :: project-config/two-server-isolation.md
Testing Time: 1.63s
```

## Mutation mapping

- Remove pending warning/send-and-clear: invalid existing files lose their
  exact log or post-`initialized` single warning.
- Warn on a missing file: `missing` fails its log and notification assertions.
- Load a project file after invalid-root fallback: the launch sentinel
  `project file was loaded` replaces the expected builtin evaluator/formatter
  results.
- Prefer valid `rootPath` after invalid `rootUri`: the authoritative-root case
  no longer warns for the supplied URI.
- Remove evaluator child `chdir`: selected-root relative imports time out.
- Remove formatter child `chdir`: selected-root `./formatter` returns an error.
- Treat formatter exit 125 as the cwd sentinel: exit-125 preservation fails.
- Remove effective-access validation: inaccessible root emits the wrong
  `.nixd.json` warning and its workers cannot serve hover.
- Share root/config across processes: one isolation marker appears in the
  other process's hover or formatting result.
- Remove I/O runner cleanup: a failed run can strand `%t-root` or its project
  file inaccessible; the idempotent preflight/finally contract prevents this.

## Final verification

Focused project-configuration suite:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command lit -vv nixd/tools/nixd/test/project-config
```

```text
Total Discovered Tests: 23
  Passed: 23 (100.00%)
Testing Time: 9.28s
```

Compile:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache nix develop --command meson compile -C build
```

```text
ninja: no work to do.
exit 0
```

Full nixd regression:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache nix develop --command meson test -C build regression/nixd
```

```text
1/1 nixd:regression/nixd OK              27.98s
Ok:                1
Fail:              0
```

`git diff --check` and `git diff --cached --check` both exited 0.

## Self-review

- Reviewed every production and test hunk from `ca90029` through the staged
  Task 2 diff.
- Confirmed `rootUri` precedence is unchanged and invalid `rootUri` does not
  fall through to `rootPath`.
- Confirmed the nixd parent never calls `chdir`; only forked evaluator and
  formatter branches do.
- Confirmed one process retains one immutable effective root and Task 1 config
  precedence, editor overlays, active-provider filtering, and worker retention
  remain intact.
- Confirmed missing files remain silent, invalid CLI stays fatal, pending
  warnings clear after one send, and invalid roots skip project loading.
- Confirmed no watchers, ancestor search, multi-root, legacy schema,
  documentation, or schema changes entered the diff.
- Confirmed `.serena/` remained unrelated, untracked, and unstaged.

## Concerns

No known functional concerns remain. The child-side evaluator/formatter
failure branches remain defensive against a root becoming unusable after
initial validation; the deterministic inaccessible-root behavior is covered at
the preflight boundary.
