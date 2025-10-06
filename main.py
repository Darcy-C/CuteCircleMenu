import sys
import json
import math
import subprocess
import faulthandler
from functools import partial

from pynput import keyboard
from PySide6.QtGui import (
    QPen,
    QColor,
    QCursor,
    QPixmap,
    QPainter,
    QTransform,
)
from PySide6.QtCore import (
    Qt,
    QUrl,
    QRect,
    QSize,
    QPoint,
    QTimer,
    Signal,
    QObject,
    QThread,
    QEasingCurve,
    QVariantAnimation,
)
from PySide6.QtWidgets import (
    QFrame,
    QApplication,
)
from PySide6.QtMultimedia import QSoundEffect

# --- 这里是监听的Alt按键, 这里为了防止误触, 只识别右侧的Alt (Mac的Alt是Option)
KEY_ALTS = [
    # keyboard.Key.alt,
    # keyboard.Key.alt_l,
    keyboard.Key.alt_r,
]

# --- 决定是否使用触发音效, 默认关闭
USE_SOUND_EFFECT = False

# --- 读取全局设置相关代码
config = json.loads(open("./assets/config.json").read())


def run_quicker_action(action_id: str):
    # 这里做自己的触发设置, 这里只演示 Windows 端, 其他平台自行编写逻辑
    if sys.platform == "win32":
        subprocess.run(
            [
                r"C:\Program Files\Quicker\QuickerStarter.exe",
                f"runaction:{action_id}",
            ]
        )


# 这个打开可以方便看到 segfault 时所处的python行, 非必要
faulthandler.enable()


# 我们这里用的 pynput, 这里包进 QObject 利用 Signal 进入 Qt 的事件系统
class ListenerWorker(QObject):
    on_pressed = Signal()
    on_released = Signal()

    def on_press(self, key):
        if key in KEY_ALTS:
            self.on_pressed.emit()

    def on_release(self, key):
        if key in KEY_ALTS:
            self.on_released.emit()

    def run(self):
        with keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release,
        ) as listener:
            listener.join()


class Window(QFrame):
    def __init__(self):
        super().__init__()

        self._hit_test_cache: list[QRect | None] = [None for _ in range(9)]
        self._hovered_radius: list[int] = [130 for _ in range(9)]
        self._anim_for_icons: list[QVariantAnimation] = []
        for i in range(8):
            _anim = QVariantAnimation(self)
            _anim.setEasingCurve(QEasingCurve.Type.InOutSine)
            _anim.setDuration(200)
            _anim.valueChanged.connect(partial(self._anim_set_radius, i))
            self._anim_for_icons.append(_anim)

        self._index_hovered: int | None = None
        self._openness: float = 0.0

        self.setMouseTracking(True)

        self.setFixedSize(600, 600)
        self.setWindowFlags(
            Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        if USE_SOUND_EFFECT:
            # fmt: off
            self._on_hover_media = QUrl.fromLocalFile("./assets/sounds/on_hover.wav")
            self._on_trigger_media = QUrl.fromLocalFile("./assets/sounds/on_trigger.wav")
            self._on_open_media = QUrl.fromLocalFile("./assets/sounds/on_open.wav")
            # fmt: on

        self._assets = [
            QPixmap(f"./assets/images/{i}.png").scaledToHeight(
                58, Qt.TransformationMode.SmoothTransformation
            )
            for i in range(1, 10)
        ]
        degrees = -90
        transform = QTransform().rotate(degrees)
        self._assets[-1] = self._assets[-1].transformed(
            transform, Qt.TransformationMode.SmoothTransformation
        )

        timer = QTimer(self)
        timer.setInterval(10)
        timer.timeout.connect(self._on_update)
        timer.start()

        self._openness_anim = QVariantAnimation()
        self._openness_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._openness_anim.setDuration(300)
        self._openness_anim.valueChanged.connect(self._on_openness_anim_value_changed)

        self.listener_worker = ListenerWorker()
        self.listener_worker.on_pressed.connect(self._on_listener_pressed)
        self.listener_worker.on_released.connect(self._on_listener_released)
        self.listener_worker_thread = QThread()
        self.listener_worker.moveToThread(self.listener_worker_thread)
        self.listener_worker_thread.started.connect(self.listener_worker.run)
        self.listener_worker_thread.start()

        self.sound_debounce_timer = QTimer()
        self.sound_debounce_timer.setInterval(100)
        self.sound_debounce_timer.setSingleShot(True)
        if USE_SOUND_EFFECT:
            self.sound_debounce_timer.timeout.connect(self.play_sound_effect)

    def _on_update(self):
        if self._openness > 0.9:
            self._check_mouse_pos()
        self.update()

    def _on_listener_pressed(self):
        self._openness_anim.stop()
        self.move(
            QCursor.pos()
            - QPoint(
                self.width() // 2,
                self.height() // 2,
            )
        )
        self.show()
        self._openness_anim.setStartValue(self._openness)
        self._openness_anim.setEndValue(1.0)
        self._openness_anim.start()
        if USE_SOUND_EFFECT:
            self.play_sound_effect(self._on_open_media)

    def play_sound_effect(self, media=None):
        if media is None:
            media = self._on_hover_media
        sound_effect = QSoundEffect(self)
        sound_effect.setSource(media)
        sound_effect.play()

    def _on_listener_released(self):
        self._openness_anim.stop()
        self._openness_anim.setStartValue(self._openness)
        self._openness_anim.setEndValue(0.0)
        self._openness_anim.start()

        # 这里的话 None 就是鼠标没有在任何一个预定的图标上, 这里 8 是中间的那个, 我们不做处理
        if self._index_hovered not in (None, 8):
            if USE_SOUND_EFFECT:
                self.play_sound_effect(self._on_trigger_media)
            print(self._index_hovered, "图标触发")
            index_s = str(self._index_hovered)
            action_id = config["action_ids"][index_s]
            if action_id:
                run_quicker_action(action_id)

    def _on_openness_anim_value_changed(self, new_value: float):
        self._openness = new_value
        self.update()

    def _check_mouse_pos(self):
        _pos = self.mapFromGlobal(QCursor.pos())
        MAX_RADIUS = 150
        found = False
        if self._hit_test_cache[0] is None:
            return
        for i, rect in enumerate(self._hit_test_cache):
            if i >= 8:
                break
            if rect is None:
                continue
            current = self._hovered_radius[i]
            anim = self._anim_for_icons[i]

            if rect.contains(_pos):
                self._index_hovered = i
                found = True

                if current != MAX_RADIUS:
                    anim.setStartValue(current)
                    anim.setEndValue(MAX_RADIUS)
                    anim.start()
                    self.sound_debounce_timer.start()

            # 我们这里用2点距离判断是否远离该图标, 只有足够远才恢复原来的位置
            elif (_pos - rect.center()).manhattanLength() > 120:
                if current != 130:
                    anim.setStartValue(current)
                    anim.setEndValue(130)
                    anim.start()

        if not found:
            self._index_hovered = None

    def _anim_set_radius(self, i: int, new_value: float):
        self._hovered_radius[i] = new_value
        self.update()

    def paintEvent(self, ev):
        # 整个圆盘的直径
        SIZE = 420

        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.LosslessImageRendering)

        painter.setOpacity(self._openness)
        border_width = min(10.0, 10.0 * self._openness * 2)
        border_pen = QPen("#E9FF97")
        border_pen.setWidthF(border_width)
        painter.setPen(border_pen)
        painter.setBrush(QColor("#FFD18E"))
        painter.drawEllipse(
            QPoint(
                self.width() // 2,
                self.height() // 2,
            ),
            (SIZE // 2 - border_width * 2) * self._openness,
            (SIZE // 2 - border_width * 2) * self._openness,
        )

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.setBrush(Qt.GlobalColor.transparent)
        painter.drawEllipse(
            QPoint(
                self.width() // 2,
                self.height() // 2,
            ),
            SIZE // 8,
            SIZE // 8,
        )
        painter.drawEllipse(
            self.mapFromGlobal(QCursor.pos()),
            60,
            60,
        )
        painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#E9FF97"))
        painter.drawEllipse(
            self.mapFromGlobal(QCursor.pos()),
            55,
            55,
        )

        self._draw_icons(painter)

        painter.end()

    def _draw_icons(self, painter: QPainter):
        item_length = 8
        center_x = self.width() // 2
        center_y = self.height() // 2

        degrees = 90 * self._openness
        transform = QTransform().rotate(degrees)
        center_asset = (
            self._assets[-1]
            .transformed(transform, Qt.TransformationMode.SmoothTransformation)
            .scaledToHeight(120 - 62 * self._openness)
        )
        _top_left_point = QPoint(
            center_x - center_asset.width() // 2,
            center_y - center_asset.height() // 2,
        )
        painter.drawPixmap(
            _top_left_point,
            center_asset,
        )
        self._hit_test_cache[-1] = QRect(_top_left_point, center_asset.size())

        for i in range(item_length):
            angle = i * (360 / item_length)

            radius = self._hovered_radius[i] * self._openness
            x = center_x + radius * math.cos(math.radians(angle))
            y = center_y + radius * math.sin(math.radians(angle))

            # painter.setBrush(Qt.blue)
            # painter.drawEllipse(QPoint(int(x), int(y)), 10, 10)
            asset = self._assets[i].scaledToHeight(int(58 * self._openness))
            _top_left_point = QPoint(
                int(x) - asset.width() // 2,
                int(y) - asset.height() // 2,
            )
            painter.drawPixmap(
                _top_left_point,
                asset,
            )
            self._hit_test_cache[i] = QRect(
                _top_left_point - QPoint(20, 20),
                asset.size() + QSize(40, 40),
            )


if __name__ == "__main__":
    print("--- 右侧Alt按下后移动鼠标打开可爱圆盘啦(Mac为右侧Option) ---")
    q_app = QApplication([])

    w = Window()
    # w.show()

    q_app.exec()
