import os

import pytest

from portal_core.service import crypto


def test_sign():
	private_key = crypto.PrivateKey()
	public_key = private_key.get_public_key()
	data = b'test data'
	signature = private_key.sign_data(data)
	public_key.verify_signature(signature, data)


def test_sign_invalid():
	private_key = crypto.PrivateKey()
	public_key = private_key.get_public_key()
	data0 = b'test data'
	data1 = b'test data invalid'
	signature = private_key.sign_data(data0)
	with pytest.raises(crypto.InvalidSignature):
		public_key.verify_signature(signature, data1)


def test_aes():
	input_value = b'foo bar'
	key = os.urandom(32)
	iv = os.urandom(16)
	ciphertext = crypto.aes_encrypt(input_value, key, iv)
	output_value = crypto.aes_decrypt(ciphertext, key, iv)
	assert input_value == output_value


def test_serialization():
	private_key = crypto.PrivateKey()
	public_key = private_key.get_public_key()
	bytes_ = public_key.to_bytes()
	assert '-BEGIN PUBLIC KEY-' in bytes_.decode()
	pubkey_from_bytes = crypto.PublicKey(bytes_)
	assert pubkey_from_bytes.to_hash_id() == public_key.to_hash_id()
