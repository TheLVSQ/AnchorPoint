"""ffmpeg hardening for phone-blast uploads (real ffmpeg, skipped if absent)."""
import os
import shutil
import subprocess
import tempfile
import unittest

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from messaging.services import AudioProcessingError, transcode_to_mp3

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not installed")
class TranscodeHardeningTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = tempfile.mkdtemp()
        wav = os.path.join(cls.dir, "tone.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=1", wav], check=True)
        cls.samples = {"tone.wav": wav}
        for name, codec in (("tone.mp3", []), ("tone.webm", ["-c:a", "libopus"]),
                            ("tone.m4a", ["-c:a", "aac"])):
            out = os.path.join(cls.dir, name)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, *codec, out], check=True)
            cls.samples[name] = out

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)
        super().tearDownClass()

    def test_real_recordings_still_transcode(self):
        for name, path in self.samples.items():
            with self.subTest(name=name), open(path, "rb") as fh:
                result = transcode_to_mp3(SimpleUploadedFile(name, fh.read()))
                self.assertTrue(result.name.endswith(".mp3"))
                self.assertGreater(result.size, 0)

    def test_playlist_payloads_disguised_as_mp3_are_refused(self):
        payloads = {
            "hls.mp3": b"#EXTM3U\n#EXTINF:1,\nfile:///etc/hosts\n#EXT-X-ENDLIST\n",
            "remote.mp3": b"#EXTM3U\n#EXTINF:1,\nhttp://169.254.169.254/latest\n#EXT-X-ENDLIST\n",
            "concat.mp3": b"ffconcat version 1.0\nfile '/etc/hosts'\n",
        }
        for name, body in payloads.items():
            with self.subTest(name=name), self.assertRaises(AudioProcessingError):
                transcode_to_mp3(SimpleUploadedFile(name, body))
