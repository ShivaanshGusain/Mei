import pyttsx3

class Voice:
    def __init__(self):
        print("[Voice] Initializing Vocal Cords...")
        try:
            self.engine = pyttsx3.init()
            
            # 1. Select a Voice
            # Windows usually has "David" (Male) [0] and "Zira" (Female) [1]
            voices = self.engine.getProperty('voices')
            
            # Try to find a female voice (Zira), otherwise default to the first one
            self.engine.setProperty('voice', voices[1].id if len(voices) > 1 else voices[0].id)
            
            # 2. Set Speed (Default is often too fast)
            self.engine.setProperty('rate', 175) 
            
            print("[Voice] Online.")
        except Exception as e:
            print(f"[Voice] ERROR: {e}")

    def speak(self, text):
        """
        Converts text to speech and plays it immediately.
        """
        if not text:
            return

        print(f"[Voice] Saying: {text}")
        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except RuntimeError:
            # Sometimes the loop is already running; this handles that edge case
            pass

# --- TEST BLOCK ---
if __name__ == "__main__":
    bot = Voice()
    bot.speak("System systems are online. Hello, I am Mei.")