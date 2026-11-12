from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent/'src'))
from direct_client import DEFAULT_PTT_KEY, DirectClient, choose_proximity_key, run_proximity_voice
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
                     pressed=lambda _key: states[index][1])
        connection = Mock(recv=receive)
        status = Mock()
        with patch('direct_client.WindowsVoiceDevice') as device:
            device.return_value.recorded.return_value = [sample]
            run_proximity_voice(connection, focus, lambda: True, status, lambda: DEFAULT_PTT_KEY)
            device.assert_called_once_with(capture=True)
            device.return_value.close.assert_called_once_with()
        self.assertEqual([call.args[0] for call in connection.sendall.call_args_list],
                         [VOICE_KEEPALIVE, VOICE_AUDIO + sample, VOICE_RELEASE])
        status.assert_any_call('Proximity mic active')

    def test_receive_only_never_opens_microphone(self):
        audio = b'\x22' * VOICE_FRAME_BYTES
        focus = Mock(alive=lambda: True, focused=lambda: True, pressed=lambda _key: False)
        connection = Mock()
        connection.recv.side_effect = [VOICE_AUDIO + audio, b'']
        with patch('direct_client.WindowsVoiceDevice') as device:
            run_proximity_voice(connection, focus, lambda: True, Mock(), lambda: DEFAULT_PTT_KEY)
            device.assert_called_once_with(capture=False)
            device.return_value.play.assert_called_once_with(audio)
            device.return_value.close.assert_called_once_with()
        connection.sendall.assert_called_once_with(VOICE_KEEPALIVE)

    def test_rebinding_releases_old_key_and_waits_for_a_fresh_press(self):
        old, new = DEFAULT_PTT_KEY, ord('K')
        steps = [(old, set()), (old, {old}), (new, {old, new}),
                 (new, {old, new}), (new, {old}), (new, {old, new})]
        index = 0
        sample = b'\x33' * VOICE_FRAME_BYTES

        def receive(_):
            nonlocal index
            index += 1
            return VOICE_KEEPALIVE if index < len(steps) else b''

        focus = Mock(alive=lambda: True, focused=lambda: True,
                     pressed=lambda key: key in steps[index][1])
        connection = Mock(recv=receive)
        with patch('direct_client.WindowsVoiceDevice') as device:
            device.return_value.recorded.return_value = [sample]
            run_proximity_voice(connection, focus, lambda: True, Mock(), lambda: steps[index][0])
            self.assertEqual(device.call_count, 2)
        self.assertEqual([call.args[0] for call in connection.sendall.call_args_list],
                         [VOICE_KEEPALIVE, VOICE_AUDIO + sample, VOICE_RELEASE, VOICE_AUDIO + sample])

    def test_binding_persists_and_invalid_saved_key_falls_back_to_f9(self):
        invitation = {'format': 1, 'hostname': 'localhost', 'public_address': '127.0.0.1',
                      'https_port': 443, 'first_udp_port': 18443, 'last_udp_port': 18443,
                      'access_token': 'x'*43}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'proximity-voice.json'

            def client():
                return DirectClient(invitation, test_source='127.0.0.2', proximity_settings=path)

            first = client()
            self.assertEqual(first.proximity_key, DEFAULT_PTT_KEY)
            first.bind_proximity_key(ord('K'))
            self.assertEqual(client().proximity_status, 'Hold K to talk')
            with self.assertRaises(ValueError):
                first.bind_proximity_key(0x1b)
            self.assertEqual(client().proximity_key, ord('K'))
            path.write_text('{"key": 27}', encoding='utf-8')
            self.assertEqual(client().proximity_key, DEFAULT_PTT_KEY)

    @unittest.skipUnless(sys.platform == 'win32', 'Uses Windows virtual key codes')
    def test_key_picker_binds_windows_keycode_and_escape_cancels(self):
        import tkinter as tk

        parent = tk.Tk()
        self.addCleanup(parent.destroy)
        saved = Mock()
        parent.update()
        for event in ('<KeyPress-Escape>', '<KeyPress-k>'):
            choose_proximity_key(parent, saved)
            dialog = next(child for child in parent.winfo_children() if isinstance(child, tk.Toplevel))
            dialog.focus_force()
            parent.update()
            dialog.event_generate(event)
            parent.update()
            self.assertFalse(dialog.winfo_exists())
        saved.assert_called_once_with(ord('K'))
