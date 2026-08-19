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
- Changed directory only inside the forked formatter child. A close-on-exec
  setup handshake establishes `chdir` and `exec` outcomes before the parent
  streams the draft, while a thread-scoped SIGPIPE mask turns a closed child
  stdin into a coherent write error. The dedicated cwd signal remains distinct
  from ordinary formatter exit status 125.
- Corrected `forkPiped` stderr-end ownership and gave its partial pipe/fork
  paths scoped descriptor cleanup. Formatter stdin/stdout/stderr/setup
  descriptors are likewise scoped and every post-fork path reaps the child.
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
- `nixd/lib/Support/ForkPiped.cpp`

Tests:

- `nixd/tools/nixd/test/project-config/lsp_test_client.py`
- `startup-warnings.{md,py}`
- `evaluator-cwd.{md,py}`
- `formatter-cwd.{md,py}`
- `formatter-process-lifecycle.{md,py}`
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

The original per-case malformed/schema RED transcripts were not retained
separately; the statements above are the contemporaneous observed failure
classification, not reconstructed literal output. Review follow-up reran the
three strengthened GREEN cases with a literal fake built-in formatter:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command sh -c 'for case in io json schema; do python3 nixd/tools/nixd/test/project-config/startup-warnings.py "$case" || exit; done'
```

```text
startup warning case passed: io
startup warning case passed: json
startup warning case passed: schema
```

Each case now requires exact `newText` from a PATH-injected `nixfmt`, proving
the server selected the literal built-in formatter after the invalid project
file instead of merely replying with the expected request ID.

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

The original selector-specific RED outputs were not retained separately.
Review follow-up captured the current selector matrix explicitly:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command sh -c 'for case in root-uri root-path launch; do python3 nixd/tools/nixd/test/project-config/evaluator-cwd.py "$case" || exit; done'
```

```text
evaluator cwd case passed: root-uri
evaluator cwd case passed: root-path
evaluator cwd case passed: launch
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

Review follow-up explicitly reran the full formatter selector matrix:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command sh -c 'for case in root-uri root-path launch exit-125; do python3 nixd/tools/nixd/test/project-config/formatter-cwd.py "$case" || exit; done'
```

```text
formatter cwd case passed: root-uri
formatter cwd case passed: root-path
formatter cwd case passed: launch
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

Review follow-up also captured each current GREEN result directly:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command sh -c 'for case in root-uri root-path root-path-inaccessible; do python3 nixd/tools/nixd/test/project-config/unusable-root.py "$case" || exit; done'
```

```text
unusable root case passed: root-uri
unusable root case passed: root-path
unusable root case passed: root-path-inaccessible
```

### Two-server isolation

The interleaved two-process integration test was intentionally added after the
evaluator/formatter fixes. It did not invent a separate RED; its failure
sensitivity is the already-observed inherited-cwd defect above. Result:

```text
PASS: nixd :: project-config/two-server-isolation.md
Testing Time: 1.63s
```

### Formatter process lifecycle review follow-up

Removed-root RED command:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command python3 nixd/tools/nixd/test/project-config/formatter-process-lifecycle.py removed-root
```

Literal RED result with the selected root removed after initialization and a
2 MiB draft:

```text
AssertionError: nixd terminated during formatting: -13
```

This exposed the parent writing before it could inspect the child cwd failure;
SIGPIPE terminated nixd instead of returning the dedicated cwd error.

Descriptor-stability RED used the same environment and:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command python3 nixd/tools/nixd/test/project-config/formatter-process-lifecycle.py descriptor-stability
```

With `RLIMIT_NOFILE=32`, the current two-descriptor/request leak failed before
the twelve requested successful formats completed:

```text
AssertionError: nixd failed on formatting request 26
```

After the setup-handshake, safe-write, and scoped-FD changes, the direct GREEN
results were:

```text
formatter process lifecycle case passed: removed-root
formatter process lifecycle case passed: descriptor-stability
formatter cwd case passed: exit-125
```

The missing-executable case was added after the fix to cover the new exec
failure marker without inventing a historical RED. The combined real-server
test result was:

```text
PASS: nixd :: project-config/formatter-process-lifecycle.md
Testing Time: 1.49s
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
- Stream before the child setup handshake: the removed-root 2 MiB case kills
  nixd with SIGPIPE instead of returning a cwd error.
- Stop scoping formatter stdout/stderr or restore the incorrect `Err`
  assignment: the bounded-descriptor case exhausts `RLIMIT_NOFILE=32`.
- Skip reaping on setup/exec failure: removed-root or missing-executable cases
  strand a child or fail to return a coherent response.
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
Total Discovered Tests: 24
  Passed: 24 (100.00%)
Testing Time: 8.00s
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
1/1 nixd:regression/nixd OK              26.12s
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
- Confirmed the setup pipe closes on successful exec, cwd failure is classified
  only after reaping the dedicated signal, exec failure returns without
  streaming, and write failure cannot terminate the process via SIGPIPE.
- Confirmed all formatter and `forkPiped` parent descriptors have scoped
  ownership, partial pipe/fork failures clean up, and repeated requests remain
  stable under the bounded descriptor limit.
- Confirmed `.serena/` remained unrelated, untracked, and unstaged.

## Concerns

The child-side evaluator/formatter failure branches remain defensive against a
root becoming unusable after initial validation; the deterministic
inaccessible-root behavior is covered at the preflight boundary.

Pre-existing and outside this bounded review: the formatter parent waits for
the child before draining stdout/stderr, so a formatter producing enough output
to fill either pipe can deadlock. This wave corrects descriptor ownership,
setup ordering, SIGPIPE safety, and cleanup without redesigning formatter I/O.
