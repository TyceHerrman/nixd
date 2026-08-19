## Configuration


We support LSP standard `workspace/configuration` for server configurations.

### Default configuration & Who needs configuration

Most important part of package/options features is the path of "nixpkgs".
By default, this is search via standard nix search path.
That is, find nixpkgs via `<nixpkgs>`.

For nix-channels users: nixos option & package features shall work out of box, without any extra effort.

For nix-flake users: (suggestion) you can set $NIX_PATH env to your flake input. e.g.

```nix
{ inputs, ... }:
{
  # NixOS configuration.
  nix.nixPath = [ "nixpkgs=${inputs.nixpkgs}" ];
}
```

If you do not config anything in nixd, here are the defaults (suitable for most nix newbies).

* nixpkgs packages comes from `import <nixpkgs> { }`
* nixos options, evaluated from `<nixpkgs>`

For advanced users, e.g. having many custom modules, or want to extend anyother options system,
"options" field must be extended in the settings, to tell nixd how to get the modules. tldr:

* custom module system (home-manager, nix-darwin, flake-parts, ...)
* custom nixpkgs path, input from your "system" flake


### Configuration sources and precedence

> [!WARNING]
> Enable project configuration only for workspaces you trust. A project file
> can provide Nix expressions for nixd to evaluate and formatter executables
> for nixd to run.

Project configuration is disabled by default. Enable it explicitly:

```console
nixd --enable-project-config
```

nixd selects one root in this order: `rootUri`, a non-empty `rootPath`, then
the directory in which nixd was launched. It reads exactly
`<root>/.nixd.json`; it does not search ancestors or nested projects. If a
supplied root is unusable, nixd warns, skips project-file loading, and falls
back to the launch directory.

The base configuration is selected in this order:

1. JSON passed to `--config`; this suppresses project-file loading.
2. A valid opted-in `<root>/.nixd.json`.
3. Built-in defaults.

`--config` and `.nixd.json` are complete, unwrapped configuration objects:
`formatting`, named `options`, `nixpkgs`, and `diagnostic`. They are not
patches over the built-ins, and legacy `eval.target` and `options.target` are
not supported. Omitted fields use their C++ defaults, including
`formatting.command` defaulting to `["nixfmt"]`.

Editor settings come from LSP `workspace/configuration`, under the client's
`nixd` section. They are a partial overlay rebuilt from the selected base:
omitted fields retain base values, while a supplied `options` object replaces
the entire options map. `[null]` and `[{}]` remove editor overrides and restore
the base; empty, malformed, or unsupported responses retain the active
configuration.

A missing `.nixd.json` is silent. An existing unreadable, invalid JSON, or
schema-invalid file logs its path and error, warns once after `initialized`,
and falls back to built-in defaults. An invalid `--config` is fatal.

Restart nixd after changing `.nixd.json`: there is no filesystem watcher.
Ancestor discovery, nested configuration files, and multi-root project
configuration are unsupported. Relative evaluator expressions and formatter
commands run from the effective workspace root (or the launch-directory
fallback).

Example `.nixd.json`:

```json
{
  "$schema": "https://json.schemastore.org/nixd-schema.json",
  "nixpkgs": {
    "expr": "import (builtins.getFlake (builtins.toString ./.)).inputs.nixpkgs { }"
  },
  "options": {
    "nixos": {
      "expr": "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<hostname>.options"
    }
  },
  "formatting": {
    "command": ["nixfmt"]
  },
  "diagnostic": {
    "suppress": ["sema-extra-with"]
  }
}
```

Replace `<hostname>` with a flake output name.

### Editor configuration

Editor configuration belongs in the client's `nixd` section. Its location is
determined by the editor setup.


> Please extend this list for your editor, thanks!

<details>
 <summary>VSCode</summary>

For vscode users you should write `settings.json`[^settings] like this:

[^settings]: the file could be applied per-workspace, i.e. `.vscode/settings.json`, our globally, remotely. VSCode users should familiar with [these locations](https://code.visualstudio.com/docs/getstarted/settings).


```
{
    "nix.serverSettings": {
        // settings for 'nixd' LSP
        "nixd": {
            "formatting": {
              // ...
            },
            "options": {
              // ...
            }
        }
  }
}
```

</details>

<details>
 <summary>Neovim</summary>

Configuration via Neovim [built-in LSP](https://neovim.io/doc/user/lsp/#lsp). If you want to make configuration changes based on different projects, you can use Neovim official [exrc](https://neovim.io/doc/user/options/#'exrc') option.

```lua
local nvim_lsp = vim.lsp
nvim_lsp.config("nixd", {
  cmd = { "nixd" },
  filetypes = { "nix" },
  root_markers = { "flake.nix", ".git" },
  settings = {
    nixd = {
      nixpkgs = {
        expr = "import <nixpkgs> { }",
      },
      formatting = {
        command = { "nixfmt" },
      },
      options = {
        nixos = {
          expr = '(builtins.getFlake (toString ./.)).nixosConfigurations.<hostname>.options',
        },
        home_manager = {
          expr = '(builtins.getFlake (toString ./.)).homeConfigurations."<username>@<hostname>".options',
        },
      },
    },
  },
})
nvim_lsp.enable("nixd")
```
</details>

<details>
  <summary>Emacs</summary>

  Configuration via [lsp-mode](https://github.com/emacs-lsp/lsp-mode) plugin. As of Oct 24, 2024, lsp-mode master has support for nixd autocompletion and formatting options.

  ```elisp
(use-package nix-mode
  :after lsp-mode
  :ensure t
  :hook
  (nix-mode . lsp-deferred) ;; So that envrc mode will work
  :custom
  (lsp-disabled-clients '((nix-mode . nix-nil))) ;; Disable nil so that nixd will be used as lsp-server
  :config
  (setq lsp-nix-nixd-server-path "nixd"
        lsp-nix-nixd-formatting-command [ "nixfmt" ]
        lsp-nix-nixd-nixpkgs-expr "import <nixpkgs> { }"
        lsp-nix-nixd-nixos-options-expr "(builtins.getFlake \"/home/nb/nixos\").nixosConfigurations.mnd.options"
        lsp-nix-nixd-home-manager-options-expr "(builtins.getFlake \"/home/nb/nixos\").homeConfigurations.\"nb@mnd\".options"))

(add-hook! 'nix-mode-hook
           ;; enable autocompletion with company
           (setq company-idle-delay 0.1))

  ```

Configuration via [Eglot](https://www.gnu.org/software/emacs/manual/html_node/eglot/).  Eglot has been included in Emacs core since 29.1.  You can configure nixd per project by putting the following snippet into the `.dir-locals.el` file in your project.
```lisp
((nil . ((eglot-workspace-configuration . (:nixd (:options (:nixos (:expr "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.artemis.options"))))))))
```
You can also set the `eglot-workspace-configuration` variable globally (by using `setq-default`), if you prefer that.

</details>

### Configuration overview

> [!NOTE]
> This is an editor overlay and belongs under the `nixd` key. Project files and
> `--config` use the same object without that wrapper. In an editor overlay,
> omitted fields preserve the selected base configuration.

```jsonc
{
  "nixpkgs": {
    // For flake.
    // "expr": "import (builtins.getFlake \"/home/lyc/workspace/CS/OS/NixOS/flakes\").inputs.nixpkgs { }   "

    // This expression will be interpreted as "nixpkgs" toplevel
    // Nixd provides package, lib completion/information from it.
    ///
    // Resource Usage: Entries are lazily evaluated, entire nixpkgs takes 200~300MB for just "names".
    ///                Package documentation, versions, are evaluated by-need.
    "expr": "import <nixpkgs> { }"
  },
  "formatting": {
    // Which command you would like to do formatting
    "command": [ "nixfmt" ]
  },
  // Tell the language server your desired option set, for completion
  // This is lazily evaluated.
  "options": { // Map of eval information
      // By default, this entriy will be read from `import <nixpkgs> { }`
      // You can write arbitary nix expression here, to produce valid "options" declaration result.
      //
      // *NOTE*: Replace "<name>" below with your actual configuration name.
      // If you're unsure what to use, you can verify with `nix repl` by evaluating
      // the expression directly.
      //
      "nixos": {
          "expr": "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<name>.options"
      },

    // Before configuring Home Manager options, consider your setup:
    // Which command do you use for home-manager switching?
    //
    //  A. home-manager switch --flake .#... (standalone Home Manager)
    //  B. nixos-rebuild switch --flake .#... (NixOS with integrated Home Manager)
    //
    // Configuration examples for both approaches are shown below.
    "home-manager": {
      // A:
      "expr": "(builtins.getFlake (builtins.toString ./.)).homeConfigurations.<name>.options"

      // B:
      "expr": "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<name>.options.home-manager.users.type.getSubOptions []"
    }
  },
  // Control the diagnostic system
  "diagnostic": {
    "suppress": [
      "sema-extra-with"
    ]
  }
}
```

### Fields explanation

#### Diagnostic Control ("diagnostic")

Some users might feel confident in their understanding of the language and
prefer to suppress diagnostics altogether. This can be achieved by utilizing the diagnostic field.

```jsonc
{
  "diagnostic": {
    // A list of diagnostic short names
    "suppress": [
      "sema-extra-with"
    ]
  }
}
```

#### Format (`formatting`)

Configure the formatter with a command array, or a direct string shorthand for
a one-element array. In a complete project/CLI base, an object without
`command` uses `["nixfmt"]`; an omitted editor-overlay command preserves the
base formatter.

```jsonc
{
  "formatting": {
    // The external command to be invoked for formatting
    "command": [ "some-command" ]
  }
}
```

#### Options ("options")

This is our support for nixpkgs option system.

Generally options are merged under a special attribute path.
For example, NixOS options could be found at:

```
<flakeref>#nixosConfigurations.<name>.options
```

And, home-manager options also could be found at:

```
<flakeref>#homeConfigurations.<name>.options
```

In our option system, you need to specify which option set you'd like to use.

```jsonc
{
  // Tell the language server your desired option set, for completion
  // This is lazily evaluated.
  "options": { // Map of eval information
    // If this is ommited, default search path (<nixpkgs>) will be used.
    "nixos": { // This name "nixos" could be arbitary.
      // The expression to eval, intepret it as option declarations.
      "expr": "(builtins.getFlake \"/home/lyc/flakes\").nixosConfigurations.adrastea.options"
    },

    // By default there is no home-manager options completion, thus you can add this entry.
    "home-manager": {
      "expr": "(builtins.getFlake \"/home/lyc/flakes\").homeConfigurations.\"lyc@adrastea\".options"
    },

    // For flake-parts options.
    // Firstly read the docs here to enable "debugging", exposing declarations for nixd.
    // https://flake.parts/debug
    "flake-parts": {
      "expr": "(builtins.getFlake \"/path/to/your/flake\").debug.options"
    },
    // For a `perSystem` flake-parts option:
    "flake-parts2": {
      "expr": "(builtins.getFlake \"/path/to/your/flake\").currentSystem.options"
    }
  }
}
```

If you aren't a flakes user with standalone home-manager with a vanilla install then the following expression should make home-manager options appear:

```jsonc
{
  "options": {
    "home-manager": {
      "expr": "(import <home-manager/modules> { configuration = ~/.config/home-manager/home.nix; pkgs = import <nixpkgs> {}; }).options"
    }
  }
}
```

## Q & A

### Home-manager options completion does not work. What is `homeConfigurations`?

See [configuration overview](#configuration-overview).
If your home-manager is installed as part of a NixOS module,
the options list can be retrieved like this:

```nix
(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<name>.options.home-manager.users.type.getSubOptions []
```

### Still not working?

Try testing your expression in `nix repl`. This will help you diagnose evaluation issues.
For example:

```
nix-repl> (builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<name>.options
error: syntax error, unexpected SPATH, expecting ID or OR_KW or DOLLAR_CURLY or '"'
  at «string»:1:65:
       1| (builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<name>.options
        |                                                                 ^
```

Replace `<name>` with your actual configuration name:

```
nix-repl> (builtins.getFlake (builtins.toString ./.)).nixosConfigurations.adrastea.options
{
  _module = { ... };
  appstream = { ... };
  assertions = { ... };
  boot = { ... };
  # ... more options ..., this is expected.
}
```
