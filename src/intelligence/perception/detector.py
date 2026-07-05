"""
Computer Vision: YOLO Object Detection wrapper.
Supports ONNX/TensorRT deployment for edge devices.
"""

import os
import logging
import numpy as np
from dataclasses import dataclass
from typing import Tuple, List, Optional

logger = logging.getLogger("sentinel.perception.detector")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV not available. Perception will not run.")

try:
    import onnxruntime as ort
    ORT_AVAILABLE = True
except ImportError:
    ORT_AVAILABLE = False
    logger.warning("ONNX Runtime not available. Perception will not run.")

@dataclass
class Detection:
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2
    class_id: int
    class_name: str
    confidence: float
    frame_id: int

class ObjectDetector:
    """YOLO-based object detection using ONNX Runtime."""
    
    def __init__(self, model_path: str = "data/models/yolo_detector.onnx", conf_threshold: float = 0.5, nms_threshold: float = 0.45, classes: Optional[dict] = None):
        self.model_path = model_path
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.session = None
        self.input_name = None
        self.output_names = None
        self.input_shape = (640, 640)  # Default YOLOv8 shape
        
        if classes is not None:
            self.classes = classes
        else:
            # Default to standard 80 COCO classes
            self.classes = {
                0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 4: 'airplane', 5: 'bus', 6: 'train', 7: 'truck', 8: 'boat', 9: 'traffic light',
                10: 'fire hydrant', 11: 'stop sign', 12: 'parking meter', 13: 'bench', 14: 'bird', 15: 'cat', 16: 'dog', 17: 'horse', 18: 'sheep', 19: 'cow',
                20: 'elephant', 21: 'bear', 22: 'zebra', 23: 'giraffe', 24: 'backpack', 25: 'umbrella', 26: 'handbag', 27: 'tie', 28: 'suitcase', 29: 'frisbee',
                30: 'skis', 31: 'snowboard', 32: 'sports ball', 33: 'kite', 34: 'baseball bat', 35: 'baseball glove', 36: 'skateboard', 37: 'surfboard', 38: 'tennis racket', 39: 'bottle',
                40: 'wine glass', 41: 'cup', 42: 'fork', 43: 'knife', 44: 'spoon', 45: 'bowl', 46: 'banana', 47: 'apple', 48: 'sandwich', 49: 'orange',
                50: 'broccoli', 51: 'carrot', 52: 'hot dog', 53: 'pizza', 54: 'donut', 55: 'cake', 56: 'chair', 57: 'couch', 58: 'potted plant', 59: 'bed',
                60: 'dining table', 61: 'toilet', 62: 'tv', 63: 'laptop', 64: 'mouse', 65: 'remote', 66: 'keyboard', 67: 'cell phone', 68: 'microwave', 69: 'oven',
                70: 'toaster', 71: 'sink', 72: 'refrigerator', 73: 'book', 74: 'clock', 75: 'vase', 76: 'scissors', 77: 'teddy bear', 78: 'hair drier', 79: 'toothbrush',
                # Sentinel specific (if used with a custom model)
                80: 'hostile_uas', 81: 'friendly_uas', 82: 'vehicle_military', 83: 'weapon', 84: 'infrastructure', 85: 'unknown'
            }
        
    def load(self, use_tensorrt: bool = False) -> bool:
        """Load the ONNX model."""
        if not ORT_AVAILABLE:
            logger.error("Cannot load model: ONNX Runtime not available.")
            return False
            
        if not os.path.exists(self.model_path):
            logger.warning(f"Model not found at {self.model_path}. Detection disabled.")
            return False
            
        try:
            providers = ['CPUExecutionProvider']
            if use_tensorrt and 'TensorrtExecutionProvider' in ort.get_available_providers():
                providers.insert(0, 'TensorrtExecutionProvider')
            elif 'CUDAExecutionProvider' in ort.get_available_providers():
                providers.insert(0, 'CUDAExecutionProvider')
                
            self.session = ort.InferenceSession(self.model_path, providers=providers)
            self.input_name = self.session.get_inputs()[0].name
            self.output_names = [out.name for out in self.session.get_outputs()]
            
            # Try to get input shape dynamically
            shape = self.session.get_inputs()[0].shape
            if len(shape) == 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
                self.input_shape = (shape[2], shape[3])
                
            logger.info(f"Loaded YOLO detector from {self.model_path} using {providers[0]}")
            return True
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            return False
            
    def _preprocess(self, frame: np.ndarray) -> Tuple[np.ndarray, float, Tuple[int, int]]:
        """Resize and normalize image for YOLO."""
        if not CV2_AVAILABLE:
            return None, 1.0, (0, 0)
            
        original_h, original_w = frame.shape[:2]
        
        # Letterbox resize
        scale = min(self.input_shape[0] / original_h, self.input_shape[1] / original_w)
        new_w = int(original_w * scale)
        new_h = int(original_h * scale)
        
        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        
        # Pad to input_shape
        dw = (self.input_shape[1] - new_w) / 2
        dh = (self.input_shape[0] - new_h) / 2
        
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        
        padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        
        # HWC to CHW, BGR to RGB
        img = padded[:, :, ::-1].transpose(2, 0, 1)
        img = np.ascontiguousarray(img)
        
        # Normalize
        img = img.astype(np.float32) / 255.0
        img = np.expand_dims(img, axis=0)  # Add batch dimension
        
        pad_info = (dw, dh)
        return img, scale, pad_info
        
    def _postprocess(self, output: np.ndarray, scale: float, pad_info: Tuple[int, int], frame_id: int) -> List[Detection]:
        """Convert raw YOLO output to Detection objects."""
        if not CV2_AVAILABLE:
            return []
            
        dw, dh = pad_info
        detections = []
        
        # YOLOv8 output shape is typically (1, num_classes + 4, num_anchors)
        # We need to transpose it to (num_anchors, num_classes + 4)
        predictions = np.squeeze(output).T
        
        # Filter by confidence
        scores = np.max(predictions[:, 4:], axis=1)
        valid_idx = scores > self.conf_threshold
        predictions = predictions[valid_idx]
        scores = scores[valid_idx]
        
        if len(predictions) == 0:
            return []
            
        class_ids = np.argmax(predictions[:, 4:], axis=1)
        
        # Extract bounding boxes (cx, cy, w, h)
        boxes = predictions[:, :4].copy()
        
        cx = boxes[:, 0]
        cy = boxes[:, 1]
        w = boxes[:, 2]
        h = boxes[:, 3]
        
        # Convert to x1, y1, x2, y2 and adjust for letterboxing
        boxes[:, 0] = (cx - w / 2 - dw) / scale  # x1
        boxes[:, 1] = (cy - h / 2 - dh) / scale  # y1
        boxes[:, 2] = (cx + w / 2 - dw) / scale  # x2
        boxes[:, 3] = (cy + h / 2 - dh) / scale  # y2
        
        # Apply NMS
        indices = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self.conf_threshold, self.nms_threshold)
        
        for i in indices:
            idx = i if isinstance(i, int) else i[0]
            box = boxes[idx].astype(int)
            class_id = int(class_ids[idx])
            
            detections.append(Detection(
                bbox=(box[0], box[1], box[2], box[3]),
                class_id=class_id,
                class_name=self.classes.get(class_id, "unknown"),
                confidence=float(scores[idx]),
                frame_id=frame_id
            ))
            
        return detections

    def detect(self, frame: np.ndarray, frame_id: int = 0) -> List[Detection]:
        """Run detection on a single frame."""
        if self.session is None or not CV2_AVAILABLE:
            return []
            
        img, scale, pad_info = self._preprocess(frame)
        if img is None:
            return []
            
        outputs = self.session.run(self.output_names, {self.input_name: img})
        detections = self._postprocess(outputs[0], scale, pad_info, frame_id)
        
        return detections
