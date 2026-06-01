'''AI: Tests for filing code in from disk into the image (disk -> image, full replace). The
image is a mutable stub recording compiles/deletes; the on-disk side is a real repository.
The crucial behaviour under test is the destructive part: code in the image that is absent
from disk is removed, while code owned by other packages is left alone.'''

import os

from reahl.swordfish.gemstone.filetree_sync import MonticelloRepository
from reahl.swordfish.gemstone.smalltalk_method_parser import (
    SmalltalkMethodParser,
    SmalltalkSyntaxError,
)
from reahl.swordfish.gemstone.working_copy import MonticelloWorkingCopy


class MutableImage:
    '''AI: A stand-in image that applies compiles/deletes to in-memory state and records the
    destructive calls so a test can assert exactly what was removed.'''

    def __init__(self, classes, methods, classes_by_category):
        self.classes = classes
        # AI: methods keyed by (class_name, show_instance_side) -> {selector: (protocol, source)}
        self.methods = methods
        self.classes_by_category = classes_by_category
        self.created_classes = []
        self.deleted_methods = []
        self.deleted_classes = []

    def mirrored_selector(self, source):
        try:
            return SmalltalkMethodParser().parse_method(source).selector
        except SmalltalkSyntaxError:
            return None

    def create_class(
        self,
        class_name,
        superclass_name='Object',
        inst_var_names=None,
        class_var_names=None,
        class_inst_var_names=None,
        pool_dictionary_names=None,
        in_dictionary='UserGlobals',
    ):
        self.created_classes.append(class_name)

    def compile_method(
        self, class_name, show_instance_side, source, method_category='unclassified'
    ):
        selector = self.mirrored_selector(source)
        self.methods.setdefault((class_name, show_instance_side), {})[selector] = (
            method_category,
            source,
        )

    def delete_method(self, class_name, selector, show_instance_side):
        self.deleted_methods.append((class_name, selector, show_instance_side))
        self.methods.get((class_name, show_instance_side), {}).pop(selector, None)

    def delete_class(self, class_name, in_dictionary='UserGlobals'):
        self.deleted_classes.append(class_name)

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

    def get_class_definition(self, class_name):
        return self.classes[class_name]

    def list_classes_in_category(self, class_category):
        return list(self.classes_by_category.get(class_category, []))


def amount_definition():
    return {
        'class_name': 'Amount',
        'superclass_name': 'Number',
        'package_name': 'Wonka-Amount-Core',
        'inst_var_names': ['number'],
        'class_var_names': [],
        'class_inst_var_names': [],
        'pool_dictionary_names': [],
    }


def disk_with_amount(tmp_path):
    '''AI: A repository on disk holding Wonka-Amount-Core with one Amount instance method.'''
    repository = MonticelloRepository(str(tmp_path))
    repository.ensure_package('Wonka-Amount-Core')
    repository.write_class_definition(
        'Wonka-Amount-Core',
        {
            'super': 'Number',
            'category': 'Wonka-Amount-Core',
            'classinstvars': [],
            'pools': [],
            'classvars': [],
            'instvars': ['number'],
            'name': 'Amount',
            'type': 'normal',
        },
    )
    repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', 'arithmetic',
        'doubled\n\t^ number * 2',
    )
    return repository


def image_diverged_from_disk():
    '''AI: An image where Amount has an outdated 'doubled', an image-only own method, an
    extension method owned by another package, plus an image-only class in the category.'''
    return MutableImage(
        classes={'Amount': amount_definition(), 'Ghost': {'class_name': 'Ghost'}},
        methods={
            ('Amount', True): {
                'doubled': ('arithmetic', 'doubled\n\t^ number'),
                'obsolete': ('arithmetic', 'obsolete\n\t^ 1'),
                'fromOther': ('*Wonka-Other-Core', 'fromOther\n\t^ 2'),
            }
        },
        classes_by_category={'Wonka-Amount-Core': ['Amount', 'Ghost']},
    )


def test_file_in_recompiles_disk_methods(tmp_path):
    '''AI: Filing in a package recompiles each method from its on-disk source, overwriting the
    image version.'''
    working_copy = MonticelloWorkingCopy(repository=disk_with_amount(tmp_path), enabled=False)
    image = image_diverged_from_disk()
    working_copy.file_in_package(image, 'Wonka-Amount-Core')
    assert image.methods[('Amount', True)]['doubled'] == (
        'arithmetic',
        'doubled\n\t^ number * 2',
    )
    assert 'Amount' in image.created_classes


def test_file_in_deletes_image_own_methods_absent_from_disk(tmp_path):
    '''AI: A class's own method that is not on disk is removed, so the image matches disk.'''
    working_copy = MonticelloWorkingCopy(repository=disk_with_amount(tmp_path), enabled=False)
    image = image_diverged_from_disk()
    working_copy.file_in_package(image, 'Wonka-Amount-Core')
    assert ('Amount', 'obsolete', True) in image.deleted_methods
    assert 'obsolete' not in image.methods[('Amount', True)]


def test_file_in_keeps_methods_owned_by_other_packages(tmp_path):
    '''AI: A full replace of one package must not delete an extension method that belongs to a
    different package, even though it lives on the same class.'''
    working_copy = MonticelloWorkingCopy(repository=disk_with_amount(tmp_path), enabled=False)
    image = image_diverged_from_disk()
    working_copy.file_in_package(image, 'Wonka-Amount-Core')
    assert 'fromOther' in image.methods[('Amount', True)]


def test_file_in_deletes_image_only_classes_in_the_package(tmp_path):
    '''AI: A class in the package's category that is absent from disk is removed.'''
    working_copy = MonticelloWorkingCopy(repository=disk_with_amount(tmp_path), enabled=False)
    image = image_diverged_from_disk()
    working_copy.file_in_package(image, 'Wonka-Amount-Core')
    assert 'Ghost' in image.deleted_classes


def test_file_in_single_method_removes_it_when_absent_from_disk(tmp_path):
    '''AI: Filing in a single method that is not on disk deletes it from the image - the
    single-method scope of 'match disk'.'''
    working_copy = MonticelloWorkingCopy(repository=disk_with_amount(tmp_path), enabled=False)
    image = image_diverged_from_disk()
    outcome = working_copy.file_in_method(image, 'Amount', 'obsolete', False)
    assert outcome.action == 'removed'
    assert ('Amount', 'obsolete', True) in image.deleted_methods


def test_file_in_single_method_compiles_it_when_present(tmp_path):
    '''AI: Filing in a single method that is on disk recompiles it from disk.'''
    working_copy = MonticelloWorkingCopy(repository=disk_with_amount(tmp_path), enabled=False)
    image = image_diverged_from_disk()
    outcome = working_copy.file_in_method(image, 'Amount', 'doubled', False)
    assert outcome.action == 'loaded'
    assert image.methods[('Amount', True)]['doubled'][1] == 'doubled\n\t^ number * 2'


def test_file_in_without_a_repository_is_a_no_op(tmp_path):
    '''AI: With no repository configured, file-in does nothing.'''
    working_copy = MonticelloWorkingCopy(repository=None, enabled=False)
    outcome = working_copy.file_in_everything(image_diverged_from_disk())
    assert outcome.action == 'skipped'
