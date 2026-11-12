from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent/'src'))
from direct_client import run_proximity_voice
from direct_network import VOICE_AUDIO, VOICE_FRAME_BYTES, VOICE_KEEPALIVE, VOICE_RELEASE


class PushToTalkTests(unittest.TestCase):
    def test_ptt_needs_focused_press_and_releases_on_focus_loss(self):
        states = [(False, True), (True, True), (True, False),
                  (True, True), (False, True), (True, True), (True, False)]
        sample = b'\x22' * VOICE_FRAME_BYTES
        index = 0

        def receive(_):
            nonlocal index
            index += 1
            return VOICE_KEEPALIVE if index < len(states) else b''

        focus = Mock(alive=lambda: True, focused=lambda: states[index][0],
                     pressed=lambda: states[index][1])
        connection = Mock(recv=receive)
        status = Mock()
        with patch('direct_client.WindowsVoiceDevice') as device:
            device.return_value.recorded.return_value = [sample]
            run_proximity_voice(connection, focus, lambda: True, status)
            device.assert_called_once_with(capture=True)
            device.return_value.close.assert_called_once_with()
        self.assertEqual([call.args[0] for call in connection.sendall.call_args_list],
                         [VOICE_KEEPALIVE, VOICE_AUDIO + sample, VOICE_RELEASE])
        status.assert_any_call('Proximity mic active')

    def test_receive_only_never_opens_microphone(self):
        audio = b'\x22' * VOICE_FRAME_BYTES
        focus = Mock(alive=lambda: True, focused=lambda: True, pressed=lambda: False)
        connection = Mock()
        connection.recv.side_effect = [VOICE_AUDIO + audio, b'']
        with patch('direct_client.WindowsVoiceDevice') as device:
            run_proximity_voice(connection, focus, lambda: True, Mock())
            device.assert_called_once_with(capture=False)
            device.return_value.play.assert_called_once_with(audio)
            device.return_value.close.assert_called_once_with()
        connection.sendall.assert_called_once_with(VOICE_KEEPALIVE)
