"""NWRD 数据准备的纯函数单测（仓库根目录运行：python -m unittest ml.test_prepare_nwrd，不需要 torch）。"""
import unittest

from ml.data.prepare_nwrd import RUST_MIN, label_for, patch_boxes, split_train_val


class PatchBoxTests(unittest.TestCase):
    def test_boxes_cover_whole_image_including_edges(self):
        boxes = patch_boxes(1000, 700, size=300, stride=150)
        self.assertTrue(all(w == h == 300 for _, _, w, h in boxes))
        self.assertEqual(max(x + w for x, _, w, _ in boxes), 1000)  # 最后一列贴右边
        self.assertEqual(max(y + h for _, y, _, h in boxes), 700)
        self.assertEqual(len(set(boxes)), len(boxes))

    def test_patch_larger_than_image_yields_nothing(self):
        self.assertEqual(patch_boxes(200, 100, size=150, stride=75), [])


class LabelTests(unittest.TestCase):
    def test_threshold_and_ambiguous_band(self):
        self.assertEqual(label_for(0.0), "healthy")
        self.assertEqual(label_for(RUST_MIN), "rust")
        self.assertIsNone(label_for(RUST_MIN / 2))  # 边界样本不参与训练


class SplitTests(unittest.TestCase):
    def test_split_is_by_whole_image_and_deterministic(self):
        names = [f"{i}.jpg" for i in range(90)]
        train, val = split_train_val(names)
        self.assertEqual(len(val), 9)
        self.assertFalse(set(train) & set(val))
        self.assertEqual(set(train) | set(val), set(names))
        self.assertEqual((train, val), split_train_val(list(reversed(names))))


if __name__ == "__main__":
    unittest.main()
