"""车端硬件抽象与假实现（计划 0016 阶段 A；底盘接口为阶段 C）。

硬件还没定型：相机和二维码标签有真实实现；云台、补光、编码器、底盘只定义接口，
真实驱动类抛出明确的 NotImplementedError，等器件选型后再接。
假实现供 ``--fake`` 链路验收和单测使用，不代表任何真实硬件参数。
"""
from __future__ import annotations

import io
from collections.abc import Callable, Iterable
from typing import Protocol

# ---------------------------------------------------------------- 接口


class Camera(Protocol):
    def capture(self) -> bytes: ...
    def close(self) -> None: ...


class Gimbal(Protocol):
    def move(self, pitch_deg: float, yaw_deg: float) -> None: ...


class Light(Protocol):
    def set(self, on: bool) -> None: ...


class Odometer(Protocol):
    def distance_m(self) -> float: ...


class TagReader(Protocol):
    def read(self, image: bytes) -> list[str]: ...


class Drive(Protocol):
    """按计划执行时开到第 ``row_no`` 垄、行内位置 ``chainage_m`` 处停下（计划 0016 阶段 C）。

    换垄、掉头、对齐都是底盘控制器的事；到位后里程计读数应接近该垄的行内位置，余下误差由标签校正。
    """

    def go_to(self, row_no: int, chainage_m: float) -> None: ...


# ---------------------------------------------------------------- 假实现

FAKE_KINDS = ("normal", "blurry", "overexposed", "dark", "backlit")


class FakeCamera:
    """生成合成图：按脚本依次产出 normal / blurry / overexposed / dark / backlit。

    脚本用完后一直产出 normal。normal 是带纹理的绿色棋盘格，能通过 iq-rule-v1；
    其余四种分别触发对应的质量原因。``fail_on`` 里的第几次调用（从 1 起）抛异常，模拟拍照失败。
    """

    def __init__(
        self, width: int, height: int, script: Iterable[str] = (), *, fail_on: Iterable[int] = (),
    ):
        from PIL import Image

        unknown = [kind for kind in script if kind not in FAKE_KINDS]
        if unknown:
            raise ValueError(f"FakeCamera 不认识的图像类型：{unknown}")
        self.width = width
        self.height = height
        self._script = list(script)
        self._fail_on = set(fail_on)
        self._index = 0
        self._image_type = Image
        self.calls = 0

    def capture(self) -> bytes:
        self.calls += 1
        if self.calls in self._fail_on:
            raise RuntimeError(f"假相机第 {self.calls} 次拍照失败（脚本注入）")
        kind = self._script.pop(0) if self._script else "normal"
        image = self._render(kind)
        self._index += 1
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def _render(self, kind: str):
        from PIL import ImageDraw, ImageFilter

        w, h = self.width, self.height
        if kind == "overexposed":
            return self._image_type.new("RGB", (w, h), (255, 255, 255))
        if kind == "dark":
            return self._image_type.new("RGB", (w, h), (3, 3, 3))
        if kind == "backlit":
            image = self._image_type.new("RGB", (w, h), (40, 45, 35))
            ImageDraw.Draw(image).rectangle([0, 0, w, h // 3], fill=(255, 255, 255))
            return image
        # normal / blurry：棋盘格叶面纹理，颜色随帧号微变
        cell = max(4, min(w, h) // 30)
        dark = (30 + self._index % 40, 90 + (self._index * 7) % 70, 25 + self._index % 30)
        light = (dark[0] + 60, min(255, dark[1] + 90), dark[2] + 50)
        image = self._image_type.new("RGB", (w, h), dark)
        draw = ImageDraw.Draw(image)
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                if (x // cell + y // cell) % 2:
                    draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=light)
        if kind == "blurry":
            image = image.filter(ImageFilter.GaussianBlur(cell * 1.5))
        return image

    def close(self) -> None:
        pass


class FakeGimbal:
    """记录每次 move 调用，供测试断言仰角序列。"""

    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []

    def move(self, pitch_deg: float, yaw_deg: float) -> None:
        self.moves.append((pitch_deg, yaw_deg))


class FakeLight:
    def __init__(self) -> None:
        self.states: list[bool] = []

    def set(self, on: bool) -> None:
        self.states.append(on)

    @property
    def on(self) -> bool:
        return bool(self.states and self.states[-1])


class FakeOdometer:
    """每调用一次就前进一个步长（第一次返回 0）。"""

    def __init__(self, step_m: float, start_m: float = 0.0):
        self.step_m = step_m
        self._next = start_m

    def distance_m(self) -> float:
        value = self._next
        self._next += self.step_m
        return round(value, 3)


class FakeTagReader:
    """每 N 次调用返回一次配置好的株号（依次轮换），其余调用返回空列表。

    给了 ``source`` 时改为每 N 次读一次「车此刻所在的株」（``source()`` 返回 None 表示这里没有标签）。
    """

    def __init__(self, tags: Iterable[str], every: int = 1, *, source: Callable[[], str | None] | None = None):
        if every < 1:
            raise ValueError("every 必须 ≥1")
        self._tags = list(tags)
        self.every = every
        self.source = source
        self._calls = 0
        self._next_tag = 0

    def read(self, image: bytes) -> list[str]:
        self._calls += 1
        if self._calls % self.every:
            return []
        if self.source is not None:
            tag = self.source()
            return [tag] if tag else []
        if not self._tags:
            return []
        tag = self._tags[self._next_tag % len(self._tags)]
        self._next_tag += 1
        return [tag]


class FakeDrive:
    """假底盘兼假里程计：``go_to`` 直接到位；里程读数 = 真实行内位置 × ``scale``（<1 模拟打滑少计）。"""

    def __init__(self, scale: float = 1.0):
        if scale <= 0:
            raise ValueError("scale 必须大于 0")
        self.scale = scale
        self.row_no: int | None = None
        self.position_m = 0.0
        self.visits: list[tuple[int, float]] = []

    def go_to(self, row_no: int, chainage_m: float) -> None:
        self.row_no, self.position_m = row_no, chainage_m
        self.visits.append((row_no, chainage_m))

    def distance_m(self) -> float:
        return round(self.position_m * self.scale, 3)


# ---------------------------------------------------------------- 真实实现


class CameraCapture:
    """USB 摄像头采集器，显式释放 OpenCV 资源。

    OpenCV（V4L2）默认在驱动里缓冲若干帧：按间隔拍照时直接 read() 拿到的是
    缓冲里的旧帧，照片与记录的时间/位置对不上（小车行进时偏差 = 车速 × 间隔），
    高密度采样的空间对应关系就失效了。每次拍照前先丢弃缓冲帧。
    """

    STALE_FRAMES = 4  # 常见 V4L2 缓冲深度；缓冲可设为 1 时多丢几帧只多等几十毫秒

    def __init__(self, index: int, width: int, height: int):
        import cv2  # 延迟导入，--fake 不需要 OpenCV

        self._cv2 = cv2
        self._width = width
        self._height = height
        self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            self._cap.release()
            raise RuntimeError(f"打不开摄像头 index={index}，确认已连接且未被占用")
        # 部分后端不支持该属性，返回 False 时仍靠 capture() 里的丢帧兜底
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def capture(self) -> bytes:
        for _ in range(self.STALE_FRAMES):
            self._cap.grab()
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("读帧失败，检查摄像头是否被占用")
        frame = self._cv2.resize(frame, (self._width, self._height))
        ok, encoded = self._cv2.imencode(
            ".jpg", frame, [self._cv2.IMWRITE_JPEG_QUALITY, 85],
        )
        if not ok:
            raise RuntimeError("JPEG 编码失败")
        return encoded.tobytes()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class QrTagReader:
    """用 OpenCV 自带的二维码解码器读株号标签（标签内容 = 株号字符串，计划 0013）。"""

    def __init__(self) -> None:
        import cv2

        self._cv2 = cv2
        self._detector = cv2.QRCodeDetector()

    def read(self, image: bytes) -> list[str]:
        import numpy as np  # opencv-python-headless 自带 numpy

        frame = self._cv2.imdecode(np.frombuffer(image, dtype=np.uint8), self._cv2.IMREAD_COLOR)
        if frame is None:
            return []
        ok, texts, _points, _ = self._detector.detectAndDecodeMulti(frame)
        if not ok:
            return []
        return [text for text in texts if text]


class _NotWired:
    """硬件未定型时的真实驱动占位：构造即报错，避免在没有云台/补光/编码器时假装成功。"""

    part = "硬件"

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            f"{self.part}驱动尚未接入（硬件未定型，计划 0016 只留接口）；无硬件时用 --fake 验证链路",
        )


class ServoGimbal(_NotWired):
    part = "云台"

    def move(self, pitch_deg: float, yaw_deg: float) -> None:  # pragma: no cover
        raise NotImplementedError


class GpioLight(_NotWired):
    part = "补光灯"

    def set(self, on: bool) -> None:  # pragma: no cover
        raise NotImplementedError


class EncoderOdometer(_NotWired):
    part = "编码器"

    def distance_m(self) -> float:  # pragma: no cover
        raise NotImplementedError


class ChassisDrive(_NotWired):
    part = "底盘"

    def go_to(self, row_no: int, chainage_m: float) -> None:  # pragma: no cover
        raise NotImplementedError
