from __future__ import annotations

import ast
import tempfile
import unittest
import wave
from pathlib import Path
import subprocess
import sys

import numpy as np

from beamforming.channel_diagnostics import analyze_channels
from beamforming.filter_io import load_filter_npz, save_filter_npz
from beamforming.mic_runtime import (
    build_arecord_stream_command,
    build_mic_packetizer,
    parse_channel_indices,
)
from beamforming.stream_adapter import FixedBeamformerPacketizer, MeanChannelPacketizer
from tools.beamforming.capture_multichannel_alsa import build_arecord_command
from tools.beamforming.replay_multichannel_wav_udp import iter_wav_packets


class BeamformingFilterIoTest(unittest.TestCase):
    def test_runtime_filter_round_trip_does_not_lose_complex_weights(self) -> None:
        weights = (
            np.arange(4 * 257, dtype=np.float64).reshape(4, 257)
            + 1j * np.linspace(0.0, 1.0, 4 * 257).reshape(4, 257)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filter.npz"
            save_filter_npz(path, weights, sample_rate=16000)
            loaded, sample_rate = load_filter_npz(path)

        self.assertEqual(sample_rate, 16000)
        np.testing.assert_array_equal(loaded, weights)


class BeamformingChannelDiagnosticsTest(unittest.TestCase):
    def test_reports_silent_duplicate_and_clipped_channels(self) -> None:
        rng = np.random.default_rng(7)
        source = rng.normal(0.0, 0.1, 1600)
        samples = rng.normal(0.0, 0.05, (1600, 8))
        samples[:, 0] = source
        samples[:, 1] = source
        samples[:, 2] = 0.0
        samples[:, 3] = np.where(np.arange(1600) % 2 == 0, 1.0, -1.0)

        report = analyze_channels(samples, sample_rate=16000)

        self.assertEqual(report["channel_count"], 8)
        self.assertIn(3, report["silent_channels"])
        self.assertIn(4, report["clipped_channels"])
        self.assertIn([1, 2], report["duplicate_pairs"])
        self.assertEqual(len(report["channels"]), 8)


class FixedBeamformerPacketizerTest(unittest.TestCase):
    def test_defaults_to_the_first_four_effective_input_channels(self) -> None:
        rng = np.random.default_rng(8)
        source = rng.integers(-2000, 2000, size=(640, 8), dtype=np.int16)
        weights = np.ones((4, 257), dtype=np.complex128) / 4.0
        default_packetizer = FixedBeamformerPacketizer(weights, source_channels=8)
        explicit_packetizer = FixedBeamformerPacketizer(
            weights,
            source_channels=8,
            channel_indices=(0, 1, 2, 3),
        )

        default_packets = default_packetizer.push_pcm16(source.tobytes())
        explicit_packets = explicit_packetizer.push_pcm16(source.tobytes())

        self.assertEqual(default_packetizer.channel_indices.tolist(), [0, 1, 2, 3])
        self.assertEqual(default_packets, explicit_packets)

    def test_repackages_16_ms_beamformer_hops_as_20_ms_udp_packets(self) -> None:
        rng = np.random.default_rng(9)
        source = rng.integers(-2000, 2000, size=(3200, 8), dtype=np.int16)
        weights = np.ones((4, 257), dtype=np.complex128) / 4.0
        packetizer = FixedBeamformerPacketizer(
            weights,
            source_channels=8,
            channel_indices=(0, 1, 2, 3),
            sample_rate=16000,
            output_packet_ms=20,
        )

        packets: list[bytes] = []
        for offset in range(0, source.shape[0], 320):
            packets.extend(packetizer.push_pcm16(source[offset : offset + 320].tobytes()))

        self.assertGreater(len(packets), 0)
        self.assertTrue(all(len(packet) == 640 for packet in packets))
        self.assertEqual(packetizer.output_packet_samples, 320)
        self.assertLess(packetizer.pending_output_samples, 320)

    def test_rejects_invalid_channel_mapping_and_incomplete_frames(self) -> None:
        weights = np.ones((4, 257), dtype=np.complex128)
        with self.assertRaises(ValueError):
            FixedBeamformerPacketizer(
                weights,
                source_channels=8,
                channel_indices=(0, 1, 2),
            )

        packetizer = FixedBeamformerPacketizer(
            weights,
            source_channels=8,
            channel_indices=(0, 1, 2, 3),
        )
        with self.assertRaises(ValueError):
            packetizer.push_pcm16(b"\x00\x01\x02")


class MeanChannelPacketizerTest(unittest.TestCase):
    def test_mean4_uses_only_the_first_four_effective_channels(self) -> None:
        samples = np.zeros((320, 8), dtype=np.int16)
        samples[:, 0] = 100
        samples[:, 1] = 200
        samples[:, 2] = 300
        samples[:, 3] = 400
        samples[:, 4:] = 30000
        packetizer = MeanChannelPacketizer(source_channels=8)

        packets = packetizer.push_pcm16(samples.tobytes())

        self.assertEqual(packetizer.channel_indices.tolist(), [0, 1, 2, 3])
        self.assertEqual(len(packets), 1)
        output = np.frombuffer(packets[0], dtype="<i2")
        np.testing.assert_array_equal(output, np.full(320, 250, dtype=np.int16))

    def test_mean4_preserves_twenty_ms_packets_across_arbitrary_chunks(self) -> None:
        rng = np.random.default_rng(10)
        source = rng.integers(-2000, 2000, size=(1600, 8), dtype=np.int16)
        packetizer = MeanChannelPacketizer(
            source_channels=8,
            channel_indices=(0, 1, 2, 3),
            sample_rate=16000,
            output_packet_ms=20,
        )

        packets: list[bytes] = []
        for start, stop in ((0, 77), (77, 509), (509, 901), (901, 1600)):
            packets.extend(packetizer.push_pcm16(source[start:stop].tobytes()))

        expected = source[:, :4].mean(axis=1).astype("<i2")
        actual = np.frombuffer(b"".join(packets), dtype="<i2")
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(len(packets), 5)
        self.assertTrue(all(len(packet) == 640 for packet in packets))
        self.assertEqual(packetizer.pending_output_samples, 0)

    def test_mean4_rejects_invalid_channel_mapping(self) -> None:
        with self.assertRaises(ValueError):
            MeanChannelPacketizer(source_channels=8, channel_indices=(0, 1, 8))


class MicrophoneRuntimeConfigurationTest(unittest.TestCase):
    def test_defaults_can_build_a_first_four_channel_mean_packetizer(self) -> None:
        packetizer = build_mic_packetizer(mode="mean4", source_channels=8)

        self.assertIsInstance(packetizer, MeanChannelPacketizer)
        self.assertEqual(packetizer.channel_indices.tolist(), [0, 1, 2, 3])

    def test_beamformer_requires_and_loads_a_runtime_filter(self) -> None:
        with self.assertRaises(ValueError):
            build_mic_packetizer(mode="beamformer", source_channels=8)

        weights = np.ones((4, 257), dtype=np.complex128) / 4.0
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "filter.npz"
            save_filter_npz(path, weights, sample_rate=16000)
            packetizer = build_mic_packetizer(
                mode="beamformer",
                source_channels=8,
                filter_path=path,
            )

        self.assertIsInstance(packetizer, FixedBeamformerPacketizer)
        self.assertEqual(packetizer.channel_indices.tolist(), [0, 1, 2, 3])

    def test_rejects_unknown_mode_and_invalid_channel_map(self) -> None:
        with self.assertRaises(ValueError):
            build_mic_packetizer(mode="unknown", source_channels=8)
        with self.assertRaises(ValueError):
            parse_channel_indices("0,1,1,3")

    def test_stream_command_requests_exactly_eight_raw_channels(self) -> None:
        command = build_arecord_stream_command(
            device="hw:2,0",
            channels=8,
            sample_rate=16000,
        )

        self.assertEqual(command[0], "arecord")
        self.assertEqual(command[command.index("-c") + 1], "8")
        self.assertEqual(command[command.index("-r") + 1], "16000")
        self.assertEqual(command[-1], "-")


class MultichannelWavReplayTest(unittest.TestCase):
    def test_replays_sixteen_ms_input_as_twenty_ms_mean4_packets(self) -> None:
        source = np.zeros((1600, 8), dtype=np.int16)
        source[:, 0] = 100
        source[:, 1] = 200
        source[:, 2] = 300
        source[:, 3] = 400
        source[:, 4:] = 30000
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw8.wav"
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(8)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(source.astype("<i2").tobytes())

            packetizer = build_mic_packetizer(mode="mean4", source_channels=8)
            packets = list(iter_wav_packets(path, packetizer, input_frame_ms=16))

        self.assertEqual(len(packets), 5)
        self.assertTrue(all(len(packet) == 640 for packet in packets))
        output = np.frombuffer(b"".join(packets), dtype="<i2")
        np.testing.assert_array_equal(output, np.full(1600, 250, dtype=np.int16))

    def test_replay_cli_can_run_directly_from_the_repository_root(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [
                sys.executable,
                str(project_root / "tools/beamforming/replay_multichannel_wav_udp.py"),
                "--help",
            ],
            cwd=project_root,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--mode {mean4,beamformer}", result.stdout)


class RobotRuntimeCompatibilityTest(unittest.TestCase):
    def test_deployed_runtime_sources_parse_as_python_38(self) -> None:
        project_root = Path(__file__).resolve().parent.parent
        runtime_sources = (
            project_root / "beamforming/filter_io.py",
            project_root / "beamforming/fixed_mini_beamformer.py",
            project_root / "beamforming/mic_runtime.py",
            project_root / "beamforming/stream_adapter.py",
            project_root / "deps/SURF2026_VoiceModule-main/tools/stream_usb_mic.py",
        )

        for source_path in runtime_sources:
            with self.subTest(source=source_path.name):
                ast.parse(
                    source_path.read_text(encoding="utf-8"),
                    filename=str(source_path),
                    feature_version=(3, 8),
                )


class MultichannelAlsaCaptureTest(unittest.TestCase):
    def test_builds_raw_eight_channel_capture_command(self) -> None:
        command = build_arecord_command(
            device="hw:2,0",
            channels=8,
            sample_rate=16000,
            duration_sec=10,
            output=Path("raw8.wav"),
        )

        self.assertEqual(command[0], "arecord")
        self.assertIn("hw:2,0", command)
        self.assertEqual(command[command.index("-c") + 1], "8")
        self.assertEqual(command[command.index("-r") + 1], "16000")
        self.assertEqual(command[-1], "raw8.wav")


if __name__ == "__main__":
    unittest.main()
