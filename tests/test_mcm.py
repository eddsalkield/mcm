from mcm import __version__
import pathlib

def test_version():
    print('#############')
    print(pathlib.Path.cwd())
    assert __version__ == '0.0.2'
