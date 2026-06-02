# XJTLU RAG ROS2 voice bridge launcher
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  XJTLU ROS2 Voice Bridge" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$env:ROS_DOMAIN_ID = "42"
$env:CYCLONEDDS_URI = '<CycloneDDS><Domain><General><AllowMulticast>false</AllowMulticast></General><Discovery><Peers><Peer address="192.168.123.225"/></Peers></Discovery></Domain></CycloneDDS>'

if (-not $env:ROS_REPLY_TOPIC) {
    $env:ROS_REPLY_TOPIC = "/xjtlu_reply"
}
if (-not $env:ROS_REPLY_FORMAT) {
    $env:ROS_REPLY_FORMAT = "text"
}

Write-Host "ROS_DOMAIN_ID:    $env:ROS_DOMAIN_ID" -ForegroundColor Green
Write-Host "ROS_REPLY_TOPIC:  $env:ROS_REPLY_TOPIC" -ForegroundColor Green
Write-Host "ROS_REPLY_FORMAT: $env:ROS_REPLY_FORMAT" -ForegroundColor Green
Write-Host ""
Write-Host "Subscribing:" -ForegroundColor Yellow
Write-Host "  /wake_word_event"
Write-Host "  /audio_msg"
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

python .\ros_bridge.py
