import unittest

from customer_urban_plan_tree import (
    NO_SUBSECTION_TEXT,
    UNASSIGNED_PLAN_ID,
    UNASSIGNED_PLAN_NAME,
    all_expandable_keys,
    build_plan_tree,
    default_expanded_keys,
)


def record(record_id, land_id, *, plan=None, owner="王", owner_id=None, section="龍岡段",
           subsection="", land_number="1-0", area="100", numerator="1", denominator="2",
           district="中壢區"):
    raw = {
        "land_id": land_id,
        "district": district,
        "section": section,
        "subsection": subsection,
        "land_number": land_number,
        "area": area,
        "numerator": numerator,
        "denominator": denominator,
        "share": f"{numerator}/{denominator}",
        "owner_name": owner,
        "registration_order": f"{record_id:04d}",
        "urban_plan_id": plan[0] if plan else None,
        "urban_plan_name": plan[1] if plan else "",
    }
    return {
        "id": record_id,
        "land_id": land_id,
        "owner_id": owner_id if owner_id is not None else record_id,
        "raw": raw,
        "display": dict(raw),
    }


LONGGANG = (1, "龍岡都市計畫")
DANAN = (2, "大湳都市計畫")


class PlanTreeTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            record(1, 10, plan=LONGGANG, owner="甲", land_number="221-0", area="200"),
            record(2, 10, plan=LONGGANG, owner="乙", land_number="221-0", area="200"),
            record(3, 11, plan=LONGGANG, owner="甲", owner_id=1, land_number="9-0", area="50"),
            record(4, 12, plan=LONGGANG, owner="丙", section="忠福段", subsection="一小段",
                   land_number="3-0", area="30"),
            record(5, 20, plan=DANAN, owner="丁", section="大湳段", land_number="7-0", area="70"),
            record(6, 30, plan=None, owner="戊", section="未定段", land_number="1-0", area="10"),
        ]
        self.plans = [{"plan_id": 1, "name": "龍岡都市計畫"}, {"plan_id": 2, "name": "大湳都市計畫"},
                      {"plan_id": 3, "name": "空的都市計畫"}]

    def titles(self, node):
        return [child.title for child in node.children]

    def test_levels_follow_plan_section_subsection_land_owner(self):
        tree = build_plan_tree(self.records, self.plans)
        self.assertEqual([root.title for root in tree.roots],
                         ["大湳都市計畫", "空的都市計畫", "龍岡都市計畫", UNASSIGNED_PLAN_NAME])
        longgang = next(root for root in tree.roots if root.plan_id == 1)
        self.assertEqual(self.titles(longgang), ["中壢區忠福段", "中壢區龍岡段"])
        zhongfu = longgang.children[0]
        self.assertEqual(self.titles(zhongfu), ["一小段"])
        self.assertEqual(self.titles(zhongfu.children[0]), ["3-0"])
        self.assertEqual(self.titles(zhongfu.children[0].children[0]), ["丙"])
        longgang_section = longgang.children[1]
        self.assertEqual(self.titles(longgang_section), [NO_SUBSECTION_TEXT])
        # parcel numbers sort naturally: 9 before 221
        self.assertEqual(self.titles(longgang_section.children[0]), ["9-0", "221-0"])
        self.assertEqual(
            [node.kind for node in longgang.walk()],
            ["plan", "section", "subsection", "land", "owner",
             "section", "subsection", "land", "owner", "land", "owner", "owner"],
        )

    def test_unassigned_is_always_last_and_empty_plans_can_be_hidden(self):
        tree = build_plan_tree(self.records, self.plans, include_empty_plans=False)
        self.assertEqual([root.title for root in tree.roots],
                         ["大湳都市計畫", "龍岡都市計畫", UNASSIGNED_PLAN_NAME])
        no_unassigned = build_plan_tree([r for r in self.records if r["id"] != 6], self.plans)
        self.assertNotIn(UNASSIGNED_PLAN_NAME, [root.title for root in no_unassigned.roots])
        self.assertEqual(no_unassigned.plan_count, 3)

    def test_counts_roll_up_without_double_counting(self):
        tree = build_plan_tree(self.records, self.plans)
        longgang = next(root for root in tree.roots if root.plan_id == 1)
        self.assertEqual(longgang.share_count, 4)
        self.assertEqual(longgang.owner_count, 3)  # 甲 owns two shares, in two lands
        self.assertEqual(longgang.area, 280.0)  # land areas, not area x owners
        self.assertEqual(len(longgang.land_ids), 3)
        land = longgang.children[1].children[0].children[1]
        self.assertEqual((land.title, land.owner_count, land.share_count, land.area), ("221-0", 2, 2, 200.0))
        self.assertEqual(sorted(land.record_ids), [1, 2])
        self.assertEqual(sorted(longgang.record_ids), [1, 2, 3, 4])
        self.assertEqual((tree.land_count, tree.share_count, tree.owner_count, tree.plan_count), (5, 6, 5, 3))
        self.assertEqual(tree.area, 360.0)

    def test_owner_rows_show_their_share_and_area(self):
        tree = build_plan_tree(self.records, self.plans)
        owner = tree.node_for_record(1)
        self.assertEqual((owner.title, owner.share_text, owner.kind), ("甲", "1/2", "owner"))
        self.assertEqual(owner.area, 100.0)  # 200 x 1/2
        self.assertEqual(owner.area_text, "100.00")
        self.assertIs(owner.parent.parent.parent.parent.parent, None)

    def test_a_single_plan_filter_shows_only_that_plan(self):
        tree = build_plan_tree(self.records, self.plans, plan_filter=2)
        self.assertEqual([root.title for root in tree.roots], ["大湳都市計畫"])
        self.assertEqual((tree.land_count, tree.share_count), (1, 1))
        self.assertIsNone(tree.node_for_record(1))
        empty = build_plan_tree(self.records, self.plans, plan_filter=3)
        self.assertEqual([root.title for root in empty.roots], ["空的都市計畫"])
        self.assertEqual(empty.land_count, 0)

    def test_unassigned_filter_shows_only_unclassified_lands(self):
        tree = build_plan_tree(self.records, self.plans, plan_filter=UNASSIGNED_PLAN_ID)
        self.assertEqual([root.title for root in tree.roots], [UNASSIGNED_PLAN_NAME])
        self.assertEqual(tree.share_count, 1)
        none_left = build_plan_tree([], self.plans, plan_filter=UNASSIGNED_PLAN_ID)
        self.assertEqual([root.title for root in none_left.roots], [UNASSIGNED_PLAN_NAME])

    def test_a_plan_the_list_does_not_know_still_appears_by_its_row_name(self):
        tree = build_plan_tree(self.records, [], include_empty_plans=False)
        self.assertIn("龍岡都市計畫", [root.title for root in tree.roots])

    def test_a_land_takes_its_plan_from_any_of_its_rows(self):
        records = [record(1, 10, plan=None), record(2, 10, plan=LONGGANG)]
        tree = build_plan_tree(records, self.plans, include_empty_plans=False)
        self.assertEqual([root.title for root in tree.roots], ["龍岡都市計畫"])

    def test_default_expansion_opens_plans_only(self):
        tree = build_plan_tree(self.records, self.plans)
        keys = default_expanded_keys(tree)
        self.assertEqual({tree.nodes[key].kind for key in keys}, {"plan"})
        self.assertEqual({tree.nodes[key].kind for key in default_expanded_keys(tree, depth=2)},
                         {"plan", "section"})
        self.assertTrue(all(tree.nodes[key].children for key in all_expandable_keys(tree)))
        self.assertEqual({tree.nodes[key].kind for key in all_expandable_keys(tree)},
                         {"plan", "section", "subsection", "land"})

    def test_node_keys_are_unique_and_stable_between_builds(self):
        first = build_plan_tree(self.records, self.plans)
        second = build_plan_tree(list(reversed(self.records)), self.plans)
        keys = [node.key for node in first.walk()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), {node.key for node in second.walk()})

    def test_records_without_any_parcel_identity_are_not_merged(self):
        blank = [record(1, None, section="", land_number="", district=""),
                 record(2, None, section="", land_number="", district="")]
        for item in blank:
            item["land_id"] = None
            item["raw"]["land_id"] = None
        tree = build_plan_tree(blank, self.plans, include_empty_plans=False)
        self.assertEqual(tree.land_count, 2)


if __name__ == "__main__":
    unittest.main()
