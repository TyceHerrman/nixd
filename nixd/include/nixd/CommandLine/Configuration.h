/// \file
/// \brief Allow default configuration being passed via CLI
#pragma once

#include "nixd/Controller/Configuration.h"

#include <exception>
#include <optional>

namespace nixd {

struct CommandLineConfiguration {
  std::optional<nixd::Configuration> config;
  bool enableProjectConfig = false;
};

/// \brief Parse the CLI configuration source and project-config opt-in.
CommandLineConfiguration parseCLIConfig();

} // namespace nixd
