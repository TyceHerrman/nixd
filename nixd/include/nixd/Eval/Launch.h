#pragma once

#include "AttrSetClient.h"

#include <filesystem>

namespace nixd {

void startAttrSetEval(const std::string &Name,
                      std::shared_ptr<AttrSetClientProc> &Worker,
                      const std::filesystem::path &Directory);

void startNixpkgs(std::shared_ptr<AttrSetClientProc> &NixpkgsEval,
                  const std::filesystem::path &Directory);

void startOption(const std::string &Name,
                 std::shared_ptr<AttrSetClientProc> &Worker,
                 const std::filesystem::path &Directory);

} // namespace nixd
