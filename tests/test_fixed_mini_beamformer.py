from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from scipy.io import loadmat, wavfile


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO_ROOT / "research" / "beamforming" / "teacher_reference_20260630"
sys.path.insert(0, str(REPO_ROOT))

from beamforming.fixed_mini_beamformer import (  # noqa: E402
    FixedMiniBeamformerStream,
    float_to_matlab_pcm16,
    process_matlab_compatible,
)
from beamforming.reference_verification import verify_teacher_reference  # noqa: E402


class FixedMiniBeamformerReferenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sample_rate, cls.mixture = wavfile.read(REFERENCE_DIR / "mixture.wav")
        cls.output_rate, cls.expected_pcm = wavfile.read(REFERENCE_DIR / "out0.wav")
        cls.weights = loadmat(REFERENCE_DIR / "DCF_Targ7.mat")["DCF_Targ_Filter"]

    def test_python_batch_matches_teacher_matlab_output(self) -> None:
        actual = process_matlab_compatible(
            self.mixture.astype(np.float64) / 32768.0,
            self.weights,
            sample_rate=self.sample_rate,
        )
        actual_pcm = float_to_matlab_pcm16(actual)
        difference = actual_pcm.astype(np.int32) - self.expected_pcm.astype(np.int32)

        self.assertEqual(self.sample_rate, self.output_rate)
        self.assertEqual(actual_pcm.shape, self.expected_pcm.shape)
        self.assertLessEqual(int(np.max(np.abs(difference))), 1)
        self.assertLess(float(np.sqrt(np.mean(difference.astype(np.float64) ** 2))), 0.01)
        self.assertGreater(float(np.mean(difference == 0)), 0.99999)

    def test_streaming_chunk_boundaries_match_batch_output(self) -> None:
        signal = self.mixture[:16384].astype(np.float64) / 32768.0
        expected = process_matlab_compatible(
            signal,
            self.weights,
            sample_rate=self.sample_rate,
        )

        for chunk_sizes in ([256], [320], [37, 511, 128, 997, 64]):
            with self.subTest(chunk_sizes=chunk_sizes):
                stream = FixedMiniBeamformerStream(
                    self.weights,
                    sample_rate=self.sample_rate,
                    matlab_compatible_tail=True,
                )
                pieces = []
                offset = 0
                chunk_index = 0
                while offset < signal.shape[0]:
                    chunk_size = chunk_sizes[chunk_index % len(chunk_sizes)]
                    pieces.append(stream.push(signal[offset : offset + chunk_size]))
                    offset += chunk_size
                    chunk_index += 1
                pieces.append(stream.flush())
                actual = np.concatenate(pieces)

                self.assertEqual(actual.shape, expected.shape)
                np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-12)

    def test_reference_report_exposes_acceptance_metrics(self) -> None:
        report = verify_teacher_reference(REFERENCE_DIR)

        self.assertEqual(report["sample_rate_hz"], 16000)
        self.assertEqual(report["input_channels"], 4)
        self.assertEqual(report["output_samples"], 896320)
        self.assertLessEqual(report["max_abs_error_lsb"], 1)
        self.assertLess(report["rmse_lsb"], 0.01)
        self.assertGreater(report["exact_sample_ratio"], 0.99999)
        self.assertTrue(report["accepted"])


if __name__ == "__main__":
    unittest.main()
