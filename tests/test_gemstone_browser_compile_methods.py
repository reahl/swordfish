'''AI: Tests for the batched compile primitive GemstoneBrowserSession.compile_methods - the single
compile path that gs_compile_methods (bulk authoring) and compile_method_in_dictionary both route
through. The GemStone-side leaves (run_compile_chunk, existing_method_source, mirror_compiled_method)
are stubbed; the orchestration - selector parsing, chunking, input-order preservation, server-side
program text and the mirroring decision - is real. Each test isolates one insight about how a batch
behaves so the round-trip-collapsing rewrite stays honest.'''

import os

from reahl.stubble import stubclass
from reahl.tofu import Fixture, scenario, with_fixtures

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.working_copy import point_working_copy_at


class FakeGemValue:
    '''AI: Stands in for a parseltongue leaf proxy whose to_py yields the Python value, so
    parsed_compile_chunk_results can be exercised without a live gem.'''

    def __init__(self, value):
        self.value = value

    @property
    def to_py(self):
        return self.value


class FakeGemArray:
    '''AI: Stands in for a gem-side Array/OrderedCollection proxy, answering size/at: the way the
    real result is traversed - nested lists become FakeGemArrays, scalars become FakeGemValues.'''

    def __init__(self, rows):
        self.rows = rows

    def size(self):
        return FakeGemValue(len(self.rows))

    def at(self, index):
        element = self.rows[index - 1]
        if isinstance(element, list):
            return FakeGemArray(element)
        return FakeGemValue(element)


class StringBuildingFixture(Fixture):
    def new_browser_session(self):
        return GemstoneBrowserSession(None)


class TargetClassExpressionScenarios(Fixture):
    @scenario
    def no_dictionary_resolves_via_symbol_list(self):
        '''AI: With no dictionary named, the class is resolved across the whole symbol list, the
        same reach an ordinary recompile has.'''
        self.in_dictionary = None
        self.expected_fragment = "System myUserProfile symbolList objectNamed: 'Account' asSymbol"

    @scenario
    def identifier_dictionary_resolves_via_that_dictionary(self):
        '''AI: A named dictionary scopes the lookup to that dictionary, reusing
        dictionary_reference_expression, and tolerates an absent class with otherwise: nil so a
        missing class is one row's error, not a chunk-wide failure.'''
        self.in_dictionary = 'UserGlobals'
        self.expected_fragment = "(UserGlobals at: 'Account' asSymbol otherwise: nil)"

    @scenario
    def non_identifier_dictionary_resolves_via_object_named(self):
        '''AI: A dictionary name that is not a bare identifier still resolves, because
        dictionary_reference_expression falls back to objectNamed: for it.'''
        self.in_dictionary = 'Weird Dict'
        self.expected_fragment = "objectNamed: 'Weird Dict' asSymbol"


@with_fixtures(StringBuildingFixture, TargetClassExpressionScenarios)
def test_target_class_expression_resolution(fixture, scenario):
    '''AI: The expression that finds the class to compile into depends only on whether a dictionary
    is named and what shape its name has - this is the seam that consolidated the dictionary-scoped
    compile onto the batch.'''
    expression = fixture.browser_session.target_class_expression('Account', scenario.in_dictionary)

    assert scenario.expected_fragment in expression


@with_fixtures(StringBuildingFixture)
def test_compile_spec_element_emits_dynamic_array_with_escaped_source(fixture):
    '''AI: Each spec becomes a dynamic array element so its booleans and nils are real objects, the
    class-side flag rides along, and a source containing a quote survives by quote-doubling rather
    than corrupting the program.'''
    element = fixture.browser_session.compile_spec_element(
        'Account', False, 'name:', "name: aName\n\t^x isn't y", None, None
    )

    assert element.startswith('{') and element.endswith('}')
    assert "'Account'" in element
    assert "'name:'" in element
    assert ' false.' in element
    assert "isn''t" in element
    assert element.rstrip().endswith('nil }')


@with_fixtures(StringBuildingFixture)
def test_batch_program_fetches_symbol_list_once_and_preserves_protocol(fixture):
    '''AI: The chunk program is what makes a batch one round-trip and protocol-safe: it fetches the
    symbol list a single time and, when a category is omitted, keeps an existing method's protocol
    server-side rather than reclassifying it.'''
    program = fixture.browser_session.batch_compile_program("{ 'A'. nil. 'm'. true. 's'. nil }")

    assert program.count('System myUserProfile symbolList') == 1
    assert 'includesSelector:' in program
    assert 'categoryOfSelector:' in program
    assert 'as yet unclassified' in program
    assert 'compileMethod:' in program


@with_fixtures(StringBuildingFixture)
def test_parsed_compile_chunk_results_maps_arrays_to_rows(fixture):
    '''AI: The gem returns one six-element array per method; parsing turns each into a result row,
    carrying a success and a not-found outcome back unchanged.'''
    raw = FakeGemArray([
        ['Account', 'name', True, 'accessing', True, ''],
        ['Bank', 'foo', False, '', False, 'Class not found.'],
    ])

    rows = fixture.browser_session.parsed_compile_chunk_results(raw)

    assert rows[0] == {
        'class_name': 'Account', 'selector': 'name', 'show_instance_side': True,
        'method_category': 'accessing', 'ok': True, 'error': '',
    }
    assert rows[1]['ok'] is False
    assert rows[1]['error'] == 'Class not found.'


@stubclass(GemstoneBrowserSession)
class ChunkRecordingBrowserSession(GemstoneBrowserSession):
    '''AI: Replaces only the gem round-trip: records each chunk it is handed and reports every spec
    in it as a successful compile, so orchestration - parse filtering, chunk boundaries and input
    order - can be observed without an image. stubclass keeps run_compile_chunk's signature honest.'''

    recorded_chunks = None

    def run_compile_chunk(self, chunk):
        self.recorded_chunks.append(list(chunk))
        return [
            self.compile_result_row(
                entry[1], entry[3], entry[2],
                entry[5] if entry[5] is not None else 'as yet unclassified',
                True, '',
            )
            for entry in chunk
        ]


def chunk_recording_session(tmp_path, monkeypatch):
    '''AI: A recording session with FileTree sync pointed at an absent config, so mirroring is
    inert and these tests observe only the compile orchestration.'''
    monkeypatch.setenv('SWORDFISH_FILETREE_SYNC_CONFIG', os.path.join(str(tmp_path), 'config.json'))
    session = ChunkRecordingBrowserSession(None)
    session.recorded_chunks = []
    return session


def test_unparseable_source_becomes_error_row_without_reaching_gem(tmp_path, monkeypatch):
    '''AI: A source whose method cannot be parsed never reaches the gem - it becomes that row's
    error here, while its well-formed siblings still compile, so one bad paste cannot block a batch
    or be blamed on the image.'''
    session = chunk_recording_session(tmp_path, monkeypatch)

    results = session.compile_methods([
        ('Account', True, '123 not a method', None, None),
        ('Account', True, 'name\n\t^x', None, None),
    ])

    assert results[0]['ok'] is False
    assert 'parseable' in results[0]['error']
    assert results[1]['ok'] is True
    assert len(session.recorded_chunks) == 1
    assert len(session.recorded_chunks[0]) == 1
    assert session.recorded_chunks[0][0][3] == 'name'


def test_results_preserve_input_order_across_chunks_and_parse_failures(tmp_path, monkeypatch):
    '''AI: Results come back in input order regardless of chunk boundaries or rows that never left
    Python, so a caller can zip results to its own list without tracking which specs were sent.'''
    session = chunk_recording_session(tmp_path, monkeypatch)

    results = session.compile_methods(
        [
            ('Account', True, 'a\n\t^1', None, None),
            ('Account', True, '123 not a method', None, None),
            ('Account', True, 'b\n\t^2', None, None),
            ('Account', True, 'c\n\t^3', None, None),
        ],
        chunk_size=2,
    )

    assert [row['selector'] for row in results] == ['a', '', 'b', 'c']
    assert [row['ok'] for row in results] == [True, False, True, True]
    assert len(session.recorded_chunks) == 2


def test_large_batch_is_split_into_bounded_chunks(tmp_path, monkeypatch):
    '''AI: A batch larger than the chunk size is sent as several bounded programs, not one
    unbounded one - the bound that keeps each round-trip's allocation from pressuring the gem's
    garbage collector.'''
    session = chunk_recording_session(tmp_path, monkeypatch)
    specs = [('Account', True, 'm%s\n\t^%s' % (index, index), None, None) for index in range(120)]

    results = session.compile_methods(specs, chunk_size=50)

    assert len(results) == 120
    assert [len(chunk) for chunk in session.recorded_chunks] == [50, 50, 20]


@stubclass(GemstoneBrowserSession)
class MirroringRecordingBrowserSession(GemstoneBrowserSession):
    '''AI: Replaces the gem compile and the mirror's own gem queries, recording which methods the
    batch asks the on-disk mirror to update so we can prove the batch funnels through the same
    mirroring everything else uses.'''

    recorded_mirror_calls = None

    def run_compile_chunk(self, chunk):
        return [
            self.compile_result_row(entry[1], entry[3], entry[2], 'accessing', True, '')
            for entry in chunk
        ]

    def existing_method_source(self, class_name, selector, show_instance_side):
        return None

    def mirror_compiled_method(
        self, class_name, show_instance_side, source, method_category, selector, previous_source
    ):
        self.recorded_mirror_calls.append((class_name, selector, method_category))
        return None


def test_successful_rows_are_mirrored_when_sync_is_active(tmp_path, monkeypatch):
    '''AI: When FileTree sync is on, each method a batch successfully compiles is mirrored to disk -
    the batch must not be a back door that edits the image without updating the working copy.'''
    monkeypatch.setenv('SWORDFISH_FILETREE_SYNC_CONFIG', os.path.join(str(tmp_path), 'config.json'))
    root = os.path.join(str(tmp_path), 'monticello')
    os.makedirs(root)
    point_working_copy_at(root)
    session = MirroringRecordingBrowserSession(None)
    session.recorded_mirror_calls = []

    session.compile_methods([('Account', True, 'name\n\t^x', None, None)])

    assert session.recorded_mirror_calls == [('Account', 'name', 'accessing')]


@stubclass(GemstoneBrowserSession)
class SpecCapturingBrowserSession(GemstoneBrowserSession):
    '''AI: Captures the spec list compile_method_in_dictionary builds, so its delegation to the
    batch primitive can be pinned exactly.'''

    captured_specs = None

    def compile_methods(self, method_specs, chunk_size=50):
        self.captured_specs = method_specs
        return [self.compile_result_row('Account', 'name', True, 'accessing', True, '')]


@with_fixtures(StringBuildingFixture)
def test_compile_method_in_dictionary_delegates_with_protocol_preserving_category(fixture):
    '''AI: A dictionary-scoped compile is now a one-element batch. Crucially this is a deliberate
    behaviour change: the old standalone version always filed an omitted category under "as yet
    unclassified", whereas delegating with method_category=None routes it through the batch's
    server-side preserve-or-default, so an existing method keeps its protocol.'''
    session = SpecCapturingBrowserSession(None)

    row = session.compile_method_in_dictionary('Account', 'UserGlobals', True, 'name\n\t^x')

    assert session.captured_specs == [('Account', True, 'name\n\t^x', None, 'UserGlobals')]
    assert row['ok'] is True
