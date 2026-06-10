"""人脸检测 + 确认状态机模块。

接口:
    FaceDetector(net, confirm_frames=8, dnn_skip=3, threshold=0.4, max_errors=10)
    detector.process_frame(image) -> DetectionState
    detector.is_healthy() -> bool

FaceDetector 将 DNN 推理与连续帧确认封装为单一入口：
- 每 dnn_skip 帧跑一次 OpenCV DNN 人脸检测
- 连续 confirm_frames 帧状态一致才触发状态切换
- DNN 异常被内部吸收，调用方无需关心错误处理
- is_healthy() 暴露检测器健康状态，供上层降级决策
"""
import cv2
from dataclasses import dataclass


@dataclass
class DetectionState:
    """process_frame() 的返回值，封装一次检测的完整快照。"""
    face_count: int       # 当前帧检测到的人脸数
    is_risky: bool         # 持续状态：>1 人已确认
    edge_rising: bool      # 上升沿：safe → risky 的瞬间（触发用）
    edge_falling: bool     # 下降沿：risky → safe 的瞬间


class FaceDetector:
    """人脸检测 + 确认状态机。

    接口：
        process_frame(image) -> DetectionState
        is_healthy() -> bool

    将检测（DNN 推理）与确认（连续 N 帧状态一致才切换）封装为单一入口。
    调用方只需检查 state.edge_rising 来决定是否触发切屏，
    无需维护额外状态变量或记住两步调用顺序。

    DNN 推理异常由内部吸收：单次异常使用上次有效值继续，
    连续异常超过 max_errors 后 is_healthy() 返回 False。
    """
    def __init__(self, net, confirm_frames=8, dnn_skip=3, threshold=0.4, max_errors=10):
        self._net = net
        self._confirm_frames = confirm_frames
        self._dnn_skip = dnn_skip
        self._threshold = threshold
        self._max_errors = max_errors
        self._face_count = 0
        self._is_risky = False
        self._confirm_counter = 0
        self._frame_idx = 0
        self._error_count = 0          # 累计 DNN 错误次数
        self._healthy = True           # 健康标志

    def process_frame(self, image):
        """处理一帧图像，返回检测状态快照。

        DNN 推理异常时返回上次有效状态，不抛出异常。
        """
        self._frame_idx += 1
        if self._frame_idx % self._dnn_skip == 0:
            try:
                blob = cv2.dnn.blobFromImage(cv2.resize(image, (300, 300)), 1.0,
                                              (300, 300), (104.0, 177.0, 123.0))
                self._net.setInput(blob)
                detections = self._net.forward()
                self._face_count = 0
                for i in range(0, detections.shape[2]):
                    if detections[0, 0, i, 2] > self._threshold:
                        self._face_count += 1
                self._error_count = 0  # 成功时重置错误计数
            except Exception:
                self._error_count += 1
                if self._error_count >= self._max_errors:
                    self._healthy = False
                # 使用上次有效的 face_count 继续

        alone = (self._face_count <= 1)
        target = not alone
        edge_rising = False
        edge_falling = False

        if target == self._is_risky:
            self._confirm_counter = 0
        else:
            self._confirm_counter += 1
            if self._confirm_counter >= self._confirm_frames:
                # 状态确认切换
                if target and not self._is_risky:
                    edge_rising = True
                elif not target and self._is_risky:
                    edge_falling = True
                self._is_risky = target
                self._confirm_counter = 0

        return DetectionState(
            face_count=self._face_count,
            is_risky=self._is_risky,
            edge_rising=edge_rising,
            edge_falling=edge_falling,
        )

    def is_healthy(self):
        """检测器是否健康。

        DNN 连续错误超过 max_errors 后返回 False，
        上层可据此降级处理（如停止监控并通知用户）。
        """
        return self._healthy
