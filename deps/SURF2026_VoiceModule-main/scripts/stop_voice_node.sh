#!/usr/bin/env bash
# Stop voice_pipeline_node service.
# Usage: ./scripts/stop_voice_node.sh

set -euo pipefail

systemctl --user stop voice-pipeline.service >/dev/null 2>&1 && \
  echo "voice-pipeline.service stopped." || \
  echo "voice-pipeline.service was not running."
