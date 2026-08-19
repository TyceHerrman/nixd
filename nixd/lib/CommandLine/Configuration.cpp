/// \file
/// \brief This file implements CLI initialized configuration.

#include "nixd/CommandLine/Configuration.h"
#include "nixd/CommandLine/Options.h"
#include "nixd/Controller/Configuration.h"
#include "nixd/Support/JSON.h"

#include <llvm/Support/CommandLine.h>
#include <llvm/Support/JSON.h>

#include <string>

using namespace nixd;
using namespace llvm::cl;

namespace {

opt<std::string> DefaultConfigJSON{"config",
                                   desc("JSON-encoded initial configuration"),
                                   init(""), cat(NixdCategory)};

opt<bool> EnableProjectConfig{
    "enable-project-config",
    desc("Load .nixd.json from the initialized workspace root"),
    init(false), cat(NixdCategory)};

} // namespace

CommandLineConfiguration nixd::parseCLIConfig() {
  CommandLineConfiguration Result{
      .enableProjectConfig = EnableProjectConfig,
  };
  if (DefaultConfigJSON.empty())
    return Result;

  Result.config = nixd::fromJSON<Configuration>(nixd::parse(DefaultConfigJSON));
  return Result;
}
