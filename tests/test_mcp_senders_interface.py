from reahl.tofu import Fixture, set_up, tear_down, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.mcp.session_registry import add_connection, clear_connections
from reahl.swordfish.mcp.tools import register_tools


class McpToolRegistrar:
    def __init__(self):
        self.registered_tools_by_name = {}

    def tool(self):
        def register(function):
            self.registered_tools_by_name[function.__name__] = function
            return function

        return register


class FakeGemstoneSession:
    """AI: Lives in the registry only so get_browser_session resolves; never read."""


class McpSendersFixture(Fixture):
    """AI: Drives the senders MCP tools with the browser layer stubbed, so the tests pin
    the MCP wrapper's own behaviour - tier routing, filter/offset/real_sends_only
    pass-through, and echoing the browser's pagination - independently of the search and
    the (browser-level) response budget."""

    @set_up
    def install_recording_browser_methods(self):
        clear_connections()
        self.recorded_overview = None
        self.recorded_find_senders = None
        self.canned_overview = {
            'total': 312,
            'by_side': {'instance': 300, 'class': 12},
            'by_class_category': {'top': [{'class_category': 'UI', 'count': 140}],
                                  'remaining_values': 3, 'remaining_count': 20},
            'by_method_category': {'top': [], 'remaining_values': 0, 'remaining_count': 0},
            'classes': {'top': [{'class_name': 'Button', 'count': 30}],
                        'remaining_values': 50, 'remaining_count': 200},
        }
        self.canned_senders = []
        self.canned_total = 0
        self.canned_omitted = 0
        self.canned_next_offset = None
        self.canned_truncated = False
        self.canned_budget_reached = False
        self.original_overview = GemstoneBrowserSession.senders_overview
        self.original_find_senders = GemstoneBrowserSession.find_senders

        fixture = self

        def recording_senders_overview(browser_session, method_name, top=10):
            fixture.recorded_overview = {'method_name': method_name, 'top': top}
            return fixture.canned_overview

        def recording_find_senders(
            browser_session, method_name, max_results=None, count_only=False,
            include_category_details=False, granularity='identifier',
            class_categories=None, method_categories=None, class_name_pattern=None,
            side=None, offset=0, real_sends_only=False, max_response_chars=None,
        ):
            fixture.recorded_find_senders = {
                'method_name': method_name, 'max_results': max_results,
                'count_only': count_only, 'granularity': granularity,
                'class_categories': class_categories,
                'method_categories': method_categories,
                'class_name_pattern': class_name_pattern, 'side': side,
                'offset': offset, 'real_sends_only': real_sends_only,
                'max_response_chars': max_response_chars,
            }
            return {
                'senders': list(fixture.canned_senders),
                'total_count': fixture.canned_total,
                'returned_count': len(fixture.canned_senders),
                'reference_only_omitted': fixture.canned_omitted,
                'next_offset': fixture.canned_next_offset,
                'truncated': fixture.canned_truncated,
                'budget_reached': fixture.canned_budget_reached,
                'offset': offset,
            }

        GemstoneBrowserSession.senders_overview = recording_senders_overview
        GemstoneBrowserSession.find_senders = recording_find_senders

        self.connection_id = add_connection(
            FakeGemstoneSession(), {'connection_mode': 'linked'}
        )
        registrar = McpToolRegistrar()
        register_tools(
            registrar,
            allow_source_read=True,
            allow_source_write=True,
            experimental=True,
        )
        self.tools = registrar.registered_tools_by_name

    @tear_down
    def restore_browser_methods(self):
        GemstoneBrowserSession.senders_overview = self.original_overview
        GemstoneBrowserSession.find_senders = self.original_find_senders
        clear_connections()


@with_fixtures(McpSendersFixture)
def test_senders_overview_tool_returns_the_sized_summary(fixture):
    """AI: The overview tier hands back the count plus the bounded breakdown the model
    uses to choose filters, without touching the list path at all."""
    result = fixture.tools['gs_senders_overview'](fixture.connection_id, 'draw')

    assert result['ok'], result
    assert result['total'] == 312
    assert result['by_side'] == {'instance': 300, 'class': 12}
    assert result['classes']['remaining_values'] == 50
    assert fixture.recorded_overview['method_name'] == 'draw'


@with_fixtures(McpSendersFixture)
def test_find_senders_forwards_filters_offset_and_the_response_budget(fixture):
    """AI: The wrapper validates and forwards every narrowing facet, the paging offset,
    real_sends_only, and the response-size budget it owns - so the browser is asked the
    precise, bounded question."""
    fixture.canned_senders = [{'class_name': 'Button', 'kind': 'direct_send'}]
    fixture.canned_total = 1

    result = fixture.tools['gs_find_senders'](
        fixture.connection_id, 'draw',
        class_categories=['UI'], method_categories=['rendering'],
        class_name_pattern='^But', side='instance', offset=20, max_results=10,
        granularity='send_site', real_sends_only=True,
    )

    assert result['ok'], result
    recorded = fixture.recorded_find_senders
    assert recorded['class_categories'] == ['UI']
    assert recorded['method_categories'] == ['rendering']
    assert recorded['class_name_pattern'] == '^But'
    assert recorded['side'] == 'instance'
    assert recorded['offset'] == 20
    assert recorded['max_results'] == 10
    assert recorded['real_sends_only'] is True
    assert recorded['max_response_chars'] == 32000


@with_fixtures(McpSendersFixture)
def test_find_senders_echoes_the_browsers_pagination_and_truncation(fixture):
    """AI: Paging and the budget verdict are decided by the browser in one pass; the
    wrapper just surfaces them, so the model gets next_offset, truncated, budget_reached
    and the omitted-reference count to drive the next call."""
    fixture.canned_senders = [{'class_name': 'Button', 'kind': 'direct_send'}]
    fixture.canned_total = 312
    fixture.canned_omitted = 4
    fixture.canned_next_offset = 50
    fixture.canned_truncated = True
    fixture.canned_budget_reached = True

    result = fixture.tools['gs_find_senders'](fixture.connection_id, 'draw')

    assert result['ok'], result
    assert result['truncated'] is True
    assert result['budget_reached'] is True
    assert result['next_offset'] == 50
    assert result['reference_only_omitted'] == 4
    assert result['total_count'] == 312
