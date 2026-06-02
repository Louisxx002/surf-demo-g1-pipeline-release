from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
from wav import read_wav, play_pcm_stream
import time

from project_config import CONFIG

CONFIG.runtime_dir.mkdir(parents=True, exist_ok=True)

ChannelFactoryInitialize(CONFIG.unitree_domain_id, CONFIG.unitree_network_interface)

audio_client = AudioClient()
audio_client.SetTimeout(10.0)
audio_client.Init()
audio_client.SetVolume(CONFIG.unitree_audio_volume)

print("Unitree Audio Player started...")
print(f"Watching wav file: {CONFIG.tts_wav_path}")

last_mtime = CONFIG.tts_wav_path.stat().st_mtime if CONFIG.tts_wav_path.exists() else 0

if last_mtime:
    print("Existing tts.wav detected at startup, skipping old audio until a new file is generated.")

while True:
    if CONFIG.tts_wav_path.exists():
        current_mtime = CONFIG.tts_wav_path.stat().st_mtime

        # ⭐ 只有文件更新才播放
        if current_mtime != last_mtime:
            last_mtime = current_mtime

            pcm_list, sample_rate, num_channels, is_ok = read_wav(str(CONFIG.tts_wav_path))

            if is_ok:
                play_pcm_stream(audio_client, pcm_list, "tts")
                print("played audio")

    time.sleep(0.2)  # ⭐ 降低CPU占用
