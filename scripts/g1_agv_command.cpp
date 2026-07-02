#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/agv/g1_agv_client.hpp>

namespace {

float parse_float(const char* value, float fallback) {
  if (value == nullptr) {
    return fallback;
  }
  try {
    return std::stof(value);
  } catch (...) {
    return fallback;
  }
}

std::string parse_string_arg(int argc, char** argv, const std::string& key, const std::string& fallback) {
  const std::string prefix = "--" + key + "=";
  for (int i = 1; i < argc; ++i) {
    std::string arg(argv[i]);
    if (arg.rfind(prefix, 0) == 0) {
      return arg.substr(prefix.size());
    }
  }
  return fallback;
}

float parse_float_arg(int argc, char** argv, const std::string& key, float fallback) {
  std::string value = parse_string_arg(argc, argv, key, "");
  if (value.empty()) {
    return fallback;
  }
  return parse_float(value.c_str(), fallback);
}

}  // namespace

int main(int argc, char** argv) {
  const std::string network_interface = parse_string_arg(argc, argv, "network_interface", "enp8s0");
  const float vx = parse_float_arg(argc, argv, "vx", 0.0f);
  const float vyaw = parse_float_arg(argc, argv, "vyaw", 0.0f);
  const float duration = parse_float_arg(argc, argv, "duration", 0.3f);

  unitree::robot::ChannelFactory::Instance()->Init(0, network_interface);

  unitree::robot::g1::AgvClient client;
  client.SetTimeout(3.0f);
  client.Init();

  std::cout << "agv move vx=" << vx << " vyaw=" << vyaw << " duration=" << duration << std::endl;
  int32_t ret = client.Move(vx, 0.0f, vyaw);
  std::cout << "agv move ret=" << ret << std::endl;

  if (duration > 0.0f) {
    std::this_thread::sleep_for(std::chrono::duration<float>(duration));
  }

  int32_t stop_ret = client.Move(0.0f, 0.0f, 0.0f);
  std::cout << "agv stop ret=" << stop_ret << std::endl;
  return ret == 0 && stop_ret == 0 ? 0 : 1;
}
