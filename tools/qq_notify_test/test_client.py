"""Offline integration tests: real Qt HTTP/WebSocket clients, local servers."""
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtNetwork import QHostAddress
from PySide6.QtTest import QTest
from PySide6.QtWebSockets import QWebSocketServer
from PySide6.QtWidgets import QApplication

if __package__:
    from .app import MainWindow
    from .client import QQClient, QQError
else:
    from app import MainWindow
    from client import QQClient, QQError


APP = QApplication.instance() or QApplication([])


def wait_until(predicate, timeout=4000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for Qt network operation")
        QTest.qWait(10)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    def handle_request(self):
        state = self.server.state
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = raw if self.command == "PUT" else json.loads(raw) if raw else None
        state["requests"].append((self.command, self.path, body, dict(self.headers)))
        status, result = 200, {}
        if self.path == "/token":
            result = {"access_token": "TEST_TOKEN", "expires_in": state.get("expiry", "7200")}
        elif self.path == "/gateway":
            result = {"url": state["gateway"]}
        elif self.path in state.get("errors", {}):
            status, result = state["errors"][self.path]
        elif self.path.endswith("/upload_prepare"):
            state["size"] = int(body["file_size"])
            result = {"upload_id": "UPLOAD", "block_size": "4", "parts": [
                {"index": i, "presigned_url": f"{state['base']}/upload/{i}"}
                for i in range(1, (state["size"] + 3) // 4 + 1)]}
        elif self.path.endswith("/files"):
            result = {"file_info": "MEDIA_INFO"}
        elif self.path.endswith("/messages"):
            result = {"id": "MESSAGE_ID"}
        response = json.dumps(result).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        try:
            self.wfile.write(response)
        except (ConnectionError, OSError):
            pass


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.ws = QWebSocketServer("QQ test", QWebSocketServer.SslMode.NonSecureMode)
        self.assertTrue(self.ws.listen(QHostAddress("127.0.0.1"), 0))
        self.state = {"base": self.base, "gateway": f"ws://127.0.0.1:{self.ws.serverPort()}", "requests": []}
        self.server.state = self.state
        self.peer = None
        self.gateway_packets = []
        self.send_ready = True
        self.heartbeat_interval = 5000
        self.ws.newConnection.connect(self.accept_socket)
        self.client = QQClient(api_base=self.base, token_url=self.base + "/token")
        self.client.configure("TEST_APP", "TEST_SECRET")
        self.results, self.logs, self.bindings, self.statuses = [], [], [], []
        self.client.finished.connect(lambda ok, message: self.results.append((ok, message)))
        self.client.log.connect(self.logs.append)
        self.client.bound.connect(lambda kind, oid: self.bindings.append((kind, oid)))
        self.client.status.connect(self.statuses.append)

    def tearDown(self):
        self.client.cancel()
        self.client.deleteLater()
        if self.peer:
            self.peer.abort()
            self.peer.deleteLater()
        self.ws.close()
        self.ws.deleteLater()
        QTest.qWait(20)

    def accept_socket(self):
        self.peer = self.ws.nextPendingConnection()
        self.peer.textMessageReceived.connect(self.receive_packet)
        self.emit_packet({"op": 10, "d": {"heartbeat_interval": self.heartbeat_interval}})

    def emit_packet(self, packet):
        self.peer.sendTextMessage(json.dumps(packet))

    def receive_packet(self, raw):
        packet = json.loads(raw)
        self.gateway_packets.append(packet)
        if packet["op"] == 2 and self.send_ready:
            self.emit_packet({"op": 0, "t": "READY", "s": 12, "d": {}})
        if packet["op"] == 1:
            self.emit_packet({"op": 11})

    def wait_result(self):
        wait_until(lambda: bool(self.results))
        return self.results[-1]

    def wait_code(self):
        wait_until(lambda: any("验证码：" in s for s in self.statuses))
        return next(s.split("验证码：")[-1] for s in reversed(self.statuses) if "验证码：" in s)

    def messages(self):
        return [r for r in self.state["requests"] if r[1].endswith("/messages")]

    def test_private_and_group_text_with_cached_token(self):
        self.client.send([("user", "U"), ("group", "G")], "中文测试")
        self.assertTrue(self.wait_result()[0])
        messages = self.messages()
        self.assertEqual([r[1] for r in messages], ["/v2/users/U/messages", "/v2/groups/G/messages"])
        self.assertEqual(messages[0][2], {"msg_type": 0, "content": "中文测试"})
        self.assertEqual(messages[1][3]["Authorization"], "QQBot TEST_TOKEN")
        self.assertEqual(sum(r[1] == "/token" for r in self.state["requests"]), 1)

    def test_credentials_change_invalidates_token(self):
        self.state["expiry"] = 7200
        self.client.check_credentials()
        self.assertTrue(self.wait_result()[0])
        self.results.clear()
        self.client.configure("OTHER_APP", "OTHER_SECRET")
        self.client.send([("user", "U")], "hello")
        self.assertTrue(self.wait_result()[0])
        tokens = [r[2] for r in self.state["requests"] if r[1] == "/token"]
        self.assertEqual(len(tokens), 2)
        self.assertEqual(tokens[-1], {"appId": "OTHER_APP", "clientSecret": "OTHER_SECRET"})

    def test_partial_failure_continues_and_redacts_secrets(self):
        self.state["errors"] = {"/v2/users/U/messages": (403, {"message": "TEST_SECRET TEST_TOKEN denied"})}
        self.client.send([("user", "U"), ("group", "G")], "hello")
        ok, message = self.wait_result()
        self.assertFalse(ok)
        self.assertIn("群聊发送成功", message)
        self.assertEqual(len(self.messages()), 2)  # No automatic message retry.
        self.assertIn("403", message)
        self.assertNotIn("TEST_SECRET", "".join(self.logs))
        self.assertNotIn("TEST_TOKEN", "".join(self.logs))

    def test_chunk_upload_then_media_message_without_auth_on_upload_url(self):
        self.client.send([("group", "G")], "", b"ABCDEFGHIJ")
        self.assertTrue(self.wait_result()[0])
        puts = [r for r in self.state["requests"] if r[0] == "PUT"]
        self.assertEqual([r[2] for r in puts], [b"ABCD", b"EFGH", b"IJ"])
        self.assertTrue(all("Authorization" not in r[3] for r in puts))
        self.assertEqual(self.messages()[0][2], {"msg_type": 7, "media": {"file_info": "MEDIA_INFO"}})
        parts = [r[2] for r in self.state["requests"] if r[1].endswith("upload_part_finish")]
        self.assertEqual([p["block_size"] for p in parts], ["4", "4", "2"])

    def test_expired_token_error_is_redacted_and_next_send_refreshes(self):
        self.state["errors"] = {"/v2/users/U/messages": (401, {"message": "expired TEST_TOKEN TEST_SECRET"})}
        self.client.send([("user", "U")], "hello")
        self.assertFalse(self.wait_result()[0])
        self.assertNotIn("TEST_TOKEN", "".join(self.logs))
        self.assertNotIn("TEST_SECRET", "".join(self.logs))
        self.state["errors"] = {}
        self.results.clear()
        self.client.send([("user", "U")], "hello again")
        self.assertTrue(self.wait_result()[0])
        self.assertEqual(sum(r[1] == "/token" for r in self.state["requests"]), 2)

    def test_image_failure_retains_text_and_reports_failure(self):
        self.state["errors"] = {"/v2/users/U/upload_prepare": (500, {"message": "upload failed"})}
        self.client.send([("user", "U")], "keep this", b"IMAGE")
        self.assertFalse(self.wait_result()[0])
        self.assertEqual(len(self.messages()), 1)
        self.assertEqual(self.messages()[0][2]["msg_type"], 0)
        self.assertTrue(any("文字发送成功" in s for s in self.logs))

    def test_private_binding_rejects_wrong_code_then_succeeds(self):
        self.client.bind("user")
        code = self.wait_code()
        identify = next(p for p in self.gateway_packets if p["op"] == 2)
        self.assertEqual(identify["d"]["intents"], 1 << 25)
        self.emit_packet({"op": 0, "t": "C2C_MESSAGE_CREATE", "s": 13,
                          "d": {"content": "wrong", "author": {"user_openid": "WRONG"}}})
        wait_until(lambda: any("未匹配" in s for s in self.logs))
        self.assertEqual(self.bindings, [])
        self.emit_packet({"op": 0, "t": "C2C_MESSAGE_CREATE", "s": 14,
                          "d": {"content": code, "author": {"user_openid": "USER_ID"}}})
        self.assertTrue(self.wait_result()[0])
        self.assertEqual(self.bindings, [("user", "USER_ID")])
        self.assertFalse(self.client.busy)

    def test_group_binding_handles_both_event_names(self):
        for event in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"):
            with self.subTest(event=event):
                self.results.clear()
                self.statuses.clear()
                self.client.bind("group")
                code = self.wait_code()
                self.emit_packet({"op": 0, "t": event, "s": 13,
                                  "d": {"content": "<@BOT> " + code, "group_openid": "GROUP_ID"}})
                self.assertTrue(self.wait_result()[0])
        self.assertEqual(self.bindings, [("group", "GROUP_ID"), ("group", "GROUP_ID")])

    def test_no_code_before_ready_and_heartbeat_uses_sequence(self):
        self.send_ready = False
        self.heartbeat_interval = 60
        self.client.bind("user")
        wait_until(lambda: any(p["op"] == 2 for p in self.gateway_packets))
        self.assertFalse(any("验证码：" in s for s in self.statuses))
        self.emit_packet({"op": 0, "t": "READY", "s": 123, "d": {}})
        self.wait_code()
        wait_until(lambda: any(p["op"] == 1 for p in self.gateway_packets))
        self.assertEqual(next(p["d"] for p in self.gateway_packets if p["op"] == 1), 123)
        self.client.cancel()
        self.assertFalse(self.wait_result()[0])

    def test_gateway_auth_error_and_binding_timeout(self):
        self.client.bind("group")
        self.wait_code()
        self.emit_packet({"op": 9})
        self.assertFalse(self.wait_result()[0])
        self.assertIn("鉴权失败", self.results[-1][1])
        self.results.clear()
        self.client.bind_timeout_ms = 100
        self.client.bind("user")
        self.assertFalse(self.wait_result()[0])
        self.assertIn("超时", self.results[-1][1])

    def test_cancel_http_then_new_operation_has_no_stale_result(self):
        self.client.check_credentials()
        self.client.cancel()
        self.assertFalse(self.results[-1][0])
        self.results.clear()
        self.client.check_credentials()
        self.assertTrue(self.wait_result()[0])
        QTest.qWait(100)
        self.assertEqual(len(self.results), 1)

    def test_missing_target_rejected_before_network(self):
        with self.assertRaises(QQError):
            self.client.send([("user", "")], "hello")
        self.assertFalse(self.client.busy)
        self.assertEqual(self.state["requests"], [])

    def test_gui_buttons_persistence_and_image_conversion(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "settings.json"
            window = MainWindow(config_path=config, client=self.client)
            window.app_id.setText("TEST_APP")
            window.secret.setText("TEST_SECRET")
            window.user_id.setText("U")
            window.show()
            window.verify_button.click()
            self.assertFalse(window.send_button.isEnabled())
            self.assertTrue(window.cancel_button.isEnabled())
            self.assertTrue(self.wait_result()[0])
            self.assertTrue(window.send_button.isEnabled())
            self.assertFalse(window.cancel_button.isEnabled())
            window.save_config()
            saved = config.read_text(encoding="utf-8")
            self.assertNotIn("TEST_SECRET", saved)
            self.assertNotIn("TEST_TOKEN", saved)
            image = QImage(8, 8, QImage.Format.Format_RGB32)
            image.fill(QColor("red"))
            image_path = str(Path(folder) / "image.png")
            self.assertTrue(image.save(image_path))
            window._image_path = image_path
            self.assertTrue(window._image_bytes().startswith(b"\xff\xd8"))
            window.close()
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
