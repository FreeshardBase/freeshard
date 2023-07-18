import time

from portal_core.util.misc import throttle


def test_throttle_once():
	@throttle(0.1)
	def call_me():
		return "called"

	assert call_me() == "called"


def test_throttle_twice():
	@throttle(0.1)
	def call_me():
		return "called"

	assert call_me() == "called"
	assert call_me() is None


def test_throttle_with_delay():
	@throttle(0.1)
	def call_me():
		return "called"

	assert call_me() == "called"
	time.sleep(0.2)
	assert call_me() == "called"
