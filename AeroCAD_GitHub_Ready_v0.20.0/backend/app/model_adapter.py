from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class ModelResult:
    building_mask: np.ndarray | None
    road_mask: np.ndarray | None
    mode: str
    model_id: str | None
    detail: str


class SegmentationAdapter:
    """Optional semantic-segmentation adapter.

    Hugging Face Transformers is loaded only when inference starts. The model
    can be swapped with AEROCAD_SEGMENTATION_MODEL without changing the API.
    """

    def __init__(self) -> None:
        self.model_id = os.getenv(
            "AEROCAD_SEGMENTATION_MODEL",
            "nvidia/segformer-b0-finetuned-ade-512-512",
        )
        self._processor = None
        self._model = None
        self._torch = None
        self._device = None
        self._load_attempted = False

    def _load(self) -> None:
        from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
        import torch

        self._torch = torch
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._processor = AutoImageProcessor.from_pretrained(self.model_id)
        self._model = AutoModelForSemanticSegmentation.from_pretrained(self.model_id)
        self._model.to(self._device)
        self._model.eval()

    def _class_ids(self, keywords: tuple[str, ...]) -> list[int]:
        labels: dict[Any, Any] = getattr(self._model.config, "id2label", {})
        ids: list[int] = []
        for raw_id, raw_label in labels.items():
            label = str(raw_label).lower()
            if any(keyword in label for keyword in keywords):
                ids.append(int(raw_id))
        return ids

    def predict(self, image_rgb: np.ndarray) -> ModelResult:
        """Run segmentation, falling back safely when the optional model fails.

        The cadastral pipeline must remain usable even when a remote Hugging Face
        checkpoint, transformers version, or model inference path is unavailable.
        Any inference-time exception is therefore converted into an explicit
        ``unavailable`` result so the caller can use the deterministic baseline.
        """
        try:
            if os.getenv("AEROCAD_DISABLE_SEMANTIC_MODEL", "0").lower() in {"1", "true", "yes"}:
                return ModelResult(
                    building_mask=None,
                    road_mask=None,
                    mode="unavailable",
                    model_id=self.model_id,
                    detail="Semantic model disabled by AEROCAD_DISABLE_SEMANTIC_MODEL.",
                )

            if self._model is None and not self._load_attempted:
                self._load_attempted = True
                self._load()

            processor = self._processor
            torch = self._torch
            if processor is None or torch is None or self._model is None or self._device is None:
                raise RuntimeError("Semantic segmentation components were not initialized.")

            inputs = processor(images=image_rgb, return_tensors="pt")
            inputs = {key: value.to(self._device) for key, value in inputs.items()}
            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = torch.nn.functional.interpolate(
                    outputs.logits,
                    size=image_rgb.shape[:2],
                    mode="bilinear",
                    align_corners=False,
                )
                probs = torch.softmax(logits, dim=1)[0].detach().cpu().numpy()

            building_ids = self._class_ids(("building", "house"))
            road_ids = self._class_ids(("road", "street", "path", "sidewalk"))

            def union(ids: list[int]) -> np.ndarray | None:
                if not ids:
                    return None
                score = probs[ids].max(axis=0)
                return (score >= 0.55).astype(np.uint8)

            return ModelResult(
                building_mask=union(building_ids),
                road_mask=union(road_ids),
                mode="semantic-segmentation",
                model_id=self.model_id,
                detail=(
                    f"Loaded {self.model_id} on {self._device}; "
                    f"building classes={building_ids or 'none'}, road classes={road_ids or 'none'}."
                ),
            )
        except Exception as exc:  # inference-time failure -> deterministic baseline
            return ModelResult(
                building_mask=None,
                road_mask=None,
                mode="unavailable",
                model_id=self.model_id,
                detail=f"Semantic model unavailable during inference: {exc}",
            )
