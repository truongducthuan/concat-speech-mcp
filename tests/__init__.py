import os
import tempfile

# Tests never read the developer's speech settings file (engine choice, API keys):
# the server reads it before every tool call, and a real key would reach a billed API.
os.environ["CONCAT_SPEECH_ENV_FILE"] = os.path.join(tempfile.gettempdir(), "concat-speech-tests-no-such-env")
