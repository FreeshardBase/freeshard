import pytz
import sqlalchemy.types as types

UTC = pytz.timezone('UTC')

class UTCTimestamp(types.TypeDecorator):
    # https://stackoverflow.com/questions/78767971/why-does-timezone-not-work-in-sqlmodel

    impl = types.TIMESTAMP(timezone=True)

    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            assert value.tzinfo is not None
            if dialect.name == 'sqlite':
                # we provide a UTC timezone, but it will get dropped by sqlite
                return value.astimezone(pytz.utc)
        else:
            # other dialects will be able to store the timezone
            return value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'sqlite':
            # we explictly store the value as UTC for sqlite, but it
            # has dropped the timezone and we have a naive datetime.
            # So make it timezone aware and convert to the desired
            # timezone.
            assert value.tzinfo is None
            return UTC.fromutc(value)
        else:
            # other dialects will keep the timezone, and some will
            # even convert it to your local timezone depending on your
            # connection settings.
            assert value.tzinfo is not None
            return value.astimezone(UTC)
