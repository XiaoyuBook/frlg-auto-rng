"""Native PySide6 QQ notification settings and tutorial window.

This intentionally uses the same cards, colours and window chrome as the FRLG
application.  It avoids Qt WebEngine so the settings page works in the regular
PySide6 installation used by the source launcher.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QRect, QUrl, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpacerItem, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app_paths import RESOURCE_ROOT
from pyside_chrome import ThemedDialog, decorate_window
from pyside_preview import APP_STYLE, Card
from notifications.qq_service import QQError, QQNotificationService
from .qq_guide_source import load_qq_steps


ACCENT = "#6177f2"
SOFT = "#eef1ff"
MUTED = "#718096"
ICON_PATH = RESOURCE_ROOT / "docs" / "assets" / "app-icon.png"
QQ_PLATFORM_URL = "https://q.qq.com/#/apps"


def _label(text="", *, muted=False, strong=False):
    label = QLabel(text)
    if muted:
        label.setProperty("qqMuted", True)
    if strong:
        label.setProperty("qqStrong", True)
    return label


def _button(text, *, primary=False):
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setProperty("qqPrimary", primary)
    button.setMinimumHeight(35)
    return button


def _card(title, subtitle=""):
    card = QFrame()
    card.setObjectName("qqCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 17)
    layout.setSpacing(10)
    heading = QHBoxLayout()
    heading.setSpacing(8)
    heading.addWidget(_label(title, strong=True))
    heading.addStretch(1)
    layout.addLayout(heading)
    if subtitle:
        layout.addWidget(_label(subtitle, muted=True))
    return card, layout


def _bell_pixmap(size=36):
    """Draw the lightweight bell mark used by the reference settings page."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#07805f"), 2.2, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    path = QPainterPath()
    path.moveTo(8, 25)
    path.cubicTo(11, 22, 11, 19, 11, 15)
    path.cubicTo(11, 5, 25, 5, 25, 15)
    path.cubicTo(25, 19, 25, 22, 28, 25)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawArc(13, 25, 10, 7, 180 * 16, 180 * 16)
    painter.end()
    return pixmap


class QQNotificationDialog(ThemedDialog):
    closed = Signal()

    def __init__(self, service: QQNotificationService, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("QQNotificationDialog")
        self.setWindowTitle("QQ 通知")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumSize(650, 560)
        self.resize(930, 760)
        self.setStyleSheet(APP_STYLE + r"""
            QDialog#QQNotificationDialog { background: #f3f6fb; }
            QFrame#qqCard { background: #ffffff; border: 1px solid #e1e7f0; border-radius: 14px; }
            QLabel[qqMuted="true"] { color: #718096; font-size: 12px; }
            QLabel[qqStrong="true"] { color: #172033; font-size: 15px; font-weight: 700; }
            QLabel#qqCode { color: #3f54b6; font-size: 29px; font-weight: 600; letter-spacing: 4px; }
            QLabel#qqFeedback { padding: 8px 10px; border-radius: 8px; background: #eef1ff; color: #5367c8; }
            QLabel#qqFeedback[error="true"] { background: #fff0f3; color: #b84459; }
            QLineEdit#qqField { background: #f8faff; border: 1px solid #dbe2ed; border-radius: 8px; padding: 8px 10px; min-height: 18px; }
            QCheckBox { spacing: 8px; min-height: 28px; }
            QPushButton[qqPrimary="true"] { color: white; border: 0; border-radius: 8px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6177f2,stop:1 #6f5fe9); }
            QPushButton[qqPrimary="true"]:hover { background: #5369e4; }
            QPushButton#qqTab { border: 0; border-bottom: 3px solid transparent; color: #718096; padding: 10px 3px; border-radius: 0; }
            QPushButton#qqTab:checked { color: #5267d7; border-bottom-color: #6177f2; font-weight: 600; }
            QPushButton#qqPhase { text-align: left; border: 1px solid #e1e7f0; border-radius: 8px; background: white; padding: 8px; }
            QPushButton#qqPhase:checked { background: #eef1ff; border-color: #bdc8ff; color: #5267cf; }
            QListWidget#qqSteps { background: transparent; border: 0; border-right: 1px solid #e1e7f0; padding-right: 9px; }
            QListWidget#qqSteps::item { color: #6d7a90; padding: 8px 6px; border-radius: 7px; }
            QListWidget#qqSteps::item:selected { background: #e7ecff; color: #4b60c8; font-weight: 600; }
            QPushButton#qqBackLink { border: 0; background: transparent; color: #07805f; padding: 4px 0; min-height: 28px; text-align: left; }
            QPushButton#qqBackLink:hover { color: #056548; text-decoration: underline; }
            QTableWidget { background: white; border: 1px solid #e1e7f0; border-radius: 10px; gridline-color: #edf0f6; }
            QHeaderView::section { background: #f7f9fd; color: #718096; border: 0; padding: 9px; font-weight: 500; }
        """)
        self._guide_steps = load_qq_steps()
        self._guide_index = 0
        self._guide_full_image = False
        self._guide_show_hints = True
        self._page = "setup"
        self._build()
        self._connect_service()
        self._refresh()
        decorate_window(self, dark=False)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName("qqHeader")
        header.setStyleSheet("QFrame#qqHeader { background:#f3f6fb; border-bottom:1px solid #e1e7f0; }")
        h = QHBoxLayout(header)
        h.setContentsMargins(22, 18, 22, 15)
        self.header_icon = QLabel()
        self.header_icon.setFixedSize(42, 42)
        self.header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_icon.setStyleSheet("background:#e8f6f0; border-radius:10px;")
        self.header_icon.setPixmap(_bell_pixmap(36))
        h.addWidget(self.header_icon)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.header_title = _label("QQ 通知", strong=True)
        self.header_subtitle = _label("任务结束后，在 QQ 查看结果与游戏画面", muted=True)
        titles.addWidget(self.header_title)
        titles.addWidget(self.header_subtitle)
        h.addLayout(titles, 1)
        self.enable_check = QCheckBox("启用通知")
        self.enable_check.toggled.connect(lambda value: self._update(enabled=value))
        h.addWidget(self.enable_check)
        outer.addWidget(header)

        tabs = QFrame()
        tabs.setStyleSheet("QFrame { background:white; border-bottom:1px solid #e1e7f0; }")
        tab_layout = QHBoxLayout(tabs)
        tab_layout.setContentsMargins(22, 0, 22, 0)
        tab_layout.setSpacing(18)
        self.tab_buttons = {}
        for key, text in (("setup", "接入设置"), ("rules", "通知规则"), ("records", "发送记录")):
            button = QPushButton(text)
            button.setObjectName("qqTab")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, value=key: self._show_page(value))
            tab_layout.addWidget(button)
            self.tab_buttons[key] = button
        tab_layout.addStretch(1)
        guide = QPushButton("▣  注册与绑定教程")
        guide.setObjectName("qqGuideButton")
        guide.clicked.connect(self._open_guide)
        tab_layout.addWidget(guide)
        self.tabs_bar = tabs
        outer.addWidget(self.tabs_bar)

        self.stack = QStackedWidget()
        self.setup_page = self._build_setup_page()
        self.rules_page = self._build_rules_page()
        self.records_page = self._build_records_page()
        self.guide_page = self._build_guide_page()
        for page in (self.setup_page, self.rules_page, self.records_page, self.guide_page):
            self.stack.addWidget(page)
        outer.addWidget(self.stack, 1)

        footer = QFrame()
        footer.setStyleSheet("QFrame { background:white; border-top:1px solid #e1e7f0; }")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(22, 12, 22, 12)
        self.feedback = _label("设置自动保存 · 密钥仅本次会话使用", muted=True)
        self.feedback.setObjectName("qqFeedback")
        self.feedback.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        fl.addWidget(self.feedback, 1)
        self.close_button = _button("完成")
        self.close_button.clicked.connect(self.close)
        fl.addWidget(self.close_button)
        outer.addWidget(footer)

    def _build_setup_page(self):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(22, 19, 22, 22)
        root.setSpacing(15)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(15)
        left, ll = _card("① 接入 QQ 机器人", "填写开放平台凭据，然后验证连接。")
        form = QVBoxLayout()
        form.setSpacing(6)
        self.app_id = QLineEdit()
        self.app_id.setObjectName("qqField")
        self.app_id.setPlaceholderText("例如 1024…")
        self.secret = QLineEdit()
        self.secret.setObjectName("qqField")
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("AppSecret")
        toggle = QPushButton("显示")
        toggle.setFixedWidth(52)
        toggle.clicked.connect(lambda: self._toggle_secret(toggle))
        secret_row = QHBoxLayout()
        secret_row.setContentsMargins(0, 0, 0, 0)
        secret_row.setSpacing(6)
        secret_row.addWidget(self.secret, 1)
        secret_row.addWidget(toggle)
        form.addWidget(_label("AppID", muted=True))
        form.addWidget(self.app_id)
        form.addWidget(_label("AppSecret", muted=True))
        form.addLayout(secret_row)
        ll.addLayout(form)
        self.remember = QCheckBox("记住密钥（使用 Windows 保护）")
        ll.addWidget(self.remember)
        verify = _button("验证凭据", primary=True)
        verify.clicked.connect(self._verify)
        ll.addWidget(verify)
        platform = _button("打开 QQ 开放平台")
        platform.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(QQ_PLATFORM_URL)))
        ll.addWidget(platform)
        self.credential_status = _label("尚未验证", muted=True)
        ll.addWidget(self.credential_status)

        recipients, rl = _card("② 绑定接收方", "私聊和群聊分别绑定；接收方无需 AppSecret。")
        self.user_check = QCheckBox("QQ 私聊")
        self.user_openid = _label("尚未绑定", muted=True)
        user_bind = _button("绑定私聊")
        user_bind.clicked.connect(lambda: self._bind("user"))
        user_info = QVBoxLayout(); user_info.setSpacing(2); user_info.addWidget(self.user_check); user_info.addWidget(self.user_openid)
        user_row = QHBoxLayout(); user_row.addLayout(user_info, 1); user_row.addWidget(user_bind); rl.addLayout(user_row)
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine); line.setStyleSheet("color:#edf0f6")
        rl.addWidget(line)
        self.group_check = QCheckBox("QQ 群聊")
        self.group_openid = _label("尚未绑定", muted=True)
        group_bind = _button("绑定群聊")
        group_bind.clicked.connect(lambda: self._bind("group"))
        group_info = QVBoxLayout(); group_info.setSpacing(2); group_info.addWidget(self.group_check); group_info.addWidget(self.group_openid)
        group_row = QHBoxLayout(); group_row.addLayout(group_info, 1); group_row.addWidget(group_bind); rl.addLayout(group_row)
        self.binding_status = _label("绑定后会显示 60 秒验证码，并自动换码。", muted=True)
        self.binding_status.setWordWrap(True)
        rl.addWidget(self.binding_status)
        self.user_check.toggled.connect(lambda value: self._update(user_enabled=value))
        self.group_check.toggled.connect(lambda value: self._update(group_enabled=value))
        grid.addWidget(left, 0, 0)
        grid.addWidget(recipients, 1, 0)

        test, tl = _card("③ 图文验证", "确认文字和图片都能收到后再启用自动通知。")
        self.test_message = QFrame()
        self.test_message.setStyleSheet("QFrame { background:#fafbff; border:1px solid #e2e8f3; border-radius:10px; }")
        tm = QVBoxLayout(self.test_message)
        tm.setContentsMargins(15, 13, 15, 13)
        tm.addWidget(_label("FRLG 通知机器人", strong=True))
        tm.addWidget(_label("QQ 通知测试：请确认同时收到本条文字和测试图片。", muted=True))
        logo = QLabel(); logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(QPixmap(str(ICON_PATH)).scaled(78, 78, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        tm.addWidget(logo)
        tl.addWidget(self.test_message)
        test_button = _button("发送图文测试", primary=True)
        test_button.clicked.connect(self._send_test)
        tl.addWidget(test_button)
        self.test_status = _label("等待测试", muted=True)
        self.test_status.setWordWrap(True)
        tl.addWidget(self.test_status)
        grid.addWidget(test, 0, 1, Qt.AlignmentFlag.AlignTop)
        next_card, next_layout = _card("接入完成后", "验证通过并确认收件，再开启自动通知。")
        for text in ("1　验证 AppID 和 AppSecret", "2　绑定私聊或群聊接收方", "3　发送图文测试并核对 QQ"):
            next_layout.addWidget(_label(text, muted=True))
        grid.addWidget(next_card, 1, 1, Qt.AlignmentFlag.AlignTop)
        left.setStyleSheet("QFrame#qqCard { background: transparent; border: 0; border-bottom: 1px solid #dfe5ee; border-radius: 0; }")
        recipients.setStyleSheet("QFrame#qqCard { background: transparent; border: 0; border-radius: 0; }")
        test.setStyleSheet("QFrame#qqCard { background: #f7f9fc; border: 0; border-radius: 0; }")
        next_card.setStyleSheet("QFrame#qqCard { background: #f7f9fc; border: 0; border-radius: 0; }")
        root.addLayout(grid)
        root.addStretch(1)
        scroll.setWidget(content)
        layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0); layout.addWidget(scroll)
        return page

    def _build_rules_page(self):
        page = QWidget()
        root = QVBoxLayout(page); root.setContentsMargins(22, 19, 22, 22); root.setSpacing(15)
        grid = QGridLayout(); grid.setHorizontalSpacing(16); grid.setVerticalSpacing(15)
        rules, rl = _card("何时通知", "每轮运行只推送最终结果。")
        self.rule_completed = QCheckBox("任务结束")
        rl.addWidget(self.rule_completed); rl.addWidget(_label("报告实际结果；未确认命中时会明确说明。", muted=True))
        self.rule_failed = QCheckBox("异常停止")
        rl.addWidget(self.rule_failed); rl.addWidget(_label("包含停止阶段和失败原因。", muted=True))
        self.rule_stopped = QCheckBox("手动停止")
        rl.addWidget(self.rule_stopped); rl.addWidget(_label("点击“停止 EasyCon”后也发送通知。", muted=True))
        content, cl = _card("消息内容", "文字包含流程、目标、实际结果和结束时间。")
        self.attach_image = QCheckBox("附带游戏画面")
        cl.addWidget(self.attach_image); cl.addWidget(_label("使用结束时可用的最新画面；无画面时只发文字。", muted=True))
        cl.addStretch(1)
        grid.addWidget(rules, 0, 0); grid.addWidget(content, 1, 0)
        preview, pl = _card("消息效果", "内容示例")
        self.preview_kind = QComboBox()
        self.preview_kind.addItems(["命中", "未确认", "异常"])
        self.preview_kind.currentIndexChanged.connect(self._refresh_preview)
        pl.addWidget(self.preview_kind)
        self.preview = QLabel(); self.preview.setWordWrap(True); self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setStyleSheet("background:#fafbff; border:1px solid #e2e8f3; border-radius:10px; padding:15px; color:#34415a")
        pl.addWidget(self.preview)
        grid.addWidget(preview, 0, 1, 2, 1)
        root.addLayout(grid); root.addStretch(1)
        for checkbox, key in ((self.rule_completed, "on_completed"), (self.rule_failed, "on_failed"), (self.rule_stopped, "on_stopped"), (self.attach_image, "attach_image")):
            checkbox.toggled.connect(lambda value, name=key: self._update(**{name: value}))
        return page

    def _build_records_page(self):
        page = QWidget(); root = QVBoxLayout(page); root.setContentsMargins(22, 19, 22, 22)
        card, layout = _card("最近发送 · 本次会话", "接口接受消息后，仍请在 QQ 中核对收件情况。")
        self.records = QTableWidget(0, 4)
        self.records.setHorizontalHeaderLabels(["时间", "通知类型", "接收方", "投递结果"])
        self.records.horizontalHeader().setStretchLastSection(True)
        self.records.verticalHeader().setVisible(False)
        self.records.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.records.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self.records, 1)
        root.addWidget(card, 1)
        return page

    def _build_guide_page(self):
        page = QWidget(); root = QVBoxLayout(page); root.setContentsMargins(22, 15, 22, 22); root.setSpacing(12)
        back = _button("← 返回通知设置"); back.setObjectName("qqBackLink"); back.clicked.connect(lambda: self._show_page("setup")); root.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        phases = QHBoxLayout(); phases.setSpacing(8)
        for index, text in enumerate(("① 注册机器人", "② 连接与绑定", "③ 图文验证")):
            button = QPushButton(text); button.setObjectName("qqPhase"); button.setCheckable(True); button.clicked.connect(lambda _=False, i=index: self._guide_phase(i)); phases.addWidget(button); setattr(self, f"phase_{index}", button)
        root.addLayout(phases)
        self.guide_stack = QStackedWidget(); root.addWidget(self.guide_stack, 1)
        self.register_page = self._build_register_guide(); self.connect_page = self._build_connect_guide(); self.test_page = self._build_test_guide()
        for widget in (self.register_page, self.connect_page, self.test_page): self.guide_stack.addWidget(widget)
        self._guide_phase(0)
        return page

    def _build_register_guide(self):
        page = QScrollArea()
        page.setObjectName("qqGuideScroll")
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.Shape.NoFrame)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QHBoxLayout(content); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(16)
        page.setWidget(content)
        self.step_list = QListWidget(); self.step_list.setObjectName("qqSteps"); self.step_list.setFixedWidth(190)
        self.step_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for index, step in enumerate(self._guide_steps, 1):
            item = QListWidgetItem(f"{index:02d}  {step['title']}"); item.setData(Qt.ItemDataRole.UserRole, index - 1); self.step_list.addItem(item)
        self.step_list.currentRowChanged.connect(self._guide_step)
        layout.addWidget(self.step_list)
        body = QVBoxLayout(); body.setSpacing(9)
        top = QHBoxLayout(); self.step_counter = _label("01 / 12"); self.step_counter.setStyleSheet("background:#eef1ff;color:#5668c5;padding:3px 7px;border-radius:6px")
        top.addWidget(self.step_counter); top.addStretch(1); body.addLayout(top)
        self.step_heading = _label("", strong=True); body.addWidget(self.step_heading)
        image_tools = QHBoxLayout(); image_tools.setSpacing(10)
        self.image_caption = _label("原始截图 · 重点区域", muted=True)
        image_tools.addWidget(self.image_caption); image_tools.addStretch(1)
        self.hints_check = QCheckBox("点击提示")
        self.hints_check.setChecked(True)
        self.hints_check.toggled.connect(self._toggle_guide_hints)
        image_tools.addWidget(self.hints_check)
        self.full_image_button = _button("查看完整截图")
        self.full_image_button.clicked.connect(self._toggle_full_guide_image)
        image_tools.addWidget(self.full_image_button)
        self.zoom_image_button = _button("放大查看")
        self.zoom_image_button.clicked.connect(self._show_image_zoom)
        image_tools.addWidget(self.zoom_image_button)
        body.addLayout(image_tools)
        self.guide_image = QLabel(); self.guide_image.setAlignment(Qt.AlignmentFlag.AlignCenter); self.guide_image.setMinimumHeight(180); self.guide_image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); self.guide_image.setStyleSheet("background:white;border:1px solid #e1e7f0;border-radius:10px;padding:10px")
        body.addWidget(self.guide_image)
        self.step_actions = _label("", muted=False)
        self.step_actions.setTextFormat(Qt.TextFormat.RichText)
        self.step_actions.setOpenExternalLinks(True)
        self.step_actions.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.step_actions.setWordWrap(True)
        self.step_actions.setStyleSheet("background:#eef1ff;color:#415187;padding:11px;border-radius:9px")
        body.addWidget(self.step_actions)
        self.step_detail = _label("", muted=True); self.step_detail.setWordWrap(True); body.addWidget(self.step_detail)
        nav = QHBoxLayout(); self.prev_step = _button("上一步"); self.next_step = _button("下一步 →", primary=True); self.prev_step.clicked.connect(lambda: self._guide_step(self._guide_index - 1)); self.next_step.clicked.connect(lambda: self._guide_step(self._guide_index + 1)); nav.addWidget(self.prev_step); nav.addStretch(1); nav.addWidget(self.next_step); body.addLayout(nav)
        layout.addLayout(body, 1)
        self.step_list.setCurrentRow(0)
        return page

    def _build_connect_guide(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0)
        card, cl = _card("连接与绑定", "回到接入设置填写凭据，验证成功后绑定私聊或群聊。")
        cl.addWidget(_label("私聊：向机器人发送六位绑定码。群聊：先将机器人加入群，再 @机器人并发送绑定码。", muted=True))
        open_settings = _button("打开接入设置", primary=True); open_settings.clicked.connect(lambda: self._show_page("setup")); cl.addWidget(open_settings)
        layout.addWidget(card); layout.addStretch(1); return page

    def _build_test_guide(self):
        page = QWidget(); layout = QVBoxLayout(page); layout.setContentsMargins(0, 0, 0, 0)
        card, cl = _card("确认文字和图片都能收到", "最后一步")
        for title, detail in (("1 发送一次图文测试", "默认附带 FRLG 火稚鸡图标。"), ("2 在 QQ 中核对内容", "检查私聊或群聊里是否同时出现文字和图片。"), ("3 启用自动通知", "任务结束和异常停止时自动推送。")):
            cl.addWidget(_label(title, strong=True)); cl.addWidget(_label(detail, muted=True))
        button = _button("去发送图文测试", primary=True); button.clicked.connect(self._send_test); cl.addWidget(button)
        layout.addWidget(card); layout.addStretch(1); return page

    def _connect_service(self):
        self.service.changed.connect(self._refresh)
        self.service.records_changed.connect(self._refresh_records)
        self.service.error.connect(lambda message: self._feedback_message(message, error=True))
        self.service.operation_finished.connect(self._operation_finished)
        self.service.setup.binding_changed.connect(self._binding_changed)
        self.service.setup.status.connect(self._status)

    def _show_page(self, page):
        self._page = page
        self.tabs_bar.show()
        self.header_title.setText("QQ 通知")
        self.header_subtitle.setText("任务结束后，在 QQ 查看结果与游戏画面")
        if page == "setup": self.stack.setCurrentWidget(self.setup_page)
        elif page == "rules": self.stack.setCurrentWidget(self.rules_page)
        elif page == "records": self.stack.setCurrentWidget(self.records_page)
        for key, button in self.tab_buttons.items(): button.setChecked(key == page)
        self._refresh()

    def _open_guide(self):
        self.tabs_bar.hide()
        self.header_title.setText("QQ 机器人注册与绑定")
        self.header_subtitle.setText("按步骤操作，可随时返回设置")
        self.stack.setCurrentWidget(self.guide_page)
        for button in self.tab_buttons.values(): button.setChecked(False)
        QTimer.singleShot(0, self._render_guide_image)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "guide_image"):
            QTimer.singleShot(0, self._render_guide_image)

    def _guide_phase(self, index):
        self.guide_stack.setCurrentIndex(index)
        for i in range(3): getattr(self, f"phase_{i}").setChecked(i == index)
        if index == 0: self.step_list.setCurrentRow(self._guide_index)

    def _guide_step(self, index):
        if not self._guide_steps: return
        self._guide_index = max(0, min(len(self._guide_steps) - 1, index))
        self._guide_full_image = False
        self.step_list.blockSignals(True); self.step_list.setCurrentRow(self._guide_index); self.step_list.blockSignals(False)
        step = self._guide_steps[self._guide_index]
        self.step_counter.setText(f"{self._guide_index + 1:02d} / {len(self._guide_steps):02d}")
        self.step_heading.setText(step["title"])
        actions = list(step.get("actions", []))
        if self._guide_index == 0 and actions:
            actions[0] = actions[0].replace(
                "登录 QQ 开放平台",
                f"登录 <a href=\"{QQ_PLATFORM_URL}\" style=\"color:#007f61; text-decoration:underline;\">QQ 开放平台</a>",
            )
        self.step_actions.setText("<br>".join("• " + value for value in actions))
        self.step_detail.setText(step.get("detail", ""))
        self._render_guide_image()
        self.prev_step.setEnabled(self._guide_index > 0); self.next_step.setEnabled(self._guide_index < len(self._guide_steps) - 1)

    def _render_guide_image(self):
        step = self._guide_steps[self._guide_index]
        source = QPixmap(str(step["path"]))
        if source.isNull():
            self.guide_image.clear()
            return
        width, height = source.width(), source.height()
        if self._guide_full_image:
            view = QRect(0, 0, width, height)
            self.image_caption.setText("原始截图 · 完整画面")
            self.full_image_button.setText("返回重点区域")
        else:
            crop = step.get("crop") or [0, 0, width, height]
            view = QRect(int(crop[0]), int(crop[1]), int(crop[2]), int(crop[3])).intersected(source.rect())
            self.image_caption.setText("原始截图 · 重点区域")
            self.full_image_button.setText("查看完整截图")
        image = source.copy(view)
        if self._guide_show_hints and step.get("focus"):
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor("#d77817"), max(3, round(min(image.width(), image.height()) / 220)))
            painter.setPen(pen)
            painter.setBrush(QColor(235, 161, 45, 35))
            for x, y, w, h in step["focus"]:
                rect = QRect(int(x - view.x()), int(y - view.y()), int(w), int(h)).intersected(image.rect())
                if not rect.isEmpty(): painter.drawRoundedRect(rect, 5, 5)
            painter.end()
        target_width = max(420, min(720, self.guide_image.parentWidget().width() - 8))
        # Keep the focus crop large enough to read while reserving room for
        # the instruction and navigation rows below it.
        target_height = max(320, min(520, self.guide_stack.height() - 100))
        self.guide_image.setPixmap(image.scaled(target_width, target_height,
                                                Qt.AspectRatioMode.KeepAspectRatio,
                                                Qt.TransformationMode.SmoothTransformation))

    def _toggle_full_guide_image(self):
        self._guide_full_image = not self._guide_full_image
        self._render_guide_image()

    def _toggle_guide_hints(self, enabled):
        self._guide_show_hints = bool(enabled)
        self._render_guide_image()

    def _show_image_zoom(self):
        step = self._guide_steps[self._guide_index]
        source = QPixmap(str(step["path"]))
        dialog = ThemedDialog(self)
        dialog.setWindowTitle(f"{step['title']} · 原始截图")
        dialog.resize(1000, 760)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        scroll = QScrollArea(); scroll.setWidgetResizable(False); scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image = QLabel(); image.setPixmap(source); image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidget(image)
        layout.addWidget(scroll, 1)
        close = _button("关闭"); close.clicked.connect(dialog.close); layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _toggle_secret(self, button):
        visible = self.secret.echoMode() == QLineEdit.EchoMode.Password
        self.secret.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        button.setText("隐藏" if visible else "显示")

    def _save_credentials(self):
        self.service.update(app_id=self.app_id.text().strip(), secret=self.secret.text().strip(), remember_secret=self.remember.isChecked())

    def _verify(self):
        try: self._save_credentials(); self.service.verify()
        except Exception as exc: self._feedback_message(str(exc), error=True)

    def _bind(self, kind):
        try:
            self._save_credentials()
            if not self.service.verified: raise QQError("请先验证凭据，再绑定接收方。")
            self.service.bind(kind)
        except Exception as exc: self._feedback_message(str(exc), error=True)

    def _send_test(self):
        try: self._save_credentials(); self.service.send_test()
        except Exception as exc: self._feedback_message(str(exc), error=True)

    def _update(self, **values):
        try: self.service.update(**values)
        except Exception as exc: self._feedback_message(str(exc), error=True); self._refresh()

    def _binding_changed(self, kind, code, seconds, generation):
        if code:
            target = "私聊" if kind == "user" else "群聊"
            self.binding_status.setText(f"{target}绑定码：{code}　剩余 {seconds} 秒（到期自动换码）")
            self.binding_status.setStyleSheet("color:#5367bd;font-weight:600")
        elif not self.service.setup.busy:
            self.binding_status.setText("绑定后会显示 60 秒验证码，并自动换码。")
            self.binding_status.setStyleSheet("")

    def _status(self, message): self._feedback_message(message)

    def _operation_finished(self, operation, ok, message):
        if operation == "verify": self.credential_status.setText(message)
        elif operation == "test": self.test_status.setText(message)
        self._feedback_message(message, error=not ok and not message.startswith("操作已取消"))
        self._refresh()

    def _feedback_message(self, message, *, error=False):
        self.feedback.setText(message)
        self.feedback.setProperty("error", error)
        self.feedback.style().unpolish(self.feedback); self.feedback.style().polish(self.feedback)

    def _refresh_preview(self):
        values = (("命中", "结果：已完成\n目标：目标宝可梦\n详情：已找到符合条件的结果。"), ("未确认", "结果：已完成\n详情：运行结束，但日志未确认命中。"), ("异常", "结果：失败\n详情：运行器在采集阶段异常停止。"))
        self.preview.setText(values[self.preview_kind.currentIndex()][1] + "\n结束时间：2026-09-20 15:30:00")

    def _refresh_records(self):
        self.records.setRowCount(0)
        for record in self.service.records:
            row = self.records.rowCount(); self.records.insertRow(row)
            for col, value in enumerate((record.time, record.event, record.recipient, ("成功 · " if record.success else "失败 · ") + record.detail)):
                self.records.setItem(row, col, QTableWidgetItem(value))

    def _refresh(self):
        settings = self.service.settings
        widgets = ((self.app_id, settings.app_id), (self.secret, settings.secret))
        for widget, value in widgets:
            if widget.text() != value: widget.setText(value)
        self.remember.setChecked(settings.remember_secret)
        self.enable_check.blockSignals(True)
        self.enable_check.setChecked(settings.enabled)
        self.enable_check.setText("已启用" if settings.enabled else "未启用")
        self.enable_check.blockSignals(False)
        for check, value in ((self.user_check, settings.user_enabled), (self.group_check, settings.group_enabled)):
            check.blockSignals(True); check.setChecked(value); check.blockSignals(False)
        self.user_openid.setText(settings.user_openid or "尚未绑定")
        self.group_openid.setText(settings.group_openid or "尚未绑定")
        self.rule_completed.blockSignals(True); self.rule_completed.setChecked(settings.on_completed); self.rule_completed.blockSignals(False)
        self.rule_failed.blockSignals(True); self.rule_failed.setChecked(settings.on_failed); self.rule_failed.blockSignals(False)
        self.rule_stopped.blockSignals(True); self.rule_stopped.setChecked(settings.on_stopped); self.rule_stopped.blockSignals(False)
        self.attach_image.blockSignals(True); self.attach_image.setChecked(settings.attach_image); self.attach_image.blockSignals(False)
        self.credential_status.setText("凭据已验证" if self.service.verified else "尚未验证")
        self._refresh_records(); self._refresh_preview()
        if self.service.last_error and not self.service.operation: self._feedback_message(self.service.last_error, error=True)

    def closeEvent(self, event):
        self.reject()
        event.accept()

    def done(self, result):
        # Escape/reject and window close all finish through QDialog.done().
        if self.service.setup.busy:
            self.service.setup.cancel()
        try:
            self._save_credentials()
        except Exception:
            pass
        self.closed.emit()
        super().done(result)
