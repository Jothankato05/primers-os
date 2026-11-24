"""
PRIMERS OS — Voice command listener.

Optional: needs the SpeechRecognition package and a microphone (PyAudio).
Speech is transcribed with Google's Web Speech API, so audio leaves the
machine while the listener is on — it is off by default and the shell says
so when it is switched on.

Say "primers <command>", e.g. "primers system status". Recognised text is
handed to a callback (the shell), which only runs read-only commands.
"""

import threading
import time
from typing import Callable, Optional

from utils.logger import PrimersLogger

WAKE_WORDS = ("primers", "primer", "primus")

try:
    import speech_recognition as sr  # type: ignore
    _IMPORT_ERROR = ""
except ImportError as e:  # pragma: no cover - depends on the host
    sr = None
    _IMPORT_ERROR = str(e)


def strip_wake_word(text: str) -> Optional[str]:
    """Return the command after the wake word, or None if it wasn't addressed to us."""
    words = (text or "").strip().split()
    if not words or words[0].lower().strip(",.!?") not in WAKE_WORDS:
        return None
    command = " ".join(words[1:]).strip(" ,.!?")
    return command or None


class VoiceListener:
    """Background voice command listener."""

    def __init__(self, command_interpreter=None, on_command: Optional[Callable[[str], None]] = None):
        self.logger = PrimersLogger.get_logger("voice_listener")
        self.ci = command_interpreter
        self.on_command = on_command
        self._running = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.recognizer = None
        if sr is not None:
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = 300
            self.recognizer.dynamic_energy_threshold = True

    # ------------------------------------------------------------------ #

    @staticmethod
    def availability() -> Optional[str]:
        """None when voice can work, otherwise a human-readable reason."""
        if sr is None:
            return ("SpeechRecognition is not installed "
                    "(run: primers-install voice)")
        try:
            sr.Microphone.list_microphone_names()
        except (AttributeError, OSError) as e:
            return f"no microphone support (PyAudio): {e}"
        return None

    def start_listening(self) -> bool:
        if self._running:
            return True
        reason = self.availability()
        if reason:
            self.logger.warning(f"Voice unavailable: {reason}")
            return False
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="VoiceListener")
        self._thread.start()
        self.logger.info("Voice engine active.")
        return True

    def stop_listening(self) -> None:
        self._running = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self.logger.info("Voice engine deactivated.")

    def is_active(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #

    def handle_transcript(self, text: str) -> Optional[str]:
        """Process one transcript; returns the command that was dispatched."""
        command = strip_wake_word(text)
        if not command:
            return None
        self.logger.info(f"Voice command: {command}")
        if self.on_command:
            self.on_command(command)
        elif self.ci:
            self.ci.parse(command)
        return command

    def _listen_loop(self):
        while self._running:
            try:
                with sr.Microphone() as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    try:
                        audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=5)
                    except sr.WaitTimeoutError:
                        continue
                try:
                    text = self.recognizer.recognize_google(audio)
                except sr.UnknownValueError:
                    continue
                except sr.RequestError as e:
                    self.logger.error(f"Speech service error: {e}")
                    self._stop.wait(5)
                    continue
                self.handle_transcript(text)
            except Exception as e:
                self.logger.error(f"Microphone error: {e}")
                self._stop.wait(10)
            if self._stop.is_set():
                break
            time.sleep(0.05)
