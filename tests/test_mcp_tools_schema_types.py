import ast
import inspect

from reahl.swordfish.mcp import tools as mcp_tools


def collect_typed_default_parameter_violations(module):
    """AI: Walk the source AST of the MCP tools module and report every function
    parameter whose default value is a Python bool, int, float, or None but
    which carries no type annotation. FastMCP uses inspect.signature() to
    derive the advertised JSON schema; parameters without annotations default
    to 'string' and break interop with strict MCP clients."""
    module_source = inspect.getsource(module)
    module_ast = ast.parse(module_source)
    violations = []
    for ast_node in ast.walk(module_ast):
        is_function = isinstance(ast_node, ast.FunctionDef)
        is_decorated_as_tool = is_function and any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == 'tool'
            or isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id in {'experimental_tool'}
            for decorator in (ast_node.decorator_list if is_function else [])
        )
        if not is_decorated_as_tool:
            continue
        function_arguments = ast_node.args
        argument_defaults = function_arguments.defaults
        positional_arguments = function_arguments.args
        # AI: defaults align to the *tail* of positional arguments.
        default_offset = len(positional_arguments) - len(argument_defaults)
        for default_position, default_node in enumerate(argument_defaults):
            argument_node = positional_arguments[default_offset + default_position]
            default_value = default_value_of(default_node)
            is_typed_literal = isinstance(default_value, (bool, int, float))
            is_explicit_none = default_value is None
            requires_annotation = is_typed_literal or is_explicit_none
            if not requires_annotation:
                continue
            if argument_node.annotation is None:
                violations.append(
                    {
                        'function_name': ast_node.name,
                        'parameter_name': argument_node.arg,
                        'default_repr': repr(default_value),
                        'line': argument_node.lineno,
                    }
                )
    return violations


def default_value_of(default_node):
    """AI: Resolve a literal default expression to its Python value. Returns a
    sentinel object for non-literal defaults so the caller skips them."""
    if isinstance(default_node, ast.Constant):
        return default_node.value
    return _NON_LITERAL_DEFAULT


_NON_LITERAL_DEFAULT = object()


def test_every_bool_or_int_default_parameter_has_a_matching_type_annotation():
    """AI: FastMCP derives each tool's JSON schema from its Python signature.
    Parameters without annotations are advertised as 'string', which means a
    strict MCP client following the schema cannot pass booleans or integers.
    Each tool parameter whose default is a bool/int/float must therefore carry
    the matching annotation."""
    violations = collect_typed_default_parameter_violations(mcp_tools)
    assert violations == [], (
        'Some MCP tool parameters with bool/int defaults still lack type '
        'annotations:\n'
        + '\n'.join(
            '  %s(%s=%s) at tools.py:%s'
            % (
                violation['function_name'],
                violation['parameter_name'],
                violation['default_repr'],
                violation['line'],
            )
            for violation in violations
        )
    )
