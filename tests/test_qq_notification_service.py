import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from notifications.qq_client import QQError
from notifications.qq_service import QQNotificationService, QQSettingsStore


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

    def configure(self, app_id, secret):
        self.configured = (app_id, secret)

    def check_credentials(self):
        self.finished.emit(not self.fail, "验证成功" if not self.fail else "验证失败")

    def bind(self, kind):
        self.busy = True
        self.status.emit("验证码：123456")

    def send(self, targets, text, image):
        self.busy = True
        if self.fail:
            self.finished.emit(False, "发送失败")
            self.busy = False
            return
        for kind, _ in targets:
            self.delivery.emit(kind, True, "文字已提交")
        self.finished.emit(True, "发送成功")
        self.busy = False

    def cancel(self):
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


if __name__ == "__main__":
    unittest.main()
