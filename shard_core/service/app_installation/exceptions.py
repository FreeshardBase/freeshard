class AppAlreadyInstalled(Exception):
    pass


class AppDoesNotExist(Exception):
    pass


class AppNotInstalled(Exception):
    pass


class AppInIllegalStatus(Exception):
    pass


class InvalidAppZip(Exception):
    pass
