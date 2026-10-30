import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from searchy.core.errors import InvalidInput, SearchyError


@dataclass(frozen=True)
class FaceEncoding:
    embedding: list[float]
    model_id: str
    bounds: tuple[int, int, int, int]


class OpenCVFaces:
    def __init__(self, detector_path: Path, recognizer_path: Path, score_threshold: float = 0.9):
        self.detector_path = Path(detector_path)
        self.recognizer_path = Path(recognizer_path)
        self.score_threshold = score_threshold
        self._detector = None
        self._recognizer = None
        self.model_id = ""

    def _load(self):
        if self._detector is not None:
            return
        if not self.detector_path.is_file() or not self.recognizer_path.is_file():
            raise SearchyError(
                "Face recognition model files are missing. Configure YuNet and SFace ONNX model paths."
            )
        try:
            import cv2
        except ImportError:
            raise SearchyError(
                "Face recognition requires the optional video dependencies: uv sync --extra video"
            ) from None
        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(self.detector_path), "", (320, 320), self.score_threshold
            )
            self._recognizer = cv2.FaceRecognizerSF.create(str(self.recognizer_path), "")
        except (cv2.error, AttributeError):
            raise SearchyError(
                "OpenCV could not load the configured YuNet and SFace models"
            ) from None
        digest = hashlib.sha256(self.recognizer_path.read_bytes()).hexdigest()[:16]
        self.model_id = f"opencv/sface:{digest}:128"

    def detect(self, path: Path) -> list[FaceEncoding]:
        self._load()
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            raise InvalidInput("The face reference image could not be decoded")
        try:
            height, width = image.shape[:2]
            scale = min(1, 1280 / max(width, height))
            if scale < 1:
                image = cv2.resize(image, (round(width * scale), round(height * scale)))
            self._detector.setInputSize((image.shape[1], image.shape[0]))
            _, faces = self._detector.detect(image)
            result = []
            for face in [] if faces is None else faces:
                crop = self._recognizer.alignCrop(image, face)
                vector = [float(value) for value in self._recognizer.feature(crop).reshape(-1)]
                norm = math.sqrt(sum(value * value for value in vector))
                if len(vector) != 128 or not math.isfinite(norm) or norm <= 0:
                    raise SearchyError("SFace returned an incompatible face embedding")
                result.append(
                    FaceEncoding(
                        [value / norm for value in vector],
                        self.model_id,
                        tuple(round(float(value) / scale) for value in face[:4]),
                    )
                )
            return result
        except cv2.error:
            raise SearchyError("Face recognition could not process this image") from None

    def encode(self, path: Path) -> FaceEncoding:
        faces = self.detect(path)
        if not faces:
            raise InvalidInput(
                "No usable face was detected. Use a clear image with one visible face."
            )
        if len(faces) != 1:
            raise InvalidInput("Multiple faces were detected. Crop the image to one person.")
        return faces[0]
