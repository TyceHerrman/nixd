#include "nixd/Controller/Controller.h"
#include "nixd/Eval/Launch.h"
#include "nixd/Support/JSON.h"

#include <llvm/Support/MemoryBuffer.h>

#include <filesystem>
#include <initializer_list>

using namespace nixd;
using namespace lspserver;
using llvm::json::Value;

namespace {

bool fromJSON(const Value &Params, ConfigurationPatch::Formatting &R,
              llvm::json::Path P);
bool fromJSON(const Value &Params, ConfigurationPatch::NixpkgsProvider &R,
              llvm::json::Path P);
bool fromJSON(const Value &Params, ConfigurationPatch::Diagnostic &R,
              llvm::json::Path P);

bool rejectUnknownKeys(const llvm::json::Object &Object,
                       std::initializer_list<llvm::StringRef> Allowed,
                       llvm::json::Path P) {
  for (const auto &[Key, Ignored] : Object) {
    bool IsAllowed = false;
    for (llvm::StringRef Candidate : Allowed)
      IsAllowed |= static_cast<llvm::StringRef>(Key) == Candidate;
    if (!IsAllowed) {
      P.field(Key).report("unknown key");
      return false;
    }
  }
  return true;
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

bool validateSchema(const llvm::json::Object &Object, llvm::json::Path P) {
  const Value *Schema = Object.get("$schema");
  if (!Schema)
    return true;
  std::string Ignored;
  return llvm::json::fromJSON(*Schema, Ignored, P.field("$schema"));
}

bool sameOptions(
    const std::map<std::string, Configuration::OptionProvider> &Left,
    const std::map<std::string, Configuration::OptionProvider> &Right) {
  if (Left.size() != Right.size())
    return false;
  auto L = Left.begin();
  auto R = Right.begin();
  for (; L != Left.end(); ++L, ++R)
    if (L->first != R->first || L->second.expr != R->second.expr)
      return false;
  return true;
}

bool fromJSON(const Value &Params, ConfigurationPatch::Formatting &R,
              llvm::json::Path P) {
  if (auto String = Params.getAsString()) {
    if (String->empty()) {
      P.report("expected nonempty string");
      return false;
    }
    R.command = {String->str()};
    return true;
  }
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object or string");
    return false;
  }
  return rejectUnknownKeys(*Object, {"command"}, P) &&
         mapPatchField(*Object, "command", R.command, std::move(P));
}

bool fromJSON(const Value &Params, ConfigurationPatch::NixpkgsProvider &R,
              llvm::json::Path P) {
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object");
    return false;
  }
  return rejectUnknownKeys(*Object, {"expr"}, P) &&
         mapPatchField(*Object, "expr", R.expr, std::move(P));
}

bool fromJSON(const Value &Params, ConfigurationPatch::Diagnostic &R,
              llvm::json::Path P) {
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object");
    return false;
  }
  return rejectUnknownKeys(*Object, {"suppress"}, P) &&
         mapPatchField(*Object, "suppress", R.suppress, std::move(P));
}

} // namespace

bool nixd::fromJSON(const Value &Params, Configuration::Diagnostic &R,
                    llvm::json::Path P) {
  ConfigurationPatch::Diagnostic Patch;
  if (!::fromJSON(Params, Patch, P))
    return false;
  if (Patch.suppress)
    R.suppress = std::move(*Patch.suppress);
  return true;
}

bool nixd::fromJSON(const Value &Params, Configuration::Formatting &R,
                    llvm::json::Path P) {
  ConfigurationPatch::Formatting Patch;
  if (!::fromJSON(Params, Patch, P))
    return false;
  if (Patch.command)
    R.command = std::move(*Patch.command);
  return true;
}

bool nixd::fromJSON(const Value &Params, Configuration::OptionProvider &R,
                    llvm::json::Path P) {
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object");
    return false;
  }
  if (!rejectUnknownKeys(*Object, {"expr"}, P))
    return false;
  const Value *Expr = Object->get("expr");
  if (!Expr) {
    P.field("expr").report("missing required field");
    return false;
  }
  auto String = Expr->getAsString();
  if (!String) {
    P.field("expr").report("expected string");
    return false;
  }
  if (String->empty()) {
    P.field("expr").report("expected nonempty string");
    return false;
  }
  R.expr = String->str();
  return true;
}

bool nixd::fromJSON(const Value &Params, Configuration::NixpkgsProvider &R,
                    llvm::json::Path P) {
  ConfigurationPatch::NixpkgsProvider Patch;
  if (!::fromJSON(Params, Patch, P))
    return false;
  if (Patch.expr)
    R.expr = std::move(*Patch.expr);
  return true;
}

bool nixd::fromJSON(const Value &Params, Configuration &R, llvm::json::Path P) {
  ConfigurationPatch Patch;
  if (!fromJSON(Params, Patch, P))
    return false;
  R = overlay(std::move(R), Patch);
  return true;
}

bool nixd::fromJSON(const Value &Params, ConfigurationPatch &R,
                    llvm::json::Path P) {
  const auto *Object = Params.getAsObject();
  if (!Object) {
    P.report("expected object");
    return false;
  }
  return rejectUnknownKeys(
             *Object,
             {"$schema", "formatting", "options", "nixpkgs", "diagnostic"},
             P) &&
         validateSchema(*Object, P) &&
         mapPatchField(*Object, "formatting", R.formatting, P) &&
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
    return {.config = nixd::fromJSON<ConfigurationPatch>(
                nixd::parse((*Input)->getBuffer()))};
  } catch (JSONParseException &Err) {
    return {.error = ProjectConfigError{
                .kind = ProjectConfigErrorKind::JSONError,
                .path = Path,
                .message = std::string(Err.what()) + ": " +
                           llvm::toString(Err.takeError()),
            }};
  } catch (JSONSchemaException &Err) {
    return {.error = ProjectConfigError{
                .kind = ProjectConfigErrorKind::SchemaError,
                .path = Path,
                .message = std::string(Err.what()) + ": " +
                           llvm::toString(Err.takeError()),
            }};
  }
}

void Controller::onDidChangeConfiguration(
    const DidChangeConfigurationParams &) {
  if (ClientCaps.WorkspaceConfiguration)
    fetchConfig();
}

void Controller::updateConfig(Configuration NewConfig) {
  Configuration PreviousConfig;
  {
    std::lock_guard Guard(ConfigLock);
    PreviousConfig = Config;
    Config = NewConfig;
  }

  if (PreviousConfig.nixpkgs.expr != NewConfig.nixpkgs.expr) {
    NixpkgsClientToken Nixpkgs;
    {
      std::lock_guard Guard(NixpkgsStateLock);
      ActiveNixpkgs = false;
      EvaluatingNixpkgs = !NewConfig.nixpkgs.expr.empty();
      ++NixpkgsGeneration;
      Nixpkgs = {NewConfig.nixpkgs.expr.empty() ? nullptr : NixpkgsEval,
                 NixpkgsGeneration};
    }
    WorkerPtr Worker = Nixpkgs.Worker;
    AttrSetClient *Client = Worker ? Worker->client() : nullptr;
    if (Client) {
      const std::uint64_t Generation = Nixpkgs.Generation;
      AttrSetClientProc *WorkerIdentity = Worker.get();
      auto OnComplete = [this, WorkerIdentity, Generation](bool Success) {
        std::lock_guard Guard(NixpkgsStateLock);
        if (Generation == NixpkgsGeneration &&
            WorkerIdentity == NixpkgsEval.get()) {
          EvaluatingNixpkgs = false;
          ActiveNixpkgs = Success;
        }
      };
      evalExprWithProgress(*Client, NewConfig.nixpkgs.expr, "nixpkgs entries",
                           std::move(OnComplete));
    } else {
      std::lock_guard Guard(NixpkgsStateLock);
      if (Nixpkgs.Generation == NixpkgsGeneration) {
        EvaluatingNixpkgs = false;
        ActiveNixpkgs = false;
      }
    }
  }

  struct PendingOptionEval {
    std::string Name;
    std::string Expr;
    WorkerPtr Worker;
    std::uint64_t Generation;
  };
  std::vector<PendingOptionEval> PendingOptions;
  std::vector<WorkerPtr> RetiredOptions;
  if (!sameOptions(PreviousConfig.options, NewConfig.options)) {
    PendingOptions.reserve(NewConfig.options.size());
    {
      std::lock_guard Guard(OptionsLock);
      RetiredOptions.reserve(Options.size());
      ++OptionsGeneration;
      for (auto It = Options.begin(); It != Options.end();) {
        const std::string &Name = It->first;
        OptionProviderSlot &Slot = It->second;
        auto New = NewConfig.options.find(Name);
        if (New == NewConfig.options.end()) {
          Slot.Active = false;
          Slot.Evaluating = false;
          ++Slot.Generation;
          if (Slot.Worker)
            RetiredOptions.push_back(std::move(Slot.Worker));
          It = Options.erase(It);
          continue;
        }
        const std::string &Expr = New->second.expr;
        if (Slot.Expr == Expr)
          ++It;
        else {
          Slot.Expr = Expr;
          Slot.Active = false;
          Slot.Evaluating = true;
          ++Slot.Generation;
          PendingOptions.push_back({Name, Expr, Slot.Worker, Slot.Generation});
          ++It;
        }
      }
      for (const auto &[Name, Provider] : NewConfig.options) {
        if (Options.contains(Name))
          continue;
        OptionProviderSlot Slot;
        Slot.Expr = Provider.expr;
        Slot.Generation = 1;
        Slot.Evaluating = true;
        auto [It, Inserted] = Options.emplace(Name, std::move(Slot));
        assert(Inserted);
        PendingOptions.push_back(
            {Name, Provider.expr, nullptr, It->second.Generation});
      }
    }

    for (WorkerPtr &Worker : RetiredOptions) {
      if (AttrSetClient *Client = Worker->client())
        Client->closeInboundAndRequests("option provider removed");
    }
    RetiredOptions.clear();

    for (auto &Pending : PendingOptions) {
      if (!Pending.Worker) {
        std::lock_guard Guard(ChildForkLock);
        startOption(Pending.Name, Pending.Worker, Root.path);
      }

      {
        std::lock_guard Guard(OptionsLock);
        auto It = Options.find(Pending.Name);
        if (It == Options.end() ||
            It->second.Generation != Pending.Generation ||
            It->second.Expr != Pending.Expr) {
          Pending.Worker.reset();
          continue;
        }
        if (!It->second.Worker)
          It->second.Worker = Pending.Worker;
        Pending.Worker = It->second.Worker;
      }

      WorkerPtr Worker = Pending.Worker;
      AttrSetClient *Client = Worker ? Worker->client() : nullptr;
      if (!Client) {
        std::lock_guard Guard(OptionsLock);
        auto It = Options.find(Pending.Name);
        if (It != Options.end() &&
            It->second.Generation == Pending.Generation &&
            It->second.Worker == Worker) {
          It->second.Evaluating = false;
          It->second.Active = false;
        }
        continue;
      }
      const std::string Name = Pending.Name;
      const std::string Expr = Pending.Expr;
      const std::uint64_t Generation = Pending.Generation;
      AttrSetClientProc *WorkerIdentity = Worker.get();
      auto OnComplete = [this, Name, Expr, WorkerIdentity,
                         Generation](bool Success) {
        std::lock_guard Guard(OptionsLock);
        auto It = Options.find(Name);
        if (It != Options.end() && It->second.Generation == Generation &&
            It->second.Expr == Expr &&
            It->second.Worker.get() == WorkerIdentity) {
          It->second.Evaluating = false;
          It->second.Active = Success;
        }
      };
      evalExprWithProgress(*Client, Expr, Name, std::move(OnComplete));
    }
  }

  // Update the diagnostic part.
  updateSuppressed(NewConfig.diagnostic.suppress);

  // After all, notify all AST modules the diagnostic set has been updated.
  std::vector<std::pair<std::string, std::shared_ptr<NixTU>>> Units;
  {
    std::lock_guard Guard(TUsLock);
    for (const auto &[File, TU] : TUs)
      Units.emplace_back(File.str(), TU);
  }
  for (const auto &[File, TU] : Units)
    publishDiagnostics(File, std::nullopt, TU->src(), TU->diagnostics());
}

void Controller::fetchConfig() {
  std::uint64_t Generation;
  {
    std::lock_guard Guard(WorkspaceConfigLock);
    Generation = ++WorkspaceConfigGeneration;
  }

  auto Action = [this,
                 Generation](llvm::Expected<llvm::json::Value> Resp) mutable {
    {
      std::lock_guard Guard(WorkspaceConfigLock);
      if (Generation != WorkspaceConfigGeneration) {
        if (!Resp)
          llvm::consumeError(Resp.takeError());
        return;
      }
    }

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
    if (Responses.size() != 1) {
      lspserver::elog(
          "workspace/configuration: expected exactly one array item");
      return;
    }

    Configuration NewConfig;
    {
      std::lock_guard Guard(ConfigLock);
      NewConfig = BaseConfig;
    }
    const Value &PatchValue = Responses.front();
    if (PatchValue.kind() != Value::Null) {
      ConfigurationPatch Patch;
      llvm::json::Path::Root P;
      if (!fromJSON(PatchValue, Patch, P)) {
        elog("workspace/configuration: parse error {0}", P.getError());
        return;
      }
      NewConfig = overlay(std::move(NewConfig), Patch);
    }

    {
      std::lock_guard Guard(WorkspaceConfigLock);
      if (Generation != WorkspaceConfigGeneration)
        return;
    }
    updateConfig(std::move(NewConfig));
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
