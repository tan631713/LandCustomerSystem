import time
import unittest

from customer_api.field_visit_routing import (
    RouteCandidate,
    haversine_km,
    optimize_route,
    validate_coordinate,
)


class FieldVisitRoutingTests(unittest.TestCase):
    def test_haversine_distance(self):
        distance = haversine_km(25.0330, 121.5654, 25.0478, 121.5319)
        self.assertAlmostEqual(distance, 3.75, delta=0.15)
        self.assertEqual(haversine_km(25.0330, 121.5654, 25.0330, 121.5654), 0)

    def test_gps_validation(self):
        self.assertEqual(validate_coordinate("25.0", "121.5"), (25.0, 121.5))
        for latitude, longitude in (
            (91, 121),
            (-91, 121),
            (25, 181),
            (25, -181),
            (float("nan"), 121),
        ):
            with self.subTest(latitude=latitude, longitude=longitude):
                with self.assertRaises(ValueError):
                    validate_coordinate(latitude, longitude)

    def test_nearest_neighbour_sort(self):
        route = optimize_route(
            [
                RouteCandidate(1, 25.03, 121.50),
                RouteCandidate(2, 25.01, 121.50),
                RouteCandidate(3, 25.02, 121.50),
            ],
            25.0,
            121.5,
        )
        self.assertEqual([item.item_id for item in route], [2, 3, 1])
        self.assertEqual([item.route_order for item in route], [1, 2, 3])
        self.assertTrue(all(item.estimated_distance_km is not None for item in route))

    def test_higher_priority_is_planned_before_normal_items(self):
        route = optimize_route(
            [
                RouteCandidate(1, 25.001, 121.5),
                RouteCandidate(2, 25.03, 121.5, priority=10),
                RouteCandidate(3, 25.02, 121.5, priority=10),
            ],
            25.0,
            121.5,
        )
        self.assertEqual([item.item_id for item in route], [3, 2, 1])

    def test_postponed_items_are_after_normal_items(self):
        route = optimize_route(
            [
                RouteCandidate(1, 25.001, 121.5, status="postponed", priority=99),
                RouteCandidate(2, 25.03, 121.5),
            ],
            25.0,
            121.5,
        )
        self.assertEqual([item.item_id for item in route], [2, 1])

    def test_items_without_coordinates_are_last(self):
        route = optimize_route(
            [
                RouteCandidate(1, priority=99),
                RouteCandidate(2, 25.03, 121.5),
                RouteCandidate(3, status="postponed"),
            ],
            25.0,
            121.5,
        )
        self.assertEqual([item.item_id for item in route], [2, 1, 3])
        self.assertIsNone(route[1].estimated_distance_km)
        self.assertIsNone(route[2].estimated_distance_km)

    def test_completed_cancelled_and_skipped_items_do_not_participate(self):
        candidates = [
            RouteCandidate(1, 25.01, 121.5, status="completed"),
            RouteCandidate(2, 25.02, 121.5, status="cancelled"),
            RouteCandidate(3, 25.03, 121.5, status="skipped"),
            RouteCandidate(4, 25.04, 121.5),
        ]
        route = optimize_route(candidates, 25.0, 121.5)
        self.assertEqual([item.item_id for item in route], [4])

        route_with_skipped = optimize_route(
            candidates, 25.0, 121.5, include_skipped=True
        )
        self.assertEqual([item.item_id for item in route_with_skipped], [3, 4])

    def test_manual_locked_items_retain_requested_slots(self):
        route = optimize_route(
            [
                RouteCandidate(1, 25.01, 121.5),
                RouteCandidate(
                    2,
                    25.04,
                    121.5,
                    route_order=2,
                    is_order_locked=True,
                ),
                RouteCandidate(3, 25.02, 121.5),
                RouteCandidate(
                    4,
                    25.03,
                    121.5,
                    route_order=4,
                    is_order_locked=True,
                ),
            ],
            25.0,
            121.5,
        )
        self.assertEqual(route[1].item_id, 2)
        self.assertEqual(route[3].item_id, 4)
        self.assertEqual({item.item_id for item in route}, {1, 2, 3, 4})

    def test_current_item_can_be_kept_first(self):
        route = optimize_route(
            [
                RouteCandidate(1, 25.01, 121.5),
                RouteCandidate(2, 25.04, 121.5, status="in_progress"),
                RouteCandidate(3, 25.02, 121.5),
            ],
            25.0,
            121.5,
            keep_current_item_id=2,
        )
        self.assertEqual(route[0].item_id, 2)

    def test_invalid_candidates_are_rejected(self):
        with self.assertRaises(ValueError):
            optimize_route(
                [RouteCandidate(1, 25.0, None)],
                25.0,
                121.5,
            )
        with self.assertRaises(ValueError):
            optimize_route(
                [RouteCandidate(1), RouteCandidate(1)],
                25.0,
                121.5,
            )
        with self.assertRaises(ValueError):
            optimize_route(
                [RouteCandidate(1, status="unknown")],
                25.0,
                121.5,
            )

    def test_supported_route_volumes_complete_without_abnormal_delay(self):
        total_started = time.perf_counter()
        for size in (10, 100, 1000):
            with self.subTest(size=size):
                candidates = [
                    RouteCandidate(
                        item_id=index + 1,
                        latitude=24.5 + (index % 100) * 0.001,
                        longitude=120.5 + (index // 100) * 0.001,
                        status="postponed" if index % 29 == 0 else "planned",
                        priority=100 if index % 17 == 0 else 0,
                    )
                    for index in range(size)
                ]
                route = optimize_route(candidates, 24.5, 120.5)

                route_ids = [item.item_id for item in route]
                self.assertEqual(len(route), size)
                self.assertEqual(set(route_ids), set(range(1, size + 1)))
                self.assertEqual(len(route_ids), len(set(route_ids)))
                self.assertEqual(
                    [item.route_order for item in route],
                    list(range(1, size + 1)),
                )

        self.assertLess(time.perf_counter() - total_started, 5.0)


if __name__ == "__main__":
    unittest.main()
