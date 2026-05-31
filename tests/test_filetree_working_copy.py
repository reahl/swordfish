'''AI: Tests for how the in-image working copy maps each kind of edit onto the on-disk
repository, including the lazy drift report and the shared, persisted configuration that the
IDE and MCP server both read.'''

import json
import os

from reahl.swordfish.gemstone.filetree_sync import MonticelloRepository
from reahl.swordfish.gemstone.working_copy import (
    MonticelloWorkingCopy,
    current_working_copy,
    disable_working_copy,
    point_working_copy_at,
)


CYPRESS_CONFIG = (
    '{\n\t"separateMethodMetaAndSource" : false,\n'
    '\t"noMethodMetaData" : true,\n\t"useCypressPropertiesFile" : true\n}'
)


def repository_with_tracked_packages(tmp_path):
    '''AI: A repository whose tracked subset is two real package directories, one of which
    carries a Cypress .filetree so class-definition writes are permitted.'''
    root = str(tmp_path)
    amount_package = os.path.join(root, 'Wonka-Amount-Core.package')
    os.makedirs(amount_package)
    with open(os.path.join(amount_package, '.filetree'), 'w', encoding='utf-8') as config:
        config.write(CYPRESS_CONFIG)
    os.makedirs(os.path.join(root, 'Wonka-Entities-Core.package'))
    return MonticelloRepository(root)


def read_text(path):
    with open(path, 'r', encoding='utf-8', newline='') as text_file:
        return text_file.read()


def test_disabled_working_copy_writes_nothing(tmp_path):
    '''AI: With sync off, an edit is acknowledged as a no-op and touches no files.'''
    working_copy = MonticelloWorkingCopy(
        repository=repository_with_tracked_packages(tmp_path), enabled=False
    )
    outcome = working_copy.update_for_compiled_method(
        'Amount', 'doubled', False, 'arithmetic', 'Wonka-Amount-Core', None, 'doubled\n\t^ 1'
    )
    assert outcome.action == 'disabled'
    assert not os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
        )
    )


def test_tracked_instance_method_is_written_to_its_class_directory(tmp_path):
    '''AI: A normal method on a class owned by a tracked package lands under that class's
    instance directory, with its protocol on the first line.'''
    working_copy = MonticelloWorkingCopy(
        repository=repository_with_tracked_packages(tmp_path), enabled=True
    )
    outcome = working_copy.update_for_compiled_method(
        'Amount', 'doubled', False, 'arithmetic', 'Wonka-Amount-Core', None, 'doubled\n\t^ number * 2'
    )
    assert outcome.action == 'wrote'
    assert read_text(outcome.path) == 'arithmetic\ndoubled\n\t^ number * 2'


def test_extension_method_is_written_to_the_extension_directory(tmp_path):
    '''AI: A method whose protocol is '*Package' is an extension and is mirrored into that
    package's <Class>.extension directory with a canonical '*Package' category line - even
    though the class itself is owned elsewhere.'''
    working_copy = MonticelloWorkingCopy(
        repository=repository_with_tracked_packages(tmp_path), enabled=True
    )
    outcome = working_copy.update_for_compiled_method(
        'Float', 'asAmount', False, '*wonka-amount-core', 'Kernel-Numbers', None, 'asAmount\n\t^ self'
    )
    assert outcome.action == 'wrote'
    assert outcome.path.endswith(
        os.path.join('Wonka-Amount-Core.package', 'Float.extension', 'instance', 'asAmount.st')
    )
    assert read_text(outcome.path) == '*Wonka-Amount-Core\nasAmount\n\t^ self'


def test_method_in_untracked_package_is_skipped(tmp_path):
    '''AI: An edit to a class whose package is not on disk is silently out of scope.'''
    working_copy = MonticelloWorkingCopy(
        repository=repository_with_tracked_packages(tmp_path), enabled=True
    )
    outcome = working_copy.update_for_compiled_method(
        'Banana', 'peel', False, 'accessing', 'Some-Other-Package', None, 'peel\n\t^ self'
    )
    assert outcome.action == 'skipped'


def test_divergent_disk_source_is_reported_then_overwritten(tmp_path):
    '''AI: If the file we are about to overwrite no longer matches the image's pre-edit source,
    that divergence is reported (lazy drift detection) and the new version is still written.'''
    repository = repository_with_tracked_packages(tmp_path)
    repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', 'arithmetic',
        'doubled\n\t^ number + number',
    )
    working_copy = MonticelloWorkingCopy(repository=repository, enabled=True)
    outcome = working_copy.update_for_compiled_method(
        'Amount', 'doubled', False, 'arithmetic', 'Wonka-Amount-Core',
        'doubled\n\t^ number * 2', 'doubled\n\t^ number + number + number',
    )
    assert outcome.drift is not None
    assert read_text(outcome.path) == 'arithmetic\ndoubled\n\t^ number + number + number'


def test_own_package_star_method_is_written_to_the_class_directory(tmp_path):
    '''AI: A '*Package' protocol naming the class's OWN defining package is not a cross-package
    extension: it is written into the class directory carrying that star category line, never a
    .extension directory - mirroring how Pharo files such a method.'''
    working_copy = MonticelloWorkingCopy(
        repository=repository_with_tracked_packages(tmp_path), enabled=True
    )
    outcome = working_copy.update_for_compiled_method(
        'Amount', 'doubled', False, '*Wonka-Amount-Core', 'Wonka-Amount-Core', None,
        'doubled\n\t^ number * 2',
    )
    assert outcome.action == 'wrote'
    assert outcome.path.endswith(
        os.path.join('Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st')
    )
    assert read_text(outcome.path) == '*Wonka-Amount-Core\ndoubled\n\t^ number * 2'


def test_recategorising_into_an_extension_removes_the_stale_class_file(tmp_path):
    '''AI: When a method's protocol moves it from its class directory into a FOREIGN package's
    extension, the recompile writes the new extension file and the stale class-directory file
    is removed.'''
    repository = repository_with_tracked_packages(tmp_path)
    # AI: the class-directory file is what existed before; the recompile has already written
    # the extension file (the compile hook does that), which we mimic here.
    repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', 'arithmetic', 'doubled\n\t^ 1',
    )
    repository.write_method(
        'Wonka-Entities-Core', 'Amount', False, True, 'doubled', '*Wonka-Entities-Core', 'doubled\n\t^ 1',
    )
    working_copy = MonticelloWorkingCopy(repository=repository, enabled=True)
    outcome = working_copy.remove_stale_after_recategorise(
        'Amount', 'doubled', False, 'arithmetic', '*Wonka-Entities-Core', 'Wonka-Amount-Core',
    )
    assert outcome.action == 'removed'
    assert not os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
        )
    )
    assert os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Entities-Core.package', 'Amount.extension', 'instance', 'doubled.st'
        )
    )


def test_recategorising_into_own_package_star_keeps_the_class_file(tmp_path):
    '''AI: Recategorising into a '*Package' protocol that names the class's OWN package does not
    move the file out of the class directory - it was never a foreign extension - so the
    class-directory file is kept rather than removed.'''
    repository = repository_with_tracked_packages(tmp_path)
    repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', '*Wonka-Amount-Core', 'doubled\n\t^ 1',
    )
    working_copy = MonticelloWorkingCopy(repository=repository, enabled=True)
    outcome = working_copy.remove_stale_after_recategorise(
        'Amount', 'doubled', False, 'arithmetic', '*Wonka-Amount-Core', 'Wonka-Amount-Core',
    )
    assert outcome.action == 'skipped'
    assert os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
        )
    )


def test_recategorising_within_the_same_location_keeps_the_file(tmp_path):
    '''AI: A protocol change that does not move the file (e.g. one ordinary protocol to
    another) must not delete the file the recompile just rewrote.'''
    repository = repository_with_tracked_packages(tmp_path)
    repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', 'computing', 'doubled\n\t^ 1',
    )
    working_copy = MonticelloWorkingCopy(repository=repository, enabled=True)
    outcome = working_copy.remove_stale_after_recategorise(
        'Amount', 'doubled', False, 'arithmetic', 'computing', 'Wonka-Amount-Core',
    )
    assert outcome.action == 'skipped'
    assert os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
        )
    )


def test_removing_a_tracked_method_deletes_its_file(tmp_path):
    '''AI: Removing a method removes its mirrored file.'''
    repository = repository_with_tracked_packages(tmp_path)
    repository.write_method(
        'Wonka-Amount-Core', 'Amount', False, False, 'doubled', 'arithmetic', 'doubled\n\t^ 1',
    )
    working_copy = MonticelloWorkingCopy(repository=repository, enabled=True)
    outcome = working_copy.update_for_removed_method(
        'Amount', 'doubled', False, 'arithmetic', 'Wonka-Amount-Core'
    )
    assert outcome.action == 'removed'
    assert not os.path.exists(
        os.path.join(
            str(tmp_path), 'Wonka-Amount-Core.package', 'Amount.class', 'instance', 'doubled.st'
        )
    )


def test_configuration_is_persisted_and_shared(tmp_path, monkeypatch):
    '''AI: Pointing the working copy at a repository persists to the shared config file, so a
    fresh read (as another process would do) sees the same enabled repository; disabling
    turns it off while remembering the path.'''
    config_path = os.path.join(str(tmp_path), 'config', 'filetree_sync.json')
    monkeypatch.setenv('SWORDFISH_FILETREE_SYNC_CONFIG', config_path)
    repository_root = os.path.join(str(tmp_path), 'repo')
    os.makedirs(repository_root)

    point_working_copy_at(repository_root)
    reloaded = current_working_copy()
    assert reloaded.active
    assert reloaded.repository.root_path == repository_root

    disable_working_copy()
    after_disable = current_working_copy()
    assert not after_disable.active
    persisted = json.loads(read_text(config_path))
    assert persisted['root_path'] == repository_root
    assert persisted['enabled'] is False
