#!/var/local/gemstone/venv/wonka/bin/python

import argparse
import asyncio
import json
import logging
import os
import queue
import re
import sys
import threading
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
import weakref
from collections import deque
from tkinter import ttk

from reahl.ptongue import GemstoneError, LinkedSession, RPCSession

from reahl.swordfish.browser import (
    BrowserWindow,
    CategorySelection,
    ClassSelection,
    CoveringTestsBrowseDialog,
    CoveringTestsDiscoveryWorkflow,
    FramedWidget,
    MethodEditor,
    MethodSelection,
    PackageSelection,
)
from reahl.swordfish.class_diagram import (
    UmlClassDiagramCanvas,
    UmlClassDiagramMethodChooserDialog,
    UmlClassDiagramRegistry,
    UmlClassDiagramTab,
    UmlClassNode,
    UmlClassRelationship,
    format_class_diagram_method_label,
)
from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.execution import DebuggerControls, DebuggerWindow, RunTab
from reahl.swordfish.gemstone import GemstoneBrowserSession, GemstoneDebugSession
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.inspector import Explorer, InspectorTab, ObjectInspector
from reahl.swordfish.mcp.integration_state import current_integrated_session_state
from reahl.swordfish.mcp.server import McpDependencyNotInstalled, create_server
from reahl.swordfish.navigation import (
    GlobalNavigationEntry,
    GlobalNavigationHistory,
    NavigationHistory,
)
from reahl.swordfish.object_diagram import (
    UmlObjectDiagramCanvas,
    UmlObjectDiagramNodeDetailDialog,
    UmlObjectDiagramNodeInspectorHost,
    UmlObjectDiagramRegistry,
    UmlObjectDiagramTab,
    UmlObjectNode,
    UmlObjectRelationship,
)
from reahl.swordfish.selection_list import InteractiveSelectionList
from reahl.swordfish.tab_registry import DeduplicatedTabRegistry
from reahl.swordfish.text_editing import (
    CodeLineNumberColumn,
    CodePanel,
    EditableText,
    EditorTab,
    JsonResultDialog,
    TextCursorPositionIndicator,
    configure_widget_if_alive,
)
from reahl.swordfish.ui_context import UiContext
from reahl.swordfish.ui_support import (
    GRAPH_NODE_HEIGHT,
    GRAPH_NODE_PADDING_X,
    GRAPH_NODE_PADDING_Y,
    GRAPH_NODE_WIDTH,
    GRAPH_NODES_PER_ROW,
    GRAPH_ORIGIN_X,
    GRAPH_ORIGIN_Y,
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
    close_popup_menu,
    popup_menu,
)


class GemstoneSessionRecord:
    def __init__(self, gemstone_session):
        self.gemstone_session = gemstone_session
        self.gemstone_browser_session = GemstoneBrowserSession(gemstone_session)
        self.change_event_publisher = None
        self.integrated_session_state = None
        self.selected_package = None
        self.selected_dictionary = None
        self.selected_class = None
        self.selected_method_category = None
        self.selected_method_symbol = None
        self.show_instance_side = True
        self.browse_mode = "dictionaries"

    def set_integrated_session_state(self, integrated_session_state):
        self.integrated_session_state = integrated_session_state

    def require_write_access(self, operation_name):
        if self.integrated_session_state is None:
            return
        if not self.integrated_session_state.is_mcp_busy():
            return
        mcp_operation_name = (
            self.integrated_session_state.current_mcp_operation_name() or "unknown"
        )
        raise DomainException(
            (
                "IDE is read-only while MCP operation %s is active. "
                "Retry %s after MCP finishes."
            )
            % (
                mcp_operation_name,
                operation_name,
            )
        )

    def publish_model_change(self, change_kind):
        if self.change_event_publisher is None:
            return
        self.change_event_publisher(change_kind)

    def select_package(self, package):
        self.selected_package = package
        self.select_class(None)

    def select_dictionary(self, dictionary_name):
        self.selected_dictionary = dictionary_name
        self.select_class(None)

    def select_class_category(self, category_name):
        if self.browse_mode == "dictionaries":
            self.selected_package = None
            self.select_dictionary(category_name)
            return
        self.selected_dictionary = None
        self.select_package(category_name)

    def selected_class_category(self):
        if self.browse_mode == "dictionaries":
            return self.selected_dictionary
        return self.selected_package

    @property
    def rowan_installed(self):
        return self.gemstone_browser_session.rowan_installed()

    def select_browse_mode(self, browse_mode):
        browse_mode = browse_mode.strip().lower()
        valid_modes = ("dictionaries", "categories", "rowan")
        if browse_mode not in valid_modes:
            raise DomainException(
                "browse_mode must be dictionaries, categories, or rowan."
            )
        if browse_mode == "rowan" and not self.rowan_installed:
            raise DomainException("Rowan is not installed on this stone.")
        if self.browse_mode == browse_mode:
            return
        self.browse_mode = browse_mode
        self.selected_package = None
        self.selected_dictionary = None
        self.selected_class = None
        self.selected_method_category = None
        self.selected_method_symbol = None
        self.publish_model_change("packages")
        self.publish_model_change("classes")
        self.publish_model_change("methods")

    def select_instance_side(self, show_instance_side):
        self.show_instance_side = show_instance_side
        self.select_method_category(None)

    def select_class(self, selected_class):
        self.selected_class = selected_class
        self.select_method_category(None)

    def select_method_category(self, selected_method_category):
        self.selected_method_category = selected_method_category
        self.select_method_symbol(None)

    def select_method_symbol(self, selected_method_symbol):
        self.selected_method_symbol = selected_method_symbol

    def commit(self):
        self.require_write_access("commit")
        self.gemstone_session.commit()

    def abort(self):
        self.require_write_access("abort")
        self.gemstone_session.abort()

    @classmethod
    def log_in_rpc(
        cls,
        gemstone_user_name,
        gemstone_password,
        rpc_hostname,
        stone_name,
        netldi_name,
    ):
        nrs_string = f"!@{rpc_hostname}#netldi:{netldi_name}!gemnetobject"
        logging.getLogger(__name__).debug(
            f"Logging in with: {gemstone_user_name} stone_name={stone_name} netldi_task={nrs_string}"
        )
        try:
            gemstone_session = RPCSession(
                gemstone_user_name,
                gemstone_password,
                stone_name=stone_name,
                netldi_task=nrs_string,
            )
        except GemstoneError as e:
            raise DomainException("Gemstone error: %s" % e)
        return cls(gemstone_session)

    @classmethod
    def log_in_linked(cls, gemstone_user_name, gemstone_password, stone_name):
        logging.getLogger(__name__).debug(
            f"Logging in with: {gemstone_user_name} stone_name={stone_name}"
        )
        try:
            gemstone_session = LinkedSession(
                gemstone_user_name, gemstone_password, stone_name=stone_name
            )
        except GemstoneError as e:
            raise DomainException("Gemstone error: %s" % e)
        return cls(gemstone_session)

    @property
    def stone_name(self):
        return self.gemstone_session.System.stoneName().to_py

    @property
    def host_name(self):
        return self.gemstone_session.System.hostname().to_py

    @property
    def user_name(self):
        return self.gemstone_session.System.myUserProfile().userId().to_py

    @property
    def session_id(self):
        # self.gemstone_session.System.session() returns our self.gemstone_session itself, not the id we want
        return self.gemstone_session.execute("System session").to_py

    def __str__(self):
        return f"{self.session_id}: {self.user_name} on {self.stone_name} at server {self.host_name}"

    def log_out(self):
        self.gemstone_browser_session.clear_stored_breakpoints()
        self.gemstone_session.log_out()

    @property
    def class_organizer(self):
        return self.gemstone_browser_session.class_organizer

    @property
    def class_categories(self):
        if self.browse_mode == "dictionaries":
            yield from self.gemstone_browser_session.list_dictionaries()
            return
        if self.browse_mode == "categories":
            yield from self.gemstone_browser_session.list_categories()
            return
        yield from self.gemstone_browser_session.list_rowan_packages()

    def create_and_install_package(self, package_name):
        self.require_write_access("create_and_install_package")
        self.gemstone_browser_session.create_and_install_package(package_name)
        self.publish_model_change("packages")

    def delete_package(self, package_name):
        self.require_write_access("delete_package")
        self.gemstone_browser_session.delete_package(package_name)
        if self.selected_package == package_name:
            self.selected_package = None
            self.selected_class = None
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change("packages")

    def create_class(
        self,
        class_name,
        superclass_name="Object",
        in_dictionary=None,
    ):
        self.require_write_access("create_class")
        selected_dictionary = in_dictionary
        if selected_dictionary is None:
            if self.browse_mode == "dictionaries":
                selected_dictionary = self.selected_dictionary or "UserGlobals"
            else:
                selected_dictionary = "UserGlobals"
        self.gemstone_browser_session.create_class(
            class_name=class_name,
            superclass_name=superclass_name,
            in_dictionary=selected_dictionary,
        )
        self.publish_model_change("classes")

    def delete_class(self, class_name, in_dictionary=None):
        self.require_write_access("delete_class")
        selected_dictionary = in_dictionary
        if selected_dictionary is None:
            if self.browse_mode == "dictionaries":
                selected_dictionary = self.selected_dictionary or "UserGlobals"
            else:
                selected_dictionary = "UserGlobals"
        self.gemstone_browser_session.delete_class(
            class_name,
            in_dictionary=selected_dictionary,
        )
        if self.selected_class == class_name:
            self.selected_class = None
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change("classes")

    def get_classes_in_category(self, category):
        if self.browse_mode == "dictionaries":
            yield from self.gemstone_browser_session.list_classes_in_dictionary(
                category
            )
            return
        if self.browse_mode == "categories":
            yield from self.gemstone_browser_session.list_classes_in_category(category)
            return
        yield from self.gemstone_browser_session.list_classes_in_rowan_package(category)

    def get_categories_in_class(self, class_name, show_instance_side):
        categories = self.gemstone_browser_session.list_method_categories(
            class_name,
            show_instance_side,
        )
        if categories and categories[0] == "all":
            categories = categories[1:]
        yield from categories

    def create_method_category(
        self,
        class_name,
        show_instance_side,
        method_category,
    ):
        self.require_write_access("create_method_category")
        self.gemstone_browser_session.create_method_category(
            class_name,
            method_category,
            show_instance_side,
        )
        self.publish_model_change("methods")

    def delete_method_category(
        self,
        class_name,
        show_instance_side,
        method_category,
    ):
        self.require_write_access("delete_method_category")
        self.gemstone_browser_session.delete_method_category(
            class_name,
            method_category,
            show_instance_side,
        )
        if self.selected_method_category == method_category:
            self.selected_method_category = None
            self.selected_method_symbol = None
        self.publish_model_change("methods")

    def get_selectors_in_class(self, class_name, method_category, show_instance_side):
        yield from self.gemstone_browser_session.list_methods(
            class_name,
            method_category,
            show_instance_side,
        )

    def get_method(self, class_name, show_instance_side, method_symbol):
        try:
            return self.gemstone_browser_session.get_compiled_method(
                class_name,
                method_symbol,
                show_instance_side,
            )
        except GemstoneError:
            return

    def class_category_containing_class(self, class_name):
        selected_category = self.selected_class_category()
        if selected_category:
            classes_in_selected_category = list(
                self.get_classes_in_category(selected_category)
            )
            if class_name in classes_in_selected_category:
                return selected_category
        all_categories = list(self.class_categories)
        matching_category = None
        category_index = 0
        while category_index < len(all_categories) and matching_category is None:
            category_name = all_categories[category_index]
            classes_in_category = list(self.get_classes_in_category(category_name))
            if class_name in classes_in_category:
                matching_category = category_name
            category_index += 1
        return matching_category

    def jump_to_class(self, class_name, show_instance_side):
        selected_gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        selected_category = self.class_category_containing_class(class_name)
        if selected_category is None:
            selected_category = selected_gemstone_class.category().to_py
        self.select_class_category(selected_category)
        self.select_instance_side(show_instance_side)
        self.select_class(class_name)

    def jump_to_method(self, class_name, show_instance_side, method_symbol):
        selected_gemstone_class = self.gemstone_session.resolve_symbol(class_name)
        selected_package = selected_gemstone_class.category().to_py
        selected_method_category = self.gemstone_browser_session.get_method_category(
            class_name,
            method_symbol,
            show_instance_side,
        )
        self.select_package(selected_package)
        self.select_class(class_name)
        self.select_instance_side(show_instance_side)
        self.select_method_category(selected_method_category)
        self.select_method_symbol(method_symbol)

    def get_current_methods(self):
        return list(
            self.get_selectors_in_class(
                self.selected_class,
                self.selected_method_category,
                self.show_instance_side,
            )
        )

    def find_class_names_matching(self, search_input, should_stop=None):
        yield from self.gemstone_browser_session.find_classes(
            search_input,
            should_stop=should_stop,
        )

    def find_selectors_matching(self, search_input, should_stop=None):
        yield from self.gemstone_browser_session.find_selectors(
            search_input,
            should_stop=should_stop,
        )

    def find_class_references(self, class_name):
        class_reference_search_result = (
            self.gemstone_browser_session.find_class_references(class_name)
        )
        yield from [
            (
                reference["class_name"],
                reference["show_instance_side"],
                reference["method_selector"],
            )
            for reference in class_reference_search_result["references"]
        ]

    def find_implementors_of_method(self, method_name):
        yield from [
            (
                implementor["class_name"],
                not implementor["show_instance_side"],
            )
            for implementor in self.gemstone_browser_session.find_implementors(
                method_name
            )
        ]

    def sender_entries_for_method(
        self,
        method_name,
        include_category_details=False,
    ):
        sender_search_result = self.gemstone_browser_session.find_senders(
            method_name,
            include_category_details=include_category_details,
        )
        return sender_search_result["senders"]

    def find_senders_of_method(self, method_name):
        yield from [
            (
                sender["class_name"],
                sender["show_instance_side"],
                sender["method_selector"],
            )
            for sender in self.sender_entries_for_method(method_name)
        ]

    def plan_sender_evidence_tests(
        self,
        method_name,
        max_depth=2,
        max_nodes=500,
        max_senders_per_selector=200,
        max_test_methods=200,
        max_elapsed_ms=1500,
        should_stop=None,
        on_candidate_test=None,
    ):
        return self.gemstone_browser_session.sender_test_plan_for_selector(
            method_name,
            max_depth,
            max_nodes,
            max_senders_per_selector,
            max_test_methods,
            max_elapsed_ms=max_elapsed_ms,
            should_stop=should_stop,
            on_candidate_test=on_candidate_test,
        )

    def collect_sender_evidence_from_tests(
        self,
        method_name,
        selected_tests,
        max_traced_senders=250,
        max_observed_results=500,
        receiver_class_name=None,
        receiver_show_instance_side=True,
    ):
        self.require_write_access('collect_sender_evidence_from_tests')
        trace_result = None
        observed_result = None
        untrace_result = None
        test_runs = []
        tracer_enabled = False
        trace_installed = False
        self.gemstone_browser_session.ensure_tracer_manifest_matches()
        self.gemstone_browser_session.enable_tracer()
        tracer_enabled = True
        try:
            if receiver_class_name is not None:
                trace_result = self.gemstone_browser_session.trace_implementation(
                    receiver_class_name,
                    receiver_show_instance_side,
                    method_name,
                )
                if not trace_result.get('instrumented'):
                    trace_result = self.gemstone_browser_session.trace_selector(
                        method_name,
                        max_results=max_traced_senders,
                    )
                    trace_result['fallback_reason'] = (
                        '%s does not define %s — tracing all implementors instead.'
                        % (receiver_class_name, method_name)
                    )
            else:
                trace_result = self.gemstone_browser_session.trace_selector(
                    method_name,
                    max_results=max_traced_senders,
                )
            trace_installed = True
            self.gemstone_browser_session.clear_observed_senders(method_name)
            for selected_test in selected_tests:
                test_case_class_name = selected_test['test_case_class_name']
                test_method_selector = selected_test['test_method_selector']
                test_result = self.run_test_method(
                    test_case_class_name,
                    test_method_selector,
                )
                test_runs.append(
                    {
                        'test_case_class_name': test_case_class_name,
                        'test_method_selector': test_method_selector,
                        'depth': selected_test.get('depth'),
                        'tests_passed': test_result['has_passed'],
                        'result': test_result,
                    }
                )
            observed_result = (
                self.gemstone_browser_session.observed_senders_for_selector(
                    method_name,
                    max_results=max_observed_results,
                    count_only=False,
                )
            )
        finally:
            if trace_installed:
                try:
                    untrace_result = self.gemstone_browser_session.untrace_selector(
                        method_name
                    )
                except (
                    GemstoneDomainException,
                    GemstoneError,
                ):
                    untrace_result = None
            if tracer_enabled:
                try:
                    self.gemstone_browser_session.disable_tracer()
                except (
                    GemstoneDomainException,
                    GemstoneError,
                ):
                    pass
        return {
            'method_name': method_name,
            'trace': trace_result,
            'test_runs': test_runs,
            'observed': observed_result,
            'untrace': untrace_result,
        }

    def method_sends(self, class_name, method_selector, show_instance_side):
        return self.gemstone_browser_session.method_sends(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_structure_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        return self.gemstone_browser_session.method_structure_summary(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_control_flow_summary(
        self,
        class_name,
        method_selector,
        show_instance_side,
    ):
        return self.gemstone_browser_session.method_control_flow_summary(
            class_name,
            method_selector,
            show_instance_side,
        )

    def method_ast(self, class_name, method_selector, show_instance_side):
        return self.gemstone_browser_session.method_ast(
            class_name,
            method_selector,
            show_instance_side,
        )

    def preview_method_rename(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        return self.gemstone_browser_session.method_rename_preview(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )

    def apply_method_rename(
        self,
        class_name,
        show_instance_side,
        old_selector,
        new_selector,
    ):
        self.require_write_access("apply_method_rename")
        rename_result = self.gemstone_browser_session.apply_method_rename(
            class_name,
            show_instance_side,
            old_selector,
            new_selector,
        )
        self.publish_model_change("methods")
        return rename_result

    def preview_method_move(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
    ):
        return self.gemstone_browser_session.method_move_preview(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
        )

    def apply_method_move(
        self,
        source_class_name,
        source_show_instance_side,
        target_class_name,
        target_show_instance_side,
        method_selector,
        overwrite_target_method=False,
        delete_source_method=True,
    ):
        self.require_write_access("apply_method_move")
        move_result = self.gemstone_browser_session.apply_method_move(
            source_class_name,
            source_show_instance_side,
            target_class_name,
            target_show_instance_side,
            method_selector,
            overwrite_target_method=overwrite_target_method,
            delete_source_method=delete_source_method,
        )
        self.publish_model_change("methods")
        return move_result

    def preview_method_add_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        return self.gemstone_browser_session.method_add_parameter_preview(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )

    def apply_method_add_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        parameter_name,
        default_argument_source,
    ):
        self.require_write_access("apply_method_add_parameter")
        add_parameter_result = self.gemstone_browser_session.apply_method_add_parameter(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            parameter_name,
            default_argument_source,
        )
        self.publish_model_change("methods")
        return add_parameter_result

    def preview_method_remove_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        rewrite_source_senders=False,
    ):
        return self.gemstone_browser_session.method_remove_parameter_preview(
            class_name,
            show_instance_side,
            method_selector,
            parameter_keyword,
            rewrite_source_senders=rewrite_source_senders,
        )

    def apply_method_remove_parameter(
        self,
        class_name,
        show_instance_side,
        method_selector,
        parameter_keyword,
        overwrite_new_method=False,
        rewrite_source_senders=False,
    ):
        self.require_write_access("apply_method_remove_parameter")
        remove_parameter_result = (
            self.gemstone_browser_session.apply_method_remove_parameter(
                class_name,
                show_instance_side,
                method_selector,
                parameter_keyword,
                overwrite_new_method=overwrite_new_method,
                rewrite_source_senders=rewrite_source_senders,
            )
        )
        self.publish_model_change("methods")
        return remove_parameter_result

    def preview_method_extract(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
    ):
        return self.gemstone_browser_session.method_extract_preview(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
        )

    def apply_method_extract(
        self,
        class_name,
        show_instance_side,
        method_selector,
        new_selector,
        statement_indexes,
        overwrite_new_method=False,
    ):
        self.require_write_access("apply_method_extract")
        extract_result = self.gemstone_browser_session.apply_method_extract(
            class_name,
            show_instance_side,
            method_selector,
            new_selector,
            statement_indexes,
            overwrite_new_method=overwrite_new_method,
        )
        self.publish_model_change("methods")
        return extract_result

    def preview_method_inline(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
    ):
        return self.gemstone_browser_session.method_inline_preview(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
        )

    def apply_method_inline(
        self,
        class_name,
        show_instance_side,
        caller_selector,
        inline_selector,
        delete_inlined_method=False,
    ):
        self.require_write_access("apply_method_inline")
        inline_result = self.gemstone_browser_session.apply_method_inline(
            class_name,
            show_instance_side,
            caller_selector,
            inline_selector,
            delete_inlined_method=delete_inlined_method,
        )
        self.publish_model_change("methods")
        return inline_result

    def update_method_source(
        self, selected_class, show_instance_side, method_symbol, source
    ):
        self.require_write_access("update_method_source")
        self.gemstone_browser_session.compile_method(
            selected_class,
            show_instance_side,
            source,
        )
        self.publish_model_change("methods")

    def create_method(
        self,
        selected_class,
        show_instance_side,
        source,
        method_category="as yet unclassified",
    ):
        self.require_write_access("create_method")
        self.gemstone_browser_session.compile_method(
            selected_class,
            show_instance_side,
            source,
            method_category=method_category,
        )
        self.publish_model_change("methods")

    def delete_method(self, selected_class, show_instance_side, method_selector):
        self.require_write_access("delete_method")
        self.gemstone_browser_session.delete_method(
            selected_class,
            method_selector,
            show_instance_side,
        )
        if self.selected_method_symbol == method_selector:
            self.selected_method_symbol = None
        self.publish_model_change("methods")

    def run_code(self, source):
        self.require_write_access("run_code")
        return self.gemstone_browser_session.run_code(source)

    def resolve_object(self, source):
        return self.gemstone_browser_session.run_code(source)

    def run_gemstone_tests(self, class_name):
        self.require_write_access("run_gemstone_tests")
        return self.gemstone_browser_session.run_gemstone_tests(class_name)

    def run_test_method(self, class_name, method_selector):
        self.require_write_access("run_test_method")
        return self.gemstone_browser_session.run_test_method(
            class_name, method_selector
        )

    def debug_test_method(self, class_name, method_selector):
        self.require_write_access("debug_test_method")
        return self.gemstone_browser_session.debug_test_method(
            class_name, method_selector
        )

    def set_breakpoint(
        self,
        class_name,
        show_instance_side,
        method_selector,
        source_offset,
    ):
        self.require_write_access("set_breakpoint")
        return self.gemstone_browser_session.set_breakpoint(
            class_name,
            method_selector,
            show_instance_side,
            source_offset,
        )

    def clear_breakpoint(self, breakpoint_id):
        self.require_write_access("clear_breakpoint")
        return self.gemstone_browser_session.clear_breakpoint(breakpoint_id)

    def clear_breakpoint_at(
        self,
        class_name,
        show_instance_side,
        method_selector,
        source_offset,
    ):
        self.require_write_access("clear_breakpoint_at")
        return self.gemstone_browser_session.clear_breakpoint_at(
            class_name,
            method_selector,
            show_instance_side,
            source_offset,
        )

    def list_breakpoints(self):
        return self.gemstone_browser_session.list_breakpoints()

    def clear_all_breakpoints(self):
        self.require_write_access("clear_all_breakpoints")
        return self.gemstone_browser_session.clear_all_breakpoints()

# except GemstoneError as e:
#     try:
#         e.context.gciStepOverFromLevel(1)
#     except GemstoneError as ex:
#         result = ex.continue_with()


class UiDispatcher:
    def __init__(self, root):
        self.root = root
        self.pending_callbacks = deque()
        self.lock = threading.RLock()
        self.flush_scheduled = False

    def dispatch(self, callback, *args, **kwargs):
        should_schedule_flush = False
        with self.lock:
            self.pending_callbacks.append((callback, args, kwargs))
            should_schedule_flush = not self.flush_scheduled
            if should_schedule_flush:
                self.flush_scheduled = True
        if should_schedule_flush:
            try:
                self.root.after(0, self.flush_pending_callbacks)
            except tk.TclError:
                with self.lock:
                    self.flush_scheduled = False

    def flush_pending_callbacks(self):
        pending_callbacks = []
        with self.lock:
            while self.pending_callbacks:
                pending_callbacks.append(self.pending_callbacks.popleft())
            self.flush_scheduled = False
        for callback, args, kwargs in pending_callbacks:
            callback(*args, **kwargs)


class BusyCoordinator:
    def __init__(self):
        self.lock = threading.RLock()
        self.active_lease_token = 0
        self.next_lease_token = 0
        self.active_operation_name = ''
        self.busy = False

    def lease_for_state(self, is_busy=False, operation_name=''):
        with self.lock:
            if is_busy:
                operation_changed = operation_name != self.active_operation_name
                if not self.busy or operation_changed:
                    self.next_lease_token = self.next_lease_token + 1
                    self.active_lease_token = self.next_lease_token
                self.busy = True
                self.active_operation_name = operation_name
                return self.active_lease_token
            self.busy = False
            self.active_operation_name = ''
            self.active_lease_token = 0
            return self.active_lease_token

    def is_current_lease(self, lease_token):
        with self.lock:
            if lease_token is None:
                return True
            if self.busy:
                return lease_token == self.active_lease_token
            return lease_token == 0


class ActionGate:
    def __init__(self):
        self.actions_blocked_while_busy = {
            'session',
            'run',
            'breakpoints',
            'run_editor_source',
            'method_editor_source',
            'ide_write',
            'mcp_stop',
        }

    def allows(self, action_name, is_busy=False):
        if is_busy and action_name in self.actions_blocked_while_busy:
            return False
        return True

    def state_for(self, action_name, is_busy=False):
        if self.allows(action_name, is_busy=is_busy):
            return tk.NORMAL
        return tk.DISABLED

    def read_only_for(self, action_name, is_busy=False):
        return not self.allows(action_name, is_busy=is_busy)

class EventQueue:
    def __init__(self, root):
        self.root = root
        self.events = {}
        self.queue = deque()
        self.queue_lock = threading.RLock()
        self.root_thread_ident = threading.get_ident()
        self.wakeup_read_descriptor = None
        self.wakeup_write_descriptor = None
        self.processing_events = False
        self.ui_dispatcher = UiDispatcher(self.root)
        self.root.bind('<<CustomEventsPublished>>', self.schedule_event_processing)
        self.configure_cross_thread_wakeup()

    def schedule_event_processing(self, event=None):
        self.ui_dispatcher.dispatch(self.process_events)

    def subscription_is_active(self, ui_context, context_snapshot):
        if ui_context is None:
            return True
        if context_snapshot is None:
            return False
        return ui_context.matches(context_snapshot)

    def configure_cross_thread_wakeup(self):
        supports_filehandler = hasattr(self.root, "createfilehandler")
        if not supports_filehandler:
            return
        try:
            read_descriptor, write_descriptor = os.pipe()
            os.set_blocking(read_descriptor, False)
            os.set_blocking(write_descriptor, False)
            self.root.createfilehandler(
                read_descriptor,
                tk.READABLE,
                self.process_cross_thread_wakeup,
            )
            self.wakeup_read_descriptor = read_descriptor
            self.wakeup_write_descriptor = write_descriptor
        except (AttributeError, OSError):
            self.wakeup_read_descriptor = None
            self.wakeup_write_descriptor = None

    def callback_reference_for(self, callback):
        try:
            return weakref.WeakMethod(callback)
        except TypeError:
            return weakref.ref(callback)

    def subscribe(self, event_name, callback, *args, ui_context=None):
        context_snapshot = None
        if ui_context is not None:
            context_snapshot = ui_context.snapshot()
        self.events.setdefault(event_name, [])
        self.events[event_name].append(
            (
                self.callback_reference_for(callback),
                args,
                ui_context,
                context_snapshot,
            )
        )

    def publish(self, event_name, *args, **kwargs):
        if event_name in self.events:
            with self.queue_lock:
                self.queue.append((event_name, args, kwargs))
        if threading.get_ident() == self.root_thread_ident:
            if self.processing_events:
                return
            self.process_events()
            return
        self.publish_cross_thread_wakeup()

    def publish_cross_thread_wakeup(self):
        if self.wakeup_write_descriptor is not None:
            try:
                os.write(self.wakeup_write_descriptor, b"1")
            except OSError:
                pass
            return
        try:
            self.root.event_generate("<<CustomEventsPublished>>")
        except tk.TclError:
            pass

    def process_cross_thread_wakeup(self, file_descriptor, wakeup_mask):
        if self.wakeup_read_descriptor is not None:
            while True:
                try:
                    wakeup_payload = os.read(self.wakeup_read_descriptor, 1024)
                except BlockingIOError:
                    break
                except OSError:
                    break
                if wakeup_payload == b"":
                    break
                if len(wakeup_payload) < 1024:
                    break
        self.schedule_event_processing()

    def process_events(self):
        if self.processing_events:
            return
        self.processing_events = True
        try:
            while True:
                with self.queue_lock:
                    if not self.queue:
                        break
                    event_name, args, kwargs = self.queue.popleft()
                if event_name in self.events:
                    logging.getLogger(__name__).debug(f"Processing: {event_name}")
                    retained_callbacks = []
                    for (
                        weak_callback,
                        callback_args,
                        ui_context,
                        context_snapshot,
                    ) in self.events[event_name]:
                        callback = weak_callback()
                        callback_is_live = callback is not None
                        context_is_active = self.subscription_is_active(
                            ui_context,
                            context_snapshot,
                        )
                        if callback_is_live and context_is_active:
                            retained_callbacks.append(
                                (
                                    weak_callback,
                                    callback_args,
                                    ui_context,
                                    context_snapshot,
                                )
                            )
                            logging.getLogger(__name__).debug(f"Calling: {callback}")
                            callback(*callback_args, *args, **kwargs)
                    self.events[event_name] = retained_callbacks
        finally:
            self.processing_events = False

    def clear_subscribers(self, owner):
        for event_name, registered_callbacks in self.events.copy().items():
            cleaned_callbacks = []
            for (
                weak_callback,
                callback_args,
                ui_context,
                context_snapshot,
            ) in registered_callbacks:
                callback = weak_callback()
                callback_is_live = callback is not None
                owner_matches = False
                if callback_is_live:
                    owner_matches = getattr(callback, "__self__", None) is owner
                if callback_is_live and not owner_matches:
                    cleaned_callbacks.append(
                        (
                            weak_callback,
                            callback_args,
                            ui_context,
                            context_snapshot,
                        )
                    )
            self.events[event_name] = cleaned_callbacks

    def close(self):
        if self.wakeup_read_descriptor is not None and hasattr(
            self.root, "deletefilehandler"
        ):
            try:
                self.root.deletefilehandler(self.wakeup_read_descriptor)
            except tk.TclError:
                pass
        if self.wakeup_read_descriptor is not None:
            try:
                os.close(self.wakeup_read_descriptor)
            except OSError:
                pass
            self.wakeup_read_descriptor = None
        if self.wakeup_write_descriptor is not None:
            try:
                os.close(self.wakeup_write_descriptor)
            except OSError:
                pass
            self.wakeup_write_descriptor = None


MCP_RUNTIME_CONFIG_SCHEMA_VERSION = 2
MCP_RUNTIME_CONFIG_FILE_NAME = "mcp.json"
MCP_PERMISSION_POLICY_CONFIG_NAME = "mcp_permission_policy"
MCP_PERMISSION_POLICY_SOURCE_NAME = (
    "allow_session_permission_changes_condition_source"
)


class McpPermissionPolicy:
    def __init__(self, allow_session_permission_changes_condition_source=""):
        self.allow_session_permission_changes_condition_source = (
            str(allow_session_permission_changes_condition_source).strip()
        )

    def copy(self):
        return McpPermissionPolicy(
            allow_session_permission_changes_condition_source=(
                self.allow_session_permission_changes_condition_source
            )
        )

    @classmethod
    def from_dict(cls, config_payload):
        if config_payload is None:
            return cls()
        return cls(
            allow_session_permission_changes_condition_source=str(
                config_payload.get(MCP_PERMISSION_POLICY_SOURCE_NAME, "")
            ).strip()
        )

    def to_dict(self):
        if not self.allow_session_permission_changes_condition_source:
            return {}
        return {
            MCP_PERMISSION_POLICY_SOURCE_NAME: (
                self.allow_session_permission_changes_condition_source
            )
        }

    def has_session_permission_change_condition(self):
        return bool(self.allow_session_permission_changes_condition_source)

    def session_permission_changes_allowed_for(self, gemstone_session_record):
        if not self.has_session_permission_change_condition():
            return False
        evaluation_result = gemstone_session_record.run_code(
            self.allow_session_permission_changes_condition_source
        )
        if isinstance(evaluation_result, bool):
            return evaluation_result
        python_value = getattr(evaluation_result, "to_py", None)
        if callable(python_value):
            python_value = python_value()
        if isinstance(python_value, bool):
            return python_value
        if isinstance(python_value, str):
            normalized_value = python_value.strip().lower()
            if normalized_value == "true":
                return True
            if normalized_value == "false":
                return False
        raise DomainException(
            "Configured MCP permission condition must answer true or false."
        )


class McpConfigurationAccess:
    def __init__(
        self,
        permission_controls_editable=True,
        configuration_persistable=True,
        note="",
    ):
        self.permission_controls_editable = bool(permission_controls_editable)
        self.configuration_persistable = bool(configuration_persistable)
        self.note = str(note)


class McpConfigurationStore:
    def config_home_directory(self):
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if xdg_config_home:
            return xdg_config_home
        return os.path.join(os.path.expanduser("~"), ".config")

    def config_file_path(self):
        return os.path.join(
            self.config_home_directory(),
            "swordfish",
            MCP_RUNTIME_CONFIG_FILE_NAME,
        )

    def validate_config_dict(self, config_payload):
        if not isinstance(config_payload, dict):
            raise ValueError("mcp_runtime_config must be an object.")
        if "mcp_host" in config_payload:
            mcp_host = str(config_payload["mcp_host"]).strip()
            if not mcp_host:
                raise ValueError("mcp_host cannot be empty.")
        if "mcp_port" in config_payload:
            mcp_port = config_payload["mcp_port"]
            if isinstance(mcp_port, bool) or not isinstance(mcp_port, int):
                raise ValueError("mcp_port must be an integer.")
            if mcp_port <= 0:
                raise ValueError("mcp_port must be greater than zero.")
        if "mcp_http_path" in config_payload:
            mcp_http_path = str(config_payload["mcp_http_path"]).strip()
            if not mcp_http_path.startswith("/"):
                raise ValueError("mcp_http_path must start with '/'.")
        return config_payload

    def validate_permission_policy_dict(self, config_payload):
        if config_payload is None:
            return {}
        if not isinstance(config_payload, dict):
            raise ValueError("mcp_permission_policy must be an object.")
        if MCP_PERMISSION_POLICY_SOURCE_NAME in config_payload:
            config_payload = dict(config_payload)
            config_payload[MCP_PERMISSION_POLICY_SOURCE_NAME] = str(
                config_payload[MCP_PERMISSION_POLICY_SOURCE_NAME]
            ).strip()
        return config_payload

    def config_payload(self):
        config_file_path = self.config_file_path()
        if not os.path.exists(config_file_path):
            return None
        try:
            with open(config_file_path, "r", encoding="utf-8") as config_file:
                payload = json.load(config_file)
        except (OSError, TypeError, json.JSONDecodeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        schema_version = payload.get(
            "schema_version",
            MCP_RUNTIME_CONFIG_SCHEMA_VERSION,
        )
        if schema_version != MCP_RUNTIME_CONFIG_SCHEMA_VERSION:
            return None
        return payload

    def load(self):
        payload = self.config_payload()
        if payload is None:
            return None
        try:
            config_payload = payload.get("mcp_runtime_config")
            validated_payload = self.validate_config_dict(config_payload)
            return McpRuntimeConfig.from_dict(validated_payload)
        except (ValueError, TypeError):
            return None

    def load_permission_policy(self):
        payload = self.config_payload()
        if payload is None:
            return McpPermissionPolicy()
        try:
            validated_payload = self.validate_permission_policy_dict(
                payload.get(MCP_PERMISSION_POLICY_CONFIG_NAME)
            )
            return McpPermissionPolicy.from_dict(validated_payload)
        except (ValueError, TypeError):
            return McpPermissionPolicy()

    def can_write_config(self):
        config_file_path = self.config_file_path()
        if os.path.exists(config_file_path):
            return os.access(config_file_path, os.W_OK)
        config_directory = os.path.dirname(config_file_path)
        if os.path.isdir(config_directory):
            return os.access(config_directory, os.W_OK)
        config_home_directory = self.config_home_directory()
        if os.path.isdir(config_home_directory):
            return os.access(config_home_directory, os.W_OK)
        return os.access(os.path.expanduser("~"), os.W_OK)

    def save(self, runtime_config, permission_policy=None):
        if permission_policy is None:
            permission_policy = self.load_permission_policy()
        permission_policy_payload = permission_policy.to_dict()
        payload = {
            "schema_version": MCP_RUNTIME_CONFIG_SCHEMA_VERSION,
            "mcp_runtime_config": runtime_config.to_dict(),
        }
        if permission_policy_payload:
            payload[MCP_PERMISSION_POLICY_CONFIG_NAME] = permission_policy_payload
        config_file_path = self.config_file_path()
        config_directory = os.path.dirname(config_file_path)
        temporary_file_path = config_file_path + ".tmp"
        try:
            os.makedirs(config_directory, exist_ok=True)
            with open(temporary_file_path, "w", encoding="utf-8") as config_file:
                json.dump(payload, config_file, indent=2, sort_keys=True)
                config_file.write("\n")
            os.replace(temporary_file_path, config_file_path)
            os.chmod(config_file_path, 0o600)
        except OSError as error:
            try:
                os.remove(temporary_file_path)
            except OSError:
                pass
            raise DomainException(
                "Unable to save MCP configuration to %s: %s" % (config_file_path, error)
            )

    def argument_is_explicitly_set(self, argument_tokens, option_name):
        option_prefix = option_name + "="
        for argument_token in argument_tokens:
            if argument_token == option_name:
                return True
            if argument_token.startswith(option_prefix):
                return True
        return False

    def explicit_overrides_from_argument_tokens(self, argument_tokens):
        explicit_overrides = {}
        if self.argument_is_explicitly_set(argument_tokens, "--allow-source-read"):
            explicit_overrides["allow_source_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--disallow-source-read"):
            explicit_overrides["allow_source_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-source-write"):
            explicit_overrides["allow_source_write"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-eval-arbitrary"):
            explicit_overrides["allow_eval_arbitrary"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-ide-read"):
            explicit_overrides["allow_ide_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--disallow-ide-read"):
            explicit_overrides["allow_ide_read"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-ide-write"):
            explicit_overrides["allow_ide_write"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-test-execution"):
            explicit_overrides["allow_test_execution"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-commit"):
            explicit_overrides["allow_commit"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--allow-tracing"):
            explicit_overrides["allow_tracing"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--require-gemstone-ast"):
            explicit_overrides["require_gemstone_ast"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--mcp-host"):
            explicit_overrides["mcp_host"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--mcp-port"):
            explicit_overrides["mcp_port"] = True
        if self.argument_is_explicitly_set(argument_tokens, "--mcp-http-path"):
            explicit_overrides["mcp_http_path"] = True
        return explicit_overrides

    def config_from_arguments(self, arguments):
        return McpRuntimeConfig(
            allow_source_read=getattr(arguments, "allow_source_read", True),
            allow_source_write=getattr(arguments, "allow_source_write", False),
            allow_eval_arbitrary=getattr(arguments, "allow_eval_arbitrary", False),
            allow_test_execution=getattr(arguments, "allow_test_execution", False),
            allow_ide_read=getattr(arguments, "allow_ide_read", True),
            allow_ide_write=getattr(arguments, "allow_ide_write", False),
            allow_commit=getattr(arguments, "allow_commit", False),
            allow_tracing=getattr(arguments, "allow_tracing", False),
            require_gemstone_ast=getattr(arguments, "require_gemstone_ast", False),
            mcp_host=getattr(arguments, "mcp_host", "127.0.0.1"),
            mcp_port=getattr(arguments, "mcp_port", 8000),
            mcp_http_path=getattr(arguments, "mcp_http_path", "/mcp"),
        )

    def merged_config_from_arguments(
        self,
        arguments,
        argument_tokens=None,
        persisted_runtime_config=None,
    ):
        cli_runtime_config = self.config_from_arguments(arguments)
        if persisted_runtime_config is None:
            persisted_runtime_config = self.load()
        if persisted_runtime_config is None:
            return cli_runtime_config
        if argument_tokens is None:
            argument_tokens = []
        explicit_overrides = self.explicit_overrides_from_argument_tokens(
            argument_tokens
        )
        if len(explicit_overrides) < 1:
            return persisted_runtime_config.copy()
        merged_runtime_config = persisted_runtime_config.copy()
        merged_runtime_config.update_with(
            allow_source_read=(
                cli_runtime_config.allow_source_read
                if explicit_overrides.get("allow_source_read")
                else None
            ),
            allow_source_write=(
                cli_runtime_config.allow_source_write
                if explicit_overrides.get("allow_source_write")
                else None
            ),
            allow_eval_arbitrary=(
                cli_runtime_config.allow_eval_arbitrary
                if explicit_overrides.get("allow_eval_arbitrary")
                else None
            ),
            allow_test_execution=(
                cli_runtime_config.allow_test_execution
                if explicit_overrides.get("allow_test_execution")
                else None
            ),
            allow_ide_read=(
                cli_runtime_config.allow_ide_read
                if explicit_overrides.get("allow_ide_read")
                else None
            ),
            allow_ide_write=(
                cli_runtime_config.allow_ide_write
                if explicit_overrides.get("allow_ide_write")
                else None
            ),
            allow_commit=(
                cli_runtime_config.allow_commit
                if explicit_overrides.get("allow_commit")
                else None
            ),
            allow_tracing=(
                cli_runtime_config.allow_tracing
                if explicit_overrides.get("allow_tracing")
                else None
            ),
            require_gemstone_ast=(
                cli_runtime_config.require_gemstone_ast
                if explicit_overrides.get("require_gemstone_ast")
                else None
            ),
            mcp_host=(
                cli_runtime_config.mcp_host
                if explicit_overrides.get("mcp_host")
                else None
            ),
            mcp_port=(
                cli_runtime_config.mcp_port
                if explicit_overrides.get("mcp_port")
                else None
            ),
            mcp_http_path=(
                cli_runtime_config.mcp_http_path
                if explicit_overrides.get("mcp_http_path")
                else None
            ),
        )
        return merged_runtime_config


class McpRuntimeConfig:
    def __init__(
        self,
        allow_source_read=True,
        allow_source_write=False,
        allow_eval_arbitrary=False,
        allow_test_execution=False,
        allow_ide_read=True,
        allow_ide_write=False,
        allow_commit=False,
        allow_tracing=False,
        require_gemstone_ast=False,
        mcp_host="127.0.0.1",
        mcp_port=8000,
        mcp_http_path="/mcp",
    ):
        self.allow_source_read = allow_source_read
        self.allow_source_write = allow_source_write
        self.allow_eval_arbitrary = allow_eval_arbitrary
        self.allow_test_execution = allow_test_execution
        self.allow_ide_read = allow_ide_read
        self.allow_ide_write = allow_ide_write
        self.allow_commit = allow_commit
        self.allow_tracing = allow_tracing
        self.require_gemstone_ast = require_gemstone_ast
        self.mcp_host = mcp_host
        self.mcp_port = mcp_port
        self.mcp_http_path = mcp_http_path

    def copy(self):
        return McpRuntimeConfig(
            allow_source_read=self.allow_source_read,
            allow_source_write=self.allow_source_write,
            allow_eval_arbitrary=self.allow_eval_arbitrary,
            allow_test_execution=self.allow_test_execution,
            allow_ide_read=self.allow_ide_read,
            allow_ide_write=self.allow_ide_write,
            allow_commit=self.allow_commit,
            allow_tracing=self.allow_tracing,
            require_gemstone_ast=self.require_gemstone_ast,
            mcp_host=self.mcp_host,
            mcp_port=self.mcp_port,
            mcp_http_path=self.mcp_http_path,
        )

    @classmethod
    def from_dict(cls, config_payload):
        return cls(
            allow_source_read=bool(config_payload.get("allow_source_read", True)),
            allow_source_write=bool(config_payload.get("allow_source_write", False)),
            allow_eval_arbitrary=bool(
                config_payload.get("allow_eval_arbitrary", False)
            ),
            allow_test_execution=bool(
                config_payload.get("allow_test_execution", False)
            ),
            allow_ide_read=bool(config_payload.get("allow_ide_read", True)),
            allow_ide_write=bool(config_payload.get("allow_ide_write", False)),
            allow_commit=bool(config_payload.get("allow_commit", False)),
            allow_tracing=bool(config_payload.get("allow_tracing", False)),
            require_gemstone_ast=bool(
                config_payload.get("require_gemstone_ast", False)
            ),
            mcp_host=str(config_payload.get("mcp_host", "127.0.0.1")).strip(),
            mcp_port=int(config_payload.get("mcp_port", 8000)),
            mcp_http_path=str(config_payload.get("mcp_http_path", "/mcp")).strip(),
        )

    def to_dict(self):
        return {
            "allow_source_read": bool(self.allow_source_read),
            "allow_source_write": bool(self.allow_source_write),
            "allow_eval_arbitrary": bool(self.allow_eval_arbitrary),
            "allow_test_execution": bool(self.allow_test_execution),
            "allow_ide_read": bool(self.allow_ide_read),
            "allow_ide_write": bool(self.allow_ide_write),
            "allow_commit": bool(self.allow_commit),
            "allow_tracing": bool(self.allow_tracing),
            "require_gemstone_ast": bool(self.require_gemstone_ast),
            "mcp_host": self.mcp_host,
            "mcp_port": self.mcp_port,
            "mcp_http_path": self.mcp_http_path,
        }

    def __eq__(self, other):
        if not isinstance(other, McpRuntimeConfig):
            return False
        return self.to_dict() == other.to_dict()

    def endpoint_url(self):
        return "http://%s:%s%s" % (
            self.mcp_host,
            self.mcp_port,
            self.mcp_http_path,
        )

    def update_with(
        self,
        allow_source_read=None,
        allow_source_write=None,
        allow_eval_arbitrary=None,
        allow_test_execution=None,
        allow_ide_read=None,
        allow_ide_write=None,
        allow_commit=None,
        allow_tracing=None,
        require_gemstone_ast=None,
        mcp_host=None,
        mcp_port=None,
        mcp_http_path=None,
    ):
        if allow_source_read is not None:
            self.allow_source_read = bool(allow_source_read)
        if allow_source_write is not None:
            self.allow_source_write = bool(allow_source_write)
        if allow_eval_arbitrary is not None:
            self.allow_eval_arbitrary = bool(allow_eval_arbitrary)
        if allow_test_execution is not None:
            self.allow_test_execution = bool(allow_test_execution)
        if allow_ide_read is not None:
            self.allow_ide_read = bool(allow_ide_read)
        if allow_ide_write is not None:
            self.allow_ide_write = bool(allow_ide_write)
        if allow_commit is not None:
            self.allow_commit = bool(allow_commit)
        if allow_tracing is not None:
            self.allow_tracing = bool(allow_tracing)
        if require_gemstone_ast is not None:
            self.require_gemstone_ast = bool(require_gemstone_ast)
        if mcp_host is not None:
            self.mcp_host = mcp_host
        if mcp_port is not None:
            self.mcp_port = mcp_port
        if mcp_http_path is not None:
            self.mcp_http_path = mcp_http_path


class McpServerController:
    def __init__(
        self,
        integrated_session_state,
        runtime_config,
        configuration_store=None,
    ):
        self.integrated_session_state = integrated_session_state
        if configuration_store is None:
            configuration_store = McpConfigurationStore()
        self.configuration_store = configuration_store
        self.runtime_config = runtime_config.copy()
        self.applied_runtime_config = None
        self.lock = threading.RLock()
        self.server_thread = None
        self.uvicorn_server = None
        self.last_error_message = ""
        self.starting = False
        self.stopping = False
        self.running = False
        self.shutdown_requested = False
        self.server_state_subscribers = []

    def current_runtime_config(self):
        with self.lock:
            return self.runtime_config.copy()

    def update_runtime_config(self, runtime_config):
        with self.lock:
            self.runtime_config = runtime_config.copy()

    def save_configuration(self, permission_policy=None):
        self.configuration_store.save(
            self.current_runtime_config(),
            permission_policy=permission_policy,
        )

    def status(self):
        with self.lock:
            configured_endpoint_url = self.runtime_config.endpoint_url()
            active_endpoint_url = configured_endpoint_url
            if self.applied_runtime_config is not None:
                active_endpoint_url = self.applied_runtime_config.endpoint_url()
            restart_required_for_config = False
            if self.running and self.applied_runtime_config is not None:
                restart_required_for_config = (
                    self.runtime_config != self.applied_runtime_config
                )
            return {
                "running": self.running,
                "starting": self.starting,
                "stopping": self.stopping,
                "last_error_message": self.last_error_message,
                "endpoint_url": active_endpoint_url,
                "configured_endpoint_url": configured_endpoint_url,
                "restart_required_for_config": restart_required_for_config,
            }

    def callback_reference_for(self, callback):
        try:
            return weakref.WeakMethod(callback)
        except TypeError:
            return weakref.ref(callback)

    def subscribe_server_state(self, callback):
        with self.lock:
            self.server_state_subscribers.append(self.callback_reference_for(callback))

    def live_callbacks_from_references(self, callback_references):
        callbacks = []
        live_callback_references = []
        for callback_reference in callback_references:
            callback = callback_reference()
            if callback is None:
                continue
            callbacks.append(callback)
            live_callback_references.append(callback_reference)
        return callbacks, live_callback_references

    def notify_server_state_subscribers(self):
        callbacks = []
        status_payload = self.status()
        with self.lock:
            callbacks, live_callback_references = self.live_callbacks_from_references(
                self.server_state_subscribers
            )
            self.server_state_subscribers = live_callback_references
        for callback in callbacks:
            callback(
                running=status_payload["running"],
                starting=status_payload["starting"],
                stopping=status_payload["stopping"],
                endpoint_url=status_payload["endpoint_url"],
                last_error_message=status_payload["last_error_message"],
            )

    def clear_subscribers(self, owner):
        with self.lock:
            self.server_state_subscribers = self.cleaned_subscribers_for_owner(
                self.server_state_subscribers,
                owner,
            )

    def cleaned_subscribers_for_owner(self, callback_references, owner):
        cleaned_callback_references = []
        for callback_reference in callback_references:
            callback = callback_reference()
            if callback is None:
                continue
            callback_owner = getattr(callback, "__self__", None)
            if callback_owner is owner:
                continue
            cleaned_callback_references.append(callback_reference)
        return cleaned_callback_references

    def start(self):
        with self.lock:
            if self.running or self.starting:
                return False
            self.starting = True
            self.stopping = False
            self.shutdown_requested = False
            self.last_error_message = ""
            self.server_thread = threading.Thread(
                target=self.run_server,
                daemon=True,
                name="SwordfishMCP",
            )
            self.server_thread.start()
        self.notify_server_state_subscribers()
        return True

    def stop(self):
        server_thread = None
        with self.lock:
            server = self.uvicorn_server
            if server is None and not self.running and not self.starting:
                return False
            self.starting = False
            self.stopping = True
            self.shutdown_requested = True
            server_thread = self.server_thread
            if server is not None:
                server.should_exit = True
        self.notify_server_state_subscribers()
        if (
            server_thread is not None
            and server_thread.is_alive()
            and threading.current_thread() is not server_thread
        ):
            wait_thread = threading.Thread(
                target=self.wait_for_server_thread_exit,
                args=(server_thread,),
                daemon=True,
                name="SwordfishMCPStopWait",
            )
            wait_thread.start()
        return True

    def stop_for_session_reset(self):
        with self.lock:
            server_thread = self.server_thread
        stopped = self.stop()
        if not stopped:
            return False
        if (
            server_thread is not None
            and server_thread.is_alive()
            and threading.current_thread() is not server_thread
        ):
            self.wait_for_server_thread_exit(server_thread)
        return True

    def wait_for_server_thread_exit(self, server_thread):
        server_thread.join(timeout=5)

    def server_for_runtime_config(self, runtime_config):
        return create_server(
            allow_source_read=runtime_config.allow_source_read,
            allow_source_write=runtime_config.allow_source_write,
            allow_eval_arbitrary=runtime_config.allow_eval_arbitrary,
            allow_test_execution=runtime_config.allow_test_execution,
            allow_ide_read=runtime_config.allow_ide_read,
            allow_ide_write=runtime_config.allow_ide_write,
            allow_commit=runtime_config.allow_commit,
            allow_tracing=runtime_config.allow_tracing,
            integrated_session_state=self.integrated_session_state,
            require_gemstone_ast=runtime_config.require_gemstone_ast,
            mcp_host=runtime_config.mcp_host,
            mcp_port=runtime_config.mcp_port,
            mcp_streamable_http_path=runtime_config.mcp_http_path,
        )

    def run(self, transport):
        local_runtime_config = self.current_runtime_config()
        mcp_server = self.server_for_runtime_config(local_runtime_config)
        mcp_server.run(transport=transport)

    def run_server(self):
        local_runtime_config = self.current_runtime_config()
        with self.lock:
            if self.shutdown_requested:
                self.starting = False
                self.stopping = False
                self.server_thread = None
                self.notify_server_state_subscribers()
                return
        try:
            mcp_server = self.server_for_runtime_config(local_runtime_config)
            import uvicorn

            streamable_http_application = mcp_server.streamable_http_app()
            uvicorn_config = uvicorn.Config(
                streamable_http_application,
                host=local_runtime_config.mcp_host,
                port=local_runtime_config.mcp_port,
                log_level=mcp_server.settings.log_level.lower(),
            )
            server = uvicorn.Server(uvicorn_config)
            with self.lock:
                self.uvicorn_server = server
                self.applied_runtime_config = local_runtime_config.copy()
                self.running = True
                self.starting = False
                self.last_error_message = ""
                if self.shutdown_requested:
                    server.should_exit = True
            self.notify_server_state_subscribers()
            asyncio.run(server.serve())
        except (
            McpDependencyNotInstalled,
            ImportError,
            ModuleNotFoundError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            with self.lock:
                self.last_error_message = str(error)
            self.notify_server_state_subscribers()
        finally:
            with self.lock:
                self.running = False
                self.starting = False
                self.stopping = False
                self.uvicorn_server = None
                self.server_thread = None
                self.applied_runtime_config = None
            self.notify_server_state_subscribers()


class McpConfigurationDialog(tk.Toplevel):
    def __init__(self, parent, current_runtime_config, configuration_access=None):
        super().__init__(parent)
        self.parent = parent
        self.current_runtime_config = current_runtime_config.copy()
        if configuration_access is None:
            configuration_access = McpConfigurationAccess()
        self.configuration_access = configuration_access
        self.result = None
        self.title("MCP Configuration")
        self.geometry("500x620")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.host_variable = tk.StringVar(value=self.current_runtime_config.mcp_host)
        self.port_variable = tk.StringVar(
            value=str(self.current_runtime_config.mcp_port)
        )
        self.path_variable = tk.StringVar(
            value=self.current_runtime_config.mcp_http_path
        )
        self.allow_source_read_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_source_read
        )
        self.allow_source_write_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_source_write
        )
        self.allow_eval_arbitrary_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_eval_arbitrary
        )
        self.allow_test_execution_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_test_execution
        )
        self.allow_ide_read_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_ide_read
        )
        self.allow_ide_write_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_ide_write
        )
        self.allow_commit_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_commit
        )
        self.allow_tracing_variable = tk.BooleanVar(
            value=self.current_runtime_config.allow_tracing
        )
        self.require_gemstone_ast_variable = tk.BooleanVar(
            value=self.current_runtime_config.require_gemstone_ast
        )
        self.permission_note_variable = tk.StringVar(
            value=self.configuration_access.note
        )
        self.risk_note_variable = tk.StringVar()

        self.create_widgets()
        for var in (
            self.allow_source_write_variable,
            self.allow_eval_arbitrary_variable,
            self.allow_test_execution_variable,
            self.allow_commit_variable,
        ):
            var.trace_add('write', self.update_risk_note)
        self.update_risk_note()

    def create_widgets(self):
        body_frame = ttk.Frame(self, padding=12)
        body_frame.grid(row=0, column=0, sticky="nsew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        permission_state = tk.NORMAL
        if not self.configuration_access.permission_controls_editable:
            permission_state = tk.DISABLED

        ttk.Label(body_frame, text="Host").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.host_variable).grid(
            row=1, column=0, sticky="ew", pady=(0, 10)
        )

        ttk.Label(body_frame, text="Port").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.port_variable).grid(
            row=3, column=0, sticky="ew", pady=(0, 10)
        )

        ttk.Label(body_frame, text="HTTP Path").grid(
            row=4, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Entry(body_frame, textvariable=self.path_variable).grid(
            row=5, column=0, sticky="ew", pady=(0, 12)
        )

        self.permission_note_label = ttk.Label(
            body_frame,
            textvariable=self.permission_note_variable,
            wraplength=440,
            justify="left",
        )
        self.permission_note_label.grid(row=6, column=0, sticky="w", pady=(0, 10))

        self.allow_source_read_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Allow source read tools",
            variable=self.allow_source_read_variable,
            state=permission_state,
        )
        self.allow_source_read_checkbutton.grid(row=7, column=0, sticky="w")
        self.allow_source_write_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Allow source write/refactor tools",
            variable=self.allow_source_write_variable,
            state=permission_state,
        )
        self.allow_source_write_checkbutton.grid(row=8, column=0, sticky="w")
        self.allow_eval_arbitrary_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Allow arbitrary eval tools",
            variable=self.allow_eval_arbitrary_variable,
            state=permission_state,
        )
        self.allow_eval_arbitrary_checkbutton.grid(row=9, column=0, sticky="w")
        self.allow_test_execution_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Allow test execution tools",
            variable=self.allow_test_execution_variable,
            state=permission_state,
        )
        self.allow_test_execution_checkbutton.grid(row=10, column=0, sticky="w")
        self.allow_ide_read_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Allow IDE state read tools",
            variable=self.allow_ide_read_variable,
            state=permission_state,
        )
        self.allow_ide_read_checkbutton.grid(row=11, column=0, sticky="w")
        self.allow_ide_write_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Allow IDE state write tools",
            variable=self.allow_ide_write_variable,
            state=permission_state,
        )
        self.allow_ide_write_checkbutton.grid(row=12, column=0, sticky="w")
        self.allow_commit_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Enable commit tool",
            variable=self.allow_commit_variable,
            state=permission_state,
        )
        self.allow_commit_checkbutton.grid(row=13, column=0, sticky="w")
        self.allow_tracing_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Enable tracing tools",
            variable=self.allow_tracing_variable,
            state=permission_state,
        )
        self.allow_tracing_checkbutton.grid(row=14, column=0, sticky="w")
        self.require_gemstone_ast_checkbutton = ttk.Checkbutton(
            body_frame,
            text="Require GemStone AST backend",
            variable=self.require_gemstone_ast_variable,
            state=permission_state,
        )
        self.require_gemstone_ast_checkbutton.grid(row=15, column=0, sticky="w")

        self.risk_note_label = ttk.Label(
            body_frame,
            textvariable=self.risk_note_variable,
            wraplength=440,
            justify="left",
        )
        self.risk_note_label.grid(row=16, column=0, sticky="w", pady=(12, 0))

        button_frame = ttk.Frame(body_frame)
        button_frame.grid(row=17, column=0, sticky="e", pady=(16, 0))
        ttk.Button(
            button_frame,
            text="Cancel",
            command=self.cancel_dialog,
        ).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(
            button_frame,
            text="Apply",
            command=self.apply_configuration,
        ).grid(row=0, column=1)
        body_frame.columnconfigure(0, weight=1)

    def compute_risk_note(self):
        source_write = self.allow_source_write_variable.get()
        eval_arbitrary = self.allow_eval_arbitrary_variable.get()
        test_execution = self.allow_test_execution_variable.get()
        commit = self.allow_commit_variable.get()
        lines = []
        if source_write and eval_arbitrary and commit:
            lines.append(
                'Code: AI can write, compile, execute, and permanently install code changes.'
            )
        elif source_write and eval_arbitrary:
            lines.append('Code: AI can write, compile, and execute Smalltalk code freely.')
        elif eval_arbitrary:
            lines.append('Code: AI can execute arbitrary Smalltalk code.')
        elif source_write and commit:
            lines.append('Code: AI can compile and permanently install method changes.')
        elif source_write:
            lines.append('Code: AI can compile method changes (lost on abort without commit).')
        if eval_arbitrary and commit:
            lines.append('Data: AI can read and permanently modify client data.')
        elif eval_arbitrary:
            lines.append('Data: AI can read and modify client data in memory.')
        elif source_write and test_execution and commit:
            lines.append(
                'Data: AI can read and permanently modify client data'
                ' by writing and running a custom test.'
            )
        elif source_write and test_execution:
            lines.append(
                'Data: AI can read and modify client data in memory'
                ' by writing and running a custom test.'
            )
        elif test_execution and commit:
            lines.append(
                'Data: Existing tests may expose or permanently modify client data they touch.'
            )
        elif test_execution:
            lines.append(
                'Data: Existing tests may expose or modify client data they happen to touch.'
            )
        if lines:
            return '\n'.join(lines)
        return '\u2713 Read-only code access \u2014 client data is not reachable.'

    def update_risk_note(self, *_):
        note = self.compute_risk_note()
        self.risk_note_variable.set(note)
        is_safe = note.startswith('\u2713')
        self.risk_note_label.configure(foreground='#006600' if is_safe else '#AA4400')

    def apply_configuration(self):
        port_text = self.port_variable.get().strip()
        if not port_text:
            messagebox.showerror("Invalid MCP configuration", "Port cannot be empty.")
            return
        if not port_text.isdigit():
            messagebox.showerror(
                "Invalid MCP configuration",
                "Port must be a positive integer.",
            )
            return
        mcp_port = int(port_text)
        if mcp_port <= 0:
            messagebox.showerror(
                "Invalid MCP configuration",
                "Port must be greater than zero.",
            )
            return
        mcp_host = self.host_variable.get().strip()
        if not mcp_host:
            messagebox.showerror(
                "Invalid MCP configuration",
                "Host cannot be empty.",
            )
            return
        mcp_http_path = self.path_variable.get().strip()
        if not mcp_http_path.startswith("/"):
            messagebox.showerror(
                "Invalid MCP configuration",
                "HTTP path must start with /.",
            )
            return
        allow_source_read = self.current_runtime_config.allow_source_read
        allow_source_write = self.current_runtime_config.allow_source_write
        allow_eval_arbitrary = self.current_runtime_config.allow_eval_arbitrary
        allow_test_execution = self.current_runtime_config.allow_test_execution
        allow_ide_read = self.current_runtime_config.allow_ide_read
        allow_ide_write = self.current_runtime_config.allow_ide_write
        allow_commit = self.current_runtime_config.allow_commit
        allow_tracing = self.current_runtime_config.allow_tracing
        require_gemstone_ast = self.current_runtime_config.require_gemstone_ast
        if self.configuration_access.permission_controls_editable:
            allow_source_read = self.allow_source_read_variable.get()
            allow_source_write = self.allow_source_write_variable.get()
            allow_eval_arbitrary = self.allow_eval_arbitrary_variable.get()
            allow_test_execution = self.allow_test_execution_variable.get()
            allow_ide_read = self.allow_ide_read_variable.get()
            allow_ide_write = self.allow_ide_write_variable.get()
            allow_commit = self.allow_commit_variable.get()
            allow_tracing = self.allow_tracing_variable.get()
            require_gemstone_ast = self.require_gemstone_ast_variable.get()
        self.result = McpRuntimeConfig(
            allow_source_read=allow_source_read,
            allow_source_write=allow_source_write,
            allow_eval_arbitrary=allow_eval_arbitrary,
            allow_test_execution=allow_test_execution,
            allow_ide_read=allow_ide_read,
            allow_ide_write=allow_ide_write,
            allow_commit=allow_commit,
            allow_tracing=allow_tracing,
            require_gemstone_ast=require_gemstone_ast,
            mcp_host=mcp_host,
            mcp_port=mcp_port,
            mcp_http_path=mcp_http_path,
        )
        self.destroy()

    def cancel_dialog(self):
        self.result = None
        self.destroy()


class MainMenu(tk.Menu):
    def __init__(self, parent, event_queue, **kwargs):
        super().__init__(parent, **kwargs)
        self.parent = parent
        self.event_queue = event_queue
        self.file_menu = tk.Menu(self, tearoff=0)
        self.session_menu = tk.Menu(self, tearoff=0)
        self.mcp_menu = tk.Menu(self, tearoff=0)

        self._create_menus()
        self._subscribe_events()

    def _create_menus(self):
        # File Menu
        self.add_cascade(label="File", menu=self.file_menu)
        self.update_file_menu()

        # Session Menu
        self.add_cascade(label="Session", menu=self.session_menu)
        self.update_session_menu()
        self.add_cascade(label="MCP", menu=self.mcp_menu)
        self.update_mcp_menu()

    def _subscribe_events(self):
        self.event_queue.subscribe("LoggedInSuccessfully", self.update_menus)
        self.event_queue.subscribe("LoggedOut", self.update_menus)
        self.event_queue.subscribe("McpBusyStateChanged", self.update_menus)
        self.event_queue.subscribe("McpServerStateChanged", self.update_menus)

    def update_menus(self, gemstone_session_record=None, **kwargs):
        self.update_session_menu()
        self.update_file_menu()
        self.update_mcp_menu()

    def update_session_menu(self):
        self.session_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            is_busy = self.parent.integrated_session_state.is_mcp_busy()
            menu_state = self.parent.action_gate.state_for('session', is_busy=is_busy)
            self.session_menu.add_command(
                label="Commit",
                command=self.parent.commit,
                state=menu_state,
            )
            self.session_menu.add_command(
                label="Abort",
                command=self.parent.abort,
                state=menu_state,
            )
            self.session_menu.add_command(
                label="Logout",
                command=self.parent.logout,
                state=menu_state,
            )
        else:
            self.session_menu.add_command(
                label="Login", command=self.parent.show_login_screen
            )

    def update_mcp_menu(self):
        self.mcp_menu.delete(0, tk.END)
        mcp_state = self.parent.embedded_mcp_server_status()
        start_state = tk.NORMAL
        if mcp_state["running"] or mcp_state["starting"] or mcp_state["stopping"]:
            start_state = tk.DISABLED
        stop_state = tk.NORMAL
        if (
            not mcp_state["running"]
            and not mcp_state["starting"]
            and not mcp_state["stopping"]
        ):
            stop_state = tk.DISABLED
        if mcp_state["stopping"]:
            stop_state = tk.DISABLED
        is_busy = self.parent.integrated_session_state.is_mcp_busy()
        if not self.parent.action_gate.allows('mcp_stop', is_busy=is_busy):
            stop_state = tk.DISABLED
        configure_state = tk.NORMAL
        if mcp_state["starting"] or mcp_state["stopping"]:
            configure_state = tk.DISABLED
        self.mcp_menu.add_command(
            label="Start MCP",
            command=self.start_mcp_server,
            state=start_state,
        )
        self.mcp_menu.add_command(
            label="Stop MCP",
            command=self.stop_mcp_server,
            state=stop_state,
        )
        self.mcp_menu.add_separator()
        self.mcp_menu.add_command(
            label="Configure MCP",
            command=self.configure_mcp_server,
            state=configure_state,
        )

    def update_file_menu(self):
        self.file_menu.delete(0, tk.END)
        if self.parent.is_logged_in:
            is_busy = self.parent.integrated_session_state.is_mcp_busy()
            run_command_state = self.parent.action_gate.state_for('run', is_busy=is_busy)
            breakpoints_state = self.parent.action_gate.state_for(
                'breakpoints',
                is_busy=is_busy,
            )
            self.file_menu.add_command(label="Find", command=self.show_find_dialog)
            self.file_menu.add_command(
                label="Implementors",
                command=self.show_find_implementors_dialog,
            )
            self.file_menu.add_command(
                label="Senders",
                command=self.show_find_senders_dialog,
            )
            self.file_menu.add_command(
                label="Run",
                command=self.show_run_dialog,
                state=run_command_state,
            )
            self.file_menu.add_command(
                label="Breakpoints",
                command=self.show_breakpoints_dialog,
                state=breakpoints_state,
            )
            self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.parent.quit)

    def show_find_dialog(self):
        self.parent.open_find_dialog()

    def show_find_implementors_dialog(self):
        self.parent.open_implementors_dialog()

    def show_find_senders_dialog(self):
        self.parent.open_senders_dialog()

    def show_run_dialog(self):
        self.parent.open_run_tab()

    def show_breakpoints_dialog(self):
        self.parent.open_breakpoints_dialog()

    def start_mcp_server(self):
        self.parent.start_mcp_server_from_menu()

    def stop_mcp_server(self):
        self.parent.stop_mcp_server_from_menu()

    def configure_mcp_server(self):
        self.parent.configure_mcp_server_from_menu()


class FindDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        search_type="class",
        search_query="",
        run_search=False,
        match_mode=None,
        reference_target=None,
        sender_source_class_name=None,
    ):
        super().__init__(parent)
        self.title("Find")
        self.geometry("720x560")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.parent = parent
        self.sender_source_class_name = sender_source_class_name
        self.method_reference_results = []
        self.navigation_method_results = []
        self.reference_method_selectors = []
        self.sender_tracing_selector = None
        self.static_sender_results = []
        self.sender_entries_by_navigation_result = {}
        self.last_reference_method_query = None
        self.last_reference_method_match_mode = None
        self.max_test_discovery_elapsed_ms = 120000
        self.status_var = tk.StringVar(value="")
        self.search_intent_var = tk.StringVar(value="")
        self.result_action_var = tk.StringVar(value="")
        self.find_operation_running = False
        self.find_stop_requested = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(7, weight=1)

        self.search_type = tk.StringVar(value="class")
        self.match_mode = tk.StringVar(value="contains")
        self.reference_target = tk.StringVar(value="class")
        ttk.Label(self, text="Search Type:").grid(
            row=0,
            column=0,
            padx=10,
            pady=5,
            sticky="w",
        )
        self.search_type_frame = ttk.Frame(self)
        self.search_type_frame.grid(
            row=0,
            column=1,
            columnspan=5,
            padx=(0, 10),
            pady=5,
            sticky="w",
        )
        self.class_radio = ttk.Radiobutton(
            self.search_type_frame,
            text="Class",
            variable=self.search_type,
            value="class",
        )
        self.class_radio.pack(side="left", padx=(0, 8))
        self.method_radio = ttk.Radiobutton(
            self.search_type_frame,
            text="Method",
            variable=self.search_type,
            value="method",
        )
        self.method_radio.pack(side="left", padx=(0, 8))
        self.reference_radio = ttk.Radiobutton(
            self.search_type_frame,
            text="References",
            variable=self.search_type,
            value="reference",
        )
        self.reference_radio.pack(side="left", padx=(0, 8))

        ttk.Label(self, text="Match:").grid(
            row=1,
            column=0,
            padx=10,
            pady=5,
            sticky="w",
        )
        self.match_mode_frame = ttk.Frame(self)
        self.match_mode_frame.grid(
            row=1,
            column=1,
            columnspan=2,
            padx=(0, 10),
            pady=5,
            sticky="w",
        )
        self.match_contains_radio = ttk.Radiobutton(
            self.match_mode_frame,
            text="Contains",
            variable=self.match_mode,
            value="contains",
        )
        self.match_contains_radio.pack(side="left", padx=(0, 8))
        self.match_exact_radio = ttk.Radiobutton(
            self.match_mode_frame,
            text="Exact",
            variable=self.match_mode,
            value="exact",
        )
        self.match_exact_radio.pack(side="left")

        self.reference_target_label = ttk.Label(
            self,
            text="Reference target:",
        )
        self.reference_target_label.grid(
            row=1,
            column=3,
            padx=(10, 6),
            pady=5,
            sticky="e",
        )
        self.reference_target_frame = ttk.Frame(self)
        self.reference_target_frame.grid(
            row=1,
            column=4,
            columnspan=2,
            padx=(0, 10),
            pady=5,
            sticky="w",
        )
        self.reference_target_class_radio = ttk.Radiobutton(
            self.reference_target_frame,
            text="Class",
            variable=self.reference_target,
            value="class",
        )
        self.reference_target_class_radio.pack(side="left", padx=(0, 8))
        self.reference_target_method_radio = ttk.Radiobutton(
            self.reference_target_frame,
            text="Method",
            variable=self.reference_target,
            value="method",
        )
        self.reference_target_method_radio.pack(side="left")

        ttk.Label(self, text="Find what:").grid(
            row=2,
            column=0,
            padx=10,
            pady=10,
            sticky="w",
        )
        self.find_entry = ttk.Entry(self)
        self.find_entry.grid(
            row=2,
            column=1,
            columnspan=5,
            padx=10,
            pady=10,
            sticky="ew",
        )
        self.find_entry.bind(
            "<KeyRelease>",
            lambda *_: self.update_search_context_fields(),
        )

        ttk.Label(self, text="Search intent:").grid(
            row=3,
            column=0,
            padx=10,
            pady=(0, 2),
            sticky="w",
        )
        self.search_intent_label = ttk.Label(
            self,
            textvariable=self.search_intent_var,
            anchor="w",
        )
        self.search_intent_label.grid(
            row=3,
            column=1,
            columnspan=5,
            padx=10,
            pady=(0, 2),
            sticky="ew",
        )

        ttk.Label(self, text="Result action:").grid(
            row=4,
            column=0,
            padx=10,
            pady=(0, 2),
            sticky="w",
        )
        self.result_action_label = ttk.Label(
            self,
            textvariable=self.result_action_var,
            anchor="w",
        )
        self.result_action_label.grid(
            row=4,
            column=1,
            columnspan=5,
            padx=10,
            pady=(0, 2),
            sticky="ew",
        )

        self.button_frame = ttk.Frame(self)
        self.button_frame.grid(row=5, column=0, columnspan=6, pady=10)
        self.button_frame.grid_columnconfigure(0, weight=1)
        self.button_frame.grid_columnconfigure(1, weight=1)
        self.button_frame.grid_columnconfigure(2, weight=1)
        self.button_frame.grid_columnconfigure(3, weight=1)
        self.button_frame.grid_columnconfigure(4, weight=1)

        self.find_button = ttk.Button(
            self.button_frame,
            text="Find",
            command=self.find_text,
        )
        self.find_button.grid(row=0, column=0, padx=5)

        self.stop_button = ttk.Button(
            self.button_frame,
            text="Stop",
            command=self.request_stop_find,
            state=tk.DISABLED,
        )
        self.stop_button.grid(row=0, column=1, padx=5)

        self.narrow_button = ttk.Button(
            self.button_frame,
            text="Narrow With Tracing",
            command=self.narrow_senders_with_tracing,
        )
        self.narrow_button.grid(row=0, column=2, padx=5)

        self.narrow_to_source_class_button = ttk.Button(
            self.button_frame,
            text="Narrow to Source Class",
            command=self.narrow_to_source_class_button_clicked,
        )
        self.narrow_to_source_class_button.grid(row=0, column=3, padx=5)

        self.cancel_button = ttk.Button(
            self.button_frame,
            text="Cancel",
            command=self.destroy,
        )
        self.cancel_button.grid(row=0, column=4, padx=5)

        self.filter_frame = ttk.Frame(self)
        self.filter_frame.grid(
            row=6,
            column=0,
            columnspan=6,
            padx=10,
            pady=(0, 4),
            sticky="ew",
        )
        ttk.Label(self.filter_frame, text="Filter by class (regex):").pack(
            side="left", padx=(0, 4)
        )
        self.class_regex_entry = ttk.Entry(self.filter_frame, width=20)
        self.class_regex_entry.pack(side="left", padx=(0, 12))
        ttk.Label(self.filter_frame, text="Filter by category (regex):").pack(
            side="left", padx=(0, 4)
        )
        self.category_regex_entry = ttk.Entry(self.filter_frame, width=20)
        self.category_regex_entry.pack(side="left", padx=(0, 12))
        self.apply_regex_filter_button = ttk.Button(
            self.filter_frame,
            text="Apply Filter",
            command=self.apply_regex_filter_button_clicked,
        )
        self.apply_regex_filter_button.pack(side="left")

        self.results_listbox = tk.Listbox(self)
        self.results_listbox.grid(
            row=7,
            column=0,
            columnspan=6,
            padx=10,
            pady=(10, 4),
            sticky="nsew",
        )
        self.results_listbox.bind("<Double-Button-1>", self.on_result_double_click)

        self.status_label = ttk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
        )
        self.status_label.grid(
            row=8,
            column=0,
            columnspan=6,
            padx=10,
            pady=(0, 10),
            sticky="ew",
        )

        configuration = self.resolved_search_configuration(
            search_type,
            match_mode,
            reference_target,
        )
        self.search_type.trace_add(
            "write",
            lambda *_: self.update_mode_controls(),
        )
        self.match_mode.trace_add(
            "write",
            lambda *_: self.update_mode_controls(),
        )
        self.reference_target.trace_add(
            "write",
            lambda *_: self.update_mode_controls(),
        )
        self.search_type.set(configuration["search_type"])
        self.match_mode.set(configuration["match_mode"])
        self.reference_target.set(configuration["reference_target"])
        if search_query:
            self.find_entry.delete(0, tk.END)
            self.find_entry.insert(0, search_query)
        self.update_mode_controls()
        self.set_find_operation_state(False)
        self.update_search_context_fields()
        if run_search:
            self.find_text()

    @property
    def gemstone_session_record(self):
        return self.parent.gemstone_session_record

    def resolved_search_configuration(
        self,
        search_type,
        match_mode,
        reference_target,
    ):
        configuration = {
            "search_type": "class",
            "match_mode": "contains",
            "reference_target": "class",
        }
        if search_type in ["class", "method", "reference"]:
            configuration["search_type"] = search_type
        if search_type == "class_reference":
            configuration["search_type"] = "reference"
            configuration["reference_target"] = "class"
            configuration["match_mode"] = "exact"
        if search_type == "implementor":
            configuration["search_type"] = "method"
            configuration["match_mode"] = "exact"
        if search_type == "sender":
            configuration["search_type"] = "reference"
            configuration["reference_target"] = "method"
            configuration["match_mode"] = "exact"
        if match_mode in ["exact", "contains"]:
            configuration["match_mode"] = match_mode
        if reference_target in ["class", "method"]:
            configuration["reference_target"] = reference_target
        if configuration["search_type"] == "reference":
            configuration["match_mode"] = "exact"
        return configuration

    def update_mode_controls(self):
        search_type = self.search_type.get()
        reference_mode_is_selected = search_type == "reference"
        if reference_mode_is_selected and self.match_mode.get() != "exact":
            self.match_mode.set("exact")
            return
        reference_target_is_method = self.reference_target.get() == "method"
        tracing_controls_visible = (
            reference_mode_is_selected and reference_target_is_method
        )
        contains_match_state = tk.NORMAL
        exact_match_state = tk.NORMAL
        if reference_mode_is_selected:
            contains_match_state = tk.DISABLED
        if self.find_operation_running:
            contains_match_state = tk.DISABLED
            exact_match_state = tk.DISABLED
        self.match_contains_radio.config(state=contains_match_state)
        self.match_exact_radio.config(state=exact_match_state)
        if reference_mode_is_selected:
            self.reference_target_label.grid()
            self.reference_target_frame.grid()
        else:
            self.reference_target_label.grid_remove()
            self.reference_target_frame.grid_remove()
        if tracing_controls_visible:
            self.narrow_button.grid()
            self.narrow_to_source_class_button.grid()
            self.filter_frame.grid()
            self.status_label.grid()
        else:
            self.narrow_button.grid_remove()
            self.narrow_to_source_class_button.grid_remove()
            self.filter_frame.grid_remove()
            self.status_label.grid_remove()
            self.status_var.set("")
        self.update_trace_narrow_state()
        self.update_search_context_fields()

    def update_trace_narrow_state(self):
        source_class_known = self.sender_source_class_name is not None
        can_trace = bool(self.sender_tracing_selector) and source_class_known
        can_narrow_to_source = source_class_known
        if self.search_type.get() != "reference":
            can_trace = False
            can_narrow_to_source = False
        if self.reference_target.get() != "method":
            can_trace = False
            can_narrow_to_source = False
        if self.find_operation_running:
            can_trace = False
            can_narrow_to_source = False
        self.narrow_button.config(state=tk.NORMAL if can_trace else tk.DISABLED)
        self.narrow_to_source_class_button.config(
            state=tk.NORMAL if can_narrow_to_source else tk.DISABLED
        )

    def set_find_operation_state(self, is_running):
        self.find_operation_running = is_running
        self.find_button.config(state=tk.DISABLED if is_running else tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL if is_running else tk.DISABLED)
        self.cancel_button.config(state=tk.DISABLED if is_running else tk.NORMAL)
        mode_control_state = tk.DISABLED if is_running else tk.NORMAL
        self.find_entry.config(state=mode_control_state)
        self.class_radio.config(state=mode_control_state)
        self.method_radio.config(state=mode_control_state)
        self.reference_radio.config(state=mode_control_state)
        contains_match_state = mode_control_state
        if not is_running and self.search_type.get() == "reference":
            contains_match_state = tk.DISABLED
        self.match_contains_radio.config(state=contains_match_state)
        self.match_exact_radio.config(state=mode_control_state)
        self.reference_target_class_radio.config(state=mode_control_state)
        self.reference_target_method_radio.config(state=mode_control_state)
        self.update_trace_narrow_state()
        self.update_search_context_fields()

    def request_stop_find(self):
        if self.find_operation_running:
            self.find_stop_requested = True
            self.status_var.set("Stopping find...")

    def find_should_stop(self):
        if not self.find_operation_running:
            return False
        self.update_idletasks()
        try:
            self.update()
        except tk.TclError:
            return True
        return self.find_stop_requested

    def finish_stopped_find(self):
        self.status_var.set("Find stopped. Showing partial results.")
        self.sender_tracing_selector = None

    def format_method_navigation_label(
        self,
        class_name,
        show_instance_side,
        method_selector,
    ):
        class_side_label = ""
        if not show_instance_side:
            class_side_label = " class"
        return "%s%s>>%s" % (
            class_name,
            class_side_label,
            method_selector,
        )

    def class_match_query_pattern(self, query_text, match_mode):
        escaped_query = re.escape(query_text)
        if match_mode == "exact":
            return "^%s$" % escaped_query
        return escaped_query

    def class_names_for_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        class_pattern = self.class_match_query_pattern(
            query_text,
            match_mode,
        )
        return list(
            self.gemstone_session_record.find_class_names_matching(
                class_pattern,
                should_stop=should_stop,
            )
        )

    def selector_names_for_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        if match_mode == "exact":
            return [query_text]
        return list(
            self.gemstone_session_record.find_selectors_matching(
                query_text,
                should_stop=should_stop,
            )
        )

    def references_for_class_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        class_names = [query_text]
        reference_results = []
        for class_name in class_names:
            if should_stop is not None and should_stop():
                return self.unique_sorted_navigation_results(reference_results)
            reference_results += list(
                self.gemstone_session_record.find_class_references(class_name)
            )
        return self.unique_sorted_navigation_results(reference_results)

    def references_for_method_query(
        self,
        query_text,
        match_mode,
        should_stop=None,
    ):
        selector_names = [query_text]
        sender_entries = []
        for selector_name in selector_names:
            if should_stop is not None and should_stop():
                (
                    sender_results,
                    sender_entries_by_result,
                ) = self.record_sender_entries_for_navigation(sender_entries)
                return (
                    sender_results,
                    selector_names,
                    sender_entries_by_result,
                )
            sender_entries += list(
                self.gemstone_session_record.sender_entries_for_method(
                    selector_name,
                    include_category_details=True,
                )
            )
        sender_results, sender_entries_by_result = (
            self.record_sender_entries_for_navigation(sender_entries)
        )
        return (
            sender_results,
            selector_names,
            sender_entries_by_result,
        )

    def unique_sorted_navigation_results(self, method_results):
        unique_result_by_key = {}
        for class_name, show_instance_side, method_selector in method_results:
            result_key = (
                class_name,
                show_instance_side,
                method_selector,
            )
            unique_result_by_key[result_key] = result_key
        return sorted(unique_result_by_key.values())

    def activity_message_for_search(
        self,
        search_type,
        match_mode,
        reference_target,
        search_query,
    ):
        if search_type == "class":
            if match_mode == "exact":
                return "Finding class %s..." % search_query
            return "Finding classes matching %s..." % search_query
        if search_type == "method":
            if match_mode == "exact":
                return "Finding implementors of %s..." % search_query
            return "Finding methods matching %s..." % search_query
        if reference_target == "class":
            return "Finding references to class %s..." % search_query
        return "Finding references to method %s..." % search_query

    def search_intent_text(
        self,
        search_type,
        match_mode,
        reference_target,
        normalized_search_query,
    ):
        if not normalized_search_query:
            return 'Enter text to search.'
        if search_type == 'class':
            if match_mode == 'exact':
                return 'Class exactly "%s".' % normalized_search_query
            return 'Classes containing "%s".' % normalized_search_query
        if search_type == 'method':
            if match_mode == 'exact':
                return 'Implementors of method "%s".' % normalized_search_query
            return 'Methods containing selector "%s".' % normalized_search_query
        if reference_target == 'class':
            return 'References to class "%s" (exact).' % normalized_search_query
        if self.sender_source_class_name is not None:
            return 'Senders of %s>>%s.' % (self.sender_source_class_name, normalized_search_query)
        return 'Senders of "%s" (all implementors).' % normalized_search_query

    def result_action_text(self, search_type, match_mode, reference_target):
        if self.find_operation_running:
            return "Search in progress. Click Stop to cancel."
        if search_type == "class":
            return "Double-click a class to navigate."
        if search_type == "method":
            if match_mode == "exact":
                return "Double-click an implementor to open the method."
            return "Double-click a selector to find implementors (exact)."
        if reference_target == "method":
            return "Double-click a reference to open the caller method."
        return "Double-click a reference to open the method."

    def update_search_context_fields(self):
        search_type = self.search_type.get()
        match_mode = self.match_mode.get()
        if search_type == "reference":
            match_mode = "exact"
        reference_target = self.reference_target.get()
        normalized_search_query = self.find_entry.get().strip()
        self.search_intent_var.set(
            self.search_intent_text(
                search_type,
                match_mode,
                reference_target,
                normalized_search_query,
            )
        )
        self.result_action_var.set(
            self.result_action_text(
                search_type,
                match_mode,
                reference_target,
            )
        )

    def display_results(self, results):
        self.results_listbox.delete(0, tk.END)
        for result in results:
            self.results_listbox.insert(tk.END, result)
        self.results_listbox.grid()

    def populate_navigation_results(self, method_results):
        self.navigation_method_results = list(method_results)
        self.display_results(
            [
                self.format_method_navigation_label(
                    class_name,
                    show_instance_side,
                    method_selector,
                )
                for class_name, show_instance_side, method_selector in (
                    self.navigation_method_results
                )
            ]
        )

    def record_sender_entries_for_navigation(self, sender_entries):
        sender_results = [
            (
                sender_entry['class_name'],
                sender_entry['show_instance_side'],
                sender_entry['method_selector'],
            )
            for sender_entry in sender_entries
        ]
        sender_entries_by_result = {}
        for sender_entry in sender_entries:
            sender_result = (
                sender_entry['class_name'],
                sender_entry['show_instance_side'],
                sender_entry['method_selector'],
            )
            sender_result_is_recorded = sender_result in sender_entries_by_result
            if not sender_result_is_recorded:
                sender_entries_by_result[sender_result] = dict(sender_entry)
        return (
            self.unique_sorted_navigation_results(sender_results),
            sender_entries_by_result,
        )

    def sender_entry_for_result(self, sender_result):
        sender_entry = self.sender_entries_by_navigation_result.get(sender_result)
        if sender_entry is not None:
            return dict(sender_entry)
        class_name, show_instance_side, method_selector = sender_result
        return {
            'class_name': class_name,
            'show_instance_side': show_instance_side,
            'method_selector': method_selector,
            'class_category': None,
            'method_category': None,
            'method_category_is_extension': False,
            'extension_category_name': None,
        }

    def sender_entries_for_navigation_results(self, sender_results):
        return [
            self.sender_entry_for_result(sender_result)
            for sender_result in sender_results
        ]

    def normalized_sender_filter_values(self, filter_values):
        if filter_values is None:
            return []
        return [
            value.strip().lower()
            for value in filter_values
            if isinstance(value, str) and value.strip()
        ]

    def sender_text_matches_filters(self, sender_text, filter_values):
        if not filter_values:
            return True
        if not isinstance(sender_text, str):
            return False
        normalized_sender_text = sender_text.strip().lower()
        if not normalized_sender_text:
            return False
        return any(
            filter_value in normalized_sender_text for filter_value in filter_values
        )

    def sender_matches_class_category_filters(
        self,
        sender_entry,
        class_category_filters,
        include_extension_method_category_for_class_category,
    ):
        if not class_category_filters:
            return True
        category_candidates = []
        class_category = sender_entry.get('class_category')
        if isinstance(class_category, str) and class_category.strip():
            category_candidates.append(class_category.strip().lower())
        if include_extension_method_category_for_class_category:
            extension_category_name = sender_entry.get('extension_category_name')
            if (
                isinstance(extension_category_name, str)
                and extension_category_name.strip()
            ):
                category_candidates.append(
                    extension_category_name.strip().lower()
                )
        if not category_candidates:
            return False
        return any(
            filter_value in category_candidate
            for filter_value in class_category_filters
            for category_candidate in category_candidates
        )

    def sender_entry_matches_filters(
        self,
        sender_entry,
        class_category_filters,
        class_name_filters,
        method_selector_filters,
        method_category_filters,
        include_extension_method_category_for_class_category,
    ):
        if not self.sender_matches_class_category_filters(
            sender_entry,
            class_category_filters,
            include_extension_method_category_for_class_category,
        ):
            return False
        if not self.sender_text_matches_filters(
            sender_entry.get('class_name'),
            class_name_filters,
        ):
            return False
        if not self.sender_text_matches_filters(
            sender_entry.get('method_selector'),
            method_selector_filters,
        ):
            return False
        if not self.sender_text_matches_filters(
            sender_entry.get('method_category'),
            method_category_filters,
        ):
            return False
        return True

    def apply_sender_filters(
        self,
        class_category_filters=None,
        class_name_filters=None,
        method_selector_filters=None,
        method_category_filters=None,
        include_extension_method_category_for_class_category=True,
        reasoning_note='',
    ):
        if self.search_type.get() != 'reference' or self.reference_target.get() != 'method':
            return {
                'ok': False,
                'error': {
                    'message': (
                        'Sender filtering requires Find in method-reference mode.'
                    )
                },
            }
        normalized_class_category_filters = self.normalized_sender_filter_values(
            class_category_filters
        )
        normalized_class_name_filters = self.normalized_sender_filter_values(
            class_name_filters
        )
        normalized_method_selector_filters = self.normalized_sender_filter_values(
            method_selector_filters
        )
        normalized_method_category_filters = self.normalized_sender_filter_values(
            method_category_filters
        )
        baseline_sender_results = list(self.navigation_method_results)
        if not baseline_sender_results:
            baseline_sender_results = list(self.static_sender_results)
        filtered_sender_results = []
        for sender_result in baseline_sender_results:
            sender_entry = self.sender_entry_for_result(sender_result)
            sender_matches_filters = self.sender_entry_matches_filters(
                sender_entry,
                normalized_class_category_filters,
                normalized_class_name_filters,
                normalized_method_selector_filters,
                normalized_method_category_filters,
                include_extension_method_category_for_class_category,
            )
            if sender_matches_filters:
                filtered_sender_results.append(sender_result)
        self.populate_navigation_results(filtered_sender_results)
        displayed_sender_entries = self.sender_entries_for_navigation_results(
            filtered_sender_results
        )
        summary_text = 'Filtered senders: %s of %s displayed references.' % (
            len(filtered_sender_results),
            len(baseline_sender_results),
        )
        if reasoning_note:
            summary_text += ' ' + reasoning_note.strip()
        self.status_var.set(summary_text)
        return {
            'ok': True,
            'displayed_sender_count': len(filtered_sender_results),
            'filtered_out_sender_count': (
                len(baseline_sender_results) - len(filtered_sender_results)
            ),
            'displayed_senders': displayed_sender_entries,
            'reasoning_note': reasoning_note,
        }

    def sender_filter_state_for_mcp(self):
        is_sender_reference_search = (
            self.search_type.get() == 'reference'
            and self.reference_target.get() == 'method'
            and self.last_reference_method_query is not None
        )
        displayed_sender_entries = self.sender_entries_for_navigation_results(
            self.navigation_method_results
        )
        static_sender_entries = self.sender_entries_for_navigation_results(
            self.static_sender_results
        )
        return {
            'is_open': True,
            'is_sender_reference_search': is_sender_reference_search,
            'total_static_sender_count': len(self.static_sender_results),
            'displayed_sender_count': len(self.navigation_method_results),
            'displayed_senders': displayed_sender_entries,
            'static_senders': static_sender_entries,
            'sender_selector_query': self.last_reference_method_query,
            'sender_source_class_name': self.sender_source_class_name,
        }

    def source_class_category(self):
        if self.sender_source_class_name is None:
            return None
        for result in self.static_sender_results:
            entry = self.sender_entry_for_result(result)
            if entry.get('class_name') == self.sender_source_class_name:
                return entry.get('class_category')
        return None

    def narrow_to_source_class_category(self):
        if self.sender_source_class_name is None:
            return {
                'ok': False,
                'error': {'message': 'No source class context recorded for this sender search.'},
            }
        category = self.source_class_category()
        if category is None:
            return {
                'ok': False,
                'error': {
                    'message': 'Could not determine class category for %s from sender results.' % self.sender_source_class_name,
                },
            }
        return self.apply_sender_filters(
            class_category_filters=[category],
            reasoning_note='Narrowed to class category "%s" of source class %s.' % (
                category, self.sender_source_class_name,
            ),
        )

    def narrow_to_source_class_button_clicked(self):
        result = self.narrow_to_source_class_category()
        if not result.get('ok'):
            messagebox.showerror('Narrow to Source Class', result['error']['message'])

    def apply_regex_filter_button_clicked(self):
        result = self.apply_regex_sender_filters(
            class_regex=self.class_regex_entry.get(),
            category_regex=self.category_regex_entry.get(),
        )
        if not result.get('ok'):
            messagebox.showerror('Apply Filter', result['error']['message'])

    def apply_regex_sender_filters(self, class_regex='', category_regex=''):
        if self.search_type.get() != 'reference' or self.reference_target.get() != 'method':
            return {
                'ok': False,
                'error': {'message': 'Sender filtering requires Find in method-reference mode.'},
            }
        baseline_sender_results = list(self.navigation_method_results)
        if not baseline_sender_results:
            baseline_sender_results = list(self.static_sender_results)
        filtered_sender_results = []
        for sender_result in baseline_sender_results:
            sender_entry = self.sender_entry_for_result(sender_result)
            if not self.sender_entry_matches_regex_filters(sender_entry, class_regex, category_regex):
                continue
            filtered_sender_results.append(sender_result)
        self.populate_navigation_results(filtered_sender_results)
        parts = []
        if class_regex:
            parts.append('class~/%s/' % class_regex)
        if category_regex:
            parts.append('category~/%s/' % category_regex)
        filter_desc = ', '.join(parts) if parts else '(none)'
        self.status_var.set(
            'Filtered senders: %s of %s displayed. Filter: %s' % (
                len(filtered_sender_results),
                len(baseline_sender_results),
                filter_desc,
            )
        )
        return {
            'ok': True,
            'displayed_sender_count': len(filtered_sender_results),
            'filtered_out_sender_count': len(baseline_sender_results) - len(filtered_sender_results),
        }

    def sender_entry_matches_regex_filters(self, sender_entry, class_regex, category_regex):
        if class_regex:
            class_name = sender_entry.get('class_name') or ''
            try:
                if not re.search(class_regex, class_name, re.IGNORECASE):
                    return False
            except re.error:
                return False
        if category_regex:
            category = sender_entry.get('class_category') or sender_entry.get('method_category') or ''
            try:
                if not re.search(category_regex, category, re.IGNORECASE):
                    return False
            except re.error:
                return False
        return True

    def update_sender_status_for_method_references(
        self,
        selector_names,
        static_reference_count,
        match_mode,
    ):
        if self.search_type.get() != "reference":
            self.status_var.set("")
            return
        if self.reference_target.get() != "method":
            self.status_var.set("")
            return
        self.status_var.set("Static references: %s methods." % static_reference_count)

    def current_reference_method_selector_for_tracing(
        self,
        selector_names,
        normalized_search_query,
        match_mode,
    ):
        return normalized_search_query

    def find_text(self):
        if self.find_operation_running:
            return
        search_query = self.find_entry.get()
        normalized_search_query = search_query.strip()
        search_type = self.search_type.get()
        match_mode = self.match_mode.get()
        if search_type == 'reference':
            match_mode = 'exact'
            if self.match_mode.get() != 'exact':
                self.match_mode.set('exact')
        reference_target = self.reference_target.get()
        self.update_search_context_fields()
        self.navigation_method_results = []
        self.method_reference_results = []
        self.reference_method_selectors = []
        self.sender_tracing_selector = None
        self.sender_entries_by_navigation_result = {}
        should_run_search = bool(normalized_search_query)
        self.find_stop_requested = False
        self.set_find_operation_state(should_run_search)
        if should_run_search:
            self.parent.begin_foreground_activity(
                self.activity_message_for_search(
                    search_type,
                    match_mode,
                    reference_target,
                    normalized_search_query,
                )
            )

        try:
            if not should_run_search:
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                self.display_results([])
                self.status_var.set('')
                return
            if search_type == 'class':
                class_names = self.class_names_for_query(
                    normalized_search_query,
                    match_mode,
                    should_stop=self.find_should_stop,
                )
                self.display_results(class_names)
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                if self.find_stop_requested:
                    self.finish_stopped_find()
                else:
                    self.status_var.set('')
                return
            if search_type == 'method':
                if match_mode == 'exact':
                    implementor_results = list(
                        self.gemstone_session_record.find_implementors_of_method(
                            normalized_search_query
                        )
                    )
                    if self.find_should_stop():
                        self.display_results([])
                        self.finish_stopped_find()
                        return
                    self.navigation_method_results = [
                        (
                            class_name,
                            not is_meta,
                            normalized_search_query,
                        )
                        for class_name, is_meta in implementor_results
                    ]
                    self.static_sender_results = []
                    self.sender_entries_by_navigation_result = {}
                    self.populate_navigation_results(self.navigation_method_results)
                    if self.find_stop_requested:
                        self.finish_stopped_find()
                    else:
                        self.status_var.set('')
                    return
                selector_names = self.selector_names_for_query(
                    normalized_search_query,
                    match_mode,
                    should_stop=self.find_should_stop,
                )
                self.display_results(selector_names)
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                if self.find_stop_requested:
                    self.finish_stopped_find()
                else:
                    self.status_var.set('')
                return
            if reference_target == 'class':
                class_reference_results = self.references_for_class_query(
                    normalized_search_query,
                    match_mode,
                    should_stop=self.find_should_stop,
                )
                self.method_reference_results = list(class_reference_results)
                self.populate_navigation_results(class_reference_results)
                self.static_sender_results = []
                self.sender_entries_by_navigation_result = {}
                self.last_reference_method_query = None
                self.last_reference_method_match_mode = None
                if self.find_stop_requested:
                    self.finish_stopped_find()
                else:
                    self.status_var.set('')
                return
            (
                method_reference_results,
                selector_names,
                sender_entries_by_result,
            ) = self.references_for_method_query(
                normalized_search_query,
                match_mode,
                should_stop=self.find_should_stop,
            )
            self.reference_method_selectors = selector_names
            self.static_sender_results = list(method_reference_results)
            self.sender_entries_by_navigation_result = dict(sender_entries_by_result)
            self.last_reference_method_query = normalized_search_query
            self.last_reference_method_match_mode = match_mode
            if self.find_stop_requested:
                self.sender_tracing_selector = None
                self.populate_navigation_results(method_reference_results)
                self.finish_stopped_find()
                return
            self.sender_tracing_selector = (
                self.current_reference_method_selector_for_tracing(
                    selector_names,
                    normalized_search_query,
                    match_mode,
                )
            )
            self.populate_navigation_results(method_reference_results)
            self.update_sender_status_for_method_references(
                selector_names,
                len(self.static_sender_results),
                match_mode,
            )
        finally:
            if should_run_search:
                self.parent.end_foreground_activity()
            self.set_find_operation_state(False)
            self.update_search_context_fields()

    def choose_tests_for_tracing(self, method_name):
        test_selection_dialog = CoveringTestsSearchDialog(
            self,
            method_name,
            self.max_test_discovery_elapsed_ms,
        )
        discovery_workflow = CoveringTestsDiscoveryWorkflow(
            self.gemstone_session_record,
            method_name,
            self.max_test_discovery_elapsed_ms,
            self.merged_sender_test_plan,
        )

        def run_search_attempt():
            test_selection_dialog.set_searching_state()
            discovery_workflow.run_search_attempt()

        def monitor_search():
            if not test_selection_dialog.winfo_exists():
                return
            if test_selection_dialog.stop_search_requested:
                if not discovery_workflow.cancelled():
                    test_selection_dialog.set_stopping_for_cancel_state()
            if test_selection_dialog.use_results_requested:
                if discovery_workflow.searching():
                    test_selection_dialog.set_stopping_for_use_results_state()

            search_outcome = discovery_workflow.advance(
                test_selection_dialog.stop_search_requested,
                test_selection_dialog.use_results_requested,
                test_selection_dialog.add_or_update_candidate_test,
            )
            if search_outcome["phase"] == "searching":
                self.after(50, monitor_search)
                return
            if search_outcome["phase"] == "cancelled":
                test_selection_dialog.destroy()
                return
            if search_outcome["phase"] == "error":
                test_selection_dialog.destroy()
                return
            if search_outcome["phase"] == "empty":
                test_selection_dialog.set_ready_state(
                    timed_out=False,
                    summary_message="Search finished without results.",
                )
            if search_outcome["phase"] == "ready":
                accumulated_plan = search_outcome["plan"]
                test_selection_dialog.add_candidate_tests(
                    accumulated_plan.get("candidate_tests", [])
                )
                test_selection_dialog.set_metrics_from_test_plan(accumulated_plan)
                summary_message = ""
                if search_outcome["used_results"]:
                    summary_message = "Using the results found so far."
                if search_outcome["timed_out"]:
                    summary_message = (
                        "Search timed out. You can continue with Search Further."
                    )
                test_selection_dialog.set_ready_state(
                    timed_out=search_outcome["timed_out"],
                    summary_message=summary_message,
                )
            if test_selection_dialog.winfo_exists():
                if test_selection_dialog.search_further_requested:
                    test_selection_dialog.search_further_requested = False
                    run_search_attempt()
                self.after(50, monitor_search)

        run_search_attempt()
        self.after(50, monitor_search)
        self.wait_window(test_selection_dialog)

        if discovery_workflow.latest_error() is not None:
            raise discovery_workflow.latest_error()
        if discovery_workflow.cancelled():
            self.status_var.set("Test discovery stopped.")
            return None
        if test_selection_dialog.selected_tests is None:
            return None
        return test_selection_dialog.selected_tests

    def observed_sender_key(self, observed_sender):
        return (
            observed_sender["caller_class_name"],
            observed_sender["caller_show_instance_side"],
            observed_sender["caller_method_selector"],
        )

    def merge_sender_test_plans(self, current_plan, new_plan):
        return self.merged_sender_test_plan(
            current_plan,
            new_plan,
        )

    def merged_sender_test_plan(self, current_plan, new_plan):
        max_elapsed_ms = self.max_test_discovery_elapsed_ms

        def candidate_test_key(candidate_test):
            return (
                candidate_test["test_case_class_name"],
                candidate_test["test_method_selector"],
            )

        if current_plan is None:
            merged_plan = dict(new_plan)
            merged_plan["candidate_tests"] = list(new_plan.get("candidate_tests", []))
            merged_plan["sender_edges"] = list(new_plan.get("sender_edges", []))
            merged_plan["candidate_test_count"] = len(merged_plan["candidate_tests"])
            merged_plan["sender_edge_count"] = len(merged_plan["sender_edges"])
            return merged_plan

        merged_plan = dict(current_plan)
        candidate_tests_by_key = {}
        for candidate_test in current_plan.get("candidate_tests", []):
            candidate_tests_by_key[candidate_test_key(candidate_test)] = dict(
                candidate_test
            )
        for candidate_test in new_plan.get("candidate_tests", []):
            current_candidate_test_key = candidate_test_key(candidate_test)
            if current_candidate_test_key in candidate_tests_by_key:
                existing_candidate_test = candidate_tests_by_key[
                    current_candidate_test_key
                ]
                if candidate_test.get("depth", 0) < existing_candidate_test.get(
                    "depth",
                    0,
                ):
                    candidate_tests_by_key[current_candidate_test_key] = dict(
                        candidate_test
                    )
            if current_candidate_test_key not in candidate_tests_by_key:
                candidate_tests_by_key[current_candidate_test_key] = dict(
                    candidate_test
                )
        merged_candidate_tests = sorted(
            candidate_tests_by_key.values(),
            key=lambda candidate_test: (
                candidate_test.get("depth", 0),
                candidate_test["test_case_class_name"],
                candidate_test["test_method_selector"],
            ),
        )

        sender_edges_by_key = {}
        for sender_edge in current_plan.get("sender_edges", []) + new_plan.get(
            "sender_edges", []
        ):
            sender_edge_key = (
                sender_edge["from_selector"],
                sender_edge["to_class_name"],
                sender_edge["to_method_selector"],
                sender_edge["to_show_instance_side"],
                sender_edge["depth"],
            )
            sender_edges_by_key[sender_edge_key] = dict(sender_edge)
        merged_sender_edges = list(sender_edges_by_key.values())

        merged_plan["candidate_tests"] = merged_candidate_tests
        merged_plan["candidate_test_count"] = len(merged_candidate_tests)
        merged_plan["sender_edges"] = merged_sender_edges
        merged_plan["sender_edge_count"] = len(merged_sender_edges)
        merged_plan["visited_selector_count"] = max(
            current_plan.get("visited_selector_count", 0),
            new_plan.get("visited_selector_count", 0),
        )
        merged_plan["sender_search_truncated"] = current_plan.get(
            "sender_search_truncated", False
        ) or new_plan.get("sender_search_truncated", False)
        merged_plan["selector_limit_reached"] = current_plan.get(
            "selector_limit_reached", False
        ) or new_plan.get("selector_limit_reached", False)
        merged_plan["elapsed_limit_reached"] = new_plan.get(
            "elapsed_limit_reached",
            False,
        )
        merged_plan["elapsed_ms"] = current_plan.get("elapsed_ms", 0) + new_plan.get(
            "elapsed_ms",
            0,
        )
        merged_plan["max_elapsed_ms"] = max_elapsed_ms
        merged_plan["stopped_by_user"] = new_plan.get("stopped_by_user", False)
        return merged_plan

    def narrow_senders_with_tracing(self):
        if self.search_type.get() != "reference":
            return
        if self.reference_target.get() != "method":
            return
        reference_query = self.find_entry.get().strip()
        if not reference_query:
            messagebox.showwarning(
                "Narrow References",
                "Enter a method selector first.",
                parent=self,
            )
            return
        query_is_out_of_date = (
            self.last_reference_method_query != reference_query
            or self.last_reference_method_match_mode != self.match_mode.get()
        )
        if query_is_out_of_date:
            self.find_text()
        method_selector = self.sender_tracing_selector
        if not method_selector:
            messagebox.showwarning(
                "Narrow References",
                (
                    "Tracing requires an exact selector or a contains "
                    "query that matches one selector."
                ),
                parent=self,
            )
            return
        try:
            selected_tests = self.choose_tests_for_tracing(method_selector)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror(
                "Narrow References",
                str(error),
                parent=self,
            )
            return
        if selected_tests is None:
            return
        source_class = self.sender_source_class_name
        trace_description = (
            '%s>>%s' % (source_class, method_selector)
            if source_class is not None
            else method_selector
        )
        self.status_var.set(
            "Tracing %s and running %s selected tests..."
            % (trace_description, len(selected_tests))
        )
        self.update_idletasks()
        try:
            evidence_result = (
                self.gemstone_session_record.collect_sender_evidence_from_tests(
                    method_selector,
                    selected_tests,
                    max_traced_senders=250,
                    max_observed_results=500,
                    receiver_class_name=source_class,
                )
            )
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror(
                "Narrow References",
                str(error),
                parent=self,
            )
            self.status_var.set("")
            return
        observed_sender_entries = evidence_result["observed"]["observed_senders"]
        observed_sender_keys = {
            self.observed_sender_key(observed_sender)
            for observed_sender in observed_sender_entries
        }
        narrowed_sender_results = [
            sender_result
            for sender_result in self.static_sender_results
            if sender_result in observed_sender_keys
        ]
        self.populate_navigation_results(narrowed_sender_results)
        trace_result = evidence_result.get("trace") or {}
        fallback_note = trace_result.get('fallback_reason', '')
        summary_text = "Observed senders of %s: %s of %s static references." % (
            trace_description,
            len(narrowed_sender_results),
            len(self.static_sender_results),
        )
        if fallback_note:
            summary_text += ' (%s)' % fallback_note
        self.status_var.set(summary_text)

    def on_result_double_click(self, event):
        selection = self.results_listbox.curselection()
        if not selection:
            pass
            return
        selected_index = selection[0]
        selected_text = self.results_listbox.get(selected_index)
        search_type = self.search_type.get()
        match_mode = self.match_mode.get()
        if search_type == "method" and match_mode == "contains":
            self.find_entry.delete(0, tk.END)
            self.find_entry.insert(0, selected_text)
            self.match_mode.set("exact")
            self.find_text()
            self.update_search_context_fields()
            return
        parent = self.parent
        self.destroy()
        if search_type == "class":
            parent.handle_find_selection(search_type == "class", selected_text)
            return
        has_navigation_result = selected_index < len(self.navigation_method_results)
        if has_navigation_result:
            (
                class_name,
                show_instance_side,
                method_selector,
            ) = self.navigation_method_results[selected_index]
            parent.handle_sender_selection(
                class_name,
                show_instance_side,
                method_selector,
            )


class CoveringTestsSearchDialog(tk.Toplevel):
    def __init__(self, parent, method_name, max_elapsed_ms):
        super().__init__(parent)
        self.title("Trace Narrowing Tests")
        self.geometry("760x520")
        self.transient(parent)
        self.wait_visibility()
        self.grab_set()

        self.selected_tests = None
        self.was_cancelled = True
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False
        self.is_searching = False
        self.is_timed_out = False
        self.method_name = method_name
        self.max_elapsed_ms = max_elapsed_ms
        self.candidate_tests_by_key = {}
        self.candidate_test_order = []
        self.checkbox_variables_by_key = {}
        self.checkbox_widgets_by_key = {}
        self.visited_selector_count = 0
        self.elapsed_ms = 0
        self.summary_message = ""

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.summary_label = ttk.Label(
            self,
            text="",
            justify="left",
        )
        self.summary_label.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=10,
            pady=(10, 6),
            sticky="w",
        )

        self.progress_bar = ttk.Progressbar(
            self,
            mode="indeterminate",
            length=360,
        )
        self.progress_bar.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=10,
            pady=(0, 6),
        )

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.canvas.grid(row=2, column=0, sticky="nsew", padx=10)
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.scrollbar.grid(row=2, column=1, sticky="ns", padx=(0, 10))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.tests_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.tests_frame,
            anchor="nw",
        )
        self.tests_frame.bind("<Configure>", self.update_scroll_region)
        self.canvas.bind("<Configure>", self.update_canvas_window_width)

        self.buttons = ttk.Frame(self)
        self.buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=10)
        self.select_all_button = ttk.Button(
            self.buttons,
            text="Select All",
            command=self.select_all_tests,
        )
        self.select_all_button.grid(row=0, column=0, padx=(0, 4))
        self.select_none_button = ttk.Button(
            self.buttons,
            text="Select None",
            command=self.select_no_tests,
        )
        self.select_none_button.grid(row=0, column=1, padx=(0, 10))
        self.run_selected_button = ttk.Button(
            self.buttons,
            text="Run Selected While Tracing",
            command=self.run_selected_tests,
        )
        self.run_selected_button.grid(row=0, column=2, padx=(0, 4))
        self.use_results_button = ttk.Button(
            self.buttons,
            text="Use Results So Far",
            command=self.request_use_results,
        )
        self.use_results_button.grid(row=0, column=3, padx=(0, 4))
        self.stop_search_button = ttk.Button(
            self.buttons,
            text="Stop Searching For Tests",
            command=self.request_stop_search,
        )
        self.stop_search_button.grid(row=0, column=4, padx=(0, 4))
        self.search_further_button = ttk.Button(
            self.buttons,
            text="Search Further",
            command=self.request_search_further,
        )
        self.search_further_button.grid(row=0, column=5, padx=(0, 4))
        self.cancel_button = ttk.Button(
            self.buttons,
            text="Cancel",
            command=self.cancel_dialog,
        )
        self.cancel_button.grid(row=0, column=6)
        self.protocol("WM_DELETE_WINDOW", self.cancel_dialog)
        self.set_searching_state()

    def candidate_test_key(self, candidate_test):
        return (
            candidate_test["test_case_class_name"],
            candidate_test["test_method_selector"],
        )

    def summary_text(self):
        candidate_count = len(self.candidate_test_order)
        if self.is_searching:
            return (
                "Searching for candidate tests for %s... "
                "Found: %s, explored selectors: %s."
            ) % (
                self.method_name,
                candidate_count,
                self.visited_selector_count,
            )
        if self.is_timed_out:
            return (
                "Search reached %ss timeout. Found: %s, explored selectors: %s. "
                "Select tests to run now or choose Search Further."
            ) % (
                int(self.max_elapsed_ms / 1000),
                candidate_count,
                self.visited_selector_count,
            )
        return ("Candidate tests for %s: %s (explored selectors: %s).") % (
            self.method_name,
            candidate_count,
            self.visited_selector_count,
        )

    def refresh_summary(self):
        summary_text = self.summary_text()
        if self.summary_message:
            summary_text = "%s %s" % (summary_text, self.summary_message)
        self.summary_label.configure(text=summary_text)

    def format_test_label(self, candidate_test):
        return "%s>>%s (depth %s via %s)" % (
            candidate_test["test_case_class_name"],
            candidate_test["test_method_selector"],
            candidate_test.get("depth", "?"),
            candidate_test.get("reached_from_selector", "?"),
        )

    def update_scroll_region(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def update_canvas_window_width(self, event):
        self.canvas.itemconfigure(
            self.canvas_window,
            width=event.width,
        )

    def selection_controls_enabled(self):
        has_tests = len(self.candidate_test_order) > 0
        return has_tests and not self.is_searching

    def update_button_states(self):
        selection_controls_enabled = self.selection_controls_enabled()
        select_button_state = tk.NORMAL if selection_controls_enabled else tk.DISABLED
        run_button_state = tk.NORMAL if selection_controls_enabled else tk.DISABLED
        self.select_all_button.configure(state=select_button_state)
        self.select_none_button.configure(state=select_button_state)
        self.run_selected_button.configure(state=run_button_state)
        use_results_state = tk.NORMAL if self.is_searching else tk.DISABLED
        stop_search_state = tk.NORMAL if self.is_searching else tk.DISABLED
        self.use_results_button.configure(state=use_results_state)
        self.stop_search_button.configure(state=stop_search_state)
        search_further_state = tk.DISABLED
        if self.is_timed_out and not self.is_searching:
            search_further_state = tk.NORMAL
        self.search_further_button.configure(state=search_further_state)
        checkbox_state = tk.NORMAL if selection_controls_enabled else tk.DISABLED
        for checkbox_widget in self.checkbox_widgets_by_key.values():
            checkbox_widget.configure(state=checkbox_state)

    def set_searching_state(self):
        self.is_searching = True
        self.is_timed_out = False
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False
        self.summary_message = ""
        self.progress_bar.start(10)
        self.update_button_states()
        self.refresh_summary()

    def set_stopping_for_use_results_state(self):
        self.summary_message = "Stopping search to use the current results..."
        self.refresh_summary()

    def set_stopping_for_cancel_state(self):
        self.summary_message = "Stopping search and cancelling..."
        self.refresh_summary()

    def set_ready_state(self, timed_out=False, summary_message=""):
        self.is_searching = False
        self.is_timed_out = timed_out
        self.summary_message = summary_message
        self.progress_bar.stop()
        self.update_button_states()
        self.refresh_summary()

    def set_metrics_from_test_plan(self, test_plan):
        self.visited_selector_count = test_plan.get(
            "visited_selector_count",
            self.visited_selector_count,
        )
        self.elapsed_ms = test_plan.get("elapsed_ms", self.elapsed_ms)
        self.refresh_summary()

    def add_or_update_candidate_test(self, candidate_test):
        candidate_key = self.candidate_test_key(candidate_test)
        has_candidate = candidate_key in self.candidate_tests_by_key
        if has_candidate:
            existing_candidate = self.candidate_tests_by_key[candidate_key]
            candidate_depth = candidate_test.get("depth", 0)
            existing_depth = existing_candidate.get("depth", 0)
            if candidate_depth < existing_depth:
                self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
                checkbutton = self.checkbox_widgets_by_key[candidate_key]
                checkbutton.configure(text=self.format_test_label(candidate_test))
        if not has_candidate:
            self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
            self.candidate_test_order.append(candidate_key)
            row_index = len(self.candidate_test_order) - 1
            default_checked_count = 20
            is_default_checked = row_index < default_checked_count
            selected = tk.BooleanVar(value=is_default_checked)
            self.checkbox_variables_by_key[candidate_key] = selected
            checkbutton = ttk.Checkbutton(
                self.tests_frame,
                text=self.format_test_label(candidate_test),
                variable=selected,
            )
            self.checkbox_widgets_by_key[candidate_key] = checkbutton
            checkbutton.grid(
                row=row_index,
                column=0,
                sticky="w",
                padx=4,
                pady=2,
            )
            self.update_scroll_region()
        self.update_button_states()
        self.refresh_summary()

    def add_candidate_tests(self, candidate_tests):
        for candidate_test in candidate_tests:
            self.add_or_update_candidate_test(candidate_test)

    def selected_candidate_tests(self):
        selected_tests = []
        for candidate_key in self.candidate_test_order:
            selected_variable = self.checkbox_variables_by_key[candidate_key]
            if selected_variable.get():
                selected_tests.append(dict(self.candidate_tests_by_key[candidate_key]))
        return selected_tests

    def select_all_tests(self):
        for selected in self.checkbox_variables_by_key.values():
            selected.set(True)

    def select_no_tests(self):
        for selected in self.checkbox_variables_by_key.values():
            selected.set(False)

    def request_use_results(self):
        if self.is_searching:
            self.use_results_requested = True
            self.set_stopping_for_use_results_state()

    def request_stop_search(self):
        if self.is_searching:
            self.stop_search_requested = True
            self.set_stopping_for_cancel_state()

    def request_search_further(self):
        if not self.is_searching and self.is_timed_out:
            self.search_further_requested = True
            self.summary_message = ""
            self.refresh_summary()

    def cancel_dialog(self):
        if self.is_searching:
            self.request_stop_search()
        if not self.is_searching:
            self.destroy()

    def run_selected_tests(self):
        selected_tests = self.selected_candidate_tests()
        if not selected_tests:
            messagebox.showwarning(
                "Trace Narrowing",
                "Select at least one test.",
                parent=self,
            )
            return
        self.selected_tests = selected_tests
        self.was_cancelled = False
        self.destroy()


class BreakpointsDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.gemstone_session_record = parent.gemstone_session_record
        self.breakpoint_entries_by_id = {}
        self.title("Breakpoints")
        self.geometry("760x320")
        self.transient(parent)
        if parent.winfo_viewable():
            self.wait_visibility()
        self.grab_set()

        self.breakpoint_list = ttk.Treeview(
            self,
            columns=("Class", "Side", "Selector", "Offset", "Step Point"),
            show="headings",
            height=10,
        )
        self.breakpoint_list.heading("Class", text="Class")
        self.breakpoint_list.heading("Side", text="Side")
        self.breakpoint_list.heading("Selector", text="Method")
        self.breakpoint_list.heading("Offset", text="Offset")
        self.breakpoint_list.heading("Step Point", text="Step Point")
        self.breakpoint_list.column("Class", width=180, anchor="w")
        self.breakpoint_list.column("Side", width=80, anchor="center")
        self.breakpoint_list.column("Selector", width=220, anchor="w")
        self.breakpoint_list.column("Offset", width=100, anchor="e")
        self.breakpoint_list.column("Step Point", width=100, anchor="e")
        self.breakpoint_list.bind("<Double-1>", self.on_breakpoint_double_click)
        self.breakpoint_list.grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="nsew",
            padx=10,
            pady=(10, 6),
        )

        self.clear_selected_button = ttk.Button(
            self,
            text="Clear Selected",
            command=self.clear_selected_breakpoint,
        )
        self.clear_selected_button.grid(
            row=1,
            column=0,
            padx=(10, 5),
            pady=(0, 10),
            sticky="w",
        )
        self.clear_all_button = ttk.Button(
            self,
            text="Clear All",
            command=self.clear_all_breakpoints,
        )
        self.clear_all_button.grid(
            row=1,
            column=1,
            padx=5,
            pady=(0, 10),
            sticky="w",
        )
        self.close_button = ttk.Button(
            self,
            text="Close",
            command=self.destroy,
        )
        self.close_button.grid(
            row=1,
            column=2,
            padx=(5, 10),
            pady=(0, 10),
            sticky="e",
        )
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)
        self.columnconfigure(2, weight=0)
        self.rowconfigure(0, weight=1)

        self.refresh_breakpoints()

    def refresh_breakpoints(self):
        self.breakpoint_entries_by_id = {}
        for row_id in self.breakpoint_list.get_children():
            self.breakpoint_list.delete(row_id)
        breakpoint_entries = self.gemstone_session_record.list_breakpoints()
        for breakpoint_entry in breakpoint_entries:
            side_label = "instance"
            if not breakpoint_entry["show_instance_side"]:
                side_label = "class"
            self.breakpoint_entries_by_id[breakpoint_entry["breakpoint_id"]] = (
                breakpoint_entry
            )
            self.breakpoint_list.insert(
                "",
                "end",
                iid=breakpoint_entry["breakpoint_id"],
                values=(
                    breakpoint_entry["class_name"],
                    side_label,
                    breakpoint_entry["method_selector"],
                    breakpoint_entry["source_offset"],
                    breakpoint_entry["step_point"],
                ),
            )

    def on_breakpoint_double_click(self, event):
        breakpoint_id = self.selected_breakpoint_id()
        if breakpoint_id is None:
            return
        breakpoint_entry = self.breakpoint_entries_by_id.get(breakpoint_id)
        if breakpoint_entry is None:
            return
        try:
            self.parent.handle_sender_selection(
                breakpoint_entry["class_name"],
                breakpoint_entry["show_instance_side"],
                breakpoint_entry["method_selector"],
            )
            if self.parent.browser_tab:
                self.parent.notebook.select(self.parent.browser_tab)
            self.destroy()
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Breakpoints", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Breakpoints", str(error))

    def selected_breakpoint_id(self):
        selection = self.breakpoint_list.selection()
        if not selection:
            return None
        return selection[0]

    def clear_selected_breakpoint(self):
        breakpoint_id = self.selected_breakpoint_id()
        if breakpoint_id is None:
            return
        try:
            self.gemstone_session_record.clear_breakpoint(breakpoint_id)
            self.refresh_breakpoints()
            self.parent.event_queue.publish("MethodsChanged")
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Breakpoints", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Breakpoints", str(error))

    def clear_all_breakpoints(self):
        try:
            self.gemstone_session_record.clear_all_breakpoints()
            self.refresh_breakpoints()
            self.parent.event_queue.publish("MethodsChanged")
        except (DomainException, GemstoneDomainException) as domain_exception:
            messagebox.showerror("Breakpoints", str(domain_exception))
        except GemstoneError as error:
            messagebox.showerror("Breakpoints", str(error))


class Swordfish(tk.Tk):
    @classmethod
    def new_argument_parser(cls, default_mode="ide"):
        argument_parser = argparse.ArgumentParser(
            description="Run Swordfish IDE and MCP server."
        )
        default_headless_mcp = default_mode == "mcp-headless"
        argument_parser.add_argument(
            "stone_name",
            nargs="?",
            default="gs64stone",
            help="GemStone stone name to prefill in login form.",
        )
        argument_parser.add_argument(
            "--headless-mcp",
            action="store_true",
            default=default_headless_mcp,
            help="Run MCP only (headless, no GUI).",
        )
        argument_parser.add_argument(
            "--mode",
            default=None,
            choices=["ide", "mcp-headless"],
            help=argparse.SUPPRESS,
        )
        argument_parser.add_argument(
            "--transport",
            default="stdio",
            choices=["stdio", "streamable-http"],
            help="MCP transport type for --headless-mcp mode.",
        )
        argument_parser.add_argument(
            "--mcp-host",
            default="127.0.0.1",
            help="Host interface for embedded MCP and streamable-http mode.",
        )
        argument_parser.add_argument(
            "--mcp-port",
            default=8000,
            type=int,
            help="TCP port for embedded MCP and streamable-http mode.",
        )
        argument_parser.add_argument(
            "--mcp-http-path",
            default="/mcp",
            help="HTTP path for embedded MCP and streamable-http mode.",
        )
        argument_parser.add_argument(
            "--allow-source-read",
            action="store_true",
            dest="allow_source_read",
            default=True,
            help="Enable source read tools (enabled by default).",
        )
        argument_parser.add_argument(
            "--disallow-source-read",
            action="store_false",
            dest="allow_source_read",
            help="Disable source read tools.",
        )
        argument_parser.add_argument(
            "--allow-source-write",
            action="store_true",
            help="Enable source write/refactor tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-eval-arbitrary",
            action="store_true",
            help="Enable gs_eval and gs_debug_eval (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-ide-read",
            action="store_true",
            dest="allow_ide_read",
            default=True,
            help="Enable IDE state read tools (enabled by default).",
        )
        argument_parser.add_argument(
            "--disallow-ide-read",
            action="store_false",
            dest="allow_ide_read",
            help="Disable IDE state read tools.",
        )
        argument_parser.add_argument(
            "--allow-ide-write",
            action="store_true",
            help="Enable IDE navigation/write tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-test-execution",
            action="store_true",
            help="Enable test execution tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-commit",
            action="store_true",
            help="Enable gs_commit tool (disabled by default).",
        )
        argument_parser.add_argument(
            "--allow-tracing",
            action="store_true",
            help="Enable gs_tracer_* and evidence tools (disabled by default).",
        )
        argument_parser.add_argument(
            "--require-gemstone-ast",
            action="store_true",
            help=(
                "Require real GemStone AST backend for refactoring tools. "
                "When enabled, heuristic refactorings are blocked."
            ),
        )
        return argument_parser

    @classmethod
    def validate_arguments(cls, argument_parser, arguments):
        if arguments.mcp_port <= 0:
            argument_parser.error("--mcp-port must be greater than zero.")
        if not arguments.mcp_http_path.startswith("/"):
            argument_parser.error("--mcp-http-path must start with /.")

    @classmethod
    def run(cls, default_mode="ide"):
        argument_parser = cls.new_argument_parser(default_mode=default_mode)
        arguments = argument_parser.parse_args()
        cls.validate_arguments(argument_parser, arguments)
        argument_tokens = sys.argv[1:]
        configuration_store = McpConfigurationStore()
        runtime_config = configuration_store.merged_config_from_arguments(
            arguments,
            argument_tokens=argument_tokens,
        )
        run_headless_mcp = arguments.headless_mcp
        if arguments.mode == "mcp-headless":
            run_headless_mcp = True
        if arguments.mode == "ide":
            run_headless_mcp = False
        if run_headless_mcp:
            mcp_server_controller = McpServerController(
                integrated_session_state=None,
                runtime_config=runtime_config,
                configuration_store=configuration_store,
            )
            mcp_server_controller.run(arguments.transport)
            return
        app = cls(
            default_stone_name=arguments.stone_name,
            start_embedded_mcp=False,
            mcp_runtime_config=runtime_config,
            mcp_configuration_store=configuration_store,
        )
        app.mainloop()

    def __init__(
        self,
        default_stone_name="gs64stone",
        start_embedded_mcp=False,
        mcp_runtime_config=None,
        mcp_configuration_store=None,
    ):
        super().__init__()
        self.action_gate = ActionGate()
        self.busy_coordinator = BusyCoordinator()
        self.event_queue = EventQueue(self)
        self.integrated_session_state = current_integrated_session_state()
        self.integrated_session_state.attach_ide_gui(
            ide_gui=self,
            ide_navigation_action=self.perform_mcp_ide_navigation_action,
        )
        self.title("Swordfish")
        self.geometry("800x600")
        self.default_stone_name = default_stone_name

        self.notebook = None
        self.browser_tab = None
        self.debugger_tab = None
        self.run_tab = None
        self.inspector_tab = None
        self.object_diagram_tab = None
        self.class_diagram_tab = None
        self.global_navigation_history = GlobalNavigationHistory()
        self.global_navigation_selection_in_progress = False
        self.next_global_navigation_session_number = 1
        self.global_back_button = None
        self.global_forward_button = None
        self.global_history_combobox = None
        self.global_history_choice_indices = []
        self.collaboration_status_frame = None
        self.collaboration_status_label = None
        self.collaboration_status_text = tk.StringVar(value="")
        self.mcp_activity_indicator = None
        self.mcp_activity_indicator_visible = False
        self.foreground_activity_message = ""

        self.gemstone_session_record = None
        self.last_mcp_busy_state = None
        self.last_mcp_server_running_state = None
        self.last_mcp_server_starting_state = None
        self.last_mcp_server_stopping_state = None
        self.last_mcp_server_error_message = None
        self.last_mcp_config_save_error_message = None
        if mcp_runtime_config is None:
            mcp_runtime_config = McpRuntimeConfig()
        self.base_mcp_runtime_config = mcp_runtime_config.copy()
        self.mcp_runtime_config = self.base_mcp_runtime_config.copy()
        self.mcp_server_controller = McpServerController(
            self.integrated_session_state,
            self.mcp_runtime_config,
            configuration_store=mcp_configuration_store,
        )
        self.mcp_permission_policy = (
            self.mcp_server_controller.configuration_store.load_permission_policy()
        )
        self.session_only_mcp_runtime_config_active = False

        self.event_queue.subscribe("LoggedInSuccessfully", self.show_main_app)
        self.event_queue.subscribe("LoggedOut", self.show_login_screen)
        self.event_queue.subscribe(
            "McpBusyStateChanged",
            self.handle_mcp_busy_state_changed,
        )
        self.event_queue.subscribe(
            "McpServerStateChanged",
            self.handle_mcp_server_state_changed,
        )
        self.event_queue.subscribe(
            "ModelRefreshRequested",
            self.handle_model_refresh_requested,
        )
        self.event_queue.subscribe(
            "McpIdeNavigationRequested",
            self.handle_mcp_ide_navigation_requested,
        )
        self.event_queue.subscribe(
            "OpenRunWindow",
            self.handle_open_run_window,
        )
        self.event_queue.subscribe(
            "MethodSelected",
            self.record_current_browser_place_in_global_history,
        )
        self.integrated_session_state.subscribe_mcp_busy_state(
            self.publish_mcp_busy_state_event,
        )
        self.integrated_session_state.subscribe_model_refresh_requests(
            self.publish_model_refresh_requested_event,
        )
        self.mcp_server_controller.subscribe_server_state(
            self.publish_mcp_server_state_event,
        )

        self.create_menu()
        self.publish_mcp_busy_state_event(
            is_busy=self.integrated_session_state.is_mcp_busy(),
            operation_name=self.integrated_session_state.current_mcp_operation_name(),
        )
        self.publish_mcp_server_state_event(**self.mcp_server_controller.status())
        if start_embedded_mcp:
            self.start_mcp_server(report_errors=False)
        self.show_login_screen()
        self.refresh_collaboration_status()

    @property
    def is_logged_in(self):
        return self.gemstone_session_record is not None

    def create_menu(self):
        self.menu_bar = MainMenu(self, self.event_queue)
        self.config(menu=self.menu_bar)

    def embedded_mcp_server_status(self):
        return self.mcp_server_controller.status()

    def mcp_configuration_access(self):
        can_write_config = self.mcp_server_controller.configuration_store.can_write_config()
        if can_write_config:
            return McpConfigurationAccess()
        if not self.is_logged_in:
            return McpConfigurationAccess(
                permission_controls_editable=False,
                configuration_persistable=False,
                note=(
                    "Config file is read-only. Permission toggles unlock only after "
                    "login to a database that passes the configured policy."
                ),
            )
        if not self.mcp_permission_policy.has_session_permission_change_condition():
            return McpConfigurationAccess(
                permission_controls_editable=False,
                configuration_persistable=False,
                note=(
                    "Config file is read-only. Permission toggles are locked because "
                    "no Smalltalk permission policy is configured."
                ),
            )
        try:
            session_changes_allowed = (
                self.mcp_permission_policy.session_permission_changes_allowed_for(
                    self.gemstone_session_record
                )
            )
        except (
            AttributeError,
            DomainException,
            GemstoneDomainException,
            GemstoneError,
            TypeError,
            ValueError,
        ):
            session_changes_allowed = False
        if session_changes_allowed:
            return McpConfigurationAccess(
                permission_controls_editable=True,
                configuration_persistable=False,
                note=(
                    "Config file is read-only. Changes apply only for this session "
                    "and reset on logout."
                ),
            )
        return McpConfigurationAccess(
            permission_controls_editable=False,
            configuration_persistable=False,
            note=(
                "Config file is read-only for this database. Permission toggles "
                "are locked."
            ),
        )

    def apply_mcp_runtime_config(self, runtime_config, configuration_access):
        self.mcp_runtime_config = runtime_config.copy()
        self.mcp_server_controller.update_runtime_config(self.mcp_runtime_config)
        if not configuration_access.configuration_persistable:
            self.last_mcp_config_save_error_message = None
            self.session_only_mcp_runtime_config_active = (
                self.mcp_runtime_config != self.base_mcp_runtime_config
            )
            return
        try:
            self.mcp_server_controller.save_configuration(self.mcp_permission_policy)
            self.base_mcp_runtime_config = self.mcp_runtime_config.copy()
            self.last_mcp_config_save_error_message = None
            self.session_only_mcp_runtime_config_active = False
        except DomainException as error:
            self.last_mcp_config_save_error_message = str(error)
            self.session_only_mcp_runtime_config_active = (
                self.mcp_runtime_config != self.base_mcp_runtime_config
            )
            messagebox.showerror(
                "MCP Configuration",
                str(error),
            )

    def reset_session_mcp_runtime_config(self):
        if not self.session_only_mcp_runtime_config_active:
            return
        self.mcp_runtime_config = self.base_mcp_runtime_config.copy()
        self.mcp_server_controller.update_runtime_config(self.mcp_runtime_config)
        self.session_only_mcp_runtime_config_active = False
        self.last_mcp_config_save_error_message = None

    def start_mcp_server(self, report_errors=True):
        started = self.mcp_server_controller.start()
        if not started and report_errors:
            messagebox.showinfo(
                "MCP",
                "MCP is already running or starting.",
            )
        return started

    def stop_mcp_server(self):
        stopped = self.mcp_server_controller.stop()
        if not stopped:
            messagebox.showinfo(
                "MCP",
                "MCP is already stopped.",
            )
        return stopped

    def start_mcp_server_from_menu(self):
        self.begin_foreground_activity("Starting MCP server...")
        try:
            self.start_mcp_server(report_errors=True)
            self.menu_bar.update_menus()
        finally:
            self.end_foreground_activity()

    def stop_mcp_server_from_menu(self):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                "MCP Busy",
                "Stop MCP after the current MCP operation finishes.",
            )
            return
        self.begin_foreground_activity("Stopping MCP server...")
        try:
            self.stop_mcp_server()
            self.menu_bar.update_menus()
        finally:
            self.end_foreground_activity()

    def configure_mcp_server_from_menu(self):
        configuration_access = self.mcp_configuration_access()
        dialog = McpConfigurationDialog(
            self,
            self.mcp_runtime_config,
            configuration_access,
        )
        self.wait_window(dialog)
        if dialog.result is None:
            return
        self.apply_mcp_runtime_config(dialog.result, configuration_access)
        self.menu_bar.update_menus()
        self.refresh_collaboration_status()

    def commit(self):
        self.gemstone_session_record.commit()
        self.integrated_session_state.mark_ide_transaction_inactive()
        self.event_queue.publish("Committed")
        self.publish_model_change_events("transaction")

    def abort(self):
        self.gemstone_session_record.abort()
        self.integrated_session_state.mark_ide_transaction_inactive()
        self.event_queue.publish("Aborted")
        self.publish_model_change_events("transaction")

    def logout(self):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                "MCP Busy",
                "Logout is disabled while MCP is running an operation.",
            )
            return
        mcp_server_status = self.embedded_mcp_server_status()
        if self.session_only_mcp_runtime_config_active and (
            mcp_server_status["running"] or mcp_server_status["starting"]
        ):
            self.mcp_server_controller.stop_for_session_reset()
        self.reset_session_mcp_runtime_config()
        self.gemstone_session_record.log_out()
        self.gemstone_session_record = None
        self.integrated_session_state.detach_ide_session()
        self.event_queue.publish("LoggedOut")

    def clear_widgets(self):
        for widget in self.winfo_children():
            if widget != self.menu_bar:
                widget.destroy()
        self.browser_tab = None
        self.debugger_tab = None
        self.run_tab = None
        self.inspector_tab = None
        self.object_diagram_tab = None
        self.class_diagram_tab = None
        self.global_navigation_history = GlobalNavigationHistory()
        self.global_navigation_selection_in_progress = False
        self.next_global_navigation_session_number = 1
        self.global_back_button = None
        self.global_forward_button = None
        self.global_history_combobox = None
        self.global_history_choice_indices = []
        self.collaboration_status_frame = None
        self.collaboration_status_label = None
        self.mcp_activity_indicator = None
        self.mcp_activity_indicator_visible = False

    def show_login_screen(self):
        self.clear_widgets()
        self.collaboration_status_text.set("")
        self.foreground_activity_message = ""
        self.last_mcp_server_stopping_state = None
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        self.login_frame = LoginFrame(
            self,
            default_stone_name=self.default_stone_name,
        )
        self.login_frame.grid(row=0, column=0, sticky="nsew")

    def show_main_app(self, gemstone_session_record):
        self.gemstone_session_record = gemstone_session_record
        self.gemstone_session_record.set_integrated_session_state(
            self.integrated_session_state
        )
        self.gemstone_session_record.change_event_publisher = (
            self.publish_model_change_events
        )
        self.integrated_session_state.attach_ide_session(
            self.gemstone_session_record.gemstone_session
        )

        self.clear_widgets()

        self.create_notebook()
        self.add_browser_tab()
        self.create_collaboration_status_bar()

    def publish_model_change_events(self, change_kind):
        if change_kind == "packages":
            self.event_queue.publish("PackagesChanged")
            self.event_queue.publish("ClassesChanged")
            return
        if change_kind == "classes":
            self.event_queue.publish("ClassesChanged")
            self.event_queue.publish("SelectedClassChanged")
            return
        if change_kind == "methods":
            self.event_queue.publish("MethodsChanged")
            self.event_queue.publish("SelectedCategoryChanged")
            self.event_queue.publish("MethodSelected")
            return
        if change_kind == "transaction":
            self.event_queue.publish("PackagesChanged")
            self.event_queue.publish("ClassesChanged")
            self.event_queue.publish("MethodsChanged")

    def create_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.bind(
            "<<NotebookTabChanged>>",
            self.record_selected_tab_in_global_history,
        )
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def create_collaboration_status_bar(self):
        self.collaboration_status_frame = ttk.Frame(self)
        self.collaboration_status_frame.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=6,
            pady=(2, 4),
        )
        self.collaboration_status_frame.columnconfigure(2, weight=1)
        self.global_back_button = ttk.Button(
            self.collaboration_status_frame,
            text="Back",
            command=self.go_to_previous_global_place,
        )
        self.global_back_button.grid(
            row=0,
            column=0,
            sticky="w",
        )
        self.global_forward_button = ttk.Button(
            self.collaboration_status_frame,
            text="Forward",
            command=self.go_to_next_global_place,
        )
        self.global_forward_button.grid(
            row=0,
            column=1,
            sticky="w",
            padx=(4, 8),
        )
        self.global_history_combobox = ttk.Combobox(
            self.collaboration_status_frame,
            state='readonly',
            width=36,
        )
        self.global_history_combobox.grid(
            row=0,
            column=2,
            sticky='w',
            padx=(0, 8),
        )
        self.global_history_combobox.bind(
            '<<ComboboxSelected>>',
            self.jump_to_selected_global_history_entry,
        )
        self.collaboration_status_label = ttk.Label(
            self.collaboration_status_frame,
            textvariable=self.collaboration_status_text,
            anchor="w",
        )
        self.collaboration_status_label.grid(
            row=0,
            column=3,
            sticky="ew",
        )
        self.mcp_activity_indicator = ttk.Progressbar(
            self.collaboration_status_frame,
            mode="indeterminate",
            length=110,
        )
        self.mcp_activity_indicator.grid(
            row=0,
            column=4,
            sticky="e",
            padx=(8, 0),
        )
        self.set_mcp_activity_indicator_visibility(False)
        self.refresh_global_navigation_controls()
        self.rowconfigure(1, weight=0)

    def allocate_global_navigation_session_key(self, kind):
        session_number = self.next_global_navigation_session_number
        self.next_global_navigation_session_number += 1
        return f"{kind}:{session_number}"

    def method_context_for_global_navigation(self):
        if not self.is_logged_in:
            return None
        selected_class = self.gemstone_session_record.selected_class
        selected_method_symbol = self.gemstone_session_record.selected_method_symbol
        if not selected_class or not selected_method_symbol:
            return None
        return (
            selected_class,
            self.gemstone_session_record.show_instance_side,
            selected_method_symbol,
        )

    def browser_state_for_global_navigation(self):
        if not self.is_logged_in:
            return None
        selected_class_category = (
            self.gemstone_session_record.selected_dictionary
            if self.gemstone_session_record.browse_mode == 'dictionaries'
            else self.gemstone_session_record.selected_package
        )
        has_browser_selection = any(
            (
                selected_class_category,
                self.gemstone_session_record.selected_class,
                self.gemstone_session_record.selected_method_category,
                self.gemstone_session_record.selected_method_symbol,
            )
        )
        if not has_browser_selection:
            return None
        return {
            'browse_mode': self.gemstone_session_record.browse_mode,
            'selected_package': self.gemstone_session_record.selected_package,
            'selected_dictionary': self.gemstone_session_record.selected_dictionary,
            'selected_class': self.gemstone_session_record.selected_class,
            'selected_method_category': (
                self.gemstone_session_record.selected_method_category
            ),
            'selected_method_symbol': self.gemstone_session_record.selected_method_symbol,
            'show_instance_side': self.gemstone_session_record.show_instance_side,
        }

    def label_for_global_method_context(self, method_context):
        if method_context is None:
            return ""
        class_name, show_instance_side, method_symbol = method_context
        if show_instance_side:
            return f"{class_name}>>{method_symbol}"
        return f"{class_name} class>>{method_symbol}"

    def label_for_browser_state(self, browser_state):
        if browser_state is None:
            return ""
        method_symbol = browser_state.get('selected_method_symbol')
        selected_class = browser_state.get('selected_class')
        show_instance_side = browser_state.get('show_instance_side', True)
        if selected_class and method_symbol:
            return self.label_for_global_method_context(
                (
                    selected_class,
                    show_instance_side,
                    method_symbol,
                )
            )
        if selected_class:
            if show_instance_side:
                return selected_class
            return f"{selected_class} class"
        selected_dictionary = browser_state.get('selected_dictionary')
        if selected_dictionary:
            return selected_dictionary
        selected_package = browser_state.get('selected_package')
        if selected_package:
            return selected_package
        return browser_state.get('browse_mode', 'browser')

    def browser_place_key(self, browser_state):
        return (
            'browser_selection',
            browser_state.get('browse_mode'),
            browser_state.get('selected_package'),
            browser_state.get('selected_dictionary'),
            browser_state.get('selected_class'),
            browser_state.get('selected_method_category'),
            browser_state.get('selected_method_symbol'),
            browser_state.get('show_instance_side'),
        )

    def current_browser_place_entry(self):
        browser_state = self.browser_state_for_global_navigation()
        if browser_state is None:
            return None
        method_context = self.method_context_for_global_navigation()
        if method_context is not None:
            return GlobalNavigationEntry(
                'browser_method',
                self.label_for_global_method_context(method_context),
                {
                    'method_context': method_context,
                    'browser_state': browser_state,
                },
                place_key=self.browser_place_key(browser_state),
            )
        return GlobalNavigationEntry(
            'browser_selection',
            self.label_for_browser_state(browser_state),
            {'browser_state': browser_state},
            place_key=self.browser_place_key(browser_state),
        )

    def record_global_navigation_entry(self, entry):
        if self.global_navigation_selection_in_progress:
            self.refresh_global_navigation_controls()
            return
        self.global_navigation_history.record(entry)
        self.refresh_global_navigation_controls()

    def record_current_browser_place_in_global_history(self, origin=None):
        browser_entry = self.current_browser_place_entry()
        if browser_entry is None:
            self.refresh_global_navigation_controls()
            return
        if self.global_navigation_selection_in_progress:
            self.refresh_global_navigation_controls()
            return
        current_entry = self.global_navigation_history.current_entry()
        if current_entry is not None and current_entry.kind in (
            'browser_method',
            'browser_selection',
        ):
            self.global_navigation_history.replace_current(browser_entry)
            self.refresh_global_navigation_controls()
            return
        self.record_global_navigation_entry(browser_entry)

    def ensure_current_browser_place_in_global_history(self):
        if self.notebook is None or not self.notebook.winfo_exists():
            return
        browser_is_open = self.browser_tab is not None and self.browser_tab.winfo_exists()
        if not browser_is_open:
            return
        try:
            selected_tab_id = self.notebook.select()
        except tk.TclError:
            return
        if selected_tab_id != str(self.browser_tab):
            return
        self.record_current_browser_place_in_global_history()

    def record_selected_tab_in_global_history(self, event=None):
        if self.notebook is None or not self.notebook.winfo_exists():
            self.refresh_global_navigation_controls()
            return
        try:
            selected_tab_id = self.notebook.select()
        except tk.TclError:
            self.refresh_global_navigation_controls()
            return
        if not selected_tab_id:
            self.refresh_global_navigation_controls()
            return
        if self.browser_tab is not None and selected_tab_id == str(self.browser_tab):
            self.record_current_browser_place_in_global_history()
            return
        if self.run_tab is not None and selected_tab_id == str(self.run_tab):
            self.record_global_navigation_entry(
                GlobalNavigationEntry(
                    'run_session',
                    'Run',
                    {'session_key': self.run_tab.global_navigation_session_key},
                    place_key=('run_session', self.run_tab.global_navigation_session_key),
                )
            )
            return
        if self.debugger_tab is not None and selected_tab_id == str(self.debugger_tab):
            self.record_global_navigation_entry(
                GlobalNavigationEntry(
                    'debugger_session',
                    'Debugger',
                    {'session_key': self.debugger_tab.global_navigation_session_key},
                    place_key=(
                        'debugger_session',
                        self.debugger_tab.global_navigation_session_key,
                    ),
                )
            )
            return
        if self.inspector_tab is not None and selected_tab_id == str(self.inspector_tab):
            self.record_global_navigation_entry(
                GlobalNavigationEntry(
                    'inspector_session',
                    'Inspect',
                    {'session_key': self.inspector_tab.global_navigation_session_key},
                    place_key=(
                        'inspector_session',
                        self.inspector_tab.global_navigation_session_key,
                    ),
                )
            )
            return
        if self.object_diagram_tab is not None and selected_tab_id == str(self.object_diagram_tab):
            self.record_global_navigation_entry(
                GlobalNavigationEntry(
                    'object_diagram_session',
                    'Object Diagram',
                    {'session_key': self.object_diagram_tab.global_navigation_session_key},
                    place_key=('object_diagram_session', self.object_diagram_tab.global_navigation_session_key),
                )
            )
            return
        if self.class_diagram_tab is not None and selected_tab_id == str(self.class_diagram_tab):
            self.record_global_navigation_entry(
                GlobalNavigationEntry(
                    'class_diagram_session',
                    'Class Diagram',
                    {'session_key': self.class_diagram_tab.global_navigation_session_key},
                    place_key=('class_diagram_session', self.class_diagram_tab.global_navigation_session_key),
                )
            )
            return
        self.refresh_global_navigation_controls()

    def global_history_label(self, history_entry):
        entry = history_entry['entry']
        label = entry.label
        if entry.is_stale:
            return f"{label} (unavailable)"
        return label

    def refresh_global_navigation_controls(self):
        if self.global_back_button is not None and self.global_back_button.winfo_exists():
            back_button_state = (
                tk.NORMAL
                if self.global_navigation_history.can_go_back()
                else tk.DISABLED
            )
            self.global_back_button.configure(state=back_button_state)
        if (
            self.global_forward_button is not None
            and self.global_forward_button.winfo_exists()
        ):
            forward_button_state = (
                tk.NORMAL
                if self.global_navigation_history.can_go_forward()
                else tk.DISABLED
            )
            self.global_forward_button.configure(state=forward_button_state)
        if (
            self.global_history_combobox is not None
            and self.global_history_combobox.winfo_exists()
        ):
            history_entries = (
                self.global_navigation_history.entries_with_current_marker()
            )
            self.global_history_choice_indices = []
            history_labels = []
            for history_entry in reversed(history_entries):
                history_index = history_entry['history_index']
                history_labels.append(self.global_history_label(history_entry))
                self.global_history_choice_indices.append(history_index)
            self.global_history_combobox['values'] = history_labels
            if len(history_labels) > 0:
                current_history_index = self.global_navigation_history.current_index
                selected_index = len(history_labels) - current_history_index - 1
                self.global_history_combobox.current(selected_index)
            if len(history_labels) == 0:
                self.global_history_combobox.set('')

    def mark_global_navigation_place_stale(self, place_key):
        self.global_navigation_history.mark_place_stale(place_key)
        self.refresh_global_navigation_controls()

    def tab_for_global_navigation_session(self, kind, session_key):
        if kind == 'run_session':
            candidate = self.run_tab
        elif kind == 'debugger_session':
            candidate = self.debugger_tab
        elif kind == 'inspector_session':
            candidate = self.inspector_tab
        elif kind == 'object_diagram_session':
            candidate = self.object_diagram_tab
        elif kind == 'class_diagram_session':
            candidate = self.class_diagram_tab
        else:
            candidate = None
        if candidate is None or not candidate.winfo_exists():
            return None
        if getattr(candidate, 'global_navigation_session_key', None) != session_key:
            return None
        return candidate

    def restore_global_navigation_entry(self, entry):
        if entry is None or entry.is_stale:
            return False
        if entry.kind in ('browser_method', 'browser_selection'):
            browser_state = entry.payload.get('browser_state')
            if browser_state is None:
                return False
            self.gemstone_session_record.browse_mode = browser_state['browse_mode']
            self.gemstone_session_record.selected_package = browser_state[
                'selected_package'
            ]
            self.gemstone_session_record.selected_dictionary = browser_state[
                'selected_dictionary'
            ]
            self.gemstone_session_record.selected_class = browser_state['selected_class']
            self.gemstone_session_record.selected_method_category = browser_state[
                'selected_method_category'
            ]
            self.gemstone_session_record.selected_method_symbol = browser_state[
                'selected_method_symbol'
            ]
            self.gemstone_session_record.show_instance_side = browser_state[
                'show_instance_side'
            ]
            self.event_queue.publish('BrowseModeChanged')
            self.event_queue.publish('SelectedClassChanged')
            self.event_queue.publish('SelectedCategoryChanged')
            self.event_queue.publish('MethodSelected')
            if self.browser_tab is not None and self.browser_tab.winfo_exists():
                self.notebook.select(self.browser_tab)
            return True
        session_key = entry.payload.get('session_key')
        session_tab = self.tab_for_global_navigation_session(entry.kind, session_key)
        if session_tab is None:
            self.mark_global_navigation_place_stale(entry.place_key)
            return False
        self.notebook.select(session_tab)
        return True

    def navigate_global_history(self, direction):
        history_entry = None
        if direction == 'back':
            history_entry = self.global_navigation_history.go_back()
        if direction == 'forward':
            history_entry = self.global_navigation_history.go_forward()
        if history_entry is None:
            self.refresh_global_navigation_controls()
            return
        self.global_navigation_selection_in_progress = True
        try:
            restored = self.restore_global_navigation_entry(history_entry)
        finally:
            self.global_navigation_selection_in_progress = False
        if restored:
            self.refresh_global_navigation_controls()
            return
        self.navigate_global_history(direction)

    def go_to_previous_global_place(self):
        self.navigate_global_history('back')

    def go_to_next_global_place(self):
        self.navigate_global_history('forward')

    def jump_to_selected_global_history_entry(self, event=None):
        combobox_index = self.global_history_combobox.current()
        if combobox_index < 0:
            return
        if combobox_index >= len(self.global_history_choice_indices):
            return
        history_index = self.global_history_choice_indices[combobox_index]
        selected_entry = self.global_navigation_history.entries[history_index]
        if selected_entry.is_stale:
            self.refresh_global_navigation_controls()
            return
        self.global_navigation_history.jump_to(history_index)
        self.global_navigation_selection_in_progress = True
        try:
            restored = self.restore_global_navigation_entry(selected_entry)
        finally:
            self.global_navigation_selection_in_progress = False
        if not restored:
            self.refresh_global_navigation_controls()
            return
        self.refresh_global_navigation_controls()

    def set_mcp_activity_indicator_visibility(self, visible):
        if self.mcp_activity_indicator is None:
            self.mcp_activity_indicator_visible = False
            return
        indicator_is_managed = self.mcp_activity_indicator.winfo_manager() == "grid"
        if visible:
            if not indicator_is_managed:
                self.mcp_activity_indicator.grid()
            self.mcp_activity_indicator.step(1)
            self.mcp_activity_indicator.start(10)
            if not self.mcp_activity_indicator_visible:
                self.event_queue.publish(
                    "UiActivityIndicatorChanged",
                    is_visible=True,
                )
            self.mcp_activity_indicator_visible = True
            return
        if indicator_is_managed:
            self.mcp_activity_indicator.stop()
            self.mcp_activity_indicator.configure(value=0)
            self.mcp_activity_indicator.grid_remove()
        if self.mcp_activity_indicator_visible:
            self.mcp_activity_indicator_visible = False
            self.event_queue.publish(
                "UiActivityIndicatorChanged",
                is_visible=False,
            )
            return
        self.mcp_activity_indicator_visible = False

    def begin_foreground_activity(self, message):
        self.foreground_activity_message = message
        self.event_queue.publish(
            "UiActivityChanged",
            is_active=True,
            message=message,
        )
        self.collaboration_status_text.set(message)
        self.set_mcp_activity_indicator_visibility(True)
        try:
            self.config(cursor="watch")
        except tk.TclError:
            pass
        self.update_idletasks()

    def end_foreground_activity(self):
        self.foreground_activity_message = ""
        self.event_queue.publish(
            "UiActivityChanged",
            is_active=False,
            message="",
        )
        try:
            self.config(cursor="")
        except tk.TclError:
            pass
        self.refresh_collaboration_status()

    def publish_mcp_busy_state_event(self, is_busy=False, operation_name=""):
        busy_lease_token = self.busy_coordinator.lease_for_state(
            is_busy=is_busy,
            operation_name=operation_name,
        )
        self.event_queue.publish(
            "McpBusyStateChanged",
            is_busy=is_busy,
            operation_name=operation_name,
            busy_lease_token=busy_lease_token,
        )

    def publish_mcp_server_state_event(
        self,
        running=False,
        starting=False,
        stopping=False,
        endpoint_url="",
        configured_endpoint_url="",
        restart_required_for_config=False,
        last_error_message="",
    ):
        self.event_queue.publish(
            "McpServerStateChanged",
            running=running,
            starting=starting,
            stopping=stopping,
            endpoint_url=endpoint_url,
            configured_endpoint_url=configured_endpoint_url,
            restart_required_for_config=restart_required_for_config,
            last_error_message=last_error_message,
        )

    def publish_model_refresh_requested_event(self, change_kind=""):
        self.event_queue.publish(
            "ModelRefreshRequested",
            change_kind=change_kind,
        )

    def process_pending_model_refresh_requests(self):
        pending_change_kinds = (
            self.integrated_session_state.consume_model_refresh_requests()
        )
        if not self.is_logged_in:
            return
        for change_kind in pending_change_kinds:
            self.publish_model_change_events(change_kind)

    def apply_collaboration_read_only_state(self, read_only):
        if self.browser_tab is not None and self.browser_tab.winfo_exists():
            self.browser_tab.editor_area_widget.set_read_only(read_only)
        if self.run_tab is not None and self.run_tab.winfo_exists():
            self.run_tab.set_read_only(read_only)

    def refresh_collaboration_status(self):
        if not self.winfo_exists():
            return
        mcp_busy = self.integrated_session_state.is_mcp_busy()
        mcp_server_status = self.mcp_server_controller.status()
        mcp_server_running = mcp_server_status["running"]
        mcp_server_starting = mcp_server_status["starting"]
        mcp_server_stopping = mcp_server_status["stopping"]
        self.apply_collaboration_read_only_state(
            self.action_gate.read_only_for('ide_write', is_busy=mcp_busy)
        )
        self.set_mcp_activity_indicator_visibility(
            bool(self.foreground_activity_message)
            or mcp_busy
            or mcp_server_starting
            or mcp_server_stopping
        )
        if self.foreground_activity_message:
            self.collaboration_status_text.set(self.foreground_activity_message)
        elif mcp_busy:
            operation_name = (
                self.integrated_session_state.current_mcp_operation_name() or "unknown"
            )
            self.collaboration_status_text.set(
                "MCP busy: %s. IDE write/run/debug actions are read-only."
                % operation_name
            )
        elif mcp_server_stopping:
            self.collaboration_status_text.set("Stopping MCP server...")
        elif mcp_server_starting:
            self.collaboration_status_text.set("Starting MCP server...")
        elif mcp_server_running:
            runtime_message = "IDE ready. MCP running at %s." % (
                mcp_server_status["endpoint_url"]
            )
            if mcp_server_status.get("restart_required_for_config"):
                runtime_message = (
                    runtime_message
                    + " MCP config changed; stop and start MCP to apply latest settings."
                )
            self.collaboration_status_text.set(runtime_message)
        elif self.is_logged_in:
            self.collaboration_status_text.set("IDE ready. Embedded MCP is stopped.")
        else:
            self.collaboration_status_text.set("")

    def handle_mcp_busy_state_changed(
        self,
        is_busy=False,
        operation_name="",
        busy_lease_token=None,
    ):
        if not self.busy_coordinator.is_current_lease(busy_lease_token):
            return
        self.last_mcp_busy_state = is_busy
        self.refresh_collaboration_status()

    def handle_mcp_server_state_changed(
        self,
        running=False,
        starting=False,
        stopping=False,
        endpoint_url="",
        configured_endpoint_url="",
        restart_required_for_config=False,
        last_error_message="",
    ):
        self.last_mcp_server_running_state = running
        self.last_mcp_server_starting_state = starting
        self.last_mcp_server_stopping_state = stopping
        if (
            last_error_message
            and last_error_message != self.last_mcp_server_error_message
        ):
            self.last_mcp_server_error_message = last_error_message
            messagebox.showerror(
                "MCP Startup Failed",
                last_error_message,
            )
        if not last_error_message:
            self.last_mcp_server_error_message = None
        self.refresh_collaboration_status()

    def handle_open_run_window(self, source=''):
        self.open_run_tab()
        self.run_tab.present_source(source, run_immediately=False)

    def handle_model_refresh_requested(self, change_kind=""):
        self.process_pending_model_refresh_requests()
        self.refresh_collaboration_status()

    def validated_oop_label_for_navigation(self, oop_value):
        oop_label = ""
        if isinstance(oop_value, int):
            oop_label = str(oop_value)
        if isinstance(oop_value, str):
            oop_label = oop_value.strip()
        if not oop_label.isdigit():
            raise DomainException("oop labels must contain digits only.")
        if int(oop_label) <= 0:
            raise DomainException("oop labels must be positive integers.")
        return oop_label

    def gemstone_object_is_nil(self, gemstone_object):
        try:
            nil_value = gemstone_object.isNil().to_py
            if isinstance(nil_value, bool):
                return nil_value
            return False
        except (GemstoneError, AttributeError):
            return False

    def gemstone_object_for_oop_label(self, oop_label):
        if not self.is_logged_in:
            raise DomainException("No active GemStone session in the IDE.")
        normalized_oop_label = self.validated_oop_label_for_navigation(oop_label)
        source_candidates = [
            f"Object _objectForOop: {normalized_oop_label}",
            f"System objectForOop: {normalized_oop_label}",
        ]
        resolved_object = None
        resolved = False
        last_error = None
        for source_code in source_candidates:
            try:
                candidate_object = self.gemstone_session_record.resolve_object(
                    source_code
                )
                if self.gemstone_object_is_nil(candidate_object):
                    last_error = DomainException(
                        f"Oop {normalized_oop_label} resolved to nil."
                    )
                if not self.gemstone_object_is_nil(candidate_object):
                    resolved_object = candidate_object
                    resolved = True
            except (DomainException, GemstoneDomainException, GemstoneError) as error:
                last_error = error
            if resolved:
                return resolved_object
        if last_error is None:
            last_error = DomainException(
                f"Unable to resolve oop {normalized_oop_label}."
            )
        raise last_error

    def open_object_diagram_for_oop_labels(self, oop_labels, clear_existing=False):
        if not self.is_logged_in:
            return {
                "ok": False,
                "error": {"message": "No active GemStone session in the IDE."},
                "opened_oops": [],
                "unresolved_oops": [],
            }
        if clear_existing:
            tab_exists = self.object_diagram_tab is not None and self.object_diagram_tab.winfo_exists()
            if tab_exists:
                self.object_diagram_tab.clear_diagram()
        opened_oops = []
        unresolved_oops = []
        for oop_label in oop_labels:
            normalized_oop_label = ""
            opened_object = None
            failure_message = ""
            try:
                normalized_oop_label = self.validated_oop_label_for_navigation(
                    oop_label
                )
                opened_object = self.gemstone_object_for_oop_label(normalized_oop_label)
            except (DomainException, GemstoneDomainException, GemstoneError) as error:
                failure_message = str(error)
            if opened_object is not None:
                self.open_object_diagram_for_object(opened_object)
                opened_oops.append(normalized_oop_label)
            if opened_object is None:
                unresolved_label = str(oop_label)
                if normalized_oop_label:
                    unresolved_label = normalized_oop_label
                unresolved_oops.append(
                    {
                        "oop": unresolved_label,
                        "message": failure_message or "Unable to resolve oop.",
                    }
                )
        return {
            "ok": len(opened_oops) > 0,
            "opened_oops": opened_oops,
            "unresolved_oops": unresolved_oops,
            "object_diagram_tab_open": self.object_diagram_tab is not None
            and self.object_diagram_tab.winfo_exists(),
        }

    def method_context_payload(self, method_context):
        if method_context is None:
            return None
        try:
            class_name, show_instance_side, method_symbol = method_context
        except (TypeError, ValueError):
            return None
        return {
            "class_name": class_name,
            "show_instance_side": show_instance_side,
            "method_symbol": method_symbol,
        }

    def text_widget_selection_state(self, text_widget):
        empty_selection_state = {
            "has_selection": False,
            "selection_start": None,
            "selection_end": None,
            "selected_text": "",
            "cursor_index": None,
        }
        if text_widget is None:
            return empty_selection_state
        try:
            if not text_widget.winfo_exists():
                return empty_selection_state
        except AttributeError:
            return empty_selection_state
        editable_text = EditableText(text_widget, self)
        selection_start, selection_end = editable_text.selected_range()
        selected_text = ""
        if selection_start is not None:
            try:
                selected_text = text_widget.get(selection_start, selection_end)
            except tk.TclError:
                selection_start = None
                selection_end = None
                selected_text = ""
        cursor_index = None
        try:
            cursor_index = text_widget.index(tk.INSERT)
        except tk.TclError:
            cursor_index = None
        return {
            "has_selection": selection_start is not None,
            "selection_start": selection_start,
            "selection_end": selection_end,
            "selected_text": selected_text,
            "cursor_index": cursor_index,
        }

    def browser_editor_state(self):
        if self.browser_tab is None or not self.browser_tab.winfo_exists():
            return None
        method_editor = self.browser_tab.editor_area_widget
        selected_editor_tab_id = ""
        try:
            selected_editor_tab_id = method_editor.editor_notebook.select()
        except tk.TclError:
            selected_editor_tab_id = ""
        active_editor_tab_label = None
        method_context = None
        selection_state = self.text_widget_selection_state(None)
        if selected_editor_tab_id:
            try:
                active_editor_tab_label = method_editor.editor_notebook.tab(
                    selected_editor_tab_id,
                    "text",
                )
            except tk.TclError:
                active_editor_tab_label = None
            selected_editor_tab = None
            try:
                selected_editor_tab = method_editor.editor_notebook.nametowidget(
                    selected_editor_tab_id
                )
            except tk.TclError:
                selected_editor_tab = None
            code_panel = None
            if selected_editor_tab is not None:
                code_panel = getattr(selected_editor_tab, "code_panel", None)
            if code_panel is not None:
                method_context = self.method_context_payload(
                    code_panel.method_context()
                )
                selection_state = self.text_widget_selection_state(
                    code_panel.text_editor
                )
        return {
            "active_editor_tab_label": active_editor_tab_label,
            "method_context": method_context,
            "selection": selection_state,
        }

    def debugger_source_state(self):
        if self.debugger_tab is None or not self.debugger_tab.winfo_exists():
            return None
        selected_frame = self.debugger_tab.get_selected_stack_frame()
        selected_frame_payload = None
        method_context = None
        if selected_frame is not None:
            selected_frame_payload = {
                "level": selected_frame.level,
                "class_name": selected_frame.class_name,
                "method_name": selected_frame.method_name,
                "step_point_offset": selected_frame.step_point_offset,
            }
            method_context = self.method_context_payload(
                self.debugger_tab.frame_method_context(selected_frame)
            )
        debugger_code_panel = getattr(self.debugger_tab, "code_panel", None)
        debugger_text_widget = None
        if debugger_code_panel is not None:
            debugger_text_widget = getattr(debugger_code_panel, "text_editor", None)
        selection_state = self.text_widget_selection_state(debugger_text_widget)
        return {
            "running": self.debugger_tab.is_running,
            "selected_frame": selected_frame_payload,
            "method_context": method_context,
            "selection": selection_state,
        }

    def run_source_state(self):
        if self.run_tab is None or not self.run_tab.winfo_exists():
            return None
        return {
            "selection": self.text_widget_selection_state(self.run_tab.source_text),
        }

    def mcp_runtime_state_for_ai(self):
        mcp_server_status = self.mcp_server_controller.status()
        return {
            "running": mcp_server_status["running"],
            "starting": mcp_server_status["starting"],
            "stopping": mcp_server_status["stopping"],
            "endpoint_url": mcp_server_status["endpoint_url"],
            "configured_endpoint_url": mcp_server_status["configured_endpoint_url"],
            "restart_required_for_config": mcp_server_status.get(
                "restart_required_for_config",
                False,
            ),
            "config_file_path": self.mcp_server_controller.configuration_store.config_file_path(),
            "last_save_error_message": self.last_mcp_config_save_error_message,
            "desired_runtime_config": self.mcp_runtime_config.to_dict(),
        }

    def current_ide_view_state(self):
        active_tab_id = None
        active_tab_label = None
        active_tab_kind = 'none'
        if self.notebook is not None and self.notebook.winfo_exists():
            try:
                active_tab_id = self.notebook.select()
            except tk.TclError:
                active_tab_id = None
            if active_tab_id:
                try:
                    active_tab_label = self.notebook.tab(active_tab_id, 'text')
                except tk.TclError:
                    active_tab_label = None
        if self.browser_tab is not None and active_tab_id == str(self.browser_tab):
            active_tab_kind = 'browser'
        if self.run_tab is not None and active_tab_id == str(self.run_tab):
            active_tab_kind = 'run'
        if self.debugger_tab is not None and active_tab_id == str(self.debugger_tab):
            active_tab_kind = 'debugger'
        if self.inspector_tab is not None and active_tab_id == str(self.inspector_tab):
            active_tab_kind = 'inspect'
        if self.object_diagram_tab is not None and active_tab_id == str(self.object_diagram_tab):
            active_tab_kind = 'object_diagram'
        if self.class_diagram_tab is not None and active_tab_id == str(self.class_diagram_tab):
            active_tab_kind = 'class_diagram'
        if active_tab_kind == 'none' and active_tab_label:
            active_tab_kind = active_tab_label.lower()

        browser_state = None
        if self.is_logged_in:
            class_view_mode = None
            if self.browser_tab is not None and self.browser_tab.winfo_exists():
                class_view_mode = (
                    'hierarchy'
                    if self.browser_tab.classes_widget.selected_tab_is_hierarchy()
                    else 'list'
                )
            browser_state = {
                'browse_mode': self.gemstone_session_record.browse_mode,
                'selected_package': self.gemstone_session_record.selected_package,
                'selected_dictionary': self.gemstone_session_record.selected_dictionary,
                'selected_class': self.gemstone_session_record.selected_class,
                'selected_method_category': (
                    self.gemstone_session_record.selected_method_category
                ),
                'selected_method_symbol': self.gemstone_session_record.selected_method_symbol,
                'show_instance_side': self.gemstone_session_record.show_instance_side,
                'class_view_mode': class_view_mode,
            }

        debugger_state = self.debugger_source_state()
        active_source_view = None
        if active_tab_kind == 'browser':
            browser_editor_state = self.browser_editor_state()
            active_source_view = {
                'kind': 'browser_method_source',
                'state': browser_editor_state,
            }
        if active_tab_kind == 'debugger':
            active_source_view = {
                'kind': 'debugger_method_source',
                'state': debugger_state,
            }
        if active_tab_kind == 'run':
            active_source_view = {
                'kind': 'run_source',
                'state': self.run_source_state(),
            }
        return {
            'ok': True,
            'is_logged_in': self.is_logged_in,
            'active_tab': {
                'label': active_tab_label,
                'kind': active_tab_kind,
            },
            'browser_state': browser_state,
            'debugger_state': debugger_state,
            'active_source_view': active_source_view,
            'find_dialog_state': self.find_dialog_state_for_mcp(),
            'mcp_runtime': self.mcp_runtime_state_for_ai(),
        }

    def active_find_dialog(self):
        find_dialog = None
        child_windows = list(self.winfo_children())
        for child_window in child_windows:
            child_is_find_dialog = isinstance(child_window, FindDialog)
            child_window_exists = False
            if child_is_find_dialog:
                try:
                    child_window_exists = bool(child_window.winfo_exists())
                except tk.TclError:
                    child_window_exists = False
            if child_is_find_dialog and child_window_exists:
                find_dialog = child_window
        return find_dialog

    def find_dialog_state_for_mcp(self):
        find_dialog = self.active_find_dialog()
        if find_dialog is None:
            return {
                'is_open': False,
                'is_sender_reference_search': False,
                'total_static_sender_count': 0,
                'displayed_sender_count': 0,
                'displayed_senders': [],
                'static_senders': [],
                'sender_selector_query': None,
                'sender_source_class_name': None,
            }
        return find_dialog.sender_filter_state_for_mcp()

    def validated_sender_filter_values(self, filter_values, argument_name):
        if filter_values is None:
            return []
        if not isinstance(filter_values, list):
            raise DomainException('%s must be a list of strings or None.' % argument_name)
        validated_values = []
        for index, filter_value in enumerate(filter_values):
            if not isinstance(filter_value, str):
                raise DomainException('%s[%s] must be a string.' % (argument_name, index))
            normalized_filter_value = filter_value.strip()
            if normalized_filter_value:
                validated_values.append(normalized_filter_value)
        return validated_values

    def filter_active_find_dialog_senders(
        self,
        class_category_filters=None,
        class_name_filters=None,
        method_selector_filters=None,
        method_category_filters=None,
        include_extension_method_category_for_class_category=True,
        reasoning_note='',
    ):
        find_dialog = self.active_find_dialog()
        if find_dialog is None:
            return {
                'ok': False,
                'error': {'message': 'No open Find dialog in the IDE.'},
            }
        return find_dialog.apply_sender_filters(
            class_category_filters=class_category_filters,
            class_name_filters=class_name_filters,
            method_selector_filters=method_selector_filters,
            method_category_filters=method_category_filters,
            include_extension_method_category_for_class_category=(
                include_extension_method_category_for_class_category
            ),
            reasoning_note=reasoning_note,
        )

    def narrow_find_dialog_senders_to_source_class_category(self):
        find_dialog = self.active_find_dialog()
        if find_dialog is None:
            return {
                'ok': False,
                'error': {'message': 'No open Find dialog in the IDE.'},
            }
        return find_dialog.narrow_to_source_class_category()

    def execute_mcp_ide_navigation_action(self, action_name, action_parameters=None):
        if action_parameters is None:
            action_parameters = {}
        if action_name == "open_object_diagram_for_oops":
            oop_labels = action_parameters.get("oop_labels")
            if not isinstance(oop_labels, list):
                return {
                    "ok": False,
                    "error": {"message": "oop_labels must be a list."},
                }
            clear_existing = action_parameters.get("clear_existing", False)
            if not isinstance(clear_existing, bool):
                return {
                    "ok": False,
                    "error": {"message": "clear_existing must be a boolean."},
                }
            return self.open_object_diagram_for_oop_labels(
                oop_labels,
                clear_existing=clear_existing,
            )
        if action_name == "select_class":
            class_name = action_parameters.get("class_name")
            if not isinstance(class_name, str):
                return {
                    "ok": False,
                    "error": {"message": "class_name must be a string."},
                }
            class_name = class_name.strip()
            if not class_name:
                return {
                    "ok": False,
                    "error": {"message": "class_name cannot be empty."},
                }
            show_instance_side = action_parameters.get("show_instance_side", True)
            if not isinstance(show_instance_side, bool):
                return {
                    "ok": False,
                    "error": {"message": "show_instance_side must be a boolean."},
                }
            if not self.is_logged_in:
                return {
                    "ok": False,
                    "error": {"message": "No active GemStone session in the IDE."},
                }
            try:
                self.handle_find_selection(show_instance_side, class_name)
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    "ok": False,
                    "error": {"message": str(error)},
                }
            return {
                "ok": True,
                "class_name": class_name,
                "show_instance_side": show_instance_side,
            }
        if action_name == "open_method":
            class_name = action_parameters.get("class_name")
            if not isinstance(class_name, str):
                return {
                    "ok": False,
                    "error": {"message": "class_name must be a string."},
                }
            class_name = class_name.strip()
            if not class_name:
                return {
                    "ok": False,
                    "error": {"message": "class_name cannot be empty."},
                }
            method_symbol = action_parameters.get("method_symbol")
            if not isinstance(method_symbol, str):
                return {
                    "ok": False,
                    "error": {"message": "method_symbol must be a string."},
                }
            method_symbol = method_symbol.strip()
            if not method_symbol:
                return {
                    "ok": False,
                    "error": {"message": "method_symbol cannot be empty."},
                }
            show_instance_side = action_parameters.get("show_instance_side", True)
            if not isinstance(show_instance_side, bool):
                return {
                    "ok": False,
                    "error": {"message": "show_instance_side must be a boolean."},
                }
            if not self.is_logged_in:
                return {
                    "ok": False,
                    "error": {"message": "No active GemStone session in the IDE."},
                }
            try:
                self.handle_sender_selection(
                    class_name,
                    show_instance_side,
                    method_symbol,
                )
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    "ok": False,
                    "error": {"message": str(error)},
                }
            return {
                "ok": True,
                "class_name": class_name,
                "show_instance_side": show_instance_side,
                "method_symbol": method_symbol,
            }
        if action_name == "open_debugger_for_exception":
            exception = action_parameters.get("exception")
            if exception is None:
                return {
                    "ok": False,
                    "error": {"message": "exception is required."},
                }
            ask_before_open = action_parameters.get("ask_before_open", False)
            if not isinstance(ask_before_open, bool):
                return {
                    "ok": False,
                    "error": {"message": "ask_before_open must be a boolean."},
                }
            return self.open_debugger_for_mcp_exception(
                exception,
                ask_before_open=ask_before_open,
            )
        if action_name == "open_run_window":
            source = action_parameters.get("source", "")
            if not isinstance(source, str):
                return {
                    "ok": False,
                    "error": {"message": "source must be a string."},
                }
            if not self.is_logged_in:
                return {
                    "ok": False,
                    "error": {"message": "No active GemStone session in the IDE."},
                }
            self.event_queue.publish("OpenRunWindow", source=source)
            return {
                "ok": True,
                "source": source,
            }
        if action_name == 'query_class_diagram':
            return {
                'ok': True,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == 'add_class_to_class_diagram':
            class_name = action_parameters.get('class_name')
            if not isinstance(class_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'class_name must be a string.'},
                }
            class_name = class_name.strip()
            if not class_name:
                return {
                    'ok': False,
                    'error': {'message': 'class_name cannot be empty.'},
                }
            if not self.is_logged_in:
                return {
                    'ok': False,
                    'error': {'message': 'No active GemStone session in the IDE.'},
                }
            try:
                self.open_class_diagram_for_class(class_name)
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    'ok': False,
                    'error': {'message': str(error)},
                }
            return {
                'ok': True,
                'class_name': class_name,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == 'remove_class_from_class_diagram':
            class_name = action_parameters.get('class_name')
            if not isinstance(class_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'class_name must be a string.'},
                }
            class_name = class_name.strip()
            if not class_name:
                return {
                    'ok': False,
                    'error': {'message': 'class_name cannot be empty.'},
                }
            if self.class_diagram_tab is None or not self.class_diagram_tab.winfo_exists():
                return {
                    'ok': False,
                    'error': {'message': 'No open class diagram in the IDE.'},
                }
            self.class_diagram_tab.remove_class_from_diagram(class_name)
            return {
                'ok': True,
                'class_name': class_name,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == 'pin_method_in_class_diagram':
            class_name = action_parameters.get('class_name')
            if not isinstance(class_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'class_name must be a string.'},
                }
            class_name = class_name.strip()
            if not class_name:
                return {
                    'ok': False,
                    'error': {'message': 'class_name cannot be empty.'},
                }
            method_symbol = action_parameters.get('method_symbol')
            if not isinstance(method_symbol, str):
                return {
                    'ok': False,
                    'error': {'message': 'method_symbol must be a string.'},
                }
            method_symbol = method_symbol.strip()
            if not method_symbol:
                return {
                    'ok': False,
                    'error': {'message': 'method_symbol cannot be empty.'},
                }
            show_instance_side = action_parameters.get('show_instance_side', True)
            if not isinstance(show_instance_side, bool):
                return {
                    'ok': False,
                    'error': {'message': 'show_instance_side must be a boolean.'},
                }
            if not self.is_logged_in:
                return {
                    'ok': False,
                    'error': {'message': 'No active GemStone session in the IDE.'},
                }
            try:
                self.pin_method_in_class_diagram(
                    class_name,
                    show_instance_side,
                    method_symbol,
                )
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    'ok': False,
                    'error': {'message': str(error)},
                }
            return {
                'ok': True,
                'class_name': class_name,
                'method_symbol': method_symbol,
                'show_instance_side': show_instance_side,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == 'add_association_to_class_diagram':
            source_class_name = action_parameters.get('source_class_name')
            if not isinstance(source_class_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'source_class_name must be a string.'},
                }
            source_class_name = source_class_name.strip()
            if not source_class_name:
                return {
                    'ok': False,
                    'error': {'message': 'source_class_name cannot be empty.'},
                }
            target_class_name = action_parameters.get('target_class_name')
            if not isinstance(target_class_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'target_class_name must be a string.'},
                }
            target_class_name = target_class_name.strip()
            if not target_class_name:
                return {
                    'ok': False,
                    'error': {'message': 'target_class_name cannot be empty.'},
                }
            inst_var_name = action_parameters.get('inst_var_name')
            if not isinstance(inst_var_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'inst_var_name must be a string.'},
                }
            inst_var_name = inst_var_name.strip()
            if not inst_var_name:
                return {
                    'ok': False,
                    'error': {'message': 'inst_var_name cannot be empty.'},
                }
            if not self.is_logged_in:
                return {
                    'ok': False,
                    'error': {'message': 'No active GemStone session in the IDE.'},
                }
            try:
                uml_tab = self.ensure_class_diagram_tab()
                uml_tab.add_association(
                    source_class_name,
                    inst_var_name,
                    target_class_name,
                )
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    'ok': False,
                    'error': {'message': str(error)},
                }
            return {
                'ok': True,
                'source_class_name': source_class_name,
                'target_class_name': target_class_name,
                'inst_var_name': inst_var_name,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == 'add_inheritance_details_to_class_diagram':
            source_class_name = action_parameters.get('source_class_name')
            if not isinstance(source_class_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'source_class_name must be a string.'},
                }
            source_class_name = source_class_name.strip()
            if not source_class_name:
                return {
                    'ok': False,
                    'error': {'message': 'source_class_name cannot be empty.'},
                }
            target_class_name = action_parameters.get('target_class_name')
            if not isinstance(target_class_name, str):
                return {
                    'ok': False,
                    'error': {'message': 'target_class_name must be a string.'},
                }
            target_class_name = target_class_name.strip()
            if not target_class_name:
                return {
                    'ok': False,
                    'error': {'message': 'target_class_name cannot be empty.'},
                }
            if self.class_diagram_tab is None or not self.class_diagram_tab.winfo_exists():
                return {
                    'ok': False,
                    'error': {'message': 'No open class diagram in the IDE.'},
                }
            try:
                added_class_names = self.class_diagram_tab.add_inheritance_details_for(
                    source_class_name,
                    target_class_name,
                )
            except (
                DomainException,
                GemstoneDomainException,
                GemstoneError,
            ) as error:
                return {
                    'ok': False,
                    'error': {'message': str(error)},
                }
            return {
                'ok': True,
                'source_class_name': source_class_name,
                'target_class_name': target_class_name,
                'added_class_names': added_class_names,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == 'clear_class_diagram':
            if self.class_diagram_tab is None or not self.class_diagram_tab.winfo_exists():
                return {
                    'ok': False,
                    'error': {'message': 'No open class diagram in the IDE.'},
                }
            diagram_changed = self.class_diagram_tab.clear_diagram()
            return {
                'ok': True,
                'diagram_changed': diagram_changed,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == 'undo_class_diagram':
            if self.class_diagram_tab is None or not self.class_diagram_tab.winfo_exists():
                return {
                    'ok': False,
                    'error': {'message': 'No open class diagram in the IDE.'},
                }
            diagram_changed = self.class_diagram_tab.undo_diagram()
            return {
                'ok': True,
                'diagram_changed': diagram_changed,
                'class_diagram_state': self.class_diagram_state_for_mcp(),
            }
        if action_name == "filter_senders_in_find_dialog":
            try:
                class_category_filters = self.validated_sender_filter_values(
                    action_parameters.get("class_category_filters"),
                    "class_category_filters",
                )
                class_name_filters = self.validated_sender_filter_values(
                    action_parameters.get("class_name_filters"),
                    "class_name_filters",
                )
                method_selector_filters = self.validated_sender_filter_values(
                    action_parameters.get("method_selector_filters"),
                    "method_selector_filters",
                )
                method_category_filters = self.validated_sender_filter_values(
                    action_parameters.get("method_category_filters"),
                    "method_category_filters",
                )
                include_extension_method_category_for_class_category = (
                    action_parameters.get(
                        "include_extension_method_category_for_class_category",
                        True,
                    )
                )
                if not isinstance(
                    include_extension_method_category_for_class_category,
                    bool,
                ):
                    raise DomainException(
                        "include_extension_method_category_for_class_category must be a boolean."
                    )
                reasoning_note = action_parameters.get("reasoning_note", "")
                if not isinstance(reasoning_note, str):
                    raise DomainException("reasoning_note must be a string.")
            except DomainException as error:
                return {
                    "ok": False,
                    "error": {"message": str(error)},
                }
            return self.filter_active_find_dialog_senders(
                class_category_filters=class_category_filters,
                class_name_filters=class_name_filters,
                method_selector_filters=method_selector_filters,
                method_category_filters=method_category_filters,
                include_extension_method_category_for_class_category=(
                    include_extension_method_category_for_class_category
                ),
                reasoning_note=reasoning_note,
            )
        if action_name == "query_current_view":
            return self.current_ide_view_state()
        if action_name == "query_find_dialog_state":
            return {'ok': True, **self.find_dialog_state_for_mcp()}
        if action_name == "narrow_senders_to_source_class_category":
            return self.narrow_find_dialog_senders_to_source_class_category()
        return {
            "ok": False,
            "error": {"message": f"Unknown IDE navigation action: {action_name}."},
        }

    def handle_mcp_ide_navigation_requested(
        self,
        action_name="",
        action_parameters=None,
        response_holder=None,
        completion_event=None,
    ):
        response = self.execute_mcp_ide_navigation_action(
            action_name,
            action_parameters,
        )
        if response_holder is not None:
            response_holder["response"] = response
        if completion_event is not None:
            completion_event.set()

    def perform_mcp_ide_navigation_action(self, action_name, action_parameters=None):
        if action_parameters is None:
            action_parameters = {}
        in_ui_thread = threading.get_ident() == self.event_queue.root_thread_ident
        if in_ui_thread:
            return self.execute_mcp_ide_navigation_action(
                action_name,
                action_parameters,
            )
        response_holder = {}
        completion_event = threading.Event()
        self.event_queue.publish(
            "McpIdeNavigationRequested",
            action_name=action_name,
            action_parameters=action_parameters,
            response_holder=response_holder,
            completion_event=completion_event,
        )
        completed = completion_event.wait(timeout=5.0)
        if not completed:
            return {
                "ok": False,
                "error": {"message": "IDE navigation request timed out."},
            }
        response = response_holder.get("response")
        if isinstance(response, dict):
            return response
        return {
            "ok": False,
            "error": {"message": "IDE navigation request returned no response."},
        }

    def synchronise_collaboration_state(self):
        if not self.winfo_exists():
            return
        self.process_pending_model_refresh_requests()
        self.publish_mcp_busy_state_event(
            is_busy=self.integrated_session_state.is_mcp_busy(),
            operation_name=self.integrated_session_state.current_mcp_operation_name(),
        )
        self.publish_mcp_server_state_event(**self.mcp_server_controller.status())
        self.refresh_collaboration_status()

    def destroy(self):
        self.mcp_server_controller.clear_subscribers(self)
        self.integrated_session_state.clear_subscribers(self)
        self.event_queue.clear_subscribers(self)
        self.mcp_server_controller.stop()
        self.integrated_session_state.detach_ide_gui()
        self.event_queue.close()
        super().destroy()

    def add_browser_tab(self):
        if self.browser_tab:
            self.browser_tab.destroy()
        self.browser_tab = BrowserWindow(self.notebook, self)
        self.notebook.add(self.browser_tab, text="Browser")

    def open_debugger(self, exception):
        if self.integrated_session_state.is_mcp_busy():
            messagebox.showwarning(
                "MCP Busy",
                "Debugging is disabled while MCP is running an operation.",
            )
            return
        self.open_debugger_with_optional_confirmation(
            exception,
            ask_before_open=False,
        )

    def open_debugger_with_optional_confirmation(
        self,
        exception,
        ask_before_open=False,
    ):
        self.ensure_current_browser_place_in_global_history()
        if ask_before_open:
            response = messagebox.askquestion(
                "Open Debugger",
                "MCP requested opening a debugger for a failure. Open it now?",
                icon="warning",
                type="okcancel",
            )
            if response == "cancel":
                return False
        if self.debugger_tab:
            if self.debugger_tab.is_running:
                response = messagebox.askquestion(
                    "Debugger Already Open",
                    "A debugger is already open. Replace it with a new one?",
                    icon="warning",
                    type="okcancel",
                )
                if response == "cancel":
                    return False
            debugger_session_key = getattr(
                self.debugger_tab,
                'global_navigation_session_key',
                None,
            )
            if debugger_session_key:
                self.mark_global_navigation_place_stale(
                    ('debugger_session', debugger_session_key),
                )
            self.debugger_tab.destroy()

        self.add_debugger_tab(exception)
        self.select_debugger_tab()
        return True

    def open_debugger_for_mcp_exception(
        self,
        exception,
        ask_before_open=False,
    ):
        if not self.is_logged_in:
            return {
                "ok": False,
                "error": {"message": "No active GemStone session in the IDE."},
            }
        debugger_opened = self.open_debugger_with_optional_confirmation(
            exception,
            ask_before_open=ask_before_open,
        )
        if not debugger_opened:
            return {
                "ok": False,
                "cancelled": True,
                "error": {"message": "Debugger opening cancelled by user."},
            }
        return {
            "ok": True,
            "debugger_opened": True,
        }

    def add_debugger_tab(self, exception):
        self.debugger_tab = DebuggerWindow(
            self.notebook,
            self,
            self.gemstone_session_record,
            self.event_queue,
            exception,
        )
        self.debugger_tab.global_navigation_session_key = (
            self.allocate_global_navigation_session_key('debugger')
        )
        self.notebook.add(self.debugger_tab, text="Debugger")

    def select_debugger_tab(self):
        self.notebook.select(self.debugger_tab)
        # if self.debugger_tab:
        #     self.notebook.select(self.debugger_tab)
        #     self.debugger_tab.top_frame.lift()
        #     self.debugger_tab.forget(self.debugger_tab.top_frame)
        #     self.debugger_tab.add(self.debugger_tab.top_frame)
        #     self.debugger_tab.event_generate('<Configure>')
        #     self.debugger_tab.update()

    def handle_find_selection(self, show_instance_side, class_name):
        self.gemstone_session_record.jump_to_class(class_name, show_instance_side)
        self.event_queue.publish("SelectedClassChanged")

    def handle_implementor_selection(
        self, method_symbol, class_name, show_instance_side
    ):
        self.gemstone_session_record.jump_to_method(
            class_name, show_instance_side, method_symbol
        )
        self.event_queue.publish("SelectedClassChanged")
        self.event_queue.publish("SelectedCategoryChanged")
        self.event_queue.publish("MethodSelected")

    def handle_sender_selection(self, class_name, show_instance_side, method_symbol):
        self.gemstone_session_record.jump_to_method(
            class_name,
            show_instance_side,
            method_symbol,
        )
        self.event_queue.publish("SelectedClassChanged")
        self.event_queue.publish("SelectedCategoryChanged")
        self.event_queue.publish("MethodSelected")

    def open_run_tab(self):
        self.ensure_current_browser_place_in_global_history()
        if self.run_tab is None or not self.run_tab.winfo_exists():
            self.run_tab = RunTab(self.notebook, self)
            self.run_tab.global_navigation_session_key = (
                self.allocate_global_navigation_session_key('run')
            )
            self.notebook.add(self.run_tab, text='Run')
        self.run_tab.set_read_only(self.integrated_session_state.is_mcp_busy())
        self.notebook.select(self.run_tab)

    def run_code(self, source=''):
        self.open_run_tab()
        run_immediately = bool(source and source.strip())
        self.run_tab.present_source(source, run_immediately=run_immediately)

    def open_inspector_for_object(self, inspected_object):
        self.ensure_current_browser_place_in_global_history()
        self.close_inspector_tab()
        self.inspector_tab = InspectorTab(
            self.notebook,
            self,
            an_object=inspected_object,
            graph_inspect_action=self.open_object_diagram_for_object,
        )
        self.inspector_tab.global_navigation_session_key = (
            self.allocate_global_navigation_session_key('inspect')
        )
        self.notebook.add(self.inspector_tab, text="Inspect")
        self.notebook.select(self.inspector_tab)

    def open_object_diagram_for_object(self, inspected_object):
        self.ensure_current_browser_place_in_global_history()
        tab_is_missing = self.object_diagram_tab is None or not self.object_diagram_tab.winfo_exists()
        if tab_is_missing:
            self.object_diagram_tab = UmlObjectDiagramTab(self.notebook, self)
            self.object_diagram_tab.global_navigation_session_key = (
                self.allocate_global_navigation_session_key('object_diagram')
            )
            self.notebook.add(self.object_diagram_tab, text="Object Diagram")
        self.notebook.select(self.object_diagram_tab)
        self.object_diagram_tab.add_object(inspected_object)

    def browse_object_class(self, inspected_object):
        if inspected_object is None:
            return
        class_name = ""
        show_instance_side = True
        try:
            is_behavior = inspected_object.isBehavior().to_py
            if is_behavior:
                class_name = inspected_object.asString().to_py
                show_instance_side = False
            if not is_behavior:
                class_name = inspected_object.gemstone_class().asString().to_py
        except (GemstoneError, AttributeError):
            class_name = ""
        class_name = " ".join(class_name.split()) if isinstance(class_name, str) else ""
        if not class_name:
            return
        if self.browser_tab is not None and self.browser_tab.winfo_exists():
            self.notebook.select(self.browser_tab)
        self.gemstone_session_record.jump_to_class(class_name, show_instance_side)
        self.event_queue.publish("SelectedClassChanged")

    def add_method_for_class(self, class_name, show_instance_side=True):
        if not class_name:
            return None
        if self.browser_tab is not None and self.browser_tab.winfo_exists():
            self.notebook.select(self.browser_tab)
        self.gemstone_session_record.jump_to_class(class_name, show_instance_side)
        self.event_queue.publish("SelectedClassChanged")
        return self.browser_tab.methods_widget.add_method()

    def open_class_diagram_for_class(self, class_name):
        if not class_name:
            return
        self.ensure_current_browser_place_in_global_history()
        self.ensure_class_diagram_tab()
        self.class_diagram_tab.add_class(class_name)

    def pin_method_in_class_diagram(self, class_name, show_instance_side, method_selector):
        if not class_name or not method_selector:
            return
        self.ensure_class_diagram_tab()
        self.class_diagram_tab.pin_method(
            class_name,
            show_instance_side,
            method_selector,
        )

    def ensure_class_diagram_tab(self):
        tab_is_missing = self.class_diagram_tab is None or not self.class_diagram_tab.winfo_exists()
        if tab_is_missing:
            self.class_diagram_tab = UmlClassDiagramTab(self.notebook, self)
            self.class_diagram_tab.global_navigation_session_key = (
                self.allocate_global_navigation_session_key('class_diagram')
            )
            self.notebook.add(self.class_diagram_tab, text="Class Diagram")
        self.notebook.select(self.class_diagram_tab)
        return self.class_diagram_tab

    def class_diagram_state_for_mcp(self):
        tab_is_open = self.class_diagram_tab is not None and self.class_diagram_tab.winfo_exists()
        if not tab_is_open:
            return {
                'is_open': False,
                'is_selected': False,
                'diagram': {
                    'nodes': [],
                    'relationships': [],
                },
            }
        selected_tab_id = None
        if self.notebook is not None and self.notebook.winfo_exists():
            try:
                selected_tab_id = self.notebook.select()
            except tk.TclError:
                selected_tab_id = None
        return {
            'is_open': True,
            'is_selected': selected_tab_id == str(self.class_diagram_tab),
            'diagram': self.class_diagram_tab.snapshot_diagram(),
        }

    def close_inspector_tab(self):
        has_open_tab = (
            self.inspector_tab is not None and self.inspector_tab.winfo_exists()
        )
        if not has_open_tab:
            self.inspector_tab = None
            return
        inspector_session_key = getattr(
            self.inspector_tab,
            'global_navigation_session_key',
            None,
        )
        if inspector_session_key:
            self.mark_global_navigation_place_stale(
                ('inspector_session', inspector_session_key),
            )
        try:
            self.notebook.forget(self.inspector_tab)
        except tk.TclError:
            pass
        self.inspector_tab.destroy()
        self.inspector_tab = None

    def close_object_diagram_tab(self):
        tab_exists = self.object_diagram_tab is not None and self.object_diagram_tab.winfo_exists()
        if not tab_exists:
            self.object_diagram_tab = None
            return
        object_diagram_session_key = getattr(
            self.object_diagram_tab,
            'global_navigation_session_key',
            None,
        )
        if object_diagram_session_key:
            self.mark_global_navigation_place_stale(
                ('object_diagram_session', object_diagram_session_key),
            )
        try:
            self.notebook.forget(self.object_diagram_tab)
        except tk.TclError:
            pass
        self.object_diagram_tab.destroy()
        self.object_diagram_tab = None

    def close_class_diagram_tab(self):
        tab_exists = self.class_diagram_tab is not None and self.class_diagram_tab.winfo_exists()
        if not tab_exists:
            self.class_diagram_tab = None
            return
        class_diagram_session_key = getattr(
            self.class_diagram_tab,
            'global_navigation_session_key',
            None,
        )
        if class_diagram_session_key:
            self.mark_global_navigation_place_stale(
                ('class_diagram_session', class_diagram_session_key),
            )
        try:
            self.notebook.forget(self.class_diagram_tab)
        except tk.TclError:
            pass
        self.class_diagram_tab.destroy()
        self.class_diagram_tab = None

    def open_find_dialog(
        self,
        search_type='class',
        search_query='',
        run_search=False,
        match_mode=None,
        reference_target=None,
        sender_source_class_name=None,
    ):
        return FindDialog(
            self,
            search_type=search_type,
            search_query=search_query,
            run_search=run_search,
            match_mode=match_mode,
            reference_target=reference_target,
            sender_source_class_name=sender_source_class_name,
        )

    def open_find_dialog_for_class(self, class_name):
        selected_class_name = (class_name or "").strip()
        if not selected_class_name:
            return None
        return self.open_find_dialog(
            search_type="reference",
            search_query=selected_class_name,
            run_search=True,
            match_mode="exact",
            reference_target="class",
        )

    def open_implementors_dialog(self, method_symbol=None):
        initial_selector = (method_symbol or "").strip()
        return self.open_find_dialog(
            search_type="method",
            search_query=initial_selector,
            run_search=bool(initial_selector),
            match_mode="exact",
        )

    def open_senders_dialog(self, method_symbol=None, source_class_name=None):
        initial_selector = (method_symbol or '').strip()
        return self.open_find_dialog(
            search_type='reference',
            search_query=initial_selector,
            run_search=bool(initial_selector),
            match_mode='exact',
            reference_target='method',
            sender_source_class_name=source_class_name,
        )

    def open_breakpoints_dialog(self):
        if self.gemstone_session_record is None:
            return
        BreakpointsDialog(self)


class LoginFrame(ttk.Frame):
    def __init__(self, parent, default_stone_name="gs64stone"):
        super().__init__(parent)
        self.parent = parent
        self.error_label = None

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        self.form_frame = ttk.Frame(self, padding=24)
        self.form_frame.grid(
            row=0,
            column=0,
            sticky="n",
            padx=20,
            pady=20,
        )
        self.form_frame.columnconfigure(0, weight=0)
        self.form_frame.columnconfigure(1, weight=1)

        ttk.Label(
            self.form_frame,
            text="Connect to GemStone",
        ).grid(
            column=0,
            row=0,
            columnspan=2,
            sticky="w",
            pady=(0, 12),
        )

        # Username label and entry
        ttk.Label(self.form_frame, text="Username:").grid(
            column=0,
            row=1,
            sticky="e",
            padx=(0, 8),
            pady=2,
        )
        self.username_entry = ttk.Entry(self.form_frame)
        self.username_entry.insert(0, "DataCurator")
        self.username_entry.grid(column=1, row=1, sticky="ew", pady=2)

        # Password label and entry
        ttk.Label(self.form_frame, text="Password:").grid(
            column=0,
            row=2,
            sticky="e",
            padx=(0, 8),
            pady=2,
        )
        self.password_entry = ttk.Entry(self.form_frame, show="*")
        self.password_entry.insert(0, "swordfish")
        self.password_entry.grid(column=1, row=2, sticky="ew", pady=2)

        ttk.Label(self.form_frame, text="Stone name:").grid(
            column=0,
            row=3,
            sticky="e",
            padx=(0, 8),
            pady=2,
        )
        self.stone_name_entry = ttk.Entry(self.form_frame)
        self.stone_name_entry.insert(0, default_stone_name)
        self.stone_name_entry.grid(column=1, row=3, sticky="ew", pady=2)

        # Remote checkbox
        self.remote_var = tk.BooleanVar()
        self.remote_checkbox = ttk.Checkbutton(
            self.form_frame,
            text="Login RPC?",
            variable=self.remote_var,
            command=self.toggle_remote_widgets,
        )
        self.remote_checkbox.grid(
            column=0,
            row=4,
            columnspan=2,
            sticky="w",
            pady=(8, 2),
        )

        # Remote widgets (initially hidden)
        self.netldi_name_label = ttk.Label(self.form_frame, text="Netldi name:")
        self.netldi_name_entry = ttk.Entry(self.form_frame)
        self.netldi_name_entry.insert(0, "gs64-ldi")

        self.rpc_hostname_label = ttk.Label(self.form_frame, text="RPC host name:")
        self.rpc_hostname_entry = ttk.Entry(self.form_frame)
        self.rpc_hostname_entry.insert(0, "localhost")

        # Login button
        ttk.Button(self.form_frame, text="Login", command=self.attempt_login).grid(
            column=1,
            row=8,
            sticky="e",
            pady=(10, 0),
        )

    @property
    def login_rpc(self):
        return self.remote_var.get()

    def toggle_remote_widgets(self):
        if self.remote_var.get():
            # Show the remote widgets
            self.netldi_name_label.grid(
                column=0,
                row=5,
                sticky="e",
                padx=(0, 8),
                pady=2,
            )
            self.netldi_name_entry.grid(column=1, row=5, sticky="ew", pady=2)
            self.rpc_hostname_label.grid(
                column=0,
                row=6,
                sticky="e",
                padx=(0, 8),
                pady=2,
            )
            self.rpc_hostname_entry.grid(column=1, row=6, sticky="ew", pady=2)
        else:
            # Hide the remote widgets
            self.netldi_name_label.grid_remove()
            self.netldi_name_entry.grid_remove()
            self.rpc_hostname_label.grid_remove()
            self.rpc_hostname_entry.grid_remove()

    def attempt_login(self):
        if self.error_label:
            self.error_label.destroy()

        username = self.username_entry.get()
        password = self.password_entry.get()
        stone_name = self.stone_name_entry.get()
        netldi_name = self.netldi_name_entry.get()
        rpc_hostname = self.rpc_hostname_entry.get()
        try:
            if self.login_rpc:
                gemstone_session_record = GemstoneSessionRecord.log_in_rpc(
                    username, password, rpc_hostname, stone_name, netldi_name
                )
            else:
                gemstone_session_record = GemstoneSessionRecord.log_in_linked(
                    username, password, stone_name
                )
            self.parent.event_queue.publish(
                "LoggedInSuccessfully", gemstone_session_record
            )
        except DomainException as ex:
            self.error_label = ttk.Label(
                self.form_frame,
                text=str(ex),
                foreground="red",
            )
            self.error_label.grid(
                column=0,
                row=7,
                columnspan=2,
                sticky="w",
                pady=(8, 0),
            )


if __name__ == "__main__":
    Swordfish.run()
