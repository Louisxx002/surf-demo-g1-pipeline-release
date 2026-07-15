from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from beamforming.channel_diagnostics import analyze_channels
from beamforming.filter_io import load_filter_npz, save_filter_npz
from beamforming.stream_adapter import FixedBeamformerPacketizer
from tools.beamforming.capture_multichannel_alsa import build_arecord_command


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
