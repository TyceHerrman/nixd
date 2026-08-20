## Configuration

`nixd` starts with built-in configuration and can receive configuration from the command line, an explicitly trusted project file, and the LSP client. The same strict JSON patch grammar is used for every non-null configuration source. The [JSON schema](nixd-schema.json) provides editor assistance; nixd validates input itself and does not fetch a schema URL at runtime.

### Sources and trust

The startup base is selected in this order:

1. Built-in defaults. `nixpkgs.expr` defaults to `import <nixpkgs> { }`, with a default `nixos` option provider.
2. An explicit `--config=<JSON>` patch, if present. It is authoritative: `--config={}` is an explicit empty patch and still prevents project-file inspection.
3. `<project-root>/.nixd.json`, only when `--enable-project-config` is passed and `--config` is absent.

Project configuration is intentionally opt-in because its expressions can evaluate Nix and its formatter command can execute a program. Do not enable it for an untrusted checkout. Without `--enable-project-config`, nixd never reads `.nixd.json`.

The project file is read once during initialization. It is exactly `<project-root>/.nixd.json`: nixd does not search parent directories, watch the file, or reload it. A missing file is silent. An unreadable, malformed, or schema-invalid file leaves the startup base and working directory unchanged, logs the error, and sends one warning after the client has initialized.

### Project root and working directory

When project configuration is eligible, nixd chooses one root from `initialize` in this order:

1. A usable `rootUri`.
2. A nonempty `rootPath`.
3. The sole `workspaceFolders` entry.
4. The process launch directory.

The selected LSP root must name an accessible directory. A malformed or unusable higher-priority value is a failure, not a reason to fall through to a lower-priority field. More than one workspace folder is unsupported and also prevents project-file loading. These failures are logged and reported as startup warnings, retaining the launch directory.

A valid project file, including `{}`, makes the selected project root the working directory for evaluator workers and formatter children. If the file is absent or invalid, or project configuration is not eligible, they use the launch directory instead. An explicit `--config` never selects a project root.

### Patch format

Configuration is a patch: every top-level section is optional, and a present section replaces only the fields it contains. Valid top-level keys are `$schema`, `nixpkgs`, `formatting`, `options`, and `diagnostic`. Unknown keys are rejected at every object level. Explicit `null` is rejected in a patch.

```json
{
  "$schema": "https://json.schemastore.org/nixd-schema.json",
  "nixpkgs": {
    "expr": "import <nixpkgs> { }"
  },
  "formatting": {
    "command": ["nixfmt"]
  },
  "options": {
    "nixos": {
      "expr": "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.host.options"
    },
    "home-manager": {
      "expr": "(builtins.getFlake (builtins.toString ./.)).homeConfigurations.\"user@host\".options"
    }
  },
  "diagnostic": {
    "suppress": ["sema-extra-with"]
  }
}
```

`$schema`, when present, is string metadata only. It does not make nixd download or interpret an external schema.

| Section | Accepted patch | Effect |
| --- | --- | --- |
| `nixpkgs` | Object with optional string `expr` | Replaces the package/library expression. `""` disables nixpkgs evaluation. |
| `formatting` | Nonempty string, or object with optional string-array `command` | The string is shorthand for a one-element command. `command: []` disables formatting. |
| `options` | Object mapping arbitrary names to `{ "expr": "nonempty string" }` | Replaces the complete option-provider map. `{}` disables option completion and lookup. |
| `diagnostic` | Object with optional string-array `suppress` | Replaces suppressed diagnostic short names. `[]` suppresses nothing. |

Arrays may be empty where shown. Object forms reject unknown keys; option providers require their nonempty `expr`. For example, these are rejected:

```json
{ "formatting": null }
```

```json
{ "formatting": { "command": null } }
```

```json
{ "options": { "nixos": { "expr": "", "extra": true } } }
```

```json
{ "diagnostic": { "unknown": [] } }
```

### Editor configuration

Place editor settings under the `nixd` section. For example, Neovim's built-in LSP configuration can provide the same patch:

```lua
vim.lsp.config("nixd", {
  cmd = { "nixd" },
  filetypes = { "nix" },
  settings = {
    nixd = {
      formatting = { command = { "nixfmt" } },
      nixpkgs = { expr = "import <nixpkgs> { }" },
      options = {
        nixos = {
          expr = "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.host.options",
        },
      },
    },
  },
})
vim.lsp.enable("nixd")
```

If the client advertises `workspace.configuration`, nixd sends one initial `workspace/configuration` request after the `initialized` notification, and therefore after the `initialize` reply, requesting the `nixd` section. A later `workspace/didChangeConfiguration` notification requests a fresh value. Each reply must be an array containing exactly one item.

An editor reply is always applied to the immutable startup base, not to the previous editor reply. Omitted editor fields therefore revert to the startup value. The wrapper values `[null]` and `[{}]` both reset the effective configuration to that base. For any other reply, the strict patch rules above apply. A malformed reply, transport failure, or stale reply leaves the active configuration unchanged; when replies race, only the latest request may take effect.

### Provider and formatter behavior

Changing `nixpkgs` or `options` invalidates the old provider generation before replacement evaluation begins. Queries retain private snapshots and publish provider-derived results only if the snapshot is still current. Option queries are all-or-none: if any configured option provider is unavailable, fails, or is replaced, no partial option result is returned. Static language results remain available while a provider is changing.

Formatting runs the effective `formatting.command` with the document on standard input. An empty command (`[]`) returns no edits and starts no child process. Unchanged formatter output also returns no edits. Launch, I/O, nonzero-exit, and signal failures are returned as LSP errors. nixd drains the formatter's standard output and standard error concurrently and reaps the direct child.

On LSP shutdown, nixd owns and terminates only formatter children it launched directly. It does not manage a formatter's descendants or implement generic process-tree ownership. A closed input loop does not retroactively kill an already accepted formatter request; shutdown does terminate active direct formatter children.

### Shutdown and reload boundaries

Project configuration is startup-only. There is no `.nixd.json` watcher or reload protocol; use an editor configuration change or restart nixd to change the effective configuration.

nixd also tracks only its own pending outbound LSP calls. On `shutdown`, and when the input loop ends, it closes that outbound gate and fails pending client-request callbacks after releasing its internal lock. New outbound calls are rejected. This is deliberately narrow: normal inbound request handling, including the reply to `shutdown`, remains possible, and it is not a general request or process-lifecycle framework.
