import logging
import random
from itertools import zip_longest
from math import floor, log2

from bitstring import BitArray

log = logging.getLogger(__name__)

bits_to_char = dict()
char_to_bits = dict()
bits_per_char = 0


def init(characters: str):
	if len(characters) != len(set(characters)):
		raise InitializationError('characters must be unique')

	reset()
	global bits_to_char, char_to_bits, bits_per_char

	original_length = len(characters)
	bits_per_char = floor(log2(original_length))
	usable_length = 2 ** bits_per_char
	usable_chars = characters[:usable_length]

	log.debug(f'human encoding is using {bits_per_char} bits per character')
	if usable_length < original_length:
		log.warning(f'human encoding only uses {usable_length} of {original_length} provided characters')

	for number, char in enumerate(usable_chars):
		bits = BitArray(uint=number, length=bits_per_char).bin
		bits_to_char[bits] = char
		char_to_bits[char] = bits


def reset():
	global bits_to_char, char_to_bits, bits_per_char
	bits_to_char, char_to_bits, bits_per_char = dict(), dict(), 0


def encode(b: bytes) -> str:
	if bits_per_char == 0:
		raise NotInitialized

	in_ = BitArray(bytes=b)
	out_ = ''
	for g in _grouper(in_.bin, n=bits_per_char, fillvalue='0'):
		bits = ''.join(g)
		out_ += bits_to_char[bits]
	return out_


def decode(s: str) -> bytes:
	if bits_per_char == 0:
		raise NotInitialized

	bits = ''
	for char in s:
		bits += char_to_bits[char]

	overhang = len(bits) % 8
	if overhang > 0:
		if not all(c == '0' for c in bits[-overhang:]):
			raise DecodingError(f'overhang is {bits[-overhang:]}, expected {"0" * overhang}')
		return BitArray('0b' + bits[:-overhang]).bytes
	else:
		return BitArray('0b' + bits).bytes


def random_string(length: int) -> str:
	return ''.join(random.choices(list(char_to_bits.keys()), k=length))


def _grouper(iterable, n, fillvalue=None):
	"""Collect data into fixed-length chunks or blocks"""
	# grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx"
	args = [iter(iterable)] * n
	return zip_longest(*args, fillvalue=fillvalue)


class HumanEncodingError(Exception):
	pass


class NotInitialized(HumanEncodingError):
	pass


class InitializationError(HumanEncodingError):
	pass


class DecodingError(HumanEncodingError):
	pass


init('abcdefghjklnpqrstvwxyz0123456789')
