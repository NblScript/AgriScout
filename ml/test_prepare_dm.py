"""霜霉病数据准备的纯函数单测（仓库根目录运行：python -m unittest ml.test_prepare_dm，不需要 torch / numpy / PIL）。"""
import random
import unittest

from ml.data.prepare_dm import (
    IGNORE, OTHER, dihedral, group_near_duplicates, is_augmented, label_for_parts, normalize_license,
    split_groups, variant_hashes,
)
from ml.eval_dm import pick_threshold


def random_grid(seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(256) for _ in range(9)] for _ in range(9)]


class ClassMappingTests(unittest.TestCase):
    def test_folder_names_map_to_labels(self):
        self.assertEqual(label_for_parts(("Original Image", "Downy Mildew")), ("downy_mildew", "Downy Mildew"))
        self.assertEqual(label_for_parts(("Original Image", "Fresh Leaf"))[0], "healthy")
        self.assertEqual(label_for_parts(("Healthy leaf",))[0], "healthy")
        self.assertEqual(label_for_parts(("Anthracnose",))[0], OTHER)
        self.assertEqual(label_for_parts(("Leaf curl virus",))[0], OTHER)
        self.assertEqual(label_for_parts(("data", "misc")), (None, None))

    def test_fruit_classes_are_ignored_not_healthy(self):
        self.assertEqual(label_for_parts(("Fresh Cucumber",))[0], IGNORE)
        self.assertEqual(label_for_parts(("Belly Rot",))[0], IGNORE)
        self.assertEqual(label_for_parts(("Pythium Fruit Rot",))[0], IGNORE)

    def test_deepest_matching_folder_wins(self):
        self.assertEqual(label_for_parts(("Downy Mildew", "healthy"))[0], "healthy")

    def test_augmented_folders_detected(self):
        self.assertTrue(is_augmented(("Augmented Image", "Downy Mildew")))
        self.assertFalse(is_augmented(("Original Image", "Downy Mildew")))


class LicenseTests(unittest.TestCase):
    def test_common_spellings_normalize(self):
        for text in ("CC BY 4.0", "CC-BY-4.0", "Creative Commons Attribution 4.0 International",
                     "https://creativecommons.org/licenses/by/4.0/"):
            self.assertEqual(normalize_license(text), "CC BY 4.0", text)
        self.assertEqual(normalize_license("CC0 1.0"), "CC0 1.0")

    def test_restrictive_licenses_never_become_cc_by(self):
        self.assertEqual(normalize_license("CC BY-NC 4.0"), "CC BY NC 4.0")
        self.assertEqual(normalize_license("Creative Commons Attribution-NonCommercial 4.0 International"),
                         "CC BY NC 4.0")
        self.assertEqual(normalize_license("https://creativecommons.org/licenses/by-nc-nd/4.0/"), "CC BY NC ND 4.0")
        self.assertEqual(normalize_license("All rights reserved"), "All rights reserved")  # 认不出就原样返回


class NearDuplicateTests(unittest.TestCase):
    def test_flips_and_rotations_share_a_hash(self):
        grid = random_grid(1)
        base = set(variant_hashes(grid))
        for variant in dihedral(grid):
            self.assertEqual(variant_hashes(variant)[0] in base, True)

    def test_grouping_merges_variants_and_small_edits_only(self):
        a, b = random_grid(1), random_grid(2)
        flipped = dihedral(a)[3]
        nudged = [row[:] for row in a]
        nudged[0][0] = 255 - nudged[0][0]  # 改一个像素，最多翻两位
        groups = group_near_duplicates([variant_hashes(g) for g in (a, b, flipped, nudged)])
        self.assertEqual(groups[0], groups[2])
        self.assertEqual(groups[0], groups[3])
        self.assertNotEqual(groups[0], groups[1])

    def test_grouping_is_transitive(self):
        a = random_grid(3)
        chain = [a]
        for k in range(3):  # 每步改一个像素：首尾可能超过阈值，但经中间一张连成一组
            nxt = [row[:] for row in chain[-1]]
            nxt[k + 1][k + 1] = 255 - nxt[k + 1][k + 1]
            chain.append(nxt)
        groups = group_near_duplicates([variant_hashes(g) for g in chain])
        self.assertEqual(len(set(groups)), 1)


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.labels = {g: ("downy_mildew" if g % 3 == 0 else "healthy") for g in range(300)}
        self.sizes = {g: 1 + g % 4 for g in range(300)}

    def test_each_group_in_exactly_one_split_and_deterministic(self):
        split = split_groups(self.labels, self.sizes)
        self.assertEqual(set(split), set(self.labels))
        self.assertEqual(split, split_groups(dict(reversed(list(self.labels.items()))), self.sizes))

    def test_stratified_by_label_with_target_fractions(self):
        split = split_groups(self.labels, self.sizes)
        for label in ("downy_mildew", "healthy"):
            total = sum(self.sizes[g] for g, lab in self.labels.items() if lab == label)
            for name in ("test", "val"):
                n = sum(self.sizes[g] for g, s in split.items() if s == name and self.labels[g] == label)
                self.assertAlmostEqual(n / total, 0.15, delta=0.03, msg=f"{label}/{name}")


class ThresholdTests(unittest.TestCase):
    def test_highest_threshold_meeting_recall(self):
        labels = [1, 1, 1, 1, 0, 0, 0, 0]
        probs = [0.9, 0.8, 0.6, 0.3, 0.7, 0.2, 0.1, 0.05]
        self.assertEqual(pick_threshold(labels, probs, min_recall=0.75), 0.6)
        self.assertEqual(pick_threshold(labels, probs, min_recall=1.0), 0.3)
        self.assertEqual(pick_threshold(labels, probs, min_recall=0.5), 0.8)

    def test_no_positives_falls_back_to_default(self):
        self.assertEqual(pick_threshold([0, 0], [0.4, 0.6], min_recall=0.9), 0.5)


if __name__ == "__main__":
    unittest.main()
