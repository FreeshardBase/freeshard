from cryptography import exceptions
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import OFB

from portal_core.service import human_encoding


class PublicKey:
	key: RSAPublicKey

	def __init__(self, input_):
		if isinstance(input_, RSAPublicKey):
			self.key = input_
		elif isinstance(input_, bytes):
			self.key = serialization.load_pem_public_key(input_)
		elif isinstance(input_, str):
			self.key = serialization.load_pem_public_key(input_.encode())

	def to_bytes(self) -> bytes:
		return self.key.public_bytes(
			serialization.Encoding.PEM,
			serialization.PublicFormat.SubjectPublicKeyInfo
		)

	def to_hash_id(self) -> str:
		digest = hashes.Hash(hashes.SHA512(), backend=default_backend())
		digest.update(self.to_bytes())
		return human_encoding.encode(digest.finalize())

	def verify_signature(self, signature: bytes, data: bytes):
		try:
			self.key.verify(
				signature,
				data,
				padding.PSS(
					mgf=padding.MGF1(hashes.SHA256()),
					salt_length=padding.PSS.MAX_LENGTH
				),
				hashes.SHA256()
			)
		except exceptions.InvalidSignature as e:
			raise InvalidSignature from e


class PrivateKey:
	key: RSAPrivateKey

	def __init__(self, input_=None):
		if input_ is None:
			self.key = rsa.generate_private_key(
				public_exponent=65537,
				key_size=4096,
			)
		elif isinstance(input_, RSAPrivateKey):
			self.key = input_
		elif isinstance(input_, bytes):
			self.key = serialization.load_pem_private_key(input_, password=None)
		elif isinstance(input_, str):
			self.key = serialization.load_pem_private_key(input_.encode(), password=None)
		else:
			raise TypeError('Expected one of None, RSAPrivateKey, bytes, str')

	def to_bytes(self) -> bytes:
		return self.key.private_bytes(
			serialization.Encoding.PEM,
			serialization.PrivateFormat.PKCS8,
			serialization.NoEncryption()
		)

	def get_public_key(self) -> PublicKey:
		return PublicKey(self.key.public_key())

	def sign_data(self, data: bytes):
		return self.key.sign(data, padding.PSS(
			mgf=padding.MGF1(hashes.SHA256()),
			salt_length=padding.PSS.MAX_LENGTH
		), hashes.SHA256())


class InvalidSignature(Exception):
	pass


def aes_encrypt(data: bytes, key: bytes, iv: bytes):
	encryptor = Cipher(AES(key), OFB(iv), backend=default_backend()).encryptor()
	return encryptor.update(data) + encryptor.finalize()


def aes_decrypt(data: bytes, key: bytes, iv: bytes):
	decryptor = Cipher(AES(key), OFB(iv), backend=default_backend()).decryptor()
	return decryptor.update(data) + decryptor.finalize()
