# Task 3 report: modern configuration documentation and JSON Schema

## Status

Implemented on branch `project-config` from accepted Task 2 HEAD
`cdd0f456fcb077d64144455824fd391338c3e8d4`.

## Review round 1 follow-up

Review found that the format-field explanation conflated complete-base
defaulting with editor-overlay preservation, and that an earlier sentence
could still imply that the options map is merged. The documentation now states
separately that a complete project/CLI `formatting` object without `command`
uses the C++ `["nixfmt"]` default, while an editor overlay that omits
`formatting.command` preserves the selected base formatter. The early options
guidance now says to configure the named options map without merge-like
"extend" wording.

## Documentation changes

- Replaced the obsolete statement that nixd does not read `.nixd.json` with a
  trust warning and the opt-in `nixd --enable-project-config` command.
- Documented exact root resolution (`rootUri`, non-empty `rootPath`, captured
  launch directory) and exact `<root>/.nixd.json` loading without ancestor or
  nested-file discovery.
- Documented base precedence (`--config`, opted-in project file, built-ins)
  and editor `workspace/configuration` as the highest-precedence overlay.
- Distinguished raw project/CLI objects from editor settings wrapped in the
  client's `nixd` section.
- Explained that project/CLI sources are complete bases: omitted formatting
  retains `nixfmt`, while omitted `nixpkgs` and `options` do not inherit the
  built-in expressions.
- Documented immutable-base overlay behavior, full `options` replacement,
  `[null]`/`[{}]` reset behavior, and retention of the active configuration
  after empty, malformed, or unsupported responses.
- Documented silent missing files, logged and once-warned invalid files with
  built-in fallback, fatal invalid `--config`, and unusable-root fallback that
  skips project loading and uses the launch directory for children.
- Documented the restart requirement and lack of filesystem watching,
  ancestor discovery, nested configuration, and multi-root support.
- Added a complete modern `.nixd.json` example with the public `$schema` URI,
  `nixpkgs.expr`, named option providers, formatter argv, and diagnostic
  suppressions.
- Retained the editor examples, made the two Home Manager expressions separate
  alternatives, clarified formatter string/object forms, and removed stale
  wording that could imply option-provider fallback or merging.

## Schema mapping

`nixd/docs/nixd-schema.json` remains draft-07 and keeps the public
`https://json.schemastore.org/nixd-schema.json` identifier.

- Root: optional `formatting`, `options`, `nixpkgs`, and `diagnostic`, with
  `additionalProperties: true` to match unvisited-key acceptance and permit
  the example's `$schema` property.
- `formatting`: direct string shorthand or an object with optional
  `command: string[]`; the command default is annotated as `["nixfmt"]`, and
  the object permits additional properties.
- `options`: arbitrary provider names validated by `additionalProperties`
  against an object with optional string `expr`; provider objects permit
  additional properties.
- `nixpkgs`: object with optional string `expr` and additional properties.
- `diagnostic`: object with optional `suppress: string[]` and additional
  properties.
- Removed legacy `eval.target`, `options.enable`, and `options.target`.
- Replaced the stale comment link with the current repository documentation
  path.

## Validation and tests

Every Nix command used
`XDG_CACHE_HOME=/private/tmp/codex-nixd-cache`.

JSON syntax:

```sh
python3 -m json.tool nixd/docs/nixd-schema.json
```

Result: exit 0.

The existing Nix development environment was probed for `check-jsonschema`, a
`jsonschema` CLI, and Python's `jsonschema` module. None was available (the
Python import raised `ModuleNotFoundError`), so no JSON-Schema meta-validator
was run and no dependency was added.

Focused real-server project-configuration suite:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache MESON_BUILD_ROOT=$PWD/build/nixd/tools NIXD_ATTRSET_EVAL=$PWD/build/nixd/tools/nixd-attrset-eval PATH=$PWD/build/nixd/tools:$PATH nix develop --command lit -vv nixd/tools/nixd/test/project-config
```

Result: 24/24 passed, 0 failed, in 13.28 seconds.

Compile:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache nix develop --command meson compile -C build
```

Result: exit 0; `ninja: no work to do` because this task changes only
documentation and schema data.

Focused nixd regression:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache nix develop --command meson test -C build regression/nixd
```

Result: 1/1 passed, `Fail: 0`, in 51.23 seconds.

Full Meson suite:

```sh
XDG_CACHE_HOME=/private/tmp/codex-nixd-cache nix develop --command meson test -C build
```

Result: 6/6 passed, `Fail: 0`; the longest test was `regression/nixd` at
52.71 seconds.

`git diff --check` exited 0.

## Self-review

- Reviewed the complete `cdd0f45` through working-tree diff and confirmed the
  Task 3 changes are limited to `configuration.md`, `nixd-schema.json`, and
  this report; runtime C++ and real-server tests remain unchanged.
- Rechecked root, source-precedence, warning, child-working-directory, restart,
  and unsupported-feature statements against the accepted Task 1/2 parser,
  lifecycle implementation, CLI help, fixtures, and real-server tests.
- Confirmed `$schema` in the example is accepted by root
  `additionalProperties: true` and matches the schema's public `$id`.
- The initial format-field wording did not distinguish complete-base defaulting
  from editor-overlay preservation. Review round 1 identified that ambiguity;
  the corrected overview and field explanation now state both behaviors
  explicitly while retaining the parser's string shorthand and command array.
- Confirmed each fixed nested object permits unvisited keys, while arbitrary
  `options` values must still be provider objects with any supplied `expr`
  typed as a string.
- Confirmed complete-base wording does not imply that omitted project/CLI
  fields inherit built-ins, and editor wording does not imply provider-map
  merging or composition over a previous editor overlay.
- Confirmed legacy schema fields and the stale documentation link are gone,
  the Home Manager alternatives no longer duplicate `expr`, and no prose-grep
  tests or dependencies were added.
- Confirmed unrelated untracked `.serena/` remains untouched and unstaged.

## Concerns

Review round 1 found and resolved a documentation-only ambiguity between base
defaulting and overlay preservation, plus one remaining merge-like options
phrase. No runtime behavior changed. The development environment does not
include a JSON-Schema meta-validator; syntax, schema structure, parser
alignment, and executable runtime behavior were validated without adding a
task-only dependency.
