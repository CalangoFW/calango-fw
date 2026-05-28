import calango


def test_calango_version_is_defined():
    assert hasattr(calango, "__version__")
    assert isinstance(calango.__version__, str)
    assert len(calango.__version__) > 0
