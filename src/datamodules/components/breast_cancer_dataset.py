import logging
from pathlib import Path

import hydra
import numpy as np
import opendatasets as od
import pandas as pd
import pyrootutils
import torch
from omegaconf import DictConfig
from sklearn.utils.class_weight import compute_class_weight
from torchvision import io, tv_tensors

log = logging.getLogger(__name__)


class BreastCancerDataset(torch.utils.data.Dataset):
    def __init__(self, data_dir: Path, dataset_url: str | None = None) -> None:
        self.label_mapping = {}

        self.data_dir = Path(data_dir)
        self.root_data_dir = self.data_dir.parent
        self.dataset_url = dataset_url

        # --- Check for directory existence BEFORE trying to read it ---
        if not self.data_dir.exists():
            log.info(f"Data directory {self.data_dir} not found.")
            if self.dataset_url:
                log.info(f"Attempting to download dataset from {self.dataset_url}...")
                self._download_dataset()  # Call your download method
                # After download attempt, check again if it exists
                if not self.data_dir.exists():
                    # If download failed or didn't create the dir
                    raise FileNotFoundError(
                        f"Dataset download attempted but directory {self.data_dir} still not found."
                    )
            else:
                raise ValueError(
                    f"Data directory {self.data_dir} not found and Dataset URL not provided. Cannot proceed."
                )

        # if len(list(self.root_data_dir.iterdir())) == 0:
        #     self._download_dataset()
        class_names = [_dir.stem for _dir in self.data_dir.iterdir()]
        self.class_names = sorted(class_names)
        self.num_classes = len(self.class_names)
        self.label_mapping = {name: i for i, name in enumerate(self.class_names)}
        self._class_weights: torch.Tensor | None = None

        self.images, self.masks, self.labels = self.get_data()

    def _download_dataset(self) -> None:
        log.info(f"Downloading dataset from kaggle at {self.root_data_dir}")
        if self.dataset_url is None:
            raise ValueError("Dataset URL not provided")
        od.download(dataset_id_or_url=self.dataset_url, data_dir=str(self.root_data_dir))

    def __len__(self) -> int:
        return len(self.images)

    def __getitem__(self, index) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        img = tv_tensors.Image(io.decode_image(str(self.images[index]), mode=io.ImageReadMode.RGB))
        mask = tv_tensors.Mask(io.decode_image(str(self.masks[index]), mode=io.ImageReadMode.GRAY))

        # Convert label to numerical representation
        label = self.labels[index]
        label_index = self.label_mapping[label]

        target = {}
        target["masks"] = mask
        target["labels"] = label_index
        return img, target

    @property
    def classes(self) -> list[str]:
        return self.class_names

    @property
    def class_to_idx(self) -> dict[str, int]:
        return self.label_mapping

    def calculate_class_weights(self, org_images: list, masks: list, labels: list):
        # --- Calculate Class Weights (using scikit-learn is convenient) ---
        data = {"images": org_images, "masks": masks, "labels": labels}
        df = pd.DataFrame(data)
        class_weights = compute_class_weight(
            class_weight="balanced", classes=np.array(self.class_names), y=df["labels"]
        )
        self._class_weights = torch.tensor(class_weights, dtype=torch.float32)
        log.info(f"Class weights: {self._class_weights}")

    @property
    def class_weights(self) -> torch.Tensor | None:
        return self._class_weights

    def get_data(self) -> tuple[list[Path], list[Path], list[str]]:
        log.info(f"Getting data from {self.data_dir}")
        org_images = []
        masks = []
        labels = []

        for _dir in self.data_dir.iterdir():
            dir_name = _dir.stem
            img_nums = (img.stem.split("(")[-1].split(")")[0] for img in _dir.glob("*.png"))
            for num in img_nums:
                # normal (1).png
                img_path = f"{_dir/dir_name} ({num})"
                org_img_path = Path(f"{img_path}.png")
                # normal (2)_mask
                mask_path = Path(f"{img_path}_mask.png")
                org_images.append(org_img_path)
                labels.append(dir_name)
                masks.append(mask_path)

        self.calculate_class_weights(org_images=org_images, masks=masks, labels=labels)

        return org_images, masks, labels


@hydra.main(version_base="1.2", config_path="../../../configs", config_name="train.yaml")
def main(cfg: DictConfig) -> None:
    dataset = hydra.utils.instantiate(cfg.data.dataset)
    for img, target in dataset:
        print(img.shape, target["masks"].shape, target["labels"].shape)
        break


if __name__ == "__main__":
    root = pyrootutils.setup_root(__file__, pythonpath=True)
    main()
