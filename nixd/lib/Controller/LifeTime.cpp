/// \file
/// \brief Implementation of [Server Lifecycle].
/// [Server Lifecycle]:
/// https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#lifeCycleMessages

#include "nixd-config.h"

#include "nixd/CommandLine/Configuration.h"
#include "nixd/CommandLine/Options.h"
#include "nixd/Controller/Controller.h"
#include "nixd/Eval/Launch.h"
#include "nixd/Support/Exception.h"

#include "lspserver/Protocol.h"

#include <llvm/Support/CommandLine.h>

#include <unistd.h>

using namespace nixd;
using namespace util;
using namespace llvm::json;
using namespace llvm::cl;
using namespace lspserver;

namespace {

opt<std::string> DefaultNixpkgsExpr{
    "nixpkgs-expr",
    desc("Default expression intrepreted as `import <nixpkgs> { }`"),
    cat(NixdCategory), init("import <nixpkgs> { }")};

opt<std::string> DefaultNixOSOptionsExpr{
    "nixos-options-expr",
    desc("Default expression interpreted as option declarations"),
    cat(NixdCategory),
    init("(let pkgs = import <nixpkgs> { }; in (pkgs.lib.evalModules { modules "
         "=  (import <nixpkgs/nixos/modules/module-list.nix>) ++ [ ({...}: { "
         "nixpkgs.hostPlatform = builtins.currentSystem;} ) ] ; })).options")};

opt<bool> EnableSemanticTokens{"semantic-tokens",
                               desc("Enable/Disable semantic tokens"),
                               init(false), cat(NixdCategory)};

// Here we try to wrap nixpkgs, nixos options in a single emtpy attrset in test.
std::string getDefaultNixpkgsExpr() {
  if (LitTest && !DefaultNixpkgsExpr.getNumOccurrences()) {
    return "{ }";
  }
  return DefaultNixpkgsExpr;
}

std::string getDefaultNixOSOptionsExpr() {
  if (LitTest && !DefaultNixOSOptionsExpr.getNumOccurrences()) {
    return "{ }";
  }
  return DefaultNixOSOptionsExpr;
}

} // namespace

void Controller::evalExprWithProgress(AttrSetClient &Client,
                                      const EvalExprParams &Params,
                                      std::string_view Description) {
  auto Token = rand();
  auto Action = [Token, Description = std::string(Description),
                 this](llvm::Expected<EvalExprResponse> Resp) {
    endWorkDoneProgress({
        .token = Token,
        .value = WorkDoneProgressEnd{.message = "evaluated " +
                                                std::string(Description)},
    });
    if (!Resp) {
      lspserver::elog("{0} eval expr: {1}", Description, Resp.takeError());
      return;
    }
  };
  createWorkDoneProgress({Token});
  beginWorkDoneProgress({.token = Token,
                         .value = WorkDoneProgressBegin{
                             .title = "evaluating " + std::string(Description),
                             .cancellable = false,
                             .percentage = false,
                         }});
  Client.evalExpr(Params, std::move(Action));
}

Configuration Controller::builtinConfig() const {
  Configuration Result;
  Result.nixpkgs.expr = getDefaultNixpkgsExpr();
  Result.options.emplace("nixos", Configuration::OptionProvider{
                                      .expr = getDefaultNixOSOptionsExpr(),
                                  });
  return Result;
}

void Controller::selectWorkspaceRoot(const InitializeParams &Params) {
  std::optional<std::filesystem::path> SuppliedRoot;
  if (Params.rootUri && *Params.rootUri)
    SuppliedRoot = Params.rootUri->file().str();
  else if (Params.rootPath && !Params.rootPath->empty())
    SuppliedRoot = *Params.rootPath;

  if (!SuppliedRoot)
    return;

  std::error_code EC;
  const std::filesystem::file_status Status =
      std::filesystem::status(*SuppliedRoot, EC);
  std::string Reason;
  if (EC)
    Reason = EC.message();
  else if (!std::filesystem::exists(Status))
    Reason = "path does not exist";
  else if (!std::filesystem::is_directory(Status))
    Reason = "path is not a directory";
  else if (access(SuppliedRoot->c_str(), X_OK) != 0)
    Reason = std::error_code(errno, std::generic_category()).message();

  if (Reason.empty()) {
    Root.path = std::move(*SuppliedRoot);
    return;
  }

  std::string Message = llvm::formatv(
      "unusable workspace root {0}: {1}; using launch directory {2}",
      SuppliedRoot->string(), Reason, LaunchDirectory.string());
  lspserver::elog("{0}", Message);
  PendingStartupWarning = ShowMessageParams{
      .type = MessageType::Warning,
      .message = std::move(Message),
  };
  Root.path = LaunchDirectory;
  SkipProjectConfig = true;
}

void Controller::selectBaseConfig() {
  CommandLineConfiguration CLI = parseCLIConfig();
  ProjectConfigError.reset();
  if (CLI.config) {
    BaseConfig = *CLI.config;
  } else if (CLI.enableProjectConfig && !SkipProjectConfig) {
    ProjectConfigLoadResult Loaded = loadProjectConfig(Root.path.string());
    ProjectConfigError = std::move(Loaded.error);
    if (ProjectConfigError) {
      std::string Message = llvm::formatv(
          "failed to load project configuration at {0}: {1}",
          ProjectConfigError->path, ProjectConfigError->message);
      lspserver::elog("{0}", Message);
      PendingStartupWarning = ShowMessageParams{
          .type = MessageType::Warning,
          .message = std::move(Message),
      };
    }
    BaseConfig = Loaded.config.value_or(builtinConfig());
  } else {
    BaseConfig = builtinConfig();
  }
  updateConfig(BaseConfig);
}

void Controller::
    onInitialize( // NOLINT(readability-convert-member-functions-to-static)
        const InitializeParams &Params,
        Callback<Value> Reply) {

  Object ServerCaps{
      {{"textDocumentSync",
        llvm::json::Object{
            {"openClose", true},
            {"change", (int)TextDocumentSyncKind::Incremental},
            {"save", true},
        }},
       {
           "codeActionProvider",
           Object{
               {"codeActionKinds",
                Array{CodeAction::QUICKFIX_KIND, CodeAction::REFACTOR_KIND,
                      CodeAction::REFACTOR_REWRITE_KIND}},
               {"resolveProvider", true},
           },
       },
       {"definitionProvider", true},
       {"documentLinkProvider", Object{}},
       {"documentSymbolProvider", true},
       {"foldingRangeProvider", true},
       {"inlayHintProvider", true},
       {"completionProvider",
        Object{
            {"resolveProvider", true},
            {"triggerCharacters", {"."}},
        }},
       {"referencesProvider", true},
       {"documentHighlightProvider", true},
       {"hoverProvider", true},
       {"documentFormattingProvider", true},
       {"renameProvider",
        Object{
            {"prepareProvider", true},
        }}},
  };

  if (EnableSemanticTokens) {
    ServerCaps["semanticTokensProvider"] = Object{
        {
            "legend",
            Object{
                {"tokenTypes",
                 Array{
                     "function",  // function
                     "string",    // string
                     "number",    // number
                     "type",      // select
                     "keyword",   // builtin
                     "variable",  // constant
                     "interface", // fromWith
                     "variable",  // variable
                     "regexp",    // null
                     "macro",     // bool
                     "method",    // attrname
                     "regexp",    // lambdaArg
                     "regexp",    // lambdaFormal
                 }},
                {"tokenModifiers",
                 Array{
                     "static",   // builtin
                     "abstract", // deprecated
                     "async",    // dynamic
                 }},
            },
        },
        {"range", false},
        {"full", true},
    };
  }

  Object Result{{
      {"serverInfo",
       Object{
           {"name", "nixd"},
           {"version", NIXD_VERSION},
       }},
      {"capabilities", std::move(ServerCaps)},
  }};

  Reply(std::move(Result));

  ClientCaps = Params.capabilities;

  selectWorkspaceRoot(Params);

  // Start default workers.
  startNixpkgs(NixpkgsEval, Root.path);

  // Create the default worker now; updateConfig() selects and evaluates its
  // active configuration after all source precedence has been resolved.
  {
    std::lock_guard _(OptionsLock);
    startOption("nixos", Options["nixos"], Root.path);
  }
  try {
    selectBaseConfig();
  } catch (LLVMErrorException &Err) {
    lspserver::elog("parse CLI config error: {0}, {1}", Err.what(),
                    Err.takeError());
    std::exit(-1);
  }
  fetchConfig();
}

void Controller::onInitialized(const lspserver::InitializedParams &Params) {
  if (!PendingStartupWarning)
    return;
  ShowMessage(*PendingStartupWarning);
  PendingStartupWarning.reset();
}

void Controller::onShutdown(const lspserver::NoParams &,
                            lspserver::Callback<std::nullptr_t> Reply) {
  ReceivedShutdown = true;
  Reply(nullptr);
}
