/// \file
/// \brief Declares workspace configuration schema
#pragma once

#include <llvm/Support/JSON.h>

#include <map>
#include <optional>
#include <string>
#include <vector>

namespace nixd {

// NOLINTBEGIN(readability-identifier-naming)
struct Configuration {
  struct Formatting {
    std::vector<std::string> command = {"nixfmt"};
  } formatting;

  struct OptionProvider {
    /// \brief Expression to eval. Select this attrset as eval .options
    std::string expr;
  };

  std::map<std::string, OptionProvider> options;

  struct NixpkgsProvider {
    /// \brief Expression to eval. Treat it as "import <nixpkgs> { }"
    std::string expr;
  } nixpkgs;

  struct Diagnostic {
    std::vector<std::string> suppress;
  } diagnostic;
};

bool fromJSON(const llvm::json::Value &Params, Configuration::Diagnostic &R,
              llvm::json::Path P);

bool fromJSON(const llvm::json::Value &Params, Configuration::Formatting &R,
              llvm::json::Path P);

bool fromJSON(const llvm::json::Value &Params, Configuration::OptionProvider &R,
              llvm::json::Path P);

bool fromJSON(const llvm::json::Value &Params,
              Configuration::NixpkgsProvider &R, llvm::json::Path P);

bool fromJSON(const llvm::json::Value &Params, Configuration &R,
              llvm::json::Path P);

/// The editor provides a partial configuration. It is applied to the immutable
/// base selected at initialization rather than to the preceding editor value.
struct ConfigurationPatch {
  struct Formatting {
    std::optional<std::vector<std::string>> command;
  };
  struct NixpkgsProvider {
    std::optional<std::string> expr;
  };
  struct Diagnostic {
    std::optional<std::vector<std::string>> suppress;
  };

  std::optional<Formatting> formatting;
  std::optional<std::map<std::string, Configuration::OptionProvider>> options;
  std::optional<NixpkgsProvider> nixpkgs;
  std::optional<Diagnostic> diagnostic;
};

bool fromJSON(const llvm::json::Value &Params, ConfigurationPatch &R,
              llvm::json::Path P);
Configuration overlay(Configuration Base, const ConfigurationPatch &Patch);

enum class ProjectConfigErrorKind { IOError, JSONError, SchemaError };

struct ProjectConfigError {
  ProjectConfigErrorKind kind;
  std::string path;
  std::string message;
};

struct ProjectConfigLoadResult {
  std::optional<Configuration> config;
  std::optional<ProjectConfigError> error;
};

/// Load exactly the project root's .nixd.json, without ancestor traversal.
ProjectConfigLoadResult loadProjectConfig(llvm::StringRef Root);

// NOLINTEND(readability-identifier-naming)

} // namespace nixd
