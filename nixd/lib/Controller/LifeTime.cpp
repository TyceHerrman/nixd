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

#include <cerrno>
#include <chrono>
#include <filesystem>
#include <system_error>
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

Controller::ProviderWorkLease::~ProviderWorkLease() {
  if (Owner)
    Owner->releaseProviderWork();
}

Controller::ProviderWorkLease Controller::acquireProviderWork() {
  std::lock_guard Guard(ProviderWorkLock);
  if (ProviderWorkShutdown)
    return {};
  ++ProviderWorkCount;
  return ProviderWorkLease(this);
}

void Controller::releaseProviderWork() {
  bool Notify = false;
  {
    std::lock_guard Guard(ProviderWorkLock);
    assert(ProviderWorkCount > 0);
    Notify = --ProviderWorkCount == 0;
  }
  if (Notify)
    ProviderWorkCV.notify_all();
}

Controller::ProviderShutdownState Controller::beginProviderShutdown() {
  {
    std::unique_lock Guard(ProviderWorkLock);
    ProviderWorkShutdown = true;
    // Preserve quick replies already admitted before exit, but never let a
    // silent evaluator prevent the later gate closure and Pool.join().
    ProviderWorkCV.wait_for(Guard, std::chrono::seconds(2),
                            [this] { return ProviderWorkCount == 0; });
  }

  ProviderShutdownState Providers;
  {
    std::lock_guard Guard(NixpkgsStateLock);
    ActiveNixpkgs = false;
    EvaluatingNixpkgs = false;
    ++NixpkgsGeneration;
    Providers.Nixpkgs = std::move(NixpkgsEval);
  }
  {
    std::lock_guard Guard(OptionsLock);
    ++OptionsGeneration;
    for (auto &[Name, Slot] : Options) {
      (void)Name;
      if (Slot.Worker)
        Providers.Options.push_back(std::move(Slot.Worker));
    }
    Options.clear();
  }

  auto Close = [](const WorkerPtr &Worker) {
    if (Worker)
      if (AttrSetClient *Client = Worker->client())
        Client->closeInboundAndRequests("controller shutdown");
  };
  Close(Providers.Nixpkgs);
  for (const WorkerPtr &Worker : Providers.Options)
    Close(Worker);
  return Providers;
}

void Controller::evalExprWithProgress(
    AttrSetClient &Client, const EvalExprParams &Params,
    std::string_view Description,
    llvm::unique_function<void(bool)> OnComplete) {
  auto Token = rand();
  auto Action = [Token, Description = std::string(Description),
                 OnComplete = std::move(OnComplete),
                 this](llvm::Expected<EvalExprResponse> Resp) mutable {
    endWorkDoneProgress({
        .token = Token,
        .value = WorkDoneProgressEnd{.message = "evaluated " +
                                                std::string(Description)},
    });
    if (!Resp) {
      lspserver::elog("{0} eval expr: {1}", Description, Resp.takeError());
      OnComplete(false);
      return;
    }
    OnComplete(true);
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
  const std::string NixOSOptions = getDefaultNixOSOptionsExpr();
  if (!NixOSOptions.empty())
    Result.options.emplace("nixos", Configuration::OptionProvider{
                                        .expr = NixOSOptions,
                                    });
  return Result;
}

void Controller::setStartupWarning(std::string Message) {
  lspserver::elog("{0}", Message);
  if (!PendingStartupWarning)
    PendingStartupWarning = ShowMessageParams{
        .type = MessageType::Warning,
        .message = std::move(Message),
    };
}

void Controller::selectWorkspaceRoot(const InitializeParams &Params) {
  ProjectRoot = LaunchDirectory;
  Root.path = LaunchDirectory;

  if (Params.workspaceFoldersProvided && Params.workspaceFoldersCount > 1) {
    setStartupWarning(llvm::formatv(
        "cannot load project configuration with multiple workspace folders "
        "({0} supplied)",
        Params.workspaceFoldersCount));
    SkipProjectConfig = true;
    return;
  }

  std::optional<std::filesystem::path> Candidate;
  std::string CandidateName;
  std::optional<std::string> ParseError;
  if (Params.rootUriProvided) {
    CandidateName = "rootUri";
    ParseError = Params.rootUriError;
    if (Params.rootUri)
      Candidate = Params.rootUri->file().str();
  } else if (Params.rootPathProvided &&
             (Params.rootPathError ||
              (Params.rootPath && !Params.rootPath->empty()))) {
    CandidateName = "rootPath";
    ParseError = Params.rootPathError;
    if (Params.rootPath)
      Candidate = *Params.rootPath;
  } else if (Params.workspaceFoldersProvided) {
    CandidateName = "workspaceFolders[0]";
    ParseError = Params.workspaceFoldersError;
    if (Params.workspaceFolders && !Params.workspaceFolders->empty())
      Candidate = Params.workspaceFolders->front().uri.file().str();
  }

  if (ParseError) {
    setStartupWarning(
        llvm::formatv("cannot use {0} as project configuration root: {1}",
                      CandidateName, *ParseError));
    SkipProjectConfig = true;
    return;
  }
  if (!Candidate)
    return;

  std::error_code EC;
  const std::filesystem::file_status Status =
      std::filesystem::status(*Candidate, EC);
  std::string Reason;
  if (EC)
    Reason = EC.message();
  else if (!std::filesystem::exists(Status))
    Reason =
        std::make_error_code(std::errc::no_such_file_or_directory).message();
  else if (!std::filesystem::is_directory(Status))
    Reason = std::make_error_code(std::errc::not_a_directory).message();
  else if (access(Candidate->c_str(), X_OK) != 0)
    Reason = std::error_code(errno, std::generic_category()).message();

  if (!Reason.empty()) {
    setStartupWarning(
        llvm::formatv("cannot use {0} as project configuration root {1}: {2}",
                      CandidateName, Candidate->string(), Reason));
    SkipProjectConfig = true;
    return;
  }

  ProjectRoot = std::move(*Candidate);
}

void Controller::selectBaseConfig(CommandLineConfiguration CLI) {
  Configuration Selected = builtinConfig();
  Root.path = LaunchDirectory;

  if (CLI.config) {
    Selected = overlay(std::move(Selected), *CLI.config);
  } else if (CLI.enableProjectConfig && !SkipProjectConfig) {
    ProjectConfigLoadResult Loaded = loadProjectConfig(ProjectRoot.string());
    if (Loaded.error) {
      setStartupWarning(
          llvm::formatv("failed to load project configuration at {0}: {1}",
                        Loaded.error->path, Loaded.error->message));
    } else if (Loaded.config) {
      Selected = overlay(std::move(Selected), *Loaded.config);
      Root.path = ProjectRoot;
    }
  }

  {
    std::lock_guard Guard(ConfigLock);
    BaseConfig = Selected;
  }
  {
    std::lock_guard Guard(ChildForkLock);
    startNixpkgs(NixpkgsEval, Root.path);
  }
  updateConfig(std::move(Selected));
}

void Controller::
    onInitialize( // NOLINT(readability-convert-member-functions-to-static)
        const InitializeParams &Params, Callback<Value> Reply) {

  LaunchDirectory = std::filesystem::current_path();
  ProjectRoot = LaunchDirectory;
  Root.path = LaunchDirectory;
  SkipProjectConfig = false;
  PendingStartupWarning.reset();

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

  ClientCaps = Params.capabilities;
  try {
    CommandLineConfiguration CLI = parseCLIConfig();
    if (CLI.enableProjectConfig && !CLI.config)
      selectWorkspaceRoot(Params);
    selectBaseConfig(std::move(CLI));
  } catch (LLVMErrorException &Err) {
    lspserver::elog("parse CLI config error: {0}, {1}", Err.what(),
                    Err.takeError());
    std::exit(-1);
  }

  Reply(std::move(Result));
}

void Controller::onInitialized(const lspserver::InitializedParams &) {
  if (PendingStartupWarning) {
    auto ShowMessage =
        mkOutNotifiction<ShowMessageParams>("window/showMessage");
    ShowMessage(*PendingStartupWarning);
    PendingStartupWarning.reset();
  }
  if (ClientCaps.WorkspaceConfiguration)
    fetchConfig();
}

void Controller::onShutdown(const lspserver::NoParams &,
                            lspserver::Callback<std::nullptr_t> Reply) {
  ReceivedShutdown = true;
  {
    std::lock_guard Guard(WorkspaceConfigLock);
    ++WorkspaceConfigGeneration;
  }
  closeRequestGate("server shutdown");
  shutdownFormatters();
  Reply(nullptr);
}
