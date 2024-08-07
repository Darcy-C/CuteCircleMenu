from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtMultimedia import QSoundEffect

from pynput import mouse, keyboard

import math
from functools import partial
import json
import subprocess

KEY_ALTS = [
    keyboard.Key.alt,
    keyboard.Key.alt_l,
    keyboard.Key.alt_r,
]


config = json.loads(open("./assets/config.json").read())


def run_quicker_action(action_id: str):
    subprocess.run(
        [
            "C:\Program Files\Quicker\QuickerStarter.exe",
            f"runaction:{action_id}",
        ]
    )


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

        self._hit_test_cache: list[QRect] = [None for i in range(9)]
        self._hovered_radius: list[int] = [130 for i in range(9)]
        self._index_hovered: int | None = None
        self._openness = 0.0

        self.setMouseTracking(True)

        self.setFixedSize(420, 420)
        self.setWindowFlags(
            Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._on_hover_media = QUrl.fromLocalFile("./assets/sounds/on_hover.wav")
        self._on_trigger_media = QUrl.fromLocalFile("./assets/sounds/on_trigger.wav")
        self._on_open_media = QUrl.fromLocalFile("./assets/sounds/on_open.wav")

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

        self.openness_anim = QVariantAnimation()
        self.openness_anim.setStartValue(0.0)
        self.openness_anim.setEndValue(1.0)
        self.openness_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.openness_anim.setDuration(300)
        self.openness_anim.valueChanged.connect(self._on_openness_anim_value_changed)
        # self.openness_anim.start()

        # timer = QTimer(self)
        # timer.setInterval(500)
        # timer.timeout.connect(self._on_test)
        # timer.start()

        self.listener_worker = ListenerWorker()
        self.listener_worker.on_pressed.connect(self._on_listener_pressed)
        self.listener_worker.on_released.connect(self._on_listener_released)
        self.listener_worker_thread = QThread()
        self.listener_worker.moveToThread(self.listener_worker_thread)
        self.listener_worker_thread.started.connect(self.listener_worker.run)
        self.listener_worker_thread.start()

        self.debounce_timer = QTimer()
        self.debounce_timer.setInterval(100)
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.timeout.connect(self.play_sound_effect)

    def _on_update(self):
        if self._openness > 0.9:
            self._check_mouse_pos()
        self.update()

    def _on_listener_pressed(self):
        if self._openness != 0.0:
            return
        self.openness_anim.setDirection(QAbstractAnimation.Direction.Forward)
        self.move(
            QCursor.pos()
            - QPoint(
                self.width() // 2,
                self.height() // 2,
            )
        )
        self.show()
        self.openness_anim.start()
        self.play_sound_effect(self._on_open_media)

    def play_sound_effect(self, media=None):
        if media is None:
            media = self._on_hover_media
        sound_effect = QSoundEffect(self)
        sound_effect.setSource(media)
        sound_effect.play()

    def _on_listener_released(self):
        self.openness_anim.setDirection(QAbstractAnimation.Direction.Backward)
        self.openness_anim.start()
        print(self._index_hovered, "triggered")
        if self._index_hovered not in [None, 8]:
            self.play_sound_effect(self._on_trigger_media)
            index_s = str(self._index_hovered)
            action_id = config["action_ids"][index_s]
            if action_id:
                run_quicker_action(action_id)

    def _on_test(self):
        if self.openness_anim.direction() == QAbstractAnimation.Direction.Backward:
            self.openness_anim.setDirection(QAbstractAnimation.Direction.Forward)
        else:
            self.openness_anim.setDirection(QAbstractAnimation.Direction.Backward)
        self.openness_anim.start()

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
            anim = QVariantAnimation(self)
            anim.setEasingCurve(QEasingCurve.Type.InOutSine)
            anim.setDuration(50)
            anim.valueChanged.connect(partial(self._anim_set_radius, i))
            current = self._hovered_radius[i]

            if rect.contains(_pos):
                self._index_hovered = i
                found = True

                if current != MAX_RADIUS:
                    anim.setStartValue(current)
                    anim.setEndValue(MAX_RADIUS)
                    anim.start()
                    self.debounce_timer.start()

            else:
                if current != 130:
                    anim.setStartValue(current)
                    anim.setEndValue(130)
                    anim.start()
        if not found:
            self._index_hovered = None

    def _anim_set_radius(self, i, new_value):
        self._hovered_radius[i] = new_value
        self.update()

    def paintEvent(self, ev):
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
            (self.width() // 2 - border_width * 2) * self._openness,
            (self.height() // 2 - border_width * 2) * self._openness,
        )

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.setBrush(Qt.GlobalColor.transparent)
        painter.drawEllipse(
            QPoint(
                self.width() // 2,
                self.height() // 2,
            ),
            self.width() // 8,
            self.height() // 8,
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
    q_app = QApplication([])

    w = Window()
    # w.show()

    q_app.exec()
