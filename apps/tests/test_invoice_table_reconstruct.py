"""
Tests for pure table reconstruction (apps/invoices/table_reconstruct.py) —
the core of the free easyocr structured extractor. Synthetic boxes, no OCR.
"""
from django.test import SimpleTestCase

from apps.invoices import table_reconstruct as tr


def box(cx, cy, text, w=40, h=20, conf=0.9):
    return {'cx': cx, 'cy': cy, 'w': w, 'h': h, 'text': text, 'conf': conf}


class GroupRowsTests(SimpleTestCase):

    def test_three_rows_cluster_by_y(self):
        boxes = [box(10, 100, 'a'), box(80, 102, 'b'),
                 box(10, 160, 'c'), box(80, 158, 'd'),
                 box(10, 220, 'e')]
        rows = tr.group_rows(boxes, y_tol=15)
        self.assertEqual(len(rows), 3)
        self.assertEqual({b['text'] for b in rows[0]}, {'a', 'b'})

    def test_rows_sorted_top_to_bottom(self):
        rows = tr.group_rows([box(0, 300, 'low'), box(0, 50, 'high')], y_tol=10)
        self.assertEqual(rows[0][0]['text'], 'high')

    def test_empty(self):
        self.assertEqual(tr.group_rows([]), [])

    def test_y_tol_auto_from_height(self):
        # two lines ~30px apart with box height 20 → auto y_tol ~12 keeps them apart
        rows = tr.group_rows([box(0, 100, 'a', h=20), box(0, 132, 'b', h=20)])
        self.assertEqual(len(rows), 2)


class ClusterColumnsTests(SimpleTestCase):

    def test_three_columns(self):
        boxes = []
        for cy in (100, 150, 200):
            boxes += [box(50, cy, 'n'), box(300, cy, 'q'), box(550, cy, 'p')]
        cols = tr.cluster_columns(boxes)
        self.assertEqual(len(cols), 3)
        self.assertTrue(cols[0] < cols[1] < cols[2])

    def test_min_count_filters_noise(self):
        # a lone stray box far right should not become its own column
        boxes = [box(50, 100, 'a'), box(50, 150, 'b'), box(50, 200, 'c'),
                 box(900, 100, 'stray')]
        cols = tr.cluster_columns(boxes, min_count=2)
        self.assertEqual(len(cols), 1)


class AssembleGridTests(SimpleTestCase):

    def test_grid_cells_placed_in_nearest_column(self):
        boxes = [box(50, 100, 'PANADOL'), box(300, 100, '10'), box(550, 100, '25'),
                 box(50, 150, 'AUGMENTIN'), box(300, 150, '3'), box(550, 150, '40')]
        cols = tr.cluster_columns(boxes)
        grid = tr.assemble_grid(boxes, cols)
        self.assertEqual(grid[0], ['PANADOL', '10', '25'])
        self.assertEqual(grid[1], ['AUGMENTIN', '3', '40'])

    def test_multiple_boxes_in_one_cell_merge_in_reading_order(self):
        # a wide name column (centre ~80) and a qty column (centre ~400): the three
        # name fragments all land in the name cell and merge left→right
        boxes = [box(40, 100, 'HERO'), box(80, 100, 'BABY'), box(120, 100, 'MILK'),
                 box(400, 100, '4')]
        grid = tr.assemble_grid(boxes, [80, 400])
        self.assertEqual(grid[0], ['HERO BABY MILK', '4'])

    def test_no_columns_single_cell_per_row(self):
        grid = tr.assemble_grid([box(10, 100, 'x'), box(90, 100, 'y')], [])
        self.assertEqual(grid, [['x y']])


class ReconstructTableTests(SimpleTestCase):

    def test_full_reconstruction_shape(self):
        boxes = []
        for cy in (100, 150):
            boxes += [box(50, cy, 'name'), box(300, cy, '2'), box(550, cy, '99')]
        out = tr.reconstruct_table(boxes, y_tol=15)
        self.assertEqual(len(out['columns']), 3)
        self.assertEqual(len(out['rows']), 2)
        self.assertEqual(out['rows'][0], ['name', '2', '99'])
