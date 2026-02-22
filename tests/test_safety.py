from radsim.safety import is_extension_safe, is_path_safe


def test_is_path_safe():
    # Safe paths
    assert is_path_safe("src/utils.py")[0] is True
    assert is_path_safe("README.md")[0] is True

    # Unsafe paths
    assert is_path_safe(".env")[0] is False
    assert is_path_safe("secrets/keys.txt")[0] is False
    assert is_path_safe("path/to/id_rsa")[0] is False


def test_is_extension_safe():
    # Safe extensions
    assert is_extension_safe("test.py")[0] is True
    assert is_extension_safe("style.css")[0] is True
    assert is_extension_safe("Makefile")[0] is True

    # Unsafe/uncommon extensions
    assert is_extension_safe("data.exe")[0] is False
    assert is_extension_safe("image.psd")[0] is False
