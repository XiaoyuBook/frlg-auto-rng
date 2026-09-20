"""QQ notification settings and delivery queue for the FRLG desktop app.

The service deliberately keeps network work in :mod:`qq_client`; the runner only
needs to report a final task outcome and never waits for QQ delivery.
"""
from __future__ import annotations

import base64
import json
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage

from app_paths import RESOURCE_ROOT, USER_DATA_ROOT
from .qq_client import QQClient, QQError


@dataclass
class QQSettings:
    app_id: str = ""
    secret: str = ""
    remember_secret: bool = False
    user_openid: str = ""
    group_openid: str = ""
    user_enabled: bool = True
    group_enabled: bool = False
    enabled: bool = False
    on_completed: bool = True
    on_failed: bool = True
    on_stopped: bool = False
    attach_image: bool = True

    def targets(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for kind in ("user", "group"):
            if getattr(self, kind + "_enabled"):
                openid = getattr(self, kind + "_openid").strip()
                if not openid:
                    raise QQError("请先绑定勾选的接收方。")
                result.append((kind, openid))
        if not result:
            raise QQError("请至少勾选一个接收方。")
        return result

    def ready(self) -> bool:
        try:
            return bool(self.app_id.strip() and self.secret.strip() and self.targets())
        except QQError:
            return False


class QQSettingsStore:
    """Small JSON store with optional Windows DPAPI protection."""

    def __init__(self, path: Path | None = None):
        self.path = path or USER_DATA_ROOT / "qq-notifications.json"
        self.warning = ""

    @staticmethod
    def _crypt_protect(secret: str) -> str:
        try:
            import win32crypt  # type: ignore
        except ImportError as exc:
            raise QQError("当前环境没有 Windows 密钥保护组件，无法记住 AppSecret；请取消勾选后保存。") from exc
        encrypted = win32crypt.CryptProtectData(secret.encode("utf-8"), "FRLG QQ notification", None, None, None, 1)
        return base64.b64encode(encrypted).decode("ascii")

    @staticmethod
    def _crypt_unprotect(value: str) -> str:
        import win32crypt  # type: ignore
        encrypted = base64.b64decode(value, validate=True)
        return win32crypt.CryptUnprotectData(encrypted, None, None, None, 1)[1].decode("utf-8")

    def load(self) -> QQSettings:
        result = QQSettings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return result
        except (OSError, ValueError, TypeError) as exc:
            self.warning = f"QQ 通知配置读取失败，将使用默认设置：{exc}"
            return result
        if not isinstance(data, dict):
            return result
        for key, default in asdict(result).items():
            if key == "secret":
                continue
            value = data.get(key)
            if isinstance(value, type(default)):
                setattr(result, key, value)
        if result.remember_secret and data.get("protected_secret"):
            try:
                result.secret = self._crypt_unprotect(str(data["protected_secret"]))
            except Exception:
                self.warning = "无法解密保存的 AppSecret，请重新填写。"
                result.secret = ""
        if not result.ready():
            result.enabled = False
        return result

    def save(self, settings: QQSettings) -> None:
        payload = asdict(settings)
        secret = payload.pop("secret", "")
        payload.pop("protected_secret", None)
        if settings.remember_secret and secret:
            payload["protected_secret"] = self._crypt_protect(secret)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


def notification_image(frame=None) -> bytes:
    """Encode the cached BGR frame (or app icon) without capturing a new frame."""
    if isinstance(frame, QImage):
        image = frame.copy()
    elif frame is not None:
        import numpy as np
        array = np.ascontiguousarray(frame)
        if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] != 3:
            raise QQError("通知截图格式无效。")
        height, width, _ = array.shape
        image = QImage(array.data, width, height, array.strides[0], QImage.Format.Format_BGR888).copy()
    else:
        image = QImage(str(RESOURCE_ROOT / "docs" / "assets" / "app-icon.png"))
    if image.isNull():
        raise QQError("通知图片不可用，请检查软件 Logo 资源。")
    if max(image.width(), image.height()) > 1600:
        image = image.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "JPEG", 88):
        raise QQError("无法转换通知图片。")
    return bytes(buffer.data())


@dataclass(frozen=True)
class DeliveryRecord:
    time: str
    event: str
    recipient: str
    success: bool
    detail: str


@dataclass(frozen=True)
class PendingNotification:
    event: str
    text: str
    image: bytes
    targets: tuple[tuple[str, str], ...]
    app_id: str
    secret: str


class QQNotificationService(QObject):
    changed = Signal()
    records_changed = Signal()
    error = Signal(str)
    log = Signal(str)
    operation_finished = Signal(str, bool, str)

    def __init__(self, parent=None, *, store=None, setup_client=None, sender=None):
        super().__init__(parent)
        self.store = store or QQSettingsStore()
        self.settings = self.store.load()
        self.setup = setup_client or QQClient(self)
        self.sender = sender or QQClient(self)
        self.records: list[DeliveryRecord] = []
        self.verified = False
        self.last_error = self.store.warning
        self.operation = ""
        self._queue: deque[PendingNotification] = deque()
        self._seen: deque[str] = deque(maxlen=200)
        self._active: PendingNotification | None = None
        self._active_delivered: set[str] = set()
        self._test_targets: list[tuple[str, str]] = []
        self._test_delivered: set[str] = set()
        self._closed = False
        self.setup.bound.connect(self._bound)
        self.setup.finished.connect(self._setup_finished)
        self.setup.delivery.connect(self._test_delivery)
        self.sender.delivery.connect(self._automatic_delivery)
        self.sender.finished.connect(self._sent)
        self.setup.log.connect(self.log)
        self.sender.log.connect(self.log)

    def update(self, **values) -> None:
        unknown = set(values) - set(asdict(self.settings))
        if unknown:
            raise QQError("未知的 QQ 通知设置：" + ", ".join(sorted(unknown)))
        updated = replace(self.settings, **values)
        credentials_changed = (updated.app_id, updated.secret) != (self.settings.app_id, self.settings.secret)
        if credentials_changed and self.setup.busy:
            raise QQError("请先取消当前操作，再修改凭据。")
        if updated.app_id != self.settings.app_id:
            updated.user_openid = updated.group_openid = ""
            updated.user_enabled = True
            updated.group_enabled = False
        if credentials_changed:
            updated.enabled = False
        if updated.enabled and not updated.ready():
            raise QQError("请先填写凭据，并绑定勾选的接收方。")
        self.store.save(updated)
        was_enabled = self.settings.enabled
        self.settings = updated
        if credentials_changed:
            self.verified = False
        if credentials_changed or (was_enabled and not updated.enabled):
            self._queue.clear()
            self.sender.cancel()
        self.changed.emit()

    def _prepare(self, operation: str) -> None:
        if self._closed:
            raise QQError("通知服务已关闭。")
        self.setup.configure(self.settings.app_id, self.settings.secret)
        self.operation = operation

    def verify(self) -> None:
        self._prepare("verify")
        self.setup.check_credentials()

    def bind(self, kind: str) -> None:
        self._prepare("bind")
        self.setup.bind(kind)

    def send_test(self) -> None:
        targets = self.settings.targets()
        self._prepare("test")
        self._test_targets = targets
        self._test_delivered.clear()
        self.setup.send(targets, "QQ 通知测试：请确认同时收到本条文字和测试图片，以验证通知是否正常。", notification_image())

    def _bound(self, kind: str, openid: str) -> None:
        try:
            self.update(**{kind + "_openid": openid, kind + "_enabled": True})
        except Exception as exc:
            self.last_error = f"绑定结果未能保存：{exc}"
            self.error.emit(self.last_error)
            setattr(self.settings, kind + "_openid", openid)
            setattr(self.settings, kind + "_enabled", True)
            self.changed.emit()

    def _setup_finished(self, ok: bool, message: str) -> None:
        operation, self.operation = self.operation, ""
        if operation == "test" and not ok:
            for kind, _ in self._test_targets:
                if kind not in self._test_delivered:
                    self._record("图文测试", kind, False, message)
        self._test_targets = []
        if operation == "verify":
            self.verified = ok
        if not ok and not message.startswith("操作已取消"):
            self.last_error = message
        elif operation in ("verify", "test"):
            self.last_error = ""
        self.changed.emit()
        self.operation_finished.emit(operation, ok, message)

    def _record(self, event: str, kind: str, ok: bool, detail: str) -> None:
        self.records.insert(0, DeliveryRecord(datetime.now().strftime("%H:%M:%S"), event,
                                             "QQ 私聊" if kind == "user" else "QQ 群聊", ok, detail))
        del self.records[100:]
        self.last_error = "" if ok else detail
        self.records_changed.emit()
        self.changed.emit()

    def _automatic_delivery(self, kind: str, ok: bool, detail: str) -> None:
        if self._active:
            self._active_delivered.add(kind)
            self._record(self._active.event, kind, ok, detail)

    def _test_delivery(self, kind: str, ok: bool, detail: str) -> None:
        self._test_delivered.add(kind)
        self._record("图文测试", kind, ok, detail)

    def notify_task(self, run_id: str, task: str, outcome: str, *, target="", detail="", frame=None) -> bool:
        setting = self.settings
        key = {"已完成": "on_completed", "失败": "on_failed", "已停止": "on_stopped"}.get(outcome)
        if self._closed or not setting.enabled or not key or not getattr(setting, key) or run_id in self._seen:
            return False
        self._seen.append(run_id)
        event = {"已完成": "任务完成", "失败": "任务异常", "已停止": "手动停止"}[outcome]
        try:
            targets = tuple(setting.targets())
            if len(self._queue) >= 20:
                raise QQError("待发送通知过多，当前通知未加入队列。")
            text = f"{task} · {event}\n"
            if target:
                text += f"目标：{target}\n"
            text += f"结果：{outcome}\n"
            if detail:
                text += f"详情：{str(detail)[:800]}\n"
            text += "结束时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            image = b""
            if setting.attach_image and frame is not None:
                try:
                    image = notification_image(frame)
                except QQError as exc:
                    self.log.emit(f"通知截图不可用，将只发送文字：{exc}")
            self._queue.append(PendingNotification(event, text, image, targets, setting.app_id, setting.secret))
            self._drain()
            return True
        except Exception as exc:
            self.last_error = f"QQ 通知未发送：{exc}"
            self.log.emit(self.last_error)
            self.error.emit(self.last_error)
            self.changed.emit()
            return False

    def _drain(self) -> None:
        if self._closed or self.sender.busy or self._active is not None or not self._queue:
            return
        self._active = self._queue.popleft()
        self._active_delivered.clear()
        try:
            self.sender.configure(self._active.app_id, self._active.secret)
            self.sender.send(list(self._active.targets), self._active.text, self._active.image)
        except Exception as exc:
            self._sent(False, str(exc))

    def _sent(self, ok: bool, message: str) -> None:
        if self._active and not ok:
            for kind, _ in self._active.targets:
                if kind not in self._active_delivered:
                    self._record(self._active.event, kind, False, message)
        self._active = None
        if not ok:
            self.last_error = message
            self.error.emit(message)
        self.changed.emit()
        QTimer.singleShot(0, self._drain)

    def shutdown(self) -> None:
        self._closed = True
        self._queue.clear()
        self.setup.cancel()
        self.sender.cancel()
