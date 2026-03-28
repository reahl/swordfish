import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
from tkinter import ttk

from reahl.ptongue import GemstoneError

from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.navigation import NavigationHistory
from reahl.swordfish.selection_list import InteractiveSelectionList
from reahl.swordfish.ui_support import (
    UML_HEADER_HEIGHT,
    UML_METHOD_LINE_HEIGHT,
    UML_NODE_MIN_HEIGHT,
    UML_NODE_PADDING_X,
    UML_NODE_PADDING_Y,
    UML_NODE_WIDTH,
    UML_NODES_PER_ROW,
    UML_ORIGIN_X,
    UML_ORIGIN_Y,
    add_close_command_to_popup_menu,
    popup_menu,
)


def format_class_diagram_method_label(show_instance_side, method_selector):
    if show_instance_side:
        return method_selector
    return f'class>>{method_selector}'


class UmlClassDiagramMethodChooserDialog(tk.Toplevel):
    def __init__(self, parent, application, class_name, on_method_selected):
        super().__init__(parent)
        self.application = application
        self.class_name = class_name
        self.on_method_selected = on_method_selected
        self.selected_method_category = None
        self.selected_method_selector = None
        self.side_var = tk.StringVar(value="instance")

        self.title(f"Add Method to Class Diagram: {class_name}")
        self.geometry("620x420")
        self.transient(parent)
        self.grab_set()

        controls_frame = ttk.Frame(self)
        controls_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        ttk.Label(controls_frame, text=class_name).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 12),
        )
        self.instance_radiobutton = ttk.Radiobutton(
            controls_frame,
            text="Instance",
            variable=self.side_var,
            value="instance",
            command=self.handle_side_changed,
        )
        self.instance_radiobutton.grid(row=0, column=1, sticky="w")
        self.class_radiobutton = ttk.Radiobutton(
            controls_frame,
            text="Class",
            variable=self.side_var,
            value="class",
            command=self.handle_side_changed,
        )
        self.class_radiobutton.grid(row=0, column=2, sticky="w", padx=(8, 0))
        controls_frame.columnconfigure(3, weight=1)

        lists_frame = ttk.Frame(self)
        lists_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        lists_frame.columnconfigure(0, weight=1)
        lists_frame.columnconfigure(1, weight=1)
        lists_frame.rowconfigure(1, weight=1)

        ttk.Label(lists_frame, text="Categories").grid(row=0, column=0, sticky="w")
        ttk.Label(lists_frame, text="Methods").grid(row=0, column=1, sticky="w")

        self.category_selection = InteractiveSelectionList(
            lists_frame,
            self.get_all_categories,
            self.get_selected_category,
            self.select_category,
        )
        self.category_selection.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.method_selection = InteractiveSelectionList(
            lists_frame,
            self.get_all_methods,
            self.get_selected_method,
            self.select_method,
        )
        self.method_selection.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        self.method_selection.selection_listbox.bind(
            "<Double-1>",
            self.add_selected_method,
        )

        buttons_frame = ttk.Frame(self)
        buttons_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        buttons_frame.columnconfigure(0, weight=1)
        self.add_button = ttk.Button(
            buttons_frame,
            text="Add",
            command=self.add_selected_method,
            state=tk.DISABLED,
        )
        self.add_button.grid(row=0, column=1)
        ttk.Button(
            buttons_frame,
            text="Cancel",
            command=self.destroy,
        ).grid(row=0, column=2, padx=(6, 0))

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.repopulate()

    @property
    def show_instance_side(self):
        return self.side_var.get() == "instance"

    def repopulate(self):
        self.selected_method_category = None
        self.selected_method_selector = None
        self.category_selection.repopulate()
        category_entries = list(self.category_selection.selection_listbox.get(0, "end"))
        if category_entries:
            self.select_category(category_entries[0])
        if not category_entries:
            self.method_selection.repopulate()
            self.refresh_add_button()

    def get_all_categories(self):
        categories = list(
            self.application.gemstone_session_record.get_categories_in_class(
                self.class_name,
                self.show_instance_side,
            )
        )
        return ["all"] + categories

    def get_selected_category(self):
        return self.selected_method_category

    def select_category(self, selected_category):
        self.selected_method_category = selected_category
        self.selected_method_selector = None
        self.method_selection.repopulate()
        self.refresh_add_button()

    def get_all_methods(self):
        if self.selected_method_category is None:
            return []
        return list(
            self.application.gemstone_session_record.get_selectors_in_class(
                self.class_name,
                self.selected_method_category,
                self.show_instance_side,
            )
        )

    def get_selected_method(self):
        return self.selected_method_selector

    def select_method(self, selected_method):
        self.selected_method_selector = selected_method
        self.refresh_add_button()

    def refresh_add_button(self):
        button_state = tk.NORMAL if self.selected_method_selector else tk.DISABLED
        self.add_button.configure(state=button_state)

    def handle_side_changed(self):
        self.repopulate()

    def add_selected_method(self, event=None):
        if not self.selected_method_selector:
            return
        self.on_method_selected(
            self.class_name,
            self.show_instance_side,
            self.selected_method_selector,
        )
        self.destroy()


class UmlClassNode:
    def __init__(self, class_definition):
        self.class_name = class_definition.get("class_name") or ""
        self.superclass_name = class_definition.get("superclass_name")
        self.inst_var_names = list(class_definition.get("inst_var_names") or [])
        self.pinned_methods = []
        self.x = 0
        self.y = 0
        self.canvas_item_ids = []

    def update_from_definition(self, class_definition):
        self.superclass_name = class_definition.get("superclass_name")
        self.inst_var_names = list(class_definition.get("inst_var_names") or [])

    def height(self):
        method_count = len(self.pinned_methods)
        if method_count == 0:
            return UML_NODE_MIN_HEIGHT
        return UML_HEADER_HEIGHT + 14 + method_count * UML_METHOD_LINE_HEIGHT + 12

    def bounding_box(self):
        half_width = UML_NODE_WIDTH // 2
        half_height = self.height() // 2
        return (
            self.x - half_width,
            self.y - half_height,
            self.x + half_width,
            self.y + half_height,
        )


class UmlClassRelationship:
    def __init__(
        self,
        source_node,
        target_node,
        label,
        relationship_kind,
        relationship_style="direct",
    ):
        self.source_node = source_node
        self.target_node = target_node
        self.label = label
        self.relationship_kind = relationship_kind
        self.relationship_style = relationship_style
        self.canvas_item_ids = []


class UmlClassDiagramRegistry:
    def __init__(self):
        self.nodes_by_class_name = {}
        self.relationships = []

    def class_node_for(self, class_name):
        return self.nodes_by_class_name.get(class_name)

    def register_node(self, node):
        self.nodes_by_class_name[node.class_name] = node

    def remove_node(self, class_name):
        node = self.nodes_by_class_name.pop(class_name, None)
        if node is None:
            return []
        relationships_to_remove = []
        for relationship in self.relationships:
            touches_node = (
                relationship.source_node is node or relationship.target_node is node
            )
            if touches_node:
                relationships_to_remove.append(relationship)
        self.relationships = [
            relationship
            for relationship in self.relationships
            if relationship not in relationships_to_remove
        ]
        return relationships_to_remove

    def add_relationship(
        self,
        source_node,
        target_node,
        label,
        relationship_kind,
        relationship_style="direct",
    ):
        existing_relationship = None
        for relationship in self.relationships:
            is_same_relationship = (
                relationship.source_node is source_node
                and relationship.target_node is target_node
                and relationship.label == label
                and relationship.relationship_kind == relationship_kind
                and relationship.relationship_style == relationship_style
            )
            if is_same_relationship:
                existing_relationship = relationship
        if existing_relationship is not None:
            return None
        relationship = UmlClassRelationship(
            source_node,
            target_node,
            label,
            relationship_kind,
            relationship_style,
        )
        self.relationships.append(relationship)
        return relationship

    def remove_relationship(self, relationship):
        if relationship in self.relationships:
            self.relationships.remove(relationship)

    def remove_relationships_by_kind(self, relationship_kind):
        relationships_to_remove = []
        for relationship in self.relationships:
            if relationship.relationship_kind == relationship_kind:
                relationships_to_remove.append(relationship)
        self.relationships = [
            relationship
            for relationship in self.relationships
            if relationship.relationship_kind != relationship_kind
        ]
        return relationships_to_remove

    def all_nodes(self):
        return list(self.nodes_by_class_name.values())

    def all_relationships(self):
        return list(self.relationships)

    def relationship_for_canvas_item(self, canvas_item_id):
        matching_relationship = None
        for relationship in self.relationships:
            if canvas_item_id in relationship.canvas_item_ids:
                matching_relationship = relationship
        return matching_relationship


class UmlClassDiagramCanvas(ttk.Frame):
    def __init__(self, parent, node_menu_action, relationship_menu_action):
        super().__init__(parent)
        self.node_menu_action = node_menu_action
        self.relationship_menu_action = relationship_menu_action
        self.registry = UmlClassDiagramRegistry()
        self.dragging_node = None
        self.drag_start_x = 0
        self.drag_start_y = 0

        self.canvas = tk.Canvas(
            self,
            bg="white",
            scrollregion=(0, 0, 2000, 2000),
        )
        horizontal_scrollbar = ttk.Scrollbar(
            self,
            orient="horizontal",
            command=self.canvas.xview,
        )
        vertical_scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.canvas.configure(
            xscrollcommand=horizontal_scrollbar.set,
            yscrollcommand=vertical_scrollbar.set,
        )

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)

    def add_or_update_class_node(self, class_definition):
        class_name = class_definition.get("class_name") or ""
        if not class_name:
            return None
        node = self.registry.class_node_for(class_name)
        if node is None:
            node = UmlClassNode(class_definition)
            self.place_new_node(node)
            self.registry.register_node(node)
        else:
            node.update_from_definition(class_definition)
        self.redraw_node(node)
        self.expand_scroll_region()
        return node

    def place_new_node(self, node):
        existing_count = len(self.registry.all_nodes())
        column_index = existing_count % UML_NODES_PER_ROW
        row_index = existing_count // UML_NODES_PER_ROW
        node.x = (
            UML_ORIGIN_X
            + column_index * (UML_NODE_WIDTH + UML_NODE_PADDING_X)
            + UML_NODE_WIDTH // 2
        )
        node.y = (
            UML_ORIGIN_Y
            + row_index * (UML_NODE_MIN_HEIGHT + 100 + UML_NODE_PADDING_Y)
            + UML_NODE_MIN_HEIGHT // 2
        )

    def redraw_node(self, node):
        for item_id in node.canvas_item_ids:
            self.canvas.delete(item_id)
        node.canvas_item_ids = []
        self.draw_node(node)
        self.redraw_all_relationships()

    def draw_node(self, node):
        x1, y1, x2, y2 = node.bounding_box()
        rectangle_id = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill="#fff9e6",
            outline="#8a6d1f",
            width=2,
        )
        divider_y = y1 + UML_HEADER_HEIGHT
        divider_id = self.canvas.create_line(
            x1,
            divider_y,
            x2,
            divider_y,
            fill="#8a6d1f",
            width=2,
        )
        class_text_id = self.canvas.create_text(
            node.x,
            y1 + 7,
            text=node.class_name,
            font=("TkDefaultFont", 10, "bold"),
            fill="#533f05",
            anchor="n",
        )
        node.canvas_item_ids.extend([rectangle_id, divider_id, class_text_id])
        method_index = 0
        for method_entry in node.pinned_methods:
            method_y = divider_y + 8 + method_index * UML_METHOD_LINE_HEIGHT
            method_id = self.canvas.create_text(
                x1 + 8,
                method_y,
                text=method_entry["label"],
                font=("TkDefaultFont", 9),
                fill="#222222",
                anchor="nw",
            )
            node.canvas_item_ids.append(method_id)
            method_index += 1

    def edge_boundary_point(self, from_node, toward_node):
        delta_x = toward_node.x - from_node.x
        delta_y = toward_node.y - from_node.y
        half_width = UML_NODE_WIDTH / 2
        half_height = from_node.height() / 2
        if delta_x == 0 and delta_y == 0:
            return from_node.x + half_width, from_node.y
        scale_x = abs(half_width / delta_x) if delta_x != 0 else float("inf")
        scale_y = abs(half_height / delta_y) if delta_y != 0 else float("inf")
        scale = min(scale_x, scale_y)
        return from_node.x + delta_x * scale, from_node.y + delta_y * scale

    def draw_relationship(self, relationship):
        relationship.canvas_item_ids = []
        fill = "#444444"
        width = 1.5
        if relationship.relationship_kind == "inheritance":
            fill = "#2266aa"
            width = 2
            if relationship.relationship_style == "inferred":
                fill = "#9aa4b2"
        x1, y1 = self.edge_boundary_point(
            relationship.source_node,
            relationship.target_node,
        )
        x2, y2 = self.edge_boundary_point(
            relationship.target_node,
            relationship.source_node,
        )
        line_id = self.canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            arrow=tk.LAST,
            arrowshape=(12, 14, 6),
            fill=fill,
            width=width,
        )
        relationship.canvas_item_ids.append(line_id)
        should_draw_label = bool(relationship.label)
        if should_draw_label:
            midpoint_x = (x1 + x2) / 2
            midpoint_y = (y1 + y2) / 2
            label_id = self.canvas.create_text(
                midpoint_x,
                midpoint_y - 10,
                text=relationship.label,
                font=("TkDefaultFont", 9),
                fill="#222288",
                anchor="s",
            )
            relationship.canvas_item_ids.append(label_id)

    def draw_inheritance_group(self, relationships):
        if not relationships:
            return
        parent_node = relationships[0].target_node
        ordered_relationships = sorted(
            relationships,
            key=lambda relationship: (
                relationship.source_node.x,
                relationship.source_node.class_name,
            ),
        )
        child_nodes = [
            relationship.source_node for relationship in ordered_relationships
        ]
        parent_bottom_y = parent_node.bounding_box()[3]
        branch_y = parent_bottom_y + 28
        child_top_points = [
            (child_node.x, child_node.bounding_box()[1])
            for child_node in child_nodes
        ]
        child_left_x = min(point[0] for point in child_top_points)
        child_right_x = max(point[0] for point in child_top_points)
        horizontal_left_x = min(parent_node.x, child_left_x)
        horizontal_right_x = max(parent_node.x, child_right_x)
        has_direct_relationship = any(
            relationship.relationship_style == 'direct'
            for relationship in ordered_relationships
        )
        group_fill = '#9aa4b2'
        if has_direct_relationship:
            group_fill = '#2266aa'
        shared_canvas_item_ids = []
        stem_id = self.canvas.create_line(
            parent_node.x,
            branch_y,
            parent_node.x,
            parent_bottom_y,
            arrow=tk.LAST,
            arrowshape=(12, 14, 6),
            fill=group_fill,
            width=2,
        )
        shared_canvas_item_ids.append(stem_id)
        should_draw_horizontal_line = horizontal_left_x != horizontal_right_x
        if should_draw_horizontal_line:
            horizontal_id = self.canvas.create_line(
                horizontal_left_x,
                branch_y,
                horizontal_right_x,
                branch_y,
                fill=group_fill,
                width=2,
            )
            shared_canvas_item_ids.append(horizontal_id)
        for index, (child_x, child_top_y) in enumerate(child_top_points):
            relationship = ordered_relationships[index]
            branch_fill = '#2266aa'
            if relationship.relationship_style == 'inferred':
                branch_fill = '#9aa4b2'
            child_line_id = self.canvas.create_line(
                child_x,
                branch_y,
                child_x,
                child_top_y,
                fill=branch_fill,
                width=2,
            )
            relationship.canvas_item_ids = list(shared_canvas_item_ids)
            relationship.canvas_item_ids.append(child_line_id)

    def redraw_relationships_for_node(self, node):
        self.redraw_all_relationships()

    def clear_relationship_items(self):
        item_ids = set()
        for relationship in self.registry.all_relationships():
            for item_id in relationship.canvas_item_ids:
                item_ids.add(item_id)
        for item_id in item_ids:
            self.canvas.delete(item_id)
        for relationship in self.registry.all_relationships():
            relationship.canvas_item_ids = []

    def redraw_all_relationships(self):
        self.clear_relationship_items()
        inheritance_relationships_by_parent = {}
        other_relationships = []
        for relationship in self.registry.all_relationships():
            is_inheritance = relationship.relationship_kind == 'inheritance'
            if is_inheritance:
                parent_name = relationship.target_node.class_name
                grouped_relationships = inheritance_relationships_by_parent.get(
                    parent_name,
                    [],
                )
                grouped_relationships.append(relationship)
                inheritance_relationships_by_parent[parent_name] = (
                    grouped_relationships
                )
            if not is_inheritance:
                other_relationships.append(relationship)
        parent_names = sorted(inheritance_relationships_by_parent.keys())
        for parent_name in parent_names:
            relationships = inheritance_relationships_by_parent[parent_name]
            self.draw_inheritance_group(relationships)
        for relationship in other_relationships:
            self.draw_relationship(relationship)

    def delete_relationship_items(self, relationship):
        for item_id in relationship.canvas_item_ids:
            self.canvas.delete(item_id)
        relationship.canvas_item_ids = []

    def delete_node_items(self, node):
        for item_id in node.canvas_item_ids:
            self.canvas.delete(item_id)
        node.canvas_item_ids = []

    def add_relationship(
        self,
        source_node,
        target_node,
        label,
        relationship_kind,
        relationship_style="direct",
    ):
        relationship = self.registry.add_relationship(
            source_node,
            target_node,
            label,
            relationship_kind,
            relationship_style,
        )
        if relationship is not None:
            self.redraw_all_relationships()
            self.expand_scroll_region()
        return relationship

    def remove_relationship(self, relationship):
        self.registry.remove_relationship(relationship)
        self.redraw_all_relationships()
        self.expand_scroll_region()

    def remove_class_node(self, class_name):
        node = self.registry.class_node_for(class_name)
        if node is None:
            return
        relationships_to_remove = self.registry.remove_node(class_name)
        for relationship in relationships_to_remove:
            self.delete_relationship_items(relationship)
        self.delete_node_items(node)
        self.redraw_all_relationships()
        self.expand_scroll_region()

    def node_at_canvas_coordinates(self, canvas_x, canvas_y):
        for node in self.registry.all_nodes():
            x1, y1, x2, y2 = node.bounding_box()
            if x1 <= canvas_x <= x2 and y1 <= canvas_y <= y2:
                return node
        return None

    def relationship_at_canvas_coordinates(self, canvas_x, canvas_y):
        overlapping_item_ids = self.canvas.find_overlapping(
            canvas_x - 4,
            canvas_y - 4,
            canvas_x + 4,
            canvas_y + 4,
        )
        matching_relationship = None
        for canvas_item_id in reversed(overlapping_item_ids):
            relationship = self.registry.relationship_for_canvas_item(canvas_item_id)
            if relationship is not None:
                matching_relationship = relationship
        return matching_relationship

    def on_canvas_press(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        self.dragging_node = self.node_at_canvas_coordinates(canvas_x, canvas_y)
        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y

    def on_canvas_drag(self, event):
        if self.dragging_node is None:
            return
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        delta_x = canvas_x - self.drag_start_x
        delta_y = canvas_y - self.drag_start_y
        for item_id in self.dragging_node.canvas_item_ids:
            self.canvas.move(item_id, delta_x, delta_y)
        self.dragging_node.x += delta_x
        self.dragging_node.y += delta_y
        self.drag_start_x = canvas_x
        self.drag_start_y = canvas_y
        self.redraw_relationships_for_node(self.dragging_node)

    def on_canvas_release(self, event):
        self.dragging_node = None
        self.expand_scroll_region()

    def on_canvas_right_click(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        node = self.node_at_canvas_coordinates(canvas_x, canvas_y)
        if node is not None:
            self.node_menu_action(node, event)
            return
        relationship = self.relationship_at_canvas_coordinates(canvas_x, canvas_y)
        if relationship is not None:
            self.relationship_menu_action(relationship, event)

    def expand_scroll_region(self):
        all_nodes = self.registry.all_nodes()
        if not all_nodes:
            self.canvas.configure(scrollregion=(0, 0, 2000, 2000))
            return
        minimum_x = min(node.bounding_box()[0] for node in all_nodes) - UML_ORIGIN_X
        minimum_y = min(node.bounding_box()[1] for node in all_nodes) - UML_ORIGIN_Y
        maximum_x = max(node.bounding_box()[2] for node in all_nodes) + UML_ORIGIN_X
        maximum_y = max(node.bounding_box()[3] for node in all_nodes) + UML_ORIGIN_Y
        self.canvas.configure(
            scrollregion=(
                min(minimum_x, 0),
                min(minimum_y, 0),
                max(maximum_x, 2000),
                max(maximum_y, 2000),
            )
        )

    def clear_all(self):
        self.canvas.delete("all")
        self.registry = UmlClassDiagramRegistry()
        self.expand_scroll_region()


class UmlClassDiagramTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application
        self.current_context_menu = None
        self.diagram_history = NavigationHistory()

        actions_frame = ttk.Frame(self)
        actions_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        ttk.Label(actions_frame, text="Class Diagram").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Button(actions_frame, text="Clear", command=self.clear_diagram).grid(
            row=0,
            column=1,
            padx=(6, 0),
        )
        ttk.Button(
            actions_frame,
            text='Rearrange',
            command=self.rearrange_diagram,
        ).grid(row=0, column=2, padx=(6, 0))
        self.undo_button = ttk.Button(
            actions_frame,
            text="Undo",
            command=self.undo_diagram,
        )
        self.undo_button.grid(row=0, column=3, padx=(6, 0))
        ttk.Button(
            actions_frame,
            text="Close",
            command=self.application.close_class_diagram_tab,
        ).grid(row=0, column=4, padx=(6, 0))

        self.uml_canvas = UmlClassDiagramCanvas(
            self,
            node_menu_action=self.open_node_menu,
            relationship_menu_action=self.open_relationship_menu,
        )
        self.uml_canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.uml_canvas.canvas.bind("<Control-z>", self.undo_diagram)
        self.uml_canvas.canvas.bind("<Control-Z>", self.undo_diagram)

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self.record_diagram_snapshot()
        self.refresh_undo_controls()

    def snapshot_diagram(self):
        nodes = []
        for node in self.uml_canvas.registry.all_nodes():
            nodes.append(
                {
                    "class_name": node.class_name,
                    "superclass_name": node.superclass_name,
                    "inst_var_names": list(node.inst_var_names),
                    "pinned_methods": [dict(method_entry) for method_entry in node.pinned_methods],
                    "x": node.x,
                    "y": node.y,
                }
            )
        relationships = []
        for relationship in self.uml_canvas.registry.all_relationships():
            relationships.append(
                {
                    "source_class_name": relationship.source_node.class_name,
                    "target_class_name": relationship.target_node.class_name,
                    "label": relationship.label,
                    "relationship_kind": relationship.relationship_kind,
                    "relationship_style": relationship.relationship_style,
                }
            )
        return {
            "nodes": sorted(nodes, key=lambda entry: entry["class_name"]),
            "relationships": sorted(
                relationships,
                key=lambda entry: (
                    entry["relationship_kind"],
                    entry["relationship_style"],
                    entry["source_class_name"],
                    entry["target_class_name"],
                    entry["label"],
                ),
            ),
        }

    def restore_diagram_snapshot(self, snapshot):
        self.uml_canvas.clear_all()
        node_by_class_name = {}
        for node_entry in snapshot["nodes"]:
            class_definition = {
                "class_name": node_entry["class_name"],
                "superclass_name": node_entry["superclass_name"],
                "inst_var_names": list(node_entry["inst_var_names"]),
            }
            node = self.uml_canvas.add_or_update_class_node(class_definition)
            node.pinned_methods = [
                dict(method_entry) for method_entry in node_entry["pinned_methods"]
            ]
            node.x = node_entry["x"]
            node.y = node_entry["y"]
            self.uml_canvas.redraw_node(node)
            node_by_class_name[node.class_name] = node
        for relationship_entry in snapshot["relationships"]:
            source_node = node_by_class_name.get(relationship_entry["source_class_name"])
            target_node = node_by_class_name.get(relationship_entry["target_class_name"])
            if source_node is None or target_node is None:
                continue
            self.uml_canvas.add_relationship(
                source_node,
                target_node,
                relationship_entry["label"],
                relationship_entry["relationship_kind"],
                relationship_entry["relationship_style"],
            )
        self.uml_canvas.expand_scroll_region()

    def record_diagram_snapshot(self):
        self.diagram_history.record(self.snapshot_diagram())
        self.refresh_undo_controls()

    def refresh_undo_controls(self):
        undo_state = tk.NORMAL if self.diagram_history.can_go_back() else tk.DISABLED
        self.undo_button.configure(state=undo_state)

    def class_definition_for(self, class_name, show_errors=True):
        browser_session = self.application.gemstone_session_record.gemstone_browser_session
        try:
            return browser_session.get_class_definition(class_name)
        except (GemstoneDomainException, GemstoneError) as error:
            if show_errors:
                messagebox.showerror("Class Diagram", str(error))
            return None

    def add_class(self, class_name, record_history=True):
        class_definition = self.class_definition_for(class_name)
        if class_definition is None:
            return None
        snapshot_before = self.snapshot_diagram()
        node = self.uml_canvas.add_or_update_class_node(class_definition)
        self.refresh_inheritance_relationships()
        snapshot_after = self.snapshot_diagram()
        if record_history and snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
        self.application.event_queue.publish('ClassAddedToDiagram', log_context={'class_name': class_name})
        return node

    def pin_method(self, class_name, show_instance_side, method_selector):
        snapshot_before = self.snapshot_diagram()
        node = self.add_class(class_name, record_history=False)
        if node is None:
            return
        method_label = format_class_diagram_method_label(show_instance_side, method_selector)
        existing_method = None
        for method_entry in node.pinned_methods:
            is_same_method = (
                method_entry['selector'] == method_selector
                and method_entry['show_instance_side'] == show_instance_side
            )
            if is_same_method:
                existing_method = method_entry
        if existing_method is None:
            node.pinned_methods.append(
                {
                    'selector': method_selector,
                    'show_instance_side': show_instance_side,
                    'label': method_label,
                }
            )
            self.uml_canvas.redraw_node(node)
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
        self.application.event_queue.publish(
            'MethodPinnedToDiagram',
            log_context={'class_name': class_name, 'method': method_selector},
        )

    def open_node_menu(self, node, event):
        if self.current_context_menu is not None:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Browse Class",
            command=lambda: self.browse_class(node.class_name),
        )
        menu.add_command(
            label="Add Method...",
            command=lambda: self.open_add_method_dialog(node),
        )

        browse_method_menu = tk.Menu(menu, tearoff=0)
        has_pinned_methods = len(node.pinned_methods) > 0
        if has_pinned_methods:
            for method_entry in node.pinned_methods:
                browse_method_menu.add_command(
                    label=method_entry["label"],
                    command=lambda entry=method_entry: self.browse_method(
                        node.class_name,
                        entry,
                    ),
                )
            menu.add_cascade(label="Browse Method...", menu=browse_method_menu)
        if not has_pinned_methods:
            menu.add_command(
                label="Browse Method...",
                state=tk.DISABLED,
            )

        menu.add_separator()

        association_menu = tk.Menu(menu, tearoff=0)
        has_instvars = len(node.inst_var_names) > 0
        if has_instvars:
            for inst_var_name in node.inst_var_names:
                association_menu.add_command(
                    label=inst_var_name,
                    command=lambda name=inst_var_name: self.prompt_add_association(
                        node,
                        name,
                    ),
                )
            menu.add_cascade(label="Add Association...", menu=association_menu)
        if not has_instvars:
            menu.add_command(
                label="Add Association...",
                state=tk.DISABLED,
            )

        remove_method_menu = tk.Menu(menu, tearoff=0)
        if has_pinned_methods:
            for method_entry in node.pinned_methods:
                remove_method_menu.add_command(
                    label=method_entry["label"],
                    command=lambda entry=method_entry: self.remove_method_from_node(
                        node,
                        entry,
                    ),
                )
            menu.add_cascade(label="Remove Method...", menu=remove_method_menu)
        if not has_pinned_methods:
            menu.add_command(
                label="Remove Method...",
                state=tk.DISABLED,
            )

        menu.add_command(
            label="Remove From Class Diagram",
            command=lambda: self.remove_class_from_diagram(node.class_name),
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def open_relationship_menu(self, relationship, event):
        if self.current_context_menu is not None:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        can_expand_inheritance = (
            relationship.relationship_kind == "inheritance"
            and relationship.relationship_style == "inferred"
        )
        if can_expand_inheritance:
            menu.add_command(
                label="Add Inheritance Details",
                command=lambda: self.add_inheritance_details(relationship),
            )
        if not can_expand_inheritance:
            menu.add_command(
                label="Add Inheritance Details",
                state=tk.DISABLED,
            )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def browse_class(self, class_name):
        self.application.handle_find_selection(True, class_name)
        if self.application.browser_tab is not None and self.application.browser_tab.winfo_exists():
            self.application.notebook.select(self.application.browser_tab)

    def browse_method(self, class_name, method_entry):
        self.application.handle_sender_selection(
            class_name,
            method_entry["show_instance_side"],
            method_entry["selector"],
        )
        if self.application.browser_tab is not None and self.application.browser_tab.winfo_exists():
            self.application.notebook.select(self.application.browser_tab)

    def add_existing_method_to_node(self, class_name, show_instance_side, method_selector):
        self.pin_method(
            class_name,
            show_instance_side,
            method_selector,
        )

    def open_add_method_dialog(self, node):
        UmlClassDiagramMethodChooserDialog(
            self,
            self.application,
            node.class_name,
            self.add_existing_method_to_node,
        )

    def prompt_add_association(self, source_node, inst_var_name):
        target_class_name = simpledialog.askstring(
            "Add Class Diagram Association",
            f"Target class for {source_node.class_name}>>{inst_var_name}:",
            parent=self,
        )
        if target_class_name is None:
            return
        target_class_name = target_class_name.strip()
        if not target_class_name:
            return
        self.add_association(source_node.class_name, inst_var_name, target_class_name)

    def add_association(self, source_class_name, inst_var_name, target_class_name):
        snapshot_before = self.snapshot_diagram()
        source_node = self.add_class(source_class_name, record_history=False)
        if source_node is None:
            return None
        if inst_var_name not in source_node.inst_var_names:
            raise DomainException(
                f'{inst_var_name} is not an instance variable on {source_class_name}.'
            )
        target_node = self.add_class(target_class_name, record_history=False)
        if target_node is None:
            return None
        self.uml_canvas.add_relationship(
            source_node,
            target_node,
            inst_var_name,
            "association",
        )
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
        return self.uml_canvas.registry.class_node_for(target_class_name)

    def remove_method_from_node(self, node, method_entry):
        node.pinned_methods = [
            existing_entry
            for existing_entry in node.pinned_methods
            if existing_entry is not method_entry
        ]
        self.uml_canvas.redraw_node(node)
        self.record_diagram_snapshot()

    def remove_class_from_diagram(self, class_name):
        snapshot_before = self.snapshot_diagram()
        self.uml_canvas.remove_class_node(class_name)
        self.refresh_inheritance_relationships()
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
        self.application.event_queue.publish('ClassRemovedFromDiagram', log_context={'class_name': class_name})

    def inheritance_detail_class_names(self, relationship):
        if relationship.relationship_kind != "inheritance":
            return []
        if relationship.relationship_style != "inferred":
            return []
        class_names = []
        superclass_name = relationship.source_node.superclass_name
        while superclass_name and superclass_name != relationship.target_node.class_name:
            class_names.append(superclass_name)
            superclass_definition = self.class_definition_for(
                superclass_name, show_errors=False
            )
            if superclass_definition is None:
                superclass_name = None
            else:
                superclass_name = superclass_definition["superclass_name"]
        if superclass_name != relationship.target_node.class_name:
            return []
        return class_names

    def inferred_inheritance_relationship(
        self, source_class_name, target_class_name
    ):
        matching_relationship = None
        for relationship in self.uml_canvas.registry.all_relationships():
            is_matching_inferred_inheritance = (
                relationship.relationship_kind == 'inheritance'
                and relationship.relationship_style == 'inferred'
                and relationship.source_node.class_name == source_class_name
                and relationship.target_node.class_name == target_class_name
            )
            if is_matching_inferred_inheritance:
                matching_relationship = relationship
        return matching_relationship

    def add_inheritance_details(self, relationship):
        class_names = self.inheritance_detail_class_names(relationship)
        if not class_names:
            return []
        snapshot_before = self.snapshot_diagram()
        for class_name in class_names:
            self.add_class(class_name, record_history=False)
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
        return class_names

    def add_inheritance_details_for(self, source_class_name, target_class_name):
        relationship = self.inferred_inheritance_relationship(
            source_class_name,
            target_class_name,
        )
        if relationship is None:
            raise DomainException(
                'No inferred inheritance edge matches the requested classes.'
            )
        return self.add_inheritance_details(relationship)

    def refresh_inheritance_relationships(self):
        relationships_to_remove = self.uml_canvas.registry.remove_relationships_by_kind(
            "inheritance"
        )
        for relationship in relationships_to_remove:
            self.uml_canvas.delete_relationship_items(relationship)
        for node in self.uml_canvas.registry.all_nodes():
            superclass_name = node.superclass_name
            ancestor_distance = 1
            found_visible_ancestor = False
            while superclass_name and not found_visible_ancestor:
                superclass_node = self.uml_canvas.registry.class_node_for(superclass_name)
                if superclass_node is not None:
                    relationship_style = "direct"
                    if ancestor_distance > 1:
                        relationship_style = "inferred"
                    self.uml_canvas.add_relationship(
                        node,
                        superclass_node,
                        "",
                        "inheritance",
                        relationship_style,
                    )
                    found_visible_ancestor = True
                if not found_visible_ancestor:
                    superclass_definition = self.class_definition_for(
                        superclass_name, show_errors=False
                    )
                    if superclass_definition is None:
                        superclass_name = None
                    else:
                        superclass_name = superclass_definition["superclass_name"]
                        ancestor_distance += 1
        self.uml_canvas.expand_scroll_region()

    def clear_diagram(self):
        snapshot_before = self.snapshot_diagram()
        self.uml_canvas.clear_all()
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
            self.application.event_queue.publish('DiagramCleared')
            return True
        return False

    def visible_inheritance_paths(self):
        parent_by_child_name = {}
        children_by_parent_name = {}
        inheritance_relationships = [
            relationship
            for relationship in self.uml_canvas.registry.all_relationships()
            if relationship.relationship_kind == 'inheritance'
        ]
        for relationship in inheritance_relationships:
            child_name = relationship.source_node.class_name
            parent_name = relationship.target_node.class_name
            parent_by_child_name[child_name] = parent_name
            existing_children = children_by_parent_name.get(parent_name, [])
            existing_children.append(child_name)
            children_by_parent_name[parent_name] = existing_children
        return parent_by_child_name, children_by_parent_name

    def rearranged_node_levels(self, parent_by_child_name, children_by_parent_name):
        all_nodes = self.uml_canvas.registry.all_nodes()
        node_by_class_name = {
            node.class_name: node for node in all_nodes
        }
        root_nodes = [
            node
            for node in all_nodes
            if node.class_name not in parent_by_child_name
        ]
        root_nodes = sorted(
            root_nodes,
            key=lambda node: (node.x, node.class_name),
        )
        level_by_class_name = {}
        pending_nodes = [(root_node, 0) for root_node in root_nodes]
        while pending_nodes:
            node, level = pending_nodes.pop(0)
            level_by_class_name[node.class_name] = level
            child_names = children_by_parent_name.get(node.class_name, [])
            ordered_child_names = sorted(
                child_names,
                key=lambda class_name: (
                    node_by_class_name[class_name].x,
                    class_name,
                ),
            )
            for child_name in ordered_child_names:
                child_node = node_by_class_name[child_name]
                pending_nodes.append((child_node, level + 1))
        return level_by_class_name, root_nodes

    def subtree_widths(
        self,
        class_name,
        children_by_parent_name,
        node_by_class_name,
        width_by_class_name,
    ):
        child_names = children_by_parent_name.get(class_name, [])
        ordered_child_names = sorted(
            child_names,
            key=lambda child_class_name: (
                node_by_class_name[child_class_name].x,
                child_class_name,
            ),
        )
        child_widths = []
        for child_name in ordered_child_names:
            child_widths.append(
                self.subtree_widths(
                    child_name,
                    children_by_parent_name,
                    node_by_class_name,
                    width_by_class_name,
                )
            )
        total_child_width = 0
        if child_widths:
            total_child_width = sum(child_widths) + UML_NODE_PADDING_X * (
                len(child_widths) - 1
            )
        own_width = UML_NODE_WIDTH
        width_by_class_name[class_name] = max(own_width, total_child_width)
        return width_by_class_name[class_name]

    def place_subtree_nodes(
        self,
        class_name,
        left_edge,
        children_by_parent_name,
        node_by_class_name,
        width_by_class_name,
        center_y_by_level,
        level_by_class_name,
    ):
        node = node_by_class_name[class_name]
        node_width = width_by_class_name[class_name]
        node.x = left_edge + node_width / 2
        node.y = center_y_by_level[level_by_class_name[class_name]]
        child_names = children_by_parent_name.get(class_name, [])
        ordered_child_names = sorted(
            child_names,
            key=lambda child_class_name: (
                node_by_class_name[child_class_name].x,
                child_class_name,
            ),
        )
        child_left_edge = left_edge
        for child_name in ordered_child_names:
            self.place_subtree_nodes(
                child_name,
                child_left_edge,
                children_by_parent_name,
                node_by_class_name,
                width_by_class_name,
                center_y_by_level,
                level_by_class_name,
            )
            child_left_edge += (
                width_by_class_name[child_name] + UML_NODE_PADDING_X
            )

    def rearrange_diagram(self):
        all_nodes = self.uml_canvas.registry.all_nodes()
        if not all_nodes:
            return False
        snapshot_before = self.snapshot_diagram()
        parent_by_child_name, children_by_parent_name = self.visible_inheritance_paths()
        node_by_class_name = {
            node.class_name: node for node in all_nodes
        }
        level_by_class_name, root_nodes = self.rearranged_node_levels(
            parent_by_child_name,
            children_by_parent_name,
        )
        level_indices = sorted(set(level_by_class_name.values()))
        center_y_by_level = {}
        current_top = UML_ORIGIN_Y
        for level_index in level_indices:
            level_nodes = [
                node
                for node in all_nodes
                if level_by_class_name.get(node.class_name) == level_index
            ]
            maximum_height = max(node.height() for node in level_nodes)
            center_y_by_level[level_index] = current_top + maximum_height / 2
            current_top += maximum_height + UML_NODE_PADDING_Y + 40
        width_by_class_name = {}
        for root_node in root_nodes:
            self.subtree_widths(
                root_node.class_name,
                children_by_parent_name,
                node_by_class_name,
                width_by_class_name,
            )
        current_left_edge = UML_ORIGIN_X
        for root_node in root_nodes:
            self.place_subtree_nodes(
                root_node.class_name,
                current_left_edge,
                children_by_parent_name,
                node_by_class_name,
                width_by_class_name,
                center_y_by_level,
                level_by_class_name,
            )
            current_left_edge += (
                width_by_class_name[root_node.class_name] + UML_NODE_PADDING_X
            )
        for node in all_nodes:
            self.uml_canvas.redraw_node(node)
        self.uml_canvas.expand_scroll_region()
        snapshot_after = self.snapshot_diagram()
        if snapshot_after != snapshot_before:
            self.record_diagram_snapshot()
            self.application.event_queue.publish('DiagramRearranged')
            return True
        return False

    def undo_diagram(self, event=None):
        snapshot = self.diagram_history.go_back()
        if snapshot is None:
            self.refresh_undo_controls()
            return False
        self.application.event_queue.publish('DiagramUndone')
        self.restore_diagram_snapshot(snapshot)
        self.refresh_undo_controls()
        return True
