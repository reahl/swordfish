import contextlib
import logging
import os
import threading

from reahl.ptongue import (
    GemstoneApiError,
    GemstoneError,
    LinkedSession,
    NotSupported,
    RPCSession,
)


class DomainException(Exception):
    pass


standard_stream_lock = threading.Lock()


@contextlib.contextmanager
def without_process_output():
    with standard_stream_lock:
        stdout_descriptor = os.dup(1)
        stderr_descriptor = os.dup(2)
        null_descriptor = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null_descriptor, 1)
            os.dup2(null_descriptor, 2)
            yield
        finally:
            os.dup2(stdout_descriptor, 1)
            os.dup2(stderr_descriptor, 2)
            os.close(null_descriptor)
            os.close(stdout_descriptor)
            os.close(stderr_descriptor)


def perform_without_process_output(action):
    with without_process_output():
        return action()


def create_linked_session(gemstone_user_name, gemstone_password, stone_name):
    logging.getLogger(__name__).debug(
        'Logging in linked session as %s stone_name=%s',
        gemstone_user_name,
        stone_name,
    )
    try:
        return perform_without_process_output(
            lambda: LinkedSession(
                gemstone_user_name,
                gemstone_password,
                stone_name=stone_name,
            )
        )
    except GemstoneError as error:
        raise DomainException('Gemstone error: %s' % error)


def create_rpc_session(
    gemstone_user_name,
    gemstone_password,
    rpc_hostname,
    stone_name,
    netldi_name,
):
    nrs_string = '!@%s#netldi:%s!gemnetobject' % (rpc_hostname, netldi_name)
    logging.getLogger(__name__).debug(
        'Logging in rpc session as %s stone_name=%s netldi_task=%s',
        gemstone_user_name,
        stone_name,
        nrs_string,
    )
    try:
        return perform_without_process_output(
            lambda: RPCSession(
                gemstone_user_name,
                gemstone_password,
                stone_name=stone_name,
                netldi_task=nrs_string,
            )
        )
    except GemstoneError as error:
        raise DomainException('Gemstone error: %s' % error)


def close_session(gemstone_session):
    perform_without_process_output(gemstone_session.log_out)


def begin_transaction(gemstone_session):
    perform_without_process_output(gemstone_session.begin)


def commit_transaction(gemstone_session):
    perform_without_process_output(gemstone_session.commit)


def abort_transaction(gemstone_session):
    perform_without_process_output(gemstone_session.abort)


def session_summary(gemstone_session):
    return perform_without_process_output(
        lambda: {
            'stone_name': gemstone_session.System.stoneName().to_py,
            'host_name': gemstone_session.System.hostname().to_py,
            'user_name': gemstone_session.System.myUserProfile().userId().to_py,
            'session_id': gemstone_session.execute('System session').to_py,
        }
    )


def evaluate_source(gemstone_session, source):
    result = perform_without_process_output(
        lambda: gemstone_session.execute(source)
    )
    result_payload = render_result(result)
    return {
        'result': result_payload,
    }


def render_result(result):
    result_payload = {
        'oop': result.oop,
    }
    add_result_class(result, result_payload)
    add_python_value(result, result_payload)
    add_string_value(result, result_payload)
    return result_payload


def add_result_class(result, result_payload):
    try:
        result_payload['class_name'] = result.gemstone_class().name().to_py
    except GemstoneError as error:
        result_payload['class_name_error'] = gemstone_error_payload(error)


def add_python_value(result, result_payload):
    try:
        result_payload['python_value'] = result.to_py
    except NotSupported:
        result_payload['python_value'] = None
    except GemstoneError as error:
        result_payload['python_value_error'] = gemstone_error_payload(error)
    except GemstoneApiError as error:
        result_payload['python_value_error'] = {'message': str(error)}


def add_string_value(result, result_payload):
    try:
        result_payload['string_value'] = result.asString().to_py
    except GemstoneError as error:
        result_payload['string_value_error'] = gemstone_error_payload(error)
    except GemstoneApiError as error:
        result_payload['string_value_error'] = {'message': str(error)}


def gemstone_error_payload(error):
    payload = {
        'message': str(error),
        'number': error.number,
        'is_fatal': error.is_fatal,
    }
    add_error_reason(error, payload)
    return payload


def add_error_reason(error, payload):
    try:
        payload['reason'] = error.reason
    except GemstoneError:
        payload['reason'] = ''
