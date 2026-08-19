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
> Only enable project configuration for workspaces you trust. A project file
> can provide Nix expressions for nixd to evaluate and select formatter
> executables for nixd to run.

Project configuration is disabled by default. To enable it, start nixd with:

```console
nixd --enable-project-config
```

nixd resolves one workspace root in this order: `rootUri`, a non-empty
`rootPath`, then the directory in which nixd was launched. It reads exactly
`<root>/.nixd.json`; it does not search parent directories or nested project
files.

The base configuration is selected in this order:

1. A JSON object supplied with `--config`. Supplying this option suppresses
   project-file loading, even with `--enable-project-config`.
2. A valid, opted-in `<root>/.nixd.json`.
3. nixd's built-in configuration.

Editor settings returned through LSP `workspace/configuration` have the highest
precedence and are applied as an overlay on the selected base. A project file
or `--config` value is a complete base, not a patch over the built-in
configuration. Omitted fields use their C++ value defaults: formatting remains
`["nixfmt"]`, while omitted `nixpkgs` and `options` do not inherit the built-in
expressions.

Project files and `--config` contain the raw configuration object. Editor
settings are wrapped in the client's `nixd` settings or section, as shown in
the editor examples below.

For editor overlays, omitted fields preserve their values from the selected
base. Supplying `options` replaces the complete options map; it does not merge
providers. A `workspace/configuration` result of `[null]` or `[{}]` removes all
editor overrides and restores the base. Empty, malformed, or unsupported
responses retain the active configuration.

A missing `.nixd.json` is silent. An existing unreadable, invalid JSON, or
schema-invalid file is logged with its exact path and error, produces one
warning after initialization, and falls back to the built-in configuration. An
invalid `--config` value is fatal. If a supplied root is unusable, nixd warns,
skips project-file loading, and runs evaluator and formatter children from the
launch directory.

Changes to `.nixd.json` require restarting nixd. Filesystem watching, ancestor
discovery, nested configuration files, and multi-root project configuration
are not supported.

The following is a complete modern `.nixd.json` example:

```json
{
  "$schema": "https://json.schemastore.org/nixd-schema.json",
  "nixpkgs": {
    "expr": "import (builtins.getFlake (builtins.toString ./.)).inputs.nixpkgs { }"
  },
  "options": {
    "nixos": {
      "expr": "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<hostname>.options"
    },
    "home-manager": {
      "expr": "(builtins.getFlake (builtins.toString ./.)).homeConfigurations.\"<username>@<hostname>\".options"
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

Replace the angle-bracket placeholders with names from your flake output.
Relative evaluator expressions, imports, and formatter commands are resolved
from the effective workspace root.


> Please extend this list for your editor, thanks!

<details>
 <summary>VSCode</summary>

For vscode users you should write `settings.json`[^settings] like this:

[^settings]: the file can be applied per-workspace, for example in `.vscode/settings.json`, or globally or remotely. VSCode users should be familiar with [these locations](https://code.visualstudio.com/docs/getstarted/settings).


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
> This annotated JSON is an editor configuration and belongs under the `nixd`
> key. Project files and `--config` use the unwrapped object instead.

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
      // You can write an arbitrary Nix expression here that produces an
      // option declarations attribute set.
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
    // This entry is for standalone Home Manager (choice A).
    "home-manager": {
      "expr": "(builtins.getFlake (builtins.toString ./.)).homeConfigurations.<name>.options"
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

For Home Manager integrated into NixOS (choice B), replace the
`home-manager` entry above with:

```jsonc
"home-manager": {
  "expr": "(builtins.getFlake (builtins.toString ./.)).nixosConfigurations.<name>.options.home-manager.users.type.getSubOptions []"
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

To configure the external command and arguments used for formatting, change the
`formatting` section. A direct string is shorthand for a one-element command
array; an object without `command` retains the default `["nixfmt"]`.

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

Supplying an `options` object replaces the complete active provider map, so
include every provider you want to keep. Provider names are arbitrary. The
expression for each provider selects its option declarations. For example,
NixOS options can be found at:

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
    "nixos": { // This provider name is arbitrary.
      // Evaluate this expression as option declarations.
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
