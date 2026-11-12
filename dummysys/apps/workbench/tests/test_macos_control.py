"""Real Darwin kernel identities, private control sockets and stale-owner recovery."""
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest

@unittest.skipUnless(sys.platform == 'darwin', 'Darwin kernel APIs')
class MacControlTest(unittest.TestCase):
    def setUp(self):
        from workbench.macos_control import PipeControl
        from workbench.macos_identity import process_identity
        self.temp = tempfile.TemporaryDirectory(prefix='工作台 控制 ')
        self.addCleanup(self.temp.cleanup)
        self.pipe = PipeControl(self.temp.name)
        self.record = process_identity(os.getpid())
        self.stops = []
        self.pipe.start_server(lambda: 'synthetic-test-token', 'one', lambda: self.stops.append(True))
        self.addCleanup(self.pipe.stop_server)

    def request(self, action, **changes):
        params = dict(expected_instance_id='one', expected_process=self.record, timeout_ms=4000)
        params.update(changes)
        return self.pipe.request(action, **params)

    def test_real_peer_identity_and_wrong_instance_do_not_stop(self):
        self.assertEqual(self.request(self.pipe.REQUEST_TOKEN)['token'], 'synthetic-test-token')
        with self.assertRaises(ConnectionError):
            self.request(self.pipe.REQUEST_STOP, expected_instance_id='wrong')
        with self.assertRaises(ConnectionError):
            self.request(self.pipe.REQUEST_STOP, expected_process={**self.record, 'process_created_at': '1'})
        self.assertEqual(self.stops, [])
        self.assertTrue(self.request(self.pipe.REQUEST_STOP)['stopping'])
        deadline = time.monotonic() + 1
        while not self.stops and time.monotonic() < deadline: time.sleep(.01)
        self.assertEqual(self.stops, [True])

    def test_second_server_cannot_replace_live_socket(self):
        from workbench.macos_control import PipeControl
        other = PipeControl(self.temp.name)
        with self.assertRaises(RuntimeError): other.start_server(lambda: 'other', 'two')
        self.assertEqual(self.request(self.pipe.REQUEST_TOKEN)['token'], 'synthetic-test-token')

    def test_partial_client_does_not_block_following_client_forever(self):
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(self.pipe.path))
            client.sendall(b'{')
            self.assertEqual(self.request(self.pipe.REQUEST_TOKEN)['instance_id'], 'one')

    def test_stale_socket_recovers_and_non_socket_is_preserved(self):
        from workbench.macos_control import PipeControl
        self.pipe.stop_server()
        with socket.socket(socket.AF_UNIX) as stale: stale.bind(str(self.pipe.path))
        self.pipe.start_server(lambda: 'recovered', 'one')
        self.assertEqual(self.request(self.pipe.REQUEST_TOKEN)['token'], 'recovered')
        self.pipe.stop_server()
        self.pipe.path.write_text('preserve')
        try:
            with self.assertRaises(RuntimeError): self.pipe.start_server(lambda: 'bad', 'one')
            self.assertEqual(self.pipe.path.read_text(), 'preserve')
        finally: self.pipe.path.unlink()
