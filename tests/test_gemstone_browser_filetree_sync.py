'''AI: Tests that the single edit chokepoint - GemstoneBrowserSession - mirrors edits to the
on-disk FileTree. Because both the IDE save path and the MCP tools funnel through these same
methods, exercising them here covers both edit sources at once. The GemStone leaf calls are
stubbed; the mirroring logic and the on-disk writes are real.'''

import os

from reahl.swordfish.gemstone.browser import GemstoneBrowserSession
from reahl.swordfish.gemstone.working_copy import point_working_copy_at


CYPRESS_CONFIG = (
    '{\n\t"separateMethodMetaAndSource" : false,\n'
    '\t"noMethodMetaData" : true,\n\t"useCypressPropertiesFile" : true\n}'
)


def enabled_repository_root(tmp_path, monkeypatch):
    '''AI: Isolate the shared sync config to a temp file and enable mirroring into a temp
    repository holding one tracked, Cypress-configured package.'''
    config_path = os.path.join(str(tmp_path), 'config.json')
    monkeypatch.setenv('SWORDFISH_FILETREE_SYNC_CONFIG', config_path)
    root = os.path.join(str(tmp_path), 'monticello')
    package = os.path.join(root, 'Wonka-Amount-Core.package')
    os.makedirs(package)
    with open(os.path.join(package, '.filetree'), 'w', encoding='utf-8') as config:
        config.write(CYPRESS_CONFIG)
    point_working_copy_at(root)
    return root


def add_tracked_package(root, package_name):
    '''AI: Register a second Cypress-configured package on disk so an extension protocol that
    names it resolves to a genuinely foreign package.'''
    package = os.path.join(root, package_name + '.package')
    os.makedirs(package)
    with open(os.path.join(package, '.filetree'), 'w', encoding='utf-8') as config:
        config.write(CYPRESS_CONFIG)


def read_text(path):
    with open(path, 'r', encoding='utf-8', newline='') as text_file:
        return text_file.read()


class FakeCompiledClass:
    '''AI: Records the category each compile is asked to use, so a test can assert the category
    that reaches the image - not only the one that reaches disk.'''

    def __init__(self, compiled_categories):
        self.compiled_categories = compiled_categories

    def compileMethod_dictionaries_category_environmentId(
        self, source, dictionaries, category, environment_id
    ):
        self.compiled_categories.append(category)
        return None


class FakeGemstoneSession:
    def execute(self, source):
        return None


class StubbedEditingSession(GemstoneBrowserSession):
    '''AI: A browser session whose GemStone leaves are stubbed, so the real compile/delete/
    recategorise/create methods run their mirroring side-effects against a temp repository.'''

    def __init__(self, class_category, source_by_selector, protocol_by_selector, class_definition):
        super().__init__(FakeGemstoneSession())
        self.class_category = class_category
        self.source_by_selector = source_by_selector
        self.protocol_by_selector = protocol_by_selector
        self.class_definition = class_definition
        self.compiled_categories = []

    def class_to_query(self, class_name, show_instance_side):
        return FakeCompiledClass(self.compiled_categories)

    def class_reference_expression(self, class_name, show_instance_side):
        return class_name

    def category_of_class(self, class_name):
        return self.class_category

    def existing_method_source(self, class_name, selector, show_instance_side):
        return self.source_by_selector.get(selector)

    def existing_method_protocol(self, class_name, method_selector, show_instance_side):
        return self.protocol_by_selector.get(method_selector)

    def get_method_source(self, class_name, method_selector, show_instance_side):
        return self.source_by_selector[method_selector]

    def get_class_definition(self, class_name):
        return self.class_definition

    def run_code(self, source):
        return None


def amount_session():
    return StubbedEditingSession(
        class_category='Wonka-Amount-Core',
        source_by_selector={},
        protocol_by_selector={},
        class_definition={
            'class_name': 'Widget',
            'superclass_name': 'Object',
            'package_name': 'Wonka-Amount-Core',
            'inst_var_names': ['size'],
            'class_var_names': [],
            'class_inst_var_names': [],
            'pool_dictionary_names': [],
        },
    )


def test_compiling_a_method_mirrors_it_to_disk(tmp_path, monkeypatch):
    '''AI: Compiling an instance method - whether from the IDE or an MCP tool - writes the
    method file under the owning package's class directory.'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    session = amount_session()
    session.compile_method('Amount', True, 'doubled\n\t^ number * 2', 'arithmetic')
    written = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
    )
    assert read_text(written) == 'arithmetic\ndoubled\n\t^ number * 2'


def test_compiling_a_binary_method_uses_the_mangled_filename(tmp_path, monkeypatch):
    '''AI: A binary selector reaches disk under its Cypress-mangled filename.'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    session = amount_session()
    session.compile_method('Amount', True, '>= other\n\t^ number >= other', 'comparing')
    written = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Amount.class', 'instance', '^more.equals.st'
    )
    assert os.path.exists(written)


def test_deleting_a_method_removes_its_mirrored_file(tmp_path, monkeypatch):
    '''AI: Deleting a method removes the file it occupied, located via its captured protocol.'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    session = amount_session()
    session.protocol_by_selector['doubled'] = 'arithmetic'
    session.compile_method('Amount', True, 'doubled\n\t^ 1', 'arithmetic')
    written = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
    )
    assert os.path.exists(written)
    session.delete_method('Amount', 'doubled', True)
    assert not os.path.exists(written)


def test_recategorising_into_extension_moves_the_file(tmp_path, monkeypatch):
    '''AI: Recategorising a method into a '*Package' extension that names a foreign package
    writes the extension file under that package and removes the now-stale class-directory file.'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    add_tracked_package(root, 'Wonka-Other-Core')
    session = amount_session()
    session.source_by_selector['doubled'] = 'doubled\n\t^ 1'
    session.protocol_by_selector['doubled'] = 'arithmetic'
    session.compile_method('Amount', True, 'doubled\n\t^ 1', 'arithmetic')
    class_file = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
    )
    assert os.path.exists(class_file)
    session.set_method_category('Amount', 'doubled', '*Wonka-Other-Core', True)
    extension_file = os.path.join(
        root, 'Wonka-Other-Core.package', 'Amount.extension', 'instance', 'doubled.st'
    )
    assert os.path.exists(extension_file)
    assert not os.path.exists(class_file)


def test_own_package_star_protocol_stays_in_the_class_directory(tmp_path, monkeypatch):
    '''AI: A '*Package' protocol that names the class's OWN defining package is not an
    extension: Pharo keeps such a method in the class directory with that star category line.
    The live mirror must write it there, never under a .extension directory.'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    session = amount_session()
    session.compile_method('Amount', True, 'doubled\n\t^ number * 2', '*Wonka-Amount-Core')
    class_file = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
    )
    assert read_text(class_file) == '*Wonka-Amount-Core\ndoubled\n\t^ number * 2'
    assert not os.path.exists(
        os.path.join(root, 'Wonka-Amount-Core.package', 'Amount.extension')
    )


def test_saving_an_edited_method_without_a_category_keeps_its_protocol(tmp_path, monkeypatch):
    '''AI: A plain save names no category (the IDE save path and the MCP default), so the
    session must reuse the method's current protocol rather than silently moving it to
    "as yet unclassified" - both in the image (the category handed to the compiler) and on disk
    (the mirrored file's category line).'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    session = amount_session()
    session.source_by_selector['doubled'] = 'doubled\n\t^ 1'
    session.protocol_by_selector['doubled'] = 'arithmetic'
    session.compile_method('Amount', True, 'doubled\n\t^ number * 2')
    assert session.compiled_categories == ['arithmetic']
    written = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
    )
    assert read_text(written) == 'arithmetic\ndoubled\n\t^ number * 2'


def test_saving_a_brand_new_method_without_a_category_is_unclassified(tmp_path, monkeypatch):
    '''AI: When no category is named and the method does not yet exist, there is no protocol to
    preserve, so it falls back to the conventional "as yet unclassified" default.'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    session = amount_session()
    session.compile_method('Amount', True, 'fresh\n\t^ 1')
    assert session.compiled_categories == ['as yet unclassified']
    written = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'fresh.st'
    )
    assert read_text(written) == 'as yet unclassified\nfresh\n\t^ 1'


def test_creating_a_class_writes_its_properties_file(tmp_path, monkeypatch):
    '''AI: Creating a class in a tracked, Cypress-configured package writes its properties.json
    with the class definition queried back from the image.'''
    root = enabled_repository_root(tmp_path, monkeypatch)
    session = amount_session()
    session.create_class('Widget', 'Object', ['size'], in_dictionary='UserGlobals')
    properties_path = os.path.join(
        root, 'Wonka-Amount-Core.package', 'Widget.class', 'properties.json'
    )
    assert os.path.exists(properties_path)
    assert '"name" : "Widget"' in read_text(properties_path)
    assert '"size"' in read_text(properties_path)


def test_mirroring_is_inert_when_sync_disabled(tmp_path, monkeypatch):
    '''AI: With no enabled config, compiling writes nothing to disk - the feature is opt-in.'''
    config_path = os.path.join(str(tmp_path), 'config.json')
    monkeypatch.setenv('SWORDFISH_FILETREE_SYNC_CONFIG', config_path)
    session = amount_session()
    session.compile_method('Amount', True, 'doubled\n\t^ 1', 'arithmetic')
    assert not os.path.exists(config_path)
