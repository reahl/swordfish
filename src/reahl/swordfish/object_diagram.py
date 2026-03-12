import tkinter as tk
from tkinter import ttk

from reahl.ptongue import GemstoneError

from reahl.swordfish.inspector import ObjectInspector
from reahl.swordfish.ui_support import (
    GRAPH_NODE_HEIGHT,
    GRAPH_NODE_PADDING_X,
    GRAPH_NODE_PADDING_Y,
    GRAPH_NODE_WIDTH,
    GRAPH_NODES_PER_ROW,
    GRAPH_ORIGIN_X,
    GRAPH_ORIGIN_Y,
    add_close_command_to_popup_menu,
    popup_menu,
)


class UmlObjectNode:
    def __init__(self, an_object, oop_key, class_name, label):
        self.gemstone_object = an_object
        self.oop_key = oop_key
        self.class_name = class_name
        self.label = label
        self.x = 0
        self.y = 0
        self.canvas_item_ids = []

    def bounding_box(self):
        half_width = GRAPH_NODE_WIDTH // 2
        half_height = GRAPH_NODE_HEIGHT // 2
        return (
            self.x - half_width,
            self.y - half_height,
            self.x + half_width,
            self.y + half_height,
        )


class UmlObjectRelationship:
    def __init__(self, source_node, target_node, instvar_label):
        self.source_node = source_node
        self.target_node = target_node
        self.instvar_label = instvar_label
        self.canvas_item_ids = []


class UmlObjectDiagramRegistry:
    def __init__(self):
        self.nodes_by_oop_key = {}
        self.edges = []

    def oop_key_for(self, an_object):
        if an_object is None:
            return ('none',)
        try:
            oop_label = an_object.oop
            if oop_label is not None:
                return ('oop', str(oop_label))
        except (
            AttributeError,
            GemstoneError,
            tk.TclError,
            TypeError,
            ValueError,
            RuntimeError,
        ):
            pass
        return ('identity', str(id(an_object)))

    def contains_object(self, an_object):
        return self.oop_key_for(an_object) in self.nodes_by_oop_key

    def node_for(self, an_object):
        return self.nodes_by_oop_key.get(self.oop_key_for(an_object))

    def register_node(self, node):
        self.nodes_by_oop_key[node.oop_key] = node

    def add_edge(self, source_node, target_node, instvar_label):
        for existing in self.edges:
            is_same = (
                existing.source_node is source_node
                and existing.target_node is target_node
                and existing.instvar_label == instvar_label
            )
            if is_same:
                return None
        self.edges.append(UmlObjectRelationship(source_node, target_node, instvar_label))
        return self.edges[-1]

    def all_nodes(self):
        return list(self.nodes_by_oop_key.values())

    def all_edges(self):
        return list(self.edges)


class UmlObjectDiagramNodeInspectorHost(ttk.Frame):
    def __init__(
        self,
        parent,
        an_object,
        graph_node,
        on_navigate_to_child,
        browse_class_action,
    ):
        super().__init__(parent)
        self.graph_node = graph_node
        self.on_navigate_to_child = on_navigate_to_child
        self.inspector = ObjectInspector(
            self,
            an_object=an_object,
            external_inspect_action=None,
            graph_inspect_action=None,
            browse_class_action=browse_class_action,
        )
        self.inspector.pack(fill='both', expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

    def open_or_select_object(self, value):
        selected_item = self.inspector.treeview.focus()
        instvar_label = ''
        if selected_item:
            row_values = self.inspector.treeview.item(selected_item, 'values')
            if row_values:
                instvar_label = row_values[0]
        self.on_navigate_to_child(value, instvar_label)


class UmlObjectDiagramNodeDetailDialog:
    def __init__(self, parent, an_object, graph_node, on_add_to_graph):
        self.parent = parent
        self.graph_node = graph_node
        self.on_add_to_graph = on_add_to_graph
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(f'Object: {graph_node.label}')
        self.dialog.geometry('650x420')
        self.dialog.grab_set()
        self.inspector_host = UmlObjectDiagramNodeInspectorHost(
            self.dialog,
            an_object=an_object,
            graph_node=graph_node,
            on_navigate_to_child=self.navigate_to_child,
            browse_class_action=self.browse_object_class,
        )
        self.inspector_host.pack(fill='both', expand=True)

    def navigate_to_child(self, target_object, instvar_label):
        self.on_add_to_graph(self.graph_node, target_object, instvar_label)
        self.dialog.destroy()

    def browse_object_class(self, inspected_object):
        self.parent.application.browse_object_class(inspected_object)
        self.dialog.destroy()


class UmlObjectDiagramCanvas(ttk.Frame):
    def __init__(self, parent, node_detail_action, browse_class_action):
        super().__init__(parent)
        self.node_detail_action = node_detail_action
        self.browse_class_action = browse_class_action
        self.registry = UmlObjectDiagramRegistry()
        self.dragging_node = None
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.current_context_menu = None

        self.canvas = tk.Canvas(
            self,
            bg='white',
            scrollregion=(0, 0, 2000, 2000),
        )
        horizontal_scrollbar = ttk.Scrollbar(
            self,
            orient='horizontal',
            command=self.canvas.xview,
        )
        vertical_scrollbar = ttk.Scrollbar(
            self,
            orient='vertical',
            command=self.canvas.yview,
        )
        self.canvas.configure(
            xscrollcommand=horizontal_scrollbar.set,
            yscrollcommand=vertical_scrollbar.set,
        )

        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical_scrollbar.grid(row=0, column=1, sticky='ns')
        horizontal_scrollbar.grid(row=1, column=0, sticky='ew')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas.bind('<Button-1>', self.on_canvas_press)
        self.canvas.bind('<B1-Motion>', self.on_canvas_drag)
        self.canvas.bind('<ButtonRelease-1>', self.on_canvas_release)
        self.canvas.bind('<Button-3>', self.on_canvas_right_click)

    def add_object_to_diagram(self, an_object, source_node=None, instvar_label=None):
        if an_object is None:
            return
        existing_node = self.registry.node_for(an_object)
        if existing_node is not None:
            target_node = existing_node
        else:
            oop_key = self.registry.oop_key_for(an_object)
            class_name = '?'
            try:
                class_name = an_object.gemstone_class().asString().to_py
            except (
                AttributeError,
                GemstoneError,
                tk.TclError,
                TypeError,
                ValueError,
            ):
                pass
            oop_string = oop_key[1] if oop_key[0] == 'oop' else '?'
            label = f'{oop_string}:{class_name}'
            target_node = UmlObjectNode(an_object, oop_key, class_name, label)
            self.place_new_node(target_node)
            self.draw_node(target_node)
            self.registry.register_node(target_node)

        should_add_edge = source_node is not None and bool(instvar_label)
        if should_add_edge:
            new_edge = self.registry.add_edge(source_node, target_node, instvar_label)
            if new_edge is not None:
                self.draw_edge(new_edge)

        self.expand_scroll_region()

    def place_new_node(self, node):
        existing_count = len(self.registry.all_nodes())
        column_index = existing_count % GRAPH_NODES_PER_ROW
        row_index = existing_count // GRAPH_NODES_PER_ROW
        node.x = (
            GRAPH_ORIGIN_X
            + column_index * (GRAPH_NODE_WIDTH + GRAPH_NODE_PADDING_X)
            + GRAPH_NODE_WIDTH // 2
        )
        node.y = (
            GRAPH_ORIGIN_Y
            + row_index * (GRAPH_NODE_HEIGHT + GRAPH_NODE_PADDING_Y)
            + GRAPH_NODE_HEIGHT // 2
        )

    def draw_node(self, node):
        x1, y1, x2, y2 = node.bounding_box()
        rectangle_id = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill='#e8f0fe',
            outline='#3366cc',
            width=2,
        )
        oop_string = node.oop_key[1] if node.oop_key[0] == 'oop' else '?'
        oop_text_id = self.canvas.create_text(
            node.x,
            y1 + 14,
            text=oop_string,
            font=('TkDefaultFont', 9, 'bold'),
            fill='#3366cc',
        )
        class_text_id = self.canvas.create_text(
            node.x,
            y1 + 32,
            text=node.class_name,
            font=('TkDefaultFont', 9),
            fill='#222222',
        )
        node.canvas_item_ids = [rectangle_id, oop_text_id, class_text_id]

    def edge_boundary_point(self, from_node, toward_node):
        delta_x = toward_node.x - from_node.x
        delta_y = toward_node.y - from_node.y
        half_width = GRAPH_NODE_WIDTH / 2
        half_height = GRAPH_NODE_HEIGHT / 2
        if delta_x == 0 and delta_y == 0:
            return from_node.x + half_width, from_node.y
        scale_x = abs(half_width / delta_x) if delta_x != 0 else float('inf')
        scale_y = abs(half_height / delta_y) if delta_y != 0 else float('inf')
        scale = min(scale_x, scale_y)
        return from_node.x + delta_x * scale, from_node.y + delta_y * scale

    def draw_edge(self, edge):
        x1, y1 = self.edge_boundary_point(edge.source_node, edge.target_node)
        x2, y2 = self.edge_boundary_point(edge.target_node, edge.source_node)
        midpoint_x = (x1 + x2) / 2
        midpoint_y = (y1 + y2) / 2
        line_id = self.canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            arrow=tk.LAST,
            arrowshape=(10, 12, 5),
            fill='#444444',
            width=1.5,
        )
        label_id = self.canvas.create_text(
            midpoint_x,
            midpoint_y - 10,
            text=edge.instvar_label,
            font=('TkDefaultFont', 9),
            fill='#222288',
            anchor='s',
        )
        edge.canvas_item_ids = [line_id, label_id]

    def redraw_edges_for_node(self, node):
        for edge in self.registry.all_edges():
            touches_node = edge.source_node is node or edge.target_node is node
            if touches_node:
                for item_id in edge.canvas_item_ids:
                    self.canvas.delete(item_id)
                edge.canvas_item_ids = []
                self.draw_edge(edge)

    def node_at_canvas_coordinates(self, canvas_x, canvas_y):
        for node in self.registry.all_nodes():
            x1, y1, x2, y2 = node.bounding_box()
            if x1 <= canvas_x <= x2 and y1 <= canvas_y <= y2:
                return node
        return None

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
        self.redraw_edges_for_node(self.dragging_node)

    def on_canvas_release(self, event):
        self.dragging_node = None
        self.expand_scroll_region()

    def on_canvas_right_click(self, event):
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        node = self.node_at_canvas_coordinates(canvas_x, canvas_y)
        if node is None:
            return
        if self.current_context_menu is not None:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label='Inspect Object',
            command=lambda: self.node_detail_action(node),
        )
        menu.add_command(
            label='Browse Class',
            command=lambda: self.browse_class_action(node.gemstone_object),
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def expand_scroll_region(self):
        all_nodes = self.registry.all_nodes()
        if not all_nodes:
            self.canvas.configure(scrollregion=(0, 0, 2000, 2000))
            return
        minimum_x = min(node.x - GRAPH_NODE_WIDTH // 2 for node in all_nodes)
        minimum_x -= GRAPH_ORIGIN_X
        minimum_y = min(node.y - GRAPH_NODE_HEIGHT // 2 for node in all_nodes)
        minimum_y -= GRAPH_ORIGIN_Y
        maximum_x = max(node.x + GRAPH_NODE_WIDTH // 2 for node in all_nodes)
        maximum_x += GRAPH_ORIGIN_X
        maximum_y = max(node.y + GRAPH_NODE_HEIGHT // 2 for node in all_nodes)
        maximum_y += GRAPH_ORIGIN_Y
        self.canvas.configure(
            scrollregion=(
                min(minimum_x, 0),
                min(minimum_y, 0),
                max(maximum_x, 2000),
                max(maximum_y, 2000),
            )
        )

    def clear_all(self):
        self.canvas.delete('all')
        self.registry = UmlObjectDiagramRegistry()
        self.expand_scroll_region()


class UmlObjectDiagramTab(ttk.Frame):
    def __init__(self, parent, application):
        super().__init__(parent)
        self.application = application

        actions_frame = ttk.Frame(self)
        actions_frame.grid(row=0, column=0, sticky='ew', padx=10, pady=(10, 5))

        ttk.Label(actions_frame, text='Object Diagram').grid(
            row=0,
            column=0,
            sticky='w',
        )
        ttk.Button(actions_frame, text='Clear', command=self.clear_diagram).grid(
            row=0,
            column=1,
            padx=(6, 0),
        )
        ttk.Button(
            actions_frame,
            text='Close',
            command=self.application.close_object_diagram_tab,
        ).grid(row=0, column=2, padx=(6, 0))

        self.graph_canvas = UmlObjectDiagramCanvas(
            self,
            node_detail_action=self.open_node_detail,
            browse_class_action=self.application.browse_object_class,
        )
        self.graph_canvas.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

    def add_object(self, an_object):
        self.graph_canvas.add_object_to_diagram(
            an_object,
            source_node=None,
            instvar_label=None,
        )

    def open_node_detail(self, graph_node):
        UmlObjectDiagramNodeDetailDialog(
            self,
            an_object=graph_node.gemstone_object,
            graph_node=graph_node,
            on_add_to_graph=self.on_add_to_graph_from_dialog,
        )

    def on_add_to_graph_from_dialog(self, source_node, target_object, instvar_label):
        self.graph_canvas.add_object_to_diagram(
            target_object,
            source_node=source_node,
            instvar_label=instvar_label,
        )

    def clear_diagram(self):
        self.graph_canvas.clear_all()
