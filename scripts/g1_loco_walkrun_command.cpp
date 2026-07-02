#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/loco/g1_loco_api.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>

namespace {

float arg_float(int argc, char const *argv[], const std::string &key, float fallback) {
  const std::string prefix = "--" + key + "=";
  for (int i = 1; i < argc; ++i) {
    std::string arg(argv[i]);
    if (arg.rfind(prefix, 0) == 0) {
      return std::stof(arg.substr(prefix.size()));
    }
  }
  return fallback;
}

std::string arg_string(int argc, char const *argv[], const std::string &key, const std::string &fallback) {
  const std::string prefix = "--" + key + "=";
  for (int i = 1; i < argc; ++i) {
    std::string arg(argv[i]);
    if (arg.rfind(prefix, 0) == 0) {
      return arg.substr(prefix.size());
    }
  }
  return fallback;
}

bool arg_bool(int argc, char const *argv[], const std::string &key, bool fallback) {
  const std::string prefix = "--" + key + "=";
  for (int i = 1; i < argc; ++i) {
    std::string arg(argv[i]);
    if (arg.rfind(prefix, 0) == 0) {
      std::string value = arg.substr(prefix.size());
      std::transform(value.begin(), value.end(), value.begin(), ::tolower);
      return value == "1" || value == "true" || value == "yes" || value == "on";
    }
  }
  return fallback;
}

void print_state(unitree::robot::g1::LocoClient &client, const std::string &label) {
  int fsm_id = -1;
  int fsm_mode = -1;
  int balance_mode = -1;
  int ret_id = client.GetFsmId(fsm_id);
  int ret_mode = client.GetFsmMode(fsm_mode);
  int ret_balance = client.GetBalanceMode(balance_mode);
  std::cout << label << " ret_id=" << ret_id << " fsm_id=" << fsm_id
            << " ret_mode=" << ret_mode << " fsm_mode=" << fsm_mode
            << " ret_balance=" << ret_balance << " balance_mode=" << balance_mode
            << std::endl;
}

}  // namespace

int main(int argc, char const *argv[]) {
  std::string iface = arg_string(argc, argv, "network_interface", "enp8s0");
  float vx = std::clamp(arg_float(argc, argv, "vx", 0.08f), -0.2f, 0.2f);
  float vy = std::clamp(arg_float(argc, argv, "vy", 0.0f), -0.1f, 0.1f);
  float yaw = std::clamp(arg_float(argc, argv, "yaw", 0.0f), -0.4f, 0.4f);
  float duration = std::clamp(arg_float(argc, argv, "duration", 0.3f), 0.0f, 0.8f);
  int fsm_id_arg = static_cast<int>(arg_float(argc, argv, "set_fsm_id", -1.0f));
  bool start = arg_bool(argc, argv, "start", false);
  bool switch_walkrun = arg_bool(argc, argv, "switch_walkrun", true);

  std::cout << "init channel iface=" << iface << std::endl;
  unitree::robot::ChannelFactory::Instance()->Init(0, iface);

  unitree::robot::g1::LocoClient client;
  client.Init();
  client.SetTimeout(5.f);

  print_state(client, "before");

  if (fsm_id_arg >= 0) {
    int ret = client.SetFsmId(fsm_id_arg);
    std::cout << "set_fsm_id value=" << fsm_id_arg << " ret=" << ret << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(1200));
    print_state(client, "after_set_fsm_id");
  }

  if (start) {
    int ret = client.Start();
    std::cout << "start ret=" << ret << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(1200));
    print_state(client, "after_start");
  }

  if (switch_walkrun) {
    int ret = client.SwitchToInternalCtrl(unitree::robot::g1::InternalFsmMode::WALKRUN);
    std::cout << "switch_internal_walkrun ret=" << ret << std::endl;
    std::this_thread::sleep_for(std::chrono::milliseconds(400));
    print_state(client, "after_switch_walkrun");
  }

  std::cout << "set_velocity vx=" << vx << " vy=" << vy << " yaw=" << yaw
            << " duration=" << duration << std::endl;
  int ret_move = client.SetVelocity(vx, vy, yaw, duration);
  std::cout << "set_velocity ret=" << ret_move << std::endl;
  std::this_thread::sleep_for(std::chrono::milliseconds(static_cast<int>((duration + 0.15f) * 1000.0f)));

  int ret_stop = client.StopMove();
  std::cout << "stop_move ret=" << ret_stop << std::endl;
  std::this_thread::sleep_for(std::chrono::milliseconds(200));
  print_state(client, "after_stop");

  return (ret_move == 0 && ret_stop == 0) ? 0 : 2;
}
