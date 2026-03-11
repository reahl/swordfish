import queue
import re
import threading
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
from tkinter import ttk

from reahl.ptongue import GemstoneError

from reahl.swordfish.exceptions import DomainException
from reahl.swordfish.gemstone.session import DomainException as GemstoneDomainException
from reahl.swordfish.navigation import NavigationHistory
from reahl.swordfish.selection_list import InteractiveSelectionList
from reahl.swordfish.tab_registry import DeduplicatedTabRegistry
from reahl.swordfish.text_editing import (
    CodeLineNumberColumn,
    EditorTab,
    TextCursorPositionIndicator,
)
from reahl.swordfish.ui_context import UiContext
from reahl.swordfish.ui_support import add_close_command_to_popup_menu, popup_menu


class CoveringTestsDiscoveryWorkflow:
    def __init__(
        self,
        gemstone_session_record,
        method_name,
        max_elapsed_ms,
        merge_sender_test_plan,
    ):
        self.gemstone_session_record = gemstone_session_record
        self.method_name = method_name
        self.max_elapsed_ms = max_elapsed_ms
        self.merge_sender_test_plan = merge_sender_test_plan
        self.should_stop = threading.Event()
        self.pending_candidate_tests = queue.Queue()
        self.accumulated_plan = None
        self.search_state = {
            'is_searching': False,
            'latest_result': None,
            'latest_error': None,
            'attempt_processed': False,
            'cancel_requested': False,
            'use_results_requested_for_attempt': False,
            'search_started': False,
        }

    def record_discovered_test(self, candidate_test):
        self.pending_candidate_tests.put(dict(candidate_test))

    def run_search_attempt(self):
        self.search_state['is_searching'] = True
        self.search_state['latest_result'] = None
        self.search_state['latest_error'] = None
        self.search_state['attempt_processed'] = False
        self.search_state['cancel_requested'] = False
        self.search_state['use_results_requested_for_attempt'] = False
        self.search_state['search_started'] = True
        self.should_stop.clear()

        def discover_tests():
            try:
                self.search_state['latest_result'] = (
                    self.gemstone_session_record.plan_sender_evidence_tests(
                        self.method_name,
                        max_depth=2,
                        max_nodes=500,
                        max_senders_per_selector=200,
                        max_test_methods=200,
                        max_elapsed_ms=self.max_elapsed_ms,
                        should_stop=self.should_stop.is_set,
                        on_candidate_test=self.record_discovered_test,
                    )
                )
            except (GemstoneDomainException, GemstoneError) as error:
                self.search_state['latest_error'] = error
            finally:
                self.search_state['is_searching'] = False

        search_thread = threading.Thread(
            target=discover_tests,
            daemon=True,
        )
        search_thread.start()

    def flush_discovered_tests(self, on_candidate_test):
        keep_flushing = True
        while keep_flushing:
            discovered_test = None
            try:
                discovered_test = self.pending_candidate_tests.get_nowait()
            except queue.Empty:
                keep_flushing = False
            if discovered_test is not None:
                on_candidate_test(discovered_test)

    def request_cancel(self):
        self.search_state['cancel_requested'] = True
        self.should_stop.set()

    def request_use_results(self):
        self.search_state['use_results_requested_for_attempt'] = True
        self.should_stop.set()

    def searching(self):
        return self.search_state['is_searching']

    def latest_error(self):
        return self.search_state['latest_error']

    def cancelled(self):
        return self.search_state['cancel_requested']

    def advance(self, stop_requested, use_results_requested, on_candidate_test):
        self.flush_discovered_tests(on_candidate_test)
        if stop_requested:
            self.request_cancel()
        if use_results_requested:
            self.request_use_results()

        if self.search_state['is_searching']:
            return {'phase': 'searching'}
        if not self.search_state['search_started']:
            return {'phase': 'idle'}
        if self.search_state['attempt_processed']:
            return {'phase': 'idle'}
        self.search_state['attempt_processed'] = True

        if self.search_state['cancel_requested']:
            return {'phase': 'cancelled'}
        if self.search_state['latest_error'] is not None:
            return {
                'phase': 'error',
                'error': self.search_state['latest_error'],
            }
        if self.search_state['latest_result'] is None:
            return {'phase': 'empty'}

        self.accumulated_plan = self.merge_sender_test_plan(
            self.accumulated_plan,
            self.search_state['latest_result'],
        )
        result_stopped_by_user = self.search_state['latest_result'].get(
            'stopped_by_user',
            False,
        )
        used_results_requested = self.search_state['use_results_requested_for_attempt']
        if result_stopped_by_user and not used_results_requested:
            return {'phase': 'cancelled'}
        return {
            'phase': 'ready',
            'plan': self.accumulated_plan,
            'timed_out': self.search_state['latest_result'].get(
                'elapsed_limit_reached',
                False,
            ),
            'used_results': used_results_requested,
        }


class CoveringTestsBrowseDialog(tk.Toplevel):
    def __init__(self, browser_window, method_name, max_elapsed_ms=120000):
        super().__init__(browser_window)
        self.title('Covering Tests')
        self.geometry('760x520')
        self.transient(browser_window)
        self.wait_visibility()
        self.grab_set()

        self.browser_window = browser_window
        self.method_name = method_name
        self.max_elapsed_ms = max_elapsed_ms
        self.candidate_tests_by_key = {}
        self.candidate_test_keys_in_order = []
        self.candidate_test_index_by_key = {}
        self.visited_selector_count = 0
        self.summary_message = ''
        self.discovery_workflow = CoveringTestsDiscoveryWorkflow(
            browser_window.gemstone_session_record,
            method_name,
            max_elapsed_ms,
            self.merged_sender_test_plan,
        )
        self.is_searching = False
        self.is_timed_out = False
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.summary_label = ttk.Label(
            self,
            text='',
            justify='left',
        )
        self.summary_label.grid(
            row=0,
            column=0,
            columnspan=2,
            padx=10,
            pady=(10, 6),
            sticky='w',
        )

        self.progress_bar = ttk.Progressbar(
            self,
            mode='indeterminate',
            length=360,
        )
        self.progress_bar.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky='ew',
            padx=10,
            pady=(0, 6),
        )

        self.results_listbox = tk.Listbox(self)
        self.results_listbox.bind('<Double-Button-1>', self.on_result_double_click)
        self.results_listbox.grid(
            row=2,
            column=0,
            sticky='nsew',
            padx=(10, 0),
            pady=(0, 8),
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient='vertical',
            command=self.results_listbox.yview,
        )
        self.scrollbar.grid(
            row=2,
            column=1,
            sticky='ns',
            padx=(0, 10),
            pady=(0, 8),
        )
        self.results_listbox.configure(yscrollcommand=self.scrollbar.set)

        self.buttons = ttk.Frame(self)
        self.buttons.grid(row=3, column=0, columnspan=2, sticky='e', pady=(0, 10))
        self.use_results_button = ttk.Button(
            self.buttons,
            text='Use Results So Far',
            command=self.request_use_results,
        )
        self.use_results_button.grid(row=0, column=0, padx=(0, 4))
        self.stop_search_button = ttk.Button(
            self.buttons,
            text='Stop Searching For Tests',
            command=self.request_stop_search,
        )
        self.stop_search_button.grid(row=0, column=1, padx=(0, 4))
        self.search_further_button = ttk.Button(
            self.buttons,
            text='Search Further',
            command=self.request_search_further,
        )
        self.search_further_button.grid(row=0, column=2, padx=(0, 4))
        self.close_button = ttk.Button(
            self.buttons,
            text='Close',
            command=self.close_dialog,
        )
        self.close_button.grid(row=0, column=3)
        self.protocol('WM_DELETE_WINDOW', self.close_dialog)

        self.run_search_attempt()
        self.after(50, self.monitor_search)

    def candidate_test_key(self, candidate_test):
        return (
            candidate_test['test_case_class_name'],
            candidate_test['test_method_selector'],
        )

    def merged_sender_test_plan(self, current_plan, new_plan):
        if current_plan is None:
            merged_plan = dict(new_plan)
            merged_plan['candidate_tests'] = list(new_plan.get('candidate_tests', []))
            merged_plan['sender_edges'] = list(new_plan.get('sender_edges', []))
            merged_plan['candidate_test_count'] = len(merged_plan['candidate_tests'])
            merged_plan['sender_edge_count'] = len(merged_plan['sender_edges'])
            return merged_plan

        merged_plan = dict(current_plan)
        candidate_tests_by_key = {}
        for candidate_test in current_plan.get('candidate_tests', []):
            candidate_tests_by_key[self.candidate_test_key(candidate_test)] = dict(
                candidate_test
            )
        for candidate_test in new_plan.get('candidate_tests', []):
            current_candidate_test_key = self.candidate_test_key(candidate_test)
            if current_candidate_test_key in candidate_tests_by_key:
                existing_candidate_test = candidate_tests_by_key[
                    current_candidate_test_key
                ]
                if candidate_test.get('depth', 0) < existing_candidate_test.get(
                    'depth',
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
                candidate_test.get('depth', 0),
                candidate_test['test_case_class_name'],
                candidate_test['test_method_selector'],
            ),
        )

        sender_edges_by_key = {}
        for sender_edge in current_plan.get('sender_edges', []) + new_plan.get(
            'sender_edges', []
        ):
            sender_edge_key = (
                sender_edge['from_selector'],
                sender_edge['to_class_name'],
                sender_edge['to_method_selector'],
                sender_edge['to_show_instance_side'],
                sender_edge['depth'],
            )
            sender_edges_by_key[sender_edge_key] = dict(sender_edge)
        merged_sender_edges = list(sender_edges_by_key.values())

        merged_plan['candidate_tests'] = merged_candidate_tests
        merged_plan['candidate_test_count'] = len(merged_candidate_tests)
        merged_plan['sender_edges'] = merged_sender_edges
        merged_plan['sender_edge_count'] = len(merged_sender_edges)
        merged_plan['visited_selector_count'] = max(
            current_plan.get('visited_selector_count', 0),
            new_plan.get('visited_selector_count', 0),
        )
        merged_plan['sender_search_truncated'] = current_plan.get(
            'sender_search_truncated', False
        ) or new_plan.get('sender_search_truncated', False)
        merged_plan['selector_limit_reached'] = current_plan.get(
            'selector_limit_reached', False
        ) or new_plan.get('selector_limit_reached', False)
        merged_plan['elapsed_limit_reached'] = new_plan.get(
            'elapsed_limit_reached',
            False,
        )
        merged_plan['elapsed_ms'] = current_plan.get('elapsed_ms', 0) + new_plan.get(
            'elapsed_ms',
            0,
        )
        merged_plan['max_elapsed_ms'] = self.max_elapsed_ms
        merged_plan['stopped_by_user'] = new_plan.get('stopped_by_user', False)
        return merged_plan

    def format_test_label(self, candidate_test):
        return '%s>>%s (depth %s via %s)' % (
            candidate_test['test_case_class_name'],
            candidate_test['test_method_selector'],
            candidate_test.get('depth', '?'),
            candidate_test.get('reached_from_selector', '?'),
        )

    def summary_text(self):
        candidate_count = len(self.candidate_test_keys_in_order)
        if self.is_searching:
            return (
                'Searching for covering tests for %s... '
                'Found: %s, explored selectors: %s.'
            ) % (
                self.method_name,
                candidate_count,
                self.visited_selector_count,
            )
        if self.is_timed_out:
            return (
                'Search reached %ss timeout. Found: %s, explored selectors: %s.'
            ) % (
                int(self.max_elapsed_ms / 1000),
                candidate_count,
                self.visited_selector_count,
            )
        return ('Covering tests for %s: %s (explored selectors: %s).') % (
            self.method_name,
            candidate_count,
            self.visited_selector_count,
        )

    def refresh_summary(self):
        summary_text = self.summary_text()
        if self.summary_message:
            summary_text = '%s %s' % (summary_text, self.summary_message)
        self.summary_label.configure(text=summary_text)

    def update_button_states(self):
        use_results_state = tk.NORMAL if self.is_searching else tk.DISABLED
        stop_search_state = tk.NORMAL if self.is_searching else tk.DISABLED
        search_further_state = (
            tk.NORMAL if self.is_timed_out and not self.is_searching else tk.DISABLED
        )
        self.use_results_button.configure(state=use_results_state)
        self.stop_search_button.configure(state=stop_search_state)
        self.search_further_button.configure(state=search_further_state)
        self.results_listbox.configure(state=tk.NORMAL)

    def add_or_update_candidate_test(self, candidate_test):
        candidate_key = self.candidate_test_key(candidate_test)
        has_candidate = candidate_key in self.candidate_tests_by_key
        if has_candidate:
            existing_candidate = self.candidate_tests_by_key[candidate_key]
            candidate_depth = candidate_test.get('depth', 0)
            existing_depth = existing_candidate.get('depth', 0)
            if candidate_depth < existing_depth:
                self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
                candidate_index = self.candidate_test_index_by_key[candidate_key]
                self.results_listbox.delete(candidate_index)
                self.results_listbox.insert(
                    candidate_index,
                    self.format_test_label(candidate_test),
                )
        if not has_candidate:
            candidate_index = len(self.candidate_test_keys_in_order)
            self.candidate_tests_by_key[candidate_key] = dict(candidate_test)
            self.candidate_test_keys_in_order.append(candidate_key)
            self.candidate_test_index_by_key[candidate_key] = candidate_index
            self.results_listbox.insert(
                tk.END,
                self.format_test_label(candidate_test),
            )
        self.refresh_summary()

    def run_search_attempt(self):
        self.is_searching = True
        self.is_timed_out = False
        self.stop_search_requested = False
        self.use_results_requested = False
        self.search_further_requested = False
        self.summary_message = ''
        self.progress_bar.start(10)
        self.update_button_states()
        self.refresh_summary()
        self.discovery_workflow.run_search_attempt()

    def set_ready_state(self, timed_out=False, summary_message=''):
        self.is_searching = False
        self.is_timed_out = timed_out
        self.summary_message = summary_message
        self.progress_bar.stop()
        self.update_button_states()
        self.refresh_summary()

    def add_candidate_tests(self, candidate_tests):
        for candidate_test in candidate_tests:
            self.add_or_update_candidate_test(candidate_test)

    def monitor_search(self):
        if not self.winfo_exists():
            return
        if self.stop_search_requested and self.discovery_workflow.searching():
            self.summary_message = 'Stopping search and closing...'
            self.refresh_summary()
        if self.use_results_requested and self.discovery_workflow.searching():
            self.summary_message = 'Stopping search to use the current results...'
            self.refresh_summary()

        search_outcome = self.discovery_workflow.advance(
            self.stop_search_requested,
            self.use_results_requested,
            self.add_or_update_candidate_test,
        )

        if search_outcome['phase'] == 'searching':
            self.after(50, self.monitor_search)
            return
        if search_outcome['phase'] == 'cancelled':
            self.destroy()
            return
        if search_outcome['phase'] == 'error':
            messagebox.showerror(
                'Covering Tests',
                str(search_outcome['error']),
                parent=self,
            )
            self.set_ready_state(
                timed_out=False,
                summary_message='Search failed.',
            )
        if search_outcome['phase'] == 'empty':
            self.set_ready_state(
                timed_out=False,
                summary_message='Search finished without results.',
            )
        if search_outcome['phase'] == 'ready':
            accumulated_plan = search_outcome['plan']
            self.visited_selector_count = max(
                self.visited_selector_count,
                accumulated_plan.get('visited_selector_count', 0),
            )
            self.add_candidate_tests(accumulated_plan.get('candidate_tests', []))
            summary_message = ''
            if search_outcome['used_results']:
                summary_message = 'Using the results found so far.'
            if search_outcome['timed_out']:
                summary_message = (
                    'Search timed out. You can continue with Search Further.'
                )
            self.set_ready_state(
                timed_out=search_outcome['timed_out'],
                summary_message=summary_message,
            )

        if self.winfo_exists():
            if self.search_further_requested:
                self.search_further_requested = False
                self.run_search_attempt()
            self.after(50, self.monitor_search)

    def request_use_results(self):
        if self.is_searching:
            self.use_results_requested = True

    def request_stop_search(self):
        if self.is_searching:
            self.stop_search_requested = True
        if not self.is_searching:
            self.destroy()

    def request_search_further(self):
        if not self.is_searching and self.is_timed_out:
            self.search_further_requested = True
            self.summary_message = ''
            self.refresh_summary()

    def close_dialog(self):
        if self.is_searching:
            self.stop_search_requested = True
        if not self.is_searching:
            self.destroy()

    def on_result_double_click(self, event):
        if self.is_searching:
            return
        selection = self.results_listbox.curselection()
        if not selection:
            return
        selected_index = selection[0]
        candidate_key = self.candidate_test_keys_in_order[selected_index]
        candidate_test = self.candidate_tests_by_key[candidate_key]
        self.browser_window.application.handle_sender_selection(
            candidate_test['test_case_class_name'],
            True,
            candidate_test['test_method_selector'],
        )


class FramedWidget(ttk.Frame):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(parent, borderwidth=2, relief='sunken')
        self.browser_window = browser_window
        self.event_queue = event_queue
        self.grid(
            row=row, column=column, columnspan=colspan, sticky='nsew', padx=1, pady=1
        )

    @property
    def gemstone_session_record(self):
        return self.browser_window.gemstone_session_record

    def destroy(self):
        super().destroy()
        self.event_queue.clear_subscribers(self)

    def show_test_result(self, result):
        if result['has_passed']:
            messagebox.showinfo('Test Result', f"Passed ({result['run_count']} run)")
        else:
            lines = [
                f"Failures: {result['failure_count']}, Errors: {result['error_count']}"
            ]
            lines.extend(result['failures'])
            lines.extend(result['errors'])
            messagebox.showerror('Test Result', '\n'.join(lines))


class PackageSelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.selection_list = InteractiveSelectionList(
            self,
            self.get_all_groups,
            self.get_selected_group,
            self.select_group,
        )
        self.selection_list.grid(row=0, column=0, sticky='nsew')
        self.browse_mode_var = tk.StringVar(
            value=self.gemstone_session_record.browse_mode
        )
        self.browse_mode_controls = ttk.Frame(self)
        self.browse_mode_controls.grid(
            row=1,
            column=0,
            sticky='ew',
            pady=(4, 0),
        )
        self.browse_mode_controls.columnconfigure(0, weight=1)
        self.browse_mode_controls.columnconfigure(1, weight=1)
        self.browse_mode_controls.columnconfigure(2, weight=1)
        self.dictionaries_radiobutton = tk.Radiobutton(
            self.browse_mode_controls,
            text='Dictionaries',
            variable=self.browse_mode_var,
            value='dictionaries',
            command=self.change_browse_mode,
        )
        self.categories_radiobutton = tk.Radiobutton(
            self.browse_mode_controls,
            text='Categories',
            variable=self.browse_mode_var,
            value='categories',
            command=self.change_browse_mode,
        )
        rowan_state = (
            tk.NORMAL if self.gemstone_session_record.rowan_installed else tk.DISABLED
        )
        self.rowan_radiobutton = tk.Radiobutton(
            self.browse_mode_controls,
            text='Rowan',
            variable=self.browse_mode_var,
            value='rowan',
            command=self.change_browse_mode,
            state=rowan_state,
        )
        self.dictionaries_radiobutton.grid(row=0, column=0, sticky='w')
        self.categories_radiobutton.grid(row=0, column=1, sticky='w')
        self.rowan_radiobutton.grid(row=0, column=2, sticky='e')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.repopulate()

        self.event_queue.subscribe('PackagesChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('BrowseModeChanged', self.handle_browse_mode_changed)

    def change_browse_mode(self):
        selected_mode = self.browse_mode_var.get()
        try:
            self.gemstone_session_record.select_browse_mode(selected_mode)
        except DomainException as error:
            messagebox.showerror('Browse Mode', str(error))
            self.browse_mode_var.set(self.gemstone_session_record.browse_mode)
            return
        self.selection_list.repopulate()
        self.event_queue.publish('BrowseModeChanged', origin=self)
        # AI: Retain legacy event name for compatibility with dependent widgets.
        self.event_queue.publish('SelectedPackageChanged', origin=self)
        self.event_queue.publish('SelectedClassChanged', origin=self)
        self.event_queue.publish('SelectedCategoryChanged', origin=self)
        self.event_queue.publish('MethodSelected', origin=self)

    def handle_browse_mode_changed(self, origin=None):
        if origin is self:
            return
        rowan_state = (
            tk.NORMAL if self.gemstone_session_record.rowan_installed else tk.DISABLED
        )
        self.rowan_radiobutton.config(state=rowan_state)
        if (
            self.gemstone_session_record.browse_mode == 'rowan'
            and not self.gemstone_session_record.rowan_installed
        ):
            self.gemstone_session_record.select_browse_mode('dictionaries')
        self.browse_mode_var.set(self.gemstone_session_record.browse_mode)
        self.selection_list.repopulate()

    def select_group(self, selected_group):
        self.gemstone_session_record.select_class_category(selected_group)
        self.event_queue.publish('SelectedPackageChanged', origin=self)

    def get_all_groups(self):
        return list(self.browser_window.gemstone_session_record.class_categories)

    def get_selected_group(self):
        return self.gemstone_session_record.selected_class_category()

    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()


class ClassSelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.class_content_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.class_content_paned.grid(row=0, column=0, columnspan=2, sticky='nsew')
        self.class_definition_sash_fraction = 0.65

        self.class_selection_frame = ttk.Frame(self.class_content_paned)
        self.class_selection_frame.rowconfigure(0, weight=1)
        self.class_selection_frame.columnconfigure(0, weight=1)
        self.class_content_paned.add(self.class_selection_frame, weight=3)

        self.classes_notebook = ttk.Notebook(self.class_selection_frame)
        self.classes_notebook.grid(row=0, column=0, sticky='nsew')

        self.rowconfigure(0, weight=1, minsize=180)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self.selection_list = InteractiveSelectionList(
            self.classes_notebook,
            self.get_all_classes,
            self.get_selected_class,
            self.select_class,
        )
        self.selection_list.grid(row=0, column=0, sticky='nsew')
        self.classes_notebook.add(self.selection_list, text='List')

        self.hierarchy_frame = ttk.Frame(self.classes_notebook)
        self.hierarchy_frame.grid(row=0, column=0, sticky='nsew')
        self.classes_notebook.add(self.hierarchy_frame, text='Hierarchy')
        self.hierarchy_tree = ttk.Treeview(
            self.hierarchy_frame,
            columns=('class_category',),
            show='tree headings',
        )
        self.hierarchy_tree.grid(row=0, column=0, sticky='nsew')
        self.hierarchy_frame.rowconfigure(0, weight=1)
        self.hierarchy_frame.columnconfigure(0, weight=1)
        self.hierarchy_tree.heading('#0', text='Class')
        self.hierarchy_tree.heading('class_category', text='Class Category')
        self.hierarchy_tree.column('#0', width=260, anchor='w')
        self.hierarchy_tree.column('class_category', width=180, anchor='w')
        self.hierarchy_item_by_class_name = {}
        self.synchronizing_hierarchy_selection = False
        self.hierarchy_tree.bind('<<TreeviewSelect>>', self.repopulate_categories)
        self.hierarchy_tree.bind('<Button-3>', self.show_hierarchy_context_menu)
        self.classes_notebook.bind(
            '<<NotebookTabChanged>>',
            self.handle_classes_notebook_changed,
        )

        self.selection_var = tk.StringVar(
            value=(
                'instance'
                if self.gemstone_session_record.show_instance_side
                else 'class'
            )
        )
        self.syncing_side_selection = False
        self.selection_var.trace_add(
            'write', lambda name, index, operation: self.switch_side()
        )
        self.class_controls_frame = ttk.Frame(self)
        self.class_controls_frame.grid(
            column=0,
            row=1,
            columnspan=2,
            sticky='ew',
            pady=(4, 0),
        )
        self.class_controls_frame.columnconfigure(0, weight=0)
        self.class_controls_frame.columnconfigure(1, weight=0)
        self.class_controls_frame.columnconfigure(2, weight=1)
        self.class_radiobutton = tk.Radiobutton(
            self.class_controls_frame,
            text='Class',
            variable=self.selection_var,
            value='class',
        )
        self.instance_radiobutton = tk.Radiobutton(
            self.class_controls_frame,
            text='Instance',
            variable=self.selection_var,
            value='instance',
        )
        self.instance_radiobutton.grid(column=0, row=0, sticky='w')
        self.class_radiobutton.grid(column=1, row=0, sticky='w')
        self.show_class_definition_var = tk.BooleanVar(value=False)
        self.show_class_definition_checkbox = tk.Checkbutton(
            self.class_controls_frame,
            text='Definition',
            variable=self.show_class_definition_var,
            command=self.toggle_class_definition,
        )
        self.show_class_definition_checkbox.grid(
            column=2,
            row=0,
            sticky='e',
        )
        self.class_definition_frame = ttk.Frame(self.class_content_paned)
        self.class_definition_frame.rowconfigure(0, weight=1)
        self.class_definition_frame.columnconfigure(1, weight=1)
        self.class_definition_text = tk.Text(
            self.class_definition_frame,
            wrap='word',
            width=1,
            height=8,
        )
        self.class_definition_line_number_column = CodeLineNumberColumn(
            self.class_definition_frame,
            self.class_definition_text,
        )
        self.class_definition_line_number_column.line_numbers_text.grid(
            column=0,
            row=0,
            sticky='ns',
        )
        self.class_definition_text.grid(
            column=1,
            row=0,
            sticky='nsew',
        )
        self.class_definition_cursor_position_label = ttk.Label(
            self.class_definition_frame,
            text='Ln 1, Col 1',
        )
        self.class_definition_cursor_position_label.grid(
            column=1,
            row=1,
            sticky='e',
            pady=(2, 0),
        )
        self.class_definition_cursor_position_indicator = TextCursorPositionIndicator(
            self.class_definition_text,
            self.class_definition_cursor_position_label,
        )
        self.class_definition_text.config(state='disabled')

        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('PackagesChanged', self.repopulate)
        self.event_queue.subscribe('ClassesChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)

        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)
        self.current_context_menu = None
        self.context_menu_class_name = None

    def switch_side(self):
        if self.syncing_side_selection:
            return
        self.gemstone_session_record.select_instance_side(self.show_instance_side)
        self.event_queue.publish('SelectedClassChanged')

    @property
    def show_instance_side(self):
        return self.selection_var.get() == 'instance'

    def repopulate_categories(self, event):
        widget = event.widget
        try:
            if isinstance(widget, tk.Listbox):
                selected_index = widget.curselection()[0]
                selected_class = widget.get(selected_index)
                self.select_class(
                    selected_class,
                    selection_source='list',
                )
                return
            if isinstance(widget, ttk.Treeview):
                if self.synchronizing_hierarchy_selection:
                    return
                selected_item_id = widget.selection()[0]
                selected_class = widget.item(selected_item_id, 'text')
                class_values = widget.item(selected_item_id, 'values')
                class_category = class_values[0] if class_values else ''
                current_class = self.gemstone_session_record.selected_class
                current_package = self.gemstone_session_record.selected_package
                selected_package = class_category or current_package
                if (
                    selected_class == current_class
                    and selected_package == current_package
                ):
                    return
                self.select_class(
                    selected_class,
                    selection_source='hierarchy',
                    class_category=class_category,
                )
        except IndexError:
            pass

    def repopulate(self, origin=None):
        if origin is not self:
            expected_side = (
                'instance'
                if self.gemstone_session_record.show_instance_side
                else 'class'
            )
            if self.selection_var.get() != expected_side:
                self.syncing_side_selection = True
                self.selection_var.set(expected_side)
                self.syncing_side_selection = False
            self.selection_list.repopulate()
            if self.selected_tab_is_hierarchy():
                self.refresh_hierarchy_tree()
            self.refresh_class_definition()

    def selected_tab_is_hierarchy(self):
        selected_tab = self.classes_notebook.select()
        return selected_tab == str(self.hierarchy_frame)

    def handle_classes_notebook_changed(self, event):
        if event.widget.select() == str(self.hierarchy_frame):
            self.refresh_hierarchy_tree()

    def refresh_hierarchy_tree(self):
        self.synchronizing_hierarchy_selection = True
        try:
            self.hierarchy_tree.delete(*self.hierarchy_tree.get_children())
            self.hierarchy_item_by_class_name = {}
            class_names = self.get_all_classes()
            if not class_names:
                return
            class_definition_by_class_name = self.class_definition_map_for_classes(
                class_names,
            )
            superclass_by_class_name = {
                class_name: class_definition.get('superclass_name')
                for class_name, class_definition in class_definition_by_class_name.items()
            }
            children_by_parent_name = {}
            for class_name, superclass_name in superclass_by_class_name.items():
                parent_name = superclass_name
                if superclass_name not in superclass_by_class_name:
                    parent_name = None
                if parent_name not in children_by_parent_name:
                    children_by_parent_name[parent_name] = []
                children_by_parent_name[parent_name].append(class_name)
            for child_names in children_by_parent_name.values():
                child_names.sort()
            self.add_hierarchy_children(
                '',
                None,
                children_by_parent_name,
                class_definition_by_class_name,
            )
            self.reveal_selected_class_in_hierarchy()
        finally:
            self.synchronizing_hierarchy_selection = False

    def class_definition_map_for_classes(self, class_names):
        class_definition_by_class_name = {}
        classes_to_query = list(class_names)
        while classes_to_query:
            class_name = classes_to_query.pop()
            if class_name not in class_definition_by_class_name:
                class_definition = {
                    'class_name': class_name,
                    'superclass_name': None,
                    'package_name': '',
                }
                try:
                    fetched_class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        class_name,
                    )
                    class_definition.update(fetched_class_definition)
                except GemstoneDomainException:
                    pass
                superclass_name = class_definition.get('superclass_name')
                class_definition_by_class_name[class_name] = class_definition
                if (
                    superclass_name is not None
                    and superclass_name not in class_definition_by_class_name
                ):
                    classes_to_query.append(superclass_name)
        return class_definition_by_class_name

    def add_hierarchy_children(
        self,
        parent_item_id,
        parent_class_name,
        children_by_parent_name,
        class_definition_by_class_name,
    ):
        child_class_names = children_by_parent_name.get(parent_class_name, [])
        for child_class_name in child_class_names:
            class_definition = class_definition_by_class_name.get(
                child_class_name,
                {},
            )
            class_category = class_definition.get('package_name') or ''
            child_item_id = self.hierarchy_tree.insert(
                parent_item_id,
                'end',
                text=child_class_name,
                values=(class_category,),
            )
            self.hierarchy_item_by_class_name[child_class_name] = child_item_id
            self.add_hierarchy_children(
                child_item_id,
                child_class_name,
                children_by_parent_name,
                class_definition_by_class_name,
            )

    def reveal_selected_class_in_hierarchy(self):
        selected_class_name = self.gemstone_session_record.selected_class
        if not selected_class_name:
            return
        selected_item_id = self.hierarchy_item_by_class_name.get(selected_class_name)
        if selected_item_id is None:
            return
        parent_item_id = self.hierarchy_tree.parent(selected_item_id)
        while parent_item_id:
            self.hierarchy_tree.item(parent_item_id, open=True)
            parent_item_id = self.hierarchy_tree.parent(parent_item_id)
        self.hierarchy_tree.item(selected_item_id, open=True)
        self.hierarchy_tree.selection_set(selected_item_id)
        self.hierarchy_tree.focus(selected_item_id)
        self.hierarchy_tree.see(selected_item_id)

    def get_all_classes(self):
        selected_category = self.gemstone_session_record.selected_class_category()
        return list(
            self.browser_window.gemstone_session_record.get_classes_in_category(
                selected_category
            )
        )

    def get_selected_class(self):
        return self.gemstone_session_record.selected_class

    def select_class(
        self,
        selected_class,
        selection_source='list',
        class_category='',
    ):
        selected_package = self.gemstone_session_record.selected_package
        if (
            selection_source == 'hierarchy'
            and self.gemstone_session_record.browse_mode == 'categories'
        ):
            selected_package = class_category
            if not selected_package:
                try:
                    class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                        selected_class,
                    )
                except (GemstoneDomainException, GemstoneError):
                    class_definition = {}
                selected_package = (
                    class_definition.get('package_name') or selected_package
                )
            if selected_package:
                self.gemstone_session_record.select_package(selected_package)
                self.selection_list.repopulate()
        self.gemstone_session_record.select_class(selected_class)
        if selection_source == 'hierarchy':
            self.gemstone_session_record.select_method_category('all')
        self.refresh_class_definition()
        self.event_queue.publish('SelectedClassChanged', origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        selected_class_name = self.class_name_from_list_context_event(event)
        self.context_menu_class_name = selected_class_name
        has_selection = selected_class_name is not None
        if self.current_context_menu:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        read_only = (
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        delete_command_state = write_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label='Add Class',
            command=self.add_class,
            state=write_command_state,
        )
        menu.add_command(
            label='Delete Class',
            command=self.delete_class,
            state=delete_command_state,
        )
        menu.add_command(
            label='References',
            command=self.find_references_for_selected_class,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_command(
            label='Add to Class Diagram',
            command=self.add_selected_class_to_class_diagram,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_command(
            label='Run All Tests',
            command=self.run_all_tests,
            state=run_command_state,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def class_name_from_list_context_event(self, event):
        listbox = self.selection_list.selection_listbox
        if listbox.size() <= 0:
            return None
        selected_index = listbox.nearest(event.y)
        listbox.selection_clear(0, 'end')
        listbox.selection_set(selected_index)
        return listbox.get(selected_index)

    def class_name_from_hierarchy_context_event(self, event):
        tree = self.hierarchy_tree
        selected_item_id = tree.identify_row(event.y)
        selected_items = tree.selection()
        if selected_item_id:
            clicked_item_is_selected = selected_item_id in selected_items
            if not clicked_item_is_selected:
                tree.selection_set(selected_item_id)
                selected_items = tree.selection()
            tree.focus(selected_item_id)
        if not selected_item_id and selected_items:
            selected_item_id = selected_items[0]
            tree.focus(selected_item_id)
        if not selected_item_id:
            return None
        return tree.item(selected_item_id, 'text')

    def selected_class_names_from_hierarchy(self):
        selected_class_names = []
        for item_id in self.hierarchy_tree.selection():
            class_name = self.hierarchy_tree.item(item_id, 'text')
            if class_name:
                selected_class_names.append(class_name)
        return selected_class_names

    def find_references_for_selected_class(self):
        class_name = self.context_menu_class_name
        if class_name is None:
            class_name = self.gemstone_session_record.selected_class
        if not class_name:
            return
        self.browser_window.application.open_find_dialog_for_class(class_name)

    def add_selected_class_to_class_diagram(self):
        class_name = self.context_menu_class_name
        if class_name is None:
            class_name = self.gemstone_session_record.selected_class
        if not class_name:
            return
        self.browser_window.application.open_class_diagram_for_class(class_name)

    def add_selected_hierarchy_classes_to_class_diagram(self):
        selected_class_names = self.selected_class_names_from_hierarchy()
        if not selected_class_names:
            self.add_selected_class_to_class_diagram()
            return
        for class_name in selected_class_names:
            self.browser_window.application.open_class_diagram_for_class(class_name)

    def show_hierarchy_context_menu(self, event):
        selected_class_name = self.class_name_from_hierarchy_context_event(event)
        self.context_menu_class_name = selected_class_name
        selected_class_names = self.selected_class_names_from_hierarchy()
        has_selection = len(selected_class_names) > 0
        if self.current_context_menu:
            self.current_context_menu.unpost()
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label='References',
            command=self.find_references_for_selected_class,
            state=tk.NORMAL if selected_class_name is not None else tk.DISABLED,
        )
        menu.add_command(
            label='Add to Class Diagram',
            command=self.add_selected_class_to_class_diagram,
            state=tk.NORMAL if selected_class_name is not None else tk.DISABLED,
        )
        menu.add_command(
            label='Add Selected to Class Diagram',
            command=self.add_selected_hierarchy_classes_to_class_diagram,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def add_class(self):
        selected_category = self.gemstone_session_record.selected_class_category()
        if not selected_category:
            category_label = 'dictionary'
            if self.gemstone_session_record.browse_mode == 'categories':
                category_label = 'category'
            if self.gemstone_session_record.browse_mode == 'rowan':
                category_label = 'Rowan package'
            messagebox.showerror(
                'Add Class',
                'Select a %s first.' % category_label,
            )
            return
        class_name = simpledialog.askstring('Add Class', 'Class name:')
        if class_name is None:
            return
        class_name = class_name.strip()
        if not class_name:
            return
        superclass_name = simpledialog.askstring(
            'Add Class',
            'Superclass name:',
            initialvalue='Object',
        )
        if superclass_name is None:
            return
        superclass_name = superclass_name.strip()
        if not superclass_name:
            return
        try:
            self.gemstone_session_record.create_class(
                class_name=class_name,
                superclass_name=superclass_name,
            )
            self.gemstone_session_record.select_class(class_name)
            self.selection_list.repopulate()
            self.refresh_class_definition()
            self.event_queue.publish('SelectedClassChanged', origin=self)
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Class', str(error))

    def delete_class(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = listbox.get(selection[0])
        selected_category = self.gemstone_session_record.selected_class_category()
        selected_category_label = 'dictionary'
        if self.gemstone_session_record.browse_mode == 'categories':
            selected_category_label = 'category'
        if self.gemstone_session_record.browse_mode == 'rowan':
            selected_category_label = 'Rowan package'
        should_delete = messagebox.askyesno(
            'Delete Class',
            ('Delete class %s from %s %s? ' 'This cannot be undone.')
            % (
                class_name,
                selected_category_label,
                selected_category or 'UserGlobals',
            ),
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_class(
                class_name,
            )
            self.selection_list.repopulate()
            self.refresh_class_definition()
            self.event_queue.publish('SelectedClassChanged', origin=self)
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
            self.event_queue.publish('MethodSelected', origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Delete Class', str(error))

    def class_definition_is_visible(self):
        return str(self.class_definition_frame) in self.class_content_paned.panes()

    def remember_class_definition_sash_position(self):
        if not self.class_definition_is_visible():
            return
        paned_height = self.class_content_paned.winfo_height()
        if paned_height <= 0:
            return
        sash_position = self.class_content_paned.sashpos(0)
        sash_fraction = sash_position / paned_height
        self.class_definition_sash_fraction = max(0.2, min(0.8, sash_fraction))

    def restore_class_definition_sash_position(self):
        if not self.class_definition_is_visible():
            return
        paned_height = self.class_content_paned.winfo_height()
        if paned_height <= 0:
            return
        minimum_pane_height = 120
        desired_sash_position = int(paned_height * self.class_definition_sash_fraction)
        maximum_sash_position = paned_height - minimum_pane_height
        if maximum_sash_position < minimum_pane_height:
            desired_sash_position = paned_height // 2
        else:
            desired_sash_position = max(
                minimum_pane_height,
                min(maximum_sash_position, desired_sash_position),
            )
        self.class_content_paned.sashpos(0, desired_sash_position)

    def ensure_class_definition_is_visible(self):
        if not self.class_definition_is_visible():
            return
        self.class_content_paned.update_idletasks()
        self.restore_class_definition_sash_position()
        self.after(20, self.restore_class_definition_sash_position)

    def toggle_class_definition(self):
        if self.show_class_definition_var.get():
            if not self.class_definition_is_visible():
                self.class_content_paned.add(self.class_definition_frame, weight=2)
            self.ensure_class_definition_is_visible()
            self.refresh_class_definition()
            return
        self.class_definition_text.config(state='normal')
        self.class_definition_text.delete('1.0', tk.END)
        self.class_definition_text.config(state='disabled')
        self.remember_class_definition_sash_position()
        if self.class_definition_is_visible():
            self.class_content_paned.forget(self.class_definition_frame)

    def formatted_class_definition(self, class_definition):
        class_name = class_definition.get('class_name') or ''
        superclass_name = class_definition.get('superclass_name') or 'Object'
        package_name = class_definition.get('package_name') or ''
        inst_var_names = class_definition.get('inst_var_names') or []
        class_var_names = class_definition.get('class_var_names') or []
        class_inst_var_names = class_definition.get('class_inst_var_names') or []
        pool_dictionary_names = class_definition.get('pool_dictionary_names') or []
        return (
            f"{superclass_name} subclass: '{class_name}'\n"
            f"    instVarNames: {self.symbol_array_literal(inst_var_names)}\n"
            f"    classVars: {self.symbol_array_literal(class_var_names)}\n"
            f"    classInstVars: {self.symbol_array_literal(class_inst_var_names)}\n"
            f"    poolDictionaries: {self.symbol_array_literal(pool_dictionary_names)}\n"
            f'    inDictionary: {package_name}'
        )

    def symbol_array_literal(self, symbol_names):
        if not symbol_names:
            return '#()'
        return '#(%s)' % ' '.join(symbol_names)

    def refresh_class_definition(self):
        if not self.show_class_definition_var.get():
            return
        class_definition_text = ''
        selected_class = self.gemstone_session_record.selected_class
        if selected_class:
            try:
                class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                    selected_class,
                )
                class_definition_text = self.formatted_class_definition(
                    class_definition,
                )
            except (GemstoneDomainException, GemstoneError):
                class_definition_text = ''
        self.class_definition_text.config(state='normal')
        self.class_definition_text.delete('1.0', tk.END)
        self.class_definition_text.insert('1.0', class_definition_text)
        self.class_definition_text.config(state='disabled')
        self.class_definition_cursor_position_indicator.update_position()

    def run_all_tests(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            'Running tests in %s...' % class_name
        )
        try:
            try:
                result = self.gemstone_session_record.run_gemstone_tests(class_name)
                self.show_test_result(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror('Run All Tests', str(domain_exception))
            except GemstoneError as error:
                self.browser_window.application.open_debugger(error)
        finally:
            self.browser_window.application.end_foreground_activity()


class CategorySelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.selection_list = InteractiveSelectionList(
            self,
            self.get_all_categories,
            self.get_selected_category,
            self.select_category,
        )
        self.selection_list.grid(row=0, column=0, sticky='nsew')

        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('ClassesChanged', self.repopulate)
        self.event_queue.subscribe('MethodsChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

    def repopulate(self, origin=None):
        if origin is self:
            return
        self.selection_list.repopulate()

    def get_all_categories(self):
        if self.gemstone_session_record.selected_class:
            return ['all'] + list(
                self.gemstone_session_record.get_categories_in_class(
                    self.gemstone_session_record.selected_class,
                    self.gemstone_session_record.show_instance_side,
                )
            )
        return []

    def get_selected_category(self):
        return self.gemstone_session_record.selected_method_category

    def select_category(self, selected_category):
        self.gemstone_session_record.select_method_category(selected_category)
        self.event_queue.publish('SelectedCategoryChanged', origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        has_selection = listbox.size() > 0
        if has_selection:
            selected_index = listbox.nearest(event.y)
            listbox.selection_clear(0, 'end')
            listbox.selection_set(selected_index)
        menu = tk.Menu(self, tearoff=0)
        read_only = (
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )
        write_command_state = tk.DISABLED if read_only else tk.NORMAL
        delete_command_state = write_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label='Add Category',
            command=self.add_category,
            state=write_command_state,
        )
        menu.add_command(
            label='Delete Category',
            command=self.delete_category,
            state=delete_command_state,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def add_category(self):
        selected_class = self.gemstone_session_record.selected_class
        if not selected_class:
            messagebox.showerror('Add Category', 'Select a class first.')
            return
        category_name = simpledialog.askstring('Add Category', 'Category name:')
        if category_name is None:
            return
        category_name = category_name.strip()
        if not category_name:
            return
        try:
            self.gemstone_session_record.create_method_category(
                selected_class,
                self.gemstone_session_record.show_instance_side,
                category_name,
            )
            self.gemstone_session_record.select_method_category(category_name)
            self.selection_list.repopulate()
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Category', str(error))

    def delete_category(self):
        selected_class = self.gemstone_session_record.selected_class
        if not selected_class:
            return
        listbox = self.selection_list.selection_listbox
        selected_indices = listbox.curselection()
        if not selected_indices:
            return
        selected_category = listbox.get(selected_indices[0])
        if selected_category == 'all':
            messagebox.showerror(
                'Delete Category', 'The all category cannot be deleted.'
            )
            return
        should_delete = messagebox.askyesno(
            'Delete Category',
            ('Delete category %s from class %s? ' 'This cannot be undone.')
            % (selected_category, selected_class),
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_method_category(
                selected_class,
                self.gemstone_session_record.show_instance_side,
                selected_category,
            )
            remaining_categories = list(
                self.gemstone_session_record.get_categories_in_class(
                    selected_class,
                    self.gemstone_session_record.show_instance_side,
                )
            )
            if remaining_categories:
                self.gemstone_session_record.select_method_category(
                    remaining_categories[0]
                )
            else:
                self.gemstone_session_record.select_method_category(None)
                self.gemstone_session_record.select_method_symbol(None)
            self.selection_list.repopulate()
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Delete Category', str(error))


class MethodSelection(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.method_content_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.method_content_paned.grid(row=0, column=0, sticky='nsew')
        self.method_hierarchy_sash_fraction = 0.65

        self.method_selection_frame = ttk.Frame(self.method_content_paned)
        self.method_selection_frame.rowconfigure(0, weight=1)
        self.method_selection_frame.columnconfigure(0, weight=1)
        self.method_content_paned.add(self.method_selection_frame, weight=3)

        self.selection_list = InteractiveSelectionList(
            self.method_selection_frame,
            self.get_all_methods,
            self.get_selected_method,
            self.select_method,
        )
        self.selection_list.grid(row=0, column=0, sticky='nsew')
        self.controls_frame = ttk.Frame(self)
        self.controls_frame.grid(row=1, column=0, sticky='ew')
        self.controls_frame.columnconfigure(0, weight=1)
        self.show_method_hierarchy_var = tk.BooleanVar(value=False)
        self.show_method_hierarchy_checkbox = tk.Checkbutton(
            self.controls_frame,
            text='Inheritance',
            variable=self.show_method_hierarchy_var,
            command=self.toggle_method_hierarchy,
        )
        self.show_method_hierarchy_checkbox.grid(row=0, column=0, sticky='w')
        self.method_hierarchy_frame = ttk.Frame(self.method_content_paned)
        self.method_hierarchy_frame.rowconfigure(0, weight=1)
        self.method_hierarchy_frame.columnconfigure(0, weight=1)
        self.method_hierarchy_tree = ttk.Treeview(
            self.method_hierarchy_frame,
            show='tree',
        )
        self.method_hierarchy_tree.heading('#0', text='Class')
        self.method_hierarchy_tree.column('#0', width=240, anchor='w')
        self.method_hierarchy_tree.grid(row=0, column=0, sticky='nsew')
        self.method_hierarchy_tree.bind(
            '<<TreeviewSelect>>',
            self.method_hierarchy_selected,
        )
        self.syncing_method_hierarchy_selection = False

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        self.event_queue.subscribe('SelectedPackageChanged', self.repopulate)
        self.event_queue.subscribe('SelectedClassChanged', self.repopulate)
        self.event_queue.subscribe('SelectedCategoryChanged', self.repopulate)
        self.event_queue.subscribe('ClassesChanged', self.repopulate)
        self.event_queue.subscribe('MethodsChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('MethodSelected', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)

        self.selection_list.selection_listbox.bind('<Button-3>', self.show_context_menu)

    def populate_text_editor(self, event):
        selected_listbox = event.widget
        try:
            selected_index = selected_listbox.curselection()[0]
            selected_method = selected_listbox.get(selected_index)

            self.gemstone_session_record.select_method_symbol(selected_method)
            self.selection_changed = False
            self.event_queue.publish('MethodSelected', origin=self)

        except IndexError:
            pass

    def repopulate(self, origin=None):
        if origin is not self:
            self.selection_list.repopulate()
            if self.show_method_hierarchy_var.get():
                self.refresh_method_hierarchy()

    def get_all_methods(self):
        return self.gemstone_session_record.get_current_methods()

    def get_selected_method(self):
        return self.gemstone_session_record.selected_method_symbol

    def select_method(self, selected_method):
        self.gemstone_session_record.select_method_symbol(selected_method)
        if self.show_method_hierarchy_var.get():
            self.refresh_method_hierarchy()
        self.event_queue.publish('MethodSelected', origin=self)

    def new_method_argument_names(self, method_selector):
        selector_tokens = self.keyword_selector_tokens(method_selector)
        if selector_tokens:
            return [f'argument{index + 1}' for index in range(len(selector_tokens))]
        if self.is_binary_selector(method_selector):
            return ['argument1']
        return []

    def keyword_selector_tokens(self, method_selector):
        if ':' not in method_selector:
            return []
        selector_parts = method_selector.split(':')
        if not selector_parts or selector_parts[-1] != '':
            return []
        keyword_tokens = []
        for selector_part in selector_parts[:-1]:
            is_valid_selector_part = re.fullmatch(
                r'[A-Za-z][A-Za-z0-9_]*',
                selector_part,
            )
            if is_valid_selector_part is None:
                return []
            keyword_tokens.append(f'{selector_part}:')
        return keyword_tokens

    def is_binary_selector(self, method_selector):
        if not method_selector:
            return False
        binary_characters = '+-*/\\~<>=@%,|&?!'
        return all(character in binary_characters for character in method_selector)

    def new_method_header(self, method_selector):
        selector_tokens = self.keyword_selector_tokens(method_selector)
        argument_names = self.new_method_argument_names(method_selector)
        if selector_tokens:
            return ' '.join(
                [
                    f'{selector_tokens[token_index]} {argument_names[token_index]}'
                    for token_index in range(len(selector_tokens))
                ]
            )
        if self.is_binary_selector(method_selector):
            return f'{method_selector} {argument_names[0]}'
        return method_selector

    def new_method_source(self, method_selector):
        method_header = self.new_method_header(method_selector)
        return f'{method_header}\n    ^self'

    def add_method(self):
        selected_class = self.gemstone_session_record.selected_class
        if not selected_class:
            messagebox.showerror('Add Method', 'Select a class first.')
            return None
        method_selector = simpledialog.askstring('Add Method', 'Method selector:')
        if method_selector is None:
            return None
        method_selector = method_selector.strip()
        if not method_selector:
            return None
        method_category = 'as yet unclassified'
        show_instance_side = self.gemstone_session_record.show_instance_side
        try:
            method_source = self.new_method_source(method_selector)
            self.gemstone_session_record.create_method(
                selected_class,
                show_instance_side,
                method_source,
                method_category=method_category,
            )
            self.gemstone_session_record.select_method_category(method_category)
            self.gemstone_session_record.select_method_symbol(method_selector)
            if self.show_method_hierarchy_var.get():
                self.refresh_method_hierarchy()
            self.event_queue.publish('SelectedClassChanged', origin=self)
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
            self.event_queue.publish('MethodSelected', origin=self)
            return method_selector
        except (GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Add Method', str(error))
        return None

    def toggle_method_hierarchy(self):
        if self.show_method_hierarchy_var.get():
            if not self.method_hierarchy_is_visible():
                self.method_content_paned.add(self.method_hierarchy_frame, weight=2)
            self.ensure_method_hierarchy_is_visible()
            self.refresh_method_hierarchy()
            return
        self.method_hierarchy_tree.delete(
            *self.method_hierarchy_tree.get_children(),
        )
        self.remember_method_hierarchy_sash_position()
        if self.method_hierarchy_is_visible():
            self.method_content_paned.forget(self.method_hierarchy_frame)

    def method_hierarchy_is_visible(self):
        return str(self.method_hierarchy_frame) in self.method_content_paned.panes()

    def remember_method_hierarchy_sash_position(self):
        if not self.method_hierarchy_is_visible():
            return
        paned_height = self.method_content_paned.winfo_height()
        if paned_height <= 0:
            return
        sash_position = self.method_content_paned.sashpos(0)
        sash_fraction = sash_position / paned_height
        self.method_hierarchy_sash_fraction = max(0.2, min(0.8, sash_fraction))

    def restore_method_hierarchy_sash_position(self):
        if not self.method_hierarchy_is_visible():
            return
        paned_height = self.method_content_paned.winfo_height()
        if paned_height <= 0:
            return
        minimum_pane_height = 120
        desired_sash_position = int(paned_height * self.method_hierarchy_sash_fraction)
        maximum_sash_position = paned_height - minimum_pane_height
        if maximum_sash_position < minimum_pane_height:
            desired_sash_position = paned_height // 2
        else:
            desired_sash_position = max(
                minimum_pane_height,
                min(maximum_sash_position, desired_sash_position),
            )
        self.method_content_paned.sashpos(0, desired_sash_position)

    def ensure_method_hierarchy_is_visible(self):
        if not self.method_hierarchy_is_visible():
            return
        self.method_content_paned.update_idletasks()
        self.restore_method_hierarchy_sash_position()
        self.after(20, self.restore_method_hierarchy_sash_position)

    def refresh_method_hierarchy(self):
        self.method_hierarchy_tree.delete(
            *self.method_hierarchy_tree.get_children(),
        )
        inheritance_entries = self.method_inheritance_entries()
        parent_item_id = ''
        selected_item_id = None
        selected_class = self.gemstone_session_record.selected_class
        for inheritance_entry in inheritance_entries:
            item_id = self.method_hierarchy_tree.insert(
                parent_item_id,
                'end',
                text=inheritance_entry['class_name'],
            )
            if inheritance_entry['class_name'] == selected_class:
                selected_item_id = item_id
            parent_item_id = item_id
        if selected_item_id is None and parent_item_id:
            selected_item_id = parent_item_id
        if selected_item_id:
            self.syncing_method_hierarchy_selection = True
            self.method_hierarchy_tree.selection_set(selected_item_id)
            self.method_hierarchy_tree.focus(selected_item_id)
            self.method_hierarchy_tree.see(selected_item_id)
            self.syncing_method_hierarchy_selection = False

    def method_inheritance_entries(self):
        selected_class = self.gemstone_session_record.selected_class
        method_selector = self.gemstone_session_record.selected_method_symbol
        show_instance_side = self.gemstone_session_record.show_instance_side
        if not selected_class or not method_selector:
            return []
        superclass_chain = self.superclass_chain_for_method_inheritance(
            selected_class,
        )
        inheritance_entries = []
        for class_name in superclass_chain:
            compiled_method = self.gemstone_session_record.get_method(
                class_name,
                show_instance_side,
                method_selector,
            )
            if compiled_method is not None:
                inheritance_entries.append(
                    {
                        'class_name': class_name,
                        'method_selector': method_selector,
                    },
                )
        return inheritance_entries

    def superclass_chain_for_method_inheritance(self, class_name):
        superclass_chain = []
        current_class_name = class_name
        while current_class_name:
            superclass_chain.append(current_class_name)
            try:
                class_definition = self.gemstone_session_record.gemstone_browser_session.get_class_definition(
                    current_class_name,
                )
            except GemstoneDomainException:
                class_definition = {}
            current_class_name = class_definition.get('superclass_name')
        superclass_chain.reverse()
        return superclass_chain

    def method_hierarchy_selected(self, event):
        if self.syncing_method_hierarchy_selection:
            return
        try:
            selected_item_id = event.widget.selection()[0]
        except IndexError:
            return
        selected_class = event.widget.item(selected_item_id, 'text')
        selected_method = self.gemstone_session_record.selected_method_symbol
        if not selected_class or not selected_method:
            return
        show_instance_side = self.gemstone_session_record.show_instance_side
        if self.gemstone_session_record.gemstone_session is not None:
            self.gemstone_session_record.jump_to_method(
                selected_class,
                show_instance_side,
                selected_method,
            )
        else:
            selected_method_category = self.gemstone_session_record.gemstone_browser_session.get_method_category(
                selected_class,
                selected_method,
                show_instance_side,
            )
            self.gemstone_session_record.select_instance_side(show_instance_side)
            self.gemstone_session_record.select_class(selected_class)
            self.gemstone_session_record.select_method_category(
                selected_method_category,
            )
            self.gemstone_session_record.select_method_symbol(selected_method)
        self.event_queue.publish('SelectedClassChanged', origin=self)
        self.event_queue.publish('SelectedCategoryChanged', origin=self)
        self.event_queue.publish('MethodSelected', origin=self)

    def show_context_menu(self, event):
        listbox = self.selection_list.selection_listbox
        has_selection = listbox.size() > 0
        if has_selection:
            idx = listbox.nearest(event.y)
            listbox.selection_clear(0, 'end')
            listbox.selection_set(idx)
        menu = self.current_context_menu = tk.Menu(self, tearoff=0)
        read_only = (
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )
        write_command_state = tk.NORMAL
        run_command_state = tk.NORMAL
        if read_only:
            write_command_state = tk.DISABLED
            run_command_state = tk.DISABLED
        delete_command_state = write_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label='Add Method',
            command=self.add_method,
            state=write_command_state,
        )
        menu.add_command(
            label='Delete Method',
            command=self.delete_method,
            state=delete_command_state,
        )
        menu.add_command(
            label='Show in Class Diagram',
            command=self.show_method_in_class_diagram,
            state=tk.NORMAL if has_selection else tk.DISABLED,
        )
        menu.add_separator()
        menu.add_command(
            label='Run Test',
            command=self.run_test,
            state=run_command_state,
        )
        menu.add_command(
            label='Debug Test',
            command=self.debug_test,
            state=run_command_state,
        )
        covering_tests_state = run_command_state if has_selection else tk.DISABLED
        menu.add_command(
            label='Covering Tests',
            command=self.open_covering_tests,
            state=covering_tests_state,
        )
        add_close_command_to_popup_menu(menu)
        popup_menu(menu, event)

    def show_method_in_class_diagram(self):
        class_name = self.gemstone_session_record.selected_class
        method_selector = self.gemstone_session_record.selected_method_symbol
        if not class_name or not method_selector:
            return
        self.browser_window.application.pin_method_in_class_diagram(
            class_name,
            self.gemstone_session_record.show_instance_side,
            method_selector,
        )

    def delete_method(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        show_instance_side = self.gemstone_session_record.show_instance_side
        method_selector = listbox.get(selection[0])
        should_delete = messagebox.askyesno(
            'Delete Method',
            ('Delete %s>>%s? This cannot be undone.') % (class_name, method_selector),
        )
        if not should_delete:
            return
        try:
            self.gemstone_session_record.delete_method(
                class_name,
                show_instance_side,
                method_selector,
            )
            self.selection_list.repopulate()
            if self.show_method_hierarchy_var.get():
                self.refresh_method_hierarchy()
            self.event_queue.publish('SelectedCategoryChanged', origin=self)
            self.event_queue.publish('MethodSelected', origin=self)
        except (DomainException, GemstoneDomainException, GemstoneError) as error:
            messagebox.showerror('Delete Method', str(error))

    def run_test(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        method_selector = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            'Running test %s>>%s...' % (class_name, method_selector)
        )
        try:
            try:
                result = self.gemstone_session_record.run_test_method(
                    class_name,
                    method_selector,
                )
                self.show_test_result(result)
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror('Run Test', str(domain_exception))
            except GemstoneError as error:
                self.browser_window.application.open_debugger(error)
        finally:
            self.browser_window.application.end_foreground_activity()

    def debug_test(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        class_name = self.gemstone_session_record.selected_class
        method_selector = listbox.get(selection[0])
        self.browser_window.application.begin_foreground_activity(
            'Debugging test %s>>%s...' % (class_name, method_selector)
        )
        try:
            try:
                self.gemstone_session_record.debug_test_method(
                    class_name,
                    method_selector,
                )
            except (DomainException, GemstoneDomainException) as domain_exception:
                messagebox.showerror('Debug Test', str(domain_exception))
            except GemstoneError as error:
                self.browser_window.application.open_debugger(error)
        finally:
            self.browser_window.application.end_foreground_activity()

    def open_covering_tests(self):
        listbox = self.selection_list.selection_listbox
        selection = listbox.curselection()
        if not selection:
            return
        method_selector = listbox.get(selection[0])
        CoveringTestsBrowseDialog(
            self.browser_window,
            method_selector,
        )


class MethodEditor(FramedWidget):
    def __init__(self, parent, browser_window, event_queue, row, column, colspan=1):
        super().__init__(
            parent, browser_window, event_queue, row, column, colspan=colspan
        )

        self.current_menu = None
        self.method_navigation_history = NavigationHistory()
        self.history_choice_indices = []
        self.ui_context = UiContext('method-editor')

        self.navigation_bar = ttk.Frame(self)
        self.navigation_bar.grid(row=0, column=0, sticky='ew')
        self.navigation_bar.columnconfigure(0, weight=1)

        self.label_bar = tk.Label(self.navigation_bar, text='Method Editor', anchor='w')
        self.label_bar.grid(row=0, column=0, sticky='ew')

        self.back_button = ttk.Button(
            self.navigation_bar,
            text='Back',
            command=self.go_to_previous_method,
        )
        self.back_button.grid(row=0, column=1, padx=(6, 0))

        self.forward_button = ttk.Button(
            self.navigation_bar,
            text='Forward',
            command=self.go_to_next_method,
        )
        self.forward_button.grid(row=0, column=2, padx=(4, 0))

        self.history_combobox = ttk.Combobox(
            self.navigation_bar,
            state='readonly',
            width=44,
        )
        self.history_combobox.grid(row=0, column=3, padx=(6, 0), sticky='e')
        self.history_combobox.bind(
            '<<ComboboxSelected>>',
            self.jump_to_selected_history_entry,
        )

        self.editor_notebook = ttk.Notebook(self)
        self.editor_notebook.grid(row=1, column=0, sticky='nsew')
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.editor_notebook.bind('<Motion>', self.on_tab_motion)
        self.editor_notebook.bind('<Leave>', self.on_tab_leave)

        self.open_tab_registry = DeduplicatedTabRegistry(self.editor_notebook)
        self.open_tabs = self.open_tab_registry.tabs_by_key

        self.event_queue.subscribe('MethodSelected', self.open_method)
        self.event_queue.subscribe(
            'MethodSelected',
            self.record_method_navigation,
        )
        self.event_queue.subscribe('MethodsChanged', self.repopulate)
        self.event_queue.subscribe('Committed', self.repopulate)
        self.event_queue.subscribe('Aborted', self.repopulate)
        self.event_queue.subscribe(
            'McpBusyStateChanged',
            self.handle_mcp_busy_state_changed,
            ui_context=self.ui_context,
        )
        self.refresh_navigation_controls()
        self.set_read_only(
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )

    def repopulate(self, origin=None):
        for key, tab in dict(self.open_tabs).items():
            tab.repopulate()

    def get_tab(self, tab_index):
        tab_id = self.editor_notebook.tabs()[tab_index]
        return self.editor_notebook.nametowidget(tab_id)

    def open_tab_menu_handler(self, event):
        return None

    def close_tab(self, tab):
        if tab.tab_key not in self.open_tabs:
            return
        self.editor_notebook.forget(self.open_tabs[tab.tab_key])
        self.open_tab_registry.remove_key(tab.tab_key)

    def current_method_context(self):
        selected_class = self.gemstone_session_record.selected_class
        selected_method_symbol = self.gemstone_session_record.selected_method_symbol
        if selected_class is None:
            return None
        if selected_method_symbol is None:
            return None
        return (
            selected_class,
            self.gemstone_session_record.show_instance_side,
            selected_method_symbol,
        )

    def method_context_label(self, method_context):
        class_name, show_instance_side, method_symbol = method_context
        if show_instance_side:
            return f'{class_name}>>{method_symbol}'
        return f'{class_name} class>>{method_symbol}'

    def record_method_navigation(self, origin=None):
        self.method_navigation_history.record(self.current_method_context())
        self.refresh_navigation_controls()

    def refresh_navigation_controls(self):
        back_button_state = (
            tk.NORMAL if self.method_navigation_history.can_go_back() else tk.DISABLED
        )
        self.back_button.configure(state=back_button_state)

        forward_button_state = (
            tk.NORMAL
            if self.method_navigation_history.can_go_forward()
            else tk.DISABLED
        )
        self.forward_button.configure(state=forward_button_state)

        history_entries = self.method_navigation_history.entries_with_current_marker()
        self.history_choice_indices = []
        history_labels = []
        for history_entry in reversed(history_entries):
            history_index = history_entry['history_index']
            method_context = history_entry['entry']
            history_labels.append(self.method_context_label(method_context))
            self.history_choice_indices.append(history_index)
        self.history_combobox['values'] = history_labels

        if len(history_labels) > 0:
            current_history_index = self.method_navigation_history.current_index
            selected_index = len(history_labels) - current_history_index - 1
            self.history_combobox.current(selected_index)
        if len(history_labels) == 0:
            self.history_combobox.set('')

    def jump_to_method_context(self, method_context):
        if method_context is None:
            self.refresh_navigation_controls()
            return
        if method_context == self.current_method_context():
            self.refresh_navigation_controls()
            return
        class_name, show_instance_side, method_symbol = method_context
        self.browser_window.application.handle_sender_selection(
            class_name,
            show_instance_side,
            method_symbol,
        )
        self.refresh_navigation_controls()

    def go_to_previous_method(self):
        method_context = self.method_navigation_history.go_back()
        self.jump_to_method_context(method_context)

    def go_to_next_method(self):
        method_context = self.method_navigation_history.go_forward()
        self.jump_to_method_context(method_context)

    def jump_to_selected_history_entry(self, event):
        combobox_index = self.history_combobox.current()
        if combobox_index < 0:
            return
        if combobox_index >= len(self.history_choice_indices):
            return
        history_index = self.history_choice_indices[combobox_index]
        method_context = self.method_navigation_history.jump_to(history_index)
        self.jump_to_method_context(method_context)

    def open_method(self, origin=None):
        method_context = self.current_method_context()
        if method_context is None:
            return
        selected_method_symbol = method_context[2]

        if self.open_tab_registry.select_key(method_context):
            return

        new_tab = EditorTab(
            self.editor_notebook,
            self.browser_window,
            self,
            method_context,
        )
        self.editor_notebook.add(new_tab, text=selected_method_symbol)
        self.editor_notebook.select(new_tab)
        self.open_tab_registry.register_tab(
            method_context,
            new_tab,
            selected_method_symbol,
        )
        new_tab.code_panel.set_read_only(
            self.browser_window.application.integrated_session_state.is_mcp_busy()
        )

    def set_read_only(self, read_only):
        for open_tab in self.open_tabs.values():
            open_tab.code_panel.set_read_only(read_only)

    def handle_mcp_busy_state_changed(
        self,
        is_busy=False,
        operation_name='',
        busy_lease_token=None,
    ):
        busy_coordinator = getattr(
            self.browser_window.application,
            'busy_coordinator',
            None,
        )
        if busy_coordinator is not None:
            if not busy_coordinator.is_current_lease(busy_lease_token):
                return
        self.set_read_only(is_busy)

    def destroy(self):
        self.ui_context.invalidate()
        super().destroy()

    def on_tab_motion(self, event):
        try:
            tab_index = self.editor_notebook.index('@%d,%d' % (event.x, event.y))
            if tab_index is not None:
                tab_key = self.get_tab(tab_index).tab_key
                if tab_key[1]:
                    text = f'{tab_key[0]}>>{tab_key[2]}'
                else:
                    text = f'{tab_key[0]} class>>{tab_key[2]}'
                self.label_bar.config(text=text)
        except tk.TclError:
            pass

    def on_tab_leave(self, event):
        self.label_bar.config(text='Method Editor')


class BrowserWindow(ttk.PanedWindow):
    def __init__(self, parent, application):
        super().__init__(
            parent, orient=tk.VERTICAL
        )

        self.application = application

        self.top_frame = ttk.Frame(self)
        self.bottom_frame = ttk.Frame(self)

        self.add(self.top_frame)
        self.add(self.bottom_frame)

        self.packages_widget = PackageSelection(
            self.top_frame, self, self.event_queue, 0, 0
        )
        self.classes_widget = ClassSelection(
            self.top_frame, self, self.event_queue, 0, 1
        )
        self.categories_widget = CategorySelection(
            self.top_frame, self, self.event_queue, 0, 2
        )
        self.methods_widget = MethodSelection(
            self.top_frame, self, self.event_queue, 0, 3
        )

        self.editor_area_widget = MethodEditor(
            self.bottom_frame, self, self.event_queue, 0, 0, colspan=4
        )

        self.top_frame.columnconfigure(0, weight=1)
        self.top_frame.columnconfigure(1, weight=1)
        self.top_frame.columnconfigure(2, weight=1)
        self.top_frame.columnconfigure(3, weight=1)
        self.top_frame.rowconfigure(0, weight=1)

        self.bottom_frame.columnconfigure(0, weight=1)
        self.bottom_frame.rowconfigure(0, weight=1)

    @property
    def event_queue(self):
        return self.application.event_queue

    @property
    def gemstone_session_record(self):
        return self.application.gemstone_session_record
