from yolox.exp import Exp as MyExp
from yolox.data import VOCDetection, TrainTransform, YoloBatchSampler, ValTransform
from torch.utils.data import DataLoader
import torch
from yolox.evaluators import VOCEvaluator


class Exp(MyExp):
    def __init__(self):
        super().__init__()
        self.num_classes = 14
        self.depth = 0.33
        self.width = 0.50
        self.input_size = (640, 640)
        self.test_size = (640, 640)
        self.test_ann = "test.txt"
        self.max_epoch = 50
        self.data_num_workers = 2
        self.eval_interval = 1
        self.data_dir = "datasets/VOCdevkit"
        self.exp_name = "all_4_16"

    def get_data_loader(self, batch_size, is_distributed, no_aug=False, cache_img=False):
        dataset = VOCDetection(
            data_dir=self.data_dir,
            image_sets=[("2007", "train")],
            img_size=self.input_size,
            preproc=TrainTransform(
                max_labels=50,
                flip_prob=self.flip_prob,
                hsv_prob=self.hsv_prob,
            ),
        )

        print("DATASET SIZE:", len(dataset))

        sampler = torch.utils.data.RandomSampler(dataset)
        batch_sampler = YoloBatchSampler(
            sampler=sampler,
            batch_size=batch_size,
            drop_last=False,
            mosaic=not no_aug,
        )

        dataloader = DataLoader(
            dataset,
            batch_sampler=batch_sampler,
            num_workers=self.data_num_workers,
            pin_memory=True,
        )
        return dataloader

    def get_eval_loader(self, batch_size, is_distributed, testdev=False, legacy=False):
        valdataset = VOCDetection(
            data_dir=self.data_dir,
            image_sets=[("2007", "val")],
            img_size=self.test_size,
            preproc=ValTransform(legacy=legacy),
        )

        dataloader = DataLoader(
            valdataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=self.data_num_workers,
            pin_memory=False,
        )

        return dataloader

    

    def get_evaluator(self, batch_size, is_distributed, testdev=False, legacy=False):
        val_loader = self.get_eval_loader(1, is_distributed, testdev, legacy)
        return VOCEvaluator(
            dataloader=val_loader,
            img_size=self.test_size,
            confthre=self.test_conf,
            nmsthre=self.nmsthre,
            num_classes=self.num_classes,
        )