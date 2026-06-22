"""Running tests in the image on the user's behalf and surfacing the outcome to the IDE."""

import tkinter.messagebox as messagebox

from reahl.ptongue import GemstoneError

from reahl.swordfish.session_activity import ForegroundActivity


class TestExecution:
    """The running of one or more tests in the image, surfaced to the IDE.

    It runs as an interruptible foreground activity, so the menu-bar Stop can abandon a long
    suite. The outcome is delivered on the UI thread: a passing or failing run is shown by the
    given reporter; a genuine error trap opens the debugger; and a user-requested Stop is silent
    and opens no debugger, because the activity classifies an interrupted run apart from a failed
    one. The same execution serves the class list (run all tests), the method list (run one
    test) and the method editor, which live in different panes."""

    def __init__(self, application, message, run_tests, report_result, error_title):
        self.application = application
        self.message = message
        self.run_tests = run_tests
        self.report_result = report_result
        self.error_title = error_title

    def start(self):
        activity = ForegroundActivity(
            self.message,
            work=self.run_tests,
            on_finished=self.report_result,
            on_failed=self.report_failure,
        )
        self.application.run_foreground_activity(activity)

    def report_failure(self, error):
        if isinstance(error, GemstoneError):
            self.application.open_debugger(error)
        else:
            messagebox.showerror(self.error_title, str(error))
