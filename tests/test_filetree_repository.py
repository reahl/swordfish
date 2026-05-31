'''AI: Byte-level fidelity tests for the on-disk Monticello FileTree representation.

The single most important property of the sync feature is that files it writes are
indistinguishable from what Pharo writes, so that mirroring an edit never produces a
spurious diff in the version-controlled repository. These tests pin that down against a
small corpus of real Wonka files copied verbatim into tests/fixtures/monticello.'''

import json
import os

from reahl.tofu import Fixture, scenario, with_fixtures
from reahl.tofu import expected, NoException

from reahl.swordfish.gemstone.filetree_sync import (
    MonticelloRepository,
    mangle_selector,
)


FIXTURE_ROOT = os.path.join(os.path.dirname(__file__), 'fixtures', 'monticello')


def read_bytes_as_text(path):
    with open(path, 'r', encoding='utf-8', newline='') as text_file:
        return text_file.read()


class SelectorManglingScenarios(Fixture):
    '''AI: One scenario per kind of selector, each carrying the domain rule it demonstrates.'''

    @scenario
    def unary_selector_is_used_verbatim(self):
        '''AI: A unary selector is already a legal filename, so it is left untouched.'''
        self.selector = 'hash'
        self.filename_base = 'hash'

    @scenario
    def single_keyword_colon_becomes_dot(self):
        '''AI: The one colon of a single-keyword selector maps to a single dot.'''
        self.selector = 'valueWithPrice:'
        self.filename_base = 'valueWithPrice.'

    @scenario
    def every_keyword_colon_becomes_a_dot(self):
        '''AI: Multi-keyword selectors map each colon independently to a dot.'''
        self.selector = 'adaptToFraction:andSend:'
        self.filename_base = 'adaptToFraction.andSend.'

    @scenario
    def single_binary_character_is_named(self):
        '''AI: A one-character binary selector becomes a caret and the character's name.'''
        self.selector = '='
        self.filename_base = '^equals'

    @scenario
    def binary_slash_is_named(self):
        '''AI: The slash, illegal in a path segment, is encoded by name.'''
        self.selector = '/'
        self.filename_base = '^slash'

    @scenario
    def multi_character_binary_joins_names_with_dots(self):
        '''AI: Each character of a multi-character binary selector is named and dot-joined.'''
        self.selector = '>='
        self.filename_base = '^more.equals'


@with_fixtures(SelectorManglingScenarios)
def test_selector_maps_to_cypress_filename(mangling):
    '''AI: A selector maps to its Cypress base filename exactly as Pharo's writer would.'''
    assert mangle_selector(mangling.selector) == mangling.filename_base


def test_every_corpus_method_filename_is_reproduced():
    '''AI: Cross-check the mangling against the real corpus: each .st file we kept must be the
    file Pharo named for the selector on its second line, so our naming cannot silently drift.'''
    expected_pairs = {
        'hash': 'hash',
        'ceiling': 'ceiling',
        'valueWithPrice:': 'valueWithPrice.',
        'adaptToFraction:andSend:': 'adaptToFraction.andSend.',
        '>=': '^more.equals',
        '/': '^slash',
        '=': '^equals',
        'zero': 'zero',
    }
    instance_directory = os.path.join(
        FIXTURE_ROOT, 'Wonka-Amount-Core.package', 'Amount.class', 'instance'
    )
    present = set(os.listdir(instance_directory))
    for selector, filename_base in expected_pairs.items():
        mangled = mangle_selector(selector)
        assert mangled == filename_base
        is_class_side = selector == 'zero'
        if not is_class_side:
            assert (mangled + '.st') in present


def test_method_file_contents_round_trip_for_every_corpus_file():
    '''AI: For every real method file, splitting it into category line + source and rebuilding
    it through the serializer must reproduce the original bytes - proving we add no trailing
    newline and disturb no internal whitespace.'''
    repository = MonticelloRepository(FIXTURE_ROOT)
    method_files = []
    for current_root, directories, files in os.walk(FIXTURE_ROOT):
        in_method_directory = os.path.basename(current_root) in ('instance', 'class')
        method_files.extend(
            os.path.join(current_root, name)
            for name in files
            if in_method_directory and name.endswith('.st')
        )
    assert method_files
    for path in method_files:
        original = read_bytes_as_text(path)
        newline_index = original.find('\n')
        category_line = original[:newline_index]
        source = original[newline_index + 1 :]
        assert repository.method_file_contents(category_line, source) == original


class ClassPropertiesScenarios(Fixture):
    '''AI: Representative class definitions exercising each serialization branch.'''

    @scenario
    def single_instance_variable(self):
        '''AI: A class with one instvar and otherwise empty lists (the common shape).'''
        self.relative_path = 'Wonka-Amount-Core.package/Amount.class/properties.json'

    @scenario
    def several_instance_variables(self):
        '''AI: A class with a multi-item instvar list, exercising the multiline array branch.'''
        self.relative_path = 'Wonka-Amount-Core.package/Currency.class/properties.json'

    @scenario
    def non_normal_class_type(self):
        '''AI: A bytes-kind class, exercising a non-normal type value.'''
        self.relative_path = 'Wonka-Entities-Core.package/IDNumber.class/properties.json'


@with_fixtures(ClassPropertiesScenarios)
def test_class_properties_json_serialization_is_byte_exact(properties):
    '''AI: Parsing a real Cypress properties.json and re-serializing it must reproduce the
    original bytes, so a class-definition change rewrites only the values that changed.'''
    path = os.path.join(FIXTURE_ROOT, properties.relative_path)
    original = read_bytes_as_text(path)
    with open(path, 'r', encoding='utf-8') as properties_file:
        definition = json.load(properties_file)
    repository = MonticelloRepository(FIXTURE_ROOT)
    assert repository.class_properties_json(definition) == original


class RepositoryFixture(Fixture):
    def new_repository(self):
        return MonticelloRepository(FIXTURE_ROOT)


@with_fixtures(RepositoryFixture)
def test_tracked_packages_are_the_package_directories(repository_fixture):
    '''AI: The tracked subset is exactly the .package directories present on disk.'''
    assert repository_fixture.repository.tracked_package_names() == [
        'Wonka-Amount-Core',
        'Wonka-Entities-Core',
    ]


@with_fixtures(RepositoryFixture)
def test_class_category_resolves_to_owning_package(repository_fixture):
    '''AI: A class is owned by the package whose name equals its category, or the longest
    package name of which the category is a hyphen-delimited sub-category.'''
    repository = repository_fixture.repository
    assert repository.package_owning_category('Wonka-Amount-Core') == 'Wonka-Amount-Core'
    assert (
        repository.package_owning_category('Wonka-Amount-Core-Private')
        == 'Wonka-Amount-Core'
    )
    assert repository.package_owning_category('Some-Other-Thing') is None


@with_fixtures(RepositoryFixture)
def test_extension_protocol_resolves_to_owning_package(repository_fixture):
    '''AI: An extension method is owned by the package named after its '*Package' protocol,
    matched case-insensitively because image protocols are not case-canonical.'''
    repository = repository_fixture.repository
    assert (
        repository.package_for_extension_protocol('*Wonka-Amount-Core')
        == 'Wonka-Amount-Core'
    )
    assert (
        repository.package_for_extension_protocol('*wonka-amount-core')
        == 'Wonka-Amount-Core'
    )
    assert repository.package_for_extension_protocol('*Not-Tracked') is None
    assert repository.package_for_extension_protocol('accessing') is None


@with_fixtures(RepositoryFixture)
def test_package_format_gate_recognises_cypress(repository_fixture):
    '''AI: We only rewrite properties.json for packages whose configured format we model.'''
    assert repository_fixture.repository.package_uses_cypress_properties('Wonka-Amount-Core')


def repository_with_empty_package(tmp_path):
    '''AI: A throwaway repository holding one empty tracked package, for write/remove tests.'''
    os.makedirs(os.path.join(str(tmp_path), 'Wonka-Amount-Core.package'))
    return MonticelloRepository(str(tmp_path))


def test_writing_a_method_produces_the_expected_file(tmp_path):
    '''AI: Writing an instance method lands the category line plus source, with no trailing
    newline, at the Cypress-named path - and reports its own source back for drift checks.'''
    repository = repository_with_empty_package(tmp_path)
    path = repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', 'arithmetic',
        'doubled\n\t^ number * 2',
    )
    assert path.endswith(
        os.path.join('Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st')
    )
    assert read_bytes_as_text(path) == 'arithmetic\ndoubled\n\t^ number * 2'
    assert (
        repository.disk_method_source('Wonka-Amount-Core', 'Amount', False, False, 'doubled')
        == 'doubled\n\t^ number * 2'
    )


def test_removing_a_method_deletes_only_its_file(tmp_path):
    '''AI: Removing a method deletes exactly its own file and reports whether one was there.'''
    repository = repository_with_empty_package(tmp_path)
    repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', 'arithmetic', 'doubled\n\t^ 1',
    )
    assert repository.remove_method('Wonka-Amount-Core', 'Amount', False, False, 'doubled')
    assert not repository.remove_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled'
    )


def test_class_definition_change_preserves_existing_comment_stamp(tmp_path):
    '''AI: Rewriting a class definition (e.g. adding an instvar) must not disturb the
    commentStamp Pharo recorded, since the comment did not change.'''
    repository = repository_with_empty_package(tmp_path)
    seeded = {
        'commentStamp': 'iwan 5/30/2026 09:00',
        'super': 'Number',
        'category': 'Wonka-Amount-Core',
        'classinstvars': [],
        'pools': [],
        'classvars': [],
        'instvars': ['number'],
        'name': 'Amount',
        'type': 'normal',
    }
    repository.write_class_definition('Wonka-Amount-Core', seeded)
    changed = dict(seeded)
    changed['instvars'] = ['number', 'currency']
    changed.pop('commentStamp')
    properties_path = repository.write_class_definition('Wonka-Amount-Core', changed)
    with open(properties_path, 'r', encoding='utf-8') as properties_file:
        written = json.load(properties_file)
    assert written['commentStamp'] == 'iwan 5/30/2026 09:00'
    assert written['instvars'] == ['number', 'currency']


def test_reading_back_the_corpus_classes_and_methods(tmp_path):
    '''AI: The repository can enumerate and read what is on disk - defined classes, extended
    classes, the class definition, and each method's category line and source - which is the
    raw material a file-in needs.'''
    repository = MonticelloRepository(FIXTURE_ROOT)
    assert 'Amount' in repository.defined_class_names('Wonka-Amount-Core')
    assert 'Float' in repository.extension_class_names('Wonka-Amount-Core')
    definition = repository.read_class_definition('Wonka-Amount-Core', 'Amount')
    assert definition['name'] == 'Amount'
    assert definition['instvars'] == ['number']
    instance_methods = repository.stored_methods(
        'Wonka-Amount-Core', 'Amount', False, False
    )
    hash_methods = [
        method for method in instance_methods if method['source'].startswith('hash')
    ]
    assert hash_methods[0]['category'] == 'hash'
    assert hash_methods[0]['source'] == 'hash\n\t^ number hash'


def test_ensuring_a_new_package_creates_cypress_layout(tmp_path):
    '''AI: Filing out into a package that is not yet on disk creates the .package directory
    with a Cypress .filetree and the minimal Monticello metadata, so it is a usable package.'''
    repository = MonticelloRepository(str(tmp_path))
    repository.ensure_package('Wonka-New-Core')
    package_directory = os.path.join(str(tmp_path), 'Wonka-New-Core.package')
    assert repository.package_uses_cypress_properties('Wonka-New-Core')
    assert read_bytes_as_text(os.path.join(package_directory, 'monticello.meta', 'package')) == (
        "(name 'Wonka-New-Core')"
    )


def test_ensuring_an_existing_package_leaves_it_untouched(tmp_path):
    '''AI: ensure_package must not rewrite a package that already exists, so a real Pharo
    package's files are never disturbed by a file-out into it.'''
    repository = MonticelloRepository(str(tmp_path))
    package_directory = os.path.join(str(tmp_path), 'Wonka-Amount-Core.package')
    os.makedirs(package_directory)
    marker_path = os.path.join(package_directory, '.filetree')
    with open(marker_path, 'w', encoding='utf-8') as marker:
        marker.write('SENTINEL')
    repository.ensure_package('Wonka-Amount-Core')
    assert read_bytes_as_text(marker_path) == 'SENTINEL'


def test_writing_class_definition_creates_method_directories(tmp_path):
    '''AI: A freshly created class gets empty instance/ and class/ directories alongside its
    properties.json, matching the layout Pharo expects.'''
    repository = repository_with_empty_package(tmp_path)
    with expected(NoException):
        repository.write_class_definition(
            'Wonka-Amount-Core',
            {
                'super': 'Object',
                'category': 'Wonka-Amount-Core',
                'classinstvars': [],
                'pools': [],
                'classvars': [],
                'instvars': [],
                'name': 'Widget',
                'type': 'normal',
            },
        )
    class_directory = os.path.join(
        str(tmp_path), 'Wonka-Amount-Core.package', 'Widget.class'
    )
    assert os.path.isdir(os.path.join(class_directory, 'instance'))
    assert os.path.isdir(os.path.join(class_directory, 'class'))
