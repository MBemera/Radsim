"""Compatibility wrappers for the canonical tool-layer file operations."""

from .tools import directory_ops as _directory_ops
from .tools import file_ops as _file_ops
from .tools import validation as _validation

create_directory = _directory_ops.create_directory
list_directory = _directory_ops.list_directory
delete_file = _file_ops.delete_file
read_file = _file_ops.read_file
read_many_files = _file_ops.read_many_files
rename_file = _file_ops.rename_file
replace_in_file = _file_ops.replace_in_file
write_file = _file_ops.write_file
is_protected_path = _validation.is_protected_path
validate_path = _validation.validate_path
clear_path_validation_cache = _validation.clear_path_validation_cache


def clear_cwd_cache():
    """Backward-compatible alias for the shared validation cache clear."""
    clear_path_validation_cache()
