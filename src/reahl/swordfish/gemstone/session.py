import logging

from reahl.ptongue import GemstoneApiError
from reahl.ptongue import GemstoneError
from reahl.ptongue import LinkedSession
from reahl.ptongue import NotSupported
from reahl.ptongue import RPCSession


class DomainException(Exception):
    pass


def create_linked_session(gemstone_user_name, gemstone_password, stone_name):
    logging.getLogger(__name__).debug(
        'Logging in linked session as %s stone_name=%s',
        gemstone_user_name,
        stone_name,
    )
    try:
        return LinkedSession(
            gemstone_user_name,
            gemstone_password,
            stone_name=stone_name,
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
        return RPCSession(
            gemstone_user_name,
            gemstone_password,
            stone_name=stone_name,
            netldi_task=nrs_string,
        )
    except GemstoneError as error:
        raise DomainException('Gemstone error: %s' % error)


def close_session(gemstone_session):
    gemstone_session.log_out()


def session_summary(gemstone_session):
    return {
        'stone_name': gemstone_session.System.stoneName().to_py,
        'host_name': gemstone_session.System.hostname().to_py,
        'user_name': gemstone_session.System.myUserProfile().userId().to_py,
        'session_id': gemstone_session.execute('System session').to_py,
    }


def evaluate_source(gemstone_session, source):
    result = gemstone_session.execute(source)
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
