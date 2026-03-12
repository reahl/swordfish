import tkinter as tk

GRAPH_NODE_WIDTH = 200
GRAPH_NODE_HEIGHT = 60
GRAPH_NODE_PADDING_X = 40
GRAPH_NODE_PADDING_Y = 40
GRAPH_NODES_PER_ROW = 4
GRAPH_ORIGIN_X = 60
GRAPH_ORIGIN_Y = 60
UML_NODE_WIDTH = 240
UML_NODE_MIN_HEIGHT = 56
UML_NODE_PADDING_X = 40
UML_NODE_PADDING_Y = 40
UML_NODES_PER_ROW = 4
UML_ORIGIN_X = 60
UML_ORIGIN_Y = 60
UML_METHOD_LINE_HEIGHT = 18
UML_HEADER_HEIGHT = 26


def close_popup_menu(menu):
    try:
        menu.unpost()
    except tk.TclError:
        pass


def add_close_command_to_popup_menu(menu):
    if menu.index('end') is not None:
        menu.add_separator()
    menu.add_command(
        label='Close Menu',
        command=lambda current_menu=menu: close_popup_menu(current_menu),
    )


def popup_menu(menu, event):
    menu.bind(
        '<Escape>',
        lambda popup_event, current_menu=menu: close_popup_menu(current_menu),
    )
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
