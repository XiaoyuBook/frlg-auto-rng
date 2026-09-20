import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from notifications.qq_client import QQError
from notifications.qq_service import QQNotificationService, QQSettingsStore
from pyside_app.qq_notifications import QQNotificationDialog


APP = QApplication.instance() or QApplication([])


class FakeClient(QObject):
    bound = Signal(str, str)
    finished = Signal(bool, str)
    delivery = Signal(str, bool, str)
    log = Signal(str)
    status = Signal(str)
    busy_changed = Signal(bool)
    binding_changed = Signal(str, str, int, int)

    def __init__(self, *, fail=False):
        super().__init__()
        self.busy = False
        self.fail = fail
        self.configured = None
        self.sent = []
        self.cancel_calls = 0

    def configure(self, app_id, secret):
        self.configured = (app_id, secret)

    def check_credentials(self):
        self.finished.emit(not self.fail, "验证成功" if not self.fail else "验证失败")

    def bind(self, kind):
        self.busy = True
        self.status.emit("验证码：123456")

    def send(self, targets, text, image):
        self.busy = True
        self.sent.append((targets, text, image))
        if self.fail:
            self.finished.emit(False, "发送失败")
            self.busy = False
            return
        for kind, _ in targets:
            self.delivery.emit(kind, True, "文字已提交")
        self.finished.emit(True, "发送成功")
        self.busy = False

    def cancel(self):
        self.cancel_calls += 1
        self.busy = False


class QQServiceTests(unittest.TestCase):
    def make_service(self, *, fail=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = QQSettingsStore(Path(directory.name) / "qq.json")
        setup = FakeClient()
        sender = FakeClient(fail=fail)
        return QQNotificationService(store=store, setup_client=setup, sender=sender), store

    def test_secret_is_not_written_by_default(self):
        service, store = self.make_service()
        service.update(app_id="app", secret="super-secret", user_openid="openid", enabled=False)
        payload = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertNotIn("secret", payload)
        self.assertNotIn("super-secret", store.path.read_text(encoding="utf-8"))

    def test_enable_requires_bound_target(self):
        service, _ = self.make_service()
        service.update(app_id="app", secret="secret")
        with self.assertRaises(QQError):
            service.update(enabled=True)

    def test_notify_is_deduplicated_and_records_delivery(self):
        service, _ = self.make_service()
        service.update(app_id="app", secret="secret")
        service.update(user_openid="openid")
        service.update(enabled=True)
        self.assertTrue(service.notify_task("run-1", "测试任务", "已完成", detail="done"))
        self.assertFalse(service.notify_task("run-1", "测试任务", "已完成"))
        self.assertEqual(len(service.records), 1)
        self.assertTrue(service.records[0].success)

    def test_failed_target_is_recorded_without_raising(self):
        service, _ = self.make_service(fail=True)
        service.update(app_id="app", secret="secret")
        service.update(user_openid="openid")
        service.update(enabled=True)
        self.assertTrue(service.notify_task("run-2", "测试任务", "失败"))
        self.assertEqual(len(service.records), 1)
        self.assertFalse(service.records[0].success)

    def test_task_without_cached_frame_sends_text_only(self):
        service, _ = self.make_service()
        service.update(app_id="app", secret="secret")
        service.update(user_openid="openid", enabled=True)

        self.assertTrue(service.notify_task("run-no-frame", "测试任务", "已完成"))
        self.assertEqual(service.sender.sent[-1][2], b"")

    def test_task_with_cached_frame_sends_jpeg(self):
        service, _ = self.make_service()
        service.update(app_id="app", secret="secret")
        service.update(user_openid="openid", enabled=True)
        frame = QImage(12, 8, QImage.Format.Format_RGB32)
        frame.fill(0x3366CC)

        self.assertTrue(service.notify_task("run-frame", "测试任务", "已完成", frame=frame))
        self.assertTrue(service.sender.sent[-1][2].startswith(b"\xff\xd8"))

    def test_closing_dialog_cancels_active_binding(self):
        service, _ = self.make_service()
        dialog = QQNotificationDialog(service)
        self.addCleanup(dialog.deleteLater)
        service.setup.bind("user")
        self.assertTrue(service.setup.busy)

        dialog.close()

        self.assertEqual(service.setup.cancel_calls, 1)
        self.assertFalse(service.setup.busy)

    def test_all_dialog_exit_paths_cancel_once_and_allow_reopening(self):
        exits = {
            "escape": lambda dialog: QTest.keyClick(dialog, Qt.Key.Key_Escape),
            "close": lambda dialog: dialog.close(),
            "finish_button": lambda dialog: dialog.close_button.click(),
            "reject": lambda dialog: dialog.reject(),
            "accept": lambda dialog: dialog.accept(),
            "done": lambda dialog: dialog.done(0),
        }
        for name, dismiss in exits.items():
            with self.subTest(exit=name):
                service, store = self.make_service()
                service.update(app_id="app", secret="secret")
                sender_cancels = service.sender.cancel_calls
                dialog = QQNotificationDialog(service)
                self.addCleanup(dialog.deleteLater)
                self.addCleanup(service.shutdown)
                closed = []
                dialog.closed.connect(lambda: closed.append(True))
                for attempt in (1, 2):
                    dialog.show()
                    APP.processEvents()
                    service.setup.bind("user")
                    dismiss(dialog)
                    APP.processEvents()
                    self.assertFalse(dialog.isVisible())
                    self.assertFalse(service.setup.busy)
                    self.assertEqual(service.setup.cancel_calls, attempt)
                    self.assertEqual(len(closed), attempt)
                    self.assertEqual(service.sender.cancel_calls, sender_cancels)
                    self.assertTrue(store.path.is_file())


if __name__ == "__main__":
    unittest.main()
