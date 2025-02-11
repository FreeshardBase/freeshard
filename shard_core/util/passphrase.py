import secrets
from pathlib import Path
from typing import List


def generate_passphrase_numbers(length=6):
	phrase_numbers = []
	for i in range(length):
		number = ''
		for j in range(5):
			number += secrets.choice('123456')
		phrase_numbers.append(number)
	return phrase_numbers


def get_passphrase(phrase_numbers: List[str]):
	words = []
	with open(Path.cwd() / 'data' / 'eff_large_wordlist.txt', 'r') as f:
		for number in phrase_numbers:
			for line in f:
				if line.startswith(number):
					words.append(line.split()[1])
					break
			else:
				raise ValueError(f'Number {number} not found in wordlist')
			f.seek(0)
	return ' '.join(words)
