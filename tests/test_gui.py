import io
import json
import os
import tempfile
import time
import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
import types
from tkinter import ttk
from unittest.mock import ANY, Mock, call, patch

from reahl.ptongue import GemstoneError
from reahl.tofu import (
    Fixture,
    NoException,
    expected,
    scenario,
    set_up,
    tear_down,
    with_fixtures,
)

from reahl.swordfish.browser import MethodEditor
from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.main import (
    GEMSTONE_EXE_CONF_CONFIG_NAME,
    BreakpointsPane,
    BrowserWindow,
    CoveringTestsBrowseDialog,
    CoveringTestsSearchDialog,
    DomainException,
    EventQueue,
    Explorer,
    FindPane,
    GemstoneSessionRecord,
    InspectorTab,
    McpConfigurationAccess,
    McpConfigurationDialog,
    McpConfigurationStore,
    McpPermissionPolicy,
    McpRuntimeConfig,
    McpServerController,
    ObjectInspector,
    Swordfish,
    UmlClassDiagramMethodChooserDialog,
    UmlClassDiagramRegistry,
    UmlClassNode,
    UmlObjectDiagramRegistry,
    UmlObjectNode,
    apply_gemstone_exe_conf,
    read_gemstone_exe_conf,
)
from reahl.swordfish.mcp.integration_state import IntegratedSessionState
from reahl.swordfish.object_diagram import UmlObjectDiagramNodeDetailDialog
from reahl.swordfish.pane_area import PaneArea
from reahl.swordfish.session_activity import ForegroundActivity, McpActivity
from reahl.swordfish.theme import active_theme
from reahl.swordfish.text_editing import PINNED_TAB_MARKER


class FakeApplication:
    """AI: Thin stand-in for Swordfish that supplies the two attributes BrowserWindow needs."""

    def __init__(self, event_queue, gemstone_session_record):
        self.event_queue = event_queue
        self.gemstone_session_record = gemstone_session_record
        self.integrated_session_state = IntegratedSessionState()
        self.experimental_features_enabled = True
        self.tab_spacing = 4
        self.auto_format = False

    def handle_sender_selection(self, class_name, show_instance_side, method_symbol):
        if self.gemstone_session_record.gemstone_session is not None:
            self.gemstone_session_record.jump_to_method(
                class_name,
                show_instance_side,
                method_symbol,
            )
        else:
            selected_method_category = self.gemstone_session_record.gemstone_browser_session.get_method_category(
                class_name,
                method_symbol,
                show_instance_side,
            )
            self.gemstone_session_record.select_instance_side(show_instance_side)
            self.gemstone_session_record.select_class(class_name)
            self.gemstone_session_record.select_method_category(
                selected_method_category
            )
            self.gemstone_session_record.select_method_symbol(method_symbol)
        self.event_queue.publish("SelectedClassChanged")
        self.event_queue.publish("SelectedCategoryChanged")
        self.event_queue.publish(
            'MethodDisplayRequested',
            (class_name, show_instance_side, method_symbol),
        )

    def begin_foreground_activity(self, message):
        pass

    def end_foreground_activity(self):
        pass

    def run_foreground_activity(self, activity):
        # AI: Run the activity inline so GUI tests observe its outcome within the call,
        # mirroring Swordfish.run_activities_synchronously (the real app's test seam).
        activity.run_work()
        activity.deliver_outcome()

    def open_debugger(self, error):
        pass

    def open_class_diagram_for_class(self, class_name):
        pass

    def pin_method_in_class_diagram(
        self, class_name, show_instance_side, method_selector
    ):
        pass

    def browse_class(self, class_name, show_instance_side=True):
        # AI: Mirrors Swordfish.browse_class — update the model and publish
        # the event the browser UI listens to, with the same GemstoneError
        # gate that turns a 'no such class' lookup into a friendly warning
        # instead of bubbling to the generic error dialog. Skips the
        # `notebook.select(browser_tab)` step because the fixture does not
        # render the top-level Swordfish notebook.
        if not class_name:
            return
        try:
            self.gemstone_session_record.jump_to_class(
                class_name, show_instance_side
            )
        except GemstoneError:
            messagebox.showwarning(
                'No Such Class',
                f'There is no class named {class_name!r}.',
            )
            return
        self.event_queue.publish("SelectedClassChanged")


def find_result_label_for_row(row):
    # AI: Reconstruct the legacy single-string label for a FindPane result row
    # ("Class>>selector" / "Class class>>selector" for method rows, the class name
    # for class rows, or the bare selector for a 'contains' search), so tests can
    # assert which results appear independently of the new columns and indentation.
    if row["class_name"] is None:
        return row["method_selector"]
    class_label = row["class_name"]
    if not row["show_instance_side"]:
        class_label = "%s class" % row["class_name"]
    if row["method_selector"] is None:
        return class_label
    return "%s>>%s" % (class_label, row["method_selector"])


def find_result_labels(dialog):
    # AI: Flatten the FindPane results Treeview (depth-first, parents before
    # their nested overrides) into the list of labels in display order.
    labels = []

    def collect(parent_iid):
        for iid in dialog.results_tree.get_children(parent_iid):
            labels.append(find_result_label_for_row(dialog.result_rows_by_iid[iid]))
            collect(iid)

    collect("")
    return labels


def find_result_iid_for_label(dialog, label):
    # AI: Locate the results-tree row whose reconstructed label matches, so
    # double-click tests can target a specific result without a listbox index.
    def search(parent_iid):
        found = []
        for iid in dialog.results_tree.get_children(parent_iid):
            if find_result_label_for_row(dialog.result_rows_by_iid[iid]) == label:
                found.append(iid)
            found.extend(search(iid))
        return found

    return search("")[0]


def select_find_result(dialog, label):
    dialog.results_tree.selection_set(find_result_iid_for_label(dialog, label))


def route_debug_source_through_real_session(mock_browser):
    # AI: The Debug button/menu calls debug_source, which (see its own unit tests) wraps the
    # selection in a block and runs it through run_code, stopping at its first step point.
    # GUI tests only need the debugger-opening flow, so route debug_source to a single
    # run_code: that lets tests arming run_code (the GemStone leaf) drive the debugger while
    # debug_source still records the unwrapped selection it was asked to debug.
    def debug_selection(source):
        return mock_browser.run_code(source)

    mock_browser.debug_source.side_effect = debug_selection


class SwordfishGuiFixture(Fixture):
    @set_up
    def create_app(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_browser = Mock(spec=GemstoneBrowserSession)
        route_debug_source_through_real_session(self.mock_browser)
        self.mock_browser.list_categories.return_value = ["Kernel", "Collections"]
        self.mock_browser.list_dictionaries.return_value = [
            "Kernel",
            "Collections",
        ]
        self.mock_browser.list_classes_in_category.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.list_classes_in_dictionary.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.rowan_installed.return_value = False
        self.mock_browser.list_rowan_packages.return_value = []
        self.mock_browser.list_classes_in_rowan_package.return_value = []
        self.mock_browser.list_method_categories.return_value = ["accessing", "testing"]
        self.mock_browser.list_methods.return_value = ["total", "description"]
        self.mock_browser.list_breakpoints.return_value = []
        self.mock_browser.get_method_category.return_value = "accessing"
        class_definitions = {
            "OrderAudit": {
                "class_name": "OrderAudit",
                "superclass_name": "Order",
                "package_name": "Kernel",
                "inst_var_names": ["entries"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "SpecialOrderLine": {
                "class_name": "SpecialOrderLine",
                "superclass_name": "OrderLine",
                "package_name": "Kernel",
                "inst_var_names": ["discount"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "OrderLine": {
                "class_name": "OrderLine",
                "superclass_name": "Order",
                "package_name": "Kernel",
                "inst_var_names": ["amount", "quantity"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Order": {
                "class_name": "Order",
                "superclass_name": "Object",
                "package_name": "Kernel",
                "inst_var_names": ["lines"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Object": {
                "class_name": "Object",
                "superclass_name": None,
                "package_name": "Kernel",
                "inst_var_names": [],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
        }

        def get_class_definition(class_name):
            class_definition = class_definitions.get(class_name)
            if class_definition is None:
                raise GemstoneDomainException("Unknown class_name.")
            return class_definition

        self.mock_browser.get_class_definition.side_effect = get_class_definition

        # AI: accessible_var_names mirrors the live gem: for each variable kind it
        # lists the class's own variables first (inherited=False) then those from its
        # superclasses (inherited=True), so the UI can group and grey them.
        def accessible_var_names(class_name):
            own_definition = class_definitions.get(class_name)
            ancestor_definitions = []
            ancestor_name = (
                own_definition["superclass_name"] if own_definition else None
            )
            while ancestor_name in class_definitions:
                ancestor_definition = class_definitions[ancestor_name]
                ancestor_definitions.append(ancestor_definition)
                ancestor_name = ancestor_definition["superclass_name"]

            def entries_for(kind_key):
                entries = []
                if own_definition:
                    for name in own_definition[kind_key]:
                        entries.append({"name": name, "inherited": False})
                for ancestor_definition in ancestor_definitions:
                    for name in ancestor_definition[kind_key]:
                        entries.append({"name": name, "inherited": True})
                return entries

            return {
                "inst_var_names": entries_for("inst_var_names"),
                "class_inst_var_names": entries_for("class_inst_var_names"),
                "class_var_names": entries_for("class_var_names"),
            }

        self.mock_browser.accessible_var_names.side_effect = accessible_var_names

        # AI: get_compiled_method returns an object whose sourceString() method
        # returns an object with a .to_py attribute (the raw Smalltalk source string).
        mock_method = Mock()
        mock_method.sourceString.return_value.to_py = "total\n    ^amount * quantity"
        self.mock_browser.get_compiled_method.return_value = mock_method

        # AI: Pass None for the gemstone session; GemstoneSessionRecord.__init__
        # wraps it in GemstoneBrowserSession which only stores it.  We then replace
        # gemstone_browser_session with the mock before any real calls are made.
        self.session_record = GemstoneSessionRecord(None)
        self.session_record.gemstone_browser_session = self.mock_browser

        self.event_queue = EventQueue(self.root)
        self.application = FakeApplication(self.event_queue, self.session_record)
        self.browser_window = BrowserWindow(self.root, self.application)
        self.root.update()

        # AI: Clear call counts accumulated during widget initialisation so that
        # individual tests start from a clean slate.
        self.mock_browser.reset_mock()

    @tear_down
    def destroy_app(self):
        self.root.destroy()

    def select_in_listbox(self, listbox, item):
        """AI: Simulate a user clicking on an item in a Listbox.

        Calls handle_selection directly on the InteractiveSelectionList
        (listbox.master) rather than using event_generate, because the
        two-level event cascade (<<ListboxSelect>> -> <<CustomEventsPublished>>)
        is not reliably flushed in a single root.update() under Xvfb.
        root.update() still drains the single-level custom-event queue that
        the selection handler itself enqueues.
        """
        items = listbox.get(0, "end")
        idx = list(items).index(item)
        listbox.selection_clear(0, "end")
        listbox.selection_set(idx)
        selection_list = (
            listbox.master
        )  # AI: listbox is a direct child of InteractiveSelectionList
        selection_list.handle_selection(types.SimpleNamespace(widget=listbox))
        self.root.update()

    def select_down_to_method(self, package, class_name, category, method, pin=False):
        """AI: Navigate all four selection columns to open an editor tab for a method.

        A single selection opens the method in a transient *preview* tab; pass
        pin=True to also pin it (as a user would by double-clicking), so it
        survives opening other methods.
        """
        self.select_in_listbox(
            self.browser_window.packages_widget.selection_list.selection_listbox,
            package,
        )
        self.select_in_listbox(
            self.browser_window.classes_widget.selection_list.selection_listbox,
            class_name,
        )
        self.select_in_listbox(
            self.browser_window.categories_widget.selection_list.selection_listbox,
            category,
        )
        self.select_in_listbox(
            self.browser_window.methods_widget.selection_list.selection_listbox,
            method,
        )
        if pin:
            self.browser_window.methods_widget.pin_selected_method_tab()
            self.root.update()

    def open_text_context_menu_for_tab(self, tab):
        menu_event = types.SimpleNamespace(
            x=1,
            y=1,
            x_root=1,
            y_root=1,
        )
        tab.code_panel.open_text_menu(menu_event)
        self.root.update()
        return tab.code_panel.current_context_menu

    def open_tab_context_menu_for_tab(self, tab):
        """AI: Build the per-tab right-click menu (EditorTab.open_tab_menu)."""
        menu_event = types.SimpleNamespace(
            x=1,
            y=1,
            x_root=1,
            y_root=1,
        )
        tab.open_tab_menu(menu_event)
        self.root.update()
        return tab.current_context_menu

    def invoke_menu_command(self, menu, label):
        entry_count = int(menu.index("end")) + 1
        for entry_index in range(entry_count):
            if menu.type(entry_index) != "command":
                continue
            if menu.entrycget(entry_index, "label") == label:
                menu.invoke(entry_index)
                self.root.update()
                return
        raise AssertionError(f"Menu command not found: {label}")

    def selected_listbox_entry(self, listbox):
        selected_index = listbox.curselection()[0]
        return listbox.get(selected_index)


def visible_tab_title(notebook):
    """AI: Title of the currently selected tab in the given notebook group."""
    return notebook.tab(notebook.select(), 'text')


def all_open_tab_texts(app):
    """AI: Titles of every open top-level tab across both notebook groups -- the
    left browser/workspace group and the right auxiliary (tools) group."""
    texts = []
    for group in app.pane_area.groups:
        texts.extend(group.tab(tab_id, 'text') for tab_id in group.tabs())
    return texts


def menu_command_labels(menu):
    labels = []
    entry_count = int(menu.index("end")) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) == "command":
            labels.append(menu.entrycget(entry_index, "label"))
    return labels


def cascade_submenu(menu, cascade_label):
    """AI: Resolve the submenu Menu widget hung off a cascade entry.

    A cascade entry stores its submenu as a Tk path string under the 'menu'
    option; nametowidget resolves that back to the child Menu widget.
    """
    entry_count = int(menu.index("end")) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) == "cascade":
            if menu.entrycget(entry_index, "label") == cascade_label:
                submenu_path = menu.entrycget(entry_index, "menu")
                return menu.nametowidget(submenu_path)
    raise AssertionError(f"Could not find cascade {cascade_label}.")


def cascade_submenu_labels(menu, cascade_label):
    """AI: Return the selectable variable labels of a cascade's submenu.

    Heading rows carry no command (they are inert labels), so filtering to entries
    that have a command leaves exactly the variable names a user could click.
    """
    submenu = cascade_submenu(menu, cascade_label)
    labels = []
    entry_count = int(submenu.index("end")) + 1
    for entry_index in range(entry_count):
        if submenu.type(entry_index) == "command":
            if str(submenu.entrycget(entry_index, "command")) != "":
                labels.append(submenu.entrycget(entry_index, "label"))
    return labels


def invoke_menu_command_by_label(menu, label):
    entry_count = int(menu.index("end")) + 1
    for entry_index in range(entry_count):
        if menu.type(entry_index) != "command":
            continue
        if menu.entrycget(entry_index, "label") == label:
            menu.invoke(entry_index)
            return
    raise AssertionError(f"Menu command not found: {label}")


@with_fixtures(SwordfishGuiFixture)
def test_selecting_group_fetches_and_shows_classes(fixture):
    """AI: Selecting a left-pane group should fetch classes for the active browse mode."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )

    fixture.mock_browser.list_classes_in_category.assert_called_with("Kernel")
    class_listbox = (
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine", "Order"]


@with_fixtures(SwordfishGuiFixture)
def test_switching_left_pane_to_dictionaries_shows_dictionary_names(fixture):
    """AI: Switching the left pane to dictionaries should repopulate it from symbolList dictionary names."""
    fixture.mock_browser.list_dictionaries.return_value = [
        "SessionGlobals",
        "UserGlobals",
    ]

    fixture.browser_window.packages_widget.browse_mode_var.set("dictionaries")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()

    assert fixture.session_record.browse_mode == "dictionaries"
    left_pane_entries = list(
        fixture.browser_window.packages_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    )
    assert left_pane_entries == ["SessionGlobals", "UserGlobals"]


@with_fixtures(SwordfishGuiFixture)
def test_selecting_dictionary_fetches_and_shows_classes_in_dictionary(fixture):
    """AI: In dictionary browse mode, selecting a dictionary should populate classes from that dictionary."""
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals"]
    fixture.mock_browser.list_classes_in_dictionary.return_value = [
        "OrderLine",
    ]

    fixture.browser_window.packages_widget.browse_mode_var.set("dictionaries")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "UserGlobals",
    )

    fixture.mock_browser.list_classes_in_dictionary.assert_called_with(
        "UserGlobals",
    )
    class_listbox = (
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine"]


@with_fixtures(SwordfishGuiFixture)
def test_switching_left_pane_to_categories_shows_category_names(fixture):
    """AI: Switching to categories mode should repopulate the left pane from ClassOrganizer categories."""
    fixture.mock_browser.list_categories.return_value = [
        "Kernel",
        "Collections",
        "Stuff",
    ]
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()

    assert fixture.session_record.browse_mode == "categories"
    left_pane_entries = list(
        fixture.browser_window.packages_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    )
    assert left_pane_entries == ["Kernel", "Collections", "Stuff"]


@with_fixtures(SwordfishGuiFixture)
def test_rowan_mode_button_is_disabled_when_rowan_is_not_installed(fixture):
    """AI: Rowan mode should be unavailable when Rowan is not installed on the connected stone."""
    fixture.mock_browser.rowan_installed.return_value = False
    fixture.browser_window.packages_widget.handle_browse_mode_changed()
    fixture.root.update()

    rowan_state = fixture.browser_window.packages_widget.rowan_radiobutton.cget("state")
    assert rowan_state == tk.DISABLED


@with_fixtures(SwordfishGuiFixture)
def test_selecting_category_fetches_and_shows_classes_in_category(fixture):
    """AI: In categories mode, selecting a category should populate classes from that category only."""
    fixture.mock_browser.list_categories.return_value = ["Kernel"]
    fixture.mock_browser.list_classes_in_category.return_value = [
        "OrderLine",
    ]
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )

    fixture.mock_browser.list_classes_in_category.assert_called_with("Kernel")
    class_listbox = (
        fixture.browser_window.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine"]


@with_fixtures(SwordfishGuiFixture)
def test_add_class_creates_in_selected_package_and_selects_it(fixture):
    """AI: Adding a class in categories mode should create it in UserGlobals."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.mock_browser.list_classes_in_category.return_value = [
        "OrderLine",
        "Order",
        "Invoice",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        side_effect=["Invoice", "Object"],
    ):
        fixture.browser_window.classes_widget.add_class()
        fixture.root.update()

    fixture.mock_browser.create_class.assert_called_with(
        class_name="Invoice",
        superclass_name="Object",
        in_dictionary="UserGlobals",
    )
    assert not fixture.mock_browser.assign_class_to_package.called
    assert fixture.session_record.selected_class == "Invoice"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.classes_widget.selection_list.selection_listbox
        )
        == "Invoice"
    )


@with_fixtures(SwordfishGuiFixture)
def test_add_class_in_dictionary_mode_creates_in_selected_dictionary(fixture):
    """AI: Adding a class in dictionary mode should create it directly in the selected dictionary."""
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals"]
    fixture.mock_browser.list_classes_in_dictionary.return_value = ["Invoice"]
    fixture.browser_window.packages_widget.browse_mode_var.set("dictionaries")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "UserGlobals",
    )

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        side_effect=["Invoice", "Object"],
    ):
        fixture.browser_window.classes_widget.add_class()
        fixture.root.update()

    fixture.mock_browser.create_class.assert_called_with(
        class_name="Invoice",
        superclass_name="Object",
        in_dictionary="UserGlobals",
    )
    assert not fixture.mock_browser.assign_class_to_package.called


@with_fixtures(SwordfishGuiFixture)
def test_delete_class_removes_selected_class_and_clears_method_selection(fixture):
    """AI: Deleting a selected class in categories mode should target UserGlobals and clear class/method selection state."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_classes_in_category.return_value = ["Order"]

    with patch("reahl.swordfish.main.messagebox.askyesno", return_value=True):
        fixture.browser_window.classes_widget.delete_class()
        fixture.root.update()

    fixture.mock_browser.delete_class.assert_called_once_with(
        "OrderLine",
        in_dictionary="UserGlobals",
    )
    assert fixture.session_record.selected_class is None
    assert fixture.session_record.selected_method_symbol is None
    assert list(
        fixture.browser_window.classes_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    ) == ["Order"]


@with_fixtures(SwordfishGuiFixture)
def test_add_category_creates_category_for_selected_class_side(fixture):
    """AI: Adding a category from the category pane should create it on the selected class side and select it."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_method_categories.return_value = [
        "accessing",
        "testing",
        "validation",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="validation",
    ):
        fixture.browser_window.categories_widget.add_category()
        fixture.root.update()

    fixture.mock_browser.create_method_category.assert_called_once_with(
        "OrderLine",
        "validation",
        True,
    )
    assert fixture.session_record.selected_method_category == "validation"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox
        )
        == "validation"
    )


@with_fixtures(SwordfishGuiFixture)
def test_delete_category_removes_selected_category_and_selects_remaining(fixture):
    """AI: Deleting a selected category should remove it from the current class side and select a remaining category."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.select_in_listbox(
        fixture.browser_window.categories_widget.selection_list.selection_listbox,
        "accessing",
    )
    fixture.mock_browser.list_method_categories.return_value = ["testing"]

    with patch("reahl.swordfish.main.messagebox.askyesno", return_value=True):
        fixture.browser_window.categories_widget.delete_category()
        fixture.root.update()

    fixture.mock_browser.delete_method_category.assert_called_once_with(
        "OrderLine",
        "accessing",
        True,
    )
    assert fixture.session_record.selected_method_category == "testing"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox
        )
        == "testing"
    )


@with_fixtures(SwordfishGuiFixture)
def test_add_method_compiles_template_in_as_yet_unclassified_and_opens_tab(fixture):
    """AI: Adding a method compiles a starter template in as yet unclassified and opens that method in the editor."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_method_categories.return_value = [
        "accessing",
        "testing",
        "as yet unclassified",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="calculateTotal",
    ):
        fixture.browser_window.methods_widget.add_method()
        fixture.root.update()

    fixture.mock_browser.compile_method.assert_called_once_with(
        "OrderLine",
        True,
        "calculateTotal\n    ^self",
        method_category="as yet unclassified",
    )
    assert fixture.session_record.selected_method_category == "as yet unclassified"
    assert fixture.session_record.selected_method_symbol == "calculateTotal"
    assert (
        "OrderLine",
        True,
        "calculateTotal",
    ) in fixture.browser_window.editor_area_widget.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_add_method_generates_keyword_template_argument_names(fixture):
    """AI: Keyword selectors are prepopulated with argument placeholders so the generated method source compiles."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.mock_browser.list_method_categories.return_value = [
        "accessing",
        "testing",
        "as yet unclassified",
    ]

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="copyFrom:to:",
    ):
        fixture.browser_window.methods_widget.add_method()
        fixture.root.update()

    fixture.mock_browser.compile_method.assert_called_once_with(
        "OrderLine",
        True,
        "copyFrom: argument1 to: argument2\n    ^self",
        method_category="as yet unclassified",
    )


@with_fixtures(SwordfishGuiFixture)
def test_delete_method_removes_selected_method_from_class(fixture):
    """AI: Deleting a selected method should remove it from the class and clear selected method state."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.list_methods.return_value = ["description"]

    with patch("reahl.swordfish.main.messagebox.askyesno", return_value=True):
        fixture.browser_window.methods_widget.delete_method()
        fixture.root.update()

    fixture.mock_browser.delete_method.assert_called_once_with(
        "OrderLine",
        "total",
        True,
    )
    assert fixture.session_record.selected_method_symbol is None
    assert list(
        fixture.browser_window.methods_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    ) == ["description"]


@with_fixtures(SwordfishGuiFixture)
def test_selecting_method_opens_editor_tab(fixture):
    """Choosing a method from the method list opens a new editor tab
    containing that method's source code."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    notebook = fixture.browser_window.editor_area_widget.editor_notebook
    assert len(notebook.tabs()) == 1
    tab_text = notebook.tab(notebook.tabs()[0], "text")
    assert tab_text == "total"


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_source_shows_line_numbers(fixture):
    """AI: Method source editors display a synchronized line-number column."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    line_numbers = tab.code_panel.line_number_column.line_numbers_text.get(
        "1.0",
        "end-1c",
    ).splitlines()
    assert line_numbers[:2] == ["1", "2"]

    tab.code_panel.text_editor.insert("end", "\n    ^42")
    fixture.root.update()

    updated_line_numbers = tab.code_panel.line_number_column.line_numbers_text.get(
        "1.0",
        "end-1c",
    ).splitlines()
    assert updated_line_numbers[:3] == ["1", "2", "3"]
    tab.code_panel.text_editor.mark_set(tk.INSERT, "2.4")
    tab.code_panel.cursor_position_indicator.update_position()
    assert tab.code_panel.cursor_position_label.cget("text") == "Ln 2, Col 5"


@with_fixtures(SwordfishGuiFixture)
def test_selecting_already_open_method_brings_its_tab_to_fore(fixture):
    """Re-selecting a method that already has an open tab switches to that
    tab rather than opening a duplicate."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method(
        "Kernel", "OrderLine", "accessing", "description", pin=True
    )
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    notebook = fixture.browser_window.editor_area_widget.editor_notebook
    assert len(notebook.tabs()) == 2
    selected_tab = notebook.select()
    assert notebook.tab(selected_tab, "text") == PINNED_TAB_MARKER + "total"


@with_fixtures(SwordfishGuiFixture)
def test_selecting_another_method_recycles_the_preview_tab(fixture):
    """AI: A method opened from the list lives in a single transient preview
    tab. Selecting a different method reuses that one tab rather than piling
    up tabs, so an unpinned tab is never left behind."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")

    editor = fixture.browser_window.editor_area_widget
    assert list(editor.open_tabs.keys()) == [("OrderLine", True, "description")]


class MethodDisplayOriginScenarios(Fixture):
    """AI: The two kinds of origin that can ask the editor to display a
    method. Both hand the method to the editor through the
    MethodDisplayRequested event; they differ only in whether the origin
    also owns and moves the browser's own selection."""

    @scenario
    def chosen_from_the_browser_list(self):
        """AI: The method list owns the browser selection, so choosing a
        method moves that selection and asks the editor to display it."""
        self.move_browser_selection = True
        self.selected_method_after_request = 'description'

    @scenario
    def peeked_from_a_search_result(self):
        """AI: A search result only asks the editor to display a method; it
        must leave the browser's selection alone (an editor-only peek)."""
        self.move_browser_selection = False
        self.selected_method_after_request = 'total'


@with_fixtures(SwordfishGuiFixture, MethodDisplayOriginScenarios)
def test_editor_displays_the_method_the_event_carries(fixture, scenario):
    """AI: The method to display travels inside the MethodDisplayRequested
    event, so any origin can drive the single editor. Because the editor no
    longer reads 'which method' from the shared browser selection, a search
    result can peek a method into the editor without moving the browser --
    only the origin that owns the selection moves it."""
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')

    requested_method = ('OrderLine', True, 'description')
    if scenario.move_browser_selection:
        fixture.application.gemstone_session_record.select_method_symbol(
            'description'
        )
    fixture.event_queue.publish(
        'MethodDisplayRequested', requested_method, origin=None
    )

    editor = fixture.browser_window.editor_area_widget
    assert list(editor.open_tabs.keys()) == [requested_method]
    assert (
        fixture.application.gemstone_session_record.selected_method_symbol
        == scenario.selected_method_after_request
    )


@with_fixtures(SwordfishGuiFixture)
def test_pinning_a_displayed_method_promotes_its_preview_tab(fixture):
    """AI: MethodTabPinRequested carries the method to pin, so a double-click
    from Find -- which previews a method then pins it WITHOUT touching the
    browser's selection -- actually promotes that method's preview tab to a
    permanent one. (The bug: pin read the browser selection, which Find, by
    design, never sets.)"""
    editor = fixture.browser_window.editor_area_widget
    method = ('OrderLine', True, 'total')

    fixture.event_queue.publish('MethodDisplayRequested', method, origin=None)
    assert editor.preview_tab_key == method

    fixture.event_queue.publish('MethodTabPinRequested', method, origin=None)

    assert method in editor.open_tabs
    assert editor.preview_tab_key is None


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_is_a_standalone_tool_built_from_the_application(fixture):
    """AI: The editor is a placeable tool in its own right -- constructed from
    only the application (its gem session and busy state) and the event queue,
    with no BrowserWindow -- and it still follows MethodDisplayRequested to show
    the chosen method."""
    editor = MethodEditor(
        fixture.root, fixture.application, fixture.event_queue
    )
    fixture.select_down_to_method('Kernel', 'OrderLine', 'accessing', 'total')
    assert list(editor.open_tabs.keys()) == [('OrderLine', True, 'total')]


@with_fixtures(SwordfishGuiFixture)
def test_double_clicking_a_method_pins_its_tab(fixture):
    """AI: Double-clicking a method pins its tab, so it is no longer the
    recyclable preview tab and survives opening another method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")

    editor = fixture.browser_window.editor_area_widget
    assert ("OrderLine", True, "total") in editor.open_tabs
    assert ("OrderLine", True, "description") in editor.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_pinned_tab_label_carries_the_pin_marker(fixture):
    """AI: A pinned tab is distinguished from a preview tab by a marker on its
    label; the preview tab shows the bare selector."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    editor = fixture.browser_window.editor_area_widget
    preview_tab = editor.open_tabs[("OrderLine", True, "total")]
    assert editor.editor_notebook.tab(preview_tab, "text") == "total"

    fixture.browser_window.methods_widget.pin_selected_method_tab()
    fixture.root.update()
    assert (
        editor.editor_notebook.tab(preview_tab, "text") == PINNED_TAB_MARKER + "total"
    )


@with_fixtures(SwordfishGuiFixture)
def test_pin_tab_command_keeps_the_tab_when_another_method_opens(fixture):
    """AI: The 'Pin Tab' action on the tab menu promotes the preview tab to a
    permanent one, exactly like double-clicking the method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    editor = fixture.browser_window.editor_area_widget
    tab = editor.open_tabs[("OrderLine", True, "total")]

    menu = fixture.open_tab_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Pin Tab")

    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")
    assert ("OrderLine", True, "total") in editor.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_editing_a_preview_tab_pins_it(fixture):
    """AI: Starting to edit a preview tab pins it, so a user's unsaved work is
    never silently discarded when the next method is opened."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    editor = fixture.browser_window.editor_area_widget
    tab = editor.open_tabs[("OrderLine", True, "total")]

    tab.code_panel.text_editor.insert("end", "\n    ^42")
    fixture.root.update()

    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")
    assert ("OrderLine", True, "total") in editor.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_back_and_forward_navigate_method_history(fixture):
    """AI: Back and Forward should move through the selected-method trail like browser navigation."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")

    editor = fixture.browser_window.editor_area_widget
    editor.back_button.invoke()
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "total"
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, "text") == "total"

    editor.forward_button.invoke()
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "description"
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, "text") == "description"


@with_fixtures(SwordfishGuiFixture)
def test_method_editor_history_list_jumps_to_selected_entry(fixture):
    """AI: Choosing an entry in method history should jump directly to that earlier method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")

    editor = fixture.browser_window.editor_area_widget
    history_values = editor.history_combobox.cget("values")
    matching_indices = [
        index
        for index, value in enumerate(history_values)
        if "OrderLine>>total" in value
    ]
    target_index = matching_indices[0]

    editor.history_combobox.current(target_index)
    editor.history_combobox.event_generate("<<ComboboxSelected>>")
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "total"
    selected_tab = editor.editor_notebook.select()
    assert editor.editor_notebook.tab(selected_tab, "text") == "total"


@with_fixtures(SwordfishGuiFixture)
def test_saving_method_compiles_to_gemstone(fixture):
    """Saving an open editor tab sends the current source to GemstoneBrowserSession
    for compilation."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^42")
    tab.save()

    fixture.mock_browser.compile_method.assert_called_with(
        "OrderLine", True, "total\n    ^42"
    )


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_keeps_save_but_drops_tab_actions(fixture):
    """AI: The text-area menu keeps actions about the *current source* (Save,
    breakpoints, navigation by selector) but no longer carries actions about
    the *tab as a whole* (Jump to Class and Close moved to the tab menu)."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Save" in command_labels
    assert "Cancel" in command_labels
    assert "Set Breakpoint Here" in command_labels
    assert "Clear Breakpoint Here" in command_labels
    assert "Implementors" in command_labels
    assert "Senders" in command_labels
    assert "Browse Class" in command_labels
    assert "Select All" in command_labels
    assert "Copy" in command_labels
    assert "Paste" in command_labels
    assert "Undo" in command_labels
    # AI: Moved to EditorTab.open_tab_menu — must no longer be here.
    assert "Jump to Class" not in command_labels
    assert "Close" not in command_labels
    # AI: Pre-existing exclusions kept as regression sentinels.
    assert "Find Implementors" not in command_labels
    assert "Find Senders" not in command_labels
    assert "Preview Rename Method" not in command_labels
    assert "Preview Move Method" not in command_labels
    assert "Preview Add Parameter" not in command_labels
    assert "Preview Remove Parameter" not in command_labels
    assert "Preview Extract Method" not in command_labels
    assert "Preview Inline Method" not in command_labels
    assert "Method Sends" not in command_labels
    assert "Method Structure" not in command_labels
    assert "Method Control Flow" not in command_labels
    assert "Method AST" not in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_tab_context_menu_lists_expected_tab_actions(fixture):
    """AI: Right-clicking a tab label offers the tab-scoped actions:
    Jump to Class, Save, Cancel, Close, Close Others, Close All to the Right."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    menu = fixture.open_tab_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Jump to Class" in command_labels
    assert "Save" in command_labels
    assert "Cancel" in command_labels
    assert "Close" in command_labels
    assert "Close Others" in command_labels
    assert "Close All to the Right" in command_labels
    # AI: The class-scoped bulk closes name the actual class (tab_key[0]).
    assert "Close All in OrderLine" in command_labels
    assert "Close All not in OrderLine" in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_close_others_closes_only_other_tabs(fixture):
    """AI: Invoking 'Close Others' from a tab keeps that one tab open and
    closes every other tab in the editor notebook."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method(
        "Kernel", "OrderLine", "accessing", "description", pin=True
    )
    fixture.select_down_to_method("Kernel", "Order", "accessing", "total", pin=True)

    editor = fixture.browser_window.editor_area_widget
    middle_tab = editor.open_tabs[("OrderLine", True, "description")]

    menu = fixture.open_tab_context_menu_for_tab(middle_tab)
    fixture.invoke_menu_command(menu, "Close Others")

    assert list(editor.open_tabs.keys()) == [("OrderLine", True, "description")]


@with_fixtures(SwordfishGuiFixture)
def test_close_tabs_to_right_preserves_left_of_clicked_tab(fixture):
    """AI: 'Close All to the Right' closes only the tabs positioned after the
    clicked tab, leaving the clicked tab and everything left of it open."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method(
        "Kernel", "OrderLine", "accessing", "description", pin=True
    )
    fixture.select_down_to_method("Kernel", "Order", "accessing", "total", pin=True)

    editor = fixture.browser_window.editor_area_widget
    middle_tab = editor.open_tabs[("OrderLine", True, "description")]

    menu = fixture.open_tab_context_menu_for_tab(middle_tab)
    fixture.invoke_menu_command(menu, "Close All to the Right")

    assert list(editor.open_tabs.keys()) == [
        ("OrderLine", True, "total"),
        ("OrderLine", True, "description"),
    ]


@with_fixtures(SwordfishGuiFixture)
def test_close_all_in_same_class_closes_only_that_classes_tabs(fixture):
    """AI: 'Close All in <class>' closes every open method of the clicked tab's
    class and leaves methods of other classes open."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method(
        "Kernel", "OrderLine", "accessing", "description", pin=True
    )
    fixture.select_down_to_method("Kernel", "Order", "accessing", "total", pin=True)

    editor = fixture.browser_window.editor_area_widget
    order_line_tab = editor.open_tabs[("OrderLine", True, "total")]

    menu = fixture.open_tab_context_menu_for_tab(order_line_tab)
    fixture.invoke_menu_command(menu, "Close All in OrderLine")

    assert list(editor.open_tabs.keys()) == [("Order", True, "total")]


@with_fixtures(SwordfishGuiFixture)
def test_close_all_not_in_class_keeps_only_that_classes_tabs(fixture):
    """AI: 'Close All not in <class>' closes methods of every other class and
    keeps the clicked tab's class open."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method(
        "Kernel", "OrderLine", "accessing", "description", pin=True
    )
    fixture.select_down_to_method("Kernel", "Order", "accessing", "total", pin=True)

    editor = fixture.browser_window.editor_area_widget
    order_line_tab = editor.open_tabs[("OrderLine", True, "total")]

    menu = fixture.open_tab_context_menu_for_tab(order_line_tab)
    fixture.invoke_menu_command(menu, "Close All not in OrderLine")

    assert list(editor.open_tabs.keys()) == [
        ("OrderLine", True, "total"),
        ("OrderLine", True, "description"),
    ]


@with_fixtures(SwordfishGuiFixture)
def test_close_all_named_closes_every_tab_with_that_selector(fixture):
    """AI: 'Close All named <selector>' closes every open tab whose method has
    that name, across classes, leaving differently-named methods open."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method(
        "Kernel", "OrderLine", "accessing", "description", pin=True
    )
    fixture.select_down_to_method("Kernel", "Order", "accessing", "total", pin=True)

    editor = fixture.browser_window.editor_area_widget
    order_line_total_tab = editor.open_tabs[("OrderLine", True, "total")]

    menu = fixture.open_tab_context_menu_for_tab(order_line_total_tab)
    fixture.invoke_menu_command(menu, "Close All named total")

    assert list(editor.open_tabs.keys()) == [("OrderLine", True, "description")]


@with_fixtures(SwordfishGuiFixture)
def test_browser_selection_columns_are_resizable(fixture):
    """AI: The four selection columns sit in a horizontal PanedWindow so the user
    can drag the borders between them to resize, rather than being locked to
    equal-width grid cells."""
    columns_pane = fixture.browser_window.top_frame

    assert columns_pane.winfo_class() == 'TPanedwindow'
    assert str(columns_pane.cget('orient')) == 'horizontal'
    assert len(columns_pane.panes()) == 4


@with_fixtures(SwordfishGuiFixture)
def test_set_breakpoint_command_from_text_context_menu_uses_method_context(
    fixture,
):
    """AI: Setting a breakpoint from method editor context menu should target the selected method context and cursor offset."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    fixture.session_record.set_breakpoint = Mock(return_value={"breakpoint_id": "bp-1"})

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Set Breakpoint Here")

    fixture.session_record.set_breakpoint.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        ANY,
    )


@with_fixtures(SwordfishGuiFixture)
def test_method_source_displays_breakpoint_markers_for_existing_breakpoints(
    fixture,
):
    """AI: Method editor should visibly tag source locations where breakpoints already exist."""
    fixture.mock_browser.list_breakpoints.return_value = [
        {
            "breakpoint_id": "bp-1",
            "class_name": "OrderLine",
            "show_instance_side": True,
            "method_selector": "total",
            "source_offset": 1,
            "step_point": 1,
        }
    ]
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    breakpoint_ranges = tab.code_panel.text_editor.tag_ranges("breakpoint_marker")

    assert len(breakpoint_ranges) == 2


@with_fixtures(SwordfishGuiFixture)
def test_clear_breakpoint_command_from_text_context_menu_uses_method_context(
    fixture,
):
    """AI: Clearing a breakpoint from method editor context menu should target the selected method context and cursor offset."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    fixture.session_record.clear_breakpoint_at = Mock(
        return_value={"breakpoint_id": "bp-1"}
    )

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Clear Breakpoint Here")

    fixture.session_record.clear_breakpoint_at.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        ANY,
    )


@with_fixtures(SwordfishGuiFixture)
def test_set_breakpoint_does_not_pop_up_a_dialog_when_snapped(
    fixture,
):
    """AI: Setting a breakpoint is silent -- even when the cursor offset snaps to
    a nearby executable location, no dialog pops up; the gutter marker already
    shows where the breakpoint landed."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.mark_set(tk.INSERT, "1.2")
    fixture.session_record.set_breakpoint = Mock(
        return_value={
            "breakpoint_id": "bp-1",
            "class_name": "OrderLine",
            "show_instance_side": True,
            "method_selector": "total",
            "source_offset": 8,
            "step_point": 2,
        }
    )
    with patch("reahl.swordfish.text_editing.messagebox") as mock_messagebox:
        tab.code_panel.set_breakpoint_at_cursor()

    mock_messagebox.showinfo.assert_not_called()
    fixture.session_record.set_breakpoint.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_includes_run_and_inspect_for_selected_text_in_open_tab(
    fixture,
):
    """AI: Selecting method source text should expose Run and Inspect in the editor context menu."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4\n5 + 6")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Run" in command_labels
    assert "Inspect" in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_includes_graph_inspect_for_selected_text_in_open_tab(
    fixture,
):
    """AI: Selecting method source text should expose Show in Object Diagram in the editor context menu."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4\n5 + 6")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Show in Object Diagram" in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_find_references_uses_selected_class_name(
    fixture,
):
    """AI: Find References from method source should launch class-reference lookup for the selected class name."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.application.open_find_dialog_for_class = Mock()
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "OrderLine")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.9")

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)
    assert "References" in command_labels
    fixture.invoke_menu_command(menu, "References")

    tab.code_panel.application.open_find_dialog_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishGuiFixture)
def test_inspect_command_from_method_source_context_menu_opens_inspector_for_selection(
    fixture,
):
    """AI: Choosing Inspect from method source context menu should evaluate selected source and open Inspector."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    inspected_object = make_mock_gemstone_object("Integer", "7", oop=3004)
    fixture.mock_browser.run_code.return_value = inspected_object
    tab.code_panel.application.open_inspector_for_object = Mock()

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Inspect")

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    tab.code_panel.application.open_inspector_for_object.assert_called_with(
        inspected_object,
    )


@with_fixtures(SwordfishGuiFixture)
def test_print_command_from_method_source_splices_print_string_after_selection(
    fixture,
):
    """AI: Print (classic 'print it') evaluates the selection and splices the
    result's printString in right after the selection, leaving the inserted result
    selected so a single delete removes it again."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    fixture.mock_browser.run_code.return_value = make_mock_gemstone_object(
        "Integer", "7", oop=3004
    )

    menu = fixture.open_text_context_menu_for_tab(tab)
    assert "Print" in menu_command_labels(menu)
    fixture.invoke_menu_command(menu, "Print")

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert tab.code_panel.text_editor.get("1.0", "end").strip() == "3 + 4 7"
    assert tab.code_panel.text_editor.get(tk.SEL_FIRST, tk.SEL_LAST) == " 7"


@with_fixtures(SwordfishGuiFixture)
def test_print_selection_evaluates_through_interruptible_foreground_activity(
    fixture,
):
    """AI: Print must evaluate through a ForegroundActivity rather than a synchronous
    UI-thread call, so the menu-bar Stop can hard-break a slow print -- the same
    interruptibility guarantee every selection evaluation now shares."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    fixture.mock_browser.run_code.return_value = make_mock_gemstone_object(
        "Integer", "7"
    )
    submitted_activities = []
    original_run_foreground_activity = fixture.application.run_foreground_activity

    def record_then_run(activity):
        submitted_activities.append(activity)
        return original_run_foreground_activity(activity)

    fixture.application.run_foreground_activity = record_then_run
    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Print")

    assert len(submitted_activities) == 1
    assert isinstance(submitted_activities[0], ForegroundActivity)


@with_fixtures(SwordfishGuiFixture)
def test_print_selection_failure_reports_error_and_leaves_editor_unchanged(fixture):
    """AI: A failed print evaluation reports the error under the action's name and
    leaves the editor text exactly as it was -- no partial or garbage insertion."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "self error: 'boom'")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.18")
    fixture.mock_browser.run_code = Mock(side_effect=DomainException("boom"))

    menu = fixture.open_text_context_menu_for_tab(tab)
    with patch("reahl.swordfish.ui_support.messagebox") as mock_messagebox:
        fixture.invoke_menu_command(menu, "Print")

    mock_messagebox.showerror.assert_called_once()
    title, _message = mock_messagebox.showerror.call_args.args
    assert title == "Print Selection"
    assert (
        tab.code_panel.text_editor.get("1.0", "end").strip() == "self error: 'boom'"
    )


@with_fixtures(SwordfishGuiFixture)
def test_graph_inspect_command_from_method_source_context_menu_opens_graph_for_selection(
    fixture,
):
    """AI: Choosing Show in Object Diagram from method source context menu should evaluate selected source and open Graph on the result."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    inspected_object = make_mock_gemstone_object("Integer", "7", oop=3004)
    fixture.mock_browser.run_code.return_value = inspected_object
    tab.code_panel.application.open_object_diagram_for_object = Mock()

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Show in Object Diagram")

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    tab.code_panel.application.open_object_diagram_for_object.assert_called_with(
        inspected_object,
    )


@with_fixtures(SwordfishGuiFixture)
def test_text_context_menu_includes_debug_for_selected_text_in_open_tab(
    fixture,
):
    """AI: Inspect, Run and Debug travel together, so selecting method source must also expose Debug."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 + 4\n5 + 6")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")

    menu = fixture.open_text_context_menu_for_tab(tab)
    command_labels = menu_command_labels(menu)

    assert "Debug" in command_labels


@with_fixtures(SwordfishGuiFixture)
def test_debug_command_from_method_source_context_menu_opens_debugger_for_runtime_error(
    fixture,
):
    """AI: Debug from method source evaluates the selection and opens the Debugger when it raises a runtime error."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "1/0")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.3")
    runtime_error = FakeGemstoneError()
    fixture.mock_browser.run_code.side_effect = runtime_error
    tab.code_panel.application.open_debugger = Mock()

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Debug")

    fixture.mock_browser.debug_source.assert_called_with("1/0")
    tab.code_panel.application.open_debugger.assert_called_once_with(runtime_error)


@with_fixtures(SwordfishGuiFixture)
def test_debug_command_from_method_source_context_menu_ignores_compile_error(
    fixture,
):
    """AI: A compile error in the selection is a coding mistake, not a runtime stop, so Debug must not open the Debugger."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "3 +")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.3")
    fixture.mock_browser.run_code.side_effect = FakeCompileGemstoneError("3 +", 3)
    tab.code_panel.application.open_debugger = Mock()

    menu = fixture.open_text_context_menu_for_tab(tab)
    with patch("reahl.swordfish.text_editing.messagebox") as mock_messagebox:
        fixture.invoke_menu_command(menu, "Debug")

    tab.code_panel.application.open_debugger.assert_not_called()
    mock_messagebox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_save_command_from_text_context_menu_compiles_to_gemstone(fixture):
    """AI: Choosing Save from text context menu compiles the current editor contents."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^99")

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Save")

    fixture.mock_browser.compile_method.assert_called_with(
        "OrderLine", True, "total\n    ^99"
    )


@with_fixtures(SwordfishGuiFixture)
def test_browse_class_from_source_jumps_to_class_under_cursor(fixture):
    """AI: Browse Class reads the identifier under the insertion cursor,
    updates the browser model AND publishes SelectedClassChanged so the
    browser UI repaints. Without the publish, jump_to_class succeeds
    silently and nothing visibly happens — the bug this test pins."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^OrderLine new")
    tab.code_panel.text_editor.mark_set("insert", "2.7")
    fixture.session_record.jump_to_class = Mock()

    published_events = []
    original_publish = fixture.application.event_queue.publish
    def recording_publish(*args, **kwargs):
        published_events.append(args[0])
        return original_publish(*args, **kwargs)
    fixture.application.event_queue.publish = recording_publish

    tab.code_panel.browse_class_from_source()

    fixture.session_record.jump_to_class.assert_called_once_with(
        "OrderLine", True
    )
    assert "SelectedClassChanged" in published_events


@with_fixtures(SwordfishGuiFixture)
def test_browse_class_warns_when_identifier_is_not_capitalised(fixture):
    """AI: A cursor on a lowercase identifier (a variable like `amount`)
    earns a friendly 'Not a Class Name' warning rather than a generic
    GemStone error from the server. The cheap local check prevents a
    wasted server round-trip for the common variable-under-cursor case."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^amount * quantity")
    tab.code_panel.text_editor.mark_set("insert", "2.6")
    fixture.session_record.jump_to_class = Mock()

    with patch("reahl.swordfish.text_editing.messagebox") as mock_messagebox:
        tab.code_panel.browse_class_from_source()

    mock_messagebox.showwarning.assert_called_once()
    title, _message = mock_messagebox.showwarning.call_args.args
    assert title == "Not a Class Name"
    fixture.session_record.jump_to_class.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_browse_class_warns_when_no_such_class_exists(fixture):
    """AI: When the identifier looks like a class but the server replies
    with a GemstoneError (class not in the system), Browse Class shows a
    specific 'No Such Class' warning rather than letting the error bubble
    to the generic report_callback_exception dialog."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^Nonexistent new")
    tab.code_panel.text_editor.mark_set("insert", "2.7")
    fixture.session_record.jump_to_class = Mock(side_effect=FakeGemstoneError())

    published_events = []
    original_publish = fixture.application.event_queue.publish
    def recording_publish(*args, **kwargs):
        published_events.append(args[0])
        return original_publish(*args, **kwargs)
    fixture.application.event_queue.publish = recording_publish

    with patch.object(messagebox, "showwarning") as mock_showwarning:
        tab.code_panel.browse_class_from_source()

    mock_showwarning.assert_called_once()
    title, _message = mock_showwarning.call_args.args
    assert title == "No Such Class"
    assert "SelectedClassChanged" not in published_events


@with_fixtures(SwordfishGuiFixture)
def test_cancel_reverts_dirty_buffer_to_saved_source(fixture):
    """AI: Invoking Cancel on a dirty editor tab discards the in-buffer edits
    and reloads the saved source from GemStone, clearing the dirty flag."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "garbage\n    ^nil")
    tab.mark_dirty()
    assert tab.is_dirty

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Cancel")

    assert (
        tab.code_panel.text_editor.get("1.0", "end-1c")
        == "total\n    ^amount * quantity"
    )
    assert tab.is_dirty is False


@with_fixtures(SwordfishGuiFixture)
def test_editor_notebook_uses_closable_style(fixture):
    """AI: The method editor's notebook is wired with the close-button
    style so every tab gets an 'x'."""
    editor = fixture.browser_window.editor_area_widget
    assert editor.editor_notebook.cget('style') == 'Closable.TNotebook'


@with_fixtures(SwordfishGuiFixture)
def test_close_editor_tab_at_index_removes_that_tab(fixture):
    """AI: Closing a tab via the close-button dispatch removes that tab from
    the editor's open_tabs registry (and only that one)."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total", pin=True)
    fixture.select_down_to_method(
        "Kernel", "OrderLine", "accessing", "description", pin=True
    )

    editor = fixture.browser_window.editor_area_widget
    editor.editor_notebook.close_tab_at_index(0)

    assert list(editor.open_tabs.keys()) == [("OrderLine", True, "description")]


@with_fixtures(SwordfishGuiFixture)
def test_close_command_from_tab_menu_closes_the_tab(fixture):
    """AI: Choosing Close from the tab's right-click menu removes that tab."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    menu = fixture.open_tab_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Close")

    assert (
        "OrderLine",
        True,
        "total",
    ) not in fixture.browser_window.editor_area_widget.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_jump_to_class_command_from_tab_menu_syncs_browser_selection(
    fixture,
):
    """AI: Choosing Jump to Class from the tab's right-click menu synchronizes package/class/side/category/method browser selections to that method context."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    fixture.browser_window.classes_widget.selection_var.set("class")
    fixture.root.update()
    assert fixture.browser_window.classes_widget.selection_var.get() == "class"

    menu = fixture.open_tab_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Jump to Class")

    assert fixture.session_record.selected_package == "Kernel"
    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.show_instance_side is True
    assert fixture.session_record.selected_method_category == "accessing"
    assert fixture.session_record.selected_method_symbol == "total"
    assert fixture.browser_window.classes_widget.selection_var.get() == "instance"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.packages_widget.selection_list.selection_listbox
        )
        == "Kernel"
    )
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.classes_widget.selection_list.selection_listbox
        )
        == "OrderLine"
    )
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox
        )
        == "accessing"
    )
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.methods_widget.selection_list.selection_listbox
        )
        == "total"
    )


@with_fixtures(SwordfishGuiFixture)
def test_text_editor_context_menu_paste_replaces_selected_text_and_undo_restores_it(
    fixture,
):
    """Pasting from the editor context menu replaces selected text and Undo restores the previous source."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "alpha beta")
    tab.code_panel.text_editor.tag_add(tk.SEL, "1.6", "1.10")

    fixture.root.clipboard_clear()
    fixture.root.clipboard_append("gamma")

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Paste")
    assert tab.code_panel.text_editor.get("1.0", "end-1c") == "alpha gamma"

    menu = fixture.open_text_context_menu_for_tab(tab)
    fixture.invoke_menu_command(menu, "Undo")
    assert tab.code_panel.text_editor.get("1.0", "end-1c") == "alpha beta"

    tab.code_panel.text_editor.tag_add(tk.SEL, "1.6", "1.10")
    tab.code_panel.replace_selected_text_editor_before_typing(
        types.SimpleNamespace(state=0, char="q", keysym="q"),
    )
    tab.code_panel.text_editor.insert(tk.INSERT, "q")
    assert tab.code_panel.text_editor.get("1.0", "end-1c") == "alpha q"


@with_fixtures(SwordfishGuiFixture)
def test_selector_for_navigation_uses_full_keyword_selector_from_selected_send_fragment(
    fixture,
):
    """AI: Selecting a keyword send fragment with arguments should resolve to the full keyword selector token sequence."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert(
        "1.0",
        "total\n" "    ^self _twoArgInstPrim: 4 with: srcByteObj with: destByteObj",
    )
    selection_start = tab.code_panel.text_editor.search(
        "_twoArgInstPrim:",
        "1.0",
        stopindex="end",
    )
    selection_end = tab.code_panel.text_editor.search(
        "destByteObj",
        "1.0",
        stopindex="end",
    )
    tab.code_panel.text_editor.tag_add(
        tk.SEL,
        selection_start,
        selection_end,
    )

    resolved_selector = tab.code_panel.selector_for_navigation()

    assert resolved_selector == "_twoArgInstPrim:with:with:"


@with_fixtures(SwordfishGuiFixture)
def test_opening_hierarchy_tab_builds_and_expands_tree_for_selected_class(fixture):
    """AI: Switching to hierarchy view should show superclass/child structure and expand to the selected class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )

    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()

    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    order_line_item = child_with_text(order_item, "OrderLine")

    assert tree.selection() == (order_line_item,)
    assert tree.item(object_item, "open")
    assert tree.item(order_item, "open")
    assert tree.set(order_line_item, "class_category") == "Kernel"


@with_fixtures(SwordfishGuiFixture)
def test_selecting_class_in_hierarchy_selects_default_category_and_refreshes_methods(
    fixture,
):
    """AI: Selecting a class in hierarchy view should auto-select a method category and refresh method views."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()

    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    child_with_text(order_item, "OrderLine")
    classes_widget.select_class(
        "OrderLine",
        selection_source="hierarchy",
        class_category="Kernel",
    )
    fixture.root.update()

    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_method_category == "all"
    assert (
        fixture.selected_listbox_entry(
            fixture.browser_window.categories_widget.selection_list.selection_listbox,
        )
        == "all"
    )
    method_entries = list(
        fixture.browser_window.methods_widget.selection_list.selection_listbox.get(
            0,
            "end",
        )
    )
    assert method_entries == ["total", "description"]


@with_fixtures(SwordfishGuiFixture)
def test_show_class_definition_displays_and_updates_for_selected_class(fixture):
    """AI: Enabling class definition view should render the selected class definition and refresh when selection changes."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    classes_widget = fixture.browser_window.classes_widget
    assert (
        str(classes_widget.class_definition_frame)
        not in classes_widget.class_content_paned.panes()
    )
    assert str(classes_widget.selection_list.master) == str(
        classes_widget.classes_notebook
    )
    assert str(classes_widget.class_controls_frame.master) == str(classes_widget)
    assert int(classes_widget.class_controls_frame.grid_info()["row"]) == 1
    initial_requested_width = classes_widget.winfo_reqwidth()
    assert (
        classes_widget.class_radiobutton.grid_info()["row"]
        == classes_widget.instance_radiobutton.grid_info()["row"]
        == classes_widget.show_class_definition_checkbox.grid_info()["row"]
        == 0
    )
    assert int(classes_widget.instance_radiobutton.grid_info()["column"]) == 0
    assert int(classes_widget.class_radiobutton.grid_info()["column"]) == 1
    classes_widget.show_class_definition_var.set(True)
    classes_widget.toggle_class_definition()
    fixture.root.update()
    assert (
        str(classes_widget.class_definition_frame)
        in classes_widget.class_content_paned.panes()
    )
    shown_requested_width = classes_widget.winfo_reqwidth()
    assert shown_requested_width <= initial_requested_width + 10
    assert int(classes_widget.class_controls_frame.grid_info()["row"]) == 1
    classes_widget.class_content_paned.sashpos(0, 150)
    fixture.root.update()
    sash_position_after_drag = classes_widget.class_content_paned.sashpos(0)

    rendered_definition = classes_widget.class_definition_text.get(
        "1.0",
        "end",
    ).strip()
    rendered_line_numbers = (
        classes_widget.class_definition_line_number_column.line_numbers_text.get(
            "1.0",
            "end-1c",
        ).splitlines()
    )
    assert rendered_line_numbers[:3] == ["1", "2", "3"]
    classes_widget.class_definition_text.mark_set(tk.INSERT, "2.3")
    classes_widget.class_definition_cursor_position_indicator.update_position()
    assert (
        classes_widget.class_definition_cursor_position_label.cget("text")
        == "Ln 2, Col 4"
    )
    assert "Order subclass: 'OrderLine'" in rendered_definition
    assert "instVarNames: #(amount quantity)" in rendered_definition
    assert "inDictionary: Kernel" in rendered_definition

    fixture.browser_window.classes_widget.selection_list.selection_listbox.selection_clear(
        0,
        "end",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "Order",
    )
    fixture.root.update()
    updated_definition = classes_widget.class_definition_text.get(
        "1.0",
        "end",
    ).strip()
    assert "Object subclass: 'Order'" in updated_definition
    assert "instVarNames: #(lines)" in updated_definition

    classes_widget.show_class_definition_var.set(False)
    classes_widget.toggle_class_definition()
    fixture.root.update()
    assert (
        str(classes_widget.class_definition_frame)
        not in classes_widget.class_content_paned.panes()
    )
    assert int(classes_widget.class_controls_frame.grid_info()["row"]) == 1

    classes_widget.show_class_definition_var.set(True)
    classes_widget.toggle_class_definition()
    fixture.root.update()
    restored_sash_position = classes_widget.class_content_paned.sashpos(0)
    assert abs(restored_sash_position - sash_position_after_drag) <= 5


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_checkbox_shows_class_hierarchy(fixture):
    """AI: Enabling method inheritance view should show the selected method's superclass chain as class names only."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget
    assert str(methods_widget.controls_frame.master) == str(methods_widget)
    assert int(methods_widget.controls_frame.grid_info()["row"]) == 1
    assert (
        str(methods_widget.method_hierarchy_frame)
        not in methods_widget.method_content_paned.panes()
    )
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    assert (
        str(methods_widget.method_hierarchy_frame)
        in methods_widget.method_content_paned.panes()
    )
    assert int(methods_widget.controls_frame.grid_info()["row"]) == 1
    assert fixture.session_record.selected_method_symbol == "total"
    method_hierarchy_tree = methods_widget.method_hierarchy_tree
    root_item_ids = method_hierarchy_tree.get_children("")
    assert len(root_item_ids) == 1
    assert method_hierarchy_tree.item(root_item_ids[0], "text") == "Object"
    fixture.root.update()

    tree = methods_widget.method_hierarchy_tree
    root_item_ids = tree.get_children("")
    assert len(root_item_ids) == 1
    object_item = root_item_ids[0]
    order_item_ids = tree.get_children(object_item)
    assert len(order_item_ids) == 1
    order_item = order_item_ids[0]
    order_line_item_ids = tree.get_children(order_item)
    assert len(order_line_item_ids) == 1
    order_line_item = order_line_item_ids[0]

    assert tree.item(object_item, "text") == "Object"
    assert tree.item(order_item, "text") == "Order"
    assert tree.item(order_line_item, "text") == "OrderLine"
    assert tree.selection() == (order_line_item,)
    methods_widget.show_method_hierarchy_var.set(False)
    methods_widget.toggle_method_hierarchy()
    fixture.root.update()
    assert (
        str(methods_widget.method_hierarchy_frame)
        not in methods_widget.method_content_paned.panes()
    )
    assert int(methods_widget.controls_frame.grid_info()["row"]) == 1


@with_fixtures(SwordfishGuiFixture)
def test_methods_pane_does_not_show_add_method_button(fixture):
    """AI: Method creation should be offered through context menu actions, not a permanent button in the methods pane."""
    methods_widget = fixture.browser_window.methods_widget
    assert not hasattr(methods_widget, "add_method_button")


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_hierarchy_refreshes_on_method_selection_change(fixture):
    """AI: Selecting a different method in the methods list should immediately refresh inheritance analysis for the new selector."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.mock_browser.get_compiled_method.reset_mock()

    methods_listbox = methods_widget.selection_list.selection_listbox
    methods_listbox.selection_clear(0, "end")
    fixture.select_in_listbox(
        methods_listbox,
        "description",
    )

    expected_calls = [
        call("Object", "description", True),
        call("Order", "description", True),
        call("OrderLine", "description", True),
    ]
    fixture.mock_browser.get_compiled_method.assert_has_calls(expected_calls)


@with_fixtures(SwordfishGuiFixture)
def test_method_hierarchy_sync_is_not_mistaken_for_a_user_jump(fixture):
    """AI: Selecting a method programmatically syncs the hierarchy tree selection, which makes
    ttk queue <<TreeviewSelect>> events for later delivery. Those echoes must not be treated
    as the user jumping to a class: the selection already matches the session state, so no
    jump (and none of its GemStone lookups) may be triggered."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.root.update()
    fixture.mock_browser.get_method_category.reset_mock()

    methods_listbox = methods_widget.selection_list.selection_listbox
    methods_listbox.selection_clear(0, "end")
    fixture.select_in_listbox(
        methods_listbox,
        "description",
    )
    fixture.root.update()

    fixture.mock_browser.get_method_category.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_selecting_a_method_preserves_the_all_category_selection(fixture):
    """AI: Clicking a method while browsing the 'all' pseudo-category must not narrow the
    category selection to the method's home category."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    fixture.select_in_listbox(
        fixture.browser_window.categories_widget.selection_list.selection_listbox,
        "all",
    )
    assert fixture.session_record.selected_method_category == "all"
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.root.update()

    fixture.select_in_listbox(
        methods_widget.selection_list.selection_listbox,
        "total",
    )
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "total"
    assert fixture.session_record.selected_method_category == "all"


@with_fixtures(SwordfishGuiFixture)
def test_method_list_can_show_inherited_methods_in_grey(fixture):
    """AI: Enabling inherited methods should add inherited selectors to the current class method list and render them in grey."""

    def list_methods(class_name, method_category, show_instance_side):
        if not show_instance_side or method_category != "accessing":
            return []
        if class_name == "OrderLine":
            return ["description"]
        if class_name == "Order":
            return ["total"]
        return []

    fixture.mock_browser.list_methods.side_effect = list_methods
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")
    methods_widget = fixture.browser_window.methods_widget
    methods_listbox = methods_widget.selection_list.selection_listbox

    assert list(methods_listbox.get(0, "end")) == ["description"]

    methods_widget.show_inherited_methods_var.set(True)
    methods_widget.repopulate()
    fixture.root.update()

    assert list(methods_listbox.get(0, "end")) == ["description", "total"]
    assert str(methods_listbox.itemcget(1, "foreground")) == "gray50"


@with_fixtures(SwordfishGuiFixture)
def test_selecting_inherited_method_from_method_list_selects_owner_class(fixture):
    """AI: Selecting an inherited method from the method list should switch the browser to the class that defines that selector."""

    def list_methods(class_name, method_category, show_instance_side):
        if not show_instance_side or method_category != "accessing":
            return []
        if class_name == "OrderLine":
            return ["description"]
        if class_name == "Order":
            return ["total"]
        return []

    fixture.mock_browser.list_methods.side_effect = list_methods
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "description")
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_inherited_methods_var.set(True)
    methods_widget.repopulate()
    fixture.root.update()

    fixture.select_in_listbox(
        methods_widget.selection_list.selection_listbox,
        "total",
    )

    assert fixture.session_record.selected_class == "Order"
    assert fixture.session_record.selected_method_category == "accessing"
    assert fixture.session_record.selected_method_symbol == "total"
    assert (
        "Order",
        True,
        "total",
    ) in fixture.browser_window.editor_area_widget.open_tabs


@with_fixtures(SwordfishGuiFixture)
def test_method_inheritance_updates_after_explicit_method_click_from_hierarchy_class_view(
    fixture,
):
    """AI: With class selected from hierarchy view and no method selected, clicking a method should refresh method inheritance for that method."""
    fixture.browser_window.packages_widget.browse_mode_var.set("categories")
    fixture.browser_window.packages_widget.change_browse_mode()
    fixture.root.update()
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    classes_widget.select_class(
        "OrderLine",
        selection_source="hierarchy",
        class_category="Kernel",
    )
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol is None
    assert fixture.session_record.selected_method_category == "all"

    methods_widget = fixture.browser_window.methods_widget
    methods_widget.show_method_hierarchy_var.set(True)
    methods_widget.toggle_method_hierarchy()
    fixture.root.update()
    assert not methods_widget.method_hierarchy_tree.get_children("")

    fixture.mock_browser.get_compiled_method.reset_mock()
    methods_listbox = methods_widget.selection_list.selection_listbox
    methods_listbox.selection_clear(0, "end")
    fixture.select_in_listbox(
        methods_listbox,
        "total",
    )
    fixture.root.update()

    assert fixture.session_record.selected_method_symbol == "total"
    expected_calls = [
        call("Object", "total", True),
        call("Order", "total", True),
        call("OrderLine", "total", True),
    ]
    fixture.mock_browser.get_compiled_method.assert_has_calls(expected_calls)
    assert methods_widget.method_hierarchy_tree.get_children("")


@with_fixtures(SwordfishGuiFixture)
def test_browser_window_has_four_selection_columns(fixture):
    """The browser window contains exactly four selection column widgets:
    packages, classes, categories, and methods."""
    children = fixture.browser_window.top_frame.winfo_children()
    assert len(children) == 4


@with_fixtures(SwordfishGuiFixture)
def test_switching_side_clears_selected_category(fixture):
    """Switching between Instance and Class side resets the selected category
    so the method list does not try to fetch methods for a category that only
    exists on the old side."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    assert fixture.session_record.selected_method_category == "accessing"

    fixture.browser_window.classes_widget.switch_side()
    fixture.root.update()

    assert fixture.session_record.selected_method_category is None


class FakeGemstoneError(GemstoneError):
    """AI: Minimal GemstoneError for testing — bypasses the real constructor
    which requires an active session and a C error structure."""

    def __init__(self):
        pass

    def __str__(self):
        return "AI: Simulated Smalltalk error"

    @property
    def context(self):
        return None


class FakeCompileGemstoneError(GemstoneError):
    """AI: Minimal compile error carrying GemStone-like structured arguments."""

    def __init__(self, source_text, source_offset):
        self.source_text = source_text
        self.source_offset = source_offset

    def __str__(self):
        return "a CompileError occurred (error 1001), unexpected token"

    @property
    def number(self):
        return 1001

    @property
    def args(self):
        return ([[1034, self.source_offset, "unexpected token"]], self.source_text)

    @property
    def context(self):
        return None


class SwordfishAppFixture(Fixture):
    @set_up
    def create_app(self):
        self.mock_gemstone_session = Mock()
        self.mock_browser = Mock(spec=GemstoneBrowserSession)
        route_debug_source_through_real_session(self.mock_browser)
        self.mock_browser.list_categories.return_value = ["Kernel", "Collections"]
        self.mock_browser.list_dictionaries.return_value = [
            "Kernel",
            "Collections",
        ]
        self.mock_browser.list_classes_in_category.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.list_classes_in_dictionary.return_value = [
            "OrderLine",
            "Order",
        ]
        self.mock_browser.rowan_installed.return_value = False
        self.mock_browser.list_rowan_packages.return_value = []
        self.mock_browser.list_classes_in_rowan_package.return_value = []
        self.mock_browser.list_method_categories.return_value = ["accessing"]
        self.mock_browser.list_methods.return_value = ["total", "description"]
        self.mock_browser.list_breakpoints.return_value = []
        self.mock_browser.get_method_category.return_value = "accessing"
        class_definitions = {
            "OrderAudit": {
                "class_name": "OrderAudit",
                "superclass_name": "Order",
                "package_name": "Kernel",
                "inst_var_names": ["entries"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "SpecialOrderLine": {
                "class_name": "SpecialOrderLine",
                "superclass_name": "OrderLine",
                "package_name": "Kernel",
                "inst_var_names": ["discount"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "OrderLine": {
                "class_name": "OrderLine",
                "superclass_name": "Order",
                "package_name": "Kernel",
                "inst_var_names": ["amount", "quantity"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Order": {
                "class_name": "Order",
                "superclass_name": "Object",
                "package_name": "Kernel",
                "inst_var_names": ["lines"],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
            "Object": {
                "class_name": "Object",
                "superclass_name": None,
                "package_name": "Kernel",
                "inst_var_names": [],
                "class_var_names": [],
                "class_inst_var_names": [],
                "pool_dictionary_names": [],
            },
        }

        def get_class_definition(class_name):
            class_definition = class_definitions.get(class_name)
            if class_definition is None:
                raise GemstoneDomainException("Unknown class_name.")
            return class_definition

        self.mock_browser.get_class_definition.side_effect = get_class_definition

        # AI: Chained mock for EditorTab.repopulate() which calls
        # get_compiled_method().sourceString().to_py
        mock_method = Mock()
        mock_method.sourceString.return_value.to_py = "total\n    ^1"
        self.mock_browser.get_compiled_method.return_value = mock_method

        # AI: Bypass GemstoneSessionRecord.__init__ (which opens a live GemStone
        # connection) by using __new__ and manually setting all instance variables.
        self.session_record = GemstoneSessionRecord.__new__(GemstoneSessionRecord)
        self.session_record.gemstone_session = self.mock_gemstone_session
        self.session_record.gemstone_browser_session = self.mock_browser
        self.session_record.selected_package = None
        self.session_record.selected_dictionary = None
        self.session_record.selected_class = None
        self.session_record.selected_method_category = None
        self.session_record.selected_method_symbol = None
        self.session_record.show_instance_side = True
        self.session_record.browse_mode = "dictionaries"
        self.session_record.transaction_is_dirty = False

        self.app = Swordfish(experimental=True)
        # AI: Run foreground activities (searches) inline so they complete within the call
        # that starts them -- deterministic, with no worker-thread/Tk-timing races. The
        # threaded path is exercised by its own dedicated test, which opts back out.
        self.app.run_activities_synchronously = True
        self.app.withdraw()
        self.app.mcp_server_controller.configuration_store.can_write_config = Mock(
            return_value=True
        )
        self.app.login_gemstone_script_source = ""
        self.app.update()

    @tear_down
    def destroy_app(self):
        self.app.destroy()

    def simulate_login(self):
        """AI: Publish LoggedInSuccessfully to transition the app to the
        browser interface without going through the real login dialog."""
        self.app.event_queue.publish("LoggedInSuccessfully", self.session_record)
        self.app.update()
        self.mock_browser.reset_mock()

    def select_in_listbox(self, listbox, item):
        """AI: Simulate a user clicking an item in one of the full app browser lists."""
        items = listbox.get(0, "end")
        item_index = list(items).index(item)
        listbox.selection_clear(0, "end")
        listbox.selection_set(item_index)
        selection_list = listbox.master
        selection_list.handle_selection(types.SimpleNamespace(widget=listbox))
        self.app.update()

    def select_down_to_method(self, package, class_name, category, method):
        """AI: Navigate the main browser tab to a concrete method selection."""
        self.select_in_listbox(
            self.app.browser_tab.packages_widget.selection_list.selection_listbox,
            package,
        )
        self.select_in_listbox(
            self.app.browser_tab.classes_widget.selection_list.selection_listbox,
            class_name,
        )
        self.select_in_listbox(
            self.app.browser_tab.categories_widget.selection_list.selection_listbox,
            category,
        )
        self.select_in_listbox(
            self.app.browser_tab.methods_widget.selection_list.selection_listbox,
            method,
        )

    def select_down_to_class(self, package, class_name):
        """AI: Navigate the main browser tab to a class selection without selecting a method."""
        self.select_in_listbox(
            self.app.browser_tab.packages_widget.selection_list.selection_listbox,
            package,
        )
        self.select_in_listbox(
            self.app.browser_tab.classes_widget.selection_list.selection_listbox,
            class_name,
        )


@with_fixtures(SwordfishAppFixture)
def test_successful_login_switches_to_browser_interface(fixture):
    """Providing valid credentials causes the app to transition from the
    login screen to the main browser interface with a notebook visible."""
    with patch.object(
        GemstoneSessionRecord, "log_in_linked", return_value=fixture.session_record
    ):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert fixture.app.is_logged_in
    assert fixture.app.notebook is not None


@with_fixtures(SwordfishAppFixture)
def test_login_runs_configured_gemstone_login_script_before_showing_main_screen(
    fixture,
):
    """AI: A configured GemStone login script should be evaluated as part of login before the IDE enters the logged-in state."""
    fixture.app.login_gemstone_script_source = "System stoneName"
    fixture.session_record.run_code = Mock(
        return_value=types.SimpleNamespace(to_py="gs64stone")
    )
    published_events = []
    original_publish = fixture.app.event_queue.publish

    def publish_and_record(*args, **kwargs):
        published_events.append(args[0])
        return original_publish(*args, **kwargs)

    with patch.object(
        GemstoneSessionRecord, "log_in_linked", return_value=fixture.session_record
    ):
        with patch.object(
            fixture.app.event_queue,
            "publish",
            side_effect=publish_and_record,
        ):
            fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert fixture.app.is_logged_in
    fixture.session_record.run_code.assert_called_once_with("System stoneName")
    assert published_events == ["LoggedInSuccessfully"]


@with_fixtures(SwordfishAppFixture)
def test_failed_login_script_keeps_user_on_login_screen(fixture):
    """AI: If the configured GemStone login script fails, login should abort and the opened session should be closed."""
    fixture.app.login_gemstone_script_source = "self error: 'boom'"
    fixture.session_record.run_code = Mock(side_effect=DomainException("boom"))

    with patch.object(
        GemstoneSessionRecord, "log_in_linked", return_value=fixture.session_record
    ):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert not fixture.app.is_logged_in
    assert fixture.app.login_frame.error_label is not None
    assert "boom" in fixture.app.login_frame.error_label.cget("text")
    fixture.mock_gemstone_session.log_out.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_login_screen_defaults_stone_name_to_gs64stone(fixture):
    """AI: The login screen should prefill stone name with gs64stone when no CLI argument is supplied."""
    assert fixture.app.login_frame.stone_name_entry.get() == "gs64stone"


@with_fixtures(SwordfishAppFixture)
def test_swordfish_custom_default_stone_name_prefills_login_field(fixture):
    """AI: A configured default stone name should be shown in the login screen stone field."""
    custom_app = Swordfish(default_stone_name="customStone")
    custom_app.withdraw()
    custom_app.update()
    assert custom_app.login_frame.stone_name_entry.get() == "customStone"
    custom_app.destroy()


def test_run_application_uses_default_stone_name_when_arg_not_given():
    """AI: run_application should construct Swordfish with gs64stone by default and leave embedded MCP stopped."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop") as swordfish_mainloop:
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=McpRuntimeConfig(),
            ):
                with patch("sys.argv", ["swordfish"]):
                    Swordfish.run()
    init_swordfish.assert_called_once()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    assert swordfish_call_arguments["default_stone_name"] == "gs64stone"
    assert not swordfish_call_arguments["start_embedded_mcp"]
    assert swordfish_call_arguments["mcp_runtime_config"].mcp_host == "127.0.0.1"
    swordfish_mainloop.assert_called_once()


def test_run_application_uses_cli_stone_name_when_given():
    """AI: run_application should pass an explicitly provided stone name into Swordfish with embedded MCP stopped."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop") as swordfish_mainloop:
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=McpRuntimeConfig(),
            ):
                with patch("sys.argv", ["swordfish", "myStone"]):
                    Swordfish.run()
    init_swordfish.assert_called_once()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    assert swordfish_call_arguments["default_stone_name"] == "myStone"
    assert not swordfish_call_arguments["start_embedded_mcp"]
    swordfish_mainloop.assert_called_once()


def test_run_application_passes_theme_override_from_command_line():
    """AI: A --theme on the command line overrides the configured appearance.theme: it reaches
    Swordfish as theme_override, the higher-priority source of the 'configured theme name' that
    the one theme resolver then honours over the saved config."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop"):
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=McpRuntimeConfig(),
            ):
                with patch("sys.argv", ["swordfish", "--theme", "dark"]):
                    Swordfish.run()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    assert swordfish_call_arguments["theme_override"] == "dark"


def test_run_application_has_no_theme_override_without_the_command_line_flag():
    """AI: Without --theme there is no override, so the configured appearance.theme (then OS, then
    light) is left to decide; the absence is signalled as None, not a guessed default."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop"):
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=McpRuntimeConfig(),
            ):
                with patch("sys.argv", ["swordfish"]):
                    Swordfish.run()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    assert swordfish_call_arguments["theme_override"] is None


def test_run_application_uses_saved_mcp_config_when_no_cli_runtime_overrides():
    """AI: run_application should load saved MCP runtime settings when no explicit MCP CLI overrides are supplied."""
    saved_runtime_config = McpRuntimeConfig(
        allow_source_read=True,
        allow_eval_arbitrary=True,
        allow_source_write=True,
        allow_ide_read=True,
        allow_ide_write=True,
        allow_commit=True,
        allow_tracing=True,
        mcp_host="10.0.0.5",
        mcp_port=9177,
        mcp_http_path="/saved",
    )
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop"):
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=saved_runtime_config,
            ):
                with patch("sys.argv", ["swordfish"]):
                    Swordfish.run()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    resolved_runtime_config = swordfish_call_arguments["mcp_runtime_config"]
    assert resolved_runtime_config.allow_eval_arbitrary
    assert resolved_runtime_config.allow_source_write
    assert resolved_runtime_config.allow_ide_read
    assert resolved_runtime_config.allow_ide_write
    assert resolved_runtime_config.allow_commit
    assert resolved_runtime_config.allow_tracing
    assert resolved_runtime_config.mcp_host == "10.0.0.5"
    assert resolved_runtime_config.mcp_port == 9177
    assert resolved_runtime_config.mcp_http_path == "/saved"


def test_run_application_cli_runtime_overrides_take_precedence_over_saved_mcp_config():
    """AI: Explicit MCP CLI flags should override matching saved MCP config fields while leaving the rest unchanged."""
    saved_runtime_config = McpRuntimeConfig(
        allow_source_read=False,
        allow_eval_arbitrary=False,
        allow_source_write=True,
        allow_ide_read=False,
        allow_ide_write=False,
        allow_commit=False,
        allow_tracing=True,
        mcp_host="10.0.0.5",
        mcp_port=9177,
        mcp_http_path="/saved",
    )
    resolved_runtime_config = saved_runtime_config.copy()
    resolved_runtime_config.update_with(
        allow_eval_arbitrary=True,
        allow_source_read=True,
        allow_ide_read=True,
        mcp_host="127.0.0.1",
        mcp_port=8123,
    )
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(Swordfish, "mainloop"):
            with patch.object(
                McpConfigurationStore,
                "merged_config_from_arguments",
                return_value=resolved_runtime_config,
            ):
                with patch(
                    "sys.argv",
                    [
                        "swordfish",
                        "--allow-eval-arbitrary",
                        "--allow-source-read",
                        "--allow-ide-read",
                        "--mcp-host",
                        "127.0.0.1",
                        "--mcp-port",
                        "8123",
                    ],
                ):
                    Swordfish.run()
    swordfish_call_arguments = init_swordfish.call_args.kwargs
    resolved_runtime_config = swordfish_call_arguments["mcp_runtime_config"]
    assert resolved_runtime_config.allow_eval_arbitrary
    assert resolved_runtime_config.allow_source_read
    assert resolved_runtime_config.allow_source_write
    assert resolved_runtime_config.allow_ide_read
    assert not resolved_runtime_config.allow_ide_write
    assert not resolved_runtime_config.allow_commit
    assert resolved_runtime_config.allow_tracing
    assert resolved_runtime_config.mcp_host == "127.0.0.1"
    assert resolved_runtime_config.mcp_port == 8123
    assert resolved_runtime_config.mcp_http_path == "/saved"


def test_cli_permission_overrides_are_ignored_with_warning_when_config_is_read_only():
    """AI: CLI permission flags must not override a read-only config — the same gate that locks the UI should lock the CLI."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': temporary_directory}):
            configuration_store = McpConfigurationStore()
            persisted_config = McpRuntimeConfig(
                allow_source_read=False,
                allow_source_write=False,
                allow_eval_arbitrary=False,
                allow_test_execution=False,
                allow_ide_read=False,
                allow_ide_write=False,
                allow_commit=False,
                allow_tracing=False,
                mcp_host='10.0.0.5',
                mcp_port=9177,
                mcp_http_path='/saved',
            )
            configuration_store.save(persisted_config)
            arguments = types.SimpleNamespace(
                allow_source_read=True,
                allow_source_write=True,
                allow_eval_arbitrary=True,
                allow_test_execution=True,
                allow_ide_read=True,
                allow_ide_write=True,
                allow_commit=True,
                allow_tracing=True,
                mcp_host='127.0.0.1',
                mcp_port=8000,
                mcp_http_path='/mcp',
            )
            argument_tokens = [
                '--allow-source-read',
                '--allow-source-write',
                '--allow-eval-arbitrary',
                '--allow-test-execution',
                '--allow-ide-read',
                '--allow-ide-write',
                '--allow-commit',
                '--allow-tracing',
            ]
            stderr_capture = io.StringIO()
            with patch.object(configuration_store, 'can_write_config', return_value=False):
                with patch('sys.stderr', stderr_capture):
                    result_config = configuration_store.merged_config_from_arguments(
                        arguments, argument_tokens=argument_tokens
                    )
            assert not result_config.allow_source_read
            assert not result_config.allow_source_write
            assert not result_config.allow_eval_arbitrary
            assert not result_config.allow_test_execution
            assert not result_config.allow_ide_read
            assert not result_config.allow_ide_write
            assert not result_config.allow_commit
            assert not result_config.allow_tracing
            warning_text = stderr_capture.getvalue()
            assert 'allow_source_read' in warning_text
            assert 'allow_source_write' in warning_text
            assert 'allow_eval_arbitrary' in warning_text
            assert 'allow_test_execution' in warning_text
            assert 'allow_ide_read' in warning_text
            assert 'allow_ide_write' in warning_text
            assert 'allow_commit' in warning_text
            assert 'allow_tracing' in warning_text


def test_cli_connectivity_overrides_still_apply_when_config_is_read_only():
    """AI: CLI host/port/path flags should still take effect even when the config file is read-only — only permission flags are blocked."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': temporary_directory}):
            configuration_store = McpConfigurationStore()
            persisted_config = McpRuntimeConfig(
                mcp_host='10.0.0.5',
                mcp_port=9177,
                mcp_http_path='/saved',
            )
            configuration_store.save(persisted_config)
            arguments = types.SimpleNamespace(
                allow_source_read=True,
                allow_source_write=False,
                allow_eval_arbitrary=False,
                allow_test_execution=False,
                allow_ide_read=True,
                allow_ide_write=False,
                allow_commit=False,
                allow_tracing=False,
                mcp_host='127.0.0.1',
                mcp_port=8123,
                mcp_http_path='/new-path',
            )
            argument_tokens = ['--mcp-host', '127.0.0.1', '--mcp-port', '8123', '--mcp-http-path', '/new-path']
            with patch.object(configuration_store, 'can_write_config', return_value=False):
                result_config = configuration_store.merged_config_from_arguments(
                    arguments, argument_tokens=argument_tokens
                )
            assert result_config.mcp_host == '127.0.0.1'
            assert result_config.mcp_port == 8123
            assert result_config.mcp_http_path == '/new-path'


def test_run_application_starts_headless_mcp_when_headless_flag_is_set():
    """AI: --headless-mcp should run only the MCP server and not construct the GUI."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(
            McpConfigurationStore, "merged_config_from_arguments"
        ) as merged:
            merged.return_value = McpRuntimeConfig()
            with patch.object(McpServerController, "run") as run_mcp:
                with patch("sys.argv", ["swordfish", "--headless-mcp"]):
                    Swordfish.run()
    init_swordfish.assert_not_called()
    run_mcp.assert_called_once()


def test_run_application_passes_streamable_http_configuration_to_mcp():
    """AI: headless mode should pass streamable-http host/port/path options into MCP startup arguments."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(
            McpConfigurationStore, "merged_config_from_arguments"
        ) as merged:
            merged.return_value = McpRuntimeConfig(
                mcp_host="127.0.0.1",
                mcp_port=9177,
                mcp_http_path="/running-ide",
            )
            with patch.object(McpServerController, "run") as run_mcp:
                with patch(
                    "sys.argv",
                    [
                        "swordfish",
                        "--headless-mcp",
                        "--transport",
                        "streamable-http",
                        "--mcp-host",
                        "127.0.0.1",
                        "--mcp-port",
                        "9177",
                        "--mcp-http-path",
                        "/running-ide",
                    ],
                ):
                    Swordfish.run()
    init_swordfish.assert_not_called()
    run_mcp.assert_called_once_with("streamable-http")


def test_run_application_supports_legacy_headless_mode_argument():
    """AI: Legacy --mode mcp-headless still maps to headless MCP startup."""
    with patch.object(Swordfish, "__init__", return_value=None) as init_swordfish:
        with patch.object(
            McpConfigurationStore, "merged_config_from_arguments"
        ) as merged:
            merged.return_value = McpRuntimeConfig()
            with patch.object(McpServerController, "run") as run_mcp:
                with patch("sys.argv", ["swordfish", "--mode", "mcp-headless"]):
                    Swordfish.run()
    init_swordfish.assert_not_called()
    run_mcp.assert_called_once()


def test_save_and_load_mcp_runtime_config_uses_xdg_home_location():
    """AI: Swordfish config should persist under XDG config home and round-trip all permission flags."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary_directory}):
            runtime_config = McpRuntimeConfig(
                allow_source_read=True,
                allow_eval_arbitrary=True,
                allow_source_write=True,
                allow_ide_read=True,
                allow_ide_write=True,
                allow_commit=True,
                allow_tracing=True,
                mcp_host="127.0.0.1",
                mcp_port=8123,
                mcp_http_path="/saved",
            )
            configuration_store = McpConfigurationStore()
            configuration_store.save(runtime_config)
            loaded_runtime_config = configuration_store.load()
            expected_config_path = os.path.join(
                temporary_directory,
                "swordfish",
                "swordfish.json",
            )
            assert configuration_store.config_file_path() == expected_config_path
            assert loaded_runtime_config is not None
            assert loaded_runtime_config.to_dict() == runtime_config.to_dict()


def test_save_mcp_runtime_config_preserves_permission_policy_source():
    """AI: Saving MCP runtime config should preserve the hand-edited Smalltalk permission policy."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary_directory}):
            configuration_store = McpConfigurationStore()
            config_file_path = configuration_store.config_file_path()
            os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
            with open(config_file_path, "w", encoding="utf-8") as config_file:
                config_file.write("""
{
  "schema_version": 2,
  "mcp_permission_policy": {
    "allow_session_permission_changes_condition_source": "System stoneName ~= 'prod'"
  },
  "mcp_runtime_config": {
    "allow_source_read": true
  }
}
""".strip() + "\n")

            configuration_store.save(
                McpRuntimeConfig(
                    allow_source_read=True,
                    allow_source_write=True,
                    mcp_host="127.0.0.1",
                    mcp_port=8123,
                    mcp_http_path="/saved",
                )
            )

            with open(config_file_path, "r", encoding="utf-8") as config_file:
                saved_payload = json.load(config_file)

            assert saved_payload["mcp_permission_policy"] == {
                "allow_session_permission_changes_condition_source": (
                    "System stoneName ~= 'prod'"
                )
            }


def test_load_login_gemstone_script_source_from_config():
    """AI: The Swordfish config should load a configured GemStone login script source verbatim."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary_directory}):
            configuration_store = McpConfigurationStore()
            config_file_path = configuration_store.config_file_path()
            os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
            with open(config_file_path, "w", encoding="utf-8") as config_file:
                config_file.write("""
{
  "login": {
    "gemstone_script_source": "System stoneName"
  },
  "schema_version": 2,
  "mcp_runtime_config": {
    "allow_source_read": true
  }
}
""".strip() + "\n")

            assert configuration_store.load_login_gemstone_script_source() == (
                "System stoneName"
            )


def test_save_mcp_runtime_config_preserves_login_gemstone_script_source():
    """AI: Saving MCP runtime config should preserve a hand-edited GemStone login script from config."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": temporary_directory}):
            configuration_store = McpConfigurationStore()
            config_file_path = configuration_store.config_file_path()
            os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
            with open(config_file_path, "w", encoding="utf-8") as config_file:
                config_file.write("""
{
  "login": {
    "gemstone_script_source": "System stoneName"
  },
  "schema_version": 2,
  "mcp_runtime_config": {
    "allow_source_read": true
  }
}
""".strip() + "\n")

            configuration_store.save(
                McpRuntimeConfig(
                    allow_source_read=True,
                    allow_source_write=True,
                    mcp_host="127.0.0.1",
                    mcp_port=8123,
                    mcp_http_path="/saved",
                )
            )

            with open(config_file_path, "r", encoding="utf-8") as config_file:
                saved_payload = json.load(config_file)

            assert saved_payload["login"] == {
                "gemstone_script_source": "System stoneName"
            }


@with_fixtures(SwordfishAppFixture)
def test_read_only_config_in_prod_locks_permission_toggles(fixture):
    """AI: A read-only config should lock all permission toggles when the connected database is treated as production."""
    fixture.app.mcp_permission_policy = McpPermissionPolicy(
        allow_session_permission_changes_condition_source="System stoneName = 'prod'"
    )
    fixture.session_record.run_code = Mock(
        return_value=types.SimpleNamespace(to_py=False)
    )
    with patch.object(
        fixture.app.mcp_server_controller.configuration_store,
        "can_write_config",
        return_value=False,
    ):
        fixture.simulate_login()
        with patch.object(McpConfigurationDialog, "wait_visibility"):
            with patch.object(McpConfigurationDialog, "grab_set"):
                dialog = McpConfigurationDialog(
                    fixture.app,
                    fixture.app.mcp_runtime_config,
                    fixture.app.mcp_configuration_access(),
                )
                fixture.app.update()
    try:
        assert str(dialog.allow_source_read_checkbutton.cget("state")) == tk.DISABLED
        assert str(dialog.allow_source_write_checkbutton.cget("state")) == tk.DISABLED
        assert str(dialog.allow_eval_arbitrary_checkbutton.cget("state")) == tk.DISABLED
        assert str(dialog.allow_test_execution_checkbutton.cget("state")) == tk.DISABLED
        assert str(dialog.allow_ide_read_checkbutton.cget("state")) == tk.DISABLED
        assert str(dialog.allow_ide_write_checkbutton.cget("state")) == tk.DISABLED
        assert str(dialog.allow_commit_checkbutton.cget("state")) == tk.DISABLED
        assert str(dialog.allow_tracing_checkbutton.cget("state")) == tk.DISABLED
        assert "locked" in dialog.permission_note_variable.get().lower()
    finally:
        dialog.destroy()
        fixture.app.update()


@with_fixtures(SwordfishAppFixture)
def test_read_only_config_non_prod_allows_session_only_permission_changes(
    fixture,
):
    """AI: A read-only config should allow permission changes only for the current session when the connected database is not production."""
    fixture.app.mcp_permission_policy = McpPermissionPolicy(
        allow_session_permission_changes_condition_source="System stoneName ~= 'prod'"
    )
    fixture.session_record.run_code = Mock(
        return_value=types.SimpleNamespace(to_py=True)
    )
    updated_runtime_config = McpRuntimeConfig(
        allow_source_read=True,
        allow_eval_arbitrary=True,
        allow_source_write=True,
        allow_ide_read=True,
        allow_ide_write=True,
        allow_commit=True,
        allow_tracing=True,
        mcp_host="127.0.0.1",
        mcp_port=9177,
        mcp_http_path="/updated",
    )
    with patch.object(
        fixture.app.mcp_server_controller.configuration_store,
        "can_write_config",
        return_value=False,
    ):
        fixture.simulate_login()
        with patch.object(McpConfigurationDialog, "wait_visibility"):
            with patch.object(McpConfigurationDialog, "grab_set"):
                dialog = McpConfigurationDialog(
                    fixture.app,
                    fixture.app.mcp_runtime_config,
                    fixture.app.mcp_configuration_access(),
                )
                fixture.app.update()
                assert (
                    str(dialog.allow_eval_arbitrary_checkbutton.cget("state"))
                    == tk.NORMAL
                )
                assert "session" in dialog.permission_note_variable.get().lower()
                dialog.destroy()
                fixture.app.update()

        fake_dialog = types.SimpleNamespace(result=updated_runtime_config)
        with patch(
            "reahl.swordfish.main.McpConfigurationDialog", return_value=fake_dialog
        ):
            with patch.object(fixture.app, "wait_window") as wait_window:
                with patch.object(
                    fixture.app.mcp_server_controller,
                    "save_configuration",
                ) as save_configuration:
                    fixture.app.configure_mcp_server_from_menu()

    wait_window.assert_called_once_with(fake_dialog)
    save_configuration.assert_not_called()
    assert fixture.app.mcp_runtime_config.to_dict() == updated_runtime_config.to_dict()
    assert (
        fixture.app.base_mcp_runtime_config.to_dict()
        != updated_runtime_config.to_dict()
    )


@with_fixtures(SwordfishAppFixture)
def test_logout_resets_session_only_mcp_configuration(fixture):
    """AI: Session-only MCP configuration changes should be cleared on logout."""
    fixture.app.mcp_permission_policy = McpPermissionPolicy(
        allow_session_permission_changes_condition_source="System stoneName ~= 'prod'"
    )
    fixture.session_record.run_code = Mock(
        return_value=types.SimpleNamespace(to_py=True)
    )
    updated_runtime_config = McpRuntimeConfig(
        allow_source_read=True,
        allow_eval_arbitrary=True,
        allow_source_write=True,
        allow_ide_read=True,
        allow_ide_write=True,
        allow_commit=True,
        allow_tracing=True,
        mcp_host="127.0.0.1",
        mcp_port=9177,
        mcp_http_path="/updated",
    )
    base_runtime_config = fixture.app.mcp_runtime_config.copy()
    with patch.object(
        fixture.app.mcp_server_controller.configuration_store,
        "can_write_config",
        return_value=False,
    ):
        fixture.simulate_login()
        fake_dialog = types.SimpleNamespace(result=updated_runtime_config)
        with patch(
            "reahl.swordfish.main.McpConfigurationDialog", return_value=fake_dialog
        ):
            with patch.object(fixture.app, "wait_window"):
                fixture.app.configure_mcp_server_from_menu()
        with patch.object(
            fixture.app.mcp_server_controller,
            "stop_for_session_reset",
        ) as stop_for_session_reset:
            fixture.app.logout()

    stop_for_session_reset.assert_not_called()
    assert fixture.app.mcp_runtime_config.to_dict() == base_runtime_config.to_dict()


@with_fixtures(SwordfishAppFixture)
def test_logout_stops_mcp_when_session_only_config_is_active(fixture):
    """AI: Logout should stop embedded MCP before clearing a session-only configuration that was never persisted."""
    fixture.app.mcp_permission_policy = McpPermissionPolicy(
        allow_session_permission_changes_condition_source="System stoneName ~= 'prod'"
    )
    fixture.session_record.run_code = Mock(
        return_value=types.SimpleNamespace(to_py=True)
    )
    updated_runtime_config = McpRuntimeConfig(
        allow_source_read=True,
        allow_eval_arbitrary=True,
        allow_source_write=True,
        allow_ide_read=True,
        allow_ide_write=True,
        allow_commit=True,
        allow_tracing=True,
        mcp_host="127.0.0.1",
        mcp_port=9177,
        mcp_http_path="/updated",
    )
    with patch.object(
        fixture.app.mcp_server_controller.configuration_store,
        "can_write_config",
        return_value=False,
    ):
        fixture.simulate_login()
        fake_dialog = types.SimpleNamespace(result=updated_runtime_config)
        with patch(
            "reahl.swordfish.main.McpConfigurationDialog", return_value=fake_dialog
        ):
            with patch.object(fixture.app, "wait_window"):
                fixture.app.configure_mcp_server_from_menu()
        with patch.object(
            fixture.app.mcp_server_controller,
            "stop_for_session_reset",
        ) as stop_for_session_reset:
            with fixture.app.mcp_server_controller.lock:
                fixture.app.mcp_server_controller.running = True
            fixture.app.logout()

    stop_for_session_reset.assert_called_once()


def test_run_mcp_server_passes_streamable_http_options_to_create_server():
    """AI: MCP startup should forward host/port/path options to create_server and run with the requested transport."""
    arguments = types.SimpleNamespace(
        allow_source_read=True,
        allow_eval_arbitrary=False,
        allow_source_write=True,
        allow_test_execution=False,
        allow_ide_read=True,
        allow_ide_write=False,
        allow_commit=False,
        allow_tracing=True,
        mcp_host='127.0.0.1',
        mcp_port=9177,
        mcp_http_path='/running-ide',
        transport='streamable-http',
    )
    configuration_store = McpConfigurationStore()
    runtime_config = configuration_store.config_from_arguments(arguments)
    mcp_server_controller = McpServerController(None, runtime_config)
    with patch('reahl.swordfish.main.create_server') as create_server:
        mock_server = Mock()
        create_server.return_value = mock_server
        mcp_server_controller.run(arguments.transport)
    _, call_kwargs = create_server.call_args
    assert callable(call_kwargs['get_permissions'])
    assert call_kwargs['get_permissions']() == {
        'allow_source_read': True,
        'allow_source_write': True,
        'allow_eval_arbitrary': False,
        'allow_test_execution': False,
        'allow_ide_read': True,
        'allow_ide_write': False,
        'allow_commit': False,
        'allow_tracing': True,
    }
    assert call_kwargs['mcp_host'] == '127.0.0.1'
    assert call_kwargs['mcp_port'] == 9177
    assert call_kwargs['mcp_streamable_http_path'] == '/running-ide'
    assert call_kwargs['integrated_session_state'] is None
    mock_server.run.assert_called_once_with(transport='streamable-http')


@with_fixtures(SwordfishAppFixture)
def test_configure_mcp_server_updates_and_saves_config_without_forcing_restart(
    fixture,
):
    """AI: MCP config dialog apply should persist settings; permission changes apply immediately, network changes require restart."""
    fixture.simulate_login()
    updated_runtime_config = McpRuntimeConfig(
        allow_source_read=True,
        allow_eval_arbitrary=True,
        allow_source_write=True,
        allow_ide_read=True,
        allow_ide_write=True,
        allow_commit=True,
        allow_tracing=True,
        mcp_host="127.0.0.1",
        mcp_port=9177,
        mcp_http_path="/updated",
    )
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.applied_runtime_config = (
            fixture.app.mcp_runtime_config.copy()
        )
    fake_dialog = types.SimpleNamespace(result=updated_runtime_config)

    with patch("reahl.swordfish.main.McpConfigurationDialog", return_value=fake_dialog):
        with patch.object(fixture.app, "wait_window") as wait_window:
            with patch.object(
                fixture.app.mcp_server_controller,
                "stop",
            ) as stop_server:
                with patch.object(fixture.app, "start_mcp_server") as start_server:
                    with patch(
                        "reahl.swordfish.main.McpServerController.save_configuration"
                    ) as save_configuration:
                        fixture.app.configure_mcp_server_from_menu()

    wait_window.assert_called_once_with(fake_dialog)
    stop_server.assert_not_called()
    start_server.assert_not_called()
    save_configuration.assert_called_once()
    assert fixture.app.mcp_runtime_config.to_dict() == updated_runtime_config.to_dict()
    assert fixture.app.embedded_mcp_server_status()["restart_required_for_config"]


@with_fixtures(SwordfishAppFixture)
def test_collaboration_status_mentions_restart_when_running_config_is_outdated(
    fixture,
):
    """AI: Collaboration status should tell the user to restart MCP when config changed while MCP is running."""
    fixture.simulate_login()
    configured_runtime_config = McpRuntimeConfig(
        mcp_host="127.0.0.1",
        mcp_port=9100,
        mcp_http_path="/configured",
    )
    active_runtime_config = McpRuntimeConfig(
        mcp_host="127.0.0.1",
        mcp_port=8000,
        mcp_http_path="/mcp",
    )
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.starting = False
        fixture.app.mcp_server_controller.stopping = False
        fixture.app.mcp_server_controller.runtime_config = configured_runtime_config
        fixture.app.mcp_server_controller.applied_runtime_config = active_runtime_config

    fixture.app.refresh_collaboration_status()
    fixture.app.update()

    assert "Network settings changed; they will take effect at next MCP start." in (
        fixture.app.collaboration_status_text.get()
    )


@with_fixtures(SwordfishAppFixture)
def test_failed_login_shows_error_label(fixture):
    """If login credentials are rejected, the login frame stays visible and
    shows a red error label describing the failure instead of the browser."""
    with patch.object(
        GemstoneSessionRecord,
        "log_in_linked",
        side_effect=DomainException("Bad credentials"),
    ):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    assert not fixture.app.is_logged_in
    assert fixture.app.login_frame.error_label is not None
    assert "Bad credentials" in fixture.app.login_frame.error_label.cget("text")


@with_fixtures(SwordfishAppFixture)
def test_logout_returns_to_login_screen(fixture):
    """After a successful login, calling logout clears the browser interface
    and returns the user to the login screen."""
    fixture.simulate_login()

    fixture.app.logout()
    fixture.app.update()

    assert not fixture.app.is_logged_in
    assert fixture.app.login_frame is not None
    assert fixture.app.login_frame.winfo_exists()


@with_fixtures(SwordfishAppFixture)
def test_login_layout_is_consistent_before_and_after_logout(fixture):
    """AI: The login form layout should stay compact and anchored after returning from the main app."""
    initial_login_frame = fixture.app.login_frame
    assert int(initial_login_frame.grid_rowconfigure(0)["weight"]) == 1
    assert int(initial_login_frame.grid_rowconfigure(1)["weight"]) == 0
    assert initial_login_frame.form_frame.grid_info()["sticky"] == "n"
    assert int(initial_login_frame.form_frame.grid_columnconfigure(1)["weight"]) == 1

    fixture.simulate_login()
    fixture.app.logout()
    fixture.app.update()

    returned_login_frame = fixture.app.login_frame
    assert int(returned_login_frame.grid_rowconfigure(0)["weight"]) == 1
    assert int(returned_login_frame.grid_rowconfigure(1)["weight"]) == 0
    assert returned_login_frame.form_frame.grid_info()["sticky"] == "n"
    assert int(returned_login_frame.form_frame.grid_columnconfigure(1)["weight"]) == 1


@with_fixtures(SwordfishAppFixture)
def test_commit_sends_commit_to_gemstone(fixture):
    """Committing via the app delegates to the underlying GemStone session,
    persisting any pending changes in the repository."""
    fixture.simulate_login()

    fixture.app.commit()

    fixture.mock_gemstone_session.commit.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_abort_sends_abort_to_gemstone(fixture):
    """Aborting via the app delegates to the underlying GemStone session,
    discarding any uncommitted changes in the repository."""
    fixture.simulate_login()

    fixture.app.abort()

    fixture.mock_gemstone_session.abort.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_mcp_busy_state_publishes_events_for_listeners(fixture):
    """AI: MCP busy/idle transitions are published as events so subscribers can update UI behavior."""
    fixture.simulate_login()

    class BusyListener:
        def __init__(self):
            self.events = []

        def on_busy_state_changed(
            self,
            is_busy=False,
            operation_name="",
            busy_lease_token=None,
        ):
            self.events.append((is_busy, operation_name))

    listener = BusyListener()
    fixture.app.event_queue.subscribe(
        "McpBusyStateChanged",
        listener.on_busy_state_changed,
    )

    fixture.app.last_mcp_busy_state = fixture.app.integrated_session_state.is_mcp_busy()
    fixture.app.integrated_session_state.begin_mcp_operation("gs_eval")
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert listener.events[-1] == (True, "gs_eval")

    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert listener.events[-1] == (False, "")


@with_fixtures(SwordfishAppFixture)
def test_mcp_busy_state_disables_run_and_session_controls(fixture):
    """AI: When MCP is busy, Run and Session controls are visually disabled and re-enabled when idle."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()

    fixture.app.integrated_session_state.begin_mcp_operation("gs_apply_rename_method")
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert str(fixture.app.run_tab.run_button.cget("state")) == tk.DISABLED
    assert str(fixture.app.run_tab.debug_button.cget("state")) == tk.DISABLED
    assert fixture.app.run_tab.source_text.cget("state") == tk.DISABLED
    assert fixture.app.menu_bar.session_menu.entrycget(0, "state") == tk.DISABLED

    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.synchronise_collaboration_state()
    fixture.app.update()

    assert str(fixture.app.run_tab.run_button.cget("state")) == tk.NORMAL
    assert str(fixture.app.run_tab.debug_button.cget("state")) == tk.NORMAL
    assert fixture.app.run_tab.source_text.cget("state") == tk.NORMAL
    assert fixture.app.menu_bar.session_menu.entrycget(0, "state") == tk.NORMAL


@with_fixtures(SwordfishAppFixture)
def test_close_run_tab_drops_stale_mcp_busy_callback(fixture):
    """AI: Closing Run tab invalidates callback context so queued busy callbacks cannot touch destroyed widgets."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    fixture.app.publish_mcp_busy_state_event(
        is_busy=True,
        operation_name='gs_eval',
    )
    run_tab.close_tab()

    with expected(NoException):
        fixture.app.update()

    assert fixture.app.run_tab is None


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_contains_only_start_stop_and_config_commands(fixture):
    """AI: The MCP menu is just MCP runtime control - FileTree concerns live on their own
    menu, so they must not leak onto the MCP menu."""
    fixture.simulate_login()
    mcp_menu = fixture.app.menu_bar.mcp_menu
    labels = menu_command_labels(mcp_menu)
    assert labels == ["Start MCP", "Stop MCP", "Configure MCP"]
    assert mcp_menu.entrycget(0, "state") == tk.NORMAL
    assert mcp_menu.entrycget(1, "state") == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_filetree_menu_holds_sync_config_and_filing_commands(fixture):
    """AI: The FileTree menu carries everything about the on-disk repository: the live-mirror
    configuration plus the explicit whole-repository file-in and category-selecting file-out."""
    fixture.simulate_login()
    labels = menu_command_labels(fixture.app.menu_bar.filetree_menu)
    assert "Set FileTree Sync Folder..." in labels
    assert "Disable FileTree Sync" in labels
    assert "File in Everything (overwrite from disk)..." in labels
    assert "File out Class Categories..." in labels


@with_fixtures(SwordfishAppFixture)
def test_debug_menu_contains_breakpoints_command_when_logged_in(fixture):
    """AI: Debug menu should expose a Breakpoints dialog action after login."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()

    debug_menu_labels = menu_command_labels(fixture.app.menu_bar.debug_menu)
    assert "Breakpoints" in debug_menu_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_menu_renames_run_action_to_workspace(fixture):
    """AI: The Debug menu surfaces the run-tab action under the Workspace label."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()

    debug_menu_labels = menu_command_labels(fixture.app.menu_bar.debug_menu)
    assert "Workspace" in debug_menu_labels
    assert "Run" not in debug_menu_labels


@with_fixtures(SwordfishAppFixture)
def test_find_menu_contains_find_implementors_senders_and_references_shortcuts(
    fixture,
):
    """AI: Find menu should gather every search entry point in one place: Find, Implementors, Senders, References."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()

    find_menu_labels = menu_command_labels(fixture.app.menu_bar.find_menu)
    assert "Find" in find_menu_labels
    assert "Implementors" in find_menu_labels
    assert "Senders" in find_menu_labels
    assert "References" in find_menu_labels
    assert find_menu_labels.index("Find") < find_menu_labels.index("Implementors")
    assert find_menu_labels.index("Implementors") < find_menu_labels.index("Senders")
    assert find_menu_labels.index("Senders") < find_menu_labels.index("References")


@with_fixtures(SwordfishAppFixture)
def test_code_menu_offers_opening_the_browser(fixture):
    """AI: The Code menu can deliberately (re)open a Browser tab, listed ahead
    of the Workspace so the primary navigation tool leads the menu."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()

    code_menu_labels = menu_command_labels(fixture.app.menu_bar.debug_menu)
    assert "Browser" in code_menu_labels
    assert code_menu_labels.index("Browser") < code_menu_labels.index("Workspace")


@with_fixtures(SwordfishAppFixture)
def test_uml_menu_holds_the_class_and_object_diagrams(fixture):
    """AI: A dedicated UML menu gathers the two diagram tools -- class diagram
    and object diagram -- as deliberately openable canvases, separate from the
    contextual inspector/debugger which need a subject."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()

    uml_menu_labels = menu_command_labels(fixture.app.menu_bar.uml_menu)
    assert uml_menu_labels == ["Class Diagram", "Object Diagram"]


@with_fixtures(SwordfishAppFixture)
def test_uml_object_diagram_opens_an_empty_canvas(fixture):
    """AI: Opening the object diagram from the menu needs no subject object --
    ensure_object_diagram_tab brings up a blank canvas you add objects to,
    mirroring ensure_class_diagram_tab."""
    fixture.simulate_login()

    fixture.app.ensure_object_diagram_tab()

    assert fixture.app.object_diagram_tab is not None
    assert fixture.app.object_diagram_tab.winfo_exists()


@with_fixtures(SwordfishAppFixture)
def test_opening_the_browser_when_already_open_focuses_it_without_replacing(fixture):
    """AI: Re-opening the Browser (e.g. from the Code menu) must keep the
    existing browser tab and its state -- it just comes to the front, rather
    than being destroyed and rebuilt under the user."""
    fixture.simulate_login()
    existing_browser = fixture.app.browser_tab
    assert existing_browser is not None

    fixture.app.add_browser_tab()

    assert fixture.app.browser_tab is existing_browser
    assert str(fixture.app.notebook.select()) == str(existing_browser)


@with_fixtures(SwordfishAppFixture)
def test_auxiliary_tools_open_in_the_right_notebook(fixture):
    """AI: The diagrams (and, by the same path, inspector/debugger) are
    auxiliary views -- they open in the right-hand notebook (the split group
    where Find opens), not in the primary left group."""
    fixture.simulate_login()

    fixture.app.ensure_class_diagram_tab()
    fixture.app.ensure_object_diagram_tab()

    right = fixture.app.pane_area.group(1)
    assert str(fixture.app.class_diagram_tab.master) == str(right)
    assert str(fixture.app.object_diagram_tab.master) == str(right)


@with_fixtures(SwordfishAppFixture)
def test_browser_and_workspace_stay_in_the_left_notebook(fixture):
    """AI: Browser and Workspace are the primary working surface and stay in the
    left group -- they are not pushed to the auxiliary right notebook."""
    fixture.simulate_login()
    fixture.app.open_run_tab()

    left = fixture.app.pane_area.group(0)
    assert str(fixture.app.browser_tab.master) == str(left)
    assert str(fixture.app.run_tab.master) == str(left)


@with_fixtures(SwordfishAppFixture)
def test_find_and_tools_share_one_right_notebook(fixture):
    """AI: Find and the auxiliary tools open into the SAME right-hand group --
    opening a diagram and then Find does not stack up extra split groups."""
    fixture.simulate_login()

    fixture.app.ensure_class_diagram_tab()
    fixture.app.open_find_dialog()

    assert len(fixture.app.pane_area.groups) == 2
    right = fixture.app.pane_area.group(1)
    assert str(fixture.app.class_diagram_tab.master) == str(right)


@with_fixtures(SwordfishAppFixture)
def test_method_selected_event_is_retired(fixture):
    """AI: The legacy MethodSelected event is retired -- method display now flows
    through MethodDisplayRequested and list refresh through MethodsChanged, so
    nothing subscribes to MethodSelected anymore."""
    fixture.simulate_login()

    assert 'MethodSelected' not in fixture.app.event_queue.events


@with_fixtures(SwordfishAppFixture)
def test_session_menu_owns_exit_and_leads_the_menubar_with_a_code_menu(fixture):
    """AI: Exit now lives on the Session menu (the File menu, which held nothing
    else, is gone), Session leads the menubar, and the former Debug menu is Code."""
    fixture.simulate_login()
    fixture.app.menu_bar.update_menus()
    menu_bar = fixture.app.menu_bar

    assert "Exit" in menu_command_labels(menu_bar.session_menu)

    cascade_labels = []
    entry_count = int(menu_bar.index("end")) + 1
    for entry_index in range(entry_count):
        if menu_bar.type(entry_index) == "cascade":
            cascade_labels.append(menu_bar.entrycget(entry_index, "label"))

    assert cascade_labels[0] == "Session"
    assert "Code" in cascade_labels
    assert "File" not in cascade_labels
    assert "Debug" not in cascade_labels


@with_fixtures(SwordfishAppFixture)
def test_find_menu_find_implementors_command_delegates_to_swordfish_handler(
    fixture,
):
    """AI: Find menu Implementors action should delegate to Swordfish find-implementors handler."""
    fixture.simulate_login()
    find_menu = fixture.app.menu_bar.find_menu
    with patch.object(fixture.app, "open_implementors_dialog") as open_dialog:
        invoke_menu_command_by_label(find_menu, "Implementors")
    open_dialog.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_find_menu_find_senders_command_delegates_to_swordfish_handler(
    fixture,
):
    """AI: Find menu Senders action should delegate to Swordfish find-senders handler."""
    fixture.simulate_login()
    find_menu = fixture.app.menu_bar.find_menu
    with patch.object(fixture.app, "open_senders_dialog") as open_dialog:
        invoke_menu_command_by_label(find_menu, "Senders")
    open_dialog.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_find_menu_references_command_delegates_to_swordfish_handler(
    fixture,
):
    """AI: Find menu References action should delegate to Swordfish find-references handler."""
    fixture.simulate_login()
    find_menu = fixture.app.menu_bar.find_menu
    with patch.object(fixture.app, "open_references_dialog") as open_dialog:
        invoke_menu_command_by_label(find_menu, "References")
    open_dialog.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_open_references_dialog_configures_find_dialog_for_exact_class_references(
    fixture,
):
    """AI: Opening references dialog should configure Find for exact class reference lookup."""
    with patch.object(fixture.app, "open_find_dialog") as open_find_dialog:
        fixture.app.open_references_dialog(class_name="OrderLine")
    open_find_dialog.assert_called_once_with(
        search_type="reference",
        search_query="OrderLine",
        run_search=True,
        match_mode="exact",
        reference_target="class",
    )


@with_fixtures(SwordfishAppFixture)
def test_open_implementors_dialog_configures_find_dialog_for_exact_method_search(
    fixture,
):
    """AI: Opening implementors dialog should configure Find for exact method implementors lookup."""
    with patch.object(fixture.app, "open_find_dialog") as open_find_dialog:
        fixture.app.open_implementors_dialog(method_symbol="total")
    open_find_dialog.assert_called_once_with(
        search_type="method",
        search_query="total",
        run_search=True,
        match_mode="exact",
    )


@with_fixtures(SwordfishAppFixture)
def test_open_senders_dialog_configures_find_dialog_for_exact_method_references(
    fixture,
):
    """AI: Opening senders dialog should configure Find for exact method reference lookup."""
    with patch.object(fixture.app, "open_find_dialog") as open_find_dialog:
        fixture.app.open_senders_dialog(method_symbol="total")
    open_find_dialog.assert_called_once_with(
        search_type="reference",
        search_query="total",
        run_search=True,
        match_mode="exact",
        reference_target="method",
        sender_source_class_name=None,
    )


@with_fixtures(SwordfishAppFixture)
def test_debug_menu_breakpoints_command_delegates_to_swordfish_handler(
    fixture,
):
    """AI: Debug menu Breakpoints action should delegate to Swordfish dialog handler."""
    fixture.simulate_login()
    debug_menu = fixture.app.menu_bar.debug_menu
    with patch.object(fixture.app, "open_breakpoints_dialog") as open_dialog:
        invoke_menu_command_by_label(debug_menu, "Breakpoints")
    open_dialog.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_debug_menu_workspace_command_opens_run_tab(
    fixture,
):
    """AI: Debug menu Workspace action should still open the run tab it was renamed from."""
    fixture.simulate_login()
    debug_menu = fixture.app.menu_bar.debug_menu
    with patch.object(fixture.app, "open_run_tab") as open_run_tab:
        invoke_menu_command_by_label(debug_menu, "Workspace")
    open_run_tab.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_open_breakpoints_dialog_lists_active_breakpoints(fixture):
    """AI: Opening Breakpoints lists the active breakpoints in a pane that opens
    in the right-hand notebook (beside Find), not a modal popup."""
    fixture.simulate_login()
    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )

    breakpoints_pane = fixture.app.open_breakpoints_dialog()
    fixture.app.update()

    assert breakpoints_pane is fixture.app.active_breakpoints_pane()
    assert str(breakpoints_pane.master) == str(fixture.app.pane_area.group(1))
    pane_rows = breakpoints_pane.breakpoint_list.get_children()
    assert len(pane_rows) == 1
    row_values = breakpoints_pane.breakpoint_list.item(pane_rows[0], "values")
    assert row_values[0] == "OrderLine"
    assert row_values[1] == "instance"
    assert row_values[2] == "total"


@with_fixtures(SwordfishAppFixture)
def test_breakpoints_double_click_pins_the_method(fixture):
    """AI: Double-clicking a breakpoint pins its method in the editor -- preview,
    then promote the tab to permanent, like the Find pane -- without moving the
    browser's column selection."""
    fixture.simulate_login()
    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )
    breakpoints_pane = fixture.app.open_breakpoints_dialog()
    fixture.app.update()

    shown = Mock()
    pinned = Mock()
    fixture.app.event_queue.subscribe('MethodDisplayRequested', shown)
    fixture.app.event_queue.subscribe('MethodTabPinRequested', pinned)
    selection_before = fixture.session_record.selected_class

    breakpoints_pane.breakpoint_list.selection_set("bp-1")
    breakpoints_pane.pin_selected_breakpoint(None)
    fixture.app.update()

    shown.assert_called_once_with(("OrderLine", True, "total"), origin=ANY)
    pinned.assert_called_once_with(("OrderLine", True, "total"), origin=ANY)
    assert fixture.session_record.selected_class == selection_before


@with_fixtures(SwordfishAppFixture)
def test_breakpoints_single_click_peeks_the_method(fixture):
    """AI: Single-clicking a breakpoint previews its method in the editor via
    MethodDisplayRequested, without pinning and without moving the browser."""
    fixture.simulate_login()
    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )
    breakpoints_pane = fixture.app.open_breakpoints_dialog()
    fixture.app.update()

    shown = Mock()
    pinned = Mock()
    fixture.app.event_queue.subscribe('MethodDisplayRequested', shown)
    fixture.app.event_queue.subscribe('MethodTabPinRequested', pinned)
    selection_before = fixture.session_record.selected_class

    breakpoints_pane.breakpoint_list.selection_set("bp-1")
    breakpoints_pane.peek_selected_breakpoint(None)
    fixture.app.update()

    shown.assert_called_once_with(("OrderLine", True, "total"), origin=ANY)
    pinned.assert_not_called()
    assert fixture.session_record.selected_class == selection_before


@with_fixtures(SwordfishAppFixture)
def test_breakpoints_pane_refreshes_when_a_breakpoint_is_set(fixture):
    """AI: An open breakpoints pane listens for breakpoint changes -- placing a
    breakpoint elsewhere (the BreakpointSet event) re-lists the active
    breakpoints in place, without reopening the pane."""
    fixture.simulate_login()
    fixture.session_record.list_breakpoints = Mock(return_value=[])
    breakpoints_pane = fixture.app.open_breakpoints_dialog()
    fixture.app.update()
    assert len(breakpoints_pane.breakpoint_list.get_children()) == 0

    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )
    fixture.app.event_queue.publish('BreakpointSet')
    fixture.app.update()

    assert len(breakpoints_pane.breakpoint_list.get_children()) == 1


@with_fixtures(SwordfishAppFixture)
def test_breakpoints_pane_refreshes_on_breakpoints_changed(fixture):
    """AI: The breakpoints pane refreshes on the generic BreakpointsChanged event
    -- the one the MCP model-refresh bridge publishes for its 'breakpoints' kind
    -- so a breakpoint set via the MCP shows up in the IDE pane."""
    fixture.simulate_login()
    fixture.session_record.list_breakpoints = Mock(return_value=[])
    breakpoints_pane = fixture.app.open_breakpoints_dialog()
    fixture.app.update()
    assert len(breakpoints_pane.breakpoint_list.get_children()) == 0

    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )
    fixture.app.event_queue.publish('BreakpointsChanged')
    fixture.app.update()

    assert len(breakpoints_pane.breakpoint_list.get_children()) == 1


@with_fixtures(SwordfishAppFixture)
def test_breakpoints_pane_refreshes_when_a_method_is_recompiled(fixture):
    """AI: Recompiling a method re-applies its breakpoint onto the new CompiledMethod,
    remapping its offset/step point. The pane re-reads on the method-change event (published
    by both editor saves and MCP compiles) so its Offset/Step Point columns track the edit
    rather than showing pre-edit values for a breakpoint that is in fact still effective."""
    fixture.simulate_login()
    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 42,
                "step_point": 3,
            }
        ]
    )
    breakpoints_pane = fixture.app.open_breakpoints_dialog()
    fixture.app.update()
    original_values = breakpoints_pane.breakpoint_list.item(
        breakpoints_pane.breakpoint_list.get_children()[0], "values"
    )
    assert original_values[3] == "42"

    # AI: The recompile re-applied the breakpoint at a shifted offset / step point.
    fixture.session_record.list_breakpoints = Mock(
        return_value=[
            {
                "breakpoint_id": "bp-1",
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "total",
                "source_offset": 58,
                "step_point": 4,
            }
        ]
    )
    fixture.app.event_queue.publish("MethodsChanged")
    fixture.app.update()

    refreshed_values = breakpoints_pane.breakpoint_list.item(
        breakpoints_pane.breakpoint_list.get_children()[0], "values"
    )
    assert refreshed_values[3] == "58"
    assert refreshed_values[4] == "4"


@with_fixtures(SwordfishAppFixture)
def test_breakpoints_model_change_kind_publishes_breakpoints_changed(fixture):
    """AI: The 'breakpoints' model-change kind (requested by the MCP breakpoint
    tools through the refresh bridge) publishes BreakpointsChanged, so the IDE's
    breakpoint views refresh."""
    fixture.simulate_login()
    changed = Mock()
    fixture.app.event_queue.subscribe('BreakpointsChanged', changed)

    fixture.app.publish_model_change_events('breakpoints')
    fixture.app.update()

    changed.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_refresh_from_image_re_reads_structural_and_breakpoint_views(fixture):
    """AI: The manual Refresh re-reads everything detectable -- structural views
    (classes/methods) and breakpoints -- immediately, for image changes the IDE
    cannot detect on its own (another client, debugger/sync state, MCP tools off
    the model-write allowlist)."""
    fixture.simulate_login()
    classes_changed = Mock()
    methods_changed = Mock()
    breakpoints_changed = Mock()
    fixture.app.event_queue.subscribe('ClassesChanged', classes_changed)
    fixture.app.event_queue.subscribe('MethodsChanged', methods_changed)
    fixture.app.event_queue.subscribe('BreakpointsChanged', breakpoints_changed)

    fixture.app.refresh_from_image()
    fixture.app.update()

    classes_changed.assert_called()
    methods_changed.assert_called()
    breakpoints_changed.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_status_bar_refresh_button_triggers_full_re_read(fixture):
    """AI: The status-bar refresh button -- a small icon button at the bottom right, shown as a
    glyph rather than a word -- forces a full re-read on click."""
    fixture.simulate_login()
    methods_changed = Mock()
    breakpoints_changed = Mock()
    fixture.app.event_queue.subscribe('MethodsChanged', methods_changed)
    fixture.app.event_queue.subscribe('BreakpointsChanged', breakpoints_changed)

    fixture.app.status_refresh_button.invoke()
    fixture.app.update()

    methods_changed.assert_called()
    breakpoints_changed.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_status_bar_icon_buttons_have_hover_tooltips(fixture):
    """AI: The status-bar icon buttons are glyphs, so they carry hover tooltips to stay
    discoverable -- the binding that drives the tooltip is present on each."""
    fixture.simulate_login()
    assert fixture.app.status_refresh_button.bind('<Enter>')
    assert fixture.app.status_stop_button.bind('<Enter>')


@with_fixtures(SwordfishAppFixture)
def test_status_bar_stop_button_is_disabled_while_the_session_is_idle(fixture):
    """AI: With nothing running on the shared session there is nothing to interrupt, so the
    single Stop control offers no false affordance -- it sits disabled."""
    fixture.simulate_login()
    assert str(fixture.app.status_stop_button.cget('state')) == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_status_bar_stop_button_enables_while_an_activity_holds_the_session(fixture):
    """AI: The one Stop control tracks the single session-activity slot: pressable exactly
    while an activity runs, disabled again the moment it ends."""
    fixture.simulate_login()
    activity = types.SimpleNamespace(request_stop=Mock(), message='Searching...')

    fixture.app.set_current_session_activity(activity)
    fixture.app.update()
    assert str(fixture.app.status_stop_button.cget('state')) == tk.NORMAL

    fixture.app.set_current_session_activity(None)
    fixture.app.update()
    assert str(fixture.app.status_stop_button.cget('state')) == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_pressing_status_bar_stop_interrupts_the_current_activity(fixture):
    """AI: One Stop gesture delegates to whatever holds the session, asking it to stop. The
    button knows nothing of Find versus MCP -- only the shared activity protocol."""
    fixture.simulate_login()
    activity = types.SimpleNamespace(request_stop=Mock(), message='Searching...')
    fixture.app.set_current_session_activity(activity)
    fixture.app.update()

    fixture.app.status_stop_button.invoke()

    activity.request_stop.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_a_running_mcp_tool_becomes_the_stoppable_session_activity(fixture):
    """AI: An MCP tool's work is the same kind of session activity as an IDE search: while it
    runs the one Stop control is live, and pressing it hard-breaks the shared session so the
    tool's blocked call is abandoned. The MCP busy lifecycle drives the slot."""
    fixture.simulate_login()
    stop_button = fixture.app.status_stop_button

    fixture.app.integrated_session_state.begin_mcp_operation('gs_run_tests')
    fixture.app.update()
    assert isinstance(fixture.app.current_session_activity, McpActivity)
    assert str(stop_button.cget('state')) == tk.NORMAL

    stop_button.invoke()
    fixture.mock_browser.hard_break.assert_called_once()

    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.update()
    assert fixture.app.current_session_activity is None
    assert str(stop_button.cget('state')) == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_running_a_foreground_activity_delivers_its_result_on_the_ui_thread(fixture):
    """AI: A foreground activity runs off the UI thread; when its worker finishes the app
    clears the session slot and hands the result back here on the UI thread. This is the
    plumbing that keeps the UI responsive -- and thus interruptible -- during a search."""
    fixture.simulate_login()
    fixture.app.run_activities_synchronously = False
    delivered = {}
    activity = ForegroundActivity(
        'Working...',
        work=lambda should_stop: 'done',
        on_finished=lambda result: delivered.update(result=result),
    )

    fixture.app.run_foreground_activity(activity)
    deadline = time.monotonic() + 5
    while (
        fixture.app.current_session_activity is not None
        and time.monotonic() < deadline
    ):
        fixture.app.update()

    assert delivered['result'] == 'done'
    assert fixture.app.current_session_activity is None


class DenyingSessionAdmission:
    """AI: Stands in for the session-admission gate while an MCP operation holds the session:
    every IDE attempt to take the session is refused."""

    def try_admit(self):
        return None

    def release(self, operation_token):
        pass


@with_fixtures(SwordfishAppFixture)
def test_stop_button_enables_for_mcp_even_while_the_session_gate_is_closed(fixture):
    """AI: The gem-free announcement of an MCP activity must reach the UI even while the MCP
    operation holds the session -- otherwise the Stop button could never enable during the very
    operation it exists to interrupt. The session-admission gate must not block pure-UI events."""
    fixture.simulate_login()
    fixture.app.event_queue.session_admission = DenyingSessionAdmission()

    fixture.app.integrated_session_state.begin_mcp_operation('gs_run_tests')
    fixture.app.update()

    assert isinstance(fixture.app.current_session_activity, McpActivity)
    assert str(fixture.app.status_stop_button.cget('state')) == tk.NORMAL

    # AI: integrated_session_state is process-global; balance the begin so the busy state
    # does not leak into the next test.
    fixture.app.event_queue.session_admission = None
    fixture.app.integrated_session_state.end_mcp_operation()
    fixture.app.update()


@with_fixtures(SwordfishAppFixture)
def test_gem_touching_events_still_wait_for_the_session_gate_to_open(fixture):
    """AI: The gate still protects gem-touching event handlers from colliding with a concurrent
    MCP operation: such an event is held back while the session is taken, then delivered once it
    frees. Only the pure-UI events jump the queue."""
    fixture.simulate_login()
    handled = Mock()
    fixture.app.event_queue.subscribe('GemTouchingProbe', handled)
    fixture.app.event_queue.session_admission = DenyingSessionAdmission()

    fixture.app.event_queue.publish('GemTouchingProbe')
    handled.assert_not_called()

    fixture.app.event_queue.session_admission = None
    fixture.app.event_queue.run_deferred_processing()
    handled.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_model_refresh_requests_are_debounced_not_immediate(fixture):
    """AI: A burst of MCP write refresh-requests must not each trigger a structural
    re-read; handling defers (debounces) so the burst collapses -- otherwise a run
    of compiles would re-query packages/classes/methods once per call."""
    fixture.simulate_login()
    classes_changed = Mock()
    fixture.app.event_queue.subscribe('ClassesChanged', classes_changed)

    fixture.app.integrated_session_state.request_model_refresh('transaction')
    fixture.app.update()

    assert classes_changed.call_count == 0
    assert fixture.app.pending_model_refresh_after_id is not None

    fixture.app.process_pending_model_refresh_requests()
    fixture.app.update()
    classes_changed.assert_called()


@with_fixtures(SwordfishAppFixture)
def test_debounced_burst_re_reads_each_view_once(fixture):
    """AI: A settled burst of identical refresh-requests re-reads the views once,
    not once per request -- the dedup that makes auto-refresh affordable."""
    fixture.simulate_login()
    classes_changed = Mock()
    fixture.app.event_queue.subscribe('ClassesChanged', classes_changed)

    fixture.app.integrated_session_state.request_model_refresh('transaction')
    fixture.app.integrated_session_state.request_model_refresh('transaction')
    fixture.app.integrated_session_state.request_model_refresh('transaction')
    fixture.app.process_pending_model_refresh_requests()
    fixture.app.update()

    assert classes_changed.call_count == 1


@with_fixtures(SwordfishGuiFixture)
def test_open_editor_tab_reloads_its_source_on_methods_changed(fixture):
    """AI: An open editor tab re-reads its method source from the gem on
    MethodsChanged (which Refresh fans out), so an edit made in the image -- e.g.
    an MCP recompile -- replaces the tab's contents. This is why 'each tool
    re-reads itself' needs no special editor refresh wiring: the typed change
    events already are that fan-out."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    assert "amount * quantity" in tab.code_panel.text_editor.get("1.0", "end-1c")

    fixture.mock_browser.get_compiled_method.return_value.sourceString.return_value.to_py = (
        "total\n    ^42"
    )
    fixture.event_queue.publish("MethodsChanged")
    fixture.root.update()

    assert "^42" in tab.code_panel.text_editor.get("1.0", "end-1c")


@with_fixtures(SwordfishAppFixture)
def test_refresh_publishes_generic_refresh_from_image_event(fixture):
    """AI: refresh_from_image also fires a generic RefreshFromImage so the
    snapshot tools (class diagram, inspector) -- which don't track the typed
    change events -- can opt into the manual refresh and re-read in place."""
    fixture.simulate_login()
    refresh_requested = Mock()
    fixture.app.event_queue.subscribe('RefreshFromImage', refresh_requested)

    fixture.app.refresh_from_image()
    fixture.app.update()

    refresh_requested.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_class_diagram_refreshes_shown_class_contents_in_place(fixture):
    """AI: A manual Refresh re-reads each shown class's contents (inst vars) from
    the image and redraws it AT ITS CURRENT POSITION -- not a relayout/rebuild.
    An in-image change to the class shape appears; the layout you arranged stays."""
    fixture.simulate_login()
    fixture.app.ensure_class_diagram_tab()
    diagram = fixture.app.class_diagram_tab
    node = diagram.uml_canvas.add_or_update_class_node(
        {
            "class_name": "OrderLine",
            "superclass_name": "Object",
            "inst_var_names": ["amount"],
        }
    )
    node.x, node.y = 120, 80
    diagram.uml_canvas.redraw_node(node)
    assert node.inst_var_names == ["amount"]

    fixture.mock_browser.get_class_definition.side_effect = None
    fixture.mock_browser.get_class_definition.return_value = {
        "class_name": "OrderLine",
        "superclass_name": "Object",
        "inst_var_names": ["amount", "quantity"],
    }
    fixture.app.refresh_from_image()
    fixture.app.update()

    assert node.inst_var_names == ["amount", "quantity"]
    assert (node.x, node.y) == (120, 80)


@with_fixtures(SwordfishAppFixture)
def test_inspector_re_reads_object_in_place_on_refresh(fixture):
    """AI: A manual Refresh re-inspects each open inspector object so its current
    state from the image replaces what's shown -- the snapshot tool opts in via
    RefreshFromImage; the Explorer re-reads every tab (incl. navigated ones)."""
    fixture.simulate_login()
    an_object = make_mock_gemstone_object("OrderLine", "an OrderLine")
    fixture.app.open_inspector_for_object(an_object)
    fixture.app.update()
    explorer = fixture.app.inspector_tab.explorer
    context_inspector = fixture.app.nametowidget(explorer.tabs()[0])
    context_inspector.inspect_object = Mock()

    fixture.app.refresh_from_image()
    fixture.app.update()

    context_inspector.inspect_object.assert_called_once_with(an_object)


@with_fixtures(SwordfishAppFixture)
def test_closing_the_last_right_hand_tab_collapses_the_group(fixture):
    """AI: Closing the last tab of the right-hand group via its tab 'x' drops the
    split so the left group reclaims the space -- the same collapse Find's Close
    does -- for any auxiliary tool, here a class diagram. No blank hole left."""
    fixture.simulate_login()
    fixture.app.ensure_class_diagram_tab()
    right = fixture.app.pane_area.group(1)
    assert len(fixture.app.pane_area.groups) == 2

    fixture.app.close_top_level_tab_at_index(right, 0)

    assert len(fixture.app.pane_area.groups) == 1


@with_fixtures(SwordfishAppFixture)
def test_find_tab_is_closable_via_its_x_and_collapses_the_group(fixture):
    """AI: The Find tab closes via its tab 'x' like every other right-hand pane
    -- it is closable and collapses the group when it was the last tab there."""
    fixture.simulate_login()
    fixture.app.open_find_dialog()
    right = fixture.app.pane_area.group(1)
    assert fixture.app.top_level_tab_is_closable(right, 0)

    fixture.app.close_top_level_tab_at_index(right, 0)

    assert len(fixture.app.pane_area.groups) == 1


@with_fixtures(SwordfishAppFixture)
def test_debugger_dismiss_collapses_the_right_group(fixture):
    """AI: Dismissing the debugger (e.g. via Stop, or its finished Close) collapses
    its right-hand group like the tab 'x' does, rather than leaving a blank hole."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab
    assert len(fixture.app.pane_area.groups) == 2

    debugger_tab.dismiss()
    fixture.app.update()

    assert fixture.app.debugger_tab is None
    assert len(fixture.app.pane_area.groups) == 1


@with_fixtures(SwordfishAppFixture)
def test_debugger_save_recompiles_method_and_restarts_the_caller(fixture):
    """AI: Saving an edited method in the debugger recompiles it, then restarts
    the CALLER frame (selected level + 1). A live frame stays bound to the old
    method version, so re-sending the selector from the caller is what runs the
    new code (verified against a live gem). Editor views refresh via
    MethodsChanged + MethodDisplayRequested."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(level=1, class_name="OrderLine", method_name="total")
    debugger_tab.code_panel.text_editor.delete("1.0", "end")
    debugger_tab.code_panel.text_editor.insert("1.0", "total\n\t^ 42")

    fixture.session_record.update_method_source = Mock()
    methods_changed = Mock()
    displayed = Mock()
    fixture.app.event_queue.subscribe("MethodsChanged", methods_changed)
    fixture.app.event_queue.subscribe("MethodDisplayRequested", displayed)

    with patch.object(debugger_tab, "get_selected_stack_frame", return_value=frame):
        with patch.object(debugger_tab.debug_session, "restart_frame") as restart_frame:
            with patch.object(debugger_tab, "apply_debug_action_outcome"):
                debugger_tab.save_current_frame_method()
    fixture.app.update()

    fixture.session_record.update_method_source.assert_called_once_with(
        "OrderLine", True, "total", "total\n\t^ 42"
    )
    restart_frame.assert_called_once_with(2)
    methods_changed.assert_called_once()
    displayed.assert_called_once_with(("OrderLine", True, "total"), origin=ANY)


@with_fixtures(SwordfishAppFixture)
def test_resuming_in_the_debugger_runs_as_an_interruptible_activity(fixture):
    """AI: A debugger Resume can run unboundedly, so it goes through the foreground-activity
    runner -- the single menu-bar Stop can then abandon a long resume rather than freezing the
    IDE while the process runs."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab

    launched = []
    original_runner = fixture.app.run_foreground_activity

    def spy(activity):
        launched.append(activity)
        return original_runner(activity)

    fixture.app.run_foreground_activity = spy

    with patch.object(debugger_tab, "selected_frame_level", return_value=1):
        with patch.object(
            debugger_tab.debug_session, "continue_running", return_value=Mock()
        ) as continue_running:
            with patch.object(debugger_tab, "apply_debug_action_outcome") as applied:
                debugger_tab.continue_running()
                fixture.app.update()

    assert len(launched) == 1
    assert launched[0].message == "Resuming..."
    continue_running.assert_called_once()
    applied.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_a_stopped_resume_redisplays_the_re_suspended_process(fixture):
    """AI: When a Resume is stopped, the break re-suspends the process and the debugger redisplays
    at the new point -- a stopped resume is applied just like a completed action, not treated as
    an error that opens a fresh debugger."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab

    outcome = Mock()
    with patch.object(debugger_tab, "apply_debug_action_outcome") as applied:
        debugger_tab.apply_interrupted_debug_action_outcome(outcome)

    applied.assert_called_once_with(outcome)


@with_fixtures(SwordfishAppFixture)
def test_stepping_in_the_debugger_runs_as_an_interruptible_activity(fixture):
    """AI: A debugger step runs as a foreground activity too, sharing the resume path's runner and
    outcome handling, so a step over a long method can be stopped with the menu-bar Stop."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab

    launched = []
    original_runner = fixture.app.run_foreground_activity

    def spy(activity):
        launched.append(activity)
        return original_runner(activity)

    fixture.app.run_foreground_activity = spy

    with patch.object(debugger_tab, "selected_frame_level", return_value=1):
        with patch.object(
            debugger_tab.debug_session, "step_over", return_value=Mock()
        ) as step_over:
            with patch.object(debugger_tab, "apply_debug_action_outcome"):
                debugger_tab.step_over()
                fixture.app.update()

    assert len(launched) == 1
    assert launched[0].message == "Stepping over..."
    step_over.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_debugging_source_runs_as_an_interruptible_activity(fixture):
    """AI: The run-window Debug button runs the code to its first step point as a foreground
    activity, so a long run-to-breakpoint can be stopped with the menu-bar Stop."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    result = Mock()
    result.asString.return_value.to_py = "7"
    fixture.session_record.debug_source = Mock(return_value=result)

    launched = []
    original_runner = fixture.app.run_foreground_activity

    def spy(activity):
        launched.append(activity)
        return original_runner(activity)

    fixture.app.run_foreground_activity = spy

    run_tab.debug_selected_source("3 + 4")
    fixture.app.update()

    assert len(launched) == 1
    assert launched[0].message == "Debugging source..."
    fixture.session_record.debug_source.assert_called_once_with("3 + 4")


@with_fixtures(SwordfishAppFixture)
def test_debugger_source_menu_has_save_and_cancel(fixture):
    """AI: The debugger source pane is a full editor, so its right-click menu
    carries Save and Cancel (acting on the selected frame's method), like the
    editor's source menu."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab

    menu_event = types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1)
    debugger_tab.code_panel.open_text_menu(menu_event)
    fixture.app.update()

    labels = menu_command_labels(debugger_tab.code_panel.current_context_menu)
    assert "Save" in labels
    assert "Cancel" in labels


@with_fixtures(SwordfishAppFixture)
def test_debugger_source_menu_cancel_reloads_frame_source(fixture):
    """AI: Cancel in the debugger source pane discards edits by reloading the
    selected frame's method source."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab

    frame = types.SimpleNamespace(
        level=1,
        class_name="OrderLine",
        method_name="total",
        method_source="total\n\t^ 0",
        step_point_offset=1,
    )
    debugger_tab.code_panel.text_editor.delete("1.0", "end")
    debugger_tab.code_panel.text_editor.insert("1.0", "total\n\t^ 999")

    with patch.object(debugger_tab, "get_selected_stack_frame", return_value=frame):
        debugger_tab.cancel_current_frame_method()
    fixture.app.update()

    assert debugger_tab.code_panel.text_editor.get("1.0", "end-1c") == "total\n\t^ 0"


@with_fixtures(SwordfishAppFixture)
def test_debugger_tab_x_ends_the_live_debug_and_closes(fixture):
    """AI: The debugger's tab 'x' takes over the old Stop button -- a still-live
    debug is ended (the suspended process is resumed) and the debugger closes,
    collapsing its group."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab
    debugger_tab.stack_frames = [types.SimpleNamespace(level=1)]
    right = debugger_tab.master
    assert len(fixture.app.pane_area.groups) == 2

    with patch.object(debugger_tab.debug_session, "stop") as stop:
        fixture.app.close_top_level_tab_at_index(right, right.index(debugger_tab))
    fixture.app.update()

    stop.assert_called_once()
    assert fixture.app.debugger_tab is None
    assert len(fixture.app.pane_area.groups) == 1


@with_fixtures(SwordfishAppFixture)
def test_debugger_trims_to_caller_when_its_running_method_is_recompiled(fixture):
    """AI: Saving a method in the EDITOR that the debugger is running re-runs it
    with the new code -- the debugger restarts the CALLER of the frame running it
    (MethodRecompiled carries the method identity, so the debugger reacts only to
    its own method)."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    fixture.app.run_tab.debug_button.invoke()
    fixture.app.update()
    debugger_tab = fixture.app.debugger_tab
    debugger_tab.stack_frames = [
        types.SimpleNamespace(level=2, class_name="OrderLine", method_name="total")
    ]

    with patch.object(debugger_tab.debug_session, "restart_frame") as restart_frame:
        with patch.object(debugger_tab, "apply_debug_action_outcome"):
            fixture.app.event_queue.publish(
                "MethodRecompiled", ("OrderLine", True, "total"), origin=Mock()
            )
            fixture.app.update()

    restart_frame.assert_called_once_with(3)


@with_fixtures(SwordfishGuiFixture)
def test_editor_save_publishes_method_recompiled(fixture):
    """AI: Saving a method in the editor publishes MethodRecompiled carrying the
    method identity, so a debugger running it can react."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    recompiled = Mock()
    fixture.browser_window.application.event_queue.subscribe(
        "MethodRecompiled", recompiled
    )

    tab.code_panel.text_editor.delete("1.0", "end")
    tab.code_panel.text_editor.insert("1.0", "total\n    ^42")
    tab.save()
    fixture.root.update()

    recompiled.assert_called_once_with(("OrderLine", True, "total"), origin=ANY)


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_commands_delegate_to_swordfish_handlers(fixture):
    """AI: Selecting MCP menu actions should call corresponding Swordfish command handlers."""
    fixture.simulate_login()
    mcp_menu = fixture.app.menu_bar.mcp_menu
    with patch.object(fixture.app, "start_mcp_server_from_menu") as start_mcp:
        invoke_menu_command_by_label(mcp_menu, "Start MCP")
    start_mcp.assert_called_once()
    with patch.object(fixture.app, "stop_mcp_server_from_menu") as stop_mcp:
        with fixture.app.mcp_server_controller.lock:
            fixture.app.mcp_server_controller.running = True
        fixture.app.menu_bar.update_menus()
        invoke_menu_command_by_label(mcp_menu, "Stop MCP")
    stop_mcp.assert_called_once()
    with patch.object(fixture.app, "configure_mcp_server_from_menu") as configure_mcp:
        invoke_menu_command_by_label(mcp_menu, "Configure MCP")
    configure_mcp.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_reflects_embedded_server_running_state(fixture):
    """AI: MCP menu should disable start and enable stop while embedded MCP is running."""
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
    fixture.app.menu_bar.update_menus()
    mcp_menu = fixture.app.menu_bar.mcp_menu
    assert mcp_menu.entrycget(0, "state") == tk.DISABLED
    assert mcp_menu.entrycget(1, "state") == tk.NORMAL


@with_fixtures(SwordfishAppFixture)
def test_mcp_menu_reflects_embedded_server_stopping_state(fixture):
    """AI: MCP menu should disable start/stop/configure while embedded MCP is stopping."""
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.stopping = True
    fixture.app.menu_bar.update_menus()
    mcp_menu = fixture.app.menu_bar.mcp_menu
    assert mcp_menu.entrycget(0, "state") == tk.DISABLED
    assert mcp_menu.entrycget(1, "state") == tk.DISABLED
    assert mcp_menu.entrycget(3, "state") == tk.DISABLED


@with_fixtures(SwordfishAppFixture)
def test_start_mcp_menu_action_uses_foreground_activity_feedback(fixture):
    """AI: Starting MCP from menu should use the shared foreground activity feedback path."""
    with patch.object(fixture.app, "start_mcp_server", return_value=True):
        with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
            with patch.object(fixture.app, "end_foreground_activity") as end_activity:
                fixture.app.start_mcp_server_from_menu()
    begin_activity.assert_called_once_with("Starting MCP server...")
    end_activity.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_stop_mcp_menu_action_uses_foreground_activity_feedback(fixture):
    """AI: Stopping MCP from menu should use the shared foreground activity feedback path."""
    with patch.object(fixture.app, "stop_mcp_server", return_value=True):
        with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
            with patch.object(fixture.app, "end_foreground_activity") as end_activity:
                fixture.app.stop_mcp_server_from_menu()
    begin_activity.assert_called_once_with("Stopping MCP server...")
    end_activity.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_foreground_activity_feedback_controls_status_and_indicator(fixture):
    """AI: Foreground activity helper should show/hide progress feedback for non-MCP long actions."""
    fixture.simulate_login()

    class ActivityListener:
        def __init__(self):
            self.activity_events = []
            self.indicator_events = []

        def on_activity_changed(self, is_active=False, message=""):
            self.activity_events.append((is_active, message))

        def on_indicator_changed(self, is_visible=False):
            self.indicator_events.append(is_visible)

    listener = ActivityListener()
    fixture.app.event_queue.subscribe(
        "UiActivityChanged",
        listener.on_activity_changed,
    )
    fixture.app.event_queue.subscribe(
        "UiActivityIndicatorChanged",
        listener.on_indicator_changed,
    )

    fixture.app.begin_foreground_activity("Running long action...")
    fixture.app.update()
    assert fixture.app.collaboration_status_text.get() == "Running long action..."
    assert fixture.app.mcp_activity_indicator_visible is True
    assert listener.activity_events[-1] == (True, "Running long action...")
    assert listener.indicator_events[-1] is True

    fixture.app.end_foreground_activity()
    fixture.app.update()
    assert fixture.app.foreground_activity_message == ""
    assert fixture.app.mcp_activity_indicator_visible is False
    assert listener.activity_events[-1] == (False, "")
    assert listener.indicator_events[-1] is False


@with_fixtures(SwordfishAppFixture)
def test_foreground_activity_feedback_advances_indicator_immediately(fixture):
    """AI: Foreground activity should advance the indicator immediately so it remains visible during synchronous work."""
    fixture.simulate_login()
    fixture.app.begin_foreground_activity("Running tests...")
    fixture.app.update_idletasks()

    assert float(fixture.app.mcp_activity_indicator.cget("value")) > 0.0

    fixture.app.end_foreground_activity()


@with_fixtures(SwordfishAppFixture)
def test_indicator_is_hidden_when_mcp_server_is_running_but_idle(fixture):
    """AI: Idle startup status should not show a partially-filled progress indicator when MCP is merely running."""
    with fixture.app.mcp_server_controller.lock:
        fixture.app.mcp_server_controller.running = True
        fixture.app.mcp_server_controller.endpoint_url = "http://127.0.0.1:9177/mcp"
    fixture.simulate_login()
    fixture.app.refresh_collaboration_status()
    fixture.app.update()

    assert fixture.app.mcp_activity_indicator_visible is False
    assert fixture.app.mcp_activity_indicator.winfo_manager() == ""
    assert fixture.app.collaboration_status_text.get().startswith(
        "IDE ready. MCP running at http://127.0.0.1:"
    )


@with_fixtures(SwordfishAppFixture)
def test_browse_class_from_run_tab_navigates_to_class_under_cursor(fixture):
    """AI: Browse Class invoked from the Run tab's source editor delegates
    to the same Swordfish.browse_class entry point as the editor-tab
    version, so the user gets identical behaviour regardless of which
    source window they came from."""
    fixture.simulate_login()
    fixture.app.run_code("")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "^OrderLine new")
    run_tab.source_text.mark_set("insert", "1.1")
    fixture.session_record.jump_to_class = Mock()

    run_tab.browse_class_from_source()

    fixture.session_record.jump_to_class.assert_called_once_with(
        "OrderLine", True
    )


@with_fixtures(SwordfishAppFixture)
def test_run_tab_run_action_uses_foreground_activity_feedback(fixture):
    """AI: Run action should trigger shared foreground activity feedback while code executes."""
    fixture.simulate_login()
    fixture.app.run_code("3 + 4")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
        with patch.object(fixture.app, "end_foreground_activity") as end_activity:
            run_tab.run_code_from_editor()

    begin_activity.assert_called_once_with("Running source...")
    end_activity.assert_called_once()


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_result_on_successful_eval(fixture):
    """Running code in the Run tab should populate the result area with the evaluated object's printString."""
    fixture.simulate_login()

    # AI: on_run_complete calls result.asString().to_py to render the result.
    mock_result = Mock()
    mock_result.asString.return_value.to_py = "7"
    fixture.mock_browser.run_code.return_value = mock_result

    fixture.app.run_code("3 + 4")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    result_content = run_tab.result_text.get("1.0", "end").strip()
    assert result_content == "7"


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_always_shows_enabled_debug_button(fixture):
    """The Run tab should always show an enabled Debug button, even before any run error occurs."""
    fixture.simulate_login()

    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert hasattr(run_tab, "debug_button")
    assert run_tab.debug_button.winfo_exists()
    assert not run_tab.debug_button.instate(["disabled"])


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_debug_button_when_code_raises_error(fixture):
    """If run code raises a GemstoneError, the Run tab should still show the Debug button for opening the debugger."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert hasattr(run_tab, "debug_button")
    assert run_tab.debug_button.winfo_exists()


@with_fixtures(SwordfishAppFixture)
def test_running_source_goes_through_the_interruptible_activity_runner(fixture):
    """AI: Running code is now a foreground activity, so the single menu-bar Stop can interrupt a
    long doit. The run window hands the doit to the activity runner instead of calling the gem
    inline on the UI thread."""
    fixture.simulate_login()
    result = Mock()
    result.asString.return_value.to_py = "7"
    fixture.mock_browser.run_code.return_value = result

    launched = []
    original_runner = fixture.app.run_foreground_activity

    def spy(activity):
        launched.append(activity)
        return original_runner(activity)

    fixture.app.run_foreground_activity = spy

    fixture.app.run_code("3 + 4")
    fixture.app.update()

    assert len(launched) == 1
    assert launched[0].message == "Running source..."
    assert fixture.mock_browser.run_code.called


@with_fixtures(SwordfishAppFixture)
def test_stopping_a_run_reports_stopped_and_does_not_open_a_debugger(fixture):
    """AI: A user-requested Stop is not a failure: the run reports it was stopped and must not
    drop the user into a debugger (unlike a genuine trap, which does). The run window routes an
    interrupted outcome away from the error/debugger path."""
    fixture.simulate_login()
    fixture.app.run_code("1 + 1")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.on_run_error = Mock()

    run_tab.interrupt_source_run()

    assert run_tab.status_label.cget("text") == "Stopped."
    run_tab.on_run_error.assert_not_called()


@with_fixtures(SwordfishAppFixture)
def test_showing_selected_source_in_a_diagram_runs_as_an_interruptible_activity(fixture):
    """AI: Evaluating selected source to show it in a diagram is a foreground activity too, so a
    long evaluation can be stopped with the menu-bar Stop -- consistent with Run/Inspect/Debug."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    result = Mock()
    result.asString.return_value.to_py = "anOrder"
    fixture.mock_browser.run_code.return_value = result
    fixture.app.open_object_diagram_for_object = Mock()

    launched = []
    original_runner = fixture.app.run_foreground_activity

    def spy(activity):
        launched.append(activity)
        return original_runner(activity)

    fixture.app.run_foreground_activity = spy

    run_tab.show_selected_source_in_object_diagram("anOrder")
    fixture.app.update()

    assert len(launched) == 1
    assert launched[0].message == "Showing selected source in Object Diagram..."
    fixture.app.open_object_diagram_for_object.assert_called_once_with(result)


@with_fixtures(SwordfishAppFixture)
def test_run_source_text_shortcuts_replace_selection_and_support_undo(fixture):
    """Run source text supports select/copy/paste/undo shortcuts, and typed input replaces selected text."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert run_tab.source_text.bind("<Control-a>")
    assert run_tab.source_text.bind("<Control-c>")
    assert run_tab.source_text.bind("<Control-v>")
    assert run_tab.source_text.bind("<Control-z>")

    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "alpha beta")
    run_tab.source_text.tag_add(tk.SEL, "1.6", "1.10")

    fixture.app.clipboard_clear()
    fixture.app.clipboard_append("gamma")
    run_tab.paste_into_source_text()
    assert run_tab.source_text.get("1.0", "end-1c") == "alpha gamma"

    run_tab.undo_source_text()
    assert run_tab.source_text.get("1.0", "end-1c") == "alpha beta"

    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")
    run_tab.replace_selected_source_text_before_typing(
        types.SimpleNamespace(state=0, char="z", keysym="z"),
    )
    run_tab.source_text.insert(tk.INSERT, "z")
    assert run_tab.source_text.get("1.0", "end-1c") == "z beta"

    run_tab.select_all_source_text()
    run_tab.copy_source_selection()
    assert fixture.app.clipboard_get() == "z beta"


@with_fixtures(SwordfishAppFixture)
def test_run_source_editor_shows_line_numbers(fixture):
    """AI: Run source editor displays line numbers that track visible source lines."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert(
        "1.0",
        "alpha\nbeta\ngamma",
    )
    fixture.app.update()

    line_numbers = run_tab.source_line_number_column.line_numbers_text.get(
        "1.0",
        "end-1c",
    ).splitlines()
    assert line_numbers[:3] == ["1", "2", "3"]
    run_tab.source_text.mark_set(tk.INSERT, "3.2")
    run_tab.source_cursor_position_indicator.update_position()
    assert run_tab.source_cursor_position_label.cget("text") == "Ln 3, Col 3"


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_includes_run_and_inspect_for_selected_text(fixture):
    """Run source context menu exposes Run and Inspect commands that target selected text."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\n5 + 6")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert "Run" in labels
    assert "Inspect" in labels


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_includes_graph_inspect_for_selected_text(fixture):
    """AI: Run source context menu should expose Show in Object Diagram when source text is selected."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\n5 + 6")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert "Show in Object Diagram" in labels


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_run_executes_selected_text_only(fixture):
    """Run command in Run source context menu evaluates only the selected source fragment."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\nthisWillNotRun")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    mock_result = Mock()
    mock_result.asString.return_value.to_py = "7"
    fixture.mock_browser.run_code.return_value = mock_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Run")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert run_tab.result_text.get("1.0", "end").strip() == "7"


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_inspect_opens_inspector_for_selected_result(fixture):
    """Inspect command in Run source context menu evaluates selected source and opens Inspector on the result object."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\nthisWillNotRun")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    inspected_result = make_mock_gemstone_object("Integer", "7")
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert fixture.app.inspector_tab is not None
    assert isinstance(fixture.app.inspector_tab, InspectorTab)
    assert isinstance(fixture.app.inspector_tab.explorer, Explorer)
    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Inspect"


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_graph_inspect_opens_graph_for_selected_result(fixture):
    """AI: Show in Object Diagram in Run source context menu should evaluate selected source and open the Graph tab on that result."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\nthisWillNotRun")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    inspected_result = make_mock_gemstone_object("Integer", "7", oop=4444)
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Show in Object Diagram")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert fixture.app.object_diagram_tab is not None
    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Object Diagram"
    assert fixture.app.object_diagram_tab.graph_canvas.registry.contains_object(
        inspected_result
    )


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_show_in_class_diagram_opens_class_diagram(fixture):
    """AI: 'Show in Class Diagram' is part of the shared source-panel protocol, so
    the workspace source menu evaluates the selection and opens the Class Diagram tab
    on the class of the resulting object (here the selected class itself)."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "OrderLine")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.9")

    evaluated_class = make_mock_gemstone_object("OrderLine class", "OrderLine")
    evaluated_class.isBehavior.return_value.to_py = True
    evaluated_class.name.return_value.to_py = "OrderLine"
    fixture.mock_browser.run_code.return_value = evaluated_class

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    assert "Show in Class Diagram" in menu_command_labels(run_tab.current_text_menu)
    invoke_menu_command_by_label(run_tab.current_text_menu, "Show in Class Diagram")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("OrderLine")
    assert fixture.app.class_diagram_tab is not None
    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Class Diagram"
    assert fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for("OrderLine")


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_add_to_class_diagram_uses_class_name_without_eval(
    fixture,
):
    """AI: 'Add to Class Diagram' is the class-name sibling of Browse Class: it adds
    the class named under the cursor/selection to the Class Diagram WITHOUT evaluating
    anything, so it works on a bare class name in a larger expression."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "OrderLine new foo")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.9")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    assert "Add to Class Diagram" in menu_command_labels(run_tab.current_text_menu)
    invoke_menu_command_by_label(run_tab.current_text_menu, "Add to Class Diagram")
    fixture.app.update()

    fixture.mock_browser.run_code.assert_not_called()
    assert fixture.app.class_diagram_tab is not None
    assert fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for("OrderLine")


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_groups_actions_with_dividers(fixture):
    """AI: The source menu groups its actions - evaluate (Run/Inspect/Debug),
    navigate (Implementors/Senders/References/Browse Class) and diagram (Show in
    Object/Class Diagram, Add to Class Diagram) - in that order, with Add to Class
    Diagram stacked directly under Show in Class Diagram and separators dividing the
    groups."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "OrderLine new")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.9")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    menu = run_tab.current_text_menu
    labels = menu_command_labels(menu)
    expected_order = [
        "Run",
        "Inspect",
        "Debug",
        "Implementors",
        "Senders",
        "References",
        "Browse Class",
        "Show in Object Diagram",
        "Show in Class Diagram",
        "Add to Class Diagram",
    ]
    positions = [labels.index(label) for label in expected_order]
    assert positions == sorted(positions)
    assert (
        labels.index("Add to Class Diagram")
        == labels.index("Show in Class Diagram") + 1
    )

    separator_count = sum(
        1
        for entry_index in range(int(menu.index("end")) + 1)
        if menu.type(entry_index) == "separator"
    )
    assert separator_count >= 3


@with_fixtures(SwordfishAppFixture)
def test_inspector_scalar_value_pane_is_an_evaluable_workspace(fixture):
    """AI: The scalar inspector pane is a Workspace seeded with the printString and
    carrying the full evaluable context menu (Run / Inspect / Object & Class Diagram /
    References / Browse Class), so an attribute-less value is no dead end."""
    fixture.simulate_login()
    scalar = make_mock_gemstone_object("Integer", "42")
    fixture.app.open_inspector_for_object(scalar)
    fixture.app.update()

    explorer = fixture.app.inspector_tab.explorer
    context_inspector = fixture.app.nametowidget(explorer.tabs()[0])
    value_workspace = context_inspector.value_workspace

    assert value_workspace.grid_info() != {}
    assert value_workspace.text.get("1.0", "end-1c") == "42"

    value_workspace.open_context_menu(
        types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1)
    )
    labels = menu_command_labels(value_workspace.current_context_menu)
    for expected_label in (
        "Run",
        "Inspect",
        "Show in Object Diagram",
        "Show in Class Diagram",
        "References",
        "Browse Class",
        "Add to Class Diagram",
    ):
        assert expected_label in labels


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_includes_implementors_senders_and_references(fixture):
    """AI: The workspace source menu should expose the same navigation group
    (Implementors, Senders, References) as the method editor, so a selector or
    class can be explored from any source window."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "anArray do: aBlock")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.6")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert "Implementors" in labels
    assert "Senders" in labels
    assert "References" in labels


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_implementors_opens_dialog_for_selected_selector(
    fixture,
):
    """AI: Implementors from the workspace should resolve the selected selector and
    open the implementors dialog for it."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "total\n5 + 6")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    with patch.object(fixture.app, "open_implementors_dialog") as open_dialog:
        invoke_menu_command_by_label(run_tab.current_text_menu, "Implementors")
    open_dialog.assert_called_once_with(method_symbol="total")


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_senders_opens_dialog_for_selected_selector(
    fixture,
):
    """AI: Senders from the workspace should resolve the selected selector and open
    the senders dialog for it."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "total\n5 + 6")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    with patch.object(fixture.app, "open_senders_dialog") as open_dialog:
        invoke_menu_command_by_label(run_tab.current_text_menu, "Senders")
    open_dialog.assert_called_once_with(method_symbol="total")


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_references_opens_class_reference_search(
    fixture,
):
    """AI: References from the workspace should resolve the class name under the
    cursor and open an exact class-reference search for it."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "OrderLine new")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.9")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    with patch.object(fixture.app, "open_find_dialog_for_class") as open_dialog:
        invoke_menu_command_by_label(run_tab.current_text_menu, "References")
    open_dialog.assert_called_once_with("OrderLine")


@with_fixtures(SwordfishAppFixture)
def test_run_source_context_menu_includes_debug_for_selected_text(fixture):
    """AI: The Run source context menu must offer Debug wherever it already offers Run and Inspect."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4\n5 + 6")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(run_tab.current_text_menu)
    assert "Debug" in labels


@with_fixtures(SwordfishAppFixture)
def test_run_context_menu_debug_opens_debugger_for_selected_text_only(fixture):
    """AI: Debug in the Run source context menu debugs only the selected fragment and opens the Debugger on a runtime error."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "1/0\nthisWillNotRun")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.3")
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Debug")
    fixture.app.update()

    fixture.mock_browser.debug_source.assert_called_with("1/0")
    tab_labels = all_open_tab_texts(fixture.app)
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_inspect_button(fixture):
    """AI: The Run tab button row should offer Run, Inspect and Debug together, all enabled."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert hasattr(run_tab, "inspect_button")
    assert run_tab.inspect_button.winfo_exists()
    # AI: The action buttons are now compact icon glyphs (named by hover tooltips), not words.
    assert run_tab.inspect_button.cget("text") not in ("Inspect", "")
    for button in (run_tab.run_button, run_tab.inspect_button, run_tab.debug_button):
        assert not button.instate(["disabled"])
        # AI: each action is a glyph icon with a hover tooltip, not a wide text button.
        assert button.cget("text") not in ("Run", "Inspect", "Debug", "")
        assert button.bind("<Enter>")


@with_fixtures(SwordfishAppFixture)
def test_inspect_button_opens_inspector_for_full_source(fixture):
    """AI: Like Run and Debug, the Inspect button acts on the whole buffer, opening the Inspector on the result."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4")
    inspected_result = make_mock_gemstone_object("Integer", "7")
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.inspect_button.invoke()
    fixture.app.update()

    fixture.mock_browser.run_code.assert_called_with("3 + 4")
    assert fixture.app.inspector_tab is not None
    assert isinstance(fixture.app.inspector_tab, InspectorTab)


@with_fixtures(SwordfishAppFixture)
def test_debugger_source_panel_context_menu_includes_run_inspect_debug(fixture):
    """AI: The debugger frame source panel is a live code editor, so it too offers Run, Inspect and Debug."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    code_panel = fixture.app.debugger_tab.code_panel
    code_panel.refresh("3 + 4")
    code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")

    code_panel.open_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    labels = menu_command_labels(code_panel.current_context_menu)
    assert "Run" in labels
    assert "Inspect" in labels
    assert "Debug" in labels


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_opens_graph_for_oops(fixture):
    """AI: MCP IDE navigation action should resolve requested oops and open those objects in the Graph tab."""
    fixture.simulate_login()
    first_object = make_mock_gemstone_object("OrderLine", "anOrderLine", oop=3001)
    second_object = make_mock_gemstone_object("Order", "anOrder", oop=3002)
    objects_by_source = {
        "Object _objectForOop: 3001": first_object,
        "Object _objectForOop: 3002": second_object,
    }

    def object_for_source(source):
        return objects_by_source[source]

    fixture.mock_browser.run_code.side_effect = object_for_source
    response = fixture.app.perform_mcp_ide_navigation_action(
        "open_object_diagram_for_oops",
        {
            "oop_labels": ["3001", "3002"],
            "clear_existing": True,
        },
    )
    fixture.app.update()

    assert response["ok"], response
    assert response["opened_oops"] == ["3001", "3002"]
    assert response["unresolved_oops"] == []
    assert fixture.app.object_diagram_tab is not None
    registry = fixture.app.object_diagram_tab.graph_canvas.registry
    assert registry.contains_object(first_object)
    assert registry.contains_object(second_object)


@with_fixtures(SwordfishAppFixture)
def test_open_class_diagram_for_class_creates_uml_tab_and_adds_class(fixture):
    """AI: Opening UML for a class should create the UML tab and register that class node."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    assert fixture.app.class_diagram_tab is not None
    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Class Diagram"
    assert (
        fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for("OrderLine")
        is not None
    )


@with_fixtures(SwordfishAppFixture)
def test_uml_tab_shows_inheritance_for_added_classes(fixture):
    """AI: Adding related classes to the UML should create one inheritance edge between them."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    relationships = (
        fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()
    )
    inheritance_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
    ]

    assert len(inheritance_relationships) == 1
    assert inheritance_relationships[0].source_node.class_name == "OrderLine"
    assert inheritance_relationships[0].target_node.class_name == "Order"
    assert inheritance_relationships[0].relationship_style == "direct"


@with_fixtures(SwordfishAppFixture)
def test_uml_tab_shows_inferred_inheritance_for_transitive_ancestors(fixture):
    """AI: Adding a class and a transitive ancestor to the UML should show an inferred inheritance edge."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Object")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    relationships = (
        fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()
    )
    inheritance_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
    ]

    assert len(inheritance_relationships) == 1
    assert inheritance_relationships[0].source_node.class_name == "OrderLine"
    assert inheritance_relationships[0].target_node.class_name == "Object"
    assert inheritance_relationships[0].relationship_style == "inferred"


@with_fixtures(SwordfishAppFixture)
def test_uml_direct_inheritance_uses_one_grouped_connector_per_superclass(fixture):
    """AI: Direct subclasses of the same visible superclass should share one grouped inheritance connector."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.open_class_diagram_for_class("OrderAudit")
    fixture.app.update()

    inheritance_relationships = [
        relationship
        for relationship in fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()
        if relationship.relationship_kind == "inheritance"
    ]

    assert len(inheritance_relationships) == 2
    shared_item_ids = set(inheritance_relationships[0].canvas_item_ids).intersection(
        inheritance_relationships[1].canvas_item_ids
    )
    assert len(shared_item_ids) >= 2


@with_fixtures(SwordfishAppFixture)
def test_uml_grouped_inheritance_adds_horizontal_join_after_child_is_moved(fixture):
    """AI: A grouped inheritance connector with one child should add a horizontal join when the child moves off the parent's x-position."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    inheritance_relationship = (
        fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()[0]
    )
    parent_node = inheritance_relationship.target_node
    child_node = inheritance_relationship.source_node
    child_node.x = parent_node.x + 140

    fixture.app.class_diagram_tab.uml_canvas.redraw_all_relationships()
    fixture.app.update()

    horizontal_line_ids = [
        item_id
        for item_id in inheritance_relationship.canvas_item_ids
        if len(fixture.app.class_diagram_tab.uml_canvas.canvas.coords(item_id)) == 4
        and fixture.app.class_diagram_tab.uml_canvas.canvas.coords(item_id)[1]
        == fixture.app.class_diagram_tab.uml_canvas.canvas.coords(item_id)[3]
    ]

    assert len(horizontal_line_ids) == 1


@with_fixtures(SwordfishAppFixture)
def test_uml_inferred_inheritance_is_grouped_with_other_visible_children(fixture):
    """AI: Inferred inheritance into a visible superclass should share the grouped connector with direct subclasses of that superclass."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.open_class_diagram_for_class("OrderAudit")
    fixture.app.open_class_diagram_for_class("SpecialOrderLine")
    fixture.app.update()

    inheritance_relationships = [
        relationship
        for relationship in fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()
        if relationship.relationship_kind == "inheritance"
    ]
    direct_relationship = next(
        relationship
        for relationship in inheritance_relationships
        if relationship.relationship_style == "direct"
    )
    inferred_relationship = next(
        relationship
        for relationship in inheritance_relationships
        if relationship.relationship_style == "inferred"
    )

    shared_item_ids = set(direct_relationship.canvas_item_ids).intersection(
        inferred_relationship.canvas_item_ids
    )

    assert direct_relationship.target_node.class_name == "Order"
    assert inferred_relationship.target_node.class_name == "Order"
    assert len(shared_item_ids) >= 1


@with_fixtures(SwordfishAppFixture)
def test_uml_inferred_edge_menu_can_add_inheritance_details(fixture):
    """AI: Adding inheritance details should replace an inferred edge with the direct superclass chain, and restore the inferred edge if that detail is removed."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Object")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    uml_tab = fixture.app.class_diagram_tab
    relationships = uml_tab.uml_canvas.registry.all_relationships()
    inferred_relationship = relationships[0]
    line_id = inferred_relationship.canvas_item_ids[0]
    line_coordinates = uml_tab.uml_canvas.canvas.coords(line_id)
    midpoint_x = int((line_coordinates[0] + line_coordinates[2]) / 2)
    midpoint_y = int((line_coordinates[1] + line_coordinates[3]) / 2)

    uml_tab.uml_canvas.on_canvas_right_click(
        types.SimpleNamespace(
            x=midpoint_x,
            y=midpoint_y,
            x_root=1,
            y_root=1,
        )
    )
    fixture.app.update()

    menu = uml_tab.current_context_menu

    assert "Add Inheritance Details" in menu_command_labels(menu)

    invoke_menu_command_by_label(menu, "Add Inheritance Details")

    order_node = uml_tab.uml_canvas.registry.class_node_for("Order")
    relationships = uml_tab.uml_canvas.registry.all_relationships()
    direct_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
        and relationship.relationship_style == "direct"
    ]
    inferred_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
        and relationship.relationship_style == "inferred"
    ]

    assert order_node is not None
    assert any(
        relationship.source_node.class_name == "OrderLine"
        and relationship.target_node.class_name == "Order"
        for relationship in direct_relationships
    )
    assert any(
        relationship.source_node.class_name == "Order"
        and relationship.target_node.class_name == "Object"
        for relationship in direct_relationships
    )
    assert inferred_relationships == []

    uml_tab.remove_class_from_diagram("Order")
    fixture.app.update()

    relationships = uml_tab.uml_canvas.registry.all_relationships()
    inferred_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
        and relationship.relationship_style == "inferred"
    ]

    assert uml_tab.uml_canvas.registry.class_node_for("Order") is None
    assert len(inferred_relationships) == 1
    assert inferred_relationships[0].source_node.class_name == "OrderLine"
    assert inferred_relationships[0].target_node.class_name == "Object"


@with_fixtures(SwordfishAppFixture)
def test_uml_shows_only_one_visible_inheritance_path_to_common_ancestor(fixture):
    """AI: When an intermediate class is missing from the UML, each class should connect only to its nearest visible ancestor."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Object")
    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.open_class_diagram_for_class("SpecialOrderLine")
    fixture.app.update()

    uml_tab = fixture.app.class_diagram_tab
    uml_tab.remove_class_from_diagram("Order")
    fixture.app.update()

    relationships = uml_tab.uml_canvas.registry.all_relationships()
    inheritance_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
    ]

    assert len(inheritance_relationships) == 2
    assert any(
        relationship.source_node.class_name == "SpecialOrderLine"
        and relationship.target_node.class_name == "OrderLine"
        and relationship.relationship_style == "direct"
        for relationship in inheritance_relationships
    )
    assert any(
        relationship.source_node.class_name == "OrderLine"
        and relationship.target_node.class_name == "Object"
        and relationship.relationship_style == "inferred"
        for relationship in inheritance_relationships
    )
    assert not any(
        relationship.source_node.class_name == "SpecialOrderLine"
        and relationship.target_node.class_name == "Object"
        for relationship in inheritance_relationships
    )


@with_fixtures(SwordfishAppFixture)
def test_uml_rearrange_places_ancestors_above_descendants(fixture):
    """AI: Rearranging the UML should place visible ancestors above their descendants and align a single inheritance chain."""
    fixture.simulate_login()

    fixture.app.open_class_diagram_for_class("Object")
    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.open_class_diagram_for_class("SpecialOrderLine")
    fixture.app.update()

    uml_tab = fixture.app.class_diagram_tab
    object_node = uml_tab.uml_canvas.registry.class_node_for("Object")
    order_node = uml_tab.uml_canvas.registry.class_node_for("Order")
    order_line_node = uml_tab.uml_canvas.registry.class_node_for("OrderLine")
    special_order_line_node = uml_tab.uml_canvas.registry.class_node_for(
        "SpecialOrderLine"
    )

    object_node.x, object_node.y = 700, 500
    order_node.x, order_node.y = 120, 420
    order_line_node.x, order_line_node.y = 540, 240
    special_order_line_node.x, special_order_line_node.y = 60, 120

    rearranged = uml_tab.rearrange_diagram()
    fixture.app.update()

    assert rearranged is True
    assert object_node.y < order_node.y < order_line_node.y < special_order_line_node.y
    assert object_node.x == order_node.x
    assert order_node.x == order_line_node.x
    assert order_line_node.x == special_order_line_node.x


@with_fixtures(SwordfishAppFixture)
def test_pin_method_in_class_diagram_adds_method_to_class_node(fixture):
    """AI: Pinning a method into UML should add a method entry to that class node."""
    fixture.simulate_login()

    fixture.app.pin_method_in_class_diagram("OrderLine", True, "total")
    fixture.app.update()

    node = fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for("OrderLine")

    assert node is not None
    assert node.pinned_methods == [
        {
            "selector": "total",
            "show_instance_side": True,
            "label": "total",
        }
    ]


@with_fixtures(SwordfishAppFixture)
def test_uml_browse_class_selects_browser_class(fixture):
    """AI: Browsing a UML class should route to the browser class selection flow."""
    fixture.simulate_login()
    fixture.app.handle_find_selection = Mock()

    fixture.app.class_diagram_tab = None
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    fixture.app.class_diagram_tab.browse_class("OrderLine")
    fixture.app.update()

    fixture.app.handle_find_selection.assert_called_once_with(True, "OrderLine")


@with_fixtures(SwordfishAppFixture)
def test_uml_browse_method_selects_browser_method(fixture):
    """AI: Browsing a pinned UML method should route to the browser method selection flow."""
    fixture.simulate_login()
    fixture.app.handle_sender_selection = Mock()

    fixture.app.pin_method_in_class_diagram("OrderLine", True, "total")
    fixture.app.update()

    node = fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for("OrderLine")
    fixture.app.class_diagram_tab.browse_method("OrderLine", node.pinned_methods[0])
    fixture.app.update()

    fixture.app.handle_sender_selection.assert_called_once_with(
        "OrderLine",
        True,
        "total",
    )


@with_fixtures(SwordfishAppFixture)
def test_uml_method_chooser_lists_and_filters_methods_before_pinning(fixture):
    """AI: UML method selection should offer browser-style category and method filtering before pinning an existing method."""
    fixture.simulate_login()

    def list_method_categories(class_name, show_instance_side):
        if show_instance_side:
            return ["all", "accessing", "testing"]
        return ["all", "class accessing"]

    def list_methods(class_name, method_category, show_instance_side):
        if show_instance_side:
            return ["total", "description"]
        return ["defaultLineClass"]

    fixture.mock_browser.list_method_categories.side_effect = list_method_categories
    fixture.mock_browser.list_methods.side_effect = list_methods
    on_method_selected = Mock()

    dialog = UmlClassDiagramMethodChooserDialog(
        fixture.app,
        fixture.app,
        "OrderLine",
        on_method_selected,
    )
    fixture.app.update()

    category_entries = list(dialog.category_selection.selection_listbox.get(0, "end"))
    method_entries = list(dialog.method_selection.selection_listbox.get(0, "end"))

    assert category_entries == ["all", "accessing", "testing"]
    assert method_entries == ["total", "description"]

    dialog.method_selection.filter_var.set("tot")
    fixture.app.update()

    filtered_method_entries = list(
        dialog.method_selection.selection_listbox.get(0, "end")
    )
    assert filtered_method_entries == ["total"]

    dialog.side_var.set("class")
    dialog.handle_side_changed()
    fixture.app.update()

    class_side_category_entries = list(
        dialog.category_selection.selection_listbox.get(0, "end")
    )
    class_side_method_entries = list(
        dialog.method_selection.selection_listbox.get(0, "end")
    )
    assert class_side_category_entries == ["all", "class accessing"]
    assert class_side_method_entries == ["defaultLineClass"]

    dialog.side_var.set("instance")
    dialog.handle_side_changed()
    fixture.app.update()

    dialog.select_method("total")
    dialog.add_selected_method()
    fixture.app.update()

    on_method_selected.assert_called_once_with("OrderLine", True, "total")


@with_fixtures(SwordfishAppFixture)
def test_uml_add_existing_method_pins_it_on_class_node(fixture):
    """AI: Adding a chosen existing method from UML should pin it on the UML node without invoking method creation."""
    fixture.simulate_login()
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    node = fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for("OrderLine")

    fixture.app.class_diagram_tab.add_existing_method_to_node(
        "OrderLine",
        True,
        "total",
    )
    fixture.app.update()

    fixture.mock_browser.compile_method.assert_not_called()
    assert node.pinned_methods[0] == {
        "selector": "total",
        "show_instance_side": True,
        "label": "total",
    }


@with_fixtures(SwordfishAppFixture)
def test_uml_association_prompt_adds_target_class_and_relationship(fixture):
    """AI: Adding an association from a UML node should prompt for a target class and create the labeled edge."""
    fixture.simulate_login()
    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.update()
    source_node = fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for(
        "Order"
    )

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="OrderLine",
    ):
        fixture.app.class_diagram_tab.prompt_add_association(source_node, "lines")
        fixture.app.update()

    target_node = fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for(
        "OrderLine"
    )
    relationships = (
        fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()
    )
    association_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "association"
    ]

    assert target_node is not None
    assert len(association_relationships) == 1
    assert association_relationships[0].source_node is source_node
    assert association_relationships[0].target_node is target_node
    assert association_relationships[0].label == "lines"


@with_fixtures(SwordfishAppFixture)
def test_uml_undo_restores_diagram_after_clear(fixture):
    """AI: Undo after clearing the UML should restore the previously shown classes."""
    fixture.simulate_login()
    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    fixture.app.class_diagram_tab.clear_diagram()
    fixture.app.update()

    assert fixture.app.class_diagram_tab.uml_canvas.registry.all_nodes() == []

    fixture.app.class_diagram_tab.undo_diagram()
    fixture.app.update()

    restored_class_names = [
        node.class_name
        for node in fixture.app.class_diagram_tab.uml_canvas.registry.all_nodes()
    ]
    assert sorted(restored_class_names) == ["Order", "OrderLine"]


@with_fixtures(SwordfishAppFixture)
def test_uml_undo_reverts_association_addition_in_one_step(fixture):
    """AI: Undoing an association add should remove both the edge and any target class added by that action."""
    fixture.simulate_login()
    fixture.app.open_class_diagram_for_class("Order")
    fixture.app.update()
    source_node = fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for(
        "Order"
    )

    with patch(
        "reahl.swordfish.main.simpledialog.askstring",
        return_value="OrderLine",
    ):
        fixture.app.class_diagram_tab.prompt_add_association(source_node, "lines")
        fixture.app.update()

    fixture.app.class_diagram_tab.undo_diagram()
    fixture.app.update()

    remaining_class_names = [
        node.class_name
        for node in fixture.app.class_diagram_tab.uml_canvas.registry.all_nodes()
    ]
    assert remaining_class_names == ["Order"]
    assert fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships() == []


@with_fixtures(SwordfishAppFixture)
def test_uml_undo_reverts_pinned_method_and_added_class_in_one_step(fixture):
    """AI: Undoing the first method pin should remove both the pinned method and the class added for it."""
    fixture.simulate_login()

    fixture.app.pin_method_in_class_diagram("OrderLine", True, "total")
    fixture.app.update()

    fixture.app.class_diagram_tab.undo_diagram()
    fixture.app.update()

    assert fixture.app.class_diagram_tab.uml_canvas.registry.all_nodes() == []


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_selects_class_in_browser(fixture):
    """AI: MCP IDE navigation action should select class context in the browser."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    response = fixture.app.perform_mcp_ide_navigation_action(
        "select_class",
        {
            "class_name": "OrderLine",
            "show_instance_side": True,
        },
    )
    fixture.app.update()

    assert response["ok"], response
    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.show_instance_side is True


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_opens_method_in_browser(fixture):
    """AI: MCP IDE navigation action should select method context in the browser."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )
    fixture.mock_browser.get_method_category.return_value = "accessing"

    response = fixture.app.perform_mcp_ide_navigation_action(
        "open_method",
        {
            "class_name": "OrderLine",
            "method_symbol": "total",
            "show_instance_side": True,
        },
    )
    fixture.app.update()

    assert response["ok"], response
    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_method_symbol == "total"
    assert fixture.session_record.selected_method_category == "accessing"


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_queries_uml_diagram_state(fixture):
    """AI: MCP UML query should report the current UML diagram state from the IDE."""
    fixture.simulate_login()
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    response = fixture.app.perform_mcp_ide_navigation_action("query_class_diagram")

    assert response["ok"], response
    assert response["class_diagram_state"]["is_open"]
    assert response["class_diagram_state"]["is_selected"]
    assert (
        response["class_diagram_state"]["diagram"]["nodes"][0]["class_name"]
        == "OrderLine"
    )


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_adds_class_to_uml(fixture):
    """AI: MCP UML add-class action should open the UML tab and add the requested class."""
    fixture.simulate_login()

    response = fixture.app.perform_mcp_ide_navigation_action(
        "add_class_to_class_diagram",
        {
            "class_name": "OrderLine",
        },
    )
    fixture.app.update()

    assert response["ok"], response
    assert fixture.app.class_diagram_tab is not None
    assert (
        response["class_diagram_state"]["diagram"]["nodes"][0]["class_name"]
        == "OrderLine"
    )


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_adds_association_to_uml(fixture):
    """AI: MCP UML association action should add the association edge and target class to the diagram."""
    fixture.simulate_login()

    response = fixture.app.perform_mcp_ide_navigation_action(
        "add_association_to_class_diagram",
        {
            "source_class_name": "Order",
            "inst_var_name": "lines",
            "target_class_name": "OrderLine",
        },
    )
    fixture.app.update()

    relationships = (
        fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()
    )
    association_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "association"
    ]

    assert response["ok"], response
    assert any(
        relationship.source_node.class_name == "Order"
        and relationship.target_node.class_name == "OrderLine"
        and relationship.label == "lines"
        for relationship in association_relationships
    )


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_adds_inheritance_details_to_uml(fixture):
    """AI: MCP UML inheritance-detail action should replace an inferred edge with the missing direct superclass classes."""
    fixture.simulate_login()
    fixture.app.open_class_diagram_for_class("Object")
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    response = fixture.app.perform_mcp_ide_navigation_action(
        "add_inheritance_details_to_class_diagram",
        {
            "source_class_name": "OrderLine",
            "target_class_name": "Object",
        },
    )
    fixture.app.update()

    relationships = (
        fixture.app.class_diagram_tab.uml_canvas.registry.all_relationships()
    )
    inferred_relationships = [
        relationship
        for relationship in relationships
        if relationship.relationship_kind == "inheritance"
        and relationship.relationship_style == "inferred"
    ]

    assert response["ok"], response
    assert response["added_class_names"] == ["Order"]
    assert (
        fixture.app.class_diagram_tab.uml_canvas.registry.class_node_for("Order")
        is not None
    )
    assert inferred_relationships == []


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_clears_and_undoes_uml_diagram(fixture):
    """AI: MCP UML clear and undo actions should edit the diagram history just like the UI controls."""
    fixture.simulate_login()
    fixture.app.open_class_diagram_for_class("OrderLine")
    fixture.app.update()

    clear_response = fixture.app.perform_mcp_ide_navigation_action(
        "clear_class_diagram"
    )
    fixture.app.update()
    undo_response = fixture.app.perform_mcp_ide_navigation_action("undo_class_diagram")
    fixture.app.update()

    assert clear_response["ok"], clear_response
    assert clear_response["diagram_changed"] is True
    assert clear_response["class_diagram_state"]["diagram"]["nodes"] == []
    assert undo_response["ok"], undo_response
    assert undo_response["diagram_changed"] is True
    assert (
        undo_response["class_diagram_state"]["diagram"]["nodes"][0]["class_name"]
        == "OrderLine"
    )


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_reports_browser_source_selection(fixture):
    """AI: MCP current-view action should report active browser method source selection and method context."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )
    fixture.mock_browser.get_method_category.return_value = "accessing"
    open_method_response = fixture.app.perform_mcp_ide_navigation_action(
        "open_method",
        {
            "class_name": "OrderLine",
            "method_symbol": "total",
            "show_instance_side": True,
        },
    )
    assert open_method_response["ok"], open_method_response
    method_editor = fixture.app.browser_tab.editor_area_widget
    selected_editor_tab_id = method_editor.editor_notebook.select()
    selected_editor_tab = method_editor.editor_notebook.nametowidget(
        selected_editor_tab_id
    )
    source_text_widget = selected_editor_tab.code_panel.text_editor
    source_text_widget.tag_add(tk.SEL, "1.0", "1.5")
    source_text_widget.mark_set(tk.INSERT, "1.5")

    response = fixture.app.perform_mcp_ide_navigation_action("query_current_view")

    assert response["ok"], response
    assert response["active_tab"]["kind"] == "browser"
    assert response["active_source_view"]["kind"] == "browser_method_source"
    browser_source_state = response["active_source_view"]["state"]
    assert browser_source_state["method_context"] == {
        "class_name": "OrderLine",
        "show_instance_side": True,
        "method_symbol": "total",
    }
    assert browser_source_state["selection"]["has_selection"]
    assert browser_source_state["selection"]["selected_text"] == "total"
    assert response["browser_state"]["selected_method_symbol"] == "total"


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_reports_sender_find_dialog_state(fixture):
    """AI: MCP current-view action should report sender metadata from an open Find senders dialog."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
                "class_category": "Sales-Core",
                "method_category": "calculating",
                "method_category_is_extension": False,
                "extension_category_name": None,
            },
            {
                "class_name": "OrderAudit",
                "show_instance_side": True,
                "method_selector": "recordTotalChange",
                "class_category": "Auditing-Core",
                "method_category": "*Sales-Core",
                "method_category_is_extension": True,
                "extension_category_name": "Sales-Core",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="exact",
            reference_target="method",
        )

    response = fixture.app.perform_mcp_ide_navigation_action("query_current_view")

    assert response["ok"], response
    assert response["find_dialog_state"]["is_open"]
    assert response["find_dialog_state"]["is_sender_reference_search"]
    assert response["find_dialog_state"]["displayed_sender_count"] == 2
    assert {
        "class_name": "OrderAudit",
        "show_instance_side": True,
        "method_selector": "recordTotalChange",
        "class_category": "Auditing-Core",
        "method_category": "*Sales-Core",
        "method_category_is_extension": True,
        "extension_category_name": "Sales-Core",
    } in response["find_dialog_state"]["displayed_senders"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_filters_sender_find_dialog_by_class_category(
    fixture,
):
    """AI: MCP sender filter action should include extension methods when configured to match extension categories."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
                "class_category": "Sales-Core",
                "method_category": "calculating",
                "method_category_is_extension": False,
                "extension_category_name": None,
            },
            {
                "class_name": "OrderAudit",
                "show_instance_side": True,
                "method_selector": "recordTotalChange",
                "class_category": "Auditing-Core",
                "method_category": "*Sales-Core",
                "method_category_is_extension": True,
                "extension_category_name": "Sales-Core",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="exact",
            reference_target="method",
        )

    include_extensions_response = fixture.app.perform_mcp_ide_navigation_action(
        "filter_senders_in_find_dialog",
        {
            "class_category_filters": ["Sales-Core"],
            "include_extension_method_category_for_class_category": True,
        },
    )
    assert include_extensions_response["ok"], include_extensions_response
    assert include_extensions_response["displayed_sender_count"] == 2
    assert find_result_labels(dialog) == [
        "OrderAudit>>recordTotalChange",
        "OrderLine>>recalculateTotal",
    ]

    exclude_extensions_response = fixture.app.perform_mcp_ide_navigation_action(
        "filter_senders_in_find_dialog",
        {
            "class_category_filters": ["Sales-Core"],
            "include_extension_method_category_for_class_category": False,
        },
    )
    assert exclude_extensions_response["ok"], exclude_extensions_response
    assert exclude_extensions_response["displayed_sender_count"] == 1
    assert find_result_labels(dialog) == ["OrderLine>>recalculateTotal"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_reports_debugger_source_selection(fixture):
    """AI: MCP current-view action should report active debugger frame context and selected source text."""
    fixture.simulate_login()
    debugger_tab = ttk.Frame(fixture.app.notebook)
    debugger_source_widget = tk.Text(debugger_tab)
    debugger_source_widget.insert("1.0", "recalculateTotal\n    ^self total")
    debugger_source_widget.tag_add(tk.SEL, "1.0", "1.10")
    debugger_source_widget.mark_set(tk.INSERT, "1.10")
    selected_frame = types.SimpleNamespace(
        level=2,
        class_name="OrderLine",
        method_name="recalculateTotal",
        step_point_offset=17,
    )
    debugger_tab.code_panel = types.SimpleNamespace(text_editor=debugger_source_widget)
    debugger_tab.get_selected_stack_frame = Mock(return_value=selected_frame)
    debugger_tab.frame_method_context = Mock(
        return_value=("OrderLine", True, "recalculateTotal")
    )
    debugger_tab.is_running = True
    fixture.app.debugger_tab = debugger_tab
    fixture.app.notebook.add(debugger_tab, text="Debugger")
    fixture.app.notebook.select(debugger_tab)
    fixture.app.update()

    response = fixture.app.perform_mcp_ide_navigation_action("query_current_view")

    assert response["ok"], response
    assert response["active_tab"]["kind"] == "debugger"
    assert response["active_source_view"]["kind"] == "debugger_method_source"
    debugger_source_state = response["active_source_view"]["state"]
    assert debugger_source_state["method_context"] == {
        "class_name": "OrderLine",
        "show_instance_side": True,
        "method_symbol": "recalculateTotal",
    }
    assert debugger_source_state["selection"]["has_selection"]
    assert debugger_source_state["selection"]["selected_text"] == "recalculat"
    assert debugger_source_state["selected_frame"]["class_name"] == "OrderLine"
    assert debugger_source_state["selected_frame"]["method_name"] == "recalculateTotal"


@with_fixtures(SwordfishAppFixture)
def test_mcp_ide_navigation_action_delegates_to_debugger_opener(fixture):
    """AI: MCP debugger action should delegate to debugger opening handler."""
    fixture.simulate_login()
    example_exception = RuntimeError("MCP debugger test")

    with patch.object(
        fixture.app,
        "open_debugger_for_mcp_exception",
        return_value={"ok": True, "debugger_opened": True},
    ) as debugger_opener:
        response = fixture.app.perform_mcp_ide_navigation_action(
            "open_debugger_for_exception",
            {
                "exception": example_exception,
                "ask_before_open": True,
            },
        )

    debugger_opener.assert_called_once_with(
        example_exception,
        ask_before_open=True,
    )
    assert response["ok"], response


@with_fixtures(SwordfishAppFixture)
def test_run_inspector_uses_object_summary_as_first_tab_label(fixture):
    """AI: The first inspector tab should identify the inspected object rather than a generic Context label."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "Date today")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.9")

    inspected_result = make_mock_gemstone_object("Date", "2023/12/12")
    inspected_result.oop = 2003
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    first_tab_id = inspector_tab.explorer.tabs()[0]
    first_tab_label = inspector_tab.explorer.tab(first_tab_id, "text")
    assert first_tab_label == "2003:Date 2023/12/12"


@with_fixtures(SwordfishAppFixture)
def test_run_inspector_tab_can_be_closed_via_its_tab_x(fixture):
    """AI: The inspector tab opened from Run closes via its tab 'x' -- the single,
    uniform close for any right-hand tab -- clearing the inspector reference."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "3 + 4")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.5")

    inspected_result = make_mock_gemstone_object("Integer", "7")
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    right = inspector_tab.master
    fixture.app.close_top_level_tab_at_index(right, right.index(inspector_tab))
    fixture.app.update()

    assert fixture.app.inspector_tab is None
    assert "Inspect" not in all_open_tab_texts(fixture.app)


@with_fixtures(SwordfishAppFixture)
def test_inspector_tab_navigates_object_history_with_back_and_forward(fixture):
    """AI: Inspector tracks selected inspected objects and supports back/forward navigation through that history."""
    fixture.simulate_login()
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "anObject")
    run_tab.source_text.tag_add(tk.SEL, "1.0", "1.8")

    nested_object = make_mock_gemstone_object("Integer", "7", oop=2002)
    inspected_result = make_mock_instance_with_inst_vars(
        "OrderLine",
        "anOrderLine",
        {"child": nested_object},
        oop=2001,
    )
    fixture.mock_browser.run_code.return_value = inspected_result

    run_tab.open_source_text_menu(types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1))
    invoke_menu_command_by_label(run_tab.current_text_menu, "Inspect")
    fixture.app.update()

    inspector_tab = fixture.app.inspector_tab
    assert inspector_tab is not None
    assert str(inspector_tab.back_button.cget("state")) == tk.DISABLED
    assert str(inspector_tab.forward_button.cget("state")) == tk.DISABLED

    context_tab_id = inspector_tab.explorer.tabs()[0]
    context_inspector = inspector_tab.explorer.nametowidget(context_tab_id)
    context_row = context_inspector.treeview.get_children()[0]
    context_inspector.treeview.focus(context_row)
    context_inspector.on_item_double_click(None)
    fixture.app.update()

    context_label = inspector_tab.explorer.tab(context_tab_id, "text")
    nested_label = inspector_tab.explorer.tab(inspector_tab.explorer.select(), "text")
    assert context_label == "2001:OrderLine anOrderLine"
    assert nested_label == "2002:Integer 7"
    assert str(inspector_tab.back_button.cget("state")) == tk.NORMAL
    assert str(inspector_tab.forward_button.cget("state")) == tk.DISABLED

    inspector_tab.back_button.invoke()
    fixture.app.update()

    assert (
        inspector_tab.explorer.tab(inspector_tab.explorer.select(), "text")
        == context_label
    )
    assert str(inspector_tab.forward_button.cget("state")) == tk.NORMAL

    inspector_tab.forward_button.invoke()
    fixture.app.update()

    assert (
        inspector_tab.explorer.tab(inspector_tab.explorer.select(), "text")
        == nested_label
    )
    history_labels = list(inspector_tab.history_combobox["values"])
    assert nested_label in history_labels
    assert context_label in history_labels


@with_fixtures(SwordfishAppFixture)
def test_object_diagram_node_menu_browse_class_routes_graphed_object(fixture):
    """AI: The object diagram node context menu should browse the clicked object's class."""
    fixture.simulate_login()
    graphed_object = make_mock_gemstone_object('Integer', '7', oop=3007)
    browse_class_action = Mock()
    fixture.app.browse_object_class = browse_class_action
    fixture.app.open_object_diagram_for_object(graphed_object)
    fixture.app.update()

    graph_node = fixture.app.object_diagram_tab.graph_canvas.registry.node_for(
        graphed_object
    )
    fixture.app.object_diagram_tab.graph_canvas.on_canvas_right_click(
        types.SimpleNamespace(
            x=int(graph_node.x),
            y=int(graph_node.y),
            x_root=1,
            y_root=1,
        )
    )
    fixture.app.update()

    command_labels = menu_command_labels(
        fixture.app.object_diagram_tab.graph_canvas.current_context_menu
    )
    assert 'Browse Class' in command_labels

    invoke_menu_command_by_label(
        fixture.app.object_diagram_tab.graph_canvas.current_context_menu,
        'Browse Class',
    )
    fixture.app.update()

    browse_class_action.assert_called_once_with(graphed_object)


@with_fixtures(SwordfishAppFixture)
def test_object_diagram_detail_dialog_uses_object_title(fixture):
    """AI: The UML object detail dialog should title itself as an object rather than an object diagram node."""
    fixture.simulate_login()
    graphed_object = make_mock_gemstone_object('Integer', '7', oop=3007)
    fixture.app.open_object_diagram_for_object(graphed_object)
    fixture.app.update()

    graph_node = fixture.app.object_diagram_tab.graph_canvas.registry.node_for(
        graphed_object
    )
    dialog = UmlObjectDiagramNodeDetailDialog(
        fixture.app.object_diagram_tab,
        graphed_object,
        graph_node,
        on_add_to_graph=Mock(),
    )
    fixture.app.update()

    assert dialog.dialog.title() == f'Object: {graph_node.label}'

    dialog.dialog.destroy()
    fixture.app.update()


@with_fixtures(SwordfishAppFixture)
def test_object_diagram_detail_browse_class_closes_dialog(fixture):
    """AI: Browsing a class from an object diagram detail dialog should close that dialog."""
    fixture.simulate_login()
    graphed_object = make_mock_gemstone_object('Integer', '7', oop=3007)
    fixture.app.open_object_diagram_for_object(graphed_object)
    browse_class_action = Mock()
    fixture.app.browse_object_class = browse_class_action
    fixture.app.update()

    graph_node = fixture.app.object_diagram_tab.graph_canvas.registry.node_for(
        graphed_object
    )
    dialog = UmlObjectDiagramNodeDetailDialog(
        fixture.app.object_diagram_tab,
        graphed_object,
        graph_node,
        on_add_to_graph=Mock(),
    )
    fixture.app.update()

    dialog.inspector_host.inspector.browse_class_button.invoke()
    fixture.app.update()

    browse_class_action.assert_called_once_with(graphed_object)
    assert not dialog.dialog.winfo_exists()


@with_fixtures(SwordfishAppFixture)
def test_active_view_reports_focused_right_group_tool_not_browser(fixture):
    """AI: When a tool opened in the right-hand group (e.g. a class diagram) is
    the focused tab, the MCP active-view query must report that tool as active
    rather than always falling back to the browser in the primary group."""
    fixture.simulate_login()
    fixture.app.ensure_class_diagram_tab()
    fixture.app.update()

    view_state = fixture.app.current_ide_view_state()

    assert view_state['active_tab']['kind'] == 'class_diagram'


@with_fixtures(SwordfishAppFixture)
def test_run_result_text_supports_copy_and_has_result_context_menu(fixture):
    """The run result pane is now a Workspace: an editable scratch pane whose
    context menu offers the full evaluable action set (Select All / Copy / Paste /
    Undo plus Run), so a run's output can itself be copied, edited and re-run."""
    fixture.simulate_login()
    mock_result = Mock()
    mock_result.asString.return_value.to_py = "42"
    fixture.mock_browser.run_code.return_value = mock_result

    fixture.app.run_code("40 + 2")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    assert run_tab.result_text.bind("<Control-a>")
    assert run_tab.result_text.bind("<Control-c>")

    run_tab.result_workspace.select_all()
    run_tab.result_workspace.copy_selection()
    assert fixture.app.clipboard_get() == "42"

    run_tab.result_workspace.open_context_menu(
        types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1)
    )
    labels = menu_command_labels(run_tab.result_workspace.current_context_menu)
    assert "Select All" in labels
    assert "Copy" in labels
    assert "Paste" in labels
    assert "Undo" in labels
    assert "Run" in labels


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_shows_compile_error_location_and_highlights_source(fixture):
    """Compile errors show line/column details and visually mark the source position that failed to parse."""
    fixture.simulate_login()
    source_text = (
        "| a b |\n"
        "b := (Set new) add: 123; add: 457; add 1122; yourself.\n"
        "a := { 1 . 2 . 3 . 4 . 5 . (Date today) . b } .\n"
        "\n"
        "a halt at: 5\n"
    )
    fixture.mock_browser.run_code.side_effect = FakeCompileGemstoneError(
        source_text, 48
    )

    fixture.app.run_code(source_text)
    fixture.app.update()
    run_tab = fixture.app.run_tab

    status_text = run_tab.status_label.cget("text")
    assert "line 2, column 40" in status_text

    result_text = run_tab.result_text.get("1.0", "end")
    assert "Line 2, column 40" in result_text
    assert "b := (Set new) add: 123; add: 457; add 1122; yourself." in result_text
    assert "\n                                       ^\n" in result_text

    highlight_range = run_tab.source_text.tag_ranges("compile_error_location")
    assert len(highlight_range) == 2
    assert str(highlight_range[0]) == "2.39"
    assert str(highlight_range[1]) == "2.40"


@with_fixtures(SwordfishAppFixture)
def test_run_dialog_preserves_leading_blank_lines_for_compile_error_location(
    fixture,
):
    """Compile error location mapping keeps the source exactly as shown in the Run editor."""
    fixture.simulate_login()
    source_text = "\n" "| a |\n" "\n" "a := set new.\n" "a\n"

    def raise_compile_error(executed_source):
        offset = executed_source.index("set") + 1
        raise FakeCompileGemstoneError(executed_source, offset)

    fixture.mock_browser.run_code.side_effect = raise_compile_error

    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", source_text)

    run_tab.run_button.invoke()
    fixture.app.update()

    status_text = run_tab.status_label.cget("text")
    assert "line 4, column 6" in status_text
    expected_source = run_tab.source_text.get("1.0", "end-1c")
    assert fixture.mock_browser.run_code.call_args_list[-1] == call(expected_source)

    highlight_range = run_tab.source_text.tag_ranges("compile_error_location")
    assert len(highlight_range) == 2
    assert str(highlight_range[0]) == "4.5"
    assert str(highlight_range[1]) == "4.6"


@with_fixtures(SwordfishAppFixture)
def test_debug_button_opens_debugger_tab_in_notebook(fixture):
    """Clicking Debug from the Run tab after a runtime error should open a Debugger tab."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.debug_button.invoke()
    fixture.app.update()

    tab_labels = all_open_tab_texts(fixture.app)
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_button_uses_current_source_text_not_stale_prior_error(fixture):
    """Debug always evaluates the code currently visible in the Run source editor."""
    fixture.simulate_login()
    successful_result = Mock()
    successful_result.asString.return_value.to_py = "4"
    fixture.mock_browser.run_code.side_effect = [
        FakeGemstoneError(),
        successful_result,
    ]

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", "2 + 2")

    run_tab.debug_button.invoke()
    fixture.app.update()

    assert fixture.mock_browser.debug_source.call_args_list[-1] == call("2 + 2")
    assert fixture.app.debugger_tab is None
    assert (
        run_tab.status_label.cget("text") == "Completed; no step point to stop at"
    )


@with_fixtures(SwordfishAppFixture)
def test_debug_button_does_not_open_debugger_for_compile_error(fixture):
    """Debug does not open a debugger tab when current source has a compile error."""
    fixture.simulate_login()
    source_text = (
        "| a b |\n"
        "b := (Set new) add: 123; add: 457; add 1122; yourself.\n"
        "a := { 1 . 2 . 3 . 4 . 5 . (Date today) . b } .\n"
        "\n"
        "a halt at: 5\n"
    )
    fixture.app.run_code()
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.source_text.delete("1.0", "end")
    run_tab.source_text.insert("1.0", source_text)
    fixture.mock_browser.run_code.side_effect = FakeCompileGemstoneError(
        source_text, 48
    )

    run_tab.debug_button.invoke()
    fixture.app.update()

    tab_labels = all_open_tab_texts(fixture.app)
    assert "Debugger" not in tab_labels
    expected_source = run_tab.source_text.get("1.0", "end-1c")
    assert fixture.mock_browser.debug_source.call_args_list[-1] == call(expected_source)
    assert "line 2, column 40" in run_tab.status_label.cget("text")


@with_fixtures(SwordfishAppFixture)
def test_debug_button_selects_debugger_tab_as_visible(fixture):
    """After Debug is clicked from the Run tab, the Debugger tab should become the selected notebook tab."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab

    run_tab.debug_button.invoke()
    fixture.app.update()

    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Debugger"


@with_fixtures(SwordfishAppFixture)
def test_debugger_refresh_uses_selected_top_frame_source(fixture):
    """AI: Debugger refresh should render source for the selected top frame, not the next frame."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    top_frame = types.SimpleNamespace(
        level=1,
        class_name="TopFrameClass",
        method_name="topFrameMethod",
        method_source="top frame source",
        step_point_offset=4,
        self=Mock(),
        vars={},
    )
    second_frame = types.SimpleNamespace(
        level=2,
        class_name="SecondFrameClass",
        method_name="secondFrameMethod",
        method_source="second frame source",
        step_point_offset=9,
        self=Mock(),
        vars={},
    )

    class OneBasedStack:
        def __init__(self, frames):
            self.frames = list(frames)

        def __iter__(self):
            return iter(self.frames)

        def __bool__(self):
            return bool(self.frames)

        def __getitem__(self, level):
            return self.frames[level - 1]

    debugger_tab.stack_frames = OneBasedStack([top_frame, second_frame])

    with patch.object(debugger_tab.code_panel, "refresh") as refresh_source:
        with patch.object(debugger_tab, "refresh_explorer") as refresh_explorer:
            debugger_tab.refresh()

    assert debugger_tab.listbox.selection() == ("1",)
    refresh_source.assert_called_once_with("top frame source", mark=4)
    refresh_explorer.assert_called_once_with(top_frame)


@with_fixtures(SwordfishAppFixture)
def test_debugger_selected_stack_frame_matches_treeview_level_identifier(fixture):
    """AI: Debugger selection should resolve Treeview level ids to matching frame levels."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    top_frame = types.SimpleNamespace(
        level=1,
        class_name="TopFrameClass",
        method_name="topFrameMethod",
        method_source="top frame source",
        step_point_offset=4,
        self=Mock(),
        vars={},
    )
    second_frame = types.SimpleNamespace(
        level=2,
        class_name="SecondFrameClass",
        method_name="secondFrameMethod",
        method_source="second frame source",
        step_point_offset=9,
        self=Mock(),
        vars={},
    )

    class OneBasedStack:
        def __init__(self, frames):
            self.frames = list(frames)

        def __iter__(self):
            return iter(self.frames)

        def __bool__(self):
            return bool(self.frames)

        def __getitem__(self, level):
            return self.frames[level - 1]

    debugger_tab.stack_frames = OneBasedStack([top_frame, second_frame])
    debugger_tab.refresh()

    assert debugger_tab.get_selected_stack_frame() is top_frame

    debugger_tab.listbox.selection_set("2")
    debugger_tab.listbox.focus("2")
    assert debugger_tab.get_selected_stack_frame() is second_frame


@with_fixtures(SwordfishAppFixture)
def test_debugger_frame_list_shows_class_and_method_category_columns(fixture):
    """AI: Each debugger frame shows the class category and method category of its
    activation - mirroring the Find dialog - while keeping call-stack order. A
    class-side activation resolves its categories from the instance-side class."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()
    fixture.mock_browser.get_method_category.return_value = "printing"

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    instance_frame = types.SimpleNamespace(
        level=1,
        class_name="Order",
        method_name="total",
        method_source="total source",
        step_point_offset=1,
        self=Mock(),
        vars={},
    )
    class_side_frame = types.SimpleNamespace(
        level=2,
        class_name="Order class",
        method_name="default",
        method_source="default source",
        step_point_offset=1,
        self=Mock(),
        vars={},
    )

    class OneBasedStack:
        def __init__(self, frames):
            self.frames = list(frames)

        def __iter__(self):
            return iter(self.frames)

        def __bool__(self):
            return bool(self.frames)

        def __getitem__(self, level):
            return self.frames[level - 1]

    debugger_tab.stack_frames = OneBasedStack([instance_frame, class_side_frame])
    debugger_tab.refresh()

    assert debugger_tab.listbox.set("1", "ClassCategory") == "Kernel"
    assert debugger_tab.listbox.set("1", "MethodCategory") == "printing"
    assert debugger_tab.listbox.set("2", "ClassName") == "Order class"
    assert debugger_tab.listbox.set("2", "ClassCategory") == "Kernel"
    assert [
        debugger_tab.listbox.set(iid, "Level")
        for iid in debugger_tab.listbox.get_children()
    ] == ["1", "2"]


@with_fixtures(SwordfishAppFixture)
def test_completed_debugger_can_be_closed_via_its_tab_x(fixture):
    """AI: Once debugger execution completes, it closes via its tab 'x' -- the
    single, uniform close for any right-hand tab -- exiting debugger mode."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    completed_result = Mock()
    completed_result.asString.return_value.to_py = "42"
    debugger_tab.finish(completed_result)
    fixture.app.update()

    right = debugger_tab.master
    fixture.app.close_top_level_tab_at_index(right, right.index(debugger_tab))
    fixture.app.update()

    assert fixture.app.debugger_tab is None
    assert "Debugger" not in all_open_tab_texts(fixture.app)


@with_fixtures(SwordfishAppFixture)
def test_debugger_active_controls_place_restart_after_through(
    fixture,
):
    """AI: Restart action sits in the stepping flow after Through (Stop is gone --
    the tab 'x' ends the debug)."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    through_column = int(
        debugger_tab.debugger_controls.through_button.grid_info()["column"]
    )
    restart_column = int(
        debugger_tab.debugger_controls.restart_button.grid_info()["column"]
    )
    assert through_column < restart_column
    # AI: The debugger controls are now compact icon glyphs (named by hover tooltips), not words.
    assert debugger_tab.debugger_controls.restart_button.cget("text") not in ("Restart", "")


@with_fixtures(SwordfishAppFixture)
def test_debugger_restart_button_dispatches_to_restart_frame(fixture):
    """AI: Restart debugger control should invoke restart of the selected frame."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    with patch.object(debugger_tab, "restart_frame") as restart_frame:
        debugger_tab.debugger_controls.restart_button.invoke()

    restart_frame.assert_called_once_with()


@with_fixtures(SwordfishAppFixture)
def test_debugger_restart_frame_uses_selected_level_with_debug_session(
    fixture,
):
    """AI: Restart frame action should restart exactly the selected frame level and apply the resulting outcome."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    action_outcome = Mock()
    with patch.object(
        debugger_tab,
        "selected_frame_level",
        return_value=3,
    ):
        with patch.object(
            debugger_tab.debug_session,
            "restart_frame",
            return_value=action_outcome,
        ) as restart_frame:
            with patch.object(
                debugger_tab,
                "apply_debug_action_outcome",
            ) as apply_debug_action_outcome:
                debugger_tab.restart_frame()

    restart_frame.assert_called_once_with(3)
    apply_debug_action_outcome.assert_called_once_with(action_outcome)


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_method_navigates_to_selected_stack_frame_method(fixture):
    """AI: Browse Method on debugger should navigate the browser to the selected stack frame method."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name="OrderLine",
        method_name="total",
    )

    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        with patch.object(
            fixture.app,
            "handle_sender_selection",
        ) as handle_sender_selection:
            debugger_tab.open_selected_frame_method()

    handle_sender_selection.assert_called_once_with(
        "OrderLine",
        True,
        "total",
    )


@with_fixtures(SwordfishAppFixture)
def test_debugger_browse_method_maps_class_side_frames_to_class_side_selection(fixture):
    """AI: Class-side stack frames should browse to the class side in the browser."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name="OrderLine class",
        method_name="buildForDemo",
    )

    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        with patch.object(
            fixture.app,
            "handle_sender_selection",
        ) as handle_sender_selection:
            debugger_tab.open_selected_frame_method()

    handle_sender_selection.assert_called_once_with(
        "OrderLine",
        False,
        "buildForDemo",
    )


@with_fixtures(SwordfishAppFixture)
def test_debugger_stack_frame_menu_offers_browse_class_and_browse_method(fixture):
    """AI: Right-clicking a stack frame in the debugger should expose both Browse Class (jumps to the frame's receiver class) and Browse Method (jumps to the method currently executing on that frame), since 'browse the code that this frame is paused inside' is what users reach for when triaging an exception."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name='OrderLine',
        method_name='total',
    )

    with patch.object(
        debugger_tab,
        'get_selected_stack_frame',
        return_value=frame,
    ):
        debugger_tab.open_stack_frame_menu(
            types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
        )
        fixture.app.update()

        command_labels = menu_command_labels(debugger_tab.current_stack_frame_menu)
        assert 'Browse Class' in command_labels
        assert 'Browse Method' in command_labels

        with patch.object(
            fixture.app,
            'browse_class',
        ) as browse_class:
            invoke_menu_command_by_label(
                debugger_tab.current_stack_frame_menu, 'Browse Class'
            )
        browse_class.assert_called_once_with('OrderLine', True)

        with patch.object(
            fixture.app,
            'handle_sender_selection',
        ) as handle_sender_selection:
            invoke_menu_command_by_label(
                debugger_tab.current_stack_frame_menu, 'Browse Method'
            )
        handle_sender_selection.assert_called_once_with('OrderLine', True, 'total')


@with_fixtures(SwordfishAppFixture)
def test_debugger_stack_frame_menu_browse_class_respects_class_side_frames(fixture):
    """AI: A class-side stack frame ('OrderLine class') should browse to the class side, mirroring how Browse Method already strips the ' class' suffix and flips show_instance_side."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code('1/0')
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame = types.SimpleNamespace(
        class_name='OrderLine class',
        method_name='buildForDemo',
    )

    with patch.object(
        debugger_tab,
        'get_selected_stack_frame',
        return_value=frame,
    ):
        debugger_tab.open_stack_frame_menu(
            types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
        )
        fixture.app.update()

        with patch.object(
            fixture.app,
            'browse_class',
        ) as browse_class:
            invoke_menu_command_by_label(
                debugger_tab.current_stack_frame_menu, 'Browse Class'
            )

    browse_class.assert_called_once_with('OrderLine', False)


@with_fixtures(SwordfishAppFixture)
def test_debugger_variable_inspect_opens_main_inspector_tab(fixture):
    """AI: Inspecting a debugger variable from its context menu opens the main Inspector tab for that object."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    frame_self = make_mock_gemstone_object("OrderLine", "anOrderLine", oop=3001)
    frame_variable = make_mock_gemstone_object("Integer", "42", oop=3002)
    frame = types.SimpleNamespace(
        self=frame_self,
        vars={"x": frame_variable},
    )
    debugger_tab.refresh_explorer(frame)
    fixture.app.update()

    context_tab_id = debugger_tab.explorer.tabs()[0]
    context_inspector = debugger_tab.explorer.nametowidget(context_tab_id)
    variable_row = None
    for row_id in context_inspector.treeview.get_children():
        row_name = context_inspector.treeview.item(row_id, "values")[0]
        if row_name == "x" and variable_row is None:
            variable_row = row_id
    assert variable_row is not None

    context_inspector.treeview.focus(variable_row)
    context_inspector.treeview.selection_set(variable_row)
    context_inspector.open_object_menu(
        types.SimpleNamespace(
            x=-1,
            y=-1,
            x_root=1,
            y_root=1,
        ),
    )
    menu_labels = menu_command_labels(context_inspector.current_object_menu)
    assert "Inspect" in menu_labels
    invoke_menu_command_by_label(context_inspector.current_object_menu, "Inspect")
    fixture.app.update()

    assert fixture.app.inspector_tab is not None
    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Inspect"
    root_tab_id = fixture.app.inspector_tab.explorer.tabs()[0]
    root_tab_label = fixture.app.inspector_tab.explorer.tab(root_tab_id, "text")
    assert root_tab_label == "3002:Integer 42"


@with_fixtures(SwordfishAppFixture)
def test_debugger_source_context_menu_inspect_evaluates_selected_expression_in_frame(
    fixture,
):
    """AI: Inspect from debugger source menu evaluates selected expression in the active frame and opens Inspector."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    evaluated_value = make_mock_gemstone_object("Integer", "3", oop=3003)
    mock_var_context = Mock()
    mock_gemstone_session = Mock()
    mock_gemstone_session.execute.return_value = evaluated_value
    frame = types.SimpleNamespace(
        self=make_mock_gemstone_object("OrderLine", "anOrderLine", oop=3001),
        vars={"x": make_mock_gemstone_object("Integer", "2", oop=3002)},
        var_context=mock_var_context,
        gemstone_session=mock_gemstone_session,
    )

    debugger_tab.code_panel.text_editor.delete("1.0", "end")
    debugger_tab.code_panel.text_editor.insert("1.0", "x + 1")
    debugger_tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.5")
    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        debugger_tab.code_panel.open_text_menu(
            types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
        )
        menu_labels = menu_command_labels(debugger_tab.code_panel.current_context_menu)
        assert "Inspect" in menu_labels
        invoke_menu_command_by_label(
            debugger_tab.code_panel.current_context_menu,
            "Inspect",
        )
        fixture.app.update()

    mock_gemstone_session.execute.assert_called_once_with(
        "x + 1",
        context=mock_var_context,
    )
    assert fixture.app.inspector_tab is not None
    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Inspect"
    root_tab_id = fixture.app.inspector_tab.explorer.tabs()[0]
    root_tab_label = fixture.app.inspector_tab.explorer.tab(root_tab_id, "text")
    assert root_tab_label == "3003:Integer 3"


@with_fixtures(SwordfishAppFixture)
def test_debugger_source_context_menu_inspect_reads_self_instance_variable(
    fixture,
):
    """AI: Inspecting an instance-variable token in debugger source should resolve from self, not evaluate as a free symbol."""
    fixture.simulate_login()
    fixture.mock_browser.run_code.side_effect = FakeGemstoneError()

    fixture.app.run_code("1/0")
    fixture.app.update()
    run_tab = fixture.app.run_tab
    run_tab.debug_button.invoke()
    fixture.app.update()

    debugger_tab = fixture.app.debugger_tab
    full_value = make_mock_gemstone_object("Set", "aSet", oop=4004)
    frame_self = make_mock_instance_with_inst_vars(
        "ExampleSetTest",
        "anExampleSetTest",
        {"full": full_value},
        oop=4001,
    )
    mock_var_context = Mock()
    mock_gemstone_session = Mock()
    mock_gemstone_session.execute.side_effect = FakeGemstoneError()
    frame = types.SimpleNamespace(
        self=frame_self,
        vars={},
        var_context=mock_var_context,
        gemstone_session=mock_gemstone_session,
    )

    debugger_tab.code_panel.text_editor.delete("1.0", "end")
    debugger_tab.code_panel.text_editor.insert("1.0", "full add: 5")
    debugger_tab.code_panel.text_editor.tag_add(tk.SEL, "1.0", "1.4")
    with patch.object(
        debugger_tab,
        "get_selected_stack_frame",
        return_value=frame,
    ):
        debugger_tab.code_panel.open_text_menu(
            types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
        )
        invoke_menu_command_by_label(
            debugger_tab.code_panel.current_context_menu,
            "Inspect",
        )
        fixture.app.update()

    mock_gemstone_session.execute.assert_not_called()
    assert fixture.app.inspector_tab is not None
    selected_tab_text = visible_tab_title(fixture.app.pane_area.group(1))
    assert selected_tab_text == "Inspect"
    root_tab_id = fixture.app.inspector_tab.explorer.tabs()[0]
    root_tab_label = fixture.app.inspector_tab.explorer.tab(root_tab_id, "text")
    assert root_tab_label == "4004:Set aSet"


@with_fixtures(SwordfishAppFixture)
def test_file_run_command_opens_run_tab_in_notebook(fixture):
    """Choosing Debug > Workspace should open and select a Workspace tab in the main notebook."""
    fixture.simulate_login()

    fixture.app.run_code()
    fixture.app.update()

    tab_labels = [
        fixture.app.notebook.tab(tab_id, "text")
        for tab_id in fixture.app.notebook.tabs()
    ]
    assert "Workspace" in tab_labels
    selected_tab_text = visible_tab_title(fixture.app.notebook)
    assert selected_tab_text == "Workspace"


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_class_search_populates_result_list(fixture):
    """Searching for a class name in the FindPane calls GemStone and
    populates the results listbox with the matching class names."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ["OrderLine", "OrderHistory"]

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.find_entry.insert(0, "Order")
    dialog.find_text()

    results = find_result_labels(dialog)
    assert "OrderLine" in results
    assert "OrderHistory" in results
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_pressing_enter_in_search_box_runs_the_search(fixture):
    """AI: Pressing Enter in the search box runs the search, exactly like the find
    (magnifying-glass) button -- so a search doesn't require reaching for a button."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ["OrderLine", "OrderHistory"]
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)
    dialog.find_entry.insert(0, "Order")

    # AI: A <Return> binding is installed on the search box (we assert the wire is
    # present; Tk won't deliver a synthetic keystroke to an unmapped widget), and
    # invoking that bound action runs the search and populates the results.
    assert dialog.find_entry.bind("<Return>")
    dialog.find_text()

    assert set(find_result_labels(dialog)) == {"OrderLine", "OrderHistory"}
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_is_an_icon_button_beside_the_search_box_with_no_per_dialog_stop(fixture):
    """AI: Find is a compact icon button (a glyph, not wide text) on the search-box row, to
    the right of the entry. There is no per-dialog Stop button: interrupting is the job of
    the single menu-bar Stop, which governs whichever activity holds the shared session."""
    fixture.simulate_login()
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    # AI: Each category tab carries its own icon find button beside its query entry.
    find_button = dialog.find_buttons[0]
    query_entry = dialog.query_entries[0]
    assert find_button.cget("text") not in ("Find", "")
    assert int(find_button.grid_info()["row"]) == int(
        query_entry.grid_info()["row"]
    )
    assert int(find_button.grid_info()["column"]) > int(
        query_entry.grid_info()["column"]
    )
    assert not hasattr(dialog, "stop_button")
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_results_have_one_regex_filter_box_per_visible_column(fixture):
    """AI: Every find type gets filtering: the filter row holds one regex box per
    visible result column. A class search shows Class + Class Category columns, so
    two filter boxes keyed by those columns."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ["OrderLine", "OrderHistory"]
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)
    dialog.find_entry.insert(0, "Order")
    dialog.find_text()

    assert set(dialog.column_filter_entries.keys()) == {"#0", "ClassCategory"}
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_class_results_filter_by_class_column_regex(fixture):
    """AI: Typing a regex in a column's filter box keeps only rows whose value in
    that column matches (case-insensitive), re-rendering the unfiltered baseline
    without re-querying GemStone."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ["OrderLine", "OrderHistory"]
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)
    dialog.find_entry.insert(0, "Order")
    dialog.find_text()
    assert set(find_result_labels(dialog)) == {"OrderLine", "OrderHistory"}

    dialog.column_filter_entries["#0"].insert(0, "Line$")
    dialog.render_current_results()

    assert find_result_labels(dialog) == ["OrderLine"]
    fixture.mock_browser.find_classes.assert_called_once()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_selector_results_filter_by_method_column_regex(fixture):
    """AI: The bare-selector ('contains') search also gets a filter box -- on its
    single Method column -- so even the simplest find type is filterable."""
    fixture.simulate_login()
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)
    dialog.display_selector_results(["printOn:", "printString", "addAll:"])
    assert set(find_result_labels(dialog)) == {"printOn:", "printString", "addAll:"}
    assert set(dialog.column_filter_entries.keys()) == {"#0"}

    dialog.column_filter_entries["#0"].insert(0, "^print")
    dialog.render_current_results()

    assert set(find_result_labels(dialog)) == {"printOn:", "printString"}
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_invalid_filter_regex_is_ignored_not_blanking_results(fixture):
    """AI: A half-typed/invalid regex in a filter box is ignored rather than
    emptying the list, so filtering as-you-type never hides everything on an
    incomplete pattern."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ["OrderLine", "OrderHistory"]
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)
    dialog.find_entry.insert(0, "Order")
    dialog.find_text()

    dialog.column_filter_entries["#0"].insert(0, "Order(")
    dialog.render_current_results()

    assert set(find_result_labels(dialog)) == {"OrderLine", "OrderHistory"}
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_filter_boxes_are_overlaid_aligned_to_their_columns(fixture):
    """AI: Each filter box is an unlabelled entry placed (overlaid) above its
    column, aligned to that column's boundary: box order follows the columns and
    each box's x-position is the cumulative width of the columns to its left, so it
    sits exactly over its heading and follows when columns resize."""
    fixture.simulate_login()
    fixture.mock_browser.find_classes.return_value = ["OrderLine"]
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)
    dialog.find_entry.insert(0, "Order")
    dialog.find_text()
    dialog.update_idletasks()

    assert dialog.filter_column_order == ["#0", "ClassCategory"]
    first_box = dialog.column_filter_entries["#0"]
    second_box = dialog.column_filter_entries["ClassCategory"]
    # AI: placed via place(), so geometry manager is 'place' and x tracks the
    # cumulative column width (#0 width) -- no label tuple, just the box.
    assert first_box.winfo_manager() == "place"
    assert first_box.place_info()["x"] == "0"
    assert int(second_box.place_info()["x"]) == dialog.results_tree.column(
        "#0", "width"
    )
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_class_mode_supports_contains_and_exact_matching(
    fixture,
):
    """AI: Class mode contains-matches by scanning every class name, but exact-matches
    by resolving the name as a symbol (an O(1) image lookup, the same primitive Browse
    Class uses) - so the exact path answers without scanning at all."""
    fixture.simulate_login()

    def classes_for_pattern(pattern, should_stop=None):
        if pattern == "Order":
            return ["Order", "OrderLine"]
        return []

    fixture.mock_browser.find_classes.side_effect = classes_for_pattern

    def class_named(class_name):
        if class_name == "Order":
            return ["Order"]
        return []

    fixture.mock_browser.existing_class_named.side_effect = class_named

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="class",
            search_query="Order",
            run_search=True,
            match_mode="contains",
        )

    assert find_result_labels(dialog) == ["Order", "OrderLine"]
    dialog.match_mode.set("exact")
    dialog.find_text()
    assert find_result_labels(dialog) == ["Order"]
    # AI: The contains search scanned once; the exact search resolved the symbol and
    # never scanned, so find_classes was not called a second time.
    fixture.mock_browser.find_classes.assert_called_once()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_scan_returns_the_partial_results_gathered_before_a_stop(fixture):
    """AI: The scan is cooperative: when the stop flag rises it returns exactly what it has
    gathered so far, rather than the full result set. This is the worker-side half of Stop,
    tested deterministically through the stop predicate without involving a real thread."""
    fixture.simulate_login()
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    def classes_for_pattern(pattern, should_stop=None):
        class_names = []
        for class_index in range(10):
            if should_stop is not None and should_stop():
                return class_names
            class_names.append("Order%s" % class_index)
        return class_names

    fixture.mock_browser.find_classes.side_effect = classes_for_pattern
    stop_after_two = {"checks": 0}

    def should_stop():
        stop_after_two["checks"] = stop_after_two["checks"] + 1
        return stop_after_two["checks"] > 2

    payload = dialog.gather_find_results(
        {"search_type": "class", "match_mode": "contains", "reference_target": "class"},
        "Order",
        should_stop,
    )

    assert payload["class_names"] == ["Order0", "Order1"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_renders_partial_results_and_a_stopped_status_when_interrupted(fixture):
    """AI: The UI-side half of Stop: an interrupted find renders whatever the scan gathered
    and tells the user these are partial results, so a stopped search is never mistaken for
    a complete (empty-or-short) one."""
    fixture.simulate_login()
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.finish_find_with_partial(
        {"kind": "class", "class_names": ["Order0", "Order1", "Order2"]}
    )

    assert dialog.status_var.get() == "Find stopped. Showing partial results."
    assert find_result_labels(dialog) == ["Order0", "Order1", "Order2"]
    assert str(dialog.find_buttons[0].cget("state")) == tk.NORMAL
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_interrupted_with_no_partial_results_clears_and_reports_stopped(fixture):
    """AI: When a forceful break aborts a single long call there is nothing partial to keep,
    so the results clear and the status still reports the search was stopped -- one consistent
    Stop semantics whether or not partial results exist."""
    fixture.simulate_login()
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.finish_find_with_partial(None)

    assert dialog.status_var.get() == "Find stopped. Showing partial results."
    assert find_result_labels(dialog) == []
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_method_mode_supports_contains_and_exact_matching(
    fixture,
):
    """AI: Method mode should search selectors for contains and implementors for exact."""
    fixture.simulate_login()
    fixture.mock_browser.find_selectors.return_value = ["subtotal", "total"]
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "Order", "show_instance_side": False},
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="method",
            search_query="total",
            run_search=True,
            match_mode="contains",
        )

    assert find_result_labels(dialog) == ["subtotal", "total"]
    dialog.match_mode.set("exact")
    dialog.find_text()
    assert find_result_labels(dialog) == [
        "Order class>>total",
        "OrderLine>>total",
    ]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_method_search_shows_class_and_method_category_columns(fixture):
    """AI: An implementor search is a method listing, so each result row carries
    the Class, Class Category, Method and Method Category that an IDE user needs
    to tell overlapping implementors apart."""
    fixture.simulate_login()
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="method",
            search_query="total",
            run_search=True,
            match_mode="exact",
        )

    assert tuple(dialog.results_tree["columns"]) == (
        "ClassCategory",
        "Method",
        "MethodCategory",
    )
    iid = find_result_iid_for_label(dialog, "OrderLine>>total")
    assert dialog.results_tree.item(iid, "text") == "OrderLine"
    assert dialog.results_tree.set(iid, "ClassCategory") == "Kernel"
    assert dialog.results_tree.set(iid, "Method") == "total"
    assert dialog.results_tree.set(iid, "MethodCategory") == "accessing"
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_nests_override_under_the_implementor_it_overrides(fixture):
    """AI: When a subclass reimplements a selector, its implementor is nested
    under the inherited implementor it overrides, so the inheritance relationship
    between implementors is visible directly in the result list."""
    fixture.simulate_login()
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "Order", "show_instance_side": True},
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="method",
            search_query="total",
            run_search=True,
            match_mode="exact",
        )

    superclass_iid = find_result_iid_for_label(dialog, "Order>>total")
    override_iid = find_result_iid_for_label(dialog, "OrderLine>>total")
    assert dialog.results_tree.parent(superclass_iid) == ""
    assert dialog.results_tree.parent(override_iid) == superclass_iid
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_class_search_shows_category_column_and_nests_subclasses(fixture):
    """AI: A class search lists classes with their class category, and a subclass
    is nested under the superclass it inherits from."""
    fixture.simulate_login()

    def classes_for_pattern(pattern, should_stop=None):
        return ["Order", "OrderLine"]

    fixture.mock_browser.find_classes.side_effect = classes_for_pattern

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="class",
            search_query="Order",
            run_search=True,
            match_mode="contains",
        )

    assert tuple(dialog.results_tree["columns"]) == ("ClassCategory",)
    superclass_iid = find_result_iid_for_label(dialog, "Order")
    subclass_iid = find_result_iid_for_label(dialog, "OrderLine")
    assert dialog.results_tree.set(superclass_iid, "ClassCategory") == "Kernel"
    assert dialog.results_tree.parent(subclass_iid) == superclass_iid
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_selector_contains_search_shows_only_a_method_column(fixture):
    """AI: A 'contains' selector search yields bare selectors with no owning
    class, so it shows a single Method column and no inheritance nesting."""
    fixture.simulate_login()
    fixture.mock_browser.find_selectors.return_value = ["subtotal", "total"]

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="method",
            search_query="total",
            run_search=True,
            match_mode="contains",
        )

    assert tuple(dialog.results_tree["columns"]) == ()
    assert find_result_labels(dialog) == ["subtotal", "total"]
    top_level_iids = dialog.results_tree.get_children("")
    assert all(
        dialog.results_tree.get_children(iid) == () for iid in top_level_iids
    )
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_intent_selection_drives_legacy_config(fixture):
    """AI: The single search intent (chosen via the category tabs/variants) drives the
    hidden search_type/match_mode/reference_target. Opening with method/contains selects
    the 'Selector containing' intent; choosing the 'Implementors' variant flips the
    derived config to method/exact."""
    fixture.simulate_login()
    fixture.mock_browser.find_selectors.return_value = ["subtotal", "total"]
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="method",
            search_query="total",
            run_search=True,
            match_mode="contains",
        )

    assert dialog.search_intent.get() == "selector_contains"
    assert dialog.search_type.get() == "method"
    assert dialog.match_mode.get() == "contains"

    dialog.search_intent.set("implementors")
    dialog.apply_search_intent()
    dialog.find_text()

    assert dialog.search_type.get() == "method"
    assert dialog.match_mode.get() == "exact"
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_method_contains_double_click_pivots_to_exact_search_in_place(fixture):
    """AI: Double-clicking a method selector in contains mode should pivot in-place to exact implementors."""
    fixture.simulate_login()
    fixture.mock_browser.find_selectors.return_value = ["subtotal", "total"]
    fixture.mock_browser.find_implementors.return_value = [
        {"class_name": "OrderLine", "show_instance_side": True},
    ]

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="method",
            search_query="tot",
            run_search=True,
            match_mode="contains",
        )

    with patch.object(fixture.app, "open_implementors_dialog") as open_implementors:
        select_find_result(dialog, "total")
        dialog.on_result_double_click(None)

    open_implementors.assert_not_called()
    fixture.mock_browser.find_implementors.assert_called_once_with("total")
    assert dialog.winfo_exists() == 1
    assert dialog.match_mode.get() == "exact"
    assert dialog.find_entry.get() == "total"
    assert find_result_labels(dialog) == ["OrderLine>>total"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_reference_method_search_is_always_exact(
    fixture,
):
    """AI: Method reference search should force exact matching; narrow tracing requires a known source class."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            }
        ],
        "total_count": 1,
        "returned_count": 1,
    }

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="contains",
            reference_target="method",
        )

    assert dialog.match_mode.get() == "exact"
    assert dialog.search_intent.get() == "method_references"
    fixture.mock_browser.find_selectors.assert_not_called()
    fixture.mock_browser.find_senders.assert_called_once_with(
        "total",
        include_category_details=True,
    )
    assert str(dialog.narrow_button.cget("state")) == tk.DISABLED
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_reference_class_search_is_always_exact(
    fixture,
):
    """AI: Class reference search should force exact matching."""
    fixture.simulate_login()
    fixture.mock_browser.find_class_references.return_value = {
        "references": [
            {
                "class_name": "OrderBuilder",
                "show_instance_side": True,
                "method_selector": "fromOrder:",
            }
        ],
        "total_count": 1,
        "returned_count": 1,
    }

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="reference",
            search_query="Or",
            run_search=True,
            match_mode="contains",
            reference_target="class",
        )

    assert dialog.match_mode.get() == "exact"
    assert dialog.search_intent.get() == "class_references"
    fixture.mock_browser.find_classes.assert_not_called()
    fixture.mock_browser.find_class_references.assert_called_once_with("Or")
    assert find_result_labels(dialog) == ["OrderBuilder>>fromOrder:"]
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_each_search_intent_derives_its_legacy_config(fixture):
    """AI: Every named intent must translate to the correct hidden
    search_type/match_mode/reference_target triple the engine reads — this is the
    contract that lets one intent control replace the three former radio groups."""
    fixture.simulate_login()
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    expected = {
        "class_contains": ("class", "contains", "class"),
        "class_exact": ("class", "exact", "class"),
        "class_references": ("reference", "exact", "class"),
        "implementors": ("method", "exact", "class"),
        "selector_contains": ("method", "contains", "class"),
        "method_references": ("reference", "exact", "method"),
        "instvar_references": ("reference", "exact", "instvar"),
        "classvar_references": ("reference", "exact", "classvar"),
    }
    for intent, (search_type, match_mode, reference_target) in expected.items():
        dialog.search_intent.set(intent)
        dialog.apply_search_intent()
        assert dialog.search_type.get() == search_type
        assert dialog.match_mode.get() == match_mode
        assert dialog.reference_target.get() == reference_target
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_switching_category_tab_falls_back_to_first_variant(fixture):
    """AI: Moving to a category whose variants do not include the current intent must
    fall back to that category's first variant; staying within the category keeps the
    current intent. (Tk's notebook selection is not observable headless, so the fallback
    rule is verified directly and then applied through apply_search_intent.)"""
    fixture.simulate_login()
    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    variable_tab_index = dialog.intent_to_tab_index["instvar_references"]
    # AI: Coming from a Class-tab intent, switching to Variable picks its first variant.
    assert dialog.default_intent_for_tab(variable_tab_index) == "instvar_references"
    # AI: Already on a Variable-tab intent, switching within the tab keeps it.
    dialog.search_intent.set("classvar_references")
    assert dialog.default_intent_for_tab(variable_tab_index) == "classvar_references"

    # AI: Applying a variable intent derives the target and reveals the owning-class
    # entry (checked via the grid manager, which is reliable headless unlike ismapped).
    dialog.search_intent.set("instvar_references")
    dialog.apply_search_intent()
    assert dialog.reference_target.get() == "instvar"
    assert dialog.instvar_class_entry.grid_info() != {}
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_open_find_dialog_for_classvar_selects_class_var_intent(fixture):
    """AI: A programmatic class-var open must select the Class var intent (Variable
    category) so the visible control reflects the search being run."""
    fixture.simulate_login()
    fixture.mock_browser.find_classvar_references.return_value = {
        "references": [], "total_count": 0, "returned_count": 0,
    }
    with patch.object(FindPane, "wait_visibility"):
        dialog = fixture.app.open_find_dialog_for_classvar("Date", "MonthNames")

    assert dialog.search_intent.get() == "classvar_references"
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_open_find_dialog_for_class_prefills_and_executes_reference_search(
    fixture,
):
    """AI: Opening class references should run class-reference lookup and show matching methods."""
    fixture.simulate_login()
    fixture.mock_browser.find_class_references.return_value = {
        "references": [
            {
                "class_name": "Order",
                "show_instance_side": True,
                "method_selector": "addLine:",
            },
            {
                "class_name": "Order",
                "show_instance_side": False,
                "method_selector": "defaultLineClass",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }

    with patch.object(fixture.app, "begin_foreground_activity") as begin_activity:
        with patch.object(fixture.app, "end_foreground_activity") as end_activity:
            with patch.object(FindPane, "wait_visibility"):
                dialog = fixture.app.open_find_dialog_for_class("OrderLine")

    assert dialog is not None
    assert dialog.search_type.get() == "reference"
    assert dialog.reference_target.get() == "class"
    assert dialog.match_mode.get() == "exact"
    assert dialog.find_entry.get() == "OrderLine"
    begin_activity.assert_called_once_with(
        "Finding references to class OrderLine...",
    )
    end_activity.assert_called_once_with()
    assert find_result_labels(dialog) == [
        "Order class>>defaultLineClass",
        "Order>>addLine:",
    ]
    dialog.destroy()

@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_pins_class_reference_method(fixture):
    """AI: Double-clicking a class-reference match (a method) pins that method
    in the editor rather than navigating the browser to it."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        'Kernel'
    )
    fixture.mock_browser.get_method_category.return_value = 'accessing'

    with patch.object(FindPane, 'wait_visibility'):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.search_type.set('reference')
    dialog.reference_target.set('class')
    dialog.match_mode.set('exact')
    dialog.populate_navigation_results([('Order', False, 'defaultLineClass')])

    shown = Mock()
    pinned = Mock()
    fixture.app.event_queue.subscribe('MethodDisplayRequested', shown)
    fixture.app.event_queue.subscribe('MethodTabPinRequested', pinned)
    selection_before = fixture.session_record.selected_class

    select_find_result(dialog, 'Order class>>defaultLineClass')
    dialog.on_result_double_click(None)
    fixture.app.update()

    shown.assert_called_once_with(('Order', False, 'defaultLineClass'), origin=ANY)
    pinned.assert_called_once()
    assert fixture.session_record.selected_class == selection_before


@with_fixtures(SwordfishAppFixture)
def test_open_find_dialog_for_instvar_prefills_controls_and_runs_search(fixture):
    """AI: open_find_dialog_for_instvar should open the Find pane in reference/instvar
    mode with class and inst var name pre-filled, and immediately run the search so
    results appear without the user clicking Find."""
    fixture.simulate_login()
    fixture.mock_browser.find_instvar_references.return_value = {
        'references': [
            {
                'class_name': 'Amount',
                'show_instance_side': True,
                'method_selector': 'printOn:',
                'method_category': 'printing',
            }
        ],
        'total_count': 1,
        'returned_count': 1,
    }
    fixture.mock_browser.get_method_category.return_value = 'printing'

    with patch.object(FindPane, 'wait_visibility'):
        dialog = fixture.app.open_find_dialog_for_instvar('Amount', 'currency')

    assert dialog is not None
    assert dialog.search_type.get() == 'reference'
    assert dialog.reference_target.get() == 'instvar'
    assert dialog.match_mode.get() == 'exact'
    assert dialog.find_entry.get() == 'currency'
    assert dialog.instvar_class_entry.get() == 'Amount'
    fixture.mock_browser.find_instvar_references.assert_called_once_with('Amount', 'currency')
    assert find_result_labels(dialog) == ['Amount>>printOn:']
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_open_find_dialog_for_classvar_runs_classvar_search(fixture):
    """AI: open_find_dialog_for_classvar must open the Find pane in reference mode with
    the new 'classvar' target and run find_classvar_references (NOT the inst-var
    search, which cannot see class variables), pre-filling class and variable name."""
    fixture.simulate_login()
    fixture.mock_browser.find_classvar_references.return_value = {
        'references': [
            {
                'class_name': 'Date',
                'show_instance_side': True,
                'method_selector': 'monthName',
                'method_category': 'accessing',
            }
        ],
        'total_count': 1,
        'returned_count': 1,
    }
    fixture.mock_browser.get_method_category.return_value = 'accessing'

    with patch.object(FindPane, 'wait_visibility'):
        dialog = fixture.app.open_find_dialog_for_classvar('Date', 'MonthNames')

    assert dialog is not None
    assert dialog.search_type.get() == 'reference'
    assert dialog.reference_target.get() == 'classvar'
    assert dialog.match_mode.get() == 'exact'
    assert dialog.find_entry.get() == 'MonthNames'
    assert dialog.instvar_class_entry.get() == 'Date'
    fixture.mock_browser.find_classvar_references.assert_called_once_with('Date', 'MonthNames')
    fixture.mock_browser.find_instvar_references.assert_not_called()
    assert find_result_labels(dialog) == ['Date>>monthName']
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_instvar_result_publishes_highlight_event(fixture):
    """AI: Double-clicking an inst-var reference result must publish both
    MethodDisplayRequested (to open the tab) and InstVarHighlightRequested (to
    highlight all occurrences of the inst var in the opened method)."""
    fixture.simulate_login()
    fixture.mock_browser.get_method_category.return_value = 'accessing'
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        'Kernel'
    )

    with patch.object(FindPane, 'wait_visibility'):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.search_type.set('reference')
    dialog.reference_target.set('instvar')
    dialog.populate_instvar_navigation_results([('Amount', True, 'printOn:')], 'currency')

    highlight_handler = Mock()
    fixture.app.event_queue.subscribe('InstVarHighlightRequested', highlight_handler)

    select_find_result(dialog, 'Amount>>printOn:')
    dialog.on_result_double_click(None)
    fixture.app.update()

    highlight_handler.assert_called_once_with('currency', origin=ANY)
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_peek_publishes_highlight_for_reference_result(fixture):
    """AI: Single-click peek must mark where the searched term occurs, the same cue as
    opening the method, so a glance at a result shows the references in context."""
    fixture.simulate_login()
    fixture.mock_browser.get_method_category.return_value = 'accessing'
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        'Kernel'
    )

    with patch.object(FindPane, 'wait_visibility'):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.search_type.set('reference')
    dialog.reference_target.set('instvar')
    dialog.populate_instvar_navigation_results([('Amount', True, 'printOn:')], 'currency')

    highlight_handler = Mock()
    fixture.app.event_queue.subscribe('InstVarHighlightRequested', highlight_handler)

    select_find_result(dialog, 'Amount>>printOn:')
    dialog.peek_selected_result(None)
    fixture.app.update()

    highlight_handler.assert_called_once_with('currency', origin=ANY)
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_result_highlights_the_sent_selector(fixture):
    """AI: To be consistent with variable searches, a senders result highlights where the
    selector is sent: the row carries the selector as its highlight term, so opening the
    method marks the send."""
    fixture.simulate_login()
    fixture.mock_browser.get_method_category.return_value = 'calculating'
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        'Kernel'
    )

    with patch.object(FindPane, 'wait_visibility'):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.search_type.set('reference')
    dialog.reference_target.set('method')
    dialog.populate_navigation_results(
        [('OrderLine', True, 'recalculate')], highlight_term='total'
    )

    highlight_handler = Mock()
    fixture.app.event_queue.subscribe('InstVarHighlightRequested', highlight_handler)

    select_find_result(dialog, 'OrderLine>>recalculate')
    dialog.on_result_double_click(None)
    fixture.app.update()

    highlight_handler.assert_called_once_with('total', origin=ANY)
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_result_without_highlight_term_does_not_publish_highlight_event(fixture):
    """AI: A result row carrying no highlight term (e.g. an implementors match) must NOT
    publish a highlight event — the highlight is only for reference-style searches."""
    fixture.simulate_login()
    fixture.mock_browser.get_method_category.return_value = 'accessing'
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        'Kernel'
    )

    with patch.object(FindPane, 'wait_visibility'):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.search_type.set('reference')
    dialog.reference_target.set('class')
    dialog.populate_navigation_results([('Amount', True, 'printOn:')])

    highlight_handler = Mock()
    fixture.app.event_queue.subscribe('InstVarHighlightRequested', highlight_handler)

    select_find_result(dialog, 'Amount>>printOn:')
    dialog.on_result_double_click(None)
    fixture.app.update()

    highlight_handler.assert_not_called()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_navigates_browser_to_selected_class(fixture):
    """Double-clicking a class name in the FindPane results navigates the
    browser to that class by selecting its package and class in the columns."""
    fixture.simulate_login()
    fixture.app.browser_tab.packages_widget.browse_mode_var.set("categories")
    fixture.app.browser_tab.packages_widget.change_browse_mode()
    fixture.app.update()
    # AI: jump_to_class resolves the class symbol to find its package via
    # gemstone_session.resolve_symbol(name).category().to_py
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.display_class_results(["OrderLine"])
    select_find_result(dialog, "OrderLine")
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_class == "OrderLine"
    assert fixture.session_record.selected_package == "Kernel"


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_in_dictionary_mode_updates_dictionary_and_class_lists(
    fixture,
):
    """AI: In dictionary browse mode, selecting a class from Find should switch dictionary/class panes to the class's dictionary and selected class."""
    fixture.simulate_login()
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals", "Kernel"]

    def classes_for_dictionary(dictionary_name):
        if dictionary_name == "UserGlobals":
            return ["LegacyClass"]
        if dictionary_name == "Kernel":
            return ["OrderLine", "Order"]
        return []

    fixture.mock_browser.list_classes_in_dictionary.side_effect = classes_for_dictionary
    fixture.mock_browser.dictionary_name_for_class.return_value = "Kernel"
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    fixture.session_record.select_class_category("UserGlobals")
    fixture.app.event_queue.publish("SelectedClassChanged")
    fixture.app.update()

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.display_class_results(["OrderLine"])
    select_find_result(dialog, "OrderLine")
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_dictionary == "Kernel"
    assert fixture.session_record.selected_class == "OrderLine"
    dictionary_listbox = (
        fixture.app.browser_tab.packages_widget.selection_list.selection_listbox
    )
    selected_dictionary_index = dictionary_listbox.curselection()[0]
    assert dictionary_listbox.get(selected_dictionary_index) == "Kernel"
    class_listbox = (
        fixture.app.browser_tab.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine", "Order"]
    selected_class_index = class_listbox.curselection()[0]
    assert class_listbox.get(selected_class_index) == "OrderLine"


@with_fixtures(SwordfishAppFixture)
def test_find_dialog_double_click_in_dictionary_mode_uses_class_membership_not_symbol_category(
    fixture,
):
    """AI: In dictionary mode, Find navigation should choose the dictionary that contains the class even if class category metadata differs."""
    fixture.simulate_login()
    fixture.mock_browser.list_dictionaries.return_value = ["UserGlobals", "Kernel"]

    def classes_for_dictionary(dictionary_name):
        if dictionary_name == "UserGlobals":
            return ["OrderLine", "LegacyClass"]
        if dictionary_name == "Kernel":
            return ["Order", "Collection"]
        return []

    fixture.mock_browser.list_classes_in_dictionary.side_effect = classes_for_dictionary
    fixture.mock_browser.dictionary_name_for_class.return_value = "UserGlobals"
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        "Kernel"
    )

    fixture.session_record.select_class_category("Kernel")
    fixture.app.event_queue.publish("SelectedClassChanged")
    fixture.app.update()

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(fixture.app, fixture.app)

    dialog.display_class_results(["OrderLine"])
    select_find_result(dialog, "OrderLine")
    dialog.on_result_double_click(None)
    fixture.app.update()

    assert fixture.session_record.selected_dictionary == "UserGlobals"
    assert fixture.session_record.selected_class == "OrderLine"
    class_listbox = (
        fixture.app.browser_tab.classes_widget.selection_list.selection_listbox
    )
    assert list(class_listbox.get(0, "end")) == ["OrderLine", "LegacyClass"]
    selected_class_index = class_listbox.curselection()[0]
    assert class_listbox.get(selected_class_index) == "OrderLine"


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_method_search_populates_result_list(fixture):
    """Searching for senders in the FindPane shows sender methods with class/side labels."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
            {
                "class_name": "Order",
                "show_instance_side": False,
                "method_selector": "default",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }

    with patch.object(FindPane, "wait_visibility"):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type="reference",
            search_query="total",
            run_search=True,
            match_mode="exact",
            reference_target="method",
        )

    results = find_result_labels(dialog)
    assert results == ["Order class>>default", "OrderLine>>recalculateTotal"]
    dialog.destroy()

@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_double_click_pins_the_method(fixture):
    """AI: Double-clicking a sender (method) result pins that method in the
    editor -- preview, then promote the tab to permanent, like the browser's
    method list -- without moving the browser's column selection."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        'Kernel'
    )
    fixture.mock_browser.get_method_category.return_value = 'accessing'
    fixture.mock_browser.find_senders.return_value = {
        'senders': [
            {
                'class_name': 'OrderLine',
                'show_instance_side': True,
                'method_selector': 'recalculateTotal',
            },
        ],
        'total_count': 1,
        'returned_count': 1,
    }

    with patch.object(FindPane, 'wait_visibility'):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type='reference',
            search_query='total',
            run_search=True,
            match_mode='exact',
            reference_target='method',
        )

    shown = Mock()
    pinned = Mock()
    fixture.app.event_queue.subscribe('MethodDisplayRequested', shown)
    fixture.app.event_queue.subscribe('MethodTabPinRequested', pinned)
    selection_before = fixture.session_record.selected_class

    select_find_result(dialog, 'OrderLine>>recalculateTotal')
    dialog.on_result_double_click(None)
    fixture.app.update()

    shown.assert_called_once_with(
        ('OrderLine', True, 'recalculateTotal'), origin=ANY
    )
    pinned.assert_called_once()
    assert fixture.session_record.selected_class == selection_before


@with_fixtures(SwordfishAppFixture)
def test_single_clicking_a_find_method_result_peeks_it_without_moving_the_browser(
    fixture,
):
    """AI: Single-clicking a method result in Find asks the editor to display
    that method (via MethodDisplayRequested) but leaves the browser's column
    selection untouched -- an editor-only peek, unlike the double-click that
    navigates the browser to the method."""
    fixture.simulate_login()
    fixture.mock_gemstone_session.resolve_symbol.return_value.category.return_value.to_py = (
        'Kernel'
    )
    fixture.mock_browser.get_method_category.return_value = 'accessing'
    fixture.mock_browser.find_senders.return_value = {
        'senders': [
            {
                'class_name': 'OrderLine',
                'show_instance_side': True,
                'method_selector': 'recalculateTotal',
            },
        ],
        'total_count': 1,
        'returned_count': 1,
    }

    with patch.object(FindPane, 'wait_visibility'):
        dialog = FindPane(
            fixture.app,
            fixture.app,
            search_type='reference',
            search_query='total',
            run_search=True,
            match_mode='exact',
            reference_target='method',
        )

    selection_before_peek = fixture.session_record.selected_class
    peeked_method = Mock()
    fixture.app.event_queue.subscribe('MethodDisplayRequested', peeked_method)

    select_find_result(dialog, 'OrderLine>>recalculateTotal')
    dialog.peek_selected_result(None)
    fixture.app.update()

    peeked_method.assert_called_once_with(
        ('OrderLine', True, 'recalculateTotal'), origin=dialog
    )
    assert fixture.session_record.selected_class == selection_before_peek


@with_fixtures(SwordfishAppFixture)
def test_opening_find_twice_reuses_one_pane(fixture):
    """AI: Find is a single reusable pane -- opening it a second time replaces
    its contents in place rather than splitting another group beside it."""
    fixture.simulate_login()

    fixture.app.open_find_dialog()
    fixture.app.open_find_dialog()

    assert len(fixture.app.pane_area.groups) == 2


@with_fixtures(SwordfishAppFixture)
def test_main_window_centre_is_a_splittable_pane_area(fixture):
    """AI: The IDE centre is a PaneArea (a splittable arrangement of tab
    groups). Today's tools live in its primary group -- self.notebook points at
    that group -- so the familiar top-level tab strip is unchanged, while the
    area can later be split to place a tool beside them."""
    fixture.simulate_login()

    assert isinstance(fixture.app.pane_area, PaneArea)
    assert fixture.app.notebook is fixture.app.pane_area.group(0)


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_filters_to_observed_senders(fixture):
    """AI: Narrowing sender results with tracing should keep only observed runtime callers."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
            {
                "class_name": "Order",
                "show_instance_side": False,
                "method_selector": "default",
            },
        ],
        "total_count": 2,
        "returned_count": 2,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        "candidate_test_count": 1,
        "candidate_tests": [
            {
                "test_case_class_name": "OrderLineTest",
                "test_method_selector": "testRecalculateTotal",
                "depth": 1,
                "reached_from_selector": "recalculateTotal",
            },
        ],
        "visited_selector_count": 3,
        "sender_search_truncated": False,
        "selector_limit_reached": False,
        "elapsed_limit_reached": False,
    }
    fixture.mock_browser.run_test_method.return_value = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.trace_selector.return_value = {
        "method_name": "total",
        "total_sender_count": 2,
        "targeted_sender_count": 2,
        "traced_sender_count": 2,
        "skipped_sender_count": 0,
        "traced_senders": [],
        "skipped_senders": [],
    }
    fixture.mock_browser.observed_senders_for_selector.return_value = {
        "total_count": 1,
        "returned_count": 1,
        "total_observed_calls": 2,
        "observed_senders": [
            {
                "caller_class_name": "OrderLine",
                "caller_show_instance_side": True,
                "caller_method_selector": "recalculateTotal",
                "method_selector": "total",
                "observed_count": 2,
            },
        ],
    }
    original_set_ready_state = CoveringTestsSearchDialog.set_ready_state

    def set_ready_then_run(dialog, timed_out=False, summary_message=""):
        original_set_ready_state(
            dialog,
            timed_out=timed_out,
            summary_message=summary_message,
        )
        if dialog.selected_tests is None:
            dialog.run_selected_tests()

    with patch.object(FindPane, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_ready_state",
                autospec=True,
                side_effect=set_ready_then_run,
            ):
                dialog = FindPane(
                    fixture.app,
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    results = find_result_labels(dialog)
    assert results == ["OrderLine>>recalculateTotal"]
    fixture.mock_browser.sender_test_plan_for_selector.assert_called_once_with(
        "total",
        2,
        500,
        200,
        200,
        max_elapsed_ms=120000,
        should_stop=ANY,
        on_candidate_test=ANY,
    )
    fixture.mock_browser.trace_selector.assert_called_once_with(
        "total",
        max_results=250,
    )
    fixture.mock_browser.run_test_method.assert_called_once_with(
        "OrderLineTest",
        "testRecalculateTotal",
    )
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_stops_when_no_candidate_tests(
    fixture,
):
    """AI: If discovery yields no candidate tests, narrowing should not proceed to tracing."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
        ],
        "total_count": 1,
        "returned_count": 1,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        "candidate_test_count": 0,
        "candidate_tests": [],
        "visited_selector_count": 1,
        "elapsed_limit_reached": False,
        "sender_search_truncated": True,
    }
    original_set_ready_state = CoveringTestsSearchDialog.set_ready_state

    def set_ready_then_cancel(dialog, timed_out=False, summary_message=""):
        original_set_ready_state(
            dialog,
            timed_out=timed_out,
            summary_message=summary_message,
        )
        dialog.cancel_dialog()

    with patch.object(FindPane, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_ready_state",
                autospec=True,
                side_effect=set_ready_then_cancel,
            ):
                dialog = FindPane(
                    fixture.app,
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    fixture.mock_browser.trace_selector.assert_not_called()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_can_search_more_after_timeout(
    fixture,
):
    """AI: When timed out, choosing Search More should continue test discovery and merge newly found candidates."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
        ],
        "total_count": 1,
        "returned_count": 1,
    }
    fixture.mock_browser.sender_test_plan_for_selector.side_effect = [
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "OrderLineTest",
                    "test_method_selector": "testRecalculateTotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateTotal",
                },
            ],
            "sender_edges": [
                {
                    "from_selector": "total",
                    "to_class_name": "OrderLine",
                    "to_method_selector": "recalculateTotal",
                    "to_show_instance_side": True,
                    "depth": 1,
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": True,
            "elapsed_ms": 120000,
            "max_elapsed_ms": 120000,
            "stopped_by_user": False,
        },
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "InvoiceTest",
                    "test_method_selector": "testRecalculateSubtotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateSubtotal",
                },
            ],
            "sender_edges": [
                {
                    "from_selector": "total",
                    "to_class_name": "Invoice",
                    "to_method_selector": "recalculateSubtotal",
                    "to_show_instance_side": True,
                    "depth": 1,
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": False,
            "elapsed_ms": 100,
            "max_elapsed_ms": 120000,
            "stopped_by_user": False,
        },
    ]
    fixture.mock_browser.run_test_method.return_value = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.trace_selector.return_value = {
        "method_name": "total",
        "total_sender_count": 1,
        "targeted_sender_count": 1,
        "traced_sender_count": 1,
        "skipped_sender_count": 0,
        "traced_senders": [],
        "skipped_senders": [],
    }
    fixture.mock_browser.observed_senders_for_selector.return_value = {
        "total_count": 1,
        "returned_count": 1,
        "total_observed_calls": 1,
        "observed_senders": [
            {
                "caller_class_name": "OrderLine",
                "caller_show_instance_side": True,
                "caller_method_selector": "recalculateTotal",
                "method_selector": "total",
                "observed_count": 1,
            },
        ],
    }

    original_set_ready_state = CoveringTestsSearchDialog.set_ready_state

    def set_ready_then_search_more_or_run(
        dialog,
        timed_out=False,
        summary_message="",
    ):
        original_set_ready_state(
            dialog,
            timed_out=timed_out,
            summary_message=summary_message,
        )
        if timed_out:
            dialog.request_search_further()
        if not timed_out:
            dialog.run_selected_tests()

    with patch.object(FindPane, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_ready_state",
                autospec=True,
                side_effect=set_ready_then_search_more_or_run,
            ):
                dialog = FindPane(
                    fixture.app,
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    assert fixture.mock_browser.sender_test_plan_for_selector.call_count == 2
    assert fixture.mock_browser.run_test_method.call_count == 2
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_stop_search_cancels_narrowing_instead_of_using_partial_results(
    fixture,
):
    """AI: Stopping discovery should cancel narrowing and never continue with partially found tests."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.return_value = {
        "senders": [
            {
                "class_name": "OrderLine",
                "show_instance_side": True,
                "method_selector": "recalculateTotal",
            },
        ],
        "total_count": 1,
        "returned_count": 1,
    }
    fixture.mock_browser.sender_test_plan_for_selector.return_value = {
        "candidate_test_count": 1,
        "candidate_tests": [
            {
                "test_case_class_name": "OrderLineTest",
                "test_method_selector": "testRecalculateTotal",
                "depth": 1,
                "reached_from_selector": "recalculateTotal",
            },
        ],
        "visited_selector_count": 1,
        "sender_search_truncated": False,
        "selector_limit_reached": False,
        "elapsed_limit_reached": False,
        "stopped_by_user": False,
    }
    original_set_searching_state = CoveringTestsSearchDialog.set_searching_state

    def set_searching_then_stop(dialog):
        original_set_searching_state(dialog)
        dialog.request_stop_search()

    with patch.object(FindPane, "wait_visibility"):
        with patch.object(CoveringTestsSearchDialog, "wait_visibility"):
            with patch.object(
                CoveringTestsSearchDialog,
                "set_searching_state",
                autospec=True,
                side_effect=set_searching_then_stop,
            ):
                dialog = FindPane(
                    fixture.app,
                    fixture.app,
                    search_type="reference",
                    search_query="total",
                    run_search=True,
                    match_mode="exact",
                    reference_target="method",
                )
                dialog.narrow_senders_with_tracing()

    assert dialog.status_var.get() == "Test discovery stopped."
    fixture.mock_browser.trace_selector.assert_not_called()
    dialog.destroy()


@with_fixtures(SwordfishAppFixture)
def test_senders_dialog_narrow_with_tracing_reloads_static_senders_after_selector_change(
    fixture,
):
    """AI: Changing selector after tracing should refresh static sender candidates before narrowing again."""
    fixture.simulate_login()
    fixture.mock_browser.find_senders.side_effect = [
        {
            "senders": [
                {
                    "class_name": "OrderLine",
                    "show_instance_side": True,
                    "method_selector": "recalculateTotal",
                },
            ],
            "total_count": 1,
            "returned_count": 1,
        },
        {
            "senders": [
                {
                    "class_name": "Invoice",
                    "show_instance_side": True,
                    "method_selector": "recalculateSubtotal",
                },
            ],
            "total_count": 1,
            "returned_count": 1,
        },
    ]
    fixture.mock_browser.sender_test_plan_for_selector.side_effect = [
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "OrderLineTest",
                    "test_method_selector": "testRecalculateTotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateTotal",
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": False,
        },
        {
            "candidate_test_count": 1,
            "candidate_tests": [
                {
                    "test_case_class_name": "InvoiceTest",
                    "test_method_selector": "testRecalculateSubtotal",
                    "depth": 1,
                    "reached_from_selector": "recalculateSubtotal",
                },
            ],
            "visited_selector_count": 1,
            "sender_search_truncated": False,
            "selector_limit_reached": False,
            "elapsed_limit_reached": False,
        },
    ]
    fixture.mock_browser.run_test_method.return_value = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.trace_selector.side_effect = [
        {
            "method_name": "total",
            "total_sender_count": 1,
            "targeted_sender_count": 1,
            "traced_sender_count": 1,
            "skipped_sender_count": 0,
            "traced_senders": [],
            "skipped_senders": [],
        },
        {
            "method_name": "subtotal",
            "total_sender_count": 1,
            "targeted_sender_count": 1,
            "traced_sender_count": 1,
            "skipped_sender_count": 0,
            "traced_senders": [],
            "skipped_senders": [],
        },
    ]
    fixture.mock_browser.observed_senders_for_selector.side_effect = [
        {
            "total_count": 1,
            "returned_count": 1,
            "total_observed_calls": 1,
            "observed_senders": [
                {
                    "caller_class_name": "OrderLine",
                    "caller_show_instance_side": True,
                    "caller_method_selector": "recalculateTotal",
                    "method_selector": "total",
                    "observed_count": 1,
                },
            ],
        },
        {
            "total_count": 1,
            "returned_count": 1,
            "total_observed_calls": 1,
            "observed_senders": [
                {
                    "caller_class_name": "Invoice",
                    "caller_show_instance_side": True,
                    "caller_method_selector": "recalculateSubtotal",
                    "method_selector": "subtotal",
                    "observed_count": 1,
                },
            ],
        },
    ]

    selected_tests_by_method = {
        "total": [
            {
                "test_case_class_name": "OrderLineTest",
                "test_method_selector": "testRecalculateTotal",
                "depth": 1,
                "reached_from_selector": "recalculateTotal",
            },
        ],
        "subtotal": [
            {
                "test_case_class_name": "InvoiceTest",
                "test_method_selector": "testRecalculateSubtotal",
                "depth": 1,
                "reached_from_selector": "recalculateSubtotal",
            },
        ],
    }

    def selected_tests_for_method(method_name):
        return selected_tests_by_method[method_name]

    with patch.object(FindPane, "wait_visibility"):
        with patch.object(
            FindPane,
            "choose_tests_for_tracing",
            side_effect=selected_tests_for_method,
        ):
            dialog = FindPane(
                fixture.app,
                fixture.app,
                search_type="reference",
                search_query="total",
                run_search=True,
                match_mode="exact",
                reference_target="method",
            )
            dialog.narrow_senders_with_tracing()
            first_results = find_result_labels(dialog)

            dialog.find_entry.delete(0, tk.END)
            dialog.find_entry.insert(0, "subtotal")
            dialog.narrow_senders_with_tracing()
            second_results = find_result_labels(dialog)

    assert first_results == ["OrderLine>>recalculateTotal"]
    assert second_results == ["Invoice>>recalculateSubtotal"]
    assert fixture.mock_browser.find_senders.call_args_list == [
        call("total", include_category_details=True),
        call("subtotal", include_category_details=True),
    ]
    dialog.destroy()


def make_mock_gemstone_object(class_name="OrderLine", string_repr="anObject", oop=None):
    """AI: Minimal GemStone object mock satisfying ObjectInspector's full protocol.
    allInstVarNames() returns [] so sub-inspectors are created empty (no recursion needed).
    isBehavior() returns False so instances are inspected via inspect_instance, not inspect_class.
    """
    obj = Mock()
    obj.gemstone_class.return_value.asString.return_value.to_py = class_name
    obj.asString.return_value.to_py = string_repr
    obj.printString.return_value.to_py = string_repr
    obj.gemstone_class.return_value.allInstVarNames.return_value = []
    obj.isBehavior.return_value.to_py = False
    if oop is not None:
        obj.oop = oop
    return obj


def make_mock_dictionary(entries):
    dictionary = make_mock_gemstone_object(
        "Dictionary", f"a Dictionary({len(entries)})"
    )
    keys = []
    values_by_key = {}
    for key_name, value in entries:
        key = make_mock_gemstone_object("Symbol", key_name)
        keys.append(key)
        values_by_key[key] = value

    dictionary.keys.return_value = keys
    dictionary.size.return_value.to_py = len(keys)

    def at_key(key):
        return values_by_key[key]

    dictionary.at.side_effect = at_key
    return dictionary


def make_mock_array(values):
    array = make_mock_gemstone_object("Array", f"an Array({len(values)})")
    array.size.return_value.to_py = len(values)
    values_by_index = {index + 1: value for index, value in enumerate(values)}

    def at_index(index):
        return values_by_index[index]

    array.at.side_effect = at_index
    return array


def make_mock_instance_with_inst_vars(class_name, string_repr, inst_vars, oop=None):
    instance = make_mock_gemstone_object(class_name, string_repr, oop=oop)
    inst_var_names = []
    values_by_name = {}
    for inst_var_name, inst_var_value in inst_vars.items():
        inst_var_symbol = Mock()
        inst_var_symbol.to_py = inst_var_name
        inst_var_names.append(inst_var_symbol)
        values_by_name[inst_var_name] = inst_var_value

    instance.gemstone_class.return_value.allInstVarNames.return_value = inst_var_names

    def value_for_inst_var(inst_var_name):
        return values_by_name[inst_var_name.to_py]

    instance.instVarNamed.side_effect = value_for_inst_var
    return instance


class GraphObjectRegistryFixture(Fixture):
    @set_up
    def create_registry(self):
        self.registry = UmlObjectDiagramRegistry()


class UmlDiagramRegistryFixture(Fixture):
    @set_up
    def create_registry(self):
        self.registry = UmlClassDiagramRegistry()


class GraphObjectKeyScenarios(Fixture):
    @scenario
    def none_object(self):
        """AI: None should map to a stable sentinel key."""
        self.an_object = None
        self.expected_key = ("none",)

    @scenario
    def oop_backed_object(self):
        """AI: Objects exposing oop should use that oop for deduplication."""
        self.an_object = make_mock_gemstone_object("Integer", "7", oop=1234)
        self.expected_key = ("oop", "1234")

    @scenario
    def object_without_oop_attribute(self):
        """AI: Objects without oop should fall back to Python identity keys."""
        self.an_object = object()
        self.expected_key = ("identity", str(id(self.an_object)))

    @scenario
    def object_with_failing_oop_accessor(self):
        """AI: oop lookup failures should fall back to identity keys."""

        class OopFailingObject:
            @property
            def oop(self):
                raise RuntimeError("oop not available")

        self.an_object = OopFailingObject()
        self.expected_key = ("identity", str(id(self.an_object)))


@with_fixtures(GraphObjectRegistryFixture, GraphObjectKeyScenarios)
def test_graph_registry_oop_key_generation_handles_object_shapes(fixture, scenario):
    """AI: Graph registry key generation should choose oop keys when available and otherwise use stable fallbacks."""
    with expected(NoException):
        oop_key = fixture.registry.oop_key_for(scenario.an_object)
    assert oop_key == scenario.expected_key


@with_fixtures(GraphObjectRegistryFixture)
def test_graph_registry_registers_and_resolves_nodes_by_key(fixture):
    """AI: Registering a graph node should allow node lookup by an equivalent object key."""
    gemstone_object = make_mock_gemstone_object("OrderLine", "anOrderLine", oop=2003)
    oop_key = fixture.registry.oop_key_for(gemstone_object)
    node = UmlObjectNode(
        gemstone_object,
        oop_key,
        class_name="OrderLine",
        label="2003:OrderLine",
    )

    fixture.registry.register_node(node)

    assert fixture.registry.contains_object(gemstone_object)
    assert fixture.registry.node_for(gemstone_object) is node


@with_fixtures(GraphObjectRegistryFixture)
def test_graph_registry_avoids_duplicate_edges_for_same_source_target_and_label(
    fixture,
):
    """AI: Re-adding an existing source-target-label edge should not duplicate graph links."""
    source_object = make_mock_gemstone_object("Order", "anOrder", oop=101)
    target_object = make_mock_gemstone_object("OrderLine", "aLine", oop=102)
    source_node = UmlObjectNode(
        source_object,
        fixture.registry.oop_key_for(source_object),
        class_name="Order",
        label="101:Order",
    )
    target_node = UmlObjectNode(
        target_object,
        fixture.registry.oop_key_for(target_object),
        class_name="OrderLine",
        label="102:OrderLine",
    )

    first_edge = fixture.registry.add_edge(source_node, target_node, "line")
    duplicate_edge = fixture.registry.add_edge(source_node, target_node, "line")
    different_label_edge = fixture.registry.add_edge(source_node, target_node, "item")

    assert first_edge is not None
    assert duplicate_edge is None
    assert different_label_edge is not None
    assert len(fixture.registry.all_edges()) == 2


@with_fixtures(UmlDiagramRegistryFixture)
def test_uml_registry_avoids_duplicate_relationships_for_same_source_target_and_kind(
    fixture,
):
    """AI: Re-adding the same UML relationship should not duplicate diagram edges."""
    order_node = UmlClassNode(
        {
            "class_name": "Order",
            "superclass_name": "Object",
            "inst_var_names": ["lines"],
        }
    )
    order_line_node = UmlClassNode(
        {
            "class_name": "OrderLine",
            "superclass_name": "Order",
            "inst_var_names": ["amount"],
        }
    )
    fixture.registry.register_node(order_node)
    fixture.registry.register_node(order_line_node)

    first_relationship = fixture.registry.add_relationship(
        order_node,
        order_line_node,
        "lines",
        "association",
    )
    duplicate_relationship = fixture.registry.add_relationship(
        order_node,
        order_line_node,
        "lines",
        "association",
    )
    inheritance_relationship = fixture.registry.add_relationship(
        order_line_node,
        order_node,
        "",
        "inheritance",
    )

    assert first_relationship is not None
    assert duplicate_relationship is None
    assert inheritance_relationship is not None
    assert len(fixture.registry.all_relationships()) == 2


class ObjectInspectorFixture(Fixture):
    @set_up
    def create_explorer(self):
        self.root = tk.Tk()
        self.root.withdraw()

        self.mock_self = make_mock_gemstone_object("OrderLine", "anOrderLine")
        self.mock_x = make_mock_gemstone_object("Integer", "42")

        # AI: Pass values= directly so ObjectInspector skips the live GemStone
        # instVar-fetching path, while still populating the treeview rows.
        self.explorer = Explorer(
            self.root, values={"self": self.mock_self, "x": self.mock_x}
        )
        self.explorer.pack()
        self.root.update()

        # AI: The Context tab (index 0) is an ObjectInspector added by Explorer.__init__
        self.context_inspector = self.root.nametowidget(self.explorer.tabs()[0])

    @tear_down
    def destroy_explorer(self):
        self.root.destroy()

    def focus_item(self, variable_name):
        """AI: Focus the treeview row whose first column matches variable_name."""
        for item in self.context_inspector.treeview.get_children():
            if self.context_inspector.treeview.item(item, "values")[0] == variable_name:
                self.context_inspector.treeview.focus(item)
                return
        raise ValueError(f"{variable_name!r} not found in treeview")


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_value_opens_new_inspector_tab_and_selects_it(fixture):
    """Double-clicking an object in the inspector opens a new tab in the
    Explorer notebook for that object and immediately makes it the visible tab."""
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, "text") for t in fixture.explorer.tabs()]
    assert "OrderLine anOrderLine" in tab_labels
    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_value_labels_nested_tab_with_oop_class_and_value(fixture):
    """AI: Nested inspector tabs should mirror the root summary format when oop is available."""
    fixture.mock_self.oop = 2003
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "2003:OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_same_value_again_reuses_existing_tab(fixture):
    """Re-opening an inspector for an object that already has a tab switches
    to that tab rather than adding a duplicate."""
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    # AI: Switch to Context so the 'self' tab is no longer selected,
    # then double-click 'self' a second time to verify deduplication.
    fixture.explorer.select(fixture.explorer.tabs()[0])
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, "text") for t in fixture.explorer.tabs()]
    assert tab_labels.count("OrderLine anOrderLine") == 1
    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_double_clicking_equivalent_oop_reuses_existing_tab(fixture):
    """AI: Objects with the same oop should reuse an existing inspector tab even if represented by a different proxy."""
    fixture.mock_self.oop = 2003
    fixture.focus_item("self")
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    same_object_different_proxy = make_mock_gemstone_object(
        "OrderLine",
        "anOrderLine",
        oop=2003,
    )
    context_row = fixture.context_inspector.treeview.get_children()[0]
    context_row_index = fixture.context_inspector.treeview.index(context_row)
    fixture.context_inspector.actual_values[context_row_index] = (
        same_object_different_proxy
    )
    fixture.context_inspector.treeview.focus(context_row)
    fixture.context_inspector.on_item_double_click(None)
    fixture.root.update()

    tab_labels = [fixture.explorer.tab(t, "text") for t in fixture.explorer.tabs()]
    assert tab_labels.count("2003:OrderLine anOrderLine") == 1
    assert (
        fixture.explorer.tab(fixture.explorer.select(), "text")
        == "2003:OrderLine anOrderLine"
    )


@with_fixtures(ObjectInspectorFixture)
def test_object_inspector_row_menu_graph_inspect_routes_selected_value(fixture):
    """AI: The object row context menu should expose Show in Object Diagram and pass the selected row value to the graph action."""
    graph_inspect_action = Mock()
    inspector = ObjectInspector(
        fixture.root,
        values={"self": fixture.mock_self},
        graph_inspect_action=graph_inspect_action,
    )
    inspector.pack()
    fixture.root.update()

    row = inspector.treeview.get_children()[0]
    inspector.treeview.focus(row)
    inspector.treeview.selection_set(row)
    inspector.open_object_menu(
        types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
    )
    fixture.root.update()

    command_labels = menu_command_labels(inspector.current_object_menu)
    assert "Show in Object Diagram" in command_labels

    invoke_menu_command_by_label(
        inspector.current_object_menu, "Show in Object Diagram"
    )
    fixture.root.update()

    graph_inspect_action.assert_called_once_with(fixture.mock_self)


@with_fixtures(ObjectInspectorFixture)
def test_object_inspector_row_menu_browse_class_routes_selected_value(fixture):
    """AI: The object row context menu should expose Browse Class and route the selected row's value to the browser callback, so a user can jump to the class of any displayed instVar without going through the inspected-container header button."""
    browse_class_action = Mock()
    inspector = ObjectInspector(
        fixture.root,
        values={'self': fixture.mock_self},
        browse_class_action=browse_class_action,
    )
    inspector.pack()
    fixture.root.update()

    row = inspector.treeview.get_children()[0]
    inspector.treeview.focus(row)
    inspector.treeview.selection_set(row)
    inspector.open_object_menu(
        types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
    )
    fixture.root.update()

    command_labels = menu_command_labels(inspector.current_object_menu)
    assert 'Browse Class' in command_labels

    invoke_menu_command_by_label(inspector.current_object_menu, 'Browse Class')
    fixture.root.update()

    browse_class_action.assert_called_once_with(fixture.mock_self)


@with_fixtures(ObjectInspectorFixture)
def test_object_inspector_browse_class_button_routes_inspected_object(fixture):
    """AI: Browse Class should route the inspected object to the browser callback."""
    browse_class_action = Mock()
    inspector = ObjectInspector(
        fixture.root,
        an_object=fixture.mock_self,
        browse_class_action=browse_class_action,
    )
    inspector.pack()
    fixture.root.update()

    inspector.browse_class_button.invoke()
    fixture.root.update()

    browse_class_action.assert_called_once_with(fixture.mock_self)


@with_fixtures(ObjectInspectorFixture)
def test_dictionary_inspector_shows_key_value_rows_and_drills_into_value(fixture):
    """Dictionary-like objects are shown as key/value rows and double-clicking a row opens an inspector for the value."""
    first_value = make_mock_gemstone_object("Integer", "1")
    second_value = make_mock_gemstone_object("OrderLine", "anOrderLine")
    dictionary = make_mock_dictionary(
        [
            ("first", first_value),
            ("second", second_value),
        ]
    )

    dictionary_inspector = ObjectInspector(fixture.explorer, an_object=dictionary)
    fixture.explorer.add(dictionary_inspector, text="Dictionary")
    fixture.explorer.select(dictionary_inspector)
    fixture.root.update()

    rows = dictionary_inspector.treeview.get_children()
    assert dictionary_inspector.treeview.heading("Name", "text") == "Key"
    assert len(rows) == 2
    assert dictionary_inspector.status_label.cget("text") == "2 items"

    dictionary_inspector.treeview.focus(rows[0])
    dictionary_inspector.on_item_double_click(None)
    fixture.root.update()

    assert fixture.explorer.tab(fixture.explorer.select(), "text") == "Integer 1"


@with_fixtures(ObjectInspectorFixture)
def test_array_inspector_shows_size_and_pages_through_values(fixture):
    """Array-like objects show indexed rows, report total size, and allow paging through large collections."""
    values = [make_mock_gemstone_object("Integer", str(index)) for index in range(105)]
    array = make_mock_array(values)
    array_inspector = ObjectInspector(fixture.root, an_object=array)
    array_inspector.pack()
    fixture.root.update()

    rows = array_inspector.treeview.get_children()
    assert array_inspector.treeview.heading("Name", "text") == "Index"
    assert len(rows) == 100
    assert array_inspector.status_label.cget("text") == "Items 1-100 of 105"

    array_inspector.on_next_page()
    fixture.root.update()

    next_rows = array_inspector.treeview.get_children()
    assert len(next_rows) == 5
    assert array_inspector.status_label.cget("text") == "Items 101-105 of 105"
    assert array_inspector.treeview.item(next_rows[0], "values")[0] == "[101]"


@with_fixtures(ObjectInspectorFixture)
def test_attribute_less_object_shows_print_string_as_text(fixture):
    """An object with no inspectable attributes (a scalar such as an Integer or
    String) is best understood by its printed form, so the inspector replaces the
    empty attribute list with a read-only text view of its printString."""
    integer = make_mock_gemstone_object("Integer", "42")
    scalar_inspector = ObjectInspector(fixture.root, an_object=integer)
    scalar_inspector.pack()
    fixture.root.update()

    assert scalar_inspector.treeview.grid_info() == {}
    assert scalar_inspector.value_workspace.grid_info() != {}
    assert scalar_inspector.value_workspace.text.get("1.0", "end-1c") == "42"


@with_fixtures(ObjectInspectorFixture)
def test_object_with_attributes_keeps_the_attribute_list(fixture):
    """An object that does expose instance variables still shows the attribute
    treeview, never the scalar text view, so structured objects are unaffected."""
    instance = make_mock_instance_with_inst_vars(
        "OrderLine", "anOrderLine", {"quantity": fixture.mock_x}
    )
    instance_inspector = ObjectInspector(fixture.root, an_object=instance)
    instance_inspector.pack()
    fixture.root.update()

    assert instance_inspector.treeview.grid_info() != {}
    assert instance_inspector.value_workspace.grid_info() == {}
    rows = instance_inspector.treeview.get_children()
    assert instance_inspector.treeview.item(rows[0], "values")[0] == "quantity"


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_method_runs_test_and_shows_pass_result(fixture):
    """Right-clicking a method and choosing Run Test calls run_test_method on
    the session and shows a passing info dialog when all assertions pass."""
    # AI: Navigate to the method so the method listbox has a live selection,
    # matching what show_context_menu does before invoking run_test.
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    passing_result = {
        "run_count": 1,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.run_test_method = Mock(return_value=passing_result)

    with patch("reahl.swordfish.browser.messagebox") as mock_msgbox:
        fixture.browser_window.methods_widget.run_test()

    fixture.mock_browser.run_test_method.assert_called_once_with("OrderLine", "total")
    mock_msgbox.showinfo.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_covering_tests_opens_browse_dialog(fixture):
    """AI: Covering Tests action should open the browse dialog for the selected method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget

    with patch("reahl.swordfish.browser.CoveringTestsBrowseDialog") as dialog_class:
        methods_widget.open_covering_tests()

    dialog_class.assert_called_once_with(
        fixture.root,
        fixture.application,
        "total",
    )


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_show_in_uml_routes_selected_method(fixture):
    """AI: The method context menu should route the selected method to the UML pin action."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    methods_widget = fixture.browser_window.methods_widget
    methods_widget.application.pin_method_in_class_diagram = Mock()

    methods_widget.show_context_menu(
        types.SimpleNamespace(x=1, y=1, x_root=1, y_root=1),
    )
    fixture.root.update()

    command_labels = menu_command_labels(methods_widget.current_context_menu)

    assert "Show in Class Diagram" in command_labels

    invoke_menu_command_by_label(
        methods_widget.current_context_menu, "Show in Class Diagram"
    )

    methods_widget.application.pin_method_in_class_diagram.assert_called_once_with(
        "OrderLine",
        True,
        "total",
    )


@with_fixtures(SwordfishGuiFixture)
def test_covering_tests_browse_dialog_navigates_to_selected_test_method(fixture):
    """AI: Double-clicking a discovered covering test should navigate browser selection to that test method."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    with patch.object(CoveringTestsBrowseDialog, "wait_visibility"):
        with patch.object(
            CoveringTestsBrowseDialog,
            "run_search_attempt",
            autospec=True,
        ):
            with patch.object(
                CoveringTestsBrowseDialog,
                "monitor_search",
                autospec=True,
            ):
                dialog = CoveringTestsBrowseDialog(
                    fixture.browser_window,
                    fixture.application,
                    "total",
                )
                dialog.add_or_update_candidate_test(
                    {
                        "test_case_class_name": "OrderLineTest",
                        "test_method_selector": "testRecalculateTotal",
                        "depth": 1,
                        "reached_from_selector": "recalculateTotal",
                    },
                )
                assert dialog.results_listbox.size() == 1
                dialog.set_ready_state(
                    timed_out=False,
                    summary_message="",
                )
                fixture.root.update()

        with patch.object(
            fixture.browser_window.application,
            "handle_sender_selection",
        ) as handle_sender_selection:
            assert dialog.results_listbox.cget("state") == tk.NORMAL
            dialog.results_listbox.selection_set(0)
            dialog.on_result_double_click(None)
            fixture.root.update()

    handle_sender_selection.assert_called_once_with(
        "OrderLineTest",
        True,
        "testRecalculateTotal",
    )
    dialog.destroy()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_add_parameter_calls_browser_preview(fixture):
    """Preview Add Parameter from the method editor forwards all prompt inputs to the browser preview API."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_add_parameter_preview.return_value = {"preview": "ok"}
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch(
        "reahl.swordfish.text_editing.simpledialog.askstring",
        side_effect=["with:", "extraValue", "nil"],
    ):
        with patch(
            "reahl.swordfish.text_editing.JsonResultDialog"
        ) as mock_result_dialog:
            tab.code_panel.preview_method_add_parameter()

    fixture.mock_browser.method_add_parameter_preview.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        "with:",
        "extraValue",
        "nil",
    )
    mock_result_dialog.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_calls_browser_preview(fixture):
    """Preview Extract Method uses selected statements and calls browser extract preview with inferred statement indexes."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.source_method_ast.return_value = {
        "statements": [
            {
                "statement_index": 1,
                "start_offset": 6,
                "end_offset": 24,
                "source": "^amount * quantity",
                "sends": [],
            },
        ],
        "temporaries": [],
        "header_source": "total",
    }
    fixture.mock_browser.method_extract_preview.return_value = {"preview": "ok"}
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.tag_add(tk.SEL, "2.0", "2.end")

    with patch(
        "reahl.swordfish.text_editing.simpledialog.askstring",
        return_value="extractedPart",
    ):
        with patch(
            "reahl.swordfish.text_editing.JsonResultDialog"
        ) as mock_result_dialog:
            tab.code_panel.preview_method_extract()

    fixture.mock_browser.source_method_ast.assert_called_once_with(ANY, "total")
    fixture.mock_browser.method_extract_preview.assert_called_once_with(
        "OrderLine",
        True,
        "total",
        "extractedPart",
        [1],
    )
    mock_result_dialog.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_requires_selection(fixture):
    """Preview Extract Method reports a user-facing error when no statement is selected."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch("reahl.swordfish.text_editing.messagebox") as mock_msgbox:
        tab.code_panel.preview_method_extract()

    mock_msgbox.showerror.assert_called_once()
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_partial_return_selection_reports_selection_error(
    fixture,
):
    """Partially selecting a return statement should report selection coverage guidance, not a return-extraction error."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.source_method_ast.return_value = {
        "statements": [
            {
                "statement_index": 1,
                "start_offset": 10,
                "end_offset": 27,
                "source": "^amount * quantity",
                "sends": [],
            },
        ],
        "temporaries": [],
        "header_source": "total",
    }
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]
    tab.code_panel.text_editor.tag_add(tk.SEL, "2.14", "2.end")

    with patch("reahl.swordfish.text_editing.messagebox") as mock_msgbox:
        with patch(
            "reahl.swordfish.text_editing.simpledialog.askstring"
        ) as mock_askstring:
            tab.code_panel.preview_method_extract()

    mock_askstring.assert_not_called()
    mock_msgbox.showerror.assert_called_once()
    error_message = mock_msgbox.showerror.call_args[0][1]
    assert "fully cover" in error_message
    assert "return" not in error_message.lower()
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_extract_suggests_keyword_selector_when_arguments_are_needed(
    fixture,
):
    """Extract suggestion should default to a keyword selector when selected statements depend on caller-scoped variables."""
    fixture.mock_browser.list_methods.return_value = ["buildFrom:"]
    mock_method = Mock()
    mock_method.sourceString.return_value.to_py = (
        "buildFrom: input\n" "    | tmp |\n" "    tmp := input + 1.\n" "    ^tmp"
    )
    fixture.mock_browser.get_compiled_method.return_value = mock_method
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "buildFrom:")
    fixture.mock_browser.source_method_ast.return_value = {
        "statements": [
            {
                "statement_index": 1,
                "start_offset": 33,
                "end_offset": 49,
                "source": "tmp := input + 1",
                "sends": [],
            },
        ],
        "temporaries": ["tmp"],
        "header_source": "buildFrom: input",
    }
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "buildFrom:")
    ]
    tab.code_panel.text_editor.tag_add(tk.SEL, "3.0", "3.end")

    captured_initial_values = []

    def fake_askstring(*args, **kwargs):
        captured_initial_values.append(kwargs.get("initialvalue"))
        return None

    with patch(
        "reahl.swordfish.text_editing.simpledialog.askstring",
        side_effect=fake_askstring,
    ):
        tab.code_panel.preview_method_extract()

    assert captured_initial_values == ["extractedComputeTmp:"]
    fixture.mock_browser.method_extract_preview.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_add_parameter_shows_error_for_browser_domain_exception(
    fixture,
):
    """Add-parameter preview failures from browser domain rules should surface as dialog errors, not Tk callback crashes."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_add_parameter_preview.side_effect = (
        GemstoneDomainException("Could not parse keyword method header.")
    )
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch(
        "reahl.swordfish.text_editing.simpledialog.askstring",
        side_effect=["with:", "extraValue", "nil"],
    ):
        with patch("reahl.swordfish.text_editing.messagebox") as mock_msgbox:
            tab.code_panel.preview_method_add_parameter()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_method_context_menu_preview_inline_shows_error_for_browser_domain_exception(
    fixture,
):
    """Inline preview validation failures should be caught and shown as an error dialog."""
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")
    fixture.mock_browser.method_inline_preview.side_effect = GemstoneDomainException(
        "inline_selector must be a unary selector."
    )
    tab = fixture.browser_window.editor_area_widget.open_tabs[
        ("OrderLine", True, "total")
    ]

    with patch(
        "reahl.swordfish.text_editing.simpledialog.askstring", return_value="ifTrue:"
    ):
        with patch("reahl.swordfish.text_editing.messagebox") as mock_msgbox:
            tab.code_panel.preview_method_inline()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_method_shows_error_dialog_when_test_fails(fixture):
    """When a test method has failures or errors, Run Test shows an error
    dialog rather than an info dialog, surfacing the failure messages."""
    # AI: Navigate all the way to the method so the method listbox has a live
    # selection, matching what show_context_menu sets before invoking run_test.
    fixture.select_down_to_method("Kernel", "OrderLine", "accessing", "total")

    failing_result = {
        "run_count": 1,
        "failure_count": 1,
        "error_count": 0,
        "has_passed": False,
        "failures": ["total: expected true"],
        "errors": [],
    }
    fixture.mock_browser.run_test_method = Mock(return_value=failing_result)

    with patch("reahl.swordfish.browser.messagebox") as mock_msgbox:
        fixture.browser_window.methods_widget.run_test()

    mock_msgbox.showerror.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_right_click_on_class_runs_all_tests_and_shows_result(fixture):
    """Right-clicking a class and choosing Run All Tests calls run_gemstone_tests
    for that class and shows the result summary in a dialog."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    # AI: Also select a class in the classes listbox so run_all_tests() reads a
    # live curselection(), matching what show_context_menu sets before invoking it.
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )

    passing_result = {
        "run_count": 3,
        "failure_count": 0,
        "error_count": 0,
        "has_passed": True,
        "failures": [],
        "errors": [],
    }
    fixture.mock_browser.run_gemstone_tests = Mock(return_value=passing_result)

    with patch("reahl.swordfish.browser.messagebox") as mock_msgbox:
        fixture.browser_window.classes_widget.run_all_tests()

    fixture.mock_browser.run_gemstone_tests.assert_called_once_with("OrderLine")
    mock_msgbox.showinfo.assert_called_once()


@with_fixtures(SwordfishGuiFixture)
def test_class_list_context_menu_find_references_uses_selected_class_name(
    fixture,
):
    """AI: Find References from class list context menu should open class-reference lookup for the clicked class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.application.open_find_dialog_for_class = Mock()
    class_listbox = classes_widget.selection_list.selection_listbox
    class_index = list(class_listbox.get(0, "end")).index("OrderLine")
    class_item_box = class_listbox.bbox(class_index)
    assert class_item_box is not None

    classes_widget.show_context_menu(
        types.SimpleNamespace(
            widget=class_listbox,
            y=class_item_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)
    assert "References" in command_labels
    fixture.invoke_menu_command(menu, "References")

    classes_widget.application.open_find_dialog_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishGuiFixture)
def test_class_list_instvar_references_submenu_reflects_the_right_clicked_class(
    fixture,
):
    """AI: The Variable References submenu must list the variables of the class the
    user right-clicked, even when a different class was right-clicked moments before.
    Right-clicking does not select, so a class-scoped cache would leak the first
    class's variables into the second menu; reading fresh per right-click prevents it."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    class_listbox = classes_widget.selection_list.selection_listbox

    def instvar_submenu_labels_after_right_click(class_name):
        class_index = list(class_listbox.get(0, "end")).index(class_name)
        class_listbox.see(class_index)
        fixture.root.update()
        class_item_box = class_listbox.bbox(class_index)
        assert class_item_box is not None
        classes_widget.show_context_menu(
            types.SimpleNamespace(
                widget=class_listbox,
                y=class_item_box[1] + 1,
                x_root=1,
                y_root=1,
            )
        )
        return cascade_submenu_labels(
            classes_widget.current_context_menu,
            "Variable References",
        )

    order_line_vars = instvar_submenu_labels_after_right_click("OrderLine")
    assert order_line_vars == ["amount", "quantity", "lines"]

    order_vars = instvar_submenu_labels_after_right_click("Order")
    assert order_vars == ["lines"]
    assert "amount" not in order_vars
    assert "quantity" not in order_vars


@with_fixtures(SwordfishGuiFixture)
def test_variable_references_submenu_marks_kinds_and_inheritance(fixture):
    """AI: The submenu must let the reader tell the variable kinds and inheritance
    apart: each kind sits under a bold, non-selectable heading, and inherited
    variables are shown in the muted colour (yet stay selectable) while the class's
    own variables render normally."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    class_listbox = classes_widget.selection_list.selection_listbox
    class_index = list(class_listbox.get(0, "end")).index("OrderLine")
    class_listbox.see(class_index)
    fixture.root.update()
    class_item_box = class_listbox.bbox(class_index)
    assert class_item_box is not None
    classes_widget.show_context_menu(
        types.SimpleNamespace(
            widget=class_listbox,
            y=class_item_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    submenu = cascade_submenu(
        classes_widget.current_context_menu,
        "Variable References",
    )

    def entry_at(label):
        entry_count = int(submenu.index("end")) + 1
        for entry_index in range(entry_count):
            if submenu.type(entry_index) == "command":
                if submenu.entrycget(entry_index, "label") == label:
                    return entry_index
        raise AssertionError(f"No submenu entry labelled {label}.")

    muted_colour = active_theme.current().color_for("disabled_list_item")
    heading_index = entry_at("Instance")
    # AI: The heading is an inert label (no command) but stays in the normal colour
    # (not greyed) and is underlined rather than bold, so it reads as a section title.
    assert str(submenu.entrycget(heading_index, "command")) == ""
    assert str(submenu.entrycget(heading_index, "foreground")) != muted_colour
    heading_font = tkfont.Font(submenu, font=submenu.entrycget(heading_index, "font"))
    assert heading_font.actual("underline") == 1
    assert heading_font.actual("weight") == "normal"

    inherited_index = entry_at("lines")
    assert str(submenu.entrycget(inherited_index, "foreground")) == muted_colour
    assert str(submenu.entrycget(inherited_index, "command")) != ""

    own_index = entry_at("amount")
    assert str(submenu.entrycget(own_index, "foreground")) != muted_colour
    assert str(submenu.entrycget(own_index, "command")) != ""


@with_fixtures(SwordfishGuiFixture)
def test_class_variable_pick_routes_to_classvar_reference_search(fixture):
    """AI: Choosing a class variable must run the class-variable search, not the
    instance-variable one (instVarsAccessed cannot see class vars). This is observable
    as the class-var-specific find entry point being invoked with the class context."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.application.open_find_dialog_for_classvar = Mock()
    classes_widget.application.open_find_dialog_for_instvar = Mock()
    # AI: Give OrderLine a class variable for this menu without disturbing the shared
    # class-definition fixtures used elsewhere.
    classes_widget.gemstone_session_record.gemstone_browser_session.accessible_var_names.side_effect = (
        lambda class_name: {
            "inst_var_names": [{"name": "amount", "inherited": False}],
            "class_inst_var_names": [],
            "class_var_names": [{"name": "DefaultRate", "inherited": False}],
        }
    )
    class_listbox = classes_widget.selection_list.selection_listbox
    class_index = list(class_listbox.get(0, "end")).index("OrderLine")
    class_listbox.see(class_index)
    fixture.root.update()
    class_item_box = class_listbox.bbox(class_index)
    assert class_item_box is not None
    classes_widget.show_context_menu(
        types.SimpleNamespace(
            widget=class_listbox,
            y=class_item_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    submenu = cascade_submenu(
        classes_widget.current_context_menu,
        "Variable References",
    )
    invoke_menu_command_by_label(submenu, "DefaultRate")

    classes_widget.application.open_find_dialog_for_classvar.assert_called_once_with(
        "OrderLine",
        "DefaultRate",
    )
    classes_widget.application.open_find_dialog_for_instvar.assert_not_called()


@with_fixtures(SwordfishGuiFixture)
def test_class_hierarchy_context_menu_find_references_uses_selected_class_name(
    fixture,
):
    """AI: Find References from hierarchy context menu should open class-reference lookup for the clicked class."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.application.open_find_dialog_for_class = Mock()
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()
    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    order_line_item = child_with_text(order_item, "OrderLine")
    tree.selection_set(order_line_item)
    tree.focus(order_line_item)
    tree.see(order_line_item)
    fixture.root.update()
    order_line_box = tree.bbox(order_line_item)
    assert order_line_box not in [None, ""]

    classes_widget.show_hierarchy_context_menu(
        types.SimpleNamespace(
            widget=tree,
            y=order_line_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)
    assert "References" in command_labels
    fixture.invoke_menu_command(menu, "References")

    classes_widget.application.open_find_dialog_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishGuiFixture)
def test_class_hierarchy_context_menu_instvar_references_submenu_reflects_clicked_class(
    fixture,
):
    """AI: The hierarchy context menu must offer the same Inst Var References submenu
    as the class list, listing the clicked class's accessible variables (own and
    inherited). This keeps the two views of the class set consistent."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    fixture.select_in_listbox(
        fixture.browser_window.classes_widget.selection_list.selection_listbox,
        "OrderLine",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()
    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    order_line_item = child_with_text(order_item, "OrderLine")
    tree.selection_set(order_line_item)
    tree.focus(order_line_item)
    tree.see(order_line_item)
    fixture.root.update()
    order_line_box = tree.bbox(order_line_item)
    assert order_line_box not in [None, ""]

    classes_widget.show_hierarchy_context_menu(
        types.SimpleNamespace(
            widget=tree,
            y=order_line_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    instvar_labels = cascade_submenu_labels(
        classes_widget.current_context_menu,
        "Variable References",
    )
    assert instvar_labels == ["amount", "quantity", "lines"]


@with_fixtures(SwordfishGuiFixture)
def test_class_hierarchy_context_menu_add_selected_to_uml_routes_all_selected_classes(
    fixture,
):
    """AI: The hierarchy context menu should bulk-add every selected class to UML without collapsing the selection."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.application.open_class_diagram_for_class = Mock()
    classes_widget.classes_notebook.select(classes_widget.hierarchy_frame)
    fixture.root.update()
    tree = classes_widget.hierarchy_tree

    def child_with_text(parent_item, expected_text):
        child_item_ids = tree.get_children(parent_item)
        for child_item_id in child_item_ids:
            if tree.item(child_item_id, "text") == expected_text:
                return child_item_id
        raise AssertionError(
            f"Could not find {expected_text} under {parent_item}.",
        )

    object_item = child_with_text("", "Object")
    order_item = child_with_text(object_item, "Order")
    tree.item(object_item, open=True)
    tree.item(order_item, open=True)
    fixture.root.update()
    order_line_item = child_with_text(order_item, "OrderLine")
    tree.selection_set((order_item, order_line_item))
    tree.focus(order_line_item)
    tree.see(order_line_item)
    fixture.root.update()

    classes_widget.show_hierarchy_context_menu(
        types.SimpleNamespace(
            widget=tree,
            y=-1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)

    assert "Add Selected to Class Diagram" in command_labels

    fixture.invoke_menu_command(menu, "Add Selected to Class Diagram")

    classes_widget.application.open_class_diagram_for_class.assert_has_calls(
        [
            call("Order"),
            call("OrderLine"),
        ]
    )


@with_fixtures(SwordfishGuiFixture)
def test_class_list_context_menu_add_to_uml_routes_selected_class(fixture):
    """AI: The class list context menu should route the clicked class to the UML action."""
    fixture.select_in_listbox(
        fixture.browser_window.packages_widget.selection_list.selection_listbox,
        "Kernel",
    )
    classes_widget = fixture.browser_window.classes_widget
    classes_widget.application.open_class_diagram_for_class = Mock()
    class_listbox = classes_widget.selection_list.selection_listbox
    class_index = list(class_listbox.get(0, "end")).index("OrderLine")
    class_item_box = class_listbox.bbox(class_index)
    assert class_item_box is not None

    classes_widget.show_context_menu(
        types.SimpleNamespace(
            widget=class_listbox,
            y=class_item_box[1] + 1,
            x_root=1,
            y_root=1,
        )
    )
    menu = classes_widget.current_context_menu
    command_labels = menu_command_labels(menu)

    assert "Add to Class Diagram" in command_labels

    fixture.invoke_menu_command(menu, "Add to Class Diagram")

    classes_widget.application.open_class_diagram_for_class.assert_called_once_with(
        "OrderLine",
    )


@with_fixtures(SwordfishAppFixture)
def test_run_test_method_opens_debugger_on_gemstone_error(fixture):
    """If running a test method raises a GemstoneError (e.g. an unhandled
    runtime exception), the debugger tab opens — the same flow as the Run tab."""
    fixture.simulate_login()

    # AI: Pre-load the method listbox and set selected_class directly;
    # no column-cascade navigation is needed to test the error-catching path.
    methods_listbox = (
        fixture.app.browser_tab.methods_widget.selection_list.selection_listbox
    )
    methods_listbox.insert(tk.END, "testDivideByZero")
    methods_listbox.selection_set(0)
    fixture.session_record.selected_class = "SwordfishDebuggerDemoTest"

    fixture.mock_browser.run_test_method = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.methods_widget.run_test()
    fixture.app.update()

    tab_labels = all_open_tab_texts(fixture.app)
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_run_all_tests_opens_debugger_on_gemstone_error(fixture):
    """If running all tests for a class raises a GemstoneError, the debugger
    tab opens so the user can inspect the error context and stack."""
    fixture.simulate_login()

    # AI: Pre-load the classes listbox; no full cascade needed for the error path.
    classes_listbox = (
        fixture.app.browser_tab.classes_widget.selection_list.selection_listbox
    )
    classes_listbox.insert(tk.END, "SwordfishDebuggerDemoTest")
    classes_listbox.selection_set(0)

    fixture.mock_browser.run_gemstone_tests = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.classes_widget.run_all_tests()
    fixture.app.update()

    tab_labels = all_open_tab_texts(fixture.app)
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_debug_test_opens_debugger_even_for_assertion_failures(fixture):
    """Choosing Debug Test runs the test via runCase (no SUnit error trapping),
    so both assertion failures and runtime errors open the debugger rather than
    returning a pass/fail summary."""
    fixture.simulate_login()

    methods_listbox = (
        fixture.app.browser_tab.methods_widget.selection_list.selection_listbox
    )
    methods_listbox.insert(tk.END, "testSomethingBroken")
    methods_listbox.selection_set(0)
    fixture.session_record.selected_class = "MyTestCase"

    # AI: debug_test_method always raises GemstoneError when the test fails
    # because runCase has no error handling — assertion failures propagate too.
    fixture.mock_browser.debug_test_method = Mock(side_effect=FakeGemstoneError())

    fixture.app.browser_tab.methods_widget.debug_test()
    fixture.app.update()

    tab_labels = all_open_tab_texts(fixture.app)
    assert "Debugger" in tab_labels


@with_fixtures(SwordfishAppFixture)
def test_class_organizer_initialized_after_login(fixture):
    """AI: The ClassOrganizer cache should be initialized at login to avoid the first-execution slowdown on every new session."""
    fixture.session_record.initialize_class_organizer = Mock()
    with patch.object(
        GemstoneSessionRecord, 'log_in_linked', return_value=fixture.session_record
    ):
        fixture.app.login_frame.attempt_login()
    fixture.app.update()

    fixture.session_record.initialize_class_organizer.assert_called_once()


def test_class_organizer_warm_up_runs_when_supported():
    """AI: When cachedOrganizer is available in the image, initialize_class_organizer should call it to pre-warm the cache."""
    session_record = GemstoneSessionRecord.__new__(GemstoneSessionRecord)
    session_record.gemstone_session = Mock()
    session_record.gemstone_session.ClassOrganizer.respondsTo.return_value = Mock(
        to_py=True
    )
    session_record.initialize_class_organizer()
    session_record.gemstone_session.ClassOrganizer.cachedOrganizer().updateClassInfo.assert_called()


def test_class_organizer_warm_up_skipped_when_not_supported():
    """AI: If the image does not have cachedOrganizer loaded, initialize_class_organizer should skip the warm-up without error."""
    session_record = GemstoneSessionRecord.__new__(GemstoneSessionRecord)
    session_record.gemstone_session = Mock()
    session_record.gemstone_session.ClassOrganizer.respondsTo.return_value = Mock(
        to_py=False
    )
    with expected(NoException):
        session_record.initialize_class_organizer()
    session_record.gemstone_session.ClassOrganizer.cachedOrganizer.assert_not_called()


def test_read_gemstone_exe_conf_from_config_file():
    """AI: The gemstone_exe_conf path should be read from swordfish.json independently of MCP config."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        config_file_path = os.path.join(temporary_directory, 'swordfish.json')
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump(
                {
                    GEMSTONE_EXE_CONF_CONFIG_NAME: '/home/acme/gem.conf',
                    'schema_version': 2,
                    'mcp_runtime_config': {},
                },
                f,
            )

        assert read_gemstone_exe_conf(config_file_path) == '/home/acme/gem.conf'


def test_read_gemstone_exe_conf_returns_empty_when_key_absent():
    """AI: Reading gemstone_exe_conf from a config file that does not contain the key should return an empty string."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        config_file_path = os.path.join(temporary_directory, 'swordfish.json')
        with open(config_file_path, 'w', encoding='utf-8') as f:
            json.dump({'schema_version': 2, 'mcp_runtime_config': {}}, f)

        assert read_gemstone_exe_conf(config_file_path) == ''


def test_apply_gemstone_exe_conf_sets_env_var():
    """AI: Applying a configured gemstone_exe_conf path should set GEMSTONE_EXE_CONF in the process environment."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop('GEMSTONE_EXE_CONF', None)
        apply_gemstone_exe_conf('/home/acme/gem.conf')
        assert os.environ['GEMSTONE_EXE_CONF'] == '/home/acme/gem.conf'


def test_apply_gemstone_exe_conf_clears_env_var_when_empty():
    """AI: Applying an empty gemstone_exe_conf should remove GEMSTONE_EXE_CONF so the GemStone default lookup applies."""
    with patch.dict(os.environ, {'GEMSTONE_EXE_CONF': '/some/existing.conf'}):
        apply_gemstone_exe_conf('')
        assert 'GEMSTONE_EXE_CONF' not in os.environ


def test_apply_gemstone_exe_conf_warns_when_overriding_env_var(caplog):
    """AI: If swordfish.json specifies a different gemstone_exe_conf than the environment already has, a warning should be logged so the user knows the env var was overridden."""
    import logging

    with patch.dict(os.environ, {'GEMSTONE_EXE_CONF': '/env/existing.conf'}):
        with caplog.at_level(logging.WARNING):
            apply_gemstone_exe_conf('/config/override.conf')
        assert os.environ.get('GEMSTONE_EXE_CONF') == '/config/override.conf'

    assert any(
        '/env/existing.conf' in record.message
        and '/config/override.conf' in record.message
        for record in caplog.records
    )


def test_save_preserves_unrecognised_top_level_keys():
    """AI: Saving MCP runtime config should not silently discard top-level keys it does not know about, such as gemstone_exe_conf."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': temporary_directory}):
            configuration_store = McpConfigurationStore()
            config_file_path = configuration_store.config_file_path()
            os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
            with open(config_file_path, 'w', encoding='utf-8') as config_file:
                config_file.write(
                    json.dumps(
                        {
                            'schema_version': 2,
                            'mcp_runtime_config': {'allow_source_read': True},
                            GEMSTONE_EXE_CONF_CONFIG_NAME: '/home/acme/gem.conf',
                        }
                    )
                    + '\n'
                )

            configuration_store.save(McpRuntimeConfig(allow_source_read=True))

            with open(config_file_path, 'r', encoding='utf-8') as config_file:
                saved_payload = json.load(config_file)

            assert (
                saved_payload[GEMSTONE_EXE_CONF_CONFIG_NAME] == '/home/acme/gem.conf'
            )
