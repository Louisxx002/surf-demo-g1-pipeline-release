#!/usr/bin/env bash
set -euo pipefail

set +u
source /opt/ros/jazzy/setup.bash
set -u

echo "Monitoring /audio_msg. Press Ctrl+C to stop."
ros2 topic echo /audio_msg
