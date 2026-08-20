/// \file
/// \brief Allow default configuration being passed via CLI
#pragma once

#include "nixd/Controller/Configuration.h"

#include <exception>
#include <optional>

namespace nixd {

struct CommandLineConfiguration {
  std::optional<nixd::ConfigurationPatch> config;
  bool enableProjectConfig = false;
};

/// \brief Parse the explicit CLI configuration and project-config opt-in.
CommandLineConfiguration parseCLIConfig();

} // namespace nixd
