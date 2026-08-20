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
                            std::shared_ptr<AttrSetClientProc> &Worker,
                            const std::filesystem::path &Directory) {
  Worker = std::make_shared<AttrSetClientProc>([Name, Directory]() {
    freopen(Name.c_str(), "w", stderr);
    if (chdir(Directory.c_str()) != 0) {
      perror("failed to change evaluator working directory");
      return -1;
    }
    return execl(AttrSetClient::getExe(), "nixd-attrset-eval", nullptr);
  });
}

void nixd::startNixpkgs(std::shared_ptr<AttrSetClientProc> &NixpkgsEval,
                        const std::filesystem::path &Directory) {
  startAttrSetEval(NixpkgsWorkerStderr, NixpkgsEval, Directory);
}

void nixd::startOption(const std::string &Name,
                       std::shared_ptr<AttrSetClientProc> &Worker,
                       const std::filesystem::path &Directory) {
  std::string NewName = NULL_DEVICE;
  if (OptionWorkerStderr.getNumOccurrences())
    NewName = OptionWorkerStderr.getValue() + "/" + Name;
  startAttrSetEval(NewName, Worker, Directory);
}
