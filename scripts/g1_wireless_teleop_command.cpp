#include <algorithm>
#include <chrono>
#include <iostream>
#include <string>
#include <thread>

#include <unitree/idl/go2/WirelessController_.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/channel/channel_publisher.hpp>

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

}  // namespace

int main(int argc, char const *argv[]) {
  std::string iface = arg_string(argc, argv, "network_interface", "enp8s0");
  float lx = std::clamp(arg_float(argc, argv, "lx", 0.0f), -0.4f, 0.4f);
  float ly = std::clamp(arg_float(argc, argv, "ly", 0.0f), -0.4f, 0.4f);
  float rx = std::clamp(arg_float(argc, argv, "rx", 0.0f), -0.4f, 0.4f);
  float ry = std::clamp(arg_float(argc, argv, "ry", 0.0f), -0.4f, 0.4f);
  float duration = std::clamp(arg_float(argc, argv, "duration", 0.3f), 0.0f, 0.8f);
  float hz = std::clamp(arg_float(argc, argv, "hz", 50.0f), 10.0f, 100.0f);

  std::cout << "init channel iface=" << iface << std::endl;
  unitree::robot::ChannelFactory::Instance()->Init(0, iface);

  unitree::robot::ChannelPublisherPtr<unitree_go::msg::dds_::WirelessController_> publisher;
  publisher.reset(new unitree::robot::ChannelPublisher<unitree_go::msg::dds_::WirelessController_>("rt/wirelesscontroller"));
  publisher->InitChannel();

  unitree_go::msg::dds_::WirelessController_ msg;
  msg.lx(lx);
  msg.ly(ly);
  msg.rx(rx);
  msg.ry(ry);
  msg.keys(0);

  const auto period = std::chrono::milliseconds(static_cast<int>(1000.0f / hz));
  const int ticks = std::max(1, static_cast<int>(duration * hz));

  std::cout << "wireless publish lx=" << lx << " ly=" << ly << " rx=" << rx
            << " ry=" << ry << " duration=" << duration << " ticks=" << ticks << std::endl;
  for (int i = 0; i < ticks; ++i) {
    publisher->Write(msg);
    std::this_thread::sleep_for(period);
  }

  msg.lx(0.0f);
  msg.ly(0.0f);
  msg.rx(0.0f);
  msg.ry(0.0f);
  msg.keys(0);
  for (int i = 0; i < 10; ++i) {
    publisher->Write(msg);
    std::this_thread::sleep_for(period);
  }
  std::cout << "wireless stop published" << std::endl;
  return 0;
}
