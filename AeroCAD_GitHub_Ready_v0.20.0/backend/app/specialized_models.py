from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class SpecialistResult:
    mask: np.ndarray | None
    model_id: str | None
    detail: str
    available: bool


class BuildingSpecialist:
    """HOTOSM DINOv3 building footprint model served via ONNX Runtime.

    Model card/source: hotosm/dinov3s-buildings. It expects RGB chips and uses
    256 px sliding windows. The implementation follows the published fAIr
    preprocessing convention: NCHW float32, 0..1 scaling, HOT normalisation.
    """

    model_repo = "hotosm/dinov3s-buildings"
    model_file = "model.onnx"
    model_id = "hotosm/dinov3s-buildings"
    window = 256
    stride = 192
    threshold = float(os.getenv("AEROCAD_BUILDING_THRESHOLD", "0.4371"))
    mean = np.asarray([0.4297, 0.4002, 0.3433], dtype=np.float32)
    std = np.asarray([0.2056, 0.1674, 0.1599], dtype=np.float32)

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = cache_root
        self.model_path = self.cache_root / "dinov3s-buildings.onnx"
        self._session: Any = None
        self._input_name: str | None = None
        self._output_name: str | None = None
        self._load_error: str | None = None

    def _ensure_loaded(self) -> None:
        if os.getenv("AEROCAD_DISABLE_SPECIALIST_MODELS", "0").lower() in {"1", "true", "yes"}:
            self._load_error = "Specialist models disabled by AEROCAD_DISABLE_SPECIALIST_MODELS."
            return
        if self._session is not None or self._load_error is not None:
            return
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download

            self.cache_root.mkdir(parents=True, exist_ok=True)
            if not self.model_path.exists():
                downloaded = hf_hub_download(
                    repo_id=self.model_repo,
                    filename=self.model_file,
                    local_dir=str(self.cache_root),
                )
                self.model_path = Path(downloaded)
            providers = ["CPUExecutionProvider"]
            self._session = ort.InferenceSession(str(self.model_path), providers=providers)
            self._input_name = self._session.get_inputs()[0].name
            self._output_name = self._session.get_outputs()[0].name
        except Exception as exc:
            self._load_error = str(exc)

    @staticmethod
    def _sigmoid(values: np.ndarray) -> np.ndarray:
        values = np.clip(values, -30.0, 30.0)
        return 1.0 / (1.0 + np.exp(-values))

    def _predict_one(self, chip: np.ndarray) -> np.ndarray:
        self._ensure_loaded()
        if self._session is None or self._input_name is None:
            raise RuntimeError(self._load_error or "Building model failed to load")

        rgb = chip.astype(np.float32) / 255.0
        rgb = np.clip(rgb, 0.0, 1.0)
        rgb = (rgb - self.mean.reshape(1, 1, 3)) / self.std.reshape(1, 1, 3)
        nchw = np.transpose(rgb, (2, 0, 1))[None, ...].astype(np.float32)
        outputs = self._session.run([self._output_name] if self._output_name else None, {self._input_name: nchw})
        arr = np.asarray(outputs[0])
        if arr.ndim == 4:
            arr = arr[0]
        if arr.ndim == 3:
            # fAIr's published ONNX output is 3-channel logits with the mask
            # logit in channel 0. Be tolerant of 1-channel exports too.
            arr = arr[0]
        if arr.ndim != 2:
            raise RuntimeError(f"Unexpected building ONNX output shape: {arr.shape}")
        return self._sigmoid(arr)

    def predict(self, image_rgb: np.ndarray) -> SpecialistResult:
        self._ensure_loaded()
        if self._session is None:
            return SpecialistResult(None, self.model_id, f"Building specialist unavailable: {self._load_error}", False)

        try:
            h, w = image_rgb.shape[:2]
            prob_sum = np.zeros((h, w), dtype=np.float32)
            count = np.zeros((h, w), dtype=np.float32)
            for y in range(0, max(h, 1), self.stride):
                for x in range(0, max(w, 1), self.stride):
                    y1, x1 = y, x
                    y2, x2 = min(y + self.window, h), min(x + self.window, w)
                    patch = image_rgb[y1:y2, x1:x2]
                    pad_h, pad_w = self.window - patch.shape[0], self.window - patch.shape[1]
                    if pad_h or pad_w:
                        patch = np.pad(patch, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
                    prob = self._predict_one(patch)
                    prob = prob[: y2 - y1, : x2 - x1]
                    prob_sum[y1:y2, x1:x2] += prob
                    count[y1:y2, x1:x2] += 1.0
                if y >= h - 1:
                    break
            probability = prob_sum / np.maximum(count, 1.0)
            mask = (probability >= self.threshold).astype(np.uint8)
            return SpecialistResult(
                mask,
                self.model_id,
                f"HOTOSM DINOv3 building segmentation; 256px window / 192px stride; threshold={self.threshold:.4f}.",
                True,
            )
        except Exception as exc:
            return SpecialistResult(None, self.model_id, f"Building specialist inference failed: {exc}", False)


class RoadSpecialist:
    """Aerial roadway instance-segmentation model served through Ultralytics."""

    model_repo = "dastrix/polylane-roadway-yolo11l-seg"
    model_file = "best.pt"
    model_id = "dastrix/polylane-roadway-yolo11l-seg"
    confidence = float(os.getenv("AEROCAD_ROAD_CONFIDENCE", "0.25"))

    def __init__(self, cache_root: Path) -> None:
        self.cache_root = cache_root
        self.model_path = self.cache_root / "roadway-yolo11l-seg-best.pt"
        self._model: Any = None
        self._load_error: str | None = None

    def _ensure_loaded(self) -> None:
        if os.getenv("AEROCAD_DISABLE_SPECIALIST_MODELS", "0").lower() in {"1", "true", "yes"}:
            self._load_error = "Specialist models disabled by AEROCAD_DISABLE_SPECIALIST_MODELS."
            return
        if self._model is not None or self._load_error is not None:
            return
        try:
            from huggingface_hub import hf_hub_download
            from ultralytics import YOLO

            self.cache_root.mkdir(parents=True, exist_ok=True)
            if not self.model_path.exists():
                downloaded = hf_hub_download(
                    repo_id=self.model_repo,
                    filename=self.model_file,
                    local_dir=str(self.cache_root),
                )
                self.model_path = Path(downloaded)
            self._model = YOLO(str(self.model_path))
        except Exception as exc:
            self._load_error = str(exc)

    def predict(self, image_rgb: np.ndarray) -> SpecialistResult:
        self._ensure_loaded()
        if self._model is None:
            return SpecialistResult(None, self.model_id, f"Road specialist unavailable: {self._load_error}", False)
        try:
            results = self._model.predict(
                source=image_rgb,
                imgsz=1280,
                conf=self.confidence,
                verbose=False,
                device=0 if _cuda_available() else "cpu",
            )
            if not results:
                return SpecialistResult(np.zeros(image_rgb.shape[:2], dtype=np.uint8), self.model_id, "Road specialist returned no detections.", True)
            result = results[0]
            if result.masks is None:
                return SpecialistResult(np.zeros(image_rgb.shape[:2], dtype=np.uint8), self.model_id, "Road specialist returned no segmentation masks.", True)
            masks = result.masks.data
            try:
                import torch
                union = masks.any(dim=0, keepdim=True).float().unsqueeze(0)
                union = torch.nn.functional.interpolate(
                    union,
                    size=image_rgb.shape[:2],
                    mode="nearest",
                )[0, 0]
                mask = union.detach().cpu().numpy().astype(np.uint8)
            except Exception:
                mask = np.asarray(masks.detach().cpu().numpy().any(axis=0), dtype=np.uint8)
                if mask.shape != image_rgb.shape[:2]:
                    from PIL import Image
                    mask = np.asarray(Image.fromarray(mask).resize((image_rgb.shape[1], image_rgb.shape[0]), Image.Resampling.NEAREST))
                    mask = (mask > 0).astype(np.uint8)
            return SpecialistResult(
                mask,
                self.model_id,
                f"YOLO11 roadway segmentation; imgsz=1280; confidence={self.confidence:.2f}.",
                True,
            )
        except Exception as exc:
            return SpecialistResult(None, self.model_id, f"Road specialist inference failed: {exc}", False)


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


class AeroCADSpecialists:
    """Lazy-load building and roadway specialists with safe fallbacks."""

    def __init__(self, project_dir: Path) -> None:
        cache = project_dir / "models"
        self.buildings = BuildingSpecialist(cache)
        self.roads = RoadSpecialist(cache)

    def predict(self, image_rgb: np.ndarray) -> tuple[SpecialistResult, SpecialistResult]:
        return self.buildings.predict(image_rgb), self.roads.predict(image_rgb)
