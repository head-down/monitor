"""人脸检测 + 确认状态机模块。

接口:
    FaceDetector(net, confirm_frames=8, dnn_skip=3, threshold=0.4)
    detector.process_frame(image) -> DetectionState

FaceDetector 将 DNN 推理与连续帧确认封装为单一入口：
- 每 dnn_skip 帧跑一次 OpenCV DNN 人脸检测
- 连续 confirm_frames 帧状态一致才触发状态切换
- 调用方只需检查 DetectionState.edge_rising 决定是否触发操作
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

    将检测（DNN 推理）与确认（连续 N 帧状态一致才切换）封装为单一入口。
    调用方只需检查 state.edge_rising 来决定是否触发切屏，
    无需维护额外状态变量或记住两步调用顺序。
    """
    def __init__(self, net, confirm_frames=8, dnn_skip=3, threshold=0.4):
        self._net = net
        self._confirm_frames = confirm_frames
        self._dnn_skip = dnn_skip
        self._threshold = threshold
        self._face_count = 0
        self._is_risky = False
        self._confirm_counter = 0
        self._frame_idx = 0

    def process_frame(self, image):
        self._frame_idx += 1
        if self._frame_idx % self._dnn_skip == 0:
            blob = cv2.dnn.blobFromImage(cv2.resize(image, (300, 300)), 1.0,
                                          (300, 300), (104.0, 177.0, 123.0))
            self._net.setInput(blob)
            detections = self._net.forward()
            self._face_count = 0
            for i in range(0, detections.shape[2]):
                if detections[0, 0, i, 2] > self._threshold:
                    self._face_count += 1

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
