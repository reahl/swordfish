'''AI: Tests for filing code out of the image into the on-disk FileTree (image -> disk). The
image is a stub backed by plain dictionaries; the on-disk writes are real. File-out is the
safe direction: it reuses the byte-exact writers and creates packages on demand.'''

import os

from reahl.swordfish.gemstone.filetree_sync import MonticelloRepository
from reahl.swordfish.gemstone.working_copy import MonticelloWorkingCopy


class StubImage:
    '''AI: A minimal stand-in for GemstoneBrowserSession's query surface used by file-out.'''

    def __init__(self, classes_by_category, class_definitions, methods):
        self.classes_by_category = classes_by_category
        self.class_definitions = class_definitions
        # AI: methods keyed by (class_name, show_instance_side) -> {selector: (protocol, source)}
        self.methods = methods

    def list_classes_in_category(self, class_category):
        return self.classes_by_category.get(class_category, [])

    def get_class_definition(self, class_name):
        return self.class_definitions[class_name]

    def list_methods(self, class_name, method_category, show_instance_side):
        installed = self.methods.get((class_name, show_instance_side), {})
        if method_category == 'all':
            return sorted(installed)
        return sorted(
            selector
            for selector, (protocol, _source) in installed.items()
            if protocol == method_category
        )

    def get_method_category(self, class_name, selector, show_instance_side):
        return self.methods[(class_name, show_instance_side)][selector][0]

    def get_method_source(self, class_name, selector, show_instance_side):
        return self.methods[(class_name, show_instance_side)][selector][1]


def amount_image():
    return StubImage(
        classes_by_category={'Wonka-Amount-Core': ['Amount']},
        class_definitions={
            'Amount': {
                'class_name': 'Amount',
                'superclass_name': 'Number',
                'package_name': 'Wonka-Amount-Core',
                'inst_var_names': ['number'],
                'class_var_names': [],
                'class_inst_var_names': [],
                'pool_dictionary_names': [],
            }
        },
        methods={
            ('Amount', True): {
                'doubled': ('arithmetic', 'doubled\n\t^ number * 2'),
                'asWidget': ('*Wonka-Other-Core', 'asWidget\n\t^ self'),
            },
            ('Amount', False): {
                'zero': ('instance creation', 'zero\n\t^ self new'),
            },
        },
    )


def working_copy_over(tmp_path):
    # AI: enabled=False proves file-out works as an explicit action even when live mirroring is off.
    return MonticelloWorkingCopy(
        repository=MonticelloRepository(str(tmp_path)), enabled=False
    )


def read_text(path):
    with open(path, 'r', encoding='utf-8', newline='') as text_file:
        return text_file.read()


def test_filing_out_a_class_writes_definition_and_own_methods(tmp_path):
    '''AI: Filing out a class creates its package, writes its properties.json, and writes each
    of its own methods under the correct side directory.'''
    working_copy = working_copy_over(tmp_path)
    working_copy.file_out_class(amount_image(), 'Amount')
    package = os.path.join(str(tmp_path), 'Wonka-Amount-Core.package')
    assert '"name" : "Amount"' in read_text(
        os.path.join(package, 'Amount.class', 'properties.json')
    )
    assert read_text(
        os.path.join(package, 'Amount.class', 'instance', 'doubled.st')
    ) == 'arithmetic\ndoubled\n\t^ number * 2'
    assert read_text(
        os.path.join(package, 'Amount.class', 'class', 'zero.st')
    ) == 'instance creation\nzero\n\t^ self new'


def test_filing_out_a_class_routes_extension_methods_to_their_package(tmp_path):
    '''AI: A method whose protocol names another package is filed out as an extension into
    that package, which is created on disk if it does not exist yet.'''
    working_copy = working_copy_over(tmp_path)
    working_copy.file_out_class(amount_image(), 'Amount')
    extension_file = os.path.join(
        str(tmp_path),
        'Wonka-Other-Core.package',
        'Amount.extension',
        'instance',
        'asWidget.st',
    )
    assert read_text(extension_file) == '*Wonka-Other-Core\nasWidget\n\t^ self'
    assert os.path.isdir(os.path.join(str(tmp_path), 'Wonka-Other-Core.package'))


def own_package_star_image():
    '''AI: A class whose own method carries a '*ThisPackage' protocol - a star category that
    names the class's own defining package rather than a foreign one.'''
    return StubImage(
        classes_by_category={'Wonka-Amount-Core': ['Amount']},
        class_definitions={
            'Amount': {
                'class_name': 'Amount',
                'superclass_name': 'Number',
                'package_name': 'Wonka-Amount-Core',
                'inst_var_names': ['number'],
                'class_var_names': [],
                'class_inst_var_names': [],
                'pool_dictionary_names': [],
            }
        },
        methods={
            ('Amount', True): {
                'tripled': ('*Wonka-Amount-Core', 'tripled\n\t^ number * 3'),
            },
            ('Amount', False): {},
        },
    )


def test_filing_out_keeps_own_package_star_methods_in_the_class_directory(tmp_path):
    '''AI: A method whose protocol names the class's OWN defining package ('*ThisPackage') is
    not an extension - Pharo keeps it in the class directory carrying that star category line.
    It must not be diverted into a .extension directory.'''
    working_copy = working_copy_over(tmp_path)
    working_copy.file_out_class(own_package_star_image(), 'Amount')
    package = os.path.join(str(tmp_path), 'Wonka-Amount-Core.package')
    assert read_text(
        os.path.join(package, 'Amount.class', 'instance', 'tripled.st')
    ) == '*Wonka-Amount-Core\ntripled\n\t^ number * 3'
    assert not os.path.exists(os.path.join(package, 'Amount.extension'))


def test_filing_out_a_category_files_out_each_of_its_classes(tmp_path):
    '''AI: Filing out a class category files out every class the image lists under it.'''
    working_copy = working_copy_over(tmp_path)
    working_copy.file_out_class_category(amount_image(), 'Wonka-Amount-Core')
    assert os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Amount-Core.package', 'Amount.class', 'properties.json'
        )
    )


def test_filing_out_a_single_method_writes_only_that_method(tmp_path):
    '''AI: Filing out one method writes exactly that method file.'''
    working_copy = working_copy_over(tmp_path)
    outcome = working_copy.file_out_method(amount_image(), 'Amount', 'doubled', False)
    assert outcome.action == 'wrote'
    assert outcome.path.endswith(
        os.path.join('Amount.class', 'instance', 'doubled.st')
    )


def test_filing_out_a_method_category_writes_its_methods(tmp_path):
    '''AI: Filing out a method category (protocol) writes the methods in that protocol.'''
    working_copy = working_copy_over(tmp_path)
    working_copy.file_out_method_category(amount_image(), 'Amount', 'arithmetic', False)
    assert os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
        )
    )


def test_file_out_without_a_repository_is_a_no_op(tmp_path):
    '''AI: With no repository configured, file-out does nothing rather than erroring.'''
    working_copy = MonticelloWorkingCopy(repository=None, enabled=False)
    outcome = working_copy.file_out_method(amount_image(), 'Amount', 'doubled', False)
    assert outcome.action == 'skipped'
