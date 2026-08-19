#include "nixd/Eval/Launch.h"
#include "nixd/CommandLine/Options.h"

#include <llvm/Support/CommandLine.h>

#include <cstdio>
#include <unistd.h>

using namespace llvm::cl;
using namespace nixd;

namespace {

#define NULL_DEVICE "/dev/null"

opt<std::string> OptionWorkerStderr{
    "option-worker-stderr", desc("Directory to write options worker stderr"),
    cat(NixdCategory), init(NULL_DEVICE)};

opt<std::string> NixpkgsWorkerStderr{
    "nixpkgs-worker-stderr",
    desc("Writable file path for nixpkgs worker stderr (debugging)"),
    cat(NixdCategory), init(NULL_DEVICE)};

} // namespace

void nixd::startAttrSetEval(const std::string &Name,
                            std::unique_ptr<AttrSetClientProc> &Worker,
                            const std::filesystem::path &Root) {
  Worker = std::make_unique<AttrSetClientProc>([Name, Root]() {
    freopen(Name.c_str(), "w", stderr);
    if (chdir(Root.c_str()) != 0) {
      perror("failed to change evaluator working directory");
      return -1;
    }
    return execl(AttrSetClient::getExe(), "nixd-attrset-eval", nullptr);
  });
}

void nixd::startNixpkgs(std::unique_ptr<AttrSetClientProc> &NixpkgsEval,
                        const std::filesystem::path &Root) {
  startAttrSetEval(NixpkgsWorkerStderr, NixpkgsEval, Root);
}

void nixd::startOption(const std::string &Name,
                       std::unique_ptr<AttrSetClientProc> &Worker,
                       const std::filesystem::path &Root) {
  std::string NewName = NULL_DEVICE;
  if (OptionWorkerStderr.getNumOccurrences())
    NewName = OptionWorkerStderr.getValue() + "/" + Name;
  startAttrSetEval(NewName, Worker, Root);
}
