import threading
import time
import speech_recognition as sr
from typing import Optional, Callable
from utils.logger import PrimersLogger

class VoiceListener:
    """
    Background voice command listener.
    Uses speech_recognition to convert voice to text and dispatch to the command interpreter.
    """

    def __init__(self, command_interpreter):
        self.logger = PrimersLogger.get_logger("voice_listener")
        self.ci = command_interpreter
        self._running = False
        self._thread = None
        self.recognizer = sr.Recognizer()
        # Adjust for ambient noise
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True

    def start_listening(self) -> None:
        """Starts the background listening thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        self.logger.info("Voice engine active. Listening for commands...")

    def stop_listening(self) -> None:
        """Stops the background listening thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        self.logger.info("Voice engine deactivated.")

    def _listen_loop(self):
        """Continuously listens for audio and processes it."""
        while self._running:
            try:
                with sr.Microphone() as source:
                    # Adjust for ambient noise on each cycle to stay calibrated
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    self.logger.info("Listening...")
                    
                    try:
                        audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=5)
                    except sr.WaitTimeoutError:
                        continue # No audio detected, loop again
                        
                    self.logger.info("Processing audio...")
                    try:
                        # Use Google Web Speech API (default)
                        text = self.recognizer.recognize_google(audio)
                        self.logger.info(f"Voice Command Detected: '{text}'")
                        
                        # Process command via interpreter
                        if text.lower().startswith("primers"):
                            # Strip the wake word
                            cmd_text = text.lower().replace("primers", "", 1).strip()
                            if cmd_text:
                                self.logger.info(f"Executing voice command: {cmd_text}")
                                # In a real shell integration, we'd need a way to pipe this to the UI
                                # For now, we dispatch to CI and log result
                                parsed = self.ci.parse(cmd_text)
                                if parsed:
                                    self.logger.info(f"Voice dispatch successful: {parsed.action}")
                                    # Note: Implementation of actual side-effects depends on where this is used
                        
                    except sr.UnknownValueError:
                        # Speech was unintelligible
                        pass
                    except sr.RequestError as e:
                        self.logger.error(f"Voice API request error: {e}")
                        time.sleep(5) # Wait before retry if network error
                        
            except Exception as e:
                self.logger.error(f"Microphone error: {e}")
                time.sleep(10) # Wait before retry if hardware error

    def is_active(self) -> bool:
        return self._running
