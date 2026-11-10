"""Pure 都市計畫 → 地段 → 小段 → 地號 → 地主 grouping for the plan view.

Nothing here touches Qt: the plan view feeds it the same processed records the
land tree uses and gets back a node tree, so the grouping rules can be tested
without a window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from customer_domain import parse_number
from customer_land_tree import (
    land_identity,
    normalized_land_number_key,
    owner_identity,
    ownership_area,
)

UNASSIGNED_PLAN_ID = 0
UNASSIGNED_PLAN_NAME = "未分類"
NO_SUBSECTION_TEXT = "（無小段）"
NO_OWNER_NAME_TEXT = "（未填姓名）"
LEVEL_LABELS = {
    "plan": "都市計畫",
    "section": "地段",
    "subsection": "小段",
    "land": "地號",
    "owner": "地主",
}


@dataclass(eq=False)
class PlanTreeNode:
    kind: str
    key: tuple
    title: str
    parent: "PlanTreeNode | None" = None
    children: list = field(default_factory=list)
    plan_id: int = UNASSIGNED_PLAN_ID
    owner_count: int = 0
    share_count: int = 0
    area: float = 0.0
    has_area: bool = False
    land_ids: tuple = ()
    record_ids: tuple = ()
    record: dict | None = None
    share_text: str = ""

    @property
    def level_label(self):
        return LEVEL_LABELS[self.kind]

    @property
    def area_text(self):
        return f"{self.area:,.2f}" if self.has_area else ""

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(eq=False)
class PlanTree:
    roots: list
    plan_count: int = 0
    land_count: int = 0
    owner_count: int = 0
    share_count: int = 0
    area: float = 0.0
    nodes: dict = field(default_factory=dict)
    owner_nodes: dict = field(default_factory=dict)

    def walk(self):
        for root in self.roots:
            yield from root.walk()

    def node_for_record(self, record_id):
        return self.owner_nodes.get(int(record_id))


def _text(raw, key):
    return str(raw.get(key) or "").strip()


def _plan_id(value):
    try:
        result = int(value)
    except (TypeError, ValueError):
        return UNASSIGNED_PLAN_ID
    return result if result > 0 else UNASSIGNED_PLAN_ID


def _plan_sort_key(node):
    # 未分類 always comes last, whatever the plans are called.
    return (node.plan_id == UNASSIGNED_PLAN_ID, node.title.casefold(), node.plan_id)


def _owner_title(record):
    display = record.get("display") or {}
    raw = record.get("raw") or {}
    return str(display.get("owner_name") or raw.get("owner_name") or "").strip()


def _owner_sort_key(record):
    raw = record.get("raw") or {}
    return (
        normalized_land_number_key(raw.get("registration_order")),
        _owner_title(record).casefold(),
        int(record.get("id") or 0),
    )


def _node(kind, key, title, parent, plan_id):
    node = PlanTreeNode(kind=kind, key=key, title=title, parent=parent, plan_id=plan_id)
    if parent is not None:
        parent.children.append(node)
    return node


def _plain_ids(values):
    return tuple(sorted({int(value) for value in values if value not in (None, "")}))


def build_plan_tree(records, plans=(), *, plan_filter=None, include_empty_plans=True):
    """Group `records` into the plan tree.

    `plans` is the known plan list (dicts with plan_id/name) so a plan without
    any land can still be shown. `plan_filter` is None for everything,
    UNASSIGNED_PLAN_ID for 未分類 only, or a plan id for that one plan only.
    """

    names = {}
    for plan in plans or ():
        plan_id = _plan_id(plan.get("plan_id", plan.get("id")))
        if plan_id:
            names[plan_id] = str(plan.get("name") or "").strip()

    lands = {}
    for record in records:
        lands.setdefault(land_identity(record), []).append(record)

    by_plan = {}
    for identity, land_records in lands.items():
        plan_id = UNASSIGNED_PLAN_ID
        for record in land_records:
            plan_id = _plan_id((record.get("raw") or {}).get("urban_plan_id"))
            if plan_id:
                break
        if plan_filter is not None and plan_id != plan_filter:
            continue
        by_plan.setdefault(plan_id, []).append((identity, land_records))
        if plan_id and plan_id not in names:
            raw = land_records[0].get("raw") or {}
            names[plan_id] = _text(raw, "urban_plan_name") or f"都市計畫 {plan_id}"

    wanted = set(by_plan)
    if include_empty_plans:
        wanted.update(
            plan_id
            for plan_id in names
            if plan_filter is None or plan_filter == plan_id
        )
    if plan_filter is not None:
        wanted.add(plan_filter)

    tree = PlanTree(roots=[])
    all_owners = set()
    for plan_id in wanted:
        title = UNASSIGNED_PLAN_NAME if plan_id == UNASSIGNED_PLAN_ID else names.get(plan_id, "")
        if plan_id == UNASSIGNED_PLAN_ID and not by_plan.get(plan_id) and plan_filter is None:
            continue  # nothing unclassified: no empty 未分類 group in the overview
        if not title:
            continue
        plan_node = _node("plan", ("plan", plan_id), title, None, plan_id)
        tree.roots.append(plan_node)

        sections = {}
        for identity, land_records in by_plan.get(plan_id, ()):
            raw = land_records[0].get("raw") or {}
            sections.setdefault((_text(raw, "district"), _text(raw, "section")), {}) \
                .setdefault(_text(raw, "subsection"), []).append((identity, land_records))

        for (district, section), subsections in sorted(
            sections.items(), key=lambda item: (item[0][0].casefold(), item[0][1].casefold())
        ):
            section_title = f"{district}{section}" or "（未填地段）"
            section_node = _node(
                "section", ("section", plan_id, district, section), section_title, plan_node, plan_id
            )
            for subsection, subsection_lands in sorted(
                subsections.items(), key=lambda item: item[0].casefold()
            ):
                subsection_node = _node(
                    "subsection",
                    ("subsection", plan_id, district, section, subsection),
                    subsection or NO_SUBSECTION_TEXT,
                    section_node,
                    plan_id,
                )
                for identity, land_records in sorted(
                    subsection_lands,
                    key=lambda item: normalized_land_number_key(
                        (item[1][0].get("raw") or {}).get("land_number")
                    ),
                ):
                    _build_land(subsection_node, identity, land_records, plan_id, tree)
        all_owners |= _finalize(plan_node)

    tree.roots.sort(key=_plan_sort_key)
    tree.plan_count = sum(1 for root in tree.roots if root.plan_id != UNASSIGNED_PLAN_ID)
    tree.share_count = sum(root.share_count for root in tree.roots)
    tree.area = sum(root.area for root in tree.roots)
    tree.owner_count = len(all_owners)
    for node in tree.walk():
        tree.nodes[node.key] = node
        if node.kind == "land":
            tree.land_count += 1
    return tree


def _build_land(subsection_node, identity, land_records, plan_id, tree):
    representative = land_records[0]
    raw = representative.get("raw") or {}
    land_node = _node(
        "land",
        ("land", plan_id, identity),
        _text(raw, "land_number") or "（未填地號）",
        subsection_node,
        plan_id,
    )
    area = parse_number(raw.get("area"))
    land_node.has_area = area is not None
    land_node.area = area or 0.0
    land_node.land_ids = _plain_ids(
        [record.get("land_id") or raw.get("land_id") for record in land_records[:1]]
    )
    for record in sorted(land_records, key=_owner_sort_key):
        owner_raw = record.get("raw") or {}
        owner = _node(
            "owner",
            ("owner", int(record["id"])),
            _owner_title(record) or NO_OWNER_NAME_TEXT,
            land_node,
            plan_id,
        )
        owner.record = record
        owner.record_ids = (int(record["id"]),)
        owner.share_count = 1
        owner.owner_count = 1
        owner.share_text = _text(owner_raw, "share")
        share_area = ownership_area(record)
        owner.has_area = share_area is not None
        owner.area = share_area or 0.0
        tree.owner_nodes[int(record["id"])] = owner


def _finalize(node):
    """Roll counts up from the lands; returns the distinct owner keys below."""

    if node.kind == "owner":
        return {owner_identity(node.record)}
    owners = set()
    record_ids = []
    land_ids = []
    share_count = 0
    area = 0.0
    has_area = False
    for child in node.children:
        owners |= _finalize(child)
        record_ids.extend(child.record_ids)
        land_ids.extend(child.land_ids)
        share_count += child.share_count
        if child.kind != "owner":
            area += child.area
            has_area = has_area or child.has_area
    node.owner_count = len(owners)
    node.share_count = share_count
    node.record_ids = tuple(record_ids)
    if node.kind == "land":
        # A land's own area was set when it was built: the owner rows below it
        # carry shares of it, and adding those up would count it twice.
        return owners
    node.land_ids = tuple(land_ids)
    node.area = area
    node.has_area = has_area
    return owners


def default_expanded_keys(tree, *, depth=1):
    """Keys of the nodes to open by default: the plans (and, for `depth` 2,
    their sections)."""

    levels = {"plan": 0, "section": 1, "subsection": 2, "land": 3}
    return {
        node.key
        for node in tree.walk()
        if node.kind in levels and levels[node.kind] < depth
    }


def all_expandable_keys(tree):
    return {node.key for node in tree.walk() if node.children}
