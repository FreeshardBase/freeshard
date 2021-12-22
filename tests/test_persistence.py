import pytest

from identity_handler import persistence

pytestmark = pytest.mark.usefixtures('init_db')


def test_creation_with_description():
	i = persistence.create_identity('id_name', 'some description')
	assert i.name == 'id_name'
	assert i.description == 'some description'


def test_creation_without_description():
	i = persistence.create_identity('id_name')
	assert i.name == 'id_name'
	assert i.description is None


def test_creation_duplicate_name():
	persistence.create_identity('dup_name')
	with pytest.raises(persistence.IdentityAlreadyExists):
		persistence.create_identity('dup_name')


def test_find_by_hash_full():
	i1 = persistence.create_identity('id_name')
	i2 = persistence.find_identity_by_id(i1.id)
	assert i1 == i2


def test_find_by_hash_partial():
	i1 = persistence.create_identity('id_name')
	i2 = persistence.find_identity_by_id(i1.id[:16])
	assert i1 == i2


def test_find_by_hash_short():
	i1 = persistence.create_identity('id_name')
	with pytest.raises(ValueError):
		persistence.find_identity_by_id(i1.id[:2])


def test_find_by_hash_unknown():
	i1 = persistence.create_identity('id_name')
	with pytest.raises(KeyError):
		persistence.find_identity_by_id('x' * 16)


def test_find_by_name():
	i1 = persistence.create_identity('id_name')
	i2 = persistence.find_identity_by_name('id_name')
	assert i1 == i2


def test_find_by_name_unknown():
	i1 = persistence.create_identity('id_name')
	with pytest.raises(KeyError):
		persistence.find_identity_by_name('id_name_unknown')


def test_make_default():
	i1 = persistence.create_identity('i1')
	i2 = persistence.create_identity('i2')
	assert not i1.is_default
	assert not i2.is_default

	persistence.make_identity_default(i1)
	i1 = persistence.find_identity_by_id(i1.id)
	i2 = persistence.find_identity_by_id(i2.id)
	assert i1.is_default
	assert not i2.is_default
	assert persistence.get_default_identity() == i1

	persistence.make_identity_default(i2)
	i1 = persistence.find_identity_by_id(i1.id)
	i2 = persistence.find_identity_by_id(i2.id)
	assert not i1.is_default
	assert i2.is_default
	assert persistence.get_default_identity() == i2
