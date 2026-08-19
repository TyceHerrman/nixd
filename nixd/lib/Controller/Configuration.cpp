#include "nixd/Controller/Controller.h"
#include "nixd/Eval/Launch.h"
#include "nixd/Support/JSON.h"

#include <llvm/Support/MemoryBuffer.h>

using namespace nixd;
using namespace lspserver;
using llvm::json::ObjectMapper;
using llvm::json::Value;

bool nixd::fromJSON(const Value &Params, Configuration::Diagnostic &R,
                    llvm::json::Path P) {
  ObjectMapper O(Params, P);
  return O && O.mapOptional("suppress", R.suppress);
}

bool nixd::fromJSON(const Value &Params, Configuration::Formatting &R,
                    llvm::json::Path P) {
  // If it is a single string, treat it as a single vector
  if (auto Str = Params.getAsString()) {
    R.command = {Str->str()};
    return true;
  }
  ObjectMapper O(Params, P);
  return O && O.mapOptional("command", R.command);
}

bool nixd::fromJSON(const Value &Params, Configuration::OptionProvider &R,
                    llvm::json::Path P) {
  ObjectMapper O(Params, P);
  return O && O.mapOptional("expr", R.expr);
}

bool nixd::fromJSON(const Value &Params, Configuration::NixpkgsProvider &R,
                    llvm::json::Path P) {
  ObjectMapper O(Params, P);
  return O && O.mapOptional("expr", R.expr);
}

bool nixd::fromJSON(const Value &Params, Configuration &R, llvm::json::Path P) {
  ObjectMapper O(Params, P);
  return O                                            //
         && O.mapOptional("formatting", R.formatting) //
         && O.mapOptional("options", R.options)       //
         && O.mapOptional("nixpkgs", R.nixpkgs)       //
         && O.mapOptional("diagnostic", R.diagnostic) //
      ;
}

namespace {

template <typename T>
bool mapPatchField(const llvm::json::Object &Object, llvm::StringRef Name,
                   std::optional<T> &Result, llvm::json::Path P);

bool fromJSON(const Value &Params, ConfigurationPatch::Formatting &R,
              llvm::json::Path P) {
  if (auto String = Params.getAsString()) {
    R.command = {String->str()};
    return true;
  }
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object or string");
    return false;
  }
  return mapPatchField(*Object, "command", R.command, std::move(P));
}

bool fromJSON(const Value &Params, ConfigurationPatch::NixpkgsProvider &R,
              llvm::json::Path P) {
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object");
    return false;
  }
  return mapPatchField(*Object, "expr", R.expr, std::move(P));
}

bool fromJSON(const Value &Params, ConfigurationPatch::Diagnostic &R,
              llvm::json::Path P) {
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object");
    return false;
  }
  return mapPatchField(*Object, "suppress", R.suppress, std::move(P));
}

template <typename T>
bool mapPatchField(const llvm::json::Object &Object, llvm::StringRef Name,
                   std::optional<T> &Result, llvm::json::Path P) {
  const Value *Field = Object.get(Name);
  if (!Field)
    return true;
  T Parsed;
  if (!fromJSON(*Field, Parsed, P.field(Name)))
    return false;
  Result = std::move(Parsed);
  return true;
}

} // namespace

bool nixd::fromJSON(const Value &Params, ConfigurationPatch &R,
                    llvm::json::Path P) {
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object");
    return false;
  }
  return mapPatchField(*Object, "formatting", R.formatting, P) &&
         mapPatchField(*Object, "options", R.options, P) &&
         mapPatchField(*Object, "nixpkgs", R.nixpkgs, P) &&
         mapPatchField(*Object, "diagnostic", R.diagnostic, std::move(P));
}

Configuration nixd::overlay(Configuration Base,
                            const ConfigurationPatch &Patch) {
  if (Patch.formatting && Patch.formatting->command)
    Base.formatting.command = *Patch.formatting->command;
  if (Patch.options)
    Base.options = *Patch.options;
  if (Patch.nixpkgs && Patch.nixpkgs->expr)
    Base.nixpkgs.expr = *Patch.nixpkgs->expr;
  if (Patch.diagnostic && Patch.diagnostic->suppress)
    Base.diagnostic.suppress = *Patch.diagnostic->suppress;
  return Base;
}

ProjectConfigLoadResult nixd::loadProjectConfig(llvm::StringRef Root) {
  const std::string Path =
      (std::filesystem::path(Root.str()) / ".nixd.json").string();
  llvm::ErrorOr<std::unique_ptr<llvm::MemoryBuffer>> Input =
      llvm::MemoryBuffer::getFile(Path);
  if (!Input) {
    const std::error_code EC = Input.getError();
    if (EC == std::errc::no_such_file_or_directory)
      return {};
    return {.error = ProjectConfigError{
                .kind = ProjectConfigErrorKind::IOError,
                .path = Path,
                .message = EC.message(),
            }};
  }

  try {
    return {.config = nixd::fromJSON<Configuration>(
                nixd::parse((*Input)->getBuffer()))};
  } catch (const JSONParseException &Err) {
    return {.error = ProjectConfigError{
                .kind = ProjectConfigErrorKind::JSONError,
                .path = Path,
                .message = Err.what(),
            }};
  } catch (const JSONSchemaException &Err) {
    return {.error = ProjectConfigError{
                .kind = ProjectConfigErrorKind::SchemaError,
                .path = Path,
                .message = Err.what(),
            }};
  }
}

void Controller::onDidChangeConfiguration(
    const DidChangeConfigurationParams &Params) {
  // FIXME: incrementally change?
  fetchConfig();
}

void Controller::updateConfig(Configuration NewConfig) {
  {
    std::lock_guard G(ConfigLock);
    Config = NewConfig;
  }

  {
    std::unique_lock Guard(NixpkgsLock);
    ActiveNixpkgs = !NewConfig.nixpkgs.expr.empty();
    /// Evaluate nixpkgs and options, using user-provided config.
    if (ActiveNixpkgs)
      if (AttrSetClient *Client = nixpkgsEval().client())
        evalExprWithProgress(*Client, NewConfig.nixpkgs.expr,
                             "nixpkgs entries");
  }
  {
    std::lock_guard _(OptionsLock);
    ActiveOptions.clear();
    // For each option configuration, update the worker.
    for (const auto &[Name, Opt] : NewConfig.options) {
      ActiveOptions.insert(Name);
      auto &Client = Options[Name];
      if (!Client) {
        // If it does not exist. Launch a new client.
        startOption(Name, Client, Root.path);
      }
      assert(Client);
      if (AttrSetClient *Worker = Client->client())
        evalExprWithProgress(*Worker, Opt.expr, Name);
    }
  }

  // Update the diagnostic part.
  updateSuppressed(NewConfig.diagnostic.suppress);

  // After all, notify all AST modules the diagnostic set has been updated.
  std::lock_guard TUsGuard(TUsLock);
  for (const auto &[File, TU] : TUs) {
    publishDiagnostics(File, std::nullopt, TU->src(), TU->diagnostics());
  }
}

void Controller::fetchConfig() {
  auto Action = [this](llvm::Expected<llvm::json::Value> Resp) mutable {
    if (!Resp) {
      elog("workspace/configuration: {0}", Resp.takeError());
      return;
    }

    // LSP response is a json array, just take the first.
    if (Resp->kind() != llvm::json::Value::Array) {
      lspserver::elog("workspace/configuration response is not an array: {0}",
                      *Resp);
      return;
    }
    const auto &Responses = *Resp->getAsArray();
    if (Responses.empty())
      return;
    if (Responses.front().kind() == Value::Null) {
      Configuration Base;
      {
        std::lock_guard G(ConfigLock);
        Base = BaseConfig;
      }
      updateConfig(std::move(Base));
      return;
    }
    const Value &FirstConfig = Responses.front();

    // Apply a completed editor update before handling the next client request.
    // updateConfig only dispatches evaluator work; queueing this composition
    // itself made later requests observe a stale configuration.
    auto ConfigAction = [this, FirstConfig]() mutable {
      // Parse the config
      ConfigurationPatch Patch;
      llvm::json::Path::Root P;
      if (!fromJSON(FirstConfig, Patch, P)) {
        elog("workspace/configuration: parse error {0}", P.getError());
        return;
      }

      // OK, update the config
      Configuration Base;
      {
        std::lock_guard G(ConfigLock);
        Base = BaseConfig;
      }
      updateConfig(overlay(std::move(Base), Patch));
    };

    ConfigAction();
  };
  workspaceConfiguration({.items = {ConfigurationItem{.section = "nixd"}}},
                         std::move(Action));
}

void Controller::workspaceConfiguration(
    const lspserver::ConfigurationParams &Params,
    lspserver::Callback<llvm::json::Value> Reply) {
  if (ClientCaps.WorkspaceConfiguration) {
    WorkspaceConfiguration(Params, std::move(Reply));
  } else {
    Reply(lspserver::error("client does not support workspace configuration"));
  }
}
